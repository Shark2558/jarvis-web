# tests/test_book_api.py -- R6 "Contract" (builder B): GET /v1/book (status; seals the current
# release for the primary owner at console boot, bounded), the owner's sections and older releases'
# sections behind a live OWNER book session (X-Jarvis-Book, checked through the BookSessions port),
# 60 s single-use code-download tickets, the download (audited first, attachment, nosniff) and
# Book settings. Every answer no-store, every failure {error, detail}.
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from book_seal_fakes import (
    GUEST_TOKEN,
    OWNER_TOKEN,
    FakeAudit,
    FakeNotifier,
    FakeSessions,
    FakeSource,
    chunk_paths,
    failed_release,
    make_release,
    ring,
    view,
)
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.buildbook.lock import DocShowLock
from jarvis.buildbook.model import ShowLockState, TalkState
from jarvis.buildbook.owner import BookSettingsStore, BookTickets
from jarvis.buildbook.ports import LockUnreadable, SessionGone
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.sealer import BookSealer, SealOutcome
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs

OWNER = "akash@example.com"
OTHER = "partner@example.com"
UID = user_id_for_email(OWNER)
OTHER_UID = user_id_for_email(OTHER)
CSRF = {"X-Requested-With": "JARVIS"}
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


class Perms:
    def __init__(self, in_force: bool = False) -> None:
        self.in_force = in_force

    async def passkey_required(self, uid: str) -> bool:
        return self.in_force


class Rig:
    def __init__(self, c: AsyncClient, app: Any, docs: MemoryDocs) -> None:
        self.c, self.app, self.docs = c, app, docs
        st = app.state
        self.source: FakeSource = st.book_source
        self.vault: DocsBookVault = st.book_vault
        self.sessions: FakeSessions = st.book_sessions
        self.notes: FakeNotifier = st.test_notes
        self.audit: FakeAudit = st.gateway.audit

    async def get(self, path: str, token: str | None = None) -> Response:
        return await self.c.get(path, headers={"X-Jarvis-Book": token} if token else {})

    async def post(self, path: str, token: str | None = None, **kw: Any) -> Response:
        h = {**CSRF, **({"X-Jarvis-Book": token} if token else {})}
        return await self.c.post(path, headers=h, **kw)


@pytest.fixture
def gsettings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER, OTHER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
            "token_key": SecretStr(KEY_B64),
        }
    )


def wire(app: Any, docs: MemoryDocs) -> None:
    """What I1's wire_r6 puts on app.state for builder B's routes (C's parts are fakes: the real
    ones I1 wires from the token key are taken off; tests/test_r6_wiring.py covers them)."""
    st = app.state
    st.book_service = st.book_talk = st.book_jobs = None
    st.book_lock = DocShowLock(docs, cache_s=0)  # SEC-3: a Google app always has a lock store
    st.test_notes = FakeNotifier()
    st.book_source = FakeSource(*make_release(1))
    st.book_vault = DocsBookVault(docs, ring(), limit_mb=60)
    st.book_sealer = BookSealer(
        st.book_source, st.book_vault, docs, notifier=st.test_notes, audit=None,
        owner_emails=[OWNER, OTHER],
    )  # fmt: skip
    st.book_sessions = FakeSessions()
    st.book_tickets = BookTickets(docs, ring())
    st.book_settings = BookSettingsStore(docs)
    st.permissions = Perms()
    st.gateway = SimpleNamespace(audit=FakeAudit())


@pytest.fixture
async def rig(gsettings: Settings) -> AsyncIterator[Rig]:
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        docs = MemoryDocs()
        wire(app, docs)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield Rig(c, app, docs)


async def login(c: AsyncClient, email: str = OWNER) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": email, "email_verified": True, "sub": email}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await c.get("/auth/callback?code=a&state=b")).status_code in (302, 307)


def no_store(r: Response) -> None:
    assert r.headers["cache-control"] == "no-store", r.text
    assert r.headers["x-content-type-options"] == "nosniff"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def owner_rig(rig: Rig) -> Rig:
    """Signed in, with a live OWNER book session (OWNER_TOKEN) and a guest token."""
    await login(rig.c)
    rig.sessions.grant(OWNER_TOKEN, UID, "owner")
    rig.sessions.grant(GUEST_TOKEN, UID, "guest")
    rig.sessions.live_view = rig.sessions.view_of(OWNER_TOKEN, _utcnow())
    return rig


# ---- GET /v1/book --------------------------------------------------------------------------


async def test_status_seals_the_current_release_at_console_boot_and_says_so(rig: Rig) -> None:
    await login(rig.c)
    r = await rig.get("/v1/book")
    assert r.status_code == 200, r.text
    no_store(r)
    body = r.json()
    release = rig.source.release
    assert release is not None
    assert body["available"] is True and "reason" not in body
    assert body["release"] == {
        "id": release.id,
        "label": "R6",
        "sha": release.sha,
        "committed_at": release.committed_at,
    }
    assert [s["id"] for s in body["sealed"]] == [release.id]
    assert set(body["sealed"][0]) == {"id", "label", "sealed_at", "mb"}
    assert (body["kept"], body["limit_mb"], body["used_mb"]) == (3, 60, 0.0)
    assert body["sealing"] is False and body["sealed_ok"] is True
    assert body["session"] is None and body["lock"] == {"on": False}
    assert body["last_closed"] is None
    assert body["talk"]["on"] is False and body["talk"]["why"]
    assert body["open"] == {"passkey_ready": False, "fresh_left_s": 0}
    assert rig.notes.kinds() == ["book_sealed"]
    assert (await rig.get("/v1/book")).json()["sealed"] == body["sealed"]
    assert rig.notes.kinds() == ["book_sealed"]


async def test_only_the_primary_owner_seals_from_the_status_route(rig: Rig) -> None:
    await login(rig.c, OTHER)
    body = (await rig.get("/v1/book")).json()
    assert body["available"] is True and body["sealed"] == []
    assert await rig.vault.releases(UID) == () and rig.notes.sent == []


async def test_status_without_a_book_or_with_a_failed_build(rig: Rig) -> None:
    await login(rig.c)
    rig.source.use(None)
    body = (await rig.get("/v1/book")).json()
    assert body["available"] is False and body["reason"] == "This server has no build book."
    assert body["release"] is None
    rig.source.use(failed_release(2))
    body = (await rig.get("/v1/book")).json()
    assert body["available"] is False and "could not be built" in body["reason"]
    assert body["release"]["id"] == failed_release(2).id


async def test_status_while_sealing_takes_longer_than_the_request(rig: Rig) -> None:
    class Slow:
        async def ensure_bounded(self, uid: str, *, within_s: float = 20) -> SealOutcome:
            assert within_s == 20
            return SealOutcome("sealing")

    rig.app.state.book_sealer = Slow()
    await login(rig.c)
    assert (await rig.get("/v1/book")).json()["sealing"] is True


def _past_the_lock_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    """With I1's wiring C's ShowLockMiddleware answers a locked or unreadable lock first (423 /
    503); these tests reach B's own status body, which must ALSO fail closed (D10)."""
    monkeypatch.setattr("jarvis.api.book_lock.allowed", lambda method, path: True)


async def test_status_reads_the_live_parts_and_fails_closed_on_the_lock(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    _past_the_lock_middleware(monkeypatch)

    class Lock:
        def __init__(self, state: ShowLockState | None | Exception) -> None:
            self.state = state

        async def get(self, uid: str) -> ShowLockState | None:
            if isinstance(self.state, Exception):
                raise self.state
            return self.state

    class Talk:
        async def state(self, uid: str) -> TalkState:
            return TalkState(on=True)

    class Service:
        async def last_closed(self, uid: str) -> dict[str, Any]:
            return {"at": "2026-11-10T14:25:00+05:30", "notified": True}

    st = rig.app.state
    st.book_lock, st.book_talk, st.book_service = Lock(None), Talk(), Service()
    st.permissions = Perms(in_force=True)
    rig.sessions.live_view = view("guest")
    await login(rig.c)
    body = (await rig.get("/v1/book")).json()
    assert body["lock"] == {"on": False} and body["talk"] == {"on": True}
    assert body["last_closed"] == {"at": "2026-11-10T14:25:00+05:30", "notified": True}
    assert body["open"]["passkey_ready"] is True
    assert body["session"]["audience"] == "guest" and "session_id" not in body["session"]
    st.book_lock = Lock(LockUnreadable("x"))
    assert (await rig.get("/v1/book")).json()["lock"] == {"on": True}
    lock = ShowLockState(
        id="bl_" + "a" * 12, bk="bk_" + "1" * 16, since="2026-11-10T09:00:00+00:00"
    )
    st.book_lock = Lock(lock)
    assert (await rig.get("/v1/book")).json()["lock"] == {"on": True}


async def test_a_tampered_index_shows_in_the_status_without_breaking_it(rig: Rig) -> None:
    await login(rig.c)
    await rig.get("/v1/book")
    path = f"jarvis_book/{UID}"
    rig.docs._data[path]["blob"] = rig.docs._data[path]["blob"][:-4] + "AAA="
    body = (await rig.get("/v1/book")).json()
    assert body["sealed_ok"] is False and body["sealed"] == [] and body["available"] is True


async def test_nothing_wired_is_book_off(rig: Rig) -> None:
    for name in ("book_source", "book_vault", "book_sessions", "book_tickets", "book_settings"):
        setattr(rig.app.state, name, None)
    await login(rig.c)
    for path in ("/v1/book/sections", "/v1/book/settings"):
        r = await rig.get(path, OWNER_TOKEN)
        assert r.status_code == 503 and r.json()["error"] == "book_off", path
        no_store(r)
    r = await rig.get("/v1/book", OWNER_TOKEN)  # I1: the panel says why, no error at boot
    assert r.status_code == 200 and r.json()["available"] is False and r.json()["reason"]
    no_store(r)


# ---- sections, behind an owner book session -------------------------------------------------


async def test_sections_need_a_live_owner_book_session(rig: Rig) -> None:
    await owner_rig(rig)
    for token, status, code in [
        (None, 401, "session_gone"),
        ("x" * 43, 401, "session_gone"),
        ("y" * 200, 401, "session_gone"),
        (GUEST_TOKEN, 403, "owner_only"),
    ]:
        r = await rig.get("/v1/book/sections", token)
        assert (r.status_code, r.json()["error"]) == (status, code), token
        no_store(r)
    r = await rig.get("/v1/book/sections", OWNER_TOKEN)
    assert r.status_code == 200
    no_store(r)
    body = r.json()
    assert body["release"]["id"] == rig.source.release.id  # type: ignore[union-attr]
    assert list(body["sections"]) == [
        "architecture",
        "stack",
        "libraries",
        "integrations",
        "workflows",
        "limitations",
        "costs",
        "decisions",
    ]


async def test_a_token_from_another_owner_opens_nothing(rig: Rig) -> None:
    await login(rig.c, OTHER)
    rig.sessions.grant(OWNER_TOKEN, UID, "owner")
    assert (await rig.get("/v1/book/sections", OWNER_TOKEN)).status_code == 401


async def test_a_bearer_script_gets_no_book(rig: Rig) -> None:
    rig.sessions.grant(OWNER_TOKEN, UID, "owner")
    h = {"Authorization": "Bearer cli-token", "X-Jarvis-Book": OWNER_TOKEN}
    for path in ("/v1/book/sections", "/v1/book/releases/0000000/sections"):
        r = await rig.c.get(path, headers=h)
        assert (r.status_code, r.json()["error"]) == (403, "console_only"), path
    r = await rig.c.post("/v1/book/releases/0000000/ticket", headers=h)
    assert r.json()["error"] == "console_only"


async def test_no_book_on_the_server_is_404_for_sections(rig: Rig) -> None:
    await owner_rig(rig)
    rig.source.use(None)
    r = await rig.get("/v1/book/sections", OWNER_TOKEN)
    assert (r.status_code, r.json()["error"]) == (404, "no_book")


async def test_an_older_sealed_release_opens_for_the_owner_only(rig: Rig) -> None:
    await owner_rig(rig)
    await rig.get("/v1/book")  # seals release 1
    first = rig.source.release
    assert first is not None
    rig.source.use(*make_release(2))
    await rig.get("/v1/book")  # seals release 2
    r = await rig.get(f"/v1/book/releases/{first.id}/sections", OWNER_TOKEN)
    assert r.status_code == 200, r.text
    no_store(r)
    assert r.json()["release"]["id"] == first.id and "costs" in r.json()["sections"]
    r = await rig.get(f"/v1/book/releases/{first.id}/sections", GUEST_TOKEN)
    assert r.status_code == 403
    for rid in ("fffffff", "3f2a1c", "ABCDEF0", "0" * 8, "3f2a1c9."):
        r = await rig.get(f"/v1/book/releases/{rid}/sections", OWNER_TOKEN)
        assert (r.status_code, r.json()["error"]) == (404, "not_found"), rid


async def test_a_tampered_sealed_book_stays_closed_and_the_owner_is_told_once(rig: Rig) -> None:
    await owner_rig(rig)
    await rig.get("/v1/book")
    rid = rig.source.release.id  # type: ignore[union-attr]
    for p in chunk_paths(rig.docs):
        rig.docs._data[p]["blob"] = rig.docs._data[p]["blob"][:-8] + "AAAAAAA="
    for _ in range(2):
        r = await rig.get(f"/v1/book/releases/{rid}/sections", OWNER_TOKEN)
        assert (r.status_code, r.json()["error"]) == (503, "tampered")
        no_store(r)
    assert rig.notes.kinds() == ["book_sealed", "book_seal_failed"]
    assert "failed its integrity check" in rig.notes.sent[-1][2]


# ---- tickets and the download ---------------------------------------------------------------


async def _ticket(rig: Rig, rid: str, token: str = OWNER_TOKEN) -> Response:
    return await rig.post(f"/v1/book/releases/{rid}/ticket", token)


async def test_the_sealed_code_downloads_once_with_a_ticket(rig: Rig) -> None:
    await owner_rig(rig)
    await rig.get("/v1/book")
    rid = rig.source.release.id  # type: ignore[union-attr]
    r = await _ticket(rig, rid)
    assert r.status_code == 200, r.text
    no_store(r)
    assert r.json()["expires_in_s"] == 60
    ticket = r.json()["ticket"]
    got = await rig.c.get(f"/v1/book/download/{ticket}")
    assert got.status_code == 200
    assert got.content == rig.source.files["source"]
    assert got.headers["content-type"] == "application/zip"
    assert got.headers["content-disposition"] == f'attachment; filename="JARVIS-source-{rid}.zip"'
    no_store(got)
    assert rig.audit.rows[-1]["tool"] == "book_download"
    assert rig.audit.rows[-1]["args"] == {"release": rid}
    again = await rig.c.get(f"/v1/book/download/{ticket}")
    assert (again.status_code, again.json()["error"]) == (410, "gone")
    no_store(again)


async def test_tickets_are_for_the_owner_and_sealed_releases_only(rig: Rig) -> None:
    await owner_rig(rig)
    await rig.get("/v1/book")
    rid = rig.source.release.id  # type: ignore[union-attr]
    assert (await _ticket(rig, rid, GUEST_TOKEN)).status_code == 403
    assert (await _ticket(rig, rid, "x" * 43)).status_code == 401
    r = await _ticket(rig, "fffffff")
    assert (r.status_code, r.json()["error"]) == (404, "not_found")
    assert (await rig.c.post(f"/v1/book/releases/{rid}/ticket")).status_code == 403  # no CSRF


async def test_a_bad_or_foreign_ticket_is_gone(rig: Rig) -> None:
    await owner_rig(rig)
    await rig.get("/v1/book")
    rid = rig.source.release.id  # type: ignore[union-attr]
    ticket = (await _ticket(rig, rid)).json()["ticket"]
    for bad in ("short", "x" * 43, ticket + "!"):
        r = await rig.c.get(f"/v1/book/download/{bad}")
        assert (r.status_code, r.json()["error"]) == (410, "gone"), bad
    await login(rig.c, OTHER)
    assert (await rig.c.get(f"/v1/book/download/{ticket}")).status_code == 410


async def test_nothing_is_sent_unless_the_download_is_audited(rig: Rig) -> None:
    await owner_rig(rig)
    await rig.get("/v1/book")
    rid = rig.source.release.id  # type: ignore[union-attr]
    ticket = (await _ticket(rig, rid)).json()["ticket"]
    rig.audit.fail = True
    r = await rig.c.get(f"/v1/book/download/{ticket}")
    assert r.status_code == 503 and b"PK" not in r.content
    no_store(r)


async def test_too_many_tickets_are_refused(rig: Rig) -> None:
    await owner_rig(rig)
    await rig.get("/v1/book")
    rid = rig.source.release.id  # type: ignore[union-attr]
    codes = [(await _ticket(rig, rid)).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and codes[-1] == 429


# ---- Book settings ---------------------------------------------------------------------------


async def test_settings_round_trip_and_the_audit_names_fields_only(rig: Rig) -> None:
    await login(rig.c)
    r = await rig.get("/v1/book/settings")
    assert r.status_code == 200
    no_store(r)
    assert r.json() == {
        "creator_name": "",
        "show_voice": "cloud",
        "talk_on": True,
        "allow_training_brain": False,
        "creator_max": 40,
    }
    r = await rig.c.put(
        "/v1/book/settings",
        json={"creator_name": "Akash Das", "show_voice": "browser"},
        headers=CSRF,
    )
    assert r.status_code == 200, r.text
    no_store(r)
    assert r.json()["creator_name"] == "Akash Das" and r.json()["show_voice"] == "browser"
    assert (await rig.get("/v1/book/settings")).json()["creator_name"] == "Akash Das"
    row = rig.audit.rows[-1]
    assert row["tool"] == "book_settings" and row["args"] == {
        "fields": ["creator_name", "show_voice"]
    }
    assert "Akash" not in str(rig.audit.rows)


@pytest.mark.parametrize(
    "body",
    [
        {"creator_name": "<b>me</b>"},
        {"talk_on": "yes"},
        {"show_voice": "robot"},
        {"sneaky": True},
        ["creator_name"],
        "x",
    ],
)
async def test_a_bad_settings_change_is_refused_without_echoing_it(rig: Rig, body: Any) -> None:
    await login(rig.c)
    r = await rig.c.put("/v1/book/settings", json=body, headers=CSRF)
    assert (r.status_code, r.json()["error"]) == (422, "input_rejected")
    no_store(r)
    assert "<b>" not in r.text and "robot" not in r.text and "sneaky" not in r.text
    assert (await rig.get("/v1/book/settings")).json()["creator_name"] == ""


async def test_a_settings_change_needs_the_csrf_header(rig: Rig) -> None:
    await login(rig.c)
    r = await rig.c.put("/v1/book/settings", json={"talk_on": False})
    assert r.status_code == 403


async def test_a_ticket_store_outage_is_a_plain_503(rig: Rig) -> None:
    await owner_rig(rig)
    await rig.get("/v1/book")
    rid = rig.source.release.id  # type: ignore[union-attr]

    async def down(*_: Any, **__: Any) -> Any:
        raise RuntimeError("firestore down")

    rig.app.state.book_tickets.issue = down
    r = await _ticket(rig, rid)
    assert (r.status_code, r.json()["error"]) == (503, "unavailable")
    no_store(r)
    rig.app.state.book_tickets.take = down
    r = await rig.c.get("/v1/book/download/" + "t" * 43)
    assert (r.status_code, r.json()["error"]) == (503, "unavailable")


# ---- review fixes: tickets bound to their session, C's close on resolve, plain answers --------


async def test_a_ticket_dies_with_the_book_session_that_asked_for_it(rig: Rig) -> None:
    await owner_rig(rig)
    await rig.get("/v1/book")
    rid = rig.source.release.id  # type: ignore[union-attr]
    ticket = (await _ticket(rig, rid)).json()["ticket"]
    rig.sessions.live_view = None  # End, expiry, idle or a Privacy close
    r = await rig.c.get(f"/v1/book/download/{ticket}")
    assert (r.status_code, r.json()["error"]) == (410, "gone")
    no_store(r)
    ticket = (await _ticket(rig, rid)).json()["ticket"]
    rig.sessions.grant("n" * 43, UID, "owner")  # a newer open ended the one the ticket is for
    rig.sessions.live_view = rig.sessions.view_of("n" * 43, _utcnow())
    r = await rig.c.get(f"/v1/book/download/{ticket}")
    assert (r.status_code, r.json()["error"]) == (410, "gone")
    assert [row["tool"] for row in rig.audit.rows] == []  # nothing was sent, nothing audited


async def test_a_ticket_never_outlives_its_sessions_idle_limit(rig: Rig) -> None:
    await owner_rig(rig)
    await rig.get("/v1/book")
    rig.sessions.idle_s = 10
    r = await _ticket(rig, rig.source.release.id)  # type: ignore[union-attr]
    assert r.status_code == 200 and 1 <= r.json()["expires_in_s"] <= 10


async def test_the_routes_resolve_through_the_book_service_when_it_is_wired(rig: Rig) -> None:
    class Service:
        """C's BookService.resolve: an expired session is finished (audit, notice), then gone."""

        def __init__(self) -> None:
            self.finished: list[str] = []

        async def resolve(self, uid: str, token: str, *, now: dt.datetime) -> Any:
            if token == OWNER_TOKEN:
                self.finished.append(uid)
                raise SessionGone("ended")
            return await rig.sessions.resolve(uid, token, now=now)

    await owner_rig(rig)
    rig.app.state.book_service = Service()
    for path in ("/v1/book/sections", "/v1/book/releases/0000000/sections"):
        r = await rig.get(path, OWNER_TOKEN)
        assert (r.status_code, r.json()["error"]) == (401, "session_gone"), path
    r = await _ticket(rig, "0000000")
    assert (r.status_code, r.json()["error"]) == (401, "session_gone")
    assert rig.app.state.book_service.finished == [UID] * 3
    assert (await rig.get("/v1/book/sections", GUEST_TOKEN)).status_code == 403


async def test_a_session_store_outage_is_a_plain_503(rig: Rig) -> None:
    await owner_rig(rig)

    async def down(*_: Any, **__: Any) -> Any:
        raise RuntimeError("firestore down")

    rig.sessions.resolve = down  # type: ignore[method-assign]
    r = await rig.get("/v1/book/sections", OWNER_TOKEN)
    assert (r.status_code, r.json()["error"]) == (503, "unavailable")
    no_store(r)


async def test_a_book_source_that_breaks_is_a_plain_503(rig: Rig) -> None:
    await owner_rig(rig)

    def boom(*_: Any) -> Any:
        raise RuntimeError("package resource")

    rig.source.current = boom  # type: ignore[method-assign]
    rig.source.book = boom  # type: ignore[method-assign]
    for path in ("/v1/book", "/v1/book/sections"):
        r = await rig.get(path, OWNER_TOKEN)
        assert (r.status_code, r.json()["error"]) == (503, "unavailable"), path
        no_store(r)


@pytest.mark.parametrize("raw", [b"{not json", b'{"talk_on": tru', b"\xff\xfe", b"9" * 5000])
async def test_malformed_settings_json_is_input_rejected(rig: Rig, raw: bytes) -> None:
    await login(rig.c)
    h = {**CSRF, "Content-Type": "application/json"}
    r = await rig.c.put("/v1/book/settings", content=raw, headers=h)
    assert (r.status_code, r.json()["error"]) == (422, "input_rejected")
    no_store(r)
    assert "json_invalid" not in r.text


async def test_unreadable_lock_and_passkey_stores_leave_a_trace(
    rig: Rig, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    _past_the_lock_middleware(monkeypatch)

    class Broken:
        async def get(self, uid: str) -> Any:
            raise LockUnreadable("x")

        async def passkey_required(self, uid: str) -> bool:
            raise RuntimeError("permissions store")

    rig.app.state.book_lock = rig.app.state.permissions = Broken()
    await login(rig.c)
    with caplog.at_level(logging.WARNING):
        body = (await rig.get("/v1/book")).json()
    assert body["lock"] == {"on": True} and body["open"]["passkey_ready"] is False
    seen = {(r.getMessage(), getattr(r, "error", None)) for r in caplog.records}
    assert ("book lock unreadable", "LockUnreadable") in seen
    assert ("book passkey state unreadable", "RuntimeError") in seen
