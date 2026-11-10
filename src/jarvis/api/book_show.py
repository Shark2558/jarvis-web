# src/jarvis/api/book_show.py
"""Opening the build book, the show, the talk-through, closing and Resume (R6 part C;
docs/plans/r6-build-book.md "Contract", D8-D14). `require_auth` on the router (cookie writes need
`X-Requested-With: JARVIS`); every answer is `no-store` (api/book_http.py).

POST /v1/book/open {proof, audience}       {token, session_id, until, audience} (console only, D8)
GET  /v1/book/show/script                  ● {release, scenes, closing, costs}
POST /v1/book/show/speak {line_id}         ● audio (server-side text only)
POST /v1/book/show/hear                    ● WAV <= 15 s, 600 KB -> {text}
POST /v1/book/show/ask {text}              ● {reply_id, reply, refused, follow_up, left}
POST /v1/book/show/beat                    ● {until}
POST /v1/book/close                        ● {closed, wiped, notified}
POST /v1/book/resume {proof}               {resumed} (purpose book_resume, target = the lock id)

● = the book session token in `X-Jarvis-Book`. R6 I0: every route answers 503 `book_off`; part C
replaces the bodies (and keeps the paths, methods and `require_auth`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.book_http import BOOK_PREFIX, book_off

router = APIRouter(prefix=BOOK_PREFIX, dependencies=[Depends(require_auth)])


@router.post("/open")
async def book_open() -> JSONResponse:
    return book_off()


@router.get("/show/script")
async def show_script() -> JSONResponse:
    return book_off()


@router.post("/show/speak")
async def show_speak() -> JSONResponse:
    return book_off()


@router.post("/show/hear")
async def show_hear() -> JSONResponse:
    return book_off()


@router.post("/show/ask")
async def show_ask() -> JSONResponse:
    return book_off()


@router.post("/show/beat")
async def show_beat() -> JSONResponse:
    return book_off()


@router.post("/close")
async def book_close() -> JSONResponse:
    return book_off()


@router.post("/resume")
async def book_resume() -> JSONResponse:
    return book_off()


__all__ = ["router"]
