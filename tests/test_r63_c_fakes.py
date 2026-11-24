# tests/test_r63_c_fakes.py -- R6.3 Part C: the fake server the console's browser tests drive
# (tests/r63_fakes_c.py) answers in the HTTP contract's models (buildbook/writer/http.py), so what
# the console draws is what the routes answer: the full book for an OWNER session only (a guest
# 403), a page with its `flow` (R6.3.1 D7), an older release with nothing written, and C74 at the
# next release. (R6.3.1 D8: the writer's fake routes went with the writer.)
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from r63_fakes import RELEASE
from r63_fakes_c import CONTROL, GUEST_BOOK, NEW_CARD, OWNER_BOOK, WRITTEN, c_app

from jarvis.buildbook.writer import http
from jarvis.buildbook.writer.model import Page

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


def test_the_full_book_is_the_owners_session_only(client: Any) -> None:
    assert client.get("/v1/book/pages", headers=AUTH).status_code == 401
    guest = client.get("/v1/book/pages", headers={**AUTH, "X-Jarvis-Book": GUEST_BOOK})
    assert (guest.status_code, guest.json()["error"]) == (403, "owner_only")
    view = http.PagesView.model_validate(client.get("/v1/book/pages", headers=OWNER).json())
    rows = {p.id: p for part in view.parts for ch in part.chapters for p in ch.pages}
    meta = rows[WRITTEN].written
    assert meta is not None and meta.written_by.startswith("Workshop")
    assert (view.limitations.shown, view.limitations.total) == (80, 112)
    body = client.get(f"/v1/book/pages/{WRITTEN}", headers=OWNER).json()
    assert body["flow"] is None  # R6.3.1 D7: the page JSON gains `flow` (null without a chart)
    page = Page.model_validate({k: v for k, v in body.items() if k != "flow"})
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
