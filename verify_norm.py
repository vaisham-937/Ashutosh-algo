
import asyncio
import sys
import os

# Add app to path
sys.path.append(os.getcwd())

from app.redis_store import norm_symbol as redis_norm
from app.chartink_client import normalize_symbol as client_norm
# from app.trade_engine import _safe_symbol as engine_norm 
# engine_norm is internal, but it calls redis_norm directly now in my update.

def test_normalization():
    test_cases = [
        ("NSE:SBIN", "SBIN"),
        ("SBIN-EQ", "SBIN"),
        ("  INFY  ", "INFY"),
        ("M&M", "M&M"),
        ("BAJAJ-AUTO", "BAJAJ-AUTO"),
        ("NIFTY BANK", "NIFTY BANK"),
        ("NSE:NIFTY BANK", "NIFTY BANK"),
    ]

    print(f"{'Input':<20} | {'Redis':<15} | {'Client':<15} | {'Match'}")
    print("-" * 65)

    all_pass = True
    for raw, expected in test_cases:
        r = redis_norm(raw)
        c = client_norm(raw)
        match = (r == c == expected)
        print(f"{raw:<20} | {r:<15} | {c:<15} | {match}")
        if not match:
            all_pass = False

    if all_pass:
        print("\n✅ All normalization tests passed!")
    else:
        print("\n❌ Some tests failed!")

if __name__ == "__main__":
    test_normalization()
