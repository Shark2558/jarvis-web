# evals/r6_book/access.py
"""R6 eval part `access` (builder C): opening the book takes a passkey AND a fresh Google sign-in
(D8), and a book token opens only its own session for its own time (D9). Through the real app:
the real /auth routes (Google's half faked), the real permissions service and a software passkey.

Cases: a stale sign-in -> reauth_required; no proof -> passkey_required; no passkey ->
passkey_setup_needed (never a sign-in-only open); a bearer caller -> console_only; a vault_unlock
proof and an owner-audience proof can't open a guest session; an expired and an idle token -> 401;
another owner's cookie can't use the token; a guest can't see the owner's month spend.

B's routes (cases_access.jsonl): a guest TOKEN on sections, older sections and the code ticket is
sent with the guest lock NOT engaged for that request (as from a browser the lock doesn't hold),
so B's own audience check must answer (403 owner_only, never 200 and never the lock's 423). While
B's routes are still the I0 stub (503 book_off) these rows pass marked `rerun_at_integration`; I1
re-runs them after the merge, when book_off fails them (B's state must then be wired in the
fixture). Settings carry no token: under the lock they are 423 for every browser of the owner.
Negative control: the fresh sign-in check skipped (a stale browser then opens the book).
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

import jarvis.api.book as b_routes
import jarvis.api.book_show_access as access_module
from jarvis.config import LLMBackend, Settings

PART = "access"
BUILT = True
HERE = Path(__file__).parent
Case = dict[str, Any]


def _settings() -> Settings:
    return Settings(_env_file=None, env="dev", llm_backend=LLMBackend.MOCK, usd_inr_live=False)


def _case(cid: str, ok: bool, why: str) -> Case:
    return {"id": f"{PART}:{cid}", "passed": ok, "failures": [] if ok else [why]}


def _err(r: Any) -> str:
    try:
        return str(r.json().get("error", ""))
    except ValueError:
        return ""


@asynccontextmanager
async def _app() -> AsyncIterator[Any]:
    gen = book_app(_settings())
    app = await gen.__anext__()
    app.state.book_clock = Clock()
    try:
        yield app
    finally:
        await gen.aclose()


async def _refusals(app: Any) -> list[Case]:
    out: list[Case] = []
    async with AsyncClient(transport=app.transport, base_url="http://test", headers=BEARER) as cli:
        r = await cli.post("/v1/book/open", json={"audience": "owner"})
        out.append(_case("bearer-console-only", _err(r) == "console_only", _err(r)))
    async with sign_in(app) as c:
        r = await c.post("/v1/book/open", json={"audience": "owner"}, headers=CSRF)
        out.append(_case("no-passkey-setup-needed", _err(r) == "passkey_setup_needed", _err(r)))
        auth = await register_passkey(c)
        r = await c.post("/v1/book/open", json={"audience": "guest"}, headers=CSRF)
        out.append(_case("no-proof-passkey-required", _err(r) == "passkey_required", _err(r)))
        vault = await proof(c, auth, "vault_unlock", None)
        r = await c.post("/v1/book/open", json={"audience": "guest", "proof": vault}, headers=CSRF)
        out.append(_case("vault-unlock-proof-fails", r.status_code == 403, _err(r)))
        mine = await proof(c, auth, "book_open", "owner")
        r = await c.post("/v1/book/open", json={"audience": "guest", "proof": mine}, headers=CSRF)
        out.append(_case("owner-proof-no-guest", r.status_code == 403, _err(r)))
    async with sign_in(app, fresh=False) as stale:
        p = await proof(stale, auth, "book_open", "owner")
        r = await stale.post("/v1/book/open", json={"audience": "owner", "proof": p}, headers=CSRF)
        out.append(_case("stale-sign-in-reauth", _err(r) == "reauth_required", _err(r)))
    return out


def _forbidden_rows() -> list[dict[str, str]]:
    text = (HERE / "cases_access.jsonl").read_text(encoding="utf-8")
    return [json.loads(x) for x in text.splitlines() if x.strip()]


class _Unlocked:
    """The lock store as a browser the guest lock doesn't hold would see it (B's check alone)."""

    async def get(self, uid: str) -> None:
        return None


def _b_is_stub() -> bool:
    return "I0 STUB" in (b_routes.__doc__ or "")


def _token_case(row: dict[str, str], r: Any) -> Case:
    err, stub = _err(r), _b_is_stub()
    ok = err == "owner_only" or (stub and err == "book_off")
    case = _case(row["id"], ok and r.status_code != 200, f"B answered {r.status_code} {err}")
    return {**case, "rerun_at_integration": True} if stub else case


async def _b_routes(app: Any, c: AsyncClient, token: str) -> list[Case]:
    out: list[Case] = []
    for row in _forbidden_rows():
        if row["kind"] == "lock":
            r = await c.request(row["method"], row["path"], headers=book(token))
            out.append(_case(row["id"], _err(r) == "show_locked", f"{r.status_code} {_err(r)}"))
            continue
        locked, app.state.book_lock = app.state.book_lock, _Unlocked()
        try:
            r = await c.request(row["method"], row["path"], headers=book(token))
        finally:
            app.state.book_lock = locked
        out.append(_token_case(row, r))
    return out


async def _guest_token(app: Any) -> list[Case]:
    out: list[Case] = []
    async with sign_in(app) as c:
        auth = await register_passkey(c)
        token = (await open_book(c, auth, "guest"))["token"]
        out += await _b_routes(app, c, token)
        s = await c.get("/v1/book/show/script", headers=book(token))
        ok = s.status_code == 200 and "month_inr" not in s.json()["costs"]
        out.append(_case("guest-no-month-spend", ok, "the guest saw the owner's spend"))
        app.state.book_clock.advance(minutes=11)
        r = await c.post("/v1/book/show/beat", headers=book(token))
        out.append(_case("idle-token-401", r.status_code == 401, str(r.status_code)))
    return out


async def _owner_token(app: Any) -> list[Case]:
    out: list[Case] = []
    async with sign_in(app) as c:
        auth = await register_passkey(c)
        token = (await open_book(c, auth, "owner"))["token"]
        async with sign_in(app, SECOND_OWNER) as other:
            r = await other.get("/v1/book/show/script", headers=book(token))
            out.append(_case("other-owner-401", r.status_code == 401, str(r.status_code)))
        for _ in range(9):  # the show beats every few minutes: 45 minutes absolute
            app.state.book_clock.advance(minutes=5)
            await c.post("/v1/book/show/beat", headers=book(token))
        r = await c.get("/v1/book/show/script", headers=book(token))
        out.append(_case("expired-token-401", r.status_code == 401, str(r.status_code)))
    return out


async def _suite() -> list[Case]:
    out: list[Case] = []
    for scenario in (_refusals, _guest_token, _owner_token):
        async with _app() as app:
            out += await scenario(app)
    return out


async def cases() -> list[Case]:
    return await _suite()


async def control() -> dict[str, Any]:
    with patch.object(access_module, "fresh_sign_in_left", lambda request, s: 300):
        results = await _suite()
    failed = [r["id"] for r in results if not r["passed"]]
    return {
        "name": "access: the fresh sign-in check skipped",
        "suite_failed": bool(failed),
        "failed_cases": failed,
    }
