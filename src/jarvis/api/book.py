# src/jarvis/api/book.py
"""The build book's status, sections, sealed releases, code download and Book settings (R6 part B;
docs/plans/r6-build-book.md "Contract", D6, D7, D9, D16). Owner-only: `require_auth` on the router
(cookie writes need `X-Requested-With: JARVIS`); every answer is `no-store` (api/book_http.py).

GET  /v1/book                              status (D7: seals this release within 20 s if needed)
GET  /v1/book/sections                     ● this release's sections (owner session)
GET  /v1/book/releases/{rid}/sections      ● an older sealed release's sections (owner)
POST /v1/book/releases/{rid}/ticket        ● {ticket, expires_in_s} (owner, 60 s, single use)
GET  /v1/book/download/{ticket}            the sealed code as a zip (attachment, nosniff)
GET  /v1/book/settings | PUT               creator name, show voice, talk-through, training brain

● = the book session token in `X-Jarvis-Book`. R6 I0: every route answers 503 `book_off`; part B
replaces the bodies (and keeps the paths, methods and `require_auth`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.book_http import BOOK_PREFIX, book_off

router = APIRouter(prefix=BOOK_PREFIX, dependencies=[Depends(require_auth)])


@router.get("")
async def book_status() -> JSONResponse:
    return book_off()


@router.get("/sections")
async def book_sections() -> JSONResponse:
    return book_off()


@router.get("/releases/{rid}/sections")
async def book_release_sections(rid: str) -> JSONResponse:
    return book_off()


@router.post("/releases/{rid}/ticket")
async def book_release_ticket(rid: str) -> JSONResponse:
    return book_off()


@router.get("/download/{ticket}")
async def book_download(ticket: str) -> JSONResponse:
    return book_off()


@router.get("/settings")
async def book_settings() -> JSONResponse:
    return book_off()


@router.put("/settings")
async def book_settings_put() -> JSONResponse:
    return book_off()


__all__ = ["router"]
