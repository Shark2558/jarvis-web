# tests/test_r63_c_fakes.py -- R6.3 Part C: the fake server the console's browser tests drive
# (tests/r63_fakes_c.py over I0's tests/r63_fake_server.py) answers in the HTTP contract's models
# (buildbook/writer/http.py), so what the console draws is what B's routes will answer: the writer
# off, a stale estimate (409 then the fresh one), a set refusal, every grant's 422 `yes_needed`
# with its Rs words until the typed YES, "yes" refused by the server, the full book for an OWNER
# session only (a guest 403), an older release with nothing written, and C74 at the next release.
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from r63_fakes import RELEASE
from r63_fakes_c import (
    CHANGED,
    CONTROL,
    GUEST_BOOK,
    NEW_CARD,
    OWNER_BOOK,
    STALE_ESTIMATE,
    WRITTEN,
    c_app,
)

from jarvis.buildbook.writer import http

TOKEN = "r63-c-test-token-not-a-secret"
AUTH = {"Authorization": f"Bearer {TOKEN}", "X-Requested-With": "JARVIS"}
OWNER = {**AUTH, "X-Jarvis-Book": OWNER_BOOK}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    for key, value in {
        "JARVIS_ENV": "dev",
        "JARVIS_AUTH_MODE": "token",
        "JARVIS_API_TOKEN": TOKEN,
        "JARVIS_SESSION_BACKEND": "memory",
        "JARVIS_LLM_BACKEND": "mock",
        "JARVIS_USD_INR_LIVE": "0",
    }.items():
        monkeypatch.setenv(key, value)
    with TestClient(c_app()) as c:
        yield c


def _set(client: Any, **state: Any) -> None:
    assert client.post(CONTROL, json=state).status_code == 200


def test_the_writer_off_says_why_and_nothing_else(client: Any) -> None:
    _set(client, off="no_key")
    got = http.WriterView.model_validate(client.get("/v1/book/writer", headers=AUTH).json())
    assert (got.on, got.why, got.brains) == (False, "no_key", ())
    _set(client, reset=True)
    assert client.get("/v1/book/writer", headers=AUTH).json()["on"] is True


def test_a_stale_estimate_is_refused_then_the_fresh_one_starts(client: Any) -> None:
    _set(client, stale={"trial": 1})
    old = client.get("/v1/book/writer/estimate?run=trial", headers=AUTH).json()["id"]
    assert old == STALE_ESTIMATE
    no = client.post(
        "/v1/book/writer/trial", json={"typed": "YES", "estimate_id": old}, headers=AUTH
    )
    assert (no.status_code, no.json()["error"]) == (409, "estimate_changed")
    new = http.Estimate.model_validate(
        client.get("/v1/book/writer/estimate?run=trial", headers=AUTH).json()
    )
    assert new.id != STALE_ESTIMATE and new.cap == 100 and new.mid == 40
    body = {"typed": "yes", "estimate_id": new.id}
    no = client.post("/v1/book/writer/trial", json=body, headers=AUTH)
    assert (no.status_code, no.json()["error"]) == (422, "not_yes")  # the server's word
    body["typed"] = "YES"
    run = http.RunView.model_validate(
        client.post("/v1/book/writer/trial", json=body, headers=AUTH).json()
    )
    assert (run.kind, run.state) == ("trial", "running")


def test_a_refusal_set_by_the_test_answers_first(client: Any) -> None:
    _set(client, refuse={"first": [409, "already_written", "The full book is written."]})
    got = client.post(
        "/v1/book/writer/first",
        json={"typed": "YES", "estimate_id": "we_" + "2" * 12},
        headers=AUTH,
    )
    assert (got.status_code, got.json()) == (
        409,
        {"error": "already_written", "detail": "The full book is written."},
    )
    seen = client.get(CONTROL).json()
    assert "POST /v1/book/writer/first?" in seen["asked"] and seen["calls"] == []


def test_every_grant_needs_the_typed_yes_on_its_terms(client: Any) -> None:
    pick = {"brain": "anthropic", "caps": http.Caps().model_dump(), "auto_update": False}
    need = client.put("/v1/book/writer/pick", json=pick, headers=AUTH)
    assert need.status_code == 422
    yes = http.YesNeeded.model_validate(need.json())
    assert yes.words and "$" not in " ".join(yes.words)
    again = client.put(
        "/v1/book/writer/pick",
        json={**pick, "typed": "YES", "terms_id": yes.terms_id},
        headers=AUTH,
    )
    assert again.status_code == 200 and again.json()["brain"] == "anthropic"
    lower = {**pick, "caps": {**pick["caps"], "month": 600}}
    assert client.put("/v1/book/writer/pick", json=lower, headers=AUTH).status_code == 200


def test_the_full_book_is_the_owners_session_only(client: Any) -> None:
    assert client.get("/v1/book/pages", headers=AUTH).status_code == 401
    guest = client.get("/v1/book/pages", headers={**AUTH, "X-Jarvis-Book": GUEST_BOOK})
    assert (guest.status_code, guest.json()["error"]) == (403, "owner_only")
    view = http.PagesView.model_validate(client.get("/v1/book/pages", headers=OWNER).json())
    rows = {p.id: p for part in view.parts for ch in part.chapters for p in ch.pages}
    assert rows[WRITTEN].written is not None and rows[CHANGED].changed
    assert (view.limitations.shown, view.limitations.total) == (80, 112)
    page = http.Page.model_validate(client.get(f"/v1/book/pages/{WRITTEN}", headers=OWNER).json())
    assert page.meta is not None and page.sections[1].heading == "Example (made up)"
    assert next(s for s in page.sections if s.id == "code").refs


def test_an_older_release_has_nothing_written_and_c74_comes_at_the_next(client: Any) -> None:
    old = client.get("/v1/book/pages?release=aebff3a", headers=OWNER).json()
    assert old["release"] == "aebff3a"
    assert all(
        p["written"] is None
        for part in old["parts"]
        for ch in part["chapters"]
        for p in ch["pages"]
    )
    ids = lambda v: {p["id"] for part in v["parts"] for ch in part["chapters"] for p in ch["pages"]}  # noqa: E731
    assert NEW_CARD not in ids(client.get("/v1/book/pages", headers=OWNER).json())
    _set(client, new_card=True)
    view = client.get(f"/v1/book/pages?release={RELEASE.id}", headers=OWNER).json()
    assert NEW_CARD in ids(view)
    assert client.get(f"/v1/book/pages/{NEW_CARD}", headers=OWNER).status_code == 200


def test_the_side_by_side_has_a_redraft_and_a_refusal_with_their_checks(client: Any) -> None:
    _set(client, trial_done=True)
    rows = http.TrialPages.model_validate(
        client.get("/v1/book/writer/trial/pages", headers=AUTH).json()
    ).rows
    assert len(rows) == 10 and {r.brain for r in rows} == {"anthropic", "gemini"}
    by = {r.nn: r for r in rows}
    assert (by[4].state, by[4].checks) == ("redrafted", ("numbers",))
    assert (by[9].state, by[9].checks) == ("refused", ("refs", "planned"))
