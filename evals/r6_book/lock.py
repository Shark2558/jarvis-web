# evals/r6_book/lock.py
"""R6 eval part `lock` (builder C): the guest lock over every cookie session of the owner (D10).
Through the real app with `ShowLockMiddleware` installed inside the session middleware, where
I1's `install_show_lock` puts it.

Cases (cases_lock.jsonl x three browsers: the presenting one, an older one and a NEW sign-in made
after logging out): /auth/me, /v1/chat, /v1/vault, /v1/memory, /v1/permissions (read and change),
/v1/book/open and EVERY passkey register / reset / cancel route -> 423; / -> 302 /book/show; the
show page, /static, /health and /console/config pass. The show routes pass with the guest token.
The other owner's sessions are held too; bearer is untouched. A guest who signs in again with a
"fresh" Google sign-in (one click on the chooser) is held, can start no passkey reset and lifts
nothing. Only a `book_resume` passkey check for THIS lock lifts it (a book_open proof, no proof, a
proof for another lock and, with no passkey in force any more, a fresh sign-in don't).
Negative control: `/auth/me` allow-listed (it would hand the guest the owner's e-mail).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from book_app_fakes import (
    BEARER,
    CSRF,
    SECOND_OWNER,
    book,
    book_app,
    open_book,
    proof,
    register_passkey,
    sign_in,
)
from book_show_fakes import Clock
from httpx import AsyncClient

import jarvis.api.book_lock as lock_module
from jarvis.config import LLMBackend, Settings

PART = "lock"
BUILT = True
HERE = Path(__file__).parent
Case = dict[str, Any]


def _case(cid: str, ok: bool, why: str) -> Case:
    return {"id": f"{PART}:{cid}", "passed": ok, "failures": [] if ok else [why]}


def _rows() -> list[dict[str, Any]]:
    text = (HERE / "cases_lock.jsonl").read_text(encoding="utf-8")
    return [json.loads(x) for x in text.splitlines() if x.strip()]


@asynccontextmanager
async def _app() -> AsyncIterator[Any]:
    s = Settings(_env_file=None, env="dev", llm_backend=LLMBackend.MOCK, usd_inr_live=False)
    gen = book_app(s)
    app = await gen.__anext__()
    app.state.book_clock = Clock()
    try:
        yield app
    finally:
        await gen.aclose()


async def _held(c: AsyncClient, who: str) -> list[Case]:
    out: list[Case] = []
    for row in _rows():
        kw: dict[str, Any] = {"headers": CSRF, "follow_redirects": False}
        if "json" in row:
            kw["json"] = row["json"]
        r = await c.request(row["method"], row["path"], **kw)
        ok = r.status_code == row["want"]
        if row["want"] == 302:
            ok = ok and r.headers.get("location") == "/book/show"
        out.append(_case(f"{who}:{row['id']}", ok, f"{r.status_code} != {row['want']}"))
    return out


async def _browsers(app: Any) -> tuple[list[Case], Any, str]:
    out: list[Case] = []
    async with sign_in(app, fresh=False) as older:  # an earlier session of the owner
        async with sign_in(app) as presenting:
            auth = await register_passkey(presenting)
            token = (await open_book(presenting, auth, "guest"))["token"]
            out += await _held(presenting, "presenting")
            out += await _held(older, "older")
            r = await presenting.get("/v1/book/show/script", headers=book(token))
            out.append(_case("show-routes-pass", r.status_code == 200, str(r.status_code)))
            await presenting.post("/auth/logout", headers=CSRF)
    async with sign_in(app, fresh=False) as new:  # rides Google's live session: no password
        out += await _held(new, "new-sign-in")
    out += await _fresh_guest_sign_in(app)
    async with sign_in(app, SECOND_OWNER) as other:
        r = await other.get("/auth/me")
        out.append(_case("other-owner-held", r.status_code == 423, str(r.status_code)))
    async with AsyncClient(transport=app.transport, base_url="http://test", headers=BEARER) as cli:
        r = await cli.post("/v1/chat", json={"message": "hello"})
        out.append(_case("bearer-untouched", r.status_code == 200, str(r.status_code)))
    return out, auth, token


async def _fresh_guest_sign_in(app: Any) -> list[Case]:
    """The guest signs in again "freshly" (Google asks nothing more with a live session)."""
    async with sign_in(app) as again:
        reset = await again.post("/v1/passkeys/reset", headers=CSRF)
        resume = await again.post("/v1/book/resume", json={}, headers=CSRF)
        held = (await again.get("/auth/me")).status_code == 423
    ok = reset.status_code == 423 and resume.status_code == 403 and held
    return [_case("fresh-guest-sign-in-lifts-nothing", ok, f"{reset.status_code} {resume.text}")]


async def _no_passkey_left(app: Any) -> list[Case]:
    """Every passkey gone (a completed reset): no sign-in, however fresh, lifts the lock."""
    real = app.state.permissions.check_purpose

    async def none_in_force(*a: Any, **k: Any) -> None:
        return None

    app.state.permissions.check_purpose = none_in_force
    try:
        async with sign_in(app) as again:
            r = await again.post("/v1/book/resume", json={}, headers=CSRF)
            held = (await again.get("/auth/me")).status_code == 423
    finally:
        app.state.permissions.check_purpose = real
    ok = r.status_code == 403 and r.json().get("error") == "emergency_unlock_needed" and held
    return [_case("no-passkey-no-sign-in-lift", ok, r.text)]


async def _resume(app: Any, auth: Any) -> list[Case]:
    out: list[Case] = []
    async with sign_in(app, fresh=False) as c:
        r = await c.post("/v1/book/resume", json={}, headers=CSRF)
        lock_id = r.json().get("lock_id", "")
        out.append(_case("no-proof-kept", r.status_code == 403 and bool(lock_id), r.text))
        attempts = {
            "open-proof-kept": await proof(c, auth, "book_open", "guest"),
            "other-lock-proof-kept": await proof(c, auth, "book_resume", "bl_000000000000"),
        }
        for cid, p in attempts.items():
            r = await c.post("/v1/book/resume", json={"proof": p}, headers=CSRF)
            still = (await c.get("/auth/me")).status_code == 423
            out.append(_case(cid, r.status_code == 403 and still, str(r.status_code)))
        good = await proof(c, auth, "book_resume", lock_id)
        r = await c.post("/v1/book/resume", json={"proof": good}, headers=CSRF)
        me = await c.get("/auth/me")
        ok = r.json() == {"resumed": True} and me.status_code == 200
        out.append(_case("resume-proof-lifts", ok, f"{r.text} {me.status_code}"))
    return out


async def _suite() -> list[Case]:
    async with _app() as app:
        out, auth, _ = await _browsers(app)
        out += await _no_passkey_left(app)
        out += await _resume(app, auth)
    return out


async def cases() -> list[Case]:
    return await _suite()


async def control() -> dict[str, Any]:
    leaky = lock_module.ALLOWED | {("GET", "/auth/me")}
    with patch.object(lock_module, "ALLOWED", leaky):
        results = await _suite()
    failed = [r["id"] for r in results if not r["passed"]]
    return {
        "name": "lock: /auth/me allow-listed",
        "suite_failed": bool(failed),
        "failed_cases": failed,
    }
