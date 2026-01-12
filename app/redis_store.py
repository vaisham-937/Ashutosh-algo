# app/redis_store.py
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, Optional, List, Tuple

import redis.asyncio as redis


# =========================
# Helpers / Keys
# =========================
def now_ist_date() -> str:
    # Simple daily key. (If you want strict IST conversion, we can adjust later.)
    return datetime.now().strftime("%Y%m%d")


def k_creds(user_id: int) -> str:
    # Stored as JSON string via SET (NOT HSET) to avoid server compatibility issues.
    return f"kite:creds:{user_id}"


def k_access(user_id: int) -> str:
    return f"kite:access:{user_id}"


def k_kill(user_id: int) -> str:
    return f"kill:{user_id}"


def k_alert_cfg(user_id: int) -> str:
    return f"cfg:alerts:{user_id}"


def k_positions(user_id: int) -> str:
    return f"positions:{user_id}"


def k_trade_open(user_id: int, symbol: str) -> str:
    return f"trade:open:{user_id}:{symbol}"


def k_lock(user_id: int, symbol: str, action: str) -> str:
    return f"lock:{user_id}:{symbol}:{action}"


def k_trade_count(user_id: int, ymd: str, alert_name: str) -> str:
    return f"trade:count:{user_id}:{ymd}:{alert_name}"


def k_symbol_token(symbol: str) -> str:
    return f"symbol_token:{symbol}"


# =========================
# Lua scripts
# =========================
LUA_LOCK = r"""
-- KEYS[1] = lock_key
-- KEYS[2] = kill_key
-- ARGV[1] = ttl_ms
-- ARGV[2] = now_ms
if redis.call('EXISTS', KEYS[2]) == 1 then
  return -2
end
if redis.call('EXISTS', KEYS[1]) == 1 then
  return 0
end
redis.call('PSETEX', KEYS[1], ARGV[1], ARGV[2])
return 1
"""

LUA_TRADE_LIMIT = r"""
-- KEYS[1] = count_key
-- ARGV[1] = limit
-- ARGV[2] = ttl_sec
local limit = tonumber(ARGV[1])
if limit <= 0 then
  return 1
end
local cur = tonumber(redis.call('GET', KEYS[1]) or "0")
if cur >= limit then
  return 0
end
cur = redis.call('INCR', KEYS[1])
if cur == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
return 1
"""


# =========================
# Store
# =========================
class RedisStore:
    """
    Notes:
    - Credentials are stored using SET JSON at key kite:creds:{user_id}
      This avoids old Redis/Memurai incompatibilities with HSET argument formats.
    - Alert configs, positions: stored in HASH (hset field value) -> safe.
    """

    def __init__(self, redis_url: str) -> None:
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self._sha_lock: Optional[str] = None
        self._sha_limit: Optional[str] = None

    async def init_scripts(self) -> None:
        self._sha_lock = await self.redis.script_load(LUA_LOCK)
        self._sha_limit = await self.redis.script_load(LUA_TRADE_LIMIT)

    # =========================
    # Lock + trade limit
    # =========================
    async def acquire_lock(self, user_id: int, symbol: str, action: str, ttl_ms: int = 1200) -> int:
        """
        Return:
          1 acquired
          0 busy
         -2 kill switch active
        """
        if not self._sha_lock:
            await self.init_scripts()

        now_ms = int(time.time() * 1000)
        return int(
            await self.redis.evalsha(
                self._sha_lock,
                2,
                k_lock(user_id, symbol, action),
                k_kill(user_id),
                str(ttl_ms),
                str(now_ms),
            )
        )

    async def allow_trade(self, user_id: int, alert_name: str, limit: int) -> bool:
        """
        Per user + per day + per alert limit
        limit <= 0 => allow always
        """
        if not self._sha_limit:
            await self.init_scripts()

        ymd = now_ist_date()
        ttl = 60 * 60 * 30  # ~30 hours (covers full day rollover safely)
        res = int(
            await self.redis.evalsha(
                self._sha_limit,
                1,
                k_trade_count(user_id, ymd, alert_name),
                str(int(limit)),
                str(int(ttl)),
            )
        )
        return res == 1

    # =========================
    # Kill switch
    # =========================
    async def is_kill(self, user_id: int) -> bool:
        return bool(await self.redis.get(k_kill(user_id)))

    async def set_kill(self, user_id: int, enabled: bool) -> None:
        if enabled:
            await self.redis.setex(k_kill(user_id), 60 * 60 * 24, "1")
        else:
            await self.redis.delete(k_kill(user_id))

    # =========================
    # Credentials (FIXED: SET JSON)
    # =========================
    async def save_credentials(self, user_id: int, api_key: str, api_secret: str) -> None:
        payload = json.dumps({"api_key": api_key, "api_secret": api_secret})
        # Optional TTL: 30 days
        # await self.redis.setex(k_creds(user_id), 60 * 60 * 24 * 30, payload)
        await self.redis.set(k_creds(user_id), payload)

    async def get_credentials(self, user_id: int) -> Tuple[Optional[str], Optional[str]]:
        raw = await self.redis.get(k_creds(user_id))
        if not raw:
            return None, None
        try:
            d = json.loads(raw)
            return d.get("api_key"), d.get("api_secret")
        except Exception:
            return None, None

    async def load_credentials(self, user_id: int) -> Dict[str, str]:
        """
        Backward compatible helper for your existing code.
        Returns dict with api_key + api_secret, empty if missing.
        """
        api_key, api_secret = await self.get_credentials(user_id)
        return {"api_key": api_key or "", "api_secret": api_secret or ""}

    # =========================
    # Access token
    # =========================
    async def save_access_token(self, user_id: int, access_token: str) -> None:
        await self.redis.set(k_access(user_id), access_token)

    async def load_access_token(self, user_id: int) -> str:
        return str(await self.redis.get(k_access(user_id)) or "")

    # =========================
    # Alert config (hash)
    # =========================
    async def set_alert_config(self, user_id: int, alert_name: str, cfg: Dict[str, Any]) -> None:
        # Use field/value form for max compatibility
        await self.redis.hset(k_alert_cfg(user_id), alert_name, json.dumps(cfg))

    async def get_alert_config(self, user_id: int, alert_name: str) -> Optional[Dict[str, Any]]:
        raw = await self.redis.hget(k_alert_cfg(user_id), alert_name)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def list_alert_configs(self, user_id: int) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        allv = await self.redis.hgetall(k_alert_cfg(user_id))
        for k, v in allv.items():
            try:
                out[k] = json.loads(v)
            except Exception:
                continue
        return out

    # =========================
    # Positions snapshot (hash)
    # =========================
    async def upsert_position(self, user_id: int, symbol: str, pos: Dict[str, Any]) -> None:
        await self.redis.hset(k_positions(user_id), symbol, json.dumps(pos))

    async def delete_position(self, user_id: int, symbol: str) -> None:
        await self.redis.hdel(k_positions(user_id), symbol)

    async def list_positions(self, user_id: int) -> List[Dict[str, Any]]:
        rows = await self.redis.hgetall(k_positions(user_id))
        out: List[Dict[str, Any]] = []
        for _sym, raw in rows.items():
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
        return out

    # =========================
    # Open-trade guard (string)
    # =========================
    async def mark_open(self, user_id: int, symbol: str, trade_id: str, ttl_sec: int = 60 * 60 * 8) -> None:
        await self.redis.setex(k_trade_open(user_id, symbol), ttl_sec, trade_id)

    async def get_open(self, user_id: int, symbol: str) -> str:
        return str(await self.redis.get(k_trade_open(user_id, symbol)) or "")

    async def clear_open(self, user_id: int, symbol: str) -> None:
        await self.redis.delete(k_trade_open(user_id, symbol))

    # =========================
    # Token cache
    # =========================
    async def set_symbol_token(self, symbol: str, token: int) -> None:
        await self.redis.set(k_symbol_token(symbol), str(int(token)))

    async def get_symbol_token(self, symbol: str) -> Optional[int]:
        v = await self.redis.get(k_symbol_token(symbol))
        if not v or not str(v).isdigit():
            return None
        return int(v)
