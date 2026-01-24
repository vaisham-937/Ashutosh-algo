from kiteconnect import KiteConnect

kite = KiteConnect(api_key="e8hn0r347q9imiha")
kite.set_access_token("40bTu02X1pdE3wDpFm48d9Mk6XKjNS0D")

m = kite.margins()
print("CASH:", m["equity"]["available"].get("cash"))
print("COLLATERAL:", m["equity"]["available"].get("collateral"))
print("LIVE_BALANCE:", m["equity"]["available"].get("live_balance"))
print("UTILISED:", m["equity"].get("utilised"))
