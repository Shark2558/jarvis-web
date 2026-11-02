# src/jarvis/api/body.py
"""Request-body size limits (Layer 1; slice 9 review items 12 and 15).

    BodySizeLimit   app-wide ASGI middleware: a declared Content-Length above MAX_BODY_BYTES
                    → 413 {"error": "too_large"} before anything is read (and before auth or
                    JSON parsing); a body without one (chunked) is cut off as soon as it passes
                    the cap (BodyTooLarge, rendered the same way).
    read_capped     the per-route capped read for routes that take a raw body (transcribe:
                    2,000,000 bytes, memory import: 512 KB); their tighter caps and their own
                    error messages still apply first.

MAX_BODY_BYTES sits just above the largest per-route cap, so no route can be starved by it. The
one exception is declared by path (`routes`): the attachment upload (slice 10 E) gets its own,
larger middleware cap just above its 10 MB route cap; every other path keeps MAX_BODY_BYTES.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any

from fastapi import HTTPException, Request

MAX_BODY_BYTES = 2_100_000
_MESSAGE = "Request bodies are limited to {limit:,} bytes."

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class BodyTooLarge(HTTPException):
    """413 too_large. An HTTPException, so FastAPI's body parser passes it on unchanged (any
    other error while reading a body becomes its generic 400)."""

    def __init__(self, limit: int = MAX_BODY_BYTES) -> None:
        super().__init__(status_code=413, detail=_MESSAGE.format(limit=limit))


def too_large_body(detail: str) -> dict[str, str]:
    return {"error": "too_large", "detail": detail}


async def read_capped(request: Request, limit: int, *, too_large: Callable[[], Exception]) -> bytes:
    """The body, refused (`too_large()`) as soon as it is known to exceed `limit`: from
    Content-Length before anything is read, else while it streams in (chunked: no length)."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_large()
    parts: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_large()
        parts.append(chunk)
    return b"".join(parts)


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers") or []:
        if name.lower() == b"content-length":
            text = value.decode("latin-1").strip()
            return int(text) if text.isdigit() else None
    return None


class BodySizeLimit:
    """Pure ASGI middleware (it must wrap `receive`, which BaseHTTPMiddleware can't)."""

    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int = MAX_BODY_BYTES,
        *,
        routes: Mapping[str, int] | None = None,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.routes = dict(routes or {})  # exact path → that path's cap

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        limit = self.routes.get(str(scope.get("path", "")), self.max_bytes)
        declared = _declared_length(scope)
        if declared is not None and declared > limit:
            await self._refuse(send, limit)
            return
        received = 0

        async def capped() -> Message:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLarge(limit)
            return message

        await self.app(scope, capped, send)

    async def _refuse(self, send: Send, limit: int) -> None:
        body = json.dumps(too_large_body(_MESSAGE.format(limit=limit))).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


__all__ = ["MAX_BODY_BYTES", "BodySizeLimit", "BodyTooLarge", "read_capped", "too_large_body"]
