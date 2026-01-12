# app/websocket_manager.py
from __future__ import annotations

import asyncio
import json
from typing import Dict, Set, Any
from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._conns: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._conns.setdefault(user_id, set()).add(ws)

    async def disconnect(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            if user_id in self._conns and ws in self._conns[user_id]:
                self._conns[user_id].remove(ws)
                if not self._conns[user_id]:
                    del self._conns[user_id]

    async def broadcast(self, user_id: int, payload: Dict[str, Any]) -> None:
        msg = json.dumps(payload, separators=(",", ":"))
        async with self._lock:
            conns = list(self._conns.get(user_id, set()))
        if not conns:
            return
        dead = []
        for ws in conns:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(user_id, ws)
