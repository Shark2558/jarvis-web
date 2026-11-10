# src/jarvis/api/book.py
"""The build book's owner routes (R6 D6-D9, D16; "Contract"; builder B). Owner-only
(`require_auth` + `current_user`), every answer `no-store` (api/book_http.py).

GET  /v1/book                            status: {available, reason?, release, sealed, kept,
                                         used_mb, limit_mb, session, lock, last_closed, talk, open}
GET  /v1/book/sections                   ● the current book's sections (owner session)
GET  /v1/book/releases/{rid}/sections    ● an older sealed release's sections (owner)
POST /v1/book/releases/{rid}/ticket      ● {ticket, expires_in_s: 60} (owner)
GET  /v1/book/download/{ticket}          the sealed source zip (attachment, nosniff)
GET  /v1/book/settings | PUT             D16: creator name, show voice, talk-through, training brain

● = header X-Jarvis-Book (the book session token).
I0 STUB: every route answers 503 book_off (tests/test_r6_contract.py). Builder B replaces the
bodies and keeps the paths, methods and the no-store answers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.book_http import book_off

router = APIRouter(prefix="/v1/book", dependencies=[Depends(require_auth)])


@router.get("", response_model=None)
async def status() -> JSONResponse:
    return book_off()


@router.get("/sections", response_model=None)
async def sections() -> JSONResponse:
    return book_off()


@router.get("/releases/{rid}/sections", response_model=None)
async def release_sections(rid: str) -> JSONResponse:
    return book_off()


@router.post("/releases/{rid}/ticket", response_model=None)
async def ticket(rid: str) -> JSONResponse:
    return book_off()


@router.get("/download/{ticket}", response_model=None)
async def download(ticket: str) -> JSONResponse:
    return book_off()


@router.get("/settings", response_model=None)
async def get_settings() -> JSONResponse:
    return book_off()


@router.put("/settings", response_model=None)
async def put_settings() -> JSONResponse:
    return book_off()


def install_book(app: FastAPI) -> None:
    app.include_router(router)


__all__ = ["install_book", "router"]
