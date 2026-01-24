import asyncio, os, json
from app.redis_store import RedisStore, k_alert_cfg, norm_alert_name

USER_ID = 1
ALERT = "test2"   # change if needed

async def main():
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    s = RedisStore(url)

    h1 = k_alert_cfg(USER_ID)         # cfg:alerts:1
    h2 = f"u:{USER_ID}:alert_cfg"     # legacy

    print("REDIS_URL =", url)
    print("\n--- HASH 1 (new) ---", h1)
    keys1 = await s.redis.hkeys(h1)
    print("count =", len(keys1))
    print("first_keys =", keys1[:50])

    print("\n--- HASH 2 (legacy) ---", h2)
    keys2 = await s.redis.hkeys(h2)
    print("count =", len(keys2))
    print("first_keys =", keys2[:50])

    key = norm_alert_name(ALERT)
    print("\n--- LOOKUP ---")
    print("alert =", ALERT, "normalized =", key)

    raw1 = await s.redis.hget(h1, key)
    raw2 = await s.redis.hget(h2, key)

    print("\nH1 raw =", raw1)
    if raw1:
        print("H1 parsed =", json.loads(raw1))

    print("\nH2 raw =", raw2)
    if raw2:
        print("H2 parsed =", json.loads(raw2))

    await s.close()

asyncio.run(main())
