# app/main.py
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Template

from kiteconnect import KiteConnect, KiteTicker

from .redis_store import RedisStore
from .chartink_client import parse_chartink_payload
from .trade_engine import TradeEngine
from .websocket_manager import WebSocketManager

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

app = FastAPI(title="AlgoEdge Ultra-Low Latency")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

ws_mgr = WebSocketManager()
store = RedisStore(REDIS_URL)

# single-user demo; extend to multi-user easily
ENGINE: Dict[int, TradeEngine] = {}

# ---------------- Marketdata (KiteTicker) ----------------
KT: Optional[KiteTicker] = None
KT_TASK: Optional[asyncio.Task] = None
SUB_TOKENS: set[int] = set()
TOKEN_TO_SYMBOL: Dict[int, str] = {}

# quick instrument cache (symbol->token). In production, load from instruments dump once.
SYMBOL_TOKEN: Dict[str, int] = {}


async def ensure_engine(user_id: int) -> TradeEngine:
    if user_id not in ENGINE:
        ENGINE[user_id] = TradeEngine(user_id=user_id, store=store)
        await ENGINE[user_id].configure_kite()
    return ENGINE[user_id]


def _read_dashboard_template(user_id: int, username: str) -> str:
    with open("app/static/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()
    t = Template(html)
    return t.render(USER_ID=user_id, USERNAME=username)


@app.on_event("startup")
async def startup() -> None:
    await store.init_scripts()


# ---------------- Dashboard ----------------
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(user_id: int = 1) -> str:
    return _read_dashboard_template(user_id=user_id, username=f"user{user_id}")


# ---------------- Credentials + Kite login ----------------
@app.post("/api/save-credentials")
async def save_credentials(payload: Dict[str, Any]) -> Dict[str, Any]:
    user_id = int(payload.get("user_id", 1))
    api_key = str(payload.get("api_key", "")).strip()
    api_secret = str(payload.get("api_secret", "")).strip()
    if not api_key or not api_secret:
        return {"error": "API_KEY_SECRET_REQUIRED"}
    await store.save_credentials(user_id, api_key, api_secret)
    return {"ok": True}


@app.get("/connect/zerodha")
async def connect_zerodha(user_id: int = 1):
    creds = await store.load_credentials(user_id)
    api_key = creds.get("api_key", "")
    api_secret = creds.get("api_secret", "")
    if not api_key or not api_secret:
        return RedirectResponse(url="/dashboard?user_id=1")

    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()
    return RedirectResponse(url=login_url)


@app.get("/zerodha/callback")
async def zerodha_callback(request: Request, user_id: int = 1):
    creds = await store.load_credentials(user_id)
    api_key = creds.get("api_key", "")
    api_secret = creds.get("api_secret", "")
    if not api_key or not api_secret:
        return RedirectResponse(url=f"/dashboard?user_id={user_id}")

    request_token = request.query_params.get("request_token", "")
    if not request_token:
        return RedirectResponse(url=f"/dashboard?user_id={user_id}")

    kite = KiteConnect(api_key=api_key)
    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data["access_token"]
    await store.save_access_token(user_id, access_token)

    # reconfigure engine
    eng = await ensure_engine(user_id)
    await eng.configure_kite()

    # start ticker if not running
    await start_kite_ticker(user_id)

    return RedirectResponse(url=f"/dashboard?user_id={user_id}")


@app.get("/api/zerodha-status")
async def zerodha_status(user_id: int = 1) -> Dict[str, Any]:
    creds = await store.load_credentials(user_id)
    at = await store.load_access_token(user_id)
    connected = bool(creds.get("api_key")) and bool(at)
    return {"connected": connected}


# ---------------- Alert Config ----------------
@app.get("/api/alert-config")
async def list_alert_config(user_id: int = 1) -> Dict[str, Any]:
    cfg = await store.list_alert_configs(user_id)
    return {"configs": cfg}


@app.post("/api/alert-config")
async def save_alert_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    user_id = int(payload.get("user_id", 1))
    alert_name = str(payload.get("alert_name", "")).strip()
    if not alert_name:
        return {"error": "ALERT_NAME_REQUIRED"}
    await store.set_alert_config(user_id, alert_name, payload)
    return {"ok": True}


# ---------------- Chartink webhook ----------------
@app.post("/webhook/chartink")
async def chartink_webhook(payload: Dict[str, Any], user_id: int = 1) -> Dict[str, Any]:
    eng = await ensure_engine(user_id)

    alert_name, symbols, ts = parse_chartink_payload(payload)

    # subscribe all symbols for ticks (ultra-fast monitoring)
    await subscribe_symbols_for_user(user_id, symbols)

    # process alert → enter trades as per config
    res = await eng.on_chartink_alert(alert_name, symbols)

    # push alert event instantly to UI
    await ws_mgr.broadcast(user_id, {
        "type": "alert",
        "alert_name": alert_name,
        "time": ts,
        "symbols": symbols,
        "result": res,
    })
    return {"ok": True, "alert": alert_name, "symbols": symbols, "result": res}


# ---------------- Positions ----------------
@app.get("/api/positions")
async def api_positions(user_id: int = 1) -> Dict[str, Any]:
    rows = await store.list_positions(user_id)
    return {"positions": rows}


@app.post("/api/position/squareoff")
async def api_squareoff(payload: Dict[str, Any]) -> Dict[str, Any]:
    user_id = int(payload.get("user_id", 1))
    symbol = str(payload.get("symbol", "")).strip().upper()
    eng = await ensure_engine(user_id)
    r = await eng.manual_squareoff(symbol, reason="MANUAL")
    await ws_mgr.broadcast(user_id, {"type": "pos_refresh"})
    return r


# ---------------- Kill switch ----------------
@app.post("/api/kill-switch")
async def api_kill(payload: Dict[str, Any]) -> Dict[str, Any]:
    user_id = int(payload.get("user_id", 1))
    enabled = bool(payload.get("enabled", True))
    await store.set_kill(user_id, enabled)
    return {"ok": True, "enabled": enabled}


# ---------------- WebSocket feed (ticks + alerts + positions) ----------------
@app.websocket("/ws/feed")
async def ws_feed(ws: WebSocket, user_id: int = 1):
    await ws_mgr.connect(user_id, ws)
    try:
        while True:
            # keep alive / accept client pings
            await ws.receive_text()
    except WebSocketDisconnect:
        await ws_mgr.disconnect(user_id, ws)
    except Exception:
        await ws_mgr.disconnect(user_id, ws)


# ---------------- KiteTicker integration ----------------
async def subscribe_symbols_for_user(user_id: int, symbols: List[str]) -> None:
    # resolve tokens from redis cache if available; else skip (you can plug instruments lookup here)
    for s in symbols:
        s = s.strip().upper()
        if not s:
            continue
        tok = await store.get_symbol_token(s)
        if tok:
            SYMBOL_TOKEN[s] = tok
            TOKEN_TO_SYMBOL[tok] = s
            SUB_TOKENS.add(tok)

    # if ticker running, update subscriptions
    if KT:
        try:
            KT.subscribe(list(SUB_TOKENS))
            KT.set_mode(KT.MODE_LTP, list(SUB_TOKENS))
        except Exception:
            pass


async def start_kite_ticker(user_id: int) -> None:
    global KT, KT_TASK

    if KT is not None:
        return

    creds = await store.load_credentials(user_id)
    api_key = creds.get("api_key", "")
    access_token = await store.load_access_token(user_id)
    if not api_key or not access_token:
        return

    kt = KiteTicker(api_key, access_token)
    KT = kt

    def on_ticks(ws, ticks):
        # ticks -> push to engine + websocket
        # ultra-fast: only minimal parse
        async def _handle():
            eng = await ensure_engine(user_id)
            for t in ticks or []:
                tok = int(t.get("instrument_token", 0))
                sym = TOKEN_TO_SYMBOL.get(tok)
                if not sym:
                    continue
                ltp = float(t.get("last_price") or 0.0)
                ohlc = t.get("ohlc") or {}
                close = float(ohlc.get("close") or 0.0)
                high = float(ohlc.get("high") or ltp)
                low = float(ohlc.get("low") or ltp)
                tbq = float(t.get("buy_quantity") or 0.0)
                tsq = float(t.get("sell_quantity") or 0.0)

                pos = await eng.on_tick(sym, ltp, close, high, low, tbq, tsq)

                await ws_mgr.broadcast(user_id, {
                    "type": "tick",
                    "symbol": sym,
                    "ltp": ltp,
                    "close": close,
                    "high": high,
                    "low": low,
                    "tbq": tbq,
                    "tsq": tsq,
                })

                if pos:
                    await store.upsert_position(user_id, sym, pos.to_public())
                    await ws_mgr.broadcast(user_id, {"type": "pos", "position": pos.to_public()})

        asyncio.get_event_loop().create_task(_handle())

    def on_connect(ws, response):
        if SUB_TOKENS:
            ws.subscribe(list(SUB_TOKENS))
            ws.set_mode(ws.MODE_LTP, list(SUB_TOKENS))

    kt.on_ticks = on_ticks
    kt.on_connect = on_connect

    # run ticker in thread so FastAPI loop stays clean
    def _run():
        kt.connect(threaded=True)

    loop = asyncio.get_running_loop()
    KT_TASK = loop.run_in_executor(None, _run)
