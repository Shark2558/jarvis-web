# src/jarvis/api/book_show.py
"""The build book's session routes (R6 D8-D14; "Contract"; builder C). Owner-only cookie sessions
(`require_auth` + `current_user`; opening is the console only, a bearer caller gets 403
console_only), every answer `no-store` (api/book_http.py).

POST /v1/book/open {proof, audience}     {token, session_id, until, audience} · 403 console_only /
                                         passkey_setup_needed / reauth_required / passkey errors ·
                                         409 guest_needs_google · 404 no_book
GET  /v1/book/show/script                ● {release, scenes, closing, costs}
POST /v1/book/show/speak {line_id}       ● audio (a beat id or a buildbook.lines.LINES key)
POST /v1/book/show/hear                  ● WAV <= 15 s, 600 KB -> {text}
POST /v1/book/show/ask {text}            ● {reply_id, reply, refused, follow_up, left}
POST /v1/book/show/beat                  ● {until}
POST /v1/book/close                      ● {closed, wiped, notified}
POST /v1/book/resume {proof}             {resumed} (purpose book_resume, target = the lock id)

● = header X-Jarvis-Book (the book session token). Under a guest lock (D10) these, GET /book/show
(api/console.py) and POST /v1/passkeys/challenge are the routes that still answer.
I0 STUB: every route answers 503 book_off (tests/test_r6_contract.py). Builder C replaces the
bodies and keeps the paths, methods and the no-store answers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.book_http import book_off

router = APIRouter(prefix="/v1/book", dependencies=[Depends(require_auth)])


@router.post("/open", response_model=None)
async def open_book() -> JSONResponse:
    return book_off()


@router.get("/show/script", response_model=None)
async def show_script() -> JSONResponse:
    return book_off()


@router.post("/show/speak", response_model=None)
async def show_speak() -> JSONResponse:
    return book_off()


@router.post("/show/hear", response_model=None)
async def show_hear() -> JSONResponse:
    return book_off()


@router.post("/show/ask", response_model=None)
async def show_ask() -> JSONResponse:
    return book_off()


@router.post("/show/beat", response_model=None)
async def show_beat() -> JSONResponse:
    return book_off()


@router.post("/close", response_model=None)
async def close() -> JSONResponse:
    return book_off()


@router.post("/resume", response_model=None)
async def resume() -> JSONResponse:
    return book_off()


def install_book_show(app: FastAPI) -> None:
    app.include_router(router)


__all__ = ["install_book_show", "router"]
