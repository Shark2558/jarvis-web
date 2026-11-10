# src/jarvis/api/book_http.py
"""The build book's HTTP answers (R6 "Contract"): every book response is `Cache-Control: no-store`
(D14: a closed session leaves nothing in a browser cache) and every failure is `{error, detail}`
in plain words. Shared by api/book.py (B) and api/book_show.py (C) so both answer alike.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
TOKEN_HEADER = "X-Jarvis-Book"  # the book session token (D9; sessionStorage of the show tab only)
BOOK_OFF = "The build book isn't available on this server yet."


def book_json(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def book_err(status: int, code: str, detail: str) -> JSONResponse:
    return book_json({"error": code, "detail": detail}, status)


def book_off() -> JSONResponse:
    """503 book_off: the feature isn't wired on this server (I0 stubs; later: no keyring)."""
    return book_err(503, "book_off", BOOK_OFF)


__all__ = ["BOOK_OFF", "NO_STORE", "TOKEN_HEADER", "book_err", "book_json", "book_off"]
