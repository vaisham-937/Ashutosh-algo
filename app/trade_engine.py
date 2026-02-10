# app/trade_engine.py
from __future__ import annotations

import asyncio
import time
import uuid
import logging
import json
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Literal, List, Tuple
from dataclasses import fields as _dc_fields
from kiteconnect import KiteConnect  # type: ignore

# Keep dependencies intact (same modules you already use)
from .redis_store import RedisStore, norm_alert_name, norm_symbol
from .stock_sector import STOCK_INDEX_MAPPING
import os 
import re

log = logging.getLogger("trade_engine")

Side = Literal["BUY", "SELL"]
Product = Literal["MIS", "CNC"]
QtyMode = Literal["QTY", "CAPITAL"]


# =========================
# Normalization (ONE SOURCE OF TRUTH)
# =========================
def normalize_alert_key(name: str) -> str:
    return norm_alert_name(name or "")


def _j(**k: Any) -> str:
    try:
        return json.dumps(k, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        return str(k)


def _fmt_pos(p: "Position") -> str:
    return (
        f"{p.symbol} | {p.side} {p.qty} {p.product} | "
        f"entry={p.entry_price:.2f} ltp={p.ltp:.2f} pnl={p.pnl:.2f} | "
        f"tgt={p.target_price:.2f} sl={p.sl_price:.2f} "
        f"hi={p.highest:.2f} lo={p.lowest:.2f} tsl%={p.tsl_pct:.2f}"
    )

# -----------------------------
# Color helpers (ANSI)
# -----------------------------
_NO_COLOR = bool(os.getenv("NO_COLOR", "").strip())

def _c(code: str, s: str) -> str:
    if _NO_COLOR:
        return s
    return f"\x1b[{code}m{s}\x1b[0m"

def _green(s: str) -> str: return _c("32", s)
def _red(s: str) -> str: return _c("31", s)
def _yellow(s: str) -> str: return _c("33", s)
def _cyan(s: str) -> str: return _c("36", s)
def _magenta(s: str) -> str: return _c("35", s)
def _bold(s: str) -> str: return _c("1", s)
def _dim(s: str) -> str: return _c("2", s)
def _bg_blue(s: str) -> str:
    return _c("1;37;44", s)

def _bg_yellow(s: str) -> str:
    return _c("1;30;43", s)


def _bg_magenta(s: str) -> str:
    return _c("1;37;45", s)


def _fmt_side(side: str) -> str:
    return _green(side) if side == "BUY" else _red(side)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def _vis_len(s: str) -> int:
    return len(_ANSI_RE.sub("", s))

def _pad(s: str, width: int) -> str:
    return s + (" " * max(0, width - _vis_len(s)))


def _fmt_pnl(pnl: float) -> str:
    if pnl > 0:
        return _green(f"{pnl:.2f}")
    if pnl < 0:
        return _red(f"{pnl:.2f}")
    return f"{pnl:.2f}"

def _fmt_pct(x: float) -> str:
    # positive green, negative red, near zero yellow
    if x > 0.05:
        return _green(f"{x:.2f}%")
    if x < -0.05:
        return _red(f"{x:.2f}%")
    return _yellow(f"{x:.2f}%")



def _safe_symbol(raw: str) -> str:
    """
    Manual-squareoff UI sometimes sends: NSE:SBIN, SBIN-EQ, etc.
    We keep norm_symbol as primary.
    """
    return norm_symbol(raw)


def _pct_dist(cur: float, ref: float) -> float:
    if ref == 0:
        return 0.0
    return ((cur - ref) / ref) * 100.0


def _is_within_entry_window(start_time: str, end_time: str) -> bool:
    """
    Check if current IST time is within the entry time window.
    
    Args:
        start_time: Entry start time in HH:MM format (e.g., "09:15")
        end_time: Entry end time in HH:MM format (e.g., "15:15")
    
    Returns:
        True if current time is within window, False otherwise
    """
    try:
        import pytz
        ist = pytz.timezone("Asia/Kolkata")
        now = datetime.now(ist)
        
        # Parse start and end times
        start_parts = start_time.strip().split(":")
        end_parts = end_time.strip().split(":")
        
        if len(start_parts) != 2 or len(end_parts) != 2:
            # Invalid format, allow by default
            return True
        
        start_hour, start_min = int(start_parts[0]), int(start_parts[1])
        end_hour, end_min = int(end_parts[0]), int(end_parts[1])
        
        # Create time objects for comparison
        current_minutes = now.hour * 60 + now.minute
        start_minutes = start_hour * 60 + start_min
        end_minutes = end_hour * 60 + end_min
        
        # Check if current time is within window
        return start_minutes <= current_minutes <= end_minutes
        
    except Exception as e:
        log.debug("TIME_WINDOW_CHECK_FAIL | err=%s", e)
        # On error, allow by default
        return True


# =========================
# Data models
# =========================
@dataclass
class AlertConfig:
    alert_name: str
    enabled: bool = True

    direction: Literal["LONG", "SHORT"] = "LONG"   # LONG->BUY, SHORT->SELL
    product: Product = "MIS"                       # MIS / CNC

    qty_mode: QtyMode = "CAPITAL"
    capital: float = 20000.0
    qty: int = 1

    # monitoring (MIS only)
    target_pct: float = 1.0
    stop_loss_pct: float = 0.7
    trailing_sl_pct: float = 0.5

    trade_limit_per_day: int = 5

    # sector filter
    sector_filter_on: bool = False
    top_n_sector: int = 2

    # entry time window (IST format HH:MM)
    entry_start_time: str = "09:15"
    entry_end_time: str = "15:15"

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AlertConfig":
        raw_name = str(d.get("alert_name") or d.get("name") or d.get("alert") or "UNKNOWN").strip()

        direction = str(d.get("direction", "LONG") or "LONG").strip().upper()
        if direction not in ("LONG", "SHORT"):
            direction = "LONG"

        p_raw = str(d.get("product", "MIS") or "MIS").strip().upper()
        if p_raw in ("CNC", "DELIVERY", "DEMAT", "CASH"):
            product: Product = "CNC"
        else:
            product = "MIS"

        qty_mode = str(d.get("qty_mode", "CAPITAL") or "CAPITAL").strip().upper()
        if qty_mode not in ("QTY", "CAPITAL"):
            qty_mode = "CAPITAL"

        return AlertConfig(
            alert_name=normalize_alert_key(raw_name),
            enabled=bool(d.get("enabled", True)),
            direction=direction,  # type: ignore[arg-type]
            product=product,
            qty_mode=qty_mode,  # type: ignore[arg-type]
            capital=float(d.get("capital", 20000.0) or 0.0),
            qty=int(d.get("qty", 1) or 1),
            target_pct=float(d.get("target_pct", 1.0) or 0.0),
            stop_loss_pct=float(d.get("stop_loss_pct", 0.7) or 0.0),
            trailing_sl_pct=float(d.get("trailing_sl_pct", 0.5) or 0.0),
            trade_limit_per_day=int(d.get("trade_limit_per_day", 3) or 0),
            sector_filter_on=bool(d.get("sector_filter_on", False)),
            top_n_sector=int(d.get("top_n_sector", 2) or 2),
            entry_start_time=str(d.get("entry_start_time", "09:15") or "09:15").strip(),
            entry_end_time=str(d.get("entry_end_time", "15:15") or "15:15").strip(),
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
    highest: float = 0.0
    lowest: float = 0.0

    status: Literal["OPEN", "EXIT_CONDITIONS_MET", "EXITING", "CLOSED", "REJECTED", "ERROR"] = "OPEN"
    exit_reason: str = ""
    exit_order_id: str = ""
    alert_time: str = ""
    created_ts: float = 0.0
    updated_ts: float = 0.0

    cfg_target_pct: float = 0.0
    cfg_sl_pct: float = 0.0
    cfg_tsl_pct: float = 0.0


    ltp: float = 0.0
    pnl: float = 0.0
    sector: str = ""  # Sector/index group the stock belongs to

    def to_public(self) -> Dict[str, Any]:
        return asdict(self)


# =========================
# Ultra-fast order worker
# =========================
class OrderWorker:
    """
    Single async queue that offloads blocking KiteConnect calls to threadpool.
    Prevents event-loop stalls.
    """

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


# =========================
# Trade Engine
# =========================
class TradeEngine:
    """
    Includes:
    - Unified alert-name normalization
    - Lazy ensure Zerodha connected
    - No REST LTP: waits for tick (CAPITAL mode)
    - mark_open AFTER successful order placement
    - Always releases locks
    - Exit de-bounced + lock-based safe exit
    - Rich monitoring logs: who is near/hit target/sl/tsl
    - Manual squareoff fixed (works even if inflight)
    """

    def __init__(self, user_id: int, store: RedisStore, broadcast_cb: Optional[Any] = None) -> None:
        self.user_id = int(user_id)
        self.store = store
        self.broadcast_cb = broadcast_cb

        self.api_key: str = ""
        self.access_token: str = ""

        self.ticks: Dict[str, Dict[str, float]] = {}
        self.positions: Dict[str, Position] = {}

        # sector perf (incremental)
        self.sym_sector: Dict[str, str] = dict(STOCK_INDEX_MAPPING)
        self.sym_pct: Dict[str, float] = {}
        self.sector_sum: Dict[str, float] = {}
        self.sector_cnt: Dict[str, int] = {}

        self.order_worker = OrderWorker()

        # exit guards
        self._exit_inflight: Dict[str, bool] = {}
        self._exit_signal_sent: Dict[str, bool] = {}
# entry reconciliation (avoid repeated REST calls)
        self._recon_inflight: Dict[str, bool] = {}
        # monitoring log controls
        self._mon_last_log: Dict[str, float] = {}
        self.monitor_log_interval_sec: float = 10.0   # per symbol

        # tick visibility (first tick log)
        self._first_tick_logged: Dict[str, bool] = {}
        
        # Sector ranking periodic log
        self._last_sector_rank_log: float = 0.0
        self.sector_rank_log_interval_sec: float = 30.0  # Log every 30 seconds

    # ---------------- broker setup ----------------
    async def configure_kite(self) -> None:
        creds = await self.store.load_credentials(self.user_id)
        api_key = (creds.get("api_key") or "").strip()

        token = ""
        try:
            token = (await self.store.load_access_token(self.user_id)).strip()
        except Exception:
            token = ""

        if not token:
            token = (creds.get("access_token") or "").strip()

        self.api_key = api_key
        self.access_token = token

        await self.order_worker.start()

        log.info(
            "🔑 CONFIGURE_KITE_READY | user=%s api_key_len=%s token_len=%s",
            self.user_id,
            len(self.api_key or ""),
            len(self.access_token or ""),
        )

    
    async def _ensure_kite_ready(self) -> bool:
        if self.api_key and self.access_token:
            return True
        try:
            await self.configure_kite()
        except Exception as e:
            log.error("❌ CONFIGURE_KITE_FAIL | user=%s err=%s", self.user_id, e)
            return False
        return bool(self.api_key and self.access_token)

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
            log.debug(
                "📊 SECTOR_TRACK_NEW | %s (%s) = %+.2f%% | Sector avg now: %+.2f%%",
                symbol, sec, pct, self.sector_sum[sec] / self.sector_cnt[sec]
            )
            return

        self.sym_pct[symbol] = pct
        self.sector_sum[sec] = self.sector_sum.get(sec, 0.0) + (pct - old)
        log.debug(
            "📊 SECTOR_UPDATE | %s (%s) = %+.2f%% (was %+.2f%%) | Sector avg: %+.2f%%",
            symbol, sec, pct, old, self.sector_sum[sec] / self.sector_cnt[sec]
        )

    def get_sector_rank(self) -> List[Tuple[str, float]]:
        out: List[Tuple[str, float]] = []
        for sec, ssum in self.sector_sum.items():
            cnt = self.sector_cnt.get(sec, 0)
            if cnt > 0:
                out.append((sec, ssum / cnt))
        out.sort(key=lambda x: x[1], reverse=True)
        return out

    def _sector_allows(self, symbol: str, cfg: AlertConfig) -> bool:
        if not cfg.sector_filter_on:
            return True

        # Debug: Show available sectors for this symbol
        sec = self.sym_sector.get(symbol)
        
        if not sec:
            # Try to help debug - show similar symbols
            available_symbols = [s for s in self.sym_sector.keys() if symbol.upper() in s.upper() or s.upper() in symbol.upper()]
            log.warning(
                "❌ SECTOR_UNKNOWN | symbol='%s' (not in STOCK_INDEX_MAPPING with %d stocks, REJECTING) | Similar: %s",
                symbol, len(self.sym_sector), available_symbols[:3] if available_symbols else "none"
            )
            return False  # STRICT: Reject unknown stocks when filter is ON

        ranked = self.get_sector_rank()
        if not ranked:
            log.info("ℹ️ SECTOR_NO_DATA | No sector data available yet, allowing all")
            return True

        topn = max(1, int(cfg.top_n_sector))
        top_gainers = {s for s, _ in ranked[:topn]}
        top_losers = {s for s, _ in ranked[-topn:]}

        # Log current sector rankings
        log.info(
            "\n" + "="*80 + "\n" +
            "📊 SECTOR RANKINGS (Top %d for %s)\n" % (topn, cfg.direction) +
            "="*80
        )
        
        if cfg.direction == "LONG":
            log.info("🔝 TOP %d GAINERS (ALLOWED for LONG):", topn)
            for i, (s, pct) in enumerate(ranked[:topn], 1):
                log.info("   %d. %s: %+.2f%%", i, s, pct)
            
            log.info("\n📉 BOTTOM SECTORS (REJECTED for LONG):")
            for i, (s, pct) in enumerate(ranked[topn:], topn+1):
                log.info("   %d. %s: %+.2f%%", i, s, pct)
        else:  # SHORT
            log.info("📉 BOTTOM %d LOSERS (ALLOWED for SHORT):", topn)
            for i, (s, pct) in enumerate(reversed(ranked[-topn:]), 1):
                log.info("   %d. %s: %+.2f%%", i, s, pct)
            
            log.info("\n🔝 TOP SECTORS (REJECTED for SHORT):")
            for i, (s, pct) in enumerate(reversed(ranked[:-topn]), 1):
                log.info("   %d. %s: %+.2f%%", i, s, pct)
        
        log.info("="*80)

        # Check if symbol's sector is in allowed list
        if cfg.direction == "LONG":
            allowed = sec in top_gainers
            sector_pct = next((pct for s, pct in ranked if s == sec), 0.0)
            
            if allowed:
                log.info(
                    "✅ SECTOR_PASS | symbol=%s sector=%s (%+.2f%%) | Rank in TOP %d gainers",
                    symbol, sec, sector_pct, topn
                )
            else:
                rank = next((i+1 for i, (s, _) in enumerate(ranked) if s == sec), 0)
                log.info(
                    "❌ SECTOR_REJECT | symbol=%s sector=%s (%+.2f%%) | Rank #%d (not in TOP %d)",
                    symbol, sec, sector_pct, rank, topn
                )
            return allowed
        else:  # SHORT
            allowed = sec in top_losers
            sector_pct = next((pct for s, pct in ranked if s == sec), 0.0)
            
            if allowed:
                log.info(
                    "✅ SECTOR_PASS | symbol=%s sector=%s (%+.2f%%) | Rank in BOTTOM %d losers",
                    symbol, sec, sector_pct, topn
                )
            else:
                rank = next((i+1 for i, (s, _) in enumerate(ranked) if s == sec), 0)
                log.info(
                    "❌ SECTOR_REJECT | symbol=%s sector=%s (%+.2f%%) | Rank #%d (not in BOTTOM %d)",
                    symbol, sec, sector_pct, rank, topn
                )
            return allowed

    # ---------------- qty helpers ----------------
    def _calc_qty(self, cfg: AlertConfig, ltp: float) -> int:
        if cfg.qty_mode == "QTY":
            return max(1, int(cfg.qty))
        if ltp <= 0:
            return 0
        return max(1, int(float(cfg.capital) // float(ltp)))

    async def _wait_for_ltp(self, symbol: str, timeout_sec: float = 0.30) -> float:
        end = time.time() + float(timeout_sec)
        while time.time() < end:
            tick = self.ticks.get(symbol)
            if tick:
                ltp = float(tick.get("ltp", 0.0))
                if ltp > 0:
                    return ltp
            await asyncio.sleep(0.05)
        return 0.0

    # ---------------- order placement ----------------
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
                validity=kite.VALIDITY_DAY,
            )

        try:
            oid = await self.order_worker.submit(
                _place,
                api_key=self.api_key,
                access_token=self.access_token,
                sym=symbol,
                s=side,
                q=int(qty),
                prod=product,
            )
            return str(oid)
        except Exception as e:
            # KILL SWITCH TRIGGER
            log.error("🔥 ORDER_FLAGS_KILL_SWITCH | user=%s sym=%s err=%s", self.user_id, symbol, e)
            await self.store.set_kill(self.user_id, True)
            raise e

    # ---------------- Zerodha order updates (ws) ----------------
    async def on_order_update(self, ou: Dict[str, Any]) -> None:
        """
        Zerodha websocket order updates -> set entry_price from average_price when entry fills.
        """
        try:
            await self._on_order_update_unsafe(ou)
        except Exception as e:
            log.exception("🔥 CRITICAL_ORDER_UPDATE_ERROR | user=%s err=%s", self.user_id, e)
            # Optional: Kill switch on order update error? Maybe not, as it might be parsing error.
            # But if it's critical, yes. Safe to just log for now unless it breaks state.
            pass

    async def _on_order_update_unsafe(self, ou: Dict[str, Any]) -> None:
        try:
            status = str(ou.get("status") or "").upper()
            order_id = str(ou.get("order_id") or "").strip()
            sym = norm_symbol(str(ou.get("tradingsymbol") or ""))
            avg = float(ou.get("average_price") or 0.0)
            filled_qty = int(ou.get("filled_quantity") or 0)
            txn = str(ou.get("transaction_type") or "").upper()

            if not order_id or not sym:
                return

            if status != "COMPLETE" or avg <= 0:
                return

            pos = self.positions.get(sym)
            if not pos:
                return

            # Entry fill
            if pos.entry_order_id == order_id:
                # ALWAYS update entry price on fill (slippage handling)
                old_entry = pos.entry_price
                pos.entry_price = float(avg)

                # ALWAYS recalculate levels based on actual fill price
                if pos.product == "MIS" and pos.entry_price > 0:
                    # Retrieve config % from stored values (you might need to ensure they are stored in pos)
                    # or fallback to current pos values if calculated.
                    # Best: use cfg_*_pct if available, else derive.
                    
                    # We stored cfg_*_pct in _try_enter, let's use them if available, else fallback
                    tgt_pct = getattr(pos, "cfg_target_pct", 0.0) or pos.target_pct
                    sl_pct = getattr(pos, "cfg_sl_pct", 0.0) or pos.stop_loss_pct
                    tsl_pct = getattr(pos, "cfg_tsl_pct", 0.0) or pos.trailing_sl_pct

                    if pos.side == "BUY":
                        pos.target_price = pos.entry_price * (1.0 + tgt_pct / 100.0)
                        pos.sl_price = pos.entry_price * (1.0 - sl_pct / 100.0)
                        pos.highest = pos.entry_price
                    else:
                        pos.target_price = pos.entry_price * (1.0 - tgt_pct / 100.0)
                        pos.sl_price = pos.entry_price * (1.0 + sl_pct / 100.0)
                        pos.lowest = pos.entry_price

                    pos.tsl_pct = tsl_pct

                pos.updated_ts = time.time()

                log.info(
                    "\n%s\n%s\n%s",
                    _bold(_green("✅ ENTRY_FILL_UPDATED")),
                    _dim(_j(user=self.user_id, symbol=sym, oid=order_id, txn=txn, filled=filled_qty, avg=avg)),
                    _dim(f"entry_adj: {old_entry:.2f} -> {pos.entry_price:.2f} | TGT: {pos.target_price:.2f} SL: {pos.sl_price:.2f}"),
                )
                try:
                    await self.store.upsert_position(self.user_id, sym, pos.to_public())
                except Exception:
                    pass

            # Exit fill (nice log)
            if pos.exit_order_id == order_id:
                log.info(
                    "\n%s\n%s",
                    _bold(_green("✅ EXIT_FILL")),
                    _dim(_j(user=self.user_id, symbol=sym, oid=order_id, avg=avg, filled=filled_qty)),
                )
        except Exception as e:
            log.debug("ORDER_UPDATE_PARSE_FAIL | user=%s err=%s ou=%s", self.user_id, e, ou)

# ---------------- Zerodha positions REST (reconcile) ----------------
    async def _kite_positions(self) -> Dict[str, Any]:
            """
            Fetch Zerodha positions using REST (slower, but works after restart).
            Returns dict with 'net' and 'day' arrays (Zerodha format).
            """
            def _fetch(api_key: str, access_token: str) -> Dict[str, Any]:
                kite = KiteConnect(api_key=api_key)
                kite.set_access_token(access_token)
                return kite.positions()

            res = await self.order_worker.submit(
                _fetch,
                api_key=self.api_key,
                access_token=self.access_token,
            )
            return res or {}

    async def rehydrate_open_positions(self) -> List[str]:
        """
        Load OPEN/EXITING positions from Redis into memory so auto-exit monitoring works after restart.
        Returns list of symbols restored.
        """
        restored: List[str] = []

        try:
            rows = await self.store.list_positions(self.user_id)
        except Exception as e:
            log.error("❌ REHYDRATE_FAIL | user=%s err=%s", self.user_id, e)
            return restored

        # allowed dataclass keys
        allowed = {f.name for f in _dc_fields(Position)}

        for row in rows or []:
            try:
                sym = norm_symbol(str(row.get("symbol") or ""))
                if not sym:
                    continue

                status = str(row.get("status") or "OPEN").upper()
                if status not in ("OPEN", "EXIT_CONDITIONS_MET", "EXITING"):
                    continue

                data = {k: row.get(k) for k in allowed if k in row}
                # force required defaults
                data["symbol"] = sym
                data["user_id"] = int(self.user_id)
                data["status"] = "OPEN"  # keep as OPEN to allow monitoring

                # If entry_price missing, keep 0.0 but monitoring will be limited
                data["entry_price"] = float(row.get("entry_price") or 0.0)
                data["qty"] = int(row.get("qty") or 0)
                if data["qty"] <= 0:
                    continue

                pos = Position(**data)  # type: ignore[arg-type]

                # ensure monitoring fields exist
                if pos.product == "MIS":
                    if pos.highest <= 0 and pos.entry_price > 0:
                        pos.highest = pos.entry_price
                    if pos.lowest <= 0 and pos.entry_price > 0:
                        pos.lowest = pos.entry_price

                self.positions[sym] = pos
                self._exit_inflight[sym] = False
                self._exit_signal_sent[sym] = False
                restored.append(sym)

            except Exception as e:
                log.debug("REHYDRATE_ROW_SKIP | user=%s err=%s row=%s", self.user_id, e, row)

        log.info("♻️ REHYDRATE_DONE | user=%s restored=%s", self.user_id, restored)
        return restored
    

    async def _fetch_positions_avg(self, symbol: str) -> float:
        """
        Fetch average_price for given symbol from kite.positions() (REST).
        """
        def _fetch(api_key: str, access_token: str) -> Dict[str, Any]:
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            return kite.positions()

        data = await self.order_worker.submit(_fetch, api_key=self.api_key, access_token=self.access_token)
        rows = []
        try:
            rows = list(data.get("net") or []) + list(data.get("day") or [])
        except Exception:
            rows = []

        for r in rows:
            tsym = norm_symbol(str(r.get("tradingsymbol") or ""))
            if tsym != symbol:
                continue
            qty = int(r.get("quantity") or 0)
            if qty == 0:
                continue
            avg = float(r.get("average_price") or 0.0)
            if avg > 0:
                return avg

        return 0.0

    # =========================
    # Chartink alert processing
    # =========================
    async def on_chartink_alert(self, alert_name: str, symbols: List[str], ts: str = "") -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []

        alert_key = normalize_alert_key(alert_name)
        log.info(
            "\n%s\n%s",
            _bold(_cyan("🔔 ALERT_RECEIVED")),
            _dim(_j(user=self.user_id, alert=alert_name, key=alert_key, symbols=symbols)),
        )

        if await self.store.is_kill(self.user_id):
            log.warning("🛑 KILL_SWITCH | user=%s alert=%s", self.user_id, alert_key)
            return [{"symbol": _safe_symbol(s), "status": "REJECTED", "reason": "KILL_SWITCH"} for s in symbols]

        cfg_raw = await self.store.get_alert_config(self.user_id, alert_key)

        if not cfg_raw:
            raw = (alert_name or "").strip()
            variants = [
                raw,
                raw.lower(),
                raw.replace(" ", "_").lower(),
                raw.replace("_", " ").lower(),
                normalize_alert_key(raw),
            ]
            for v in variants:
                if not v:
                    continue
                cfg_raw = await self.store.get_alert_config(self.user_id, v)
                if cfg_raw:
                    log.info("ℹ️ CFG_FALLBACK_HIT | user=%s key=%s original=%s", self.user_id, v, alert_key)
                    break

        if not cfg_raw:
            log.warning("⚠️ NO_CONFIG | user=%s alert=%s", self.user_id, alert_key)
            return [{"symbol": _safe_symbol(s), "status": "SKIPPED", "reason": "NO_CONFIG"} for s in symbols]

        cfg = AlertConfig.from_dict(cfg_raw)
        if not cfg.enabled:
            log.warning("⚠️ CFG_DISABLED | user=%s alert=%s", self.user_id, alert_key)
            return [{"symbol": _safe_symbol(s), "status": "SKIPPED", "reason": "CFG_DISABLED"} for s in symbols]

        # Check entry time window
        if not _is_within_entry_window(cfg.entry_start_time, cfg.entry_end_time):
            log.warning(
                "⏰ OUTSIDE_ENTRY_WINDOW | user=%s alert=%s start=%s end=%s",
                self.user_id, alert_key, cfg.entry_start_time, cfg.entry_end_time
            )
            return [{"symbol": _safe_symbol(s), "status": "REJECTED", "reason": "OUTSIDE_ENTRY_WINDOW"} for s in symbols]

        log.info(
            "✅ CFG_OK | user=%s alert=%s dir=%s product=%s qty_mode=%s limit=%s sector_filter=%s topN=%s entry_window=%s-%s",
            self.user_id,
            alert_key,
            cfg.direction,
            cfg.product,
            cfg.qty_mode,
            cfg.trade_limit_per_day,
            cfg.sector_filter_on,
            cfg.top_n_sector,
            cfg.entry_start_time,
            cfg.entry_end_time,
        )

        for sym in symbols:
            sym2 = _safe_symbol(sym)
            if not sym2:
                continue
            r = await self._try_enter(sym2, alert_key, cfg, alert_time=ts)
            
            # Inject latest tick data into result for immediate UI feedback
            tick = self.ticks.get(sym2, {})
            
            # Fallback: If no tick, try REST quote (for fresh alerts)
            if not tick or tick.get("ltp", 0.0) == 0:
                try:
                    # We need a kite instance.
                    # This might fail if not connected, but worth a try for accurate UI.
                    if self.api_key and self.access_token:
                        # Temporary kite client just for quote? Or use a shared one?
                        # Since we don't have a persistent kite client object in TradeEngine,
                        # we can try to use a lightweight approach or just skip.
                        # For now, let's rely on the main loop's Ticker. 
                        # But wait, we can't easily get a quote without a kite instance.
                        # Let's try to grab one from the store/creds if we really need it,
                        # OR better: just checking ticks is usually enough if auto-sub works fast.
                        # However, for the very first alert, auto-sub happens *after*.
                        # So we SHOULD try to get a quote if possible.
                        
                        # Re-instantiate a temp kite for this (rate limits apply, be careful)
                        # Only do this if we have absolutely NO data.
                        k = KiteConnect(api_key=self.api_key)
                        k.set_access_token(self.access_token)
                        # "NSE:SBIN" format
                        q_key = f"NSE:{sym2}"
                        qs = k.quote([q_key])
                        if qs and q_key in qs:
                            d = qs[q_key]
                            tick = {
                                "ltp": d.get("last_price", 0.0),
                                "close": d.get("ohlc", {}).get("close", 0.0)
                            }
                            # Only update cache if it's empty
                            if sym2 not in self.ticks:
                                self.ticks[sym2] = tick
                except Exception as e:
                    log.debug("⚠️ QUOTE_FALLBACK_FAIL | %s | %s", sym2, e)

            r["ltp"] = float(tick.get("ltp", 0.0))
            ltp = r["ltp"]
            close = float(tick.get("close", 0.0))
            r["pct"] = ((ltp - close) / close * 100.0) if close > 0 else 0.0
            
            out.append(r)

        entered = sum(1 for r in out if r.get("status") == "ENTERED")
        skipped = sum(1 for r in out if r.get("status") == "SKIPPED")
        rejected = sum(1 for r in out if r.get("status") == "REJECTED")
        errors = sum(1 for r in out if r.get("status") == "ERROR")

        log.info(
            "\n%s\n%s",
            _bold(_magenta("📊 ALERT_SUMMARY")),
            _dim(_j(user=self.user_id, alert=alert_key, entered=entered, skipped=skipped, rejected=rejected, errors=errors, total=len(out))),
        )

        return out

    async def _try_enter(self, symbol: str, alert_key: str, cfg: AlertConfig, alert_time: str = "") -> Dict[str, Any]:
        symbol = _safe_symbol(symbol)

        if not self._sector_allows(symbol, cfg):
            sector = self.sym_sector.get(symbol, "UNKNOWN")
            log.info(
                "🚫 SECTOR_BLOCK | user=%s alert=%s symbol=%s sector=%s topN=%s dir=%s",
                self.user_id, alert_key, symbol, sector, cfg.top_n_sector, cfg.direction
            )
            return {"symbol": symbol, "status": "SKIPPED", "reason": "SECTOR_FILTER"}

        if symbol in self.positions and self.positions[symbol].status in ("OPEN", "EXITING"):
            log.info("⚠️ ALREADY_OPEN_MEM | user=%s alert=%s symbol=%s", self.user_id, alert_key, symbol)
            return {"symbol": symbol, "status": "SKIPPED", "reason": "ALREADY_OPEN"}

        if await self.store.get_open(self.user_id, symbol):
            log.info("⚠️ ALREADY_OPEN_REDIS | user=%s alert=%s symbol=%s", self.user_id, alert_key, symbol)
            return {"symbol": symbol, "status": "SKIPPED", "reason": "ALREADY_OPEN_REDIS"}

        lk = await self.store.acquire_lock(self.user_id, symbol, "entry", ttl_ms=2000)
        if lk != 1:
            reason = "KILL" if lk == -2 else "ENTRY_LOCK_BUSY"
            log.info("🔒 ENTRY_LOCK_FAIL | user=%s alert=%s symbol=%s reason=%s lk=%s", self.user_id, alert_key, symbol, reason, lk)
            return {"symbol": symbol, "status": "SKIPPED", "reason": reason}

        try:
            ok = await self._ensure_kite_ready()
            if not ok:
                log.error(
                    "❌ ZERODHA_NOT_CONNECTED | user=%s alert=%s symbol=%s api_key_len=%s token_len=%s",
                    self.user_id, alert_key, symbol, len(self.api_key or ""), len(self.access_token or "")
                )
                return {"symbol": symbol, "status": "ERROR", "reason": "ZERODHA_NOT_CONNECTED"}

            side: Side = "BUY" if cfg.direction == "LONG" else "SELL"
            product: Product = "CNC" if str(cfg.product).upper() == "CNC" else "MIS"

            if product == "CNC" and side == "SELL":
                log.warning("❌ CNC_SHORT_BLOCK | user=%s alert=%s symbol=%s", self.user_id, alert_key, symbol)
                return {"symbol": symbol, "status": "REJECTED", "reason": "CNC_SHORT_NOT_ALLOWED"}

            tick = self.ticks.get(symbol, {})
            ltp = float(tick.get("ltp", 0.0))

            if cfg.qty_mode == "CAPITAL" and ltp <= 0:
                ltp = await self._wait_for_ltp(symbol, timeout_sec=0.30)

            if cfg.qty_mode == "CAPITAL" and ltp <= 0:
                log.warning("⚠️ NO_LTP_CAPITAL | user=%s alert=%s symbol=%s", self.user_id, alert_key, symbol)
                return {"symbol": symbol, "status": "SKIPPED", "reason": "NO_LTP_FOR_CAPITAL_QTY"}

            qty = self._calc_qty(cfg, ltp if ltp > 0 else 1.0)
            if qty <= 0:
                log.warning("❌ BAD_QTY | user=%s alert=%s symbol=%s ltp=%.2f qty=%s", self.user_id, alert_key, symbol, ltp, qty)
                return {"symbol": symbol, "status": "REJECTED", "reason": "BAD_QTY"}

            allowed = await self.store.allow_trade(self.user_id, alert_key, cfg.trade_limit_per_day)
            if not allowed:
                log.info("⛔ TRADE_LIMIT | user=%s alert=%s symbol=%s limit=%s/day", self.user_id, alert_key, symbol, cfg.trade_limit_per_day)
                return {"symbol": symbol, "status": "SKIPPED", "reason": "TRADE_LIMIT"}

            trade_id = uuid.uuid4().hex[:12]
            pos = Position(
                trade_id=trade_id,
                user_id=self.user_id,
                symbol=symbol,
                alert_name=alert_key,
                side=side,
                product=product,
                qty=int(qty),
                entry_price=float(ltp),
                alert_time=str(alert_time),
                created_ts=time.time(),
                updated_ts=time.time(),
            )
            pos.cfg_target_pct=float(cfg.target_pct)
            pos.cfg_sl_pct=float(cfg.stop_loss_pct)
            pos.cfg_tsl_pct = float(cfg.trailing_sl_pct)
            pos.sector = self.sym_sector.get(symbol, "")  # Add sector info


            # MIS monitoring setup
            if product == "MIS" and ltp > 0:
                entry = float(ltp)
                if side == "BUY":
                    pos.target_price = entry * (1.0 + float(cfg.target_pct) / 100.0)
                    pos.sl_price = entry * (1.0 - float(cfg.stop_loss_pct) / 100.0)
                    pos.highest = entry
                else:
                    pos.target_price = entry * (1.0 - float(cfg.target_pct) / 100.0)
                    pos.sl_price = entry * (1.0 + float(cfg.stop_loss_pct) / 100.0)
                    pos.lowest = entry
                pos.tsl_pct = float(cfg.trailing_sl_pct)

            sep = "─" * 90
            sym_tag = _bg_yellow(f" {symbol} ")

            log.info(
                "\n%s\n%s\n%s",
                sep,
                _bold(_cyan("📤 ENTRY_SEND")) + " " + sym_tag + " " + _dim(f"user={self.user_id} alert={alert_key} trade={trade_id}"),
                _dim(f"{symbol}  {_fmt_side(side)} qty={qty} {product}  ltp={ltp:.2f}  | tgt={pos.target_price:.2f} sl={pos.sl_price:.2f} tsl%={pos.tsl_pct:.2f}"),
            )


            try:
                oid = await self._place_order(symbol, side, qty, product)
            except Exception as e:
                log.error("❌ ENTRY_ORDER_FAIL | user=%s alert=%s symbol=%s err=%s", self.user_id, alert_key, symbol, e)
                return {"symbol": symbol, "status": "ERROR", "reason": str(e)}

            try:
                await self.store.mark_open(self.user_id, symbol, str(oid))
            except Exception as e:
                log.debug("📝 MARK_OPEN_FAIL | user=%s symbol=%s err=%s", self.user_id, symbol, e)

            pos.entry_order_id = str(oid)
            pos.status = "OPEN"
            pos.ltp = float(ltp)
            pos.updated_ts = time.time()

            self.positions[symbol] = pos
            try:
                await self.store.upsert_position(self.user_id, symbol, pos.to_public())
            except Exception as e:
                log.debug("📝 UPSERT_POS_FAIL | user=%s symbol=%s err=%s", self.user_id, symbol, e)

            sep = "─" * 90
            sym_tag = _bg_yellow(f" {symbol} ")

            log.info(
                "\n%s\n%s\n%s\n%s",
                sep,
                _bold(_green("✅ ENTRY_OK")) + " " + sym_tag + " " + _dim(f"user={self.user_id} alert={alert_key} trade={trade_id}"),
                _dim(f"oid={str(oid)}  {symbol}  {_fmt_side(side)} qty={qty} {product}"),
                _dim(_fmt_pos(pos)),
            )


            return {
                "symbol": symbol,
                "status": "ENTERED",
                "trade_id": trade_id,
                "order_id": str(oid),
                "qty": int(qty),
                "side": side,
                "product": product,
            }

        finally:
            try:
                await self.store.release_lock(self.user_id, symbol, "entry")
            except Exception:
                pass

    # =========================
    # Tick ingestion + monitoring (HOT PATH)
    # =========================
    async def on_tick(
        self,
        symbol: str,
        ltp: float,
        close: float,
        high: float,
        low: float,
        tbq: float = 0.0,
        tsq: float = 0.0,
    ) -> Optional[Position]:
        try:
            return await self._on_tick_unsafe(symbol, ltp, close, high, low, tbq, tsq)
        except Exception as e:
            log.exception("🔥 CRITICAL_TICK_ERROR | user=%s symbol=%s err=%s", self.user_id, symbol, e)
            return None

    async def _on_tick_unsafe(
        self,
        symbol: str, 
        ltp: float,
        close: float,
        high: float,
        low: float,
        tbq: float,
        tsq: float
    ) -> Optional[Position]:
        symbol = norm_symbol(symbol)
        if not symbol or ltp <= 0:
            return None

        self.ticks[symbol] = {
            "ltp": float(ltp),
            "close": float(close),
            "high": float(high),
            "low": float(low),
            "tbq": float(tbq),
            "tsq": float(tsq),
        }

        if close and close > 0:
            pct = ((ltp - close) / close) * 100.0
            self._update_sector_perf(symbol, float(pct))
            
            # Periodic sector ranking summary
            now = time.time()
            if now - self._last_sector_rank_log >= self.sector_rank_log_interval_sec:
                self._last_sector_rank_log = now
                ranked = self.get_sector_rank()
                if ranked:
                    # Explicit Top 1 Gainer / Loser
                    top_gainer_name, top_gainer_pct = ranked[0]
                    top_loser_name, top_loser_pct = ranked[-1]

                    log.info("\n" + "="*80)
                    log.info("📊 SECTOR PERFORMANCE SUMMARY (Updated: %s)", 
                             datetime.now().strftime("%H:%M:%S"))
                    
                    # 1. Always show Top Gainer (or Best Performer)
                    if top_gainer_pct > 0:
                        log.info("👑 TOP GAINER: %s (+%.2f%%)", _green(_bold(top_gainer_name)), top_gainer_pct)
                    else:
                        # If best is negative, it's still the "Best" relative
                        log.info("👑 TOP GAINER: %s (%.2f%%)", top_gainer_name, top_gainer_pct)

                    # 2. Show Top Loser ONLY if it's different from Top Gainer
                    if top_gainer_name != top_loser_name:
                        if top_loser_pct < 0:
                             log.info("💀 TOP LOSER : %s (%.2f%%)", _red(_bold(top_loser_name)), top_loser_pct)
                        else:
                             log.info("💀 TOP LOSER : %s (+%.2f%%)", top_loser_name, top_loser_pct)

                    log.info("-" * 40)
                    log.info("All Sectors Ranked:")
                    
                    for i, (sec, avg_pct) in enumerate(ranked, 1):
                        cnt = self.sector_cnt.get(sec, 0)
                        emoji = "🟢" if avg_pct > 0 else "🔴" if avg_pct < 0 else "⚪"
                        
                        # Highlight top 2 boundaries if relevant
                        prefix = "   "
                        if i <= 2: prefix = "⚡ " # Top 2
                        
                        log.info("  %s%2d. %s %-25s %+7.2f%% (%d stocks)", 
                                prefix, i, emoji, sec, avg_pct, cnt)
                    log.info("="*80 + "\n")

        pos = self.positions.get(symbol)
        if not pos or pos.status != "OPEN":
            return None

        # update LTP and pnl safely (avoid entry=0 wrong pnl)
        pos.ltp = float(ltp)
        pos.updated_ts = time.time()

        if pos.entry_price > 0:
            pos.pnl = (ltp - pos.entry_price) * pos.qty if pos.side == "BUY" else (pos.entry_price - ltp) * pos.qty
        else:
            pos.pnl = 0.0

        # CNC: no auto exit monitoring (keep as per your design)
        if pos.product == "CNC":
            return pos

        # reconcile entry_price once if missing (REST)
        if pos.entry_price <= 0 and not self._recon_inflight.get(symbol):
            self._recon_inflight[symbol] = True

            async def _recon():
                try:
                    ok = await self._ensure_kite_ready()
                    if not ok:
                        return
                    avg = await self._fetch_positions_avg(symbol)
                    if avg > 0 and pos.entry_price <= 0:
                        pos.entry_price = float(avg)

                        # init monitoring from cfg pcts
                        if pos.cfg_target_pct > 0 and pos.target_price <= 0:
                            if pos.side == "BUY":
                                pos.target_price = pos.entry_price * (1.0 + pos.cfg_target_pct / 100.0)
                            else:
                                pos.target_price = pos.entry_price * (1.0 - pos.cfg_target_pct / 100.0)
                        if pos.cfg_sl_pct > 0 and pos.sl_price <= 0:
                            if pos.side == "BUY":
                                pos.sl_price = pos.entry_price * (1.0 - pos.cfg_sl_pct / 100.0)
                            else:
                                pos.sl_price = pos.entry_price * (1.0 + pos.cfg_sl_pct / 100.0)
                        if pos.cfg_tsl_pct > 0 and pos.tsl_pct <= 0:
                            pos.tsl_pct = float(pos.cfg_tsl_pct)

                        if pos.side == "BUY" and pos.highest <= 0:
                            pos.highest = pos.entry_price
                        if pos.side == "SELL" and pos.lowest <= 0:
                            pos.lowest = pos.entry_price

                        log.info(
                            "\n%s\n%s",
                            _bold(_yellow("♻️ ENTRY_RECONCILED")),
                            _dim(_j(user=self.user_id, symbol=symbol, avg=avg)),
                        )

                        try:
                            await self.store.upsert_position(self.user_id, symbol, pos.to_public())
                        except Exception:
                            pass
                finally:
                    self._recon_inflight[symbol] = False

            asyncio.create_task(_recon(), name=f"recon_{symbol}")

        # extremes
        if pos.side == "BUY":
            pos.highest = max(pos.highest, ltp) if pos.highest else float(ltp)
        else:
            pos.lowest = min(pos.lowest, ltp) if pos.lowest else float(ltp)

        # tsl line for BUY/SELL
        tsl_line = 0.0
        if pos.tsl_pct > 0:
            if pos.side == "BUY" and pos.highest > 0:
                tsl_line = pos.highest * (1.0 - pos.tsl_pct / 100.0)
            elif pos.side == "SELL" and pos.lowest > 0:
                tsl_line = pos.lowest * (1.0 + pos.tsl_pct / 100.0)

        # distances (signed)
        tgt_dist = 0.0
        sl_dist = 0.0
        tsl_dist = 0.0
        if pos.target_price > 0:
            tgt_dist = ((pos.ltp - pos.target_price) / pos.target_price) * 100.0
        if pos.sl_price > 0:
            sl_dist = ((pos.ltp - pos.sl_price) / pos.sl_price) * 100.0
        if tsl_line > 0:
            tsl_dist = ((pos.ltp - tsl_line) / tsl_line) * 100.0

        # exit reason
        reason: Optional[str] = None
        if pos.side == "BUY":
            if pos.target_price > 0 and ltp >= pos.target_price:
                reason = "TARGET"
            elif pos.sl_price > 0 and ltp <= pos.sl_price:
                reason = "STOP_LOSS"
            elif tsl_line > 0 and ltp <= tsl_line:
                reason = "TRAILING_SL"
        else:
            if pos.target_price > 0 and ltp <= pos.target_price:
                reason = "TARGET"
            elif pos.sl_price > 0 and ltp >= pos.sl_price:
                reason = "STOP_LOSS"
            elif tsl_line > 0 and ltp >= tsl_line:
                reason = "TRAILING_SL"

        # near tags (for monitor)
        near_tags: List[str] = []
        if pos.target_price > 0 and abs(tgt_dist) <= 0.15:
            near_tags.append("NEAR_TARGET")
        if pos.sl_price > 0 and abs(sl_dist) <= 0.15:
            near_tags.append("NEAR_SL")
        if tsl_line > 0 and abs(tsl_dist) <= 0.15:
            near_tags.append("NEAR_TSL")

        # -----------------------------
        # ✅ MONITOR LOG (throttled: 5 sec per symbol)
        # -----------------------------
        now = time.time()
        last = self._mon_last_log.get(symbol, 0.0)
        if now - last >= self.monitor_log_interval_sec:
            self._mon_last_log[symbol] = now

            # -----------------------------
            # ✅ MONITOR LOG (BOXED)
            # -----------------------------
            sym_tag = _bg_blue(f" {symbol} ") 
            
            # Format sector badge if available
            sec_tag = ""
            if hasattr(pos, "sector") and pos.sector:
                sec_tag = " " + _bg_magenta(f" {pos.sector} ") 

            title = _bold(_cyan("📈 MONITOR")) + " " + sym_tag + sec_tag + " " + _dim(f"alert={pos.alert_name}")

            line1 = (
                f"{_bold(_cyan(symbol))}  {_fmt_side(pos.side)} {pos.qty} qty {pos.product}  "
                f"entry={pos.entry_price:.2f}  ltp={pos.ltp:.2f}  pnl={_fmt_pnl(pos.pnl)}"
            )
            line2 = (
                f"tgt={pos.target_price:.2f}  sl={pos.sl_price:.2f}  "
                f"hi={pos.highest:.2f}  lo={pos.lowest:.2f}  tsl%={pos.tsl_pct:.2f}"
            )
            line3 = (
                f"dist: tgt={_fmt_pct(tgt_dist)}  sl={_fmt_pct(sl_dist)}  tsl={_fmt_pct(tsl_dist)}  "
                f"tsl_line={tsl_line:.2f}"
            )

            if reason:
                status = _bold(_magenta(f"🧨 EXIT_TRIGGER={reason}"))
            elif near_tags:
                status = _yellow("⚠️ " + " ".join(near_tags))
            else:
                status = _dim("ok")

            # ---- build box (NO double borders) ----
            lines = [title, line1, _dim(line2), _dim(line3), status]
            w = max(_vis_len(x) for x in lines)

            top = "╔" + "═" * (w + 2) + "╗"
            bot = "╚" + "═" * (w + 2) + "╝"

            boxed = [top]
            for s in lines:
                boxed.append("║ " + _pad(s, w) + " ║")
            boxed.append(bot)

            log.info("\n" + "\n".join(boxed))

        # -----------------------------
        # ✅ LOG when condition fulfilled (only once) + trigger exit
        # -----------------------------
        if reason:
            if not self._exit_signal_sent.get(symbol):
                self._exit_signal_sent[symbol] = True
                
                # ✅ UPDATE STATUS - Mark as EXIT_CONDITIONS_MET
                pos.status = "EXIT_CONDITIONS_MET"
                pos.exit_reason = reason
                pos.updated_ts = time.time()
                
                # Save to Redis so dashboard shows the status
                try:
                    await self.store.upsert_position(self.user_id, symbol, pos.to_public())
                except Exception as e:
                    log.debug("REDIS_UPDATE_FAIL | symbol=%s err=%s", symbol, e)
                
                log.info(
                    "\n%s\n%s",
                    _bold(_magenta("✅ EXIT_CONDITION_MET")),
                    _dim(
                        _j(
                            user=self.user_id,
                            trade=pos.trade_id,
                            alert=pos.alert_name,
                            symbol=symbol,
                            reason=reason,
                            ltp=pos.ltp,
                            entry=pos.entry_price,
                            pnl=pos.pnl,
                            tgt=pos.target_price,
                            sl=pos.sl_price,
                            tsl_line=tsl_line,
                            hi=pos.highest,
                            lo=pos.lowest,
                            qty=pos.qty,
                            side=pos.side,
                        )
                    ),
                )

            if not self._exit_inflight.get(symbol):
                self._exit_inflight[symbol] = True
                # Set status to EXITING before placing exit order
                pos.status = "EXITING"
                try:
                    await self.store.upsert_position(self.user_id, symbol, pos.to_public())
                except Exception:
                    pass
                asyncio.create_task(self._exit_position(symbol, reason), name=f"exit_{symbol}")
            else:
                log.debug("⏳ EXIT_DEBOUNCE | user=%s symbol=%s reason=%s", self.user_id, symbol, reason)

        return pos


    def _maybe_log_monitor(self, pos: Position) -> None:
        """
        Rich monitoring log: shows for each OPEN position:
        - ltp, pnl, entry
        - target/sl/tsl-line
        - distance (%) to each level
        - "NEAR" tags so you know which stocks are close to hit
        """
        now = time.time()
        last = self._mon_last_log.get(pos.symbol, 0.0)
        if self.monitor_log_interval_sec > 0 and (now - last) < self.monitor_log_interval_sec:
            return
        self._mon_last_log[pos.symbol] = now

        ltp = float(pos.ltp)
        entry = float(pos.entry_price)
        tgt = float(pos.target_price)
        sl = float(pos.sl_price)

        tsl_line = 0.0
        if pos.product == "MIS" and pos.tsl_pct > 0:
            if pos.side == "BUY" and pos.highest > 0:
                tsl_line = float(pos.highest) * (1.0 - float(pos.tsl_pct) / 100.0)
            elif pos.side == "SELL" and pos.lowest > 0:
                tsl_line = float(pos.lowest) * (1.0 + float(pos.tsl_pct) / 100.0)

        # distance sign: + means ltp above level, - means below (generic)
        dt = _pct_dist(ltp, tgt) if tgt > 0 else 0.0
        ds = _pct_dist(ltp, sl) if sl > 0 else 0.0
        dtsl = _pct_dist(ltp, tsl_line) if tsl_line > 0 else 0.0

        # interpret "near" differently for BUY/SELL
        near_tags: List[str] = []
        hit_tags: List[str] = []

        if pos.product == "MIS":
            if pos.side == "BUY":
                if tgt > 0 and ltp >= tgt:
                    hit_tags.append("HIT_TARGET")
                elif tgt > 0 and abs(_pct_dist(ltp, tgt)) <= self.near_pct:
                    near_tags.append("NEAR_TARGET")

                if sl > 0 and ltp <= sl:
                    hit_tags.append("HIT_SL")
                elif sl > 0 and abs(_pct_dist(ltp, sl)) <= self.near_pct:
                    near_tags.append("NEAR_SL")

                if tsl_line > 0 and ltp <= tsl_line:
                    hit_tags.append("HIT_TSL")
                elif tsl_line > 0 and abs(_pct_dist(ltp, tsl_line)) <= self.near_pct:
                    near_tags.append("NEAR_TSL")
            else:
                if tgt > 0 and ltp <= tgt:
                    hit_tags.append("HIT_TARGET")
                elif tgt > 0 and abs(_pct_dist(ltp, tgt)) <= self.near_pct:
                    near_tags.append("NEAR_TARGET")

                if sl > 0 and ltp >= sl:
                    hit_tags.append("HIT_SL")
                elif sl > 0 and abs(_pct_dist(ltp, sl)) <= self.near_pct:
                    near_tags.append("NEAR_SL")

                if tsl_line > 0 and ltp >= tsl_line:
                    hit_tags.append("HIT_TSL")
                elif tsl_line > 0 and abs(_pct_dist(ltp, tsl_line)) <= self.near_pct:
                    near_tags.append("NEAR_TSL")

        tag_str = ""
        if hit_tags:
            tag_str += " ✅" + ",".join(hit_tags)
        if near_tags:
            tag_str += " ⚠️  " + ",".join(near_tags)

        log.info(
            "📈 MONITOR | user=%s trade=%s alert=%s | %s | "
            "dist[tgt=%.2f%% sl=%.2f%% tsl=%.2f%%]%s",
            self.user_id,
            pos.trade_id,
            pos.alert_name,
            _fmt_pos(pos),
            float(dt),
            float(ds),
            float(dtsl),
            tag_str,
        )

    # =========================
    # Manual squareoff (FIXED)
    # =========================
    async def manual_squareoff_zerodha(self, symbol: str, reason: str = "MANUAL_RESTART") -> Dict[str, Any]:
        """
        Manual squareoff that works even after restart (without Redis).
        Strategy:
          1) Try in-memory position -> normal exit path
          2) Else call kite.positions() and find open position for symbol
          3) Place opposite market order (MIS/CNC) for abs(quantity)
        """
        symbol = norm_symbol(symbol or "")
        if not symbol:
            return {"status": "ERROR", "reason": "BAD_SYMBOL"}

        # 1) Memory fast path
        pos = self.positions.get(symbol)
        if pos and pos.status == "OPEN":
            log.info("🖐️ MANUAL_EXIT_MEM | user=%s symbol=%s reason=%s", self.user_id, symbol, reason)
            await self._exit_position(symbol, reason)
            return {"status": "EXIT_TRIGGERED", "symbol": symbol, "reason": reason, "source": "MEMORY"}

        # Ensure kite ready
        ok = await self._ensure_kite_ready()
        if not ok:
            return {"status": "ERROR", "reason": "ZERODHA_NOT_CONNECTED"}

        # 2) Zerodha REST fallback
        log.info("🔎 MANUAL_EXIT_RESTART_LOOKUP | user=%s symbol=%s reason=%s", self.user_id, symbol, reason)
        try:
            data = await self._kite_positions()
        except Exception as e:
            log.error("❌ POSITIONS_FETCH_FAIL | user=%s symbol=%s err=%s", self.user_id, symbol, e)
            return {"status": "ERROR", "reason": f"POSITIONS_FETCH_FAIL:{e}"}

        rows = []
        try:
            rows = list(data.get("net") or []) + list(data.get("day") or [])
        except Exception:
            rows = []

        # Find position for this symbol with non-zero qty
        found = None
        for r in rows:
            tsym = norm_symbol(str(r.get("tradingsymbol") or ""))
            if tsym != symbol:
                continue
            qty = int(r.get("quantity") or 0)  # net quantity (+ long, - short)
            if qty == 0:
                continue
            found = r
            break

        if not found:
            log.warning("⚠️ MANUAL_EXIT_NO_ZERODHA_POS | user=%s symbol=%s", self.user_id, symbol)
            return {"status": "NOT_FOUND", "symbol": symbol, "reason": "NO_OPEN_POSITION_ON_ZERODHA"}

        qty = abs(int(found.get("quantity") or 0))
        if qty <= 0:
            return {"status": "NOT_FOUND", "symbol": symbol, "reason": "ZERO_QTY"}

        # Product: MIS/CNC from Zerodha position (usually 'product' key)
        prod_raw = str(found.get("product") or "MIS").strip().upper()
        product: Product = "CNC" if prod_raw == "CNC" else "MIS"

        # If net qty positive => long => exit by SELL, else short => exit by BUY
        net_qty = int(found.get("quantity") or 0)
        exit_side: Side = "SELL" if net_qty > 0 else "BUY"

        log.info(
            "🧯 MANUAL_EXIT_ZERODHA_POS_FOUND | user=%s symbol=%s net_qty=%s exit_side=%s qty=%s product=%s reason=%s",
            self.user_id, symbol, net_qty, exit_side, qty, product, reason
        )

        # Place exit order on Zerodha
        try:
            oid = await self._place_order(symbol, exit_side, qty, product)
            log.info(
                "✅ MANUAL_EXIT_ZERODHA_OK | user=%s symbol=%s exit_oid=%s side=%s qty=%s product=%s",
                self.user_id, symbol, str(oid), exit_side, qty, product
            )
            return {
                "status": "EXIT_OK",
                "symbol": symbol,
                "exit_order_id": str(oid),
                "exit_side": exit_side,
                "qty": qty,
                "product": product,
                "reason": reason,
                "source": "ZERODHA_POSITIONS",
            }
        except Exception as e:
            log.error("❌ MANUAL_EXIT_ZERODHA_FAIL | user=%s symbol=%s err=%s", self.user_id, symbol, e)
            return {"status": "ERROR", "reason": f"EXIT_ORDER_FAIL:{e}", "symbol": symbol}


    # =========================
    # Exit path
    # =========================
    async def _exit_position(self, symbol: str, reason: str) -> None:
        symbol = _safe_symbol(symbol)
        exit_side: Side = "SELL"

        try:
            pos = self.positions.get(symbol)
            if not pos or pos.status not in ("OPEN", "EXITING", "EXIT_CONDITIONS_MET"):
                log.debug("↩️ EXIT_SKIP | user=%s symbol=%s reason=%s (not OPEN/EXITING)", self.user_id, symbol, reason)
                return

            exit_side = "SELL" if pos.side == "BUY" else "BUY"

            log.info(
                "🚪 EXIT_START | user=%s trade=%s alert=%s reason=%s | exit_side=%s | %s",
                self.user_id,
                pos.trade_id,
                pos.alert_name,
                reason,
                exit_side,
                _fmt_pos(pos),
            )

            lk = await self.store.acquire_lock(self.user_id, symbol, "exit", ttl_ms=2500)
            if lk != 1:
                log.warning(
                    "🔒 EXIT_LOCK_FAIL | user=%s trade=%s symbol=%s reason=%s lock=%s",
                    self.user_id,
                    pos.trade_id,
                    symbol,
                    reason,
                    lk,
                )
                return

            try:
                pos.status = "EXITING"
                pos.exit_reason = str(reason)
                pos.updated_ts = time.time()
                try:
                    await self.store.upsert_position(self.user_id, symbol, pos.to_public())
                except Exception as e:
                    log.debug("📝 EXIT_UPSERT_FAIL | user=%s symbol=%s err=%s", self.user_id, symbol, e)

                log.info(
                    "📤 EXIT_ORDER_SEND | user=%s trade=%s symbol=%s | %s %s qty=%s product=%s",
                    self.user_id,
                    pos.trade_id,
                    symbol,
                    exit_side,
                    symbol,
                    pos.qty,
                    pos.product,
                )

                try:
                    oid = await self._place_order(symbol, exit_side, int(pos.qty), pos.product)
                    pos.exit_order_id = str(oid)
                    pos.status = "CLOSED"
                    pos.updated_ts = time.time()

                    log.info(
                        "✅ EXIT_ORDER_OK | user=%s trade=%s symbol=%s exit_oid=%s reason=%s | pnl=%.2f",
                        self.user_id,
                        pos.trade_id,
                        symbol,
                        str(oid),
                        reason,
                        float(pos.pnl),
                    )

                    # Delete from Redis and memory instead of keeping CLOSED positions
                    try:
                        await self.store.delete_position(self.user_id, symbol)
                        # Remove from memory
                        if symbol in self.positions:
                            del self.positions[symbol]
                        log.info("🗑️ POSITION_DELETED | user=%s symbol=%s (CLOSED)", self.user_id, symbol)
                        
                        # ✅ Update alert status in history
                        if pos.alert_time:
                            await self.store.update_alert_status(
                                self.user_id, 
                                pos.alert_time, 
                                symbol, 
                                new_status=reason.replace("_", " "), # e.g. "TARGET_HIT" -> "TARGET HIT"
                                reason=reason,
                                alert_name=pos.alert_name
                            )

                        # ✅ Trigger UI refresh
                        if self.broadcast_cb:
                            self.broadcast_cb(self.user_id, {"type": "pos_refresh"})
                            
                    except Exception as e:
                        log.debug("📝 DELETE_POS_FAIL | user=%s symbol=%s err=%s", self.user_id, symbol, e)

                except Exception as e:
                    pos.status = "ERROR"
                    pos.exit_reason = f"EXIT_ORDER_FAIL:{e}"
                    pos.updated_ts = time.time()

                    log.error(
                        "❌ EXIT_ORDER_FAIL | user=%s trade=%s symbol=%s reason=%s err=%s | %s",
                        self.user_id,
                        pos.trade_id,
                        symbol,
                        reason,
                        e,
                        _fmt_pos(pos),
                    )

                    try:
                        await self.store.upsert_position(self.user_id, symbol, pos.to_public())
                    except Exception as e2:
                        log.debug("📝 EXIT_UPSERT_FAIL3 | user=%s symbol=%s err=%s", self.user_id, symbol, e2)

                finally:
                    try:
                        await self.store.clear_open(self.user_id, symbol)
                        log.info("🧹 CLEAR_OPEN_OK | user=%s trade=%s symbol=%s", self.user_id, pos.trade_id, symbol)
                    except Exception as e:
                        log.warning("🧹 CLEAR_OPEN_FAIL | user=%s trade=%s symbol=%s err=%s", self.user_id, pos.trade_id, symbol, e)

            finally:
                try:
                    await self.store.release_lock(self.user_id, symbol, "exit")
                    log.debug("🔓 EXIT_LOCK_RELEASED | user=%s symbol=%s", self.user_id, symbol)
                except Exception as e:
                    log.debug("🔓 EXIT_LOCK_RELEASE_FAIL | user=%s symbol=%s err=%s", self.user_id, symbol, e)

        finally:
            self._exit_inflight[symbol] = False
            self._exit_signal_sent[symbol] = False
            log.debug("🏁 EXIT_DONE | user=%s symbol=%s", self.user_id, symbol)

    async def exit_all_open_positions(self, reason: str = "AUTO_SQ_OFF") -> int:
        """
        Trigger exit for ALL open positions (e.g. at 3:15 PM).
        Returns number of positions triggered.
        """
        count = 0
        # Snapshot keys to avoid runtime dict change errors if async
        symbols = [s for s, p in self.positions.items() if p.status == "OPEN"]
        
        if not symbols:
            log.warning("⏰ EXIT_ALL_SKIP | user=%s reason=%s | No OPEN positions found in memory. Total tracked=%s", 
                        self.user_id, reason, len(self.positions))
            return 0

        # 🛑 KILL SWITCH CHECK
        if await self.store.is_kill(self.user_id):
            log.error("🛑 KILL_SWITCH_ACTIVE | user=%s | Rejecting exit_all for reason=%s", self.user_id, reason)
            # Return 0 as no positions will be exited
            return 0

        log.info("⏰ EXIT_ALL_TRIGGER | user=%s reason=%s count=%s symbols=%s", self.user_id, reason, len(symbols), symbols)

        for sym in symbols:
            # fire and forget exits (they have their own locks/logging)
            asyncio.create_task(self._exit_position(sym, reason))
            count += 1
        
        return count

