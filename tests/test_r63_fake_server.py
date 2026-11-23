# tests/test_r63_fake_server.py -- R6.3 I0 seam 12: the fake server part C builds its console on
# answers every row of the HTTP contract in its own models, and the money rules hold there too: a
# grant answers 422 `yes_needed` with its terms until his typed YES on those terms; "yes" is not a
# YES; a stale estimate is 409; lowering a cap is instant; a guest's book session gets 403 on the
# pages. (The real routes are B's; the wired app at I1 checks console-only and the primary owner.)
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from r63_fake_server import (
    FIRST_ESTIMATE,
    GUEST_BOOK,
    OWNER_BOOK,
    TRIAL_ESTIMATE,
    FakeWriter,
    fake_app,
)

from jarvis.buildbook.writer import http
from jarvis.buildbook.writer.model import Caps
from jarvis.config import Settings
from jarvis.memory.inmemory import InMemorySessionStore

H = {"X-Requested-With": "JARVIS"}


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[tuple[AsyncClient, FakeWriter]]:
    state = FakeWriter()
    app = fake_app(state, settings=settings, store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, state


async def test_every_contract_row_answers_in_its_model(client: Any) -> None:
    c, state = client
    view = http.WriterView.model_validate((await c.get("/v1/book/writer", headers=H)).json())
    assert view.on and [b.id for b in view.brains] == ["anthropic", "gemini"]
    est = http.Estimate.model_validate(
        (await c.get("/v1/book/writer/estimate?run=trial", headers=H)).json()
    )
    assert (est.id, est.mid, est.cap, est.pages) == (TRIAL_ESTIMATE, 40, 100, 5)
    run = await c.post(
        "/v1/book/writer/trial", json={"typed": "YES", "estimate_id": est.id}, headers=H
    )
    assert http.RunView.model_validate(run.json()).state == "running"
    for _ in range(3):
        await c.post("/v1/book/writer/step", headers=H)
    rows = http.TrialPages.model_validate(
        (await c.get("/v1/book/writer/trial/pages", headers=H)).json()
    )
    assert [r.nn for r in rows.rows] == [1, 2, 3]
    one = await c.get("/v1/book/writer/trial/pages/2", headers=H)
    assert http.TrialPageView.model_validate(one.json()).page.meta is not None
    assert (await c.delete("/v1/book/writer/trial", headers=H)).json() == {"deleted": 3}
    assert state.calls == ["trial"]


@pytest.mark.parametrize("typed", ["yes", "Yes", "YES!", ""])
async def test_only_an_exact_yes_starts_the_trial(client: Any, typed: str) -> None:
    c, state = client
    r = await c.post(
        "/v1/book/writer/trial", json={"typed": typed, "estimate_id": TRIAL_ESTIMATE}, headers=H
    )
    assert r.status_code == 422 and r.json()["error"] == "not_yes" and state.calls == []


async def test_a_stale_estimate_asks_again(client: Any) -> None:
    c, state = client
    r = await c.post(
        "/v1/book/writer/trial", json={"typed": "YES", "estimate_id": "we_" + "9" * 12}, headers=H
    )
    assert r.status_code == 409 and r.json()["error"] == "estimate_changed" and state.calls == []


async def test_every_grant_needs_his_typed_yes_on_the_terms_shown(client: Any) -> None:
    c, state = client
    pick = {"brain": "anthropic", "caps": Caps().model_dump(), "auto_update": False}
    first = await c.put("/v1/book/writer/pick", json=pick, headers=H)
    need = http.YesNeeded.model_validate(first.json())
    assert first.status_code == 422 and need.words and state.pick.brain is None  # nothing saved
    wrong = await c.put(
        "/v1/book/writer/pick",
        json={**pick, "typed": "YES", "terms_id": "wt_" + "0" * 12},
        headers=H,
    )
    assert wrong.status_code == 409 and wrong.json()["error"] == "terms_changed"
    ok = await c.put(
        "/v1/book/writer/pick", json={**pick, "typed": "YES", "terms_id": need.terms_id}, headers=H
    )
    assert ok.status_code == 200 and state.pick.confirmed.terms_id == need.terms_id
    lower = {**pick, "caps": {**pick["caps"], "month": 600}}
    assert (
        await c.put("/v1/book/writer/pick", json=lower, headers=H)
    ).status_code == 200  # instant
    raise_ = {**pick, "caps": {**pick["caps"], "month": 1_200}}
    assert (await c.put("/v1/book/writer/pick", json=raise_, headers=H)).status_code == 422
    auto = {**lower, "auto_update": True}
    got = await c.put("/v1/book/writer/pick", json=auto, headers=H)
    assert got.status_code == 422 and any("by itself" in w for w in got.json()["words"])


async def test_the_first_write_needs_the_pick_then_a_second_yes(client: Any) -> None:
    c, state = client
    body = {"typed": "YES", "estimate_id": FIRST_ESTIMATE}
    r = await c.post("/v1/book/writer/first", json=body, headers=H)
    assert r.status_code == 409 and r.json()["error"] == "pick_needed"
    pick = {"brain": "anthropic", "caps": Caps().model_dump(), "auto_update": False}
    need = (await c.put("/v1/book/writer/pick", json=pick, headers=H)).json()
    await c.put(
        "/v1/book/writer/pick",
        json={**pick, "typed": "YES", "terms_id": need["terms_id"]},
        headers=H,
    )
    r = await c.post("/v1/book/writer/first", json=body, headers=H)
    assert r.status_code == 200 and r.json()["cap_inr"] == 1_500 and state.calls == ["first"]


async def test_the_pages_are_an_owner_sessions(client: Any) -> None:
    c, _ = client
    assert (
        await c.get("/v1/book/pages", headers={**H, "X-Jarvis-Book": GUEST_BOOK})
    ).status_code == 403
    assert (await c.get("/v1/book/pages", headers=H)).status_code == 401
    got = http.PagesView.model_validate(
        (await c.get("/v1/book/pages", headers={**H, "X-Jarvis-Book": OWNER_BOOK})).json()
    )
    assert got.limitations.total > got.limitations.shown and got.parts
    page = await c.get("/v1/book/pages/pg_card_c02", headers={**H, "X-Jarvis-Book": OWNER_BOOK})
    assert page.status_code == 200 and page.json()["meta"] is None  # "Not written by AI yet"
    gone = await c.get("/v1/book/pages/pg_card_c99", headers={**H, "X-Jarvis-Book": OWNER_BOOK})
    assert gone.status_code == 404 and gone.json()["error"] == "no_page"
