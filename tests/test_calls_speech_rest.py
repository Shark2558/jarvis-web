# tests/test_calls_speech_rest.py — R18 B: the speech adapters' one REST call: a total deadline,
# retries with backoff only where the vendor surely did not process the request, and the error
# mapping (401/403 → auth, 400/413/415/422 → rejected, 429 → busy, 5xx → upstream_error).
from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from jarvis.calls.speech.errors import OptionUnavailable, SpeechBusy, SpeechRejected
from jarvis.calls.speech.rest import RetryPolicy, send

URL = "https://speech.example.test/v1/recognize"


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, s: float) -> None:
        self.delays.append(s)


def client(
    answers: list[Callable[[httpx.Request], httpx.Response]],
) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return answers[min(len(seen), len(answers)) - 1](req)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


def ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


def status(code: int, headers: dict[str, str] | None = None) -> Callable[..., httpx.Response]:
    return lambda _: httpx.Response(code, headers=headers, json={"error": "vendor words"})


def raise_(exc: Exception) -> Callable[..., httpx.Response]:
    def f(_: httpx.Request) -> httpx.Response:
        raise exc

    return f


POLICY = RetryPolicy(attempts=3, base_s=0.2, max_s=1.0, deadline_s=5.0)


async def test_a_clean_answer_comes_back_with_the_request_as_sent() -> None:
    http, seen = client([ok])
    sleeps = Sleeps()
    r = await send(
        http, "POST", URL, option="azure", headers={"X-Key": "k"}, content=b"abc",
        policy=POLICY, sleep=sleeps,
    )  # fmt: skip
    assert r.json() == {"ok": True}
    assert seen[0].headers["X-Key"] == "k" and seen[0].content == b"abc"
    assert sleeps.delays == []


@pytest.mark.parametrize("first", [status(503), status(502), status(500), status(429)])
async def test_throttles_and_server_errors_are_retried_with_backoff(
    first: Callable[..., httpx.Response],
) -> None:
    http, seen = client([first, first, ok])
    sleeps = Sleeps()
    r = await send(http, "GET", URL, option="sarvam", policy=POLICY, sleep=sleeps)
    assert r.status_code == 200 and len(seen) == 3
    assert len(sleeps.delays) == 2
    assert 0.1 <= sleeps.delays[0] <= 0.2 and 0.2 <= sleeps.delays[1] <= 0.4  # doubling, jitter


async def test_a_connection_that_never_opened_is_retried() -> None:
    http, seen = client([raise_(httpx.ConnectError("no route")), ok])
    r = await send(http, "GET", URL, option="bhashini", policy=POLICY, sleep=Sleeps())
    assert r.status_code == 200 and len(seen) == 2


async def test_retry_after_is_honoured_up_to_the_cap() -> None:
    http, _ = client([status(429, {"Retry-After": "30"}), ok])
    sleeps = Sleeps()
    await send(http, "GET", URL, option="azure", policy=POLICY, sleep=sleeps)
    assert sleeps.delays == [1.0]


async def test_a_request_that_may_have_been_processed_is_not_retried() -> None:
    http, seen = client([raise_(httpx.ReadTimeout("slow")), ok])
    with pytest.raises(OptionUnavailable) as e:
        await send(http, "POST", URL, option="sarvam", policy=POLICY, sleep=Sleeps())
    assert e.value.reason == "timeout" and e.value.maybe_billed
    assert len(seen) == 1


async def test_a_broken_answer_after_sending_is_not_retried() -> None:
    http, seen = client([raise_(httpx.RemoteProtocolError("cut")), ok])
    with pytest.raises(OptionUnavailable) as e:
        await send(http, "POST", URL, option="sarvam", policy=POLICY, sleep=Sleeps())
    assert e.value.reason == "upstream_error" and e.value.maybe_billed and len(seen) == 1


async def test_the_last_failure_is_raised_after_the_attempts() -> None:
    http, seen = client([status(503)])
    with pytest.raises(OptionUnavailable) as e:
        await send(http, "GET", URL, option="azure", policy=POLICY, sleep=Sleeps())
    assert e.value.reason == "upstream_error" and not e.value.maybe_billed and len(seen) == 3

    http, _ = client([status(429)])
    with pytest.raises(SpeechBusy):
        await send(http, "GET", URL, option="azure", policy=POLICY, sleep=Sleeps())


@pytest.mark.parametrize(
    ("code", "kind", "reason"),
    [
        (401, OptionUnavailable, "auth"),
        (403, OptionUnavailable, "auth"),
        (400, SpeechRejected, None),
        (404, SpeechRejected, None),
        (413, SpeechRejected, None),
        (415, SpeechRejected, None),
        (422, SpeechRejected, None),
    ],
)
async def test_client_errors_are_mapped_and_never_retried(
    code: int, kind: type[Exception], reason: str | None
) -> None:
    http, seen = client([status(code)])
    with pytest.raises(kind) as e:
        await send(http, "POST", URL, option="google", policy=POLICY, sleep=Sleeps())
    assert len(seen) == 1
    assert "vendor words" not in str(e.value)
    if reason is not None:
        assert getattr(e.value, "reason", None) == reason


async def test_the_total_deadline_covers_every_attempt() -> None:
    import asyncio

    async def real_sleep(s: float) -> None:
        await asyncio.sleep(s)

    async def slow(req: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(503)

    http = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    tight = RetryPolicy(attempts=10, base_s=0.05, max_s=0.05, deadline_s=0.3)
    with pytest.raises(OptionUnavailable) as e:
        await send(http, "GET", URL, option="azure", policy=tight, sleep=real_sleep)
    assert e.value.reason == "timeout"
