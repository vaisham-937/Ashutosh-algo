# app/trade_engine.py
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Literal, List, Tuple

from kiteconnect import KiteConnect

from .redis_store import RedisStore
from .stock_sector import STOCK_INDEX_MAPPING

Side = Literal["BUY", "SELL"]
Product = Literal["MIS", "CNC"]
QtyMode = Literal["QTY", "CAPITAL"]


@dataclass
class AlertConfig:
    alert_name: str
    enabled: bool = True

    # trade direction decided by user for this alert
    direction: Literal["LONG", "SHORT"] = "LONG"   # LONG -> BUY, SHORT -> SELL
    product: Product = "MIS"                      # MIS or CNC

    qty_mode: QtyMode = "CAPITAL"
    capital: float = 20000.0
    qty: int = 1

    # MIS monitoring
    target_pct: float = 1.0
    stop_loss_pct: float = 0.7
    trailing_sl_pct: float = 0.5

    trade_limit_per_day: int = 3

    # sector filter
    sector_filter_on: bool = False
    top_n_sector: int = 2  # e.g. top 2 gainers for LONG, top 2 losers for SHORT

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AlertConfig":
        return AlertConfig(
            alert_name=str(d.get("alert_name") or d.get("name") or "UNKNOWN").strip(),
            enabled=bool(d.get("enabled", True)),
            direction=str(d.get("direction", "LONG")).upper(),
            product=str(d.get("product", "MIS")).upper(),
            qty_mode=str(d.get("qty_mode", "CAPITAL")).upper(),
            capital=float(d.get("capital", 20000.0)),
            qty=int(d.get("qty", 1)),
            target_pct=float(d.get("target_pct", 1.0)),
            stop_loss_pct=float(d.get("stop_loss_pct", 0.7)),
            trailing_sl_pct=float(d.get("trailing_sl_pct", 0.5)),
            trade_limit_per_day=int(d.get("trade_limit_per_day", 3)),
            sector_filter_on=bool(d.get("sector_filter_on", False)),
            top_n_sector=int(d.get("top_n_sector", 2)),
        )


@dataclass
class Position:
    trade_id: str
    user_id: int
    symbol: str
    alert_name: str

    side: Side
    product: Product
    qty: int

    entry_price: float
    entry_order_id: str = ""

    # monitoring (MIS only)
    target_price: float = 0.0
    sl_price: float = 0.0
    tsl_pct: float = 0.0
    highest: float = 0.0   # for BUY
    lowest: float = 0.0    # for SELL

    status: Literal["OPEN", "EXITING", "CLOSED", "REJECTED", "ERROR"] = "OPEN"
    exit_reason: str = ""
    exit_order_id: str = ""
    created_ts: float = 0.0
    updated_ts: float = 0.0

    ltp: float = 0.0
    pnl: float = 0.0

    def to_public(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


class OrderWorker:
    def __init__(self) -> None:
        self.q: "asyncio.Queue[Tuple[asyncio.Future, Any, Dict[str, Any]]]" = asyncio.Queue()
        self.task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self.task:
            return
        self.task = asyncio.create_task(self._run(), name="order_worker")

    async def submit(self, fn, **kwargs):
        fut = asyncio.get_running_loop().create_future()
        await self.q.put((fut, fn, kwargs))
        return await fut

    async def _run(self):
        while True:
            fut, fn, kwargs = await self.q.get()
            try:
                res = await asyncio.to_thread(fn, **kwargs)
                if not fut.cancelled():
                    fut.set_result(res)
            except Exception as e:
                if not fut.cancelled():
                    fut.set_exception(e)


class TradeEngine:
    """
    Ultra-low latency:
    - on_tick: in-memory monitoring only
    - Redis only for: Lua locks + trade-limit + snapshots
    """

    def __init__(self, user_id: int, store: RedisStore) -> None:
        self.user_id = int(user_id)
        self.store = store

        self.api_key = ""
        self.access_token = ""

        self.ticks: Dict[str, Dict[str, float]] = {}  # symbol -> {ltp, close, high, low}
        self.positions: Dict[str, Position] = {}      # symbol -> Position

        # sector perf (incremental)
        self.sym_sector: Dict[str, str] = STOCK_INDEX_MAPPING
        self.sym_pct: Dict[str, float] = {}           # symbol -> pct change
        self.sector_sum: Dict[str, float] = {}
        self.sector_cnt: Dict[str, int] = {}

        self.order_worker = OrderWorker()

    async def configure_kite(self) -> None:
        creds = await self.store.load_credentials(self.user_id)
        self.api_key = creds.get("api_key", "")
        self.access_token = await self.store.load_access_token(self.user_id)

        await self.order_worker.start()

    # ---------------- sector ranking ----------------
    def _update_sector_perf(self, symbol: str, pct: float) -> None:
        sec = self.sym_sector.get(symbol)
        if not sec:
            return
        old = self.sym_pct.get(symbol)
        if old is None:
            self.sym_pct[symbol] = pct
            self.sector_sum[sec] = self.sector_sum.get(sec, 0.0) + pct
            self.sector_cnt[sec] = self.sector_cnt.get(sec, 0) + 1
            return

        # adjust sum with delta
        self.sym_pct[symbol] = pct
        self.sector_sum[sec] = self.sector_sum.get(sec, 0.0) + (pct - old)

    def get_sector_rank(self) -> List[Tuple[str, float]]:
        # compute averages (small #sectors)
        out = []
        for sec, ssum in self.sector_sum.items():
            cnt = self.sector_cnt.get(sec, 0)
            if cnt > 0:
                out.append((sec, ssum / cnt))
        out.sort(key=lambda x: x[1], reverse=True)
        return out

    def _sector_allows(self, symbol: str, cfg: AlertConfig) -> bool:
        if not cfg.sector_filter_on:
            return True

        sec = self.sym_sector.get(symbol)
        if not sec:
            # requested: if sector not available -> process directly
            return True

        ranked = self.get_sector_rank()
        if not ranked:
            return True

        topn = max(1, int(cfg.top_n_sector))
        top_gainers = {s for s, _ in ranked[:topn]}
        top_losers = {s for s, _ in ranked[-topn:]}

        if cfg.direction == "LONG":
            return sec in top_gainers
        else:
            return sec in top_losers

    # ---------------- qty ----------------
    def _calc_qty(self, cfg: AlertConfig, ltp: float) -> int:
        if ltp <= 0:
            return 0
        if cfg.qty_mode == "QTY":
            return max(1, int(cfg.qty))
        # CAPITAL
        return max(1, int(cfg.capital // ltp))

    # ---------------- order placement ----------------
    def _kite(self) -> KiteConnect:
        if not self.api_key or not self.access_token:
            raise RuntimeError("Kite not connected")
        kite = KiteConnect(api_key=self.api_key)
        kite.set_access_token(self.access_token)
        return kite

    async def _place_order(self, symbol: str, side: Side, qty: int, product: Product) -> str:
        def _place(api_key: str, access_token: str, sym: str, s: Side, q: int, prod: Product) -> str:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            return kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=kite.EXCHANGE_NSE,
                tradingsymbol=sym,
                transaction_type=(kite.TRANSACTION_TYPE_BUY if s == "BUY" else kite.TRANSACTION_TYPE_SELL),
                quantity=int(q),
                product=(kite.PRODUCT_MIS if prod == "MIS" else kite.PRODUCT_CNC),
                order_type=kite.ORDER_TYPE_MARKET,
            )
        oid = await self.order_worker.submit(
            _place,
            api_key=self.api_key,
            access_token=self.access_token,
            sym=symbol,
            s=side,
            q=qty,
            prod=product,
        )
        return str(oid)

    # ---------------- ALERT processing ----------------
    async def on_chartink_alert(self, alert_name: str, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        Called by webhook.
        Returns per-symbol results.
        """
        out = []
        if await self.store.is_kill(self.user_id):
            for s in symbols:
                out.append({"symbol": s, "status": "REJECTED", "reason": "KILL_SWITCH"})
            return out

        cfg_raw = await self.store.get_alert_config(self.user_id, alert_name)
        if not cfg_raw:
            for s in symbols:
                out.append({"symbol": s, "status": "SKIPPED", "reason": "NO_CONFIG"})
            return out

        cfg = AlertConfig.from_dict(cfg_raw)
        if not cfg.enabled:
            for s in symbols:
                out.append({"symbol": s, "status": "SKIPPED", "reason": "CFG_DISABLED"})
            return out

        # trade limit (atomic in Redis)
        allowed = await self.store.allow_trade(self.user_id, alert_name, cfg.trade_limit_per_day)
        if not allowed:
            for s in symbols:
                out.append({"symbol": s, "status": "SKIPPED", "reason": "TRADE_LIMIT"})
            return out

        for sym in symbols:
            sym = sym.strip().upper()
            if not sym:
                continue
            r = await self._try_enter(sym, alert_name, cfg)
            out.append(r)

        return out

    async def _try_enter(self, symbol: str, alert_name: str, cfg: AlertConfig) -> Dict[str, Any]:
        # sector filter
        if not self._sector_allows(symbol, cfg):
            return {"symbol": symbol, "status": "SKIPPED", "reason": "SECTOR_FILTER"}

        # already open?
        if symbol in self.positions and self.positions[symbol].status == "OPEN":
            return {"symbol": symbol, "status": "SKIPPED", "reason": "ALREADY_OPEN"}

        # Redis open guard (cross-process safety)
        if await self.store.get_open(self.user_id, symbol):
            return {"symbol": symbol, "status": "SKIPPED", "reason": "ALREADY_OPEN_REDIS"}

        # lock entry
        lk = await self.store.acquire_lock(self.user_id, symbol, "entry", ttl_ms=1200)
        if lk != 1:
            return {"symbol": symbol, "status": "SKIPPED", "reason": ("KILL" if lk == -2 else "ENTRY_LOCK_BUSY")}

        # determine side/product
        side: Side = "BUY" if cfg.direction == "LONG" else "SELL"
        product: Product = cfg.product

        # CNC short not allowed
        if product == "CNC" and side == "SELL":
            return {"symbol": symbol, "status": "REJECTED", "reason": "CNC_SHORT_NOT_ALLOWED"}

        tick = self.ticks.get(symbol, {})
        ltp = float(tick.get("ltp", 0.0))
        if ltp <= 0:
            return {"symbol": symbol, "status": "SKIPPED", "reason": "NO_LTP_YET"}

        qty = self._calc_qty(cfg, ltp)
        if qty <= 0:
            return {"symbol": symbol, "status": "REJECTED", "reason": "BAD_QTY"}

        trade_id = uuid.uuid4().hex[:12]
        pos = Position(
            trade_id=trade_id,
            user_id=self.user_id,
            symbol=symbol,
            alert_name=alert_name,
            side=side,
            product=product,
            qty=qty,
            entry_price=ltp,
            created_ts=time.time(),
            updated_ts=time.time(),
        )

        # MIS monitoring setup
        if product == "MIS":
            if side == "BUY":
                pos.target_price = ltp * (1.0 + cfg.target_pct / 100.0)
                pos.sl_price = ltp * (1.0 - cfg.stop_loss_pct / 100.0)
                pos.highest = ltp
            else:
                pos.target_price = ltp * (1.0 - cfg.target_pct / 100.0)
                pos.sl_price = ltp * (1.0 + cfg.stop_loss_pct / 100.0)
                pos.lowest = ltp
            pos.tsl_pct = float(cfg.trailing_sl_pct)

        # mark open in Redis before order (race safe)
        await self.store.mark_open(self.user_id, symbol, trade_id)

        try:
            oid = await self._place_order(symbol, side, qty, product)
            pos.entry_order_id = oid
            self.positions[symbol] = pos
            await self.store.upsert_position(self.user_id, symbol, pos.to_public())
            return {"symbol": symbol, "status": "ENTERED", "trade_id": trade_id, "order_id": oid, "qty": qty, "side": side, "product": product}
        except Exception as e:
            pos.status = "ERROR"
            pos.exit_reason = f"ORDER_FAIL:{e}"
            await self.store.clear_open(self.user_id, symbol)
            await self.store.delete_position(self.user_id, symbol)
            return {"symbol": symbol, "status": "ERROR", "reason": str(e)}

    # ---------------- Tick ingestion + monitoring ----------------
    async def on_tick(self, symbol: str, ltp: float, close: float, high: float, low: float, tbq: float = 0.0, tsq: float = 0.0) -> Optional[Position]:
        """
        Hot path: in-memory only.
        Returns updated position if changed.
        """
        if ltp <= 0:
            return None

        self.ticks[symbol] = {"ltp": ltp, "close": close, "high": high, "low": low, "tbq": tbq, "tsq": tsq}

        # update sector perf fast
        if close > 0:
            pct = ((ltp - close) / close) * 100.0
            self._update_sector_perf(symbol, pct)

        pos = self.positions.get(symbol)
        if not pos or pos.status != "OPEN":
            return None

        # CNC: no monitoring
        if pos.product == "CNC":
            pos.ltp = ltp
            pos.updated_ts = time.time()
            pos.pnl = (ltp - pos.entry_price) * pos.qty if pos.side == "BUY" else (pos.entry_price - ltp) * pos.qty
            return pos

        # MIS monitoring
        pos.ltp = ltp
        pos.updated_ts = time.time()
        pos.pnl = (ltp - pos.entry_price) * pos.qty if pos.side == "BUY" else (pos.entry_price - ltp) * pos.qty

        # update extremes
        if pos.side == "BUY":
            pos.highest = max(pos.highest, ltp) if pos.highest else ltp
        else:
            pos.lowest = min(pos.lowest, ltp) if pos.lowest else ltp

        # exit conditions
        if pos.side == "BUY":
            if ltp >= pos.target_price > 0:
                await self._exit_position(symbol, "TARGET")
            elif ltp <= pos.sl_price > 0:
                await self._exit_position(symbol, "STOP_LOSS")
            elif pos.tsl_pct > 0 and pos.highest > 0:
                tsl = pos.highest * (1.0 - pos.tsl_pct / 100.0)
                if ltp <= tsl:
                    await self._exit_position(symbol, "TRAILING_SL")
        else:
            if ltp <= pos.target_price > 0:
                await self._exit_position(symbol, "TARGET")
            elif ltp >= pos.sl_price > 0:
                await self._exit_position(symbol, "STOP_LOSS")
            elif pos.tsl_pct > 0 and pos.lowest > 0:
                tsl = pos.lowest * (1.0 + pos.tsl_pct / 100.0)
                if ltp >= tsl:
                    await self._exit_position(symbol, "TRAILING_SL")

        return pos

    async def manual_squareoff(self, symbol: str, reason: str = "MANUAL") -> Dict[str, Any]:
        symbol = symbol.strip().upper()
        if not symbol:
            return {"error": "BAD_SYMBOL"}

        pos = self.positions.get(symbol)
        if not pos or pos.status != "OPEN":
            # try redis snapshot?
            return {"status": "NOT_OPEN"}

        await self._exit_position(symbol, reason)
        return {"status": "EXIT_SENT", "symbol": symbol, "reason": reason}

    async def _exit_position(self, symbol: str, reason: str) -> None:
        pos = self.positions.get(symbol)
        if not pos or pos.status != "OPEN":
            return

        # exit lock
        lk = await self.store.acquire_lock(self.user_id, symbol, "exit", ttl_ms=1500)
        if lk != 1:
            return

        pos.status = "EXITING"
        pos.exit_reason = reason
        await self.store.upsert_position(self.user_id, symbol, pos.to_public())

        exit_side: Side = "SELL" if pos.side == "BUY" else "BUY"
        try:
            oid = await self._place_order(symbol, exit_side, pos.qty, pos.product)
            pos.exit_order_id = oid
            pos.status = "CLOSED"
            await self.store.upsert_position(self.user_id, symbol, pos.to_public())
        finally:
            # clear open guard
            await self.store.clear_open(self.user_id, symbol)
            # keep snapshot for UI; you can delete if you want
            # await self.store.delete_position(self.user_id, symbol)
