from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .models import OTP, Session, User


class InMemoryStore:
    """
    Minimal async store used for integration tests and local development.

    This intentionally implements only the subset of RedisStore that is used by:
      - app.main routes/startup
      - app.auth.AuthService
    """

    def __init__(self) -> None:
        self._credentials: Dict[int, Dict[str, str]] = {}
        self._access_tokens: Dict[int, str] = {}
        self._kill: Dict[int, bool] = {}
        self._alert_configs: Dict[int, Dict[str, Dict[str, Any]]] = {}
        self._alerts: Dict[int, List[Dict[str, Any]]] = {}
        self._positions: Dict[int, Dict[str, Dict[str, Any]]] = {}

        self._auto_sq_off_enabled: Dict[int, bool] = {}
        self._auto_sq_off_ran_ymd: Dict[int, str] = {}

        # Auth data
        self._users_by_email: Dict[str, Dict[str, Any]] = {}
        self._user_id_by_email: Dict[str, int] = {}
        self._otp_by_email: Dict[str, Dict[str, Any]] = {}
        self._otp_requests: Dict[str, List[float]] = {}  # email -> timestamps
        self._sessions_by_token: Dict[str, Dict[str, Any]] = {}

    # -------------------------
    # Compatibility / lifecycle
    # -------------------------
    async def close(self) -> None:
        return

    async def ping(self) -> bool:
        return True

    async def init_scripts(self) -> None:
        return

    # -------------------------
    # Credentials + tokens
    # -------------------------
    async def save_credentials(self, user_id: int, api_key: str, api_secret: str) -> None:
        self._credentials[int(user_id)] = {"api_key": api_key, "api_secret": api_secret}

    async def load_credentials(self, user_id: int) -> Dict[str, str]:
        return dict(self._credentials.get(int(user_id), {}))

    async def save_access_token(self, user_id: int, access_token: str) -> None:
        self._access_tokens[int(user_id)] = str(access_token or "")

    async def load_access_token(self, user_id: int) -> str:
        return str(self._access_tokens.get(int(user_id), ""))

    # -------------------------
    # Kill switch
    # -------------------------
    async def set_kill(self, user_id: int, enabled: bool) -> None:
        self._kill[int(user_id)] = bool(enabled)

    async def is_kill(self, user_id: int) -> bool:
        return bool(self._kill.get(int(user_id), False))

    # -------------------------
    # Alert config
    # -------------------------
    async def list_alert_configs(self, user_id: int) -> List[Dict[str, Any]]:
        cfg = self._alert_configs.get(int(user_id), {})
        return list(cfg.values())

    async def save_alert_config(self, user_id: int, payload: Dict[str, Any]) -> None:
        uid = int(user_id)
        alert_name = str(payload.get("alert_name") or "").strip()
        if not alert_name:
            return
        self._alert_configs.setdefault(uid, {})[alert_name] = dict(payload)

    async def delete_alert_config(self, user_id: int, alert_name: str) -> bool:
        uid = int(user_id)
        key = str(alert_name or "").strip()
        if not key:
            return False
        cfg = self._alert_configs.get(uid)
        if not cfg or key not in cfg:
            return False
        del cfg[key]
        return True

    # -------------------------
    # Alerts history
    # -------------------------
    async def save_alert(self, user_id: int, payload: Dict[str, Any]) -> None:
        uid = int(user_id)
        self._alerts.setdefault(uid, []).append(dict(payload))

    async def get_recent_alerts(self, user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        uid = int(user_id)
        items = self._alerts.get(uid, [])
        limit_n = max(0, int(limit))
        if limit_n <= 0:
            return []
        return list(items[-limit_n:])

    async def delete_alerts(self, user_id: int) -> None:
        self._alerts[int(user_id)] = []

    # -------------------------
    # Positions
    # -------------------------
    async def upsert_position(self, user_id: int, symbol: str, position: Dict[str, Any]) -> None:
        uid = int(user_id)
        sym = str(symbol or "").strip().upper()
        if not sym:
            return
        self._positions.setdefault(uid, {})[sym] = dict(position)

    async def list_positions(self, user_id: int) -> List[Dict[str, Any]]:
        uid = int(user_id)
        return list(self._positions.get(uid, {}).values())

    # -------------------------
    # Auto Square Off
    # -------------------------
    async def is_auto_sq_off_enabled(self, user_id: int) -> bool:
        return bool(self._auto_sq_off_enabled.get(int(user_id), False))

    async def set_auto_sq_off_enabled(self, user_id: int, enabled: bool) -> None:
        self._auto_sq_off_enabled[int(user_id)] = bool(enabled)

    async def has_auto_sq_off_run(self, user_id: int) -> bool:
        uid = int(user_id)
        ymd = datetime.utcnow().strftime("%Y%m%d")
        return self._auto_sq_off_ran_ymd.get(uid) == ymd

    async def mark_auto_sq_off_run(self, user_id: int) -> None:
        uid = int(user_id)
        ymd = datetime.utcnow().strftime("%Y%m%d")
        self._auto_sq_off_ran_ymd[uid] = ymd

    async def list_all_user_ids(self) -> List[int]:
        uids = set(self._credentials.keys()) | set(self._access_tokens.keys()) | set(self._kill.keys())
        return sorted(uids)

    # -------------------------
    # Auth: users
    # -------------------------
    @staticmethod
    def _stable_user_id(email: str) -> int:
        return int(hashlib.md5(email.encode()).hexdigest()[:8], 16) % 100000

    async def save_user(self, user: Any) -> None:
        u = user if isinstance(user, User) else User(**user)
        self._users_by_email[u.email] = u.to_dict()
        self._user_id_by_email[u.email] = self._stable_user_id(u.email)

    async def get_user_by_email(self, email: str) -> Optional[Any]:
        raw = self._users_by_email.get(email)
        if not raw:
            return None
        try:
            return User.from_dict(dict(raw))
        except Exception:
            return None

    async def get_user_id_by_email(self, email: str) -> int:
        if email in self._user_id_by_email:
            return int(self._user_id_by_email[email])
        uid = self._stable_user_id(email)
        self._user_id_by_email[email] = uid
        return uid

    # -------------------------
    # Auth: OTP
    # -------------------------
    async def save_otp(self, email: str, otp: Any) -> None:
        o = otp if isinstance(otp, OTP) else OTP(**otp)
        self._otp_by_email[email] = o.to_dict()

    async def get_otp(self, email: str) -> Optional[Any]:
        raw = self._otp_by_email.get(email)
        if not raw:
            return None
        try:
            otp = OTP.from_dict(dict(raw))
        except Exception:
            return None
        if datetime.utcnow() >= otp.expires_at:
            self._otp_by_email.pop(email, None)
            return None
        return otp

    async def delete_otp(self, email: str) -> None:
        self._otp_by_email.pop(email, None)

    async def check_otp_rate_limit(self, email: str) -> bool:
        # max 3 per hour
        now = time.time()
        window = 3600.0
        times = self._otp_requests.setdefault(email, [])
        times[:] = [t for t in times if (now - t) < window]
        if len(times) >= 3:
            return False
        times.append(now)
        return True

    # -------------------------
    # Auth: sessions
    # -------------------------
    async def save_session(self, token: str, session: Any) -> None:
        s = session if isinstance(session, Session) else Session(**session)
        self._sessions_by_token[token] = s.to_dict()

    async def get_session(self, token: str) -> Optional[Any]:
        raw = self._sessions_by_token.get(token)
        if not raw:
            return None
        try:
            sess = Session.from_dict(dict(raw))
        except Exception:
            return None
        if datetime.utcnow() >= sess.expires_at:
            self._sessions_by_token.pop(token, None)
            return None
        return sess

    async def delete_session(self, token: str) -> bool:
        existed = token in self._sessions_by_token
        self._sessions_by_token.pop(token, None)
        return existed

