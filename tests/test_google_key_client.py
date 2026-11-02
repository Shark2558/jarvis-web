# tests/test_google_key_client.py — slice 12 D2: the one door for JARVIS's server-side Google API
# key. The key travels only in the X-Goog-Api-Key header (never a URL, a log line or an error), only
# to the four allow-listed Google hosts; redirects are not followed; the response is size-capped and
# must be a JSON object; Google's own words never surface; each failure says whether Google clearly
# did not charge for it (refund) and whether its quota is gone (latch).
from __future__ import annotations

import logging

import httpx
import pytest
from media_fakes import KEY, PLACES_URL, YT, FakeGoogleKeyAPIs
from pydantic import SecretStr

from jarvis.config import Settings
from jarvis.integrations.google_key import (
    MAX_RESPONSE_BYTES,
    GoogleKeyClient,
    KeyAPIError,
    build_google_key_client,
    google_key_configured,
)


def _client(fake: FakeGoogleKeyAPIs, key: str = KEY) -> GoogleKeyClient:
    return GoogleKeyClient(SecretStr(key), http=fake.client())


async def test_post_sends_the_key_and_field_mask_as_headers_never_in_the_url() -> None:
    fake = FakeGoogleKeyAPIs()
    c = _client(fake, KEY + "\n")  # Secret Manager values often end with a newline
    data = await c.post(PLACES_URL, {"textQuery": "cafe"}, field_mask="places.id")
    assert "places" in data
    req = fake.requests[0]
    assert req.headers["x-goog-api-key"] == KEY
    assert req.headers["x-goog-fieldmask"] == "places.id"
    assert KEY not in str(req.url) and "key=" not in str(req.url)


async def test_get_sends_params_and_the_key_header_only() -> None:
    fake = FakeGoogleKeyAPIs()
    await _client(fake).get(f"{YT}/search", {"part": "snippet", "q": "lofi"})
    req = fake.requests[0]
    assert req.url.params["q"] == "lofi" and "key" not in req.url.params
    assert req.headers["x-goog-api-key"] == KEY


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/v1/places:searchText",
        "http://places.googleapis.com/v1/places:searchText",
        "https://places.googleapis.com.evil.example/v1/x",
        "https://www.googleapis.com/drive/v3/files",  # a Google host, but not a key API
        "https://oauth2.googleapis.com/token",
    ],
)
async def test_the_key_goes_only_to_the_allow_listed_google_apis(url: str) -> None:
    fake = FakeGoogleKeyAPIs()
    with pytest.raises(ValueError):
        await _client(fake).get(url, {})
    assert fake.requests == []


async def test_a_redirect_is_never_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/steal"})

    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    c = GoogleKeyClient(
        SecretStr(KEY), http=httpx.AsyncClient(transport=httpx.MockTransport(recording))
    )
    with pytest.raises(KeyAPIError):
        await c.get(f"{YT}/search", {})
    assert len(seen) == 1


async def test_an_oversized_answer_is_refused() -> None:
    fake = FakeGoogleKeyAPIs()
    fake.raw = b'{"items": "' + b"x" * (MAX_RESPONSE_BYTES + 10) + b'"}'
    with pytest.raises(KeyAPIError) as exc:
        await _client(fake).get(f"{YT}/search", {})
    assert "too large" in str(exc.value)


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b'"text"', b"NaN"])
async def test_an_answer_that_is_not_a_json_object_is_unreadable(raw: bytes) -> None:
    fake = FakeGoogleKeyAPIs()
    fake.raw = raw
    with pytest.raises(KeyAPIError) as exc:
        await _client(fake).get(f"{YT}/search", {})
    assert "unreadable" in str(exc.value)


@pytest.mark.parametrize(
    ("status", "reason", "exhausted", "words"),
    [
        (400, "badRequest", False, "invalid"),
        (403, "API_KEY_INVALID", False, "key"),
        (403, "API_KEY_SERVICE_BLOCKED", False, "not switched on"),
        (403, "SERVICE_DISABLED", False, "not switched on"),
        (403, "accessNotConfigured", False, "not switched on"),
        (403, "quotaExceeded", True, "allowance"),
        (403, "dailyLimitExceeded", True, "allowance"),
        (429, "RATE_LIMIT_EXCEEDED", False, "busy"),
        (500, "backendError", False, "unavailable"),
        (503, "", False, "unavailable"),
    ],
)
async def test_errors_are_plain_words_with_a_latch_flag_and_never_a_refund(
    status: int, reason: str, exhausted: bool, words: str, caplog: pytest.LogCaptureFixture
) -> None:
    """YouTube counts even invalid requests against the quota, and Maps billing for an error
    answer is not documented: once a request reached Google it is never given back."""
    fake = FakeGoogleKeyAPIs()
    fake.status = status
    fake.body = {
        "error": {
            "code": status,
            "message": "VENDOR SECRET TEXT " + KEY,
            "errors": [{"reason": reason}],
            "details": [{"reason": reason}],
        }
    }
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(KeyAPIError) as exc:
            await _client(fake).get(f"{YT}/search", {})
    err = exc.value
    assert err.clear is False and err.exhausted is exhausted
    assert words in str(err).lower()
    assert "VENDOR" not in str(err) and KEY not in str(err)
    assert KEY not in caplog.text and "VENDOR" not in caplog.text


async def test_unreachable_is_a_clear_failure_only_when_nothing_was_sent() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    def drop(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    for handler, clear in ((refuse, True), (drop, False)):
        c = GoogleKeyClient(
            SecretStr(KEY), http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        with pytest.raises(KeyAPIError) as exc:
            await c.get(f"{YT}/search", {})
        assert exc.value.clear is clear
        assert KEY not in str(exc.value)


def test_settings_read_the_key_from_jarvis_google_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_GOOGLE_API_KEY", KEY)
    s = Settings(_env_file=None)
    assert s.google_api_key is not None and s.google_api_key.get_secret_value() == KEY
    assert KEY not in repr(s)
    assert google_key_configured(s)
    assert build_google_key_client(s) is not None


@pytest.mark.parametrize("value", [None, "", "   \n"])
def test_no_key_means_no_client(value: str | None) -> None:
    s = Settings(_env_file=None, google_api_key=SecretStr(value) if value is not None else None)
    assert not google_key_configured(s)
    assert build_google_key_client(s) is None
