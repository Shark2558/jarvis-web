# src/jarvis/api/book_http.py
"""The build book's HTTP answers (R6 "Contract"): every book response is `Cache-Control: no-store`
(D14: a closed session leaves nothing in a browser cache) and every failure is `{error, detail}`
in plain words. Shared by api/book.py (B) and api/book_show.py (C) so both answer alike.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
TOKEN_HEADER = "X-Jarvis-Book"  # the book session token (D9; sessionStorage of the show tab only)
BOOK_OFF = "The build book isn't available on this server yet."
RESUME_OFF = (  # SEC-3: the lock holds while the book is off; this is the owner's way out
    "The build book is off on this server, so Resume can't check your passkey here. Unlock from "
    "the server with the emergency unlock: python -m jarvis.buildbook.unlock."
)


def book_now(app: FastAPI) -> datetime:
    """The build book's time: `app.state.book_clock` when tests and evals moved it, else now.
    Every R6 part reads this one clock (integrated review L3)."""
    clock = getattr(app.state, "book_clock", None)
    return clock() if callable(clock) else datetime.now(UTC)


def setup_failure(app: FastAPI) -> str | None:
    """For Vitals (review L2): the class of the error that kept the book from starting (set by
    `r6_wiring.wire_r6`; never a message), or None."""
    if getattr(app.state, "book_off", None) != "setup_failed":
        return None
    return str(getattr(app.state, "book_off_error", None) or "Exception")


def book_json(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def book_err(status: int, code: str, detail: str) -> JSONResponse:
    return book_json({"error": code, "detail": detail}, status)


def book_off() -> JSONResponse:
    """503 book_off: the feature isn't wired on this server (I0 stubs; later: no keyring)."""
    return book_err(503, "book_off", BOOK_OFF)


__all__ = [
    "BOOK_OFF",
    "NO_STORE",
    "RESUME_OFF",
    "TOKEN_HEADER",
    "book_err",
    "book_json",
    "book_off",
]
