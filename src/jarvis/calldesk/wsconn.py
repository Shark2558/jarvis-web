# src/jarvis/calldesk/wsconn.py
"""The `client.Connector` on the `websockets` library (BSD-3-Clause; hash-pinned in the kit).

Imported lazily by the desk's start, so the rest of the desk needs no WebSocket library. Frames of
at most 64 KiB, no compression (audio doesn't compress, and nothing secret is ever compressed next
to something an attacker controls), the library's own pings every 20 s, TLS checked against the
system's certificates (Windows' store on the laptop).
"""

from __future__ import annotations

from typing import Any

from jarvis.calldesk import DESK_VERSION
from jarvis.calldesk.client import Connection, LinkClosed, Refused, Unauthorized

MAX_MESSAGE_BYTES = 64 * 1024
OPEN_TIMEOUT_S = 15.0
PING_S = 20.0
CLOSE_TIMEOUT_S = 5.0
_DROPPED = 1006


class _WsConnection:
    def __init__(self, ws: Any) -> None:
        self._ws = ws

    async def send(self, data: str | bytes) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            await self._ws.send(data)
        except ConnectionClosed as exc:
            raise LinkClosed(_code(exc)) from None

    async def recv(self) -> str | bytes:
        from websockets.exceptions import ConnectionClosed

        try:
            data = await self._ws.recv()
        except ConnectionClosed as exc:
            raise LinkClosed(_code(exc)) from None
        return data if isinstance(data, str | bytes) else bytes(data)

    async def close(self) -> None:
        await self._ws.close()


def _code(exc: Any) -> int:
    rcvd = getattr(exc, "rcvd", None)
    return int(rcvd.code) if rcvd is not None else _DROPPED


async def connect(url: str, headers: dict[str, str]) -> Connection:
    from websockets.asyncio.client import connect as ws_connect
    from websockets.exceptions import InvalidHandshake, InvalidStatus

    try:
        ws = await ws_connect(
            url,
            additional_headers=headers,
            user_agent_header=f"JARVIS-CallDesk/{DESK_VERSION}",
            compression=None,
            max_size=MAX_MESSAGE_BYTES,
            open_timeout=OPEN_TIMEOUT_S,
            ping_interval=PING_S,
            ping_timeout=PING_S,
            close_timeout=CLOSE_TIMEOUT_S,
        )
    except InvalidStatus as exc:
        status = exc.response.status_code
        if status == 401:
            raise Unauthorized(exc.response.headers.get("Date")) from None
        raise Refused(status) from None
    except InvalidHandshake:
        raise Refused(0) from None
    return _WsConnection(ws)


__all__ = ["MAX_MESSAGE_BYTES", "connect"]
