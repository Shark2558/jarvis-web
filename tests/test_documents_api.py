# tests/test_documents_api.py — slice 10 E: POST /v1/attachments (raw body + X-Jarvis-Filename,
# its own 10 MB cap while the app-wide 2.1 MB cap stays everywhere else, owner-only, CSRF on cookie
# writes, per-owner rate limit, type by name AND bytes, plain errors), DELETE of a waiting file,
# and the whole path: attach → chat → transcript → delete the conversation → files gone.
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import pytest
from doc_fakes import encrypt_pdf, make_docx, make_pdf
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.body import MAX_BODY_BYTES
from jarvis.api.documents import UPLOADS_PER_MINUTE
from jarvis.api.scheduler_auth import TICK_PATH
from jarvis.config import AuthMode, SessionBackend, Settings
from jarvis.documents.models import MAX_FILE_BYTES
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

PATH = "/v1/attachments"
OWNER = "akash@example.com"
CSRF = {"X-Requested-With": "JARVIS"}


def named(name: str, **extra: str) -> dict[str, str]:
    return {"X-Jarvis-Filename": quote(name), "Content-Type": "application/octet-stream", **extra}


@pytest.fixture
async def client(settings: Settings, provider: MockProvider) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, provider=provider, store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


async def _never() -> AsyncIterator[bytes]:
    raise AssertionError("the body must not be read")
    yield b""  # pragma: no cover


async def upload(c: AsyncClient, name: str, data: bytes) -> Any:
    return await c.post(PATH, content=data, headers=named(name))


# ---- upload --------------------------------------------------------------------------------------


async def test_upload_returns_201_and_the_ref(client: AsyncClient) -> None:
    r = await upload(client, "Board memo.docx", make_docx(["Budget is 4 crore."]))
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"id", "name", "kind", "size", "pages", "words", "chars", "truncated"}
    assert body["name"] == "Board memo.docx" and body["kind"] == "docx" and body["words"] == 4


async def test_unicode_names_survive_percent_encoding(client: AsyncClient) -> None:
    r = await upload(client, "കരാർ notes.txt", "ശമ്പളം".encode())
    assert r.status_code == 201 and r.json()["name"] == "കരാർ notes.txt"


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({}, "no_name"),
        ({"X-Jarvis-Filename": "%FF%FE.txt"}, "no_name"),
        ({"X-Jarvis-Filename": "a" * 2_000 + ".txt"}, "no_name"),
        ({"X-Jarvis-Filename": "virus.exe"}, "unsupported"),
    ],
)
async def test_name_problems_are_refused_before_reading_the_body(
    client: AsyncClient, headers: dict[str, str], code: str
) -> None:
    r = await client.post(PATH, content=_never(), headers=headers)
    assert r.json()["error"] == code and r.status_code in (415, 422), r.text
    assert isinstance(r.json()["detail"], str)


async def test_over_10_mb_by_content_length_is_refused_before_reading(client: AsyncClient) -> None:
    headers = named("big.pdf", **{"Content-Length": str(MAX_FILE_BYTES + 1)})
    r = await client.post(PATH, content=_never(), headers=headers)
    assert r.status_code == 413 and r.json()["error"] == "too_large" and "10 MB" in r.text


async def test_far_over_the_cap_is_cut_by_the_middleware(client: AsyncClient) -> None:
    headers = named("big.pdf", **{"Content-Length": str(50 * 1024 * 1024)})
    r = await client.post(PATH, content=_never(), headers=headers)
    assert r.status_code == 413 and r.json()["error"] == "too_large"


async def test_a_chunked_body_over_10_mb_is_cut_off(client: AsyncClient) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(11):
            yield b"a" * (1024 * 1024)

    r = await client.post(PATH, content=chunks(), headers=named("big.txt"))
    assert r.status_code == 413 and r.json()["error"] == "too_large"


async def test_this_route_takes_more_than_the_app_wide_cap_and_no_other_does(
    client: AsyncClient,
) -> None:
    big = b"word " * (3 * 1024 * 1024 // 5)  # 3 MB, over the app-wide 2.1 MB
    assert len(big) > MAX_BODY_BYTES
    r = await upload(client, "long.txt", big)
    assert r.status_code == 201, r.text
    assert r.json()["truncated"] is True  # 300,000 characters kept
    r = await client.post(
        "/v1/chat",
        content=_never(),
        headers={"Content-Type": "application/json", "Content-Length": str(len(big))},
    )
    assert r.status_code == 413


@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("locked.pdf", encrypt_pdf(make_pdf(["secret"])), 422, "encrypted"),
        ("scan.pdf", make_pdf(["", ""]), 422, "no_text"),
        ("fake.pdf", b"hello there", 415, "unsupported"),
        ("empty.txt", b"", 422, "empty"),
        ("broken.docx", b"PK\x03\x04" + b"\0" * 40, 422, "unreadable"),
    ],
)
async def test_plain_errors_for_files_that_cannot_be_read(
    client: AsyncClient, name: str, data: bytes, status: int, code: str
) -> None:
    r = await upload(client, name, data)
    assert r.status_code == status and r.json()["error"] == code, r.text
    assert r.json()["detail"] and "Traceback" not in r.text


async def test_uploads_are_rate_limited_per_owner(client: AsyncClient) -> None:
    for i in range(UPLOADS_PER_MINUTE):
        assert (await upload(client, f"{i}.txt", b"x")).status_code == 201
    r = await upload(client, "one-too-many.txt", b"x")
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1


async def test_discard_a_waiting_file(client: AsyncClient) -> None:
    aid = (await upload(client, "a.txt", b"hello")).json()["id"]
    assert (await client.delete(f"{PATH}/{aid}")).status_code == 204
    r = await client.delete(f"{PATH}/{aid}")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    r = await client.delete(f"{PATH}/..%2F..%2Fsessions")
    assert r.status_code == 404


async def test_an_upload_that_trickles_in_is_cut_off(client: AsyncClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Review LOW: the body read has an overall deadline (a slow sender can't hold the route)."""
    import jarvis.api.documents as mod

    monkeypatch.setattr(mod, "READ_TIMEOUT_S", 0.2)

    async def trickle() -> AsyncIterator[bytes]:
        yield b"first bytes "
        await asyncio.sleep(5)
        yield b"never"

    r = await client.post(PATH, content=trickle(), headers=named("slow.txt"))
    assert r.status_code == 408 and r.json()["error"] == "upload_timeout"
    assert "took too long" in r.json()["detail"]


# ---- auth ---------------------------------------------------------------------------------------


@pytest.fixture
async def gc(settings: Settings, provider: MockProvider) -> AsyncIterator[AsyncClient]:
    gs = settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
        }
    )
    app = create_app(gs, provider=provider, store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


async def test_upload_needs_the_owner_and_cookie_writes_need_the_csrf_header(
    gc: AsyncClient,
) -> None:
    r = await gc.post(PATH, content=b"hi", headers={**named("a.txt"), **CSRF})
    assert r.status_code == 401

    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": OWNER, "email_verified": True, "sub": OWNER}}

    gc.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await gc.get("/auth/callback?code=a&state=b")).status_code in (302, 307)
    r = await gc.post(PATH, content=b"hi", headers=named("a.txt"))
    assert r.status_code == 403 and r.json()["error"] == "csrf"
    r = await gc.post(PATH, content=b"hi", headers={**named("a.txt"), **CSRF})
    assert r.status_code == 201


# ---- end to end ----------------------------------------------------------------------------------


async def test_attach_chat_transcript_and_delete(
    client: AsyncClient, provider: MockProvider
) -> None:
    aid = (await upload(client, "Lease.pdf", make_pdf(["Rent is due on the 5th."]))).json()["id"]
    provider.script("On the 5th, Sir.")
    r = await client.post("/v1/chat", json={"message": "When is rent due?", "attachments": [aid]})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    view = (await client.get(f"/v1/sessions/{sid}")).json()
    owner = view["turns"][0]
    assert owner["content"] == "When is rent due?"
    assert [a["id"] for a in owner["attachments"]] == [aid]
    assert owner["attachments"][0]["name"] == "Lease.pdf"
    # sending it again is refused plainly: it belongs to that conversation now
    r = await client.post("/v1/chat", json={"message": "again", "attachments": [aid]})
    assert r.status_code == 422 and "no longer available" in r.json()["detail"]
    assert (await client.delete(f"/v1/sessions/{sid}")).status_code == 204
    store = client.app.state.documents.store  # type: ignore[attr-defined]
    assert await store.get(aid) is None


async def test_documents_switched_off_refuses_uploads_and_sending(
    client: AsyncClient, provider: MockProvider
) -> None:
    """Integration review (extra): with Documents on "Never" no file is taken in or sent, so the
    start of a file (the note's ≤ 2,000 characters) never reaches the model."""
    waiting = (await upload(client, "Lease.pdf", make_pdf(["Rent is due on the 5th."]))).json()
    r = await client.put("/v1/permissions", json={"groups": {"documents": "deny"}})
    assert r.status_code == 200, r.text
    r = await client.post(PATH, content=_never(), headers=named("Other.txt"))
    assert r.status_code == 403 and r.json()["error"] == "documents_off"
    assert r.json()["detail"] == "Documents are switched off in Permissions."
    calls = len(provider.calls)
    r = await client.post("/v1/chat", json={"message": "read it", "attachments": [waiting["id"]]})
    assert r.status_code == 422 and "switched off in Permissions" in r.json()["detail"]
    assert len(provider.calls) == calls  # nothing reached the model
    assert (await client.get("/v1/sessions")).json() == []  # no empty conversation left
    await client.put("/v1/permissions", json={"groups": {"documents": "allow"}})
    provider.script("On the 5th, Sir.")
    r = await client.post("/v1/chat", json={"message": "read it", "attachments": [waiting["id"]]})
    assert r.status_code == 200, r.text  # switched back on: the waiting file goes


async def test_more_than_three_files_in_one_message_is_refused(client: AsyncClient) -> None:
    ids = [(await upload(client, f"{i}.txt", b"note")).json()["id"] for i in range(4)]
    r = await client.post("/v1/chat", json={"message": "read all", "attachments": ids})
    assert r.status_code == 422 and "3 files" in r.json()["detail"]
    assert (await client.get("/v1/sessions")).json() == []  # no empty conversation left


async def test_doc_tools_are_offered_to_the_model(
    client: AsyncClient, provider: MockProvider
) -> None:
    await client.post("/v1/chat", json={"message": "hello"})
    names = {t.name for t in provider.calls[-1].tools or []}
    assert {"doc_read", "doc_search"} <= names


async def test_the_scheduler_tick_sweeps_unsent_uploads(settings: Settings) -> None:
    """Review M3: stale unsent uploads go even when the owner never uploads or deletes again."""
    from test_scheduler_auth import KEY, SA, FakeJWKS, token, verifier

    s = settings.model_copy(
        update={
            "brief_scheduler_sa": SA,
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
            "session_backend": SessionBackend.FIRESTORE,  # the tick needs persistent storage
        }
    )
    app = create_app(
        s,
        provider=MockProvider(),
        store=InMemorySessionStore(),
        scheduler_verifier=verifier(FakeJWKS(KEY)),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            ran: list[bool] = []

            async def spy() -> bool:
                ran.append(True)
                return True

            app.state.documents.sweep_waiting = spy
            r = await c.post(TICK_PATH, headers={"Authorization": f"Bearer {token()}"})
            assert r.status_code == 200 and ran == [True]
