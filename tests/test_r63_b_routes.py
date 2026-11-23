# tests/test_r63_b_routes.py -- R6.3 part B's routes (docs/plans/r6-3-book-content.md "The HTTP
# contract", D13): the 13 rows of `writer/http.ROUTES` on the real app (Google sign-in faked, the
# show lock, R6's book sessions), the writer's service over the fakes swapped in. Console routes:
# signed in, console only, the primary owner only, no-store, the limits, plain refusals; the pages
# routes: an owner book session. No model is ever called.
from __future__ import annotations

from typing import Any

from book_app_fakes import (
    BEARER,
    CSRF,
    OWNER,
    SECOND_OWNER,
    book,
    book_app,
    open_book,
    owner_uid,
    register_passkey,
    sign_in,
)
from httpx import AsyncClient
from r63_fake_brains import claude_like, gemini_like, registry
from r63_fakes_b import seal_r6, service

from jarvis.buildbook.writer.http import ROUTES
from jarvis.config import Settings

W = "/v1/book/writer"


def _wire(app: Any) -> Any:
    built = service(
        brains=registry(claude_like(), gemini_like()), uid=owner_uid(OWNER), emails=(OWNER,)
    )
    app.state.book_writer = built.service
    return built


async def test_the_console_routes_run_a_trial_for_the_primary_owner(settings: Settings) -> None:
    async for app in book_app(settings):
        _wire(app)
        async with AsyncClient(transport=app.transport, base_url="http://test") as bare:
            assert (await bare.get(W)).status_code == 401
            r = await bare.get(W, headers=BEARER)
            assert r.status_code == 403 and r.json()["error"] == "console_only"
        async with sign_in(app) as c:
            r = await c.get(W)
            assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
            assert r.json()["on"] is True and "$" not in r.text
            est = (await c.get(f"{W}/estimate", params={"run": "trial"})).json()
            assert est["cap"] == 100 and "$" not in str(est)
            no = await c.post(f"{W}/trial", json={"typed": "yes", "estimate_id": est["id"]},
                              headers=CSRF)  # fmt: skip
            assert no.status_code == 422 and no.json()["error"] == "not_yes"
            ok = await c.post(f"{W}/trial", json={"typed": "YES", "estimate_id": est["id"]},
                              headers=CSRF)  # fmt: skip
            assert ok.status_code == 200 and ok.json()["state"] == "queued"
            assert (await c.post(f"{W}/step", headers=CSRF)).json()["state"] == "done"
            rows = (await c.get(f"{W}/trial/pages")).json()["rows"]
            assert len(rows) == 10
            one = await c.get(f"{W}/trial/pages/01")
            assert one.status_code == 200 and one.json()["page"]["meta"]["tier"] == "balanced"
            assert (await c.get(f"{W}/trial/pages/11")).status_code == 404
            gone = await c.request("DELETE", f"{W}/trial", headers=CSRF)
            assert gone.json() == {"deleted": 10}


async def test_the_pick_answers_yes_needed_with_its_words_and_saves_on_the_yes(
    settings: Settings,
) -> None:
    async for app in book_app(settings):
        _wire(app)
        async with sign_in(app) as c:
            pick = {"brain": "anthropic", "caps": {"trial": 100, "first": 1500, "release": 500,
                                                   "month": 1000, "limit_pct": 80}}  # fmt: skip
            r = await c.put(f"{W}/pick", json=pick, headers=CSRF)
            body = r.json()
            assert r.status_code == 422 and body["error"] == "yes_needed"
            assert body["terms_id"].startswith("wt_") and any("₹" in w for w in body["words"])
            yes = {**pick, "typed": "YES", "terms_id": body["terms_id"]}
            r = await c.put(f"{W}/pick", json=yes, headers=CSRF)
            assert r.status_code == 200 and r.json()["confirmed"]["brain"] == "anthropic"
            bad = {**pick, "caps": {**pick["caps"], "release": 9_999}}
            r = await c.put(f"{W}/pick", json=bad, headers=CSRF)
            assert r.status_code == 422 and r.json()["error"] == "bad_cap"
            r = await c.post(f"{W}/first", json={"typed": "YES", "estimate_id": "we_" + "0" * 12},
                             headers=CSRF)  # fmt: skip
            assert r.status_code == 409 and r.json()["error"] == "estimate_changed"


async def test_another_owner_is_not_primary_and_the_step_is_limited(settings: Settings) -> None:
    async for app in book_app(settings):
        _wire(app)
        async with sign_in(app, SECOND_OWNER) as c:
            r = await c.get(W)
            assert r.status_code == 403 and r.json()["error"] == "not_primary"
        async with sign_in(app) as c:
            codes = [(await c.post(f"{W}/step", headers=CSRF)).status_code for _ in range(7)]
            assert codes[:6] == [200] * 6 and codes[6] == 429


async def test_the_pages_need_an_owner_book_session_and_a_guest_never_reaches_the_writer(
    settings: Settings,
) -> None:
    async for app in book_app(settings):
        built = _wire(app)
        await seal_r6(built)
        async with sign_in(app) as c:
            assert (await c.get("/v1/book/pages")).status_code == 401  # no book session
            auth = await register_passkey(c)
            owner = await open_book(c, auth, "owner")
            r = await c.get("/v1/book/pages", headers=book(owner["token"]))
            assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
            assert {p["id"] for p in r.json()["parts"]} >= {"parts", "modules"}
            r = await c.get("/v1/book/pages/pg_card_c01", headers=book(owner["token"]))
            assert r.status_code == 200 and r.json()["meta"] is None
            r = await c.get("/v1/book/pages/pg_card_c99", headers=book(owner["token"]))
            assert r.status_code == 404 and r.json()["error"] == "no_page"
            r = await c.get("/v1/book/pages", params={"release": "0000000"},
                            headers=book(owner["token"]))  # fmt: skip
            assert r.status_code == 404
            await c.post("/v1/book/close", json={}, headers=book(owner["token"]))
            guest = await open_book(c, auth, "guest")
            for method, path, *_rest in ROUTES:
                url = path.replace("{nn}", "01").replace("{page_id}", "pg_card_c01")
                r = await c.request(method, url, headers=book(guest["token"]),
                                    json=None if method in ("GET", "DELETE") else {})  # fmt: skip
                assert r.status_code in (403, 423), (method, path, r.status_code)
