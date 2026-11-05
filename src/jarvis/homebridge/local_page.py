# src/jarvis/homebridge/local_page.py
"""The laptop's Faces page, `http://localhost:8098/faces` (R3 D13). Home only: pictures never go
to the JARVIS cloud, and this page is the only place they are added.

- Binds 127.0.0.1 only (`HOST`). A request whose Host is not localhost / 127.0.0.1 on this port
  is refused (DNS rebinding); a POST whose Origin is another site is refused.
- Login: a code the setup prints (`FACES_CODE` or `/data/faces_code.txt`), compared in constant
  time, 5 wrong tries lock the page for a minute. The session is a random cookie (HttpOnly,
  SameSite=Strict, 12 hours) plus a CSRF token the page sends in `X-CSRF` on every write.
- Lists consented people by their code (`fp_...`), takes uploads (raw JPEG or PNG body, <= 5 MB,
  <= 20 a person) or lets the owner pick from recent visitors. An id without consent is refused.
- Its own CSP: `default-src 'self'`; no inline script; no remote anything. Responses are never
  cached. Pictures are not logged.
"""

from __future__ import annotations

import hmac
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from jarvis.homebridge.faces import MAX_IMAGE_BYTES, FaceLibrary, FaceRefused
from jarvis.homebridge.plugins import BridgeContext

HOST = "127.0.0.1"
PORT = 8098
SESSION_S = 12 * 3600
MAX_SESSIONS = 4
MAX_TRIES = 5
LOCK_S = 60
COOKIE = "jf_session"
STATIC = Path(__file__).parent / "static"
ASSETS = {"faces.html": "text/html", "faces.js": "text/javascript", "faces.css": "text/css"}
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
MIN_CODE = 8


def login_code(env: dict[str, str] | Any, data_dir: Path) -> str:
    """`FACES_CODE` if the owner set one, else a code made once and kept in `faces_code.txt`
    (mode 0600) for the setup to print. Never logged."""
    given = env.get("FACES_CODE", "")
    if len(given) >= MIN_CODE:
        return str(given)
    path = data_dir / "faces_code.txt"
    try:
        stored = path.read_text().strip()
        if len(stored) >= MIN_CODE:
            return stored
    except OSError:
        pass
    code = secrets.token_urlsafe(9)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(code + "\n")
    return code


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=200)


class Classify(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person: str = Field(max_length=32)
    file: str = Field(max_length=120)


class Sessions:
    def __init__(self, now: Callable[[], float]) -> None:
        self._now = now
        self._live: dict[str, tuple[float, str]] = {}
        self._fails = 0
        self._locked_until = 0.0

    def locked(self) -> bool:
        return self._now() < self._locked_until

    def failed(self) -> None:
        self._fails += 1
        if self._fails >= MAX_TRIES:
            self._fails = 0
            self._locked_until = self._now() + LOCK_S

    def start(self) -> tuple[str, str]:
        now = self._now()
        self._live = {k: v for k, v in self._live.items() if v[0] > now}
        while len(self._live) >= MAX_SESSIONS:
            self._live.pop(min(self._live, key=lambda k: self._live[k][0]))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        self._live[token] = (now + SESSION_S, csrf)
        self._fails = 0
        return token, csrf

    def csrf(self, token: str | None) -> str | None:
        found = self._live.get(token or "")
        if found is None or found[0] <= self._now():
            return None
        return found[1]

    def end(self, token: str | None) -> None:
        self._live.pop(token or "", None)


def _reply(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=HEADERS)


def _plain(status: int, error: str, detail: str) -> JSONResponse:
    return _reply(status, {"error": error, "detail": detail})


def create_local_app(
    library: FaceLibrary,
    code: str,
    *,
    port: int = PORT,
    now: Callable[[], float] = time.time,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    sessions = Sessions(now)
    hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
    origins = {f"http://{h}" for h in hosts}

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.headers.get("host", "") not in hosts:
            return _plain(403, "bad_host", "Open this page as http://localhost:8098/faces.")
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD") and origin is not None and origin not in origins:
            return _plain(403, "bad_origin", "That request came from another site.")
        response = await call_next(request)
        for k, v in HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    def session(request: Request, *, write: bool = False) -> JSONResponse | None:
        csrf = sessions.csrf(request.cookies.get(COOKIE))
        if csrf is None:
            return _plain(401, "login", "Enter the code from the setup first.")
        if write and not hmac.compare_digest(request.headers.get("x-csrf", ""), csrf):
            return _plain(403, "csrf", "Reload the page and try again.")
        return None

    def asset(name: str) -> Response:
        return FileResponse(STATIC / name, media_type=ASSETS[name], headers=HEADERS)

    @app.get("/faces")
    async def page() -> Response:
        return asset("faces.html")

    @app.get("/faces/{name}")
    async def static(name: str) -> Response:
        if name not in ASSETS or name == "faces.html":
            return _plain(404, "not_found", "No such page.")
        return asset(name)

    @app.post("/faces/api/login")
    async def login(body: Login) -> JSONResponse:
        if sessions.locked():
            return _plain(429, "locked", "Too many wrong codes. Wait a minute.")
        if not hmac.compare_digest(body.code.encode(), code.encode()):
            sessions.failed()
            return _plain(401, "wrong_code", "That code isn't right.")
        token, csrf = sessions.start()
        out = _reply(200, {"csrf": csrf})
        out.set_cookie(
            COOKIE, token, max_age=SESSION_S, httponly=True, samesite="strict", path="/faces"
        )
        return out

    @app.post("/faces/api/logout")
    async def logout(request: Request) -> JSONResponse:
        if (refused := session(request, write=True)) is not None:
            return refused
        sessions.end(request.cookies.get(COOKIE))
        return _reply(200, {"ok": True})

    @app.get("/faces/api/people")
    async def people(request: Request) -> JSONResponse:
        if (refused := session(request)) is not None:
            return refused
        try:
            summary = await library.summary()
            recent = await library.recent()
        except FaceRefused as exc:
            return _plain(503, exc.code, exc.words)
        return _reply(
            200,
            {
                "people": [{"id": p, "pictures": n} for p, n in summary.items()],
                "recent": recent,
                "max_pictures": 20,
                "csrf": sessions.csrf(request.cookies.get(COOKIE)),
            },
        )

    @app.post("/faces/api/enrol")
    async def enrol(request: Request, person: str = "") -> JSONResponse:
        if (refused := session(request, write=True)) is not None:
            return refused
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
            return _plain(413, "too_big", "Pictures can be at most 5 MB.")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_IMAGE_BYTES:  # no trust in the header: stop reading at the limit
                return _plain(413, "too_big", "Pictures can be at most 5 MB.")
        try:
            n = await library.enrol(person, bytes(data))
        except FaceRefused as exc:
            return _plain(413 if exc.code == "too_big" else 422, exc.code, exc.words)
        return _reply(200, {"pictures": n})

    @app.get("/faces/api/recent/{file}")
    async def recent_image(request: Request, file: str) -> Response:
        if (refused := session(request)) is not None:
            return refused
        try:
            data = await library.recent_image(file)
        except FaceRefused as exc:
            return _plain(404, exc.code, exc.words)
        kind = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
        if data[:4] == b"RIFF":
            kind = "image/webp"
        return Response(data, media_type=kind, headers=HEADERS)

    @app.post("/faces/api/classify")
    async def classify(request: Request, body: Classify) -> JSONResponse:
        if (refused := session(request, write=True)) is not None:
            return refused
        try:
            await library.enrol_recent(body.person, body.file)
        except FaceRefused as exc:
            return _plain(422, exc.code, exc.words)
        return _reply(200, {"ok": True})

    return app


async def serve_local_page(library: FaceLibrary, ctx: BridgeContext) -> None:
    """Run the page on 127.0.0.1 until cancelled."""
    import uvicorn

    port = int(ctx.env.get("FACES_PORT", PORT))
    app = create_local_app(library, login_code(ctx.env, ctx.data_dir), port=port, now=ctx.now)
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning", access_log=False)
    await uvicorn.Server(config).serve()


__all__ = ["HOST", "PORT", "Sessions", "create_local_app", "login_code", "serve_local_page"]
