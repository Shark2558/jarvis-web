# tests/test_body_limits.py — slice 9 review item 15: every request body is size-capped app-wide
# (JSON bodies used to be parsed in full, before auth, with no cap). Content-Length over the cap →
# 413 too_large before anything is read; a chunked body is cut off at the same size. The tighter
# per-route caps (transcribe 2,000,000 bytes, memory import 512 KB) keep working, and both routes
# share one capped-read helper (review item 12).
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from voice_fakes import FakeSTT, FakeTokens, FakeTTS

from jarvis.api import create_app
from jarvis.api.body import MAX_BODY_BYTES, read_capped
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.recall.models import IMPORT_MAX_BYTES
from jarvis.voice.service import VoiceEngines

JSON = {"Content-Type": "application/json"}


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    engines = VoiceEngines(tts=FakeTTS(), stt=FakeSTT(), tokens=FakeTokens())
    app = create_app(
        settings, provider=MockProvider(), store=InMemorySessionStore(), voice_engines=engines
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


def test_the_app_wide_cap_sits_just_above_the_largest_route_cap() -> None:
    assert 2_000_000 < MAX_BODY_BYTES <= 2_100_000


async def _never() -> AsyncIterator[bytes]:
    raise AssertionError("the body must not be read")
    yield b""  # pragma: no cover


@pytest.mark.parametrize(
    "path", ["/v1/voice/speak", "/v1/voice/settings", "/v1/chat", "/v1/usage/budget"]
)
async def test_an_oversize_content_length_is_refused_before_reading(
    client: AsyncClient, path: str
) -> None:
    headers = {**JSON, "Content-Length": str(MAX_BODY_BYTES + 1)}
    method = "PUT" if path.endswith(("settings", "budget")) else "POST"
    r = await client.request(method, path, content=_never(), headers=headers)
    assert r.status_code == 413 and r.json()["error"] == "too_large", r.text
    assert "x-trace-id" in r.headers


async def test_an_oversize_chunked_json_body_is_cut_off(client: AsyncClient) -> None:
    sent = 0

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal sent
        yield b'{"text": "'
        for _ in range(30):
            sent += 100_000
            yield b"a" * 100_000
        yield b'"}'

    r = await client.post("/v1/voice/speak", content=chunks(), headers=JSON)
    assert r.status_code == 413 and r.json()["error"] == "too_large", r.text


async def test_a_normal_json_body_without_content_length_still_works(client: AsyncClient) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b'{"text": "Hello '
        yield b'there."}'

    r = await client.post("/v1/voice/speak", content=chunks(), headers=JSON)
    assert r.status_code == 200, r.text


async def test_the_tighter_route_caps_still_apply(client: AsyncClient) -> None:
    # transcribe: over its own 2,000,000 bytes but under the app-wide cap → its own 413
    r = await client.post(
        "/v1/voice/transcribe",
        content=_never(),
        headers={"Content-Type": "audio/wav", "Content-Length": "2000001"},
    )
    assert r.status_code == 413 and "about a minute" in r.json()["detail"]

    # memory import: 512 KB, chunked
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(IMPORT_MAX_BYTES // 100_000 + 2):
            yield b" " * 100_000

    r = await client.post("/v1/memory/import", content=chunks(), headers=JSON)
    assert r.status_code == 413 and r.json()["error"] == "too_large"


class _Req:
    """Just enough of a Starlette Request for read_capped."""

    def __init__(self, parts: list[bytes], length: str | None = None) -> None:
        self.headers = {"content-length": length} if length is not None else {}
        self._parts = parts

    async def stream(self) -> AsyncIterator[bytes]:
        for p in self._parts:
            yield p


class Big(Exception):
    pass


async def test_read_capped_is_the_one_shared_helper() -> None:
    assert await read_capped(_Req([b"ab", b"cd"]), 4, too_large=Big) == b"abcd"  # type: ignore[arg-type]
    with pytest.raises(Big):
        await read_capped(_Req([b"ab", b"cde"]), 4, too_large=Big)  # type: ignore[arg-type]
    with pytest.raises(Big):
        await read_capped(_Req([], length="5"), 4, too_large=Big)  # type: ignore[arg-type]
    import jarvis.api.memory as memory_api
    import jarvis.api.voice as voice_api

    assert not hasattr(memory_api, "_capped_body")
    assert voice_api.read_capped is read_capped
