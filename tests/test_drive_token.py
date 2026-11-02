# tests/test_drive_token.py — slice 12 D1: JARVIS's own Drive token from the Cloud Run metadata
# server (`?scopes=` is honoured on Cloud Run — google-auth compute_engine.Credentials docstring),
# cached until 60 s before expiry, one refresh in flight, an overall deadline; no network here.
from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest
from drive_fakes import TOKEN_URL, FakeMetadata

from jarvis.drive.ports import DRIVE_SCOPE, DriveUnavailable
from jarvis.drive.token import MetadataTokens


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _tokens(meta: FakeMetadata, clock: Clock | None = None, **kw: object) -> MetadataTokens:
    return MetadataTokens(http=meta.client(), clock=clock or Clock(), **kw)  # type: ignore[arg-type]


async def test_asks_the_metadata_server_for_a_drive_readonly_token() -> None:
    meta = FakeMetadata()
    tok = await _tokens(meta).token()
    assert tok == meta.token
    (req,) = meta.requests
    assert str(req.url).split("?")[0] == TOKEN_URL
    assert req.headers["metadata-flavor"] == "Google"
    assert parse_qs(req.url.query.decode())["scopes"] == [DRIVE_SCOPE]


async def test_caches_until_sixty_seconds_before_expiry() -> None:
    meta, clock = FakeMetadata(expires_in=300), Clock()
    src = _tokens(meta, clock)
    await src.token()
    clock.now += 239
    await src.token()
    assert len(meta.requests) == 1
    clock.now += 2  # 241 s: inside the last 60 s
    await src.token()
    assert len(meta.requests) == 2


async def test_invalidate_forces_a_fresh_token() -> None:
    meta = FakeMetadata()
    src = _tokens(meta)
    await src.token()
    src.invalidate()
    await src.token()
    assert len(meta.requests) == 2


async def test_one_refresh_in_flight_for_concurrent_callers() -> None:
    gate = asyncio.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await gate.wait()
        return httpx.Response(200, json={"access_token": "t1", "expires_in": 3599})

    src = MetadataTokens(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    waiters = [asyncio.create_task(src.token()) for _ in range(5)]
    await asyncio.sleep(0.01)
    gate.set()
    assert await asyncio.gather(*waiters) == ["t1"] * 5
    assert calls == 1


async def test_overall_deadline_says_unavailable() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={"access_token": "t", "expires_in": 3599})

    src = MetadataTokens(
        http=httpx.AsyncClient(transport=httpx.MockTransport(slow)), deadline_s=0.05
    )
    with pytest.raises(DriveUnavailable):
        await src.token()


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(404, text="no such account"),
        httpx.Response(200, json={"access_token": "", "expires_in": 3599}),
        httpx.Response(200, json={"access_token": "a b", "expires_in": 3599}),
        httpx.Response(200, json={"access_token": "t", "expires_in": "3599"}),
        httpx.Response(200, json={"access_token": "t", "expires_in": True}),
        httpx.Response(200, json={"access_token": "t", "expires_in": 0}),
        httpx.Response(200, json=["t"]),
        httpx.Response(200, content=b"not json"),
        httpx.Response(302, headers={"location": "http://evil.example/"}),
        httpx.Response(200, content=b"{" + b" " * 70_000 + b"}"),
    ],
)
async def test_odd_answers_are_refused_without_vendor_text(answer: httpx.Response) -> None:
    meta = FakeMetadata()
    meta.answers.append(answer)
    with pytest.raises(DriveUnavailable) as e:
        await _tokens(meta).token()
    assert "evil" not in str(e.value) and "no such account" not in str(e.value)


async def test_off_cloud_run_is_not_configured_and_not_retried_at_once() -> None:
    calls = 0

    def unreachable(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("name resolution failed")

    clock = Clock()
    src = MetadataTokens(
        http=httpx.AsyncClient(transport=httpx.MockTransport(unreachable)), clock=clock
    )
    for _ in range(3):
        with pytest.raises(DriveUnavailable) as e:
            await src.token()
        assert "Cloud Run" in str(e.value)
    assert calls == 1
    clock.now += 61
    with pytest.raises(DriveUnavailable):
        await src.token()
    assert calls == 2


async def test_service_email_comes_from_the_metadata_server_once() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.headers["metadata-flavor"] == "Google"
        return httpx.Response(200, text="jarvis-run@proj.iam.gserviceaccount.com")

    src = MetadataTokens(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await src.email() == "jarvis-run@proj.iam.gserviceaccount.com"
    assert await src.email() == "jarvis-run@proj.iam.gserviceaccount.com"
    assert seen == ["/computeMetadata/v1/instance/service-accounts/default/email"]


async def test_a_bad_email_answer_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<script>x</script>")

    src = MetadataTokens(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(DriveUnavailable):
        await src.email()


async def test_the_token_never_appears_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    meta = FakeMetadata(token="ya29.SECRET-TOKEN")
    src = _tokens(meta)
    caplog.set_level("DEBUG")
    await src.token()
    assert "SECRET-TOKEN" not in caplog.text
