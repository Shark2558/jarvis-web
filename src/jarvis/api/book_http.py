# src/jarvis/api/book_http.py
"""What the build book's routes share (R6 I0; docs/plans/r6-build-book.md "Contract"). Owned by
the integrator: parts B (`api/book.py`) and C (`api/book_show.py`) import these names and never
redefine them.

- Every answer under `/v1/book` (and the `/book/show` page) is `Cache-Control: no-store`, errors
  and the 401 from `require_auth` included: `BookNoStore` stamps it on the way out, so no route
  can forget it.
- Failures are `{error, detail}` in plain words (`book_error`); `book_off()` is the answer while
  the book is OFF on this server (no token key, or the part not wired yet).
- `BOOK_TOKEN_HEADER`: the book session token (D9), held in the show tab's sessionStorage only.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

NO_STORE = "no-store"
BOOK_TOKEN_HEADER = "X-Jarvis-Book"
BOOK_OFF = "The build book isn't available on this server."
BOOK_PREFIX = "/v1/book"
SHOW_PAGE = "/book/show"


def book_error(status: int, error: str, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": error, "detail": detail, **extra},
        headers={"Cache-Control": NO_STORE},
    )


def book_off() -> JSONResponse:
    return book_error(503, "book_off", BOOK_OFF)


def is_book_path(path: str) -> bool:
    return path == BOOK_PREFIX or path.startswith(BOOK_PREFIX + "/") or path == SHOW_PAGE


class BookNoStore:
    """Pure ASGI middleware: `Cache-Control: no-store` on every book response (D14)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_book_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = NO_STORE
            await send(message)

        await self.app(scope, receive, send_no_store)


__all__ = [
    "BOOK_OFF",
    "BOOK_PREFIX",
    "BOOK_TOKEN_HEADER",
    "NO_STORE",
    "SHOW_PAGE",
    "BookNoStore",
    "book_error",
    "book_off",
    "is_book_path",
]
