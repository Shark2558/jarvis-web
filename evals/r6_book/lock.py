# evals/r6_book/lock.py
"""R6 eval part `lock` (builder C): the guest lock over every cookie session of the owner (D10).
Through the real app with `ShowLockMiddleware` installed inside the session middleware, where
I1's `install_show_lock` puts it.

Cases (cases_lock.jsonl x three browsers: the presenting one, an older one and a NEW sign-in made
after logging out): /auth/me, /v1/chat, /v1/vault, /v1/memory, /v1/permissions, /v1/book/open
and /v1/passkeys/reset/cancel -> 423; / -> 302 /book/show; the show page, /static, /health and
/console/config pass; the passkey reset is reachable but refused without a fresh sign-in (the
guest's browsers have none: the presenting one's was consumed by the guest open), while the owner,
signing in again with his password, can start it (the recovery for a passkey lost mid-show). The
show routes pass with the guest token. The other owner's sessions are held too; bearer is untouched.
Only a `book_resume` passkey check for THIS lock lifts it (a book_open proof, no proof and a proof
for another lock don't).
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
        if row["id"] == "reset":
            ok = ok and r.json().get("reason") == "reauth"  # reached, and still refused
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
    async with sign_in(app) as owner:  # the owner signs in again (password + 2-Step)
        r = await owner.post("/v1/passkeys/reset", headers=CSRF)
        held = (await owner.get("/auth/me")).status_code == 423
        out.append(
            _case(
                "owner-can-start-passkey-recovery",
                r.status_code == 200 and held,
                f"{r.status_code} held={held}",
            )
        )
    async with sign_in(app, SECOND_OWNER) as other:
        r = await other.get("/auth/me")
        out.append(_case("other-owner-held", r.status_code == 423, str(r.status_code)))
    async with AsyncClient(transport=app.transport, base_url="http://test", headers=BEARER) as cli:
        r = await cli.post("/v1/chat", json={"message": "hello"})
        out.append(_case("bearer-untouched", r.status_code == 200, str(r.status_code)))
    return out, auth, token


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
