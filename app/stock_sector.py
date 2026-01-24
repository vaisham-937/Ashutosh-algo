# app/stock_sector.py
"""
stock_sector.py

Purpose:
- Provide STOCK_INDEX_MAPPING used by TradeEngine sector filter and by main.py base universe.
- Keep keys as NSE trading symbols (uppercase).
- Includes a small normalization helper so symbols like "M&M" / "BAJAJ-AUTO" stay consistent.

Notes:
- Your TradeEngine currently does: self.sym_sector: Dict[str, str] = STOCK_INDEX_MAPPING
  so this module must export STOCK_INDEX_MAPPING as a dict[str, str].

If you want to add more symbols, just extend the dict below.
"""

from __future__ import annotations
from typing import Dict


def norm_symbol(sym: str) -> str:
    """
    Normalize incoming symbols to match keys in STOCK_INDEX_MAPPING.

    Examples:
      "NSE:ITC" -> "ITC"
      "m&m"     -> "M&M"
      "BAJAJ-AUTO" stays "BAJAJ-AUTO"
    """
    s = (sym or "").strip().upper()
    if not s:
        return ""
    # Strip exchange prefix like NSE: or BSE:
    if ":" in s:
        s = s.split(":", 1)[1].strip()

    # Keep common NSE allowed chars (includes & and -)
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-&")
    s = "".join(ch for ch in s if ch in allowed)
    return s


# -------------------------------------------------------------------
# STOCK -> INDEX / SECTOR GROUP
# -------------------------------------------------------------------
# This mapping is intentionally "sector / index group" style strings,
# not strictly NSE "index membership" only. Your sector filter uses these
# strings as "sector buckets" for ranking.
#
# You can rename values to whatever you want; just keep them consistent.
# -------------------------------------------------------------------
STOCK_INDEX_MAPPING: Dict[str, str] = {
    # =======================
    # NIFTY AUTO
    # =======================
    "TVSMOTOR": "NIFTY AUTO",
    "MARUTI": "NIFTY AUTO",
    "M&M": "NIFTY AUTO",
    "TATAMOTORS": "NIFTY AUTO",
    "BAJAJ-AUTO": "NIFTY AUTO",
    "EICHERMOT": "NIFTY AUTO",
    "HEROMOTOCO": "NIFTY AUTO",

    # =======================
    # NIFTY BANK
    # =======================
    "HDFCBANK": "NIFTY BANK",
    "ICICIBANK": "NIFTY BANK",
    "KOTAKBANK": "NIFTY BANK",
    "SBIN": "NIFTY BANK",
    "AXISBANK": "NIFTY BANK",
    "INDUSINDBK": "NIFTY BANK",

    # =======================
    # NIFTY FINANCIAL SERVICES / NBFC / INSURANCE
    # =======================
    "HDFCLIFE": "NIFTY FIN SERVICE",
    "SBILIFE": "NIFTY FIN SERVICE",
    "BAJFINANCE": "NIFTY FIN SERVICE",
    "BAJAJFINSV": "NIFTY FIN SERVICE",
    "HDFC": "NIFTY FIN SERVICE",
    "LICI": "NIFTY FIN SERVICE",

    # =======================
    # NIFTY FMCG / CONSUMER
    # =======================
    "ITC": "NIFTY FMCG",
    "HINDUNILVR": "NIFTY FMCG",
    "NESTLEIND": "NIFTY FMCG",
    "BRITANNIA": "NIFTY FMCG",
    "TATACONSUM": "NIFTY FMCG",

    # =======================
    # NIFTY IT
    # =======================
    "TCS": "NIFTY IT",
    "INFY": "NIFTY IT",
    "HCLTECH": "NIFTY IT",
    "WIPRO": "NIFTY IT",
    "TECHM": "NIFTY IT",

    # =======================
    # NIFTY PHARMA / HEALTHCARE
    # =======================
    "SUNPHARMA": "NIFTY PHARMA",
    "DRREDDY": "NIFTY PHARMA",
    "CIPLA": "NIFTY PHARMA",
    "DIVISLAB": "NIFTY PHARMA",
    "APOLLOHOSP": "NIFTY PHARMA",

    # =======================
    # NIFTY METAL
    # =======================
    "TATASTEEL": "NIFTY METAL",
    "HINDALCO": "NIFTY METAL",
    "JSWSTEEL": "NIFTY METAL",

    # =======================
    # NIFTY OIL & GAS / ENERGY
    # =======================
    "RELIANCE": "NIFTY OIL & GAS",
    "ONGC": "NIFTY OIL & GAS",

    # =======================
    # NIFTY POWER / UTILITIES
    # =======================
    "NTPC": "NIFTY POWER",
    "POWERGRID": "NIFTY POWER",

    # =======================
    # NIFTY CONSUMER DURABLES
    # =======================
    "TITAN": "NIFTY CONSUMER",
    "ASIANPAINT": "NIFTY CONSUMER",

    # =======================
    # NIFTY REALTY / CEMENT / INFRA
    # =======================
    "ULTRACEMCO": "NIFTY INFRA",
    "GRASIM": "NIFTY INFRA",
    "LT": "NIFTY INFRA",

    # =======================
    # NIFTY TELECOM / MEDIA
    # =======================
    "BHARTIARTL": "NIFTY TELECOM",

    # =======================
    # NIFTY PSU / DEFENCE / CAPITAL GOODS (bucketed)
    # =======================
    "ADANIPORTS": "NIFTY INFRA",

    # =======================
    # NIFTY CHEMICALS / SPECIALTY (bucketed)
    # =======================
    # Add your broader universe here as needed
}


def get_sector(symbol: str) -> str:
    """
    Convenience lookup that uses norm_symbol.
    Returns empty string if not found.
    """
    s = norm_symbol(symbol)
    return STOCK_INDEX_MAPPING.get(s, "")


def add_mapping(symbol: str, sector: str) -> None:
    """
    Convenience function to extend mapping at runtime.
    """
    s = norm_symbol(symbol)
    if s:
        STOCK_INDEX_MAPPING[s] = str(sector).strip()
