# app/main.py
from __future__ import annotations

import asyncio
import os
import time
import pytz
import datetime

from typing import Any, Dict, List, Optional, Set, Tuple
from fastapi import HTTPException
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Template
from kiteconnect import KiteConnect, KiteTicker 
from .redis_store import RedisStore
from .chartink_client import (
    parse_chartink_payload,
    normalize_alert_name,
    normalize_symbols,
    normalize_symbol,
)
from .trade_engine import TradeEngine
from .websocket_manager import WebSocketManager
from .stock_sector import STOCK_INDEX_MAPPING
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# make sure your module loggers show INFO
logging.getLogger("trade_engine").setLevel(logging.INFO)
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("uvicorn.error").setLevel(logging.INFO)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)

# -----------------------------
# Config
# -----------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

app = FastAPI(title="AlgoEdge Ultra-Low Latency")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # change in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ws_mgr = WebSocketManager()
store = RedisStore(REDIS_URL)

# Engines per user
ENGINE: Dict[int, TradeEngine] = {}

# -----------------------------
# KiteTicker globals (single ticker)
# -----------------------------
KT: Optional[KiteTicker] = None
KT_CONNECTED: bool = False
KT_TASK: Optional[asyncio.Future] = None
KT_LOCK = asyncio.Lock()

KT_USER_ID: Optional[int] = None
KT_ACCESS_TOKEN: str = ""

APP_LOOP: Optional[asyncio.AbstractEventLoop] = None

# Subscriptions + token map
SUB_TOKENS: Set[int] = set()
TOKEN_TO_SYMBOL: Dict[int, str] = {}
SYMBOL_TOKEN: Dict[str, int] = {}

# If webhook arrives before instruments map is loaded, we queue symbols here
PENDING_SYMBOLS: Dict[int, Set[str]] = {}
INSTR_LOCK = asyncio.Lock()

# Zerodha session validity cache (avoid calling profile() every 5s)
_SESSION_CACHE: Dict[int, Dict[str, Any]] = {}  # user_id -> {"ok": bool, "ts": float}
_SESSION_CACHE_TTL = 30.0  # seconds

# Throttle Redis position writes (per symbol)
_LAST_POS_SAVE: Dict[Tuple[int, str], float] = {}
_POS_SAVE_THROTTLE_SEC = 0.8


# -----------------------------
# Helpers
# -----------------------------
def _read_dashboard_template(user_id: int, username: str) -> str:
    with open("app/static/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()
    t = Template(html)
    return t.render(USER_ID=user_id, USERNAME=username)


def _kite_client(api_key: str, access_token: str) -> KiteConnect:
    k = KiteConnect(api_key=api_key)
    k.set_access_token(access_token)
    return k


def _sym_safe(x: Any) -> str:
    """
    Strong symbol normalizer (extra-safe).
    Your chartink_client.normalize_symbol should already do this,
    but this protects you from SBIN-EQ / NSE:SBIN / SBIN.NS, etc.
    """
    s = normalize_symbol(x)
    s = (s or "").strip().upper()

    # common suffix/prefix cleanups (idempotent if already clean)
    if ":" in s:
        s = s.split(":", 1)[1].strip()

    if s.endswith(".NS"):
        s = s[:-3]

    if s.endswith("-EQ"):
        s = s[:-3]

    # final cleanup
    s = "".join(s.split())
    return s


async def is_session_valid(user_id: int) -> bool:
    """
    Dashboard polls every 5s. Cache validity for short TTL.
    """
    now = time.time()
    cached = _SESSION_CACHE.get(user_id)
    if cached and (now - float(cached.get("ts", 0.0)) < _SESSION_CACHE_TTL):
        return bool(cached.get("ok", False))

    creds = await store.load_credentials(user_id)
    at = (await store.load_access_token(user_id)).strip()
    api_key = (creds.get("api_key") or "").strip()

    if not api_key or not at:
        _SESSION_CACHE[user_id] = {"ok": False, "ts": now}
        return False

    try:
        kite = _kite_client(api_key, at)
        kite.profile()  # validates access_token
        _SESSION_CACHE[user_id] = {"ok": True, "ts": now}
        return True
    except Exception:
        _SESSION_CACHE[user_id] = {"ok": False, "ts": now}
        return False


# async def ensure_engine(user_id: int) -> TradeEngine:
#     user_id = int(user_id)
#     if user_id not in ENGINE:
#         ENGINE[user_id] = TradeEngine(user_id=user_id, store=store)
#         await ENGINE[user_id].configure_kite()
#     return ENGINE[user_id]
async def ensure_engine(user_id: int) -> TradeEngine:
    user_id = int(user_id)
    if user_id not in ENGINE:
        ENGINE[user_id] = TradeEngine(user_id=user_id, store=store)
        await ENGINE[user_id].configure_kite()

        # ✅ Restore open positions after restart
        restored = await ENGINE[user_id].rehydrate_open_positions()
        if restored:
            # ✅ Ensure ticks come for these symbols
            asyncio.create_task(subscribe_symbols_for_user(user_id, restored))

    return ENGINE[user_id]



# -----------------------------
# Instruments (symbol -> token)
# -----------------------------
async def build_symbol_token_map_from_kite(user_id: int) -> bool:
    """
    Download NSE instruments once after login and keep in memory.
    Heavy operation: never do this in the webhook hot path unless unavoidable.
    """
    user_id = int(user_id)

    creds = await store.load_credentials(user_id)
    api_key = (creds.get("api_key") or "").strip()
    access_token = (await store.load_access_token(user_id)).strip()
    if not api_key or not access_token:
        print("[INSTR] Missing api_key/access_token; cannot load instruments")
        return False

    try:
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)

        print("[INSTR] Downloading NSE instruments...")
        instruments = kite.instruments("NSE")  # list[dict]

        SYMBOL_TOKEN.clear()
        TOKEN_TO_SYMBOL.clear()

        for ins in instruments or []:
            sym = _sym_safe(ins.get("tradingsymbol", ""))
            tok = ins.get("instrument_token")
            if sym and tok:
                itok = int(tok)
                SYMBOL_TOKEN[sym] = itok
                TOKEN_TO_SYMBOL[itok] = sym

        print(f"[INSTR] Loaded {len(SYMBOL_TOKEN)} NSE symbols into memory")
        return True
    except Exception as e:
        print("[INSTR] instruments download failed:", e)
        return False


async def _ensure_token_map_ready(user_id: int) -> None:
    """
    Ensures SYMBOL_TOKEN is available.
    If webhook comes early, we build map in background and then subscribe pending symbols.
    """
    user_id = int(user_id)

    if SYMBOL_TOKEN:
        # already ready
        return

    async with INSTR_LOCK:
        # double-check after acquiring lock
        if SYMBOL_TOKEN:
            return

        ok = await is_session_valid(user_id)
        if not ok:
            return

        built = await build_symbol_token_map_from_kite(user_id)
        if not built:
            return

    # after map is ready, subscribe pending symbols
    pending = list(PENDING_SYMBOLS.get(user_id, set()))
    if pending:
        await subscribe_symbols_for_user(user_id, pending)
        PENDING_SYMBOLS[user_id] = set()


# -----------------------------
# Subscriptions
# -----------------------------
async def subscribe_symbols_for_user(user_id: int, symbols: List[str]) -> None:
    """
    Adds tokens to SUB_TOKENS and subscribes if KiteTicker is running.

    Key behaviors:
    - If token map is not ready, queue symbols and build map in background.
    - Uses MODE_FULL to receive OHLC (close/high/low) and quantities.
    """
    user_id = int(user_id)
    if not symbols:
        return

    # Normalize symbols up-front
    norm_syms: List[str] = []
    for s in symbols:
        sym = _sym_safe(s)
        if sym:
            norm_syms.append(sym)

    if not norm_syms:
        return

    # If token map is not ready, queue and kick off background build (non-blocking).
    if not SYMBOL_TOKEN:
        PENDING_SYMBOLS.setdefault(user_id, set()).update(norm_syms)
        asyncio.create_task(_ensure_token_map_ready(user_id))
        # Do not block webhook here.
        return

    changed = False
    for sym in norm_syms:
        tok = SYMBOL_TOKEN.get(sym)
        if not tok:
            print(f"[TOKEN MISSING] {sym}  (common cause: symbol format like SBIN-EQ)")
            continue

        if tok not in SUB_TOKENS:
            SUB_TOKENS.add(tok)
            changed = True

        TOKEN_TO_SYMBOL[int(tok)] = sym

    # Update live ticker subscriptions if running
    if changed and KT and KT_CONNECTED and SUB_TOKENS:
        try:
            KT.subscribe(list(SUB_TOKENS))
            # FULL mode gives ohlc.close/high/low etc
            KT.set_mode(KT.MODE_FULL, list(SUB_TOKENS))
            print(f"[SUB] subscribed tokens={len(SUB_TOKENS)} mode=FULL")
        except Exception as e:
            print("[SUB] subscribe failed:", e)


# -----------------------------
# KiteTicker start / restart
# -----------------------------
async def _stop_kite_ticker() -> None:
    global KT, KT_CONNECTED, KT_TASK, KT_USER_ID, KT_ACCESS_TOKEN
    try:
        if KT is not None:
            try:
                KT.close()  # KiteTicker supports close()
            except Exception:
                pass
    finally:
        KT = None
        KT_CONNECTED = False
        KT_TASK = None
        KT_USER_ID = None
        KT_ACCESS_TOKEN = ""


async def start_kite_ticker(user_id: int) -> None:
    """
    Starts a single KiteTicker (threaded=True) and routes ticks back into FastAPI loop.
    Uses MODE_FULL for OHLC + quantities.
    """
    global KT, KT_TASK, KT_CONNECTED, KT_USER_ID, KT_ACCESS_TOKEN

    user_id = int(user_id)

    async with KT_LOCK:
        creds = await store.load_credentials(user_id)
        api_key = (creds.get("api_key") or "").strip()
        access_token = (await store.load_access_token(user_id)).strip()

        if not api_key or not access_token:
            print("[KT] missing api_key/access_token; ticker not started")
            return

        # If ticker already running but token changed, restart it
        if KT is not None:
            if (KT_USER_ID != user_id) or (KT_ACCESS_TOKEN != access_token):
                print("[KT] access token changed -> restarting ticker")
                await _stop_kite_ticker()
            else:
                return  # already running with same creds

        kt = KiteTicker(api_key, access_token)
        KT = kt
        KT_USER_ID = user_id
        KT_ACCESS_TOKEN = access_token

        def on_connect(ws, response):
            global KT_CONNECTED
            KT_CONNECTED = True
            try:
                if SUB_TOKENS:
                    ws.subscribe(list(SUB_TOKENS))
                    ws.set_mode(ws.MODE_FULL, list(SUB_TOKENS))
            except Exception as e:
                print("[KT] subscribe on_connect failed:", e)
            print("[KT] connected, subs:", len(SUB_TOKENS), "mode=FULL")

        def on_close(ws, code, reason):
            global KT_CONNECTED
            KT_CONNECTED = False
            print("[KT] closed", code, reason)

        def on_error(ws, code, reason):
            print("[KT] error", code, reason)

        def on_ticks(ws, ticks):
            loop = APP_LOOP
            if loop is None:
                return

            async def _handle():
                eng = await ensure_engine(user_id)

                for t in ticks or []:
                    try:
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

                        # Feed engine with proper OHLC (important for sector ranking)
                        pos = await eng.on_tick(sym, ltp, close, high, low, tbq, tsq)

                        # UI tick push (non-blocking)
                        ws_mgr.broadcast_nowait(
                            user_id,
                            {
                                "type": "tick",
                                "symbol": sym,
                                "ltp": ltp,
                                "close": close,
                                "high": high,
                                "low": low,
                                "tbq": tbq,
                                "tsq": tsq,
                            },
                        )

                        # Throttle Redis writes for positions
                        if pos:
                            key = (user_id, sym)
                            now = time.time()
                            last = _LAST_POS_SAVE.get(key, 0.0)
                            if now - last >= _POS_SAVE_THROTTLE_SEC:
                                _LAST_POS_SAVE[key] = now
                                asyncio.create_task(store.upsert_position(user_id, sym, pos.to_public()))
                                ws_mgr.broadcast_nowait(user_id, {"type": "pos", "position": pos.to_public()})

                    except Exception as e:
                        print("[KT] tick handle error:", e)

            asyncio.run_coroutine_threadsafe(_handle(), loop)

        kt.on_connect = on_connect
        kt.on_close = on_close
        kt.on_error = on_error
        kt.on_ticks = on_ticks

        def on_order_update(ws, data):
            loop = APP_LOOP
            if loop is None:
                return

            async def _handle_ou():
                try:
                    eng = await ensure_engine(user_id)
                    await eng.on_order_update(data)  # <-- add this method in TradeEngine
                except Exception as e:
                    print("[KT] order_update handle error:", e)

            asyncio.run_coroutine_threadsafe(_handle_ou(), loop)

        kt.on_order_update = on_order_update


        def _run():
            kt.connect(threaded=True)

        loop = asyncio.get_running_loop()
        KT_TASK = loop.run_in_executor(None, _run)
        print("[KT] connect thread started")


# -----------------------------
# Startup
# -----------------------------
@app.on_event("startup")
async def startup():
    global APP_LOOP
    APP_LOOP = asyncio.get_running_loop()
    ws_mgr.set_loop(APP_LOOP)

    await store.init_scripts()

    # Auto-start if already logged in
    try:
        ok = await is_session_valid(1)
        if ok:
            async with INSTR_LOCK:
                if not SYMBOL_TOKEN:
                    await build_symbol_token_map_from_kite(1)

            base_symbols = list(STOCK_INDEX_MAPPING.keys())
            await subscribe_symbols_for_user(1, base_symbols)
            await start_kite_ticker(1)

            eng = await ensure_engine(1)
            await eng.configure_kite()
    except Exception as e:
        print("[startup] auto-start failed:", e)


# -----------------------------
# Dashboard
# -----------------------------
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(user_id: int = 1) -> str:
    return _read_dashboard_template(user_id=user_id, username=f"user{int(user_id)}")


# -----------------------------
# Credentials + Kite login
# -----------------------------
@app.post("/api/save-credentials")
async def save_credentials(payload: Dict[str, Any]) -> Dict[str, Any]:
    user_id = int(payload.get("user_id", 1))
    api_key = str(payload.get("api_key", "")).strip()
    api_secret = str(payload.get("api_secret", "")).strip()
    if not api_key or not api_secret:
        return {"error": "API_KEY_SECRET_REQUIRED"}

    await store.save_credentials(user_id, api_key, api_secret)
    _SESSION_CACHE.pop(user_id, None)
    return {"ok": True}


@app.get("/connect/zerodha")
async def connect_zerodha(user_id: int = 1):
    user_id = int(user_id)
    creds = await store.load_credentials(user_id)
    api_key = (creds.get("api_key") or "").strip()
    api_secret = (creds.get("api_secret") or "").strip()
    if not api_key or not api_secret:
        return RedirectResponse(url=f"/dashboard?user_id={user_id}")

    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()
    return RedirectResponse(url=login_url)


@app.get("/zerodha/callback")
async def zerodha_callback(request: Request, user_id: int = 1):
    user_id = int(user_id)

    creds = await store.load_credentials(user_id)
    api_key = (creds.get("api_key") or "").strip()
    api_secret = (creds.get("api_secret") or "").strip()
    if not api_key or not api_secret:
        return RedirectResponse(url=f"/dashboard?user_id={user_id}")

    request_token = request.query_params.get("request_token", "") or ""
    if not request_token.strip():
        return RedirectResponse(url=f"/dashboard?user_id={user_id}")

    kite = KiteConnect(api_key=api_key)
    data = kite.generate_session(request_token.strip(), api_secret=api_secret)
    access_token = str(data.get("access_token") or "").strip()

    await store.save_access_token(user_id, access_token)
    _SESSION_CACHE.pop(user_id, None)

    # Build instruments map
    async with INSTR_LOCK:
        await build_symbol_token_map_from_kite(user_id)

    # Subscribe base universe (for sector ranking)
    base_symbols = list(STOCK_INDEX_MAPPING.keys())
    await subscribe_symbols_for_user(user_id, base_symbols)

    # Subscribe any pending symbols that arrived via webhook earlier
    pending = list(PENDING_SYMBOLS.get(user_id, set()))
    if pending:
        await subscribe_symbols_for_user(user_id, pending)
        PENDING_SYMBOLS[user_id] = set()

    # Start / restart ticker
    await start_kite_ticker(user_id)

    # Ensure engine has latest access token
    eng = await ensure_engine(user_id)
    await eng.configure_kite()

    return RedirectResponse(url=f"/dashboard?user_id={user_id}")


@app.get("/api/zerodha-status")
async def zerodha_status(user_id: int = 1) -> Dict[str, Any]:
    user_id = int(user_id)
    ok = await is_session_valid(user_id)
    return {"connected": ok}


# -----------------------------
# Alert Config
# -----------------------------
@app.get("/api/alert-config")
async def list_alert_config(user_id: int = 1) -> Dict[str, Any]:
    user_id = int(user_id)
    cfg = await store.list_alert_configs(user_id)
    return {"configs": cfg}


@app.post("/api/alert-config")
async def save_alert_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    user_id = int(payload.get("user_id", 1))
    raw_name = payload.get("alert_name", "")
    if not raw_name or not str(raw_name).strip():
        return {"error": "ALERT_NAME_REQUIRED"}

    # Normalize key consistently
    alert_name = normalize_alert_name(raw_name)

    payload2 = dict(payload)
    payload2["alert_name"] = alert_name
    payload2["alert_name_raw"] = str(raw_name)

    await store.set_alert_config(user_id, alert_name, payload2)
    return {"ok": True, "alert_name": alert_name}


# -----------------------------
# Chartink webhook
# -----------------------------
@app.post("/webhook/chartink")
async def chartink_webhook(request: Request, user_id: int = 1) -> Dict[str, Any]:
    user_id = int(user_id)
    eng = await ensure_engine(user_id)

    payload: Dict[str, Any] = {}
    content_type = (request.headers.get("content-type") or "").lower()

    # 1) JSON
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    else:
        # 2) form-data / urlencoded
        try:
            form = await request.form()
            if form:
                payload = dict(form)
        except Exception:
            payload = {}

        # 3) raw text might be JSON
        if not payload:
            try:
                raw = (await request.body() or b"").decode("utf-8", errors="ignore").strip()
                if raw.startswith("{") and raw.endswith("}"):
                    import json as _json
                    payload = _json.loads(raw)
            except Exception:
                payload = {}

    alert_name_raw, symbols_raw, ts = parse_chartink_payload(payload)
    alert_name = normalize_alert_name(alert_name_raw)

    # normalize symbols (and also force extra-safe cleanup)
    symbols0 = normalize_symbols(symbols_raw)
    symbols = [_sym_safe(s) for s in symbols0 if _sym_safe(s)]

    # Subscribe symbols for ticks (non-blocking)
    asyncio.create_task(subscribe_symbols_for_user(user_id, symbols))

    # Process alert -> orders
    res = await eng.on_chartink_alert(alert_name, symbols)

    alert_data = {
        "type": "alert",
        "alert_name": alert_name,
        "time": ts,
        "symbols": symbols,
        "result": res,
    }
    print(f"📥 Chartink alert_data → {alert_data}")

    # Push to UI
    await ws_mgr.broadcast(user_id, alert_data)

    # Store alert history in background
    asyncio.create_task(store.save_alert(user_id, alert_data))

    return {
        "ok": True,
        "alert": alert_name,
        "symbols": symbols,
        "result": res,
        "content_type": content_type,
    }


# -----------------------------
# Alerts
# -----------------------------
@app.get("/api/alerts")
async def api_alerts(user_id: int = 1, limit: int = 100) -> Dict[str, Any]:
    user_id = int(user_id)
    alerts = await store.get_recent_alerts(user_id, int(limit))
    return {"alerts": alerts}


# -----------------------------
# Positions
# -----------------------------
@app.get("/api/positions")
async def api_positions(user_id: int = 1) -> Dict[str, Any]:
    user_id = int(user_id)
    rows = await store.list_positions(user_id)
    return {"positions": rows}


#-----------------------------
# Square Off positions
# -----------------------------
@app.post("/api/position/squareoff")
async def api_squareoff(payload: Dict[str, Any]) -> Dict[str, Any]:
    user_id = int(payload.get("user_id", 1))
    raw_symbol = payload.get("symbol", "")
    symbol = _sym_safe(raw_symbol)
    reason = str(payload.get("reason", "MANUAL") or "MANUAL").strip().upper()

    if not symbol:
        raise HTTPException(status_code=400, detail={"error": "BAD_SYMBOL", "raw": raw_symbol})

    eng = await ensure_engine(user_id)

    print(f"🖱️ [SQUAREOFF_CLICK] user={user_id} raw='{raw_symbol}' sym='{symbol}' reason={reason}")

    ok = await is_session_valid(user_id)
    if not ok:
        raise HTTPException(status_code=400, detail={"error": "ZERODHA_NOT_CONNECTED"})

    # ✅ Works even after restart (memory -> Zerodha fallback)
    r = await eng.manual_squareoff_zerodha(symbol, reason=reason)

    print(f"🧾 [SQUAREOFF_RESULT] user={user_id} sym={symbol} -> {r}")
    ws_mgr.broadcast_nowait(user_id, {"type": "pos_refresh"})
    return r


# -----------------------------
# Kill switch
# -----------------------------
@app.post("/api/kill-switch")
async def api_kill(payload: Dict[str, Any]) -> Dict[str, Any]:
    user_id = int(payload.get("user_id", 1))
    enabled = bool(payload.get("enabled", True))
    await store.set_kill(user_id, enabled)
    return {"ok": True, "enabled": enabled}


# -----------------------------
# WebSocket feed
# -----------------------------
@app.websocket("/ws/feed")
async def ws_feed(ws: WebSocket, user_id: int = 1):
    user_id = int(user_id)
    await ws_mgr.connect(user_id, ws)
    try:
        while True:
            # Keep-alive from client (dashboard sends ping)
            await ws.receive_text()
    except WebSocketDisconnect:
        await ws_mgr.disconnect(user_id, ws)
    except Exception:
        await ws_mgr.disconnect(user_id, ws)
