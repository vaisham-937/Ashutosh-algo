# app/chartink_client.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple


def parse_chartink_payload(payload: Dict[str, Any]) -> Tuple[str, List[str], str]:
    """
    Returns: (alert_name, symbols, time_str)

    Supports common Chartink webhook shapes:
    - { "scan_name": "...", "stocks": ["SBIN","TCS"], "triggered_at": "..." }
    - { "trigger_name": "...", "symbol": "SBIN" }
    - { "scan": "...", "stocks": "SBIN,TCS" }
    """
    alert = (
        payload.get("scan_name")
        or payload.get("trigger_name")
        or payload.get("scan")
        or payload.get("alert")
        or "UNKNOWN_ALERT"
    )
    alert = str(alert).strip()

    ts = payload.get("triggered_at") or payload.get("time") or payload.get("timestamp") or ""

    symbols: List[str] = []
    if "stocks" in payload:
        st = payload["stocks"]
        if isinstance(st, list):
            symbols = [str(x).strip().upper() for x in st if str(x).strip()]
        elif isinstance(st, str):
            # "SBIN,TCS"
            symbols = [s.strip().upper() for s in st.split(",") if s.strip()]
    elif "symbol" in payload:
        symbols = [str(payload["symbol"]).strip().upper()]
    elif "tradingsymbol" in payload:
        symbols = [str(payload["tradingsymbol"]).strip().upper()]

    symbols = [s for s in symbols if s and s.isalnum()]
    return alert, symbols, str(ts)
