# src/jarvis/calls/speech/rest.py
"""The speech adapters' one REST call (R18 B; Layer 6): httpx, a deadline, retries, plain errors.

One total deadline covers every attempt and every pause. Inside it, a request is retried with
exponential backoff and jitter (base · 2^n · [0.5, 1], capped; a vendor's Retry-After is honoured
up to the cap) ONLY where the vendor surely did not process it, so nothing is billed twice:

    retried     the connection never opened (connect error / timeout, pool timeout, proxy), a
                429, or a 500 / 502 / 503 / 504 answer
    not retried a timeout or a broken connection after the request was sent (`maybe_billed`),
                401 / 403 (the key), 400 / 404 / 413 / 415 / 422 (this audio or text)

    401 / 403           OptionUnavailable("auth")
    4xx (other)         SpeechRejected
    429 (last attempt)  SpeechBusy(retry_after_s)
    5xx (last attempt)  OptionUnavailable("upstream_error")
    deadline            OptionUnavailable("timeout", maybe_billed=<a request was in flight>)

The vendor's own error text never leaves this module, and neither the audio, the text nor a
transcript is ever logged: the option, the API name, the status and the attempt only. Secrets
travel in headers the caller passes and are never logged either.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from jarvis.calls.speech.errors import OptionUnavailable, SpeechBusy, SpeechRejected
from jarvis.logging import get_logger

log = get_logger(__name__)

HTTP_TIMEOUT = httpx.Timeout(8.0, connect=3.0)  # per phase, inside the deadline
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
AUTH_STATUSES = frozenset({401, 403})
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ProxyError)
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_s: float = 0.25
    max_s: float = 2.0
    deadline_s: float = 10.0


IN_CALL = RetryPolicy(attempts=2, base_s=0.15, max_s=0.5, deadline_s=6.0)  # a turn is waiting
BATCH = RetryPolicy(attempts=4, base_s=0.5, max_s=4.0, deadline_s=45.0)  # the language check


def _retry_after(r: httpx.Response) -> float | None:
    raw = r.headers.get("Retry-After", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _pause(
    policy: RetryPolicy, attempt: int, hint: float | None, rng: Callable[[], float]
) -> float:
    if hint is not None:
        return min(hint, policy.max_s)
    return min(policy.base_s * (2.0**attempt) * (0.5 + 0.5 * rng()), policy.max_s)


def _raise_for(r: httpx.Response, option: str, api: str) -> None:
    code = r.status_code
    if code < 400:
        return
    log.warning("speech api error", extra={"option": option, "api": api, "status": code})
    if code in AUTH_STATUSES:
        raise OptionUnavailable(option, "auth")
    if code == 429:
        raise SpeechBusy(option, _retry_after(r) or 5.0)
    if code < 500:
        raise SpeechRejected(option)
    raise OptionUnavailable(option, "upstream_error")


async def _attempt(
    http: httpx.AsyncClient, method: str, url: str, kw: Mapping[str, Any], option: str, api: str
) -> httpx.Response | None:
    """One try: the answer, or None when the connection never opened (safe to retry)."""
    try:
        return await http.request(method, url, timeout=HTTP_TIMEOUT, **kw)
    except _NOT_SENT as exc:
        log.warning(
            "speech api unreachable",
            extra={"option": option, "api": api, "why": type(exc).__name__},
        )
        return None
    except httpx.TimeoutException:
        log.warning("speech api timed out", extra={"option": option, "api": api})
        raise OptionUnavailable(option, "timeout", maybe_billed=True) from None
    except httpx.HTTPError as exc:
        log.warning(
            "speech api broke off", extra={"option": option, "api": api, "why": type(exc).__name__}
        )
        raise OptionUnavailable(option, "upstream_error", maybe_billed=True) from None


async def _loop(
    http: httpx.AsyncClient,
    method: str,
    url: str,
    kw: Mapping[str, Any],
    option: str,
    api: str,
    policy: RetryPolicy,
    sleep: Sleep,
    rng: Callable[[], float],
    in_flight: list[bool],
) -> httpx.Response:
    for attempt in range(max(1, policy.attempts)):
        last = attempt == max(1, policy.attempts) - 1
        in_flight[0] = True
        r = await _attempt(http, method, url, kw, option, api)
        in_flight[0] = False
        if r is not None and (r.status_code not in RETRY_STATUSES or last):
            _raise_for(r, option, api)
            return r
        if r is None and last:
            raise OptionUnavailable(option, "upstream_error")
        hint = _retry_after(r) if r is not None else None
        await sleep(_pause(policy, attempt, hint, rng))
    raise AssertionError("unreachable")


async def send(
    http: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    option: str,
    api: str = "speech",
    policy: RetryPolicy = IN_CALL,
    sleep: Sleep = asyncio.sleep,
    rng: Callable[[], float] = random.random,
    headers: Mapping[str, str] | None = None,
    json: Any = None,
    content: bytes | None = None,
    data: Mapping[str, str] | None = None,
    files: Mapping[str, tuple[str, bytes, str]] | None = None,
    params: Mapping[str, str] | None = None,
) -> httpx.Response:
    """The vendor's 2xx answer, or one of the speech errors (see the module docstring)."""
    kw: dict[str, Any] = {"headers": dict(headers or {})}
    for key, value in (
        ("json", json),
        ("content", content),
        ("data", data),
        ("files", files),
        ("params", params),
    ):
        if value is not None:
            kw[key] = value
    in_flight = [False]
    try:
        async with asyncio.timeout(policy.deadline_s):
            return await _loop(http, method, url, kw, option, api, policy, sleep, rng, in_flight)
    except TimeoutError:
        log.warning("speech api: deadline passed", extra={"option": option, "api": api})
        raise OptionUnavailable(option, "timeout", maybe_billed=in_flight[0]) from None


def json_body(r: httpx.Response, option: str) -> dict[str, Any]:
    """A 2xx answer's JSON object; OptionUnavailable("bad_answer", billed) otherwise."""
    try:
        body = r.json()
    except ValueError:
        raise OptionUnavailable(option, "bad_answer", maybe_billed=True) from None
    if not isinstance(body, dict):
        raise OptionUnavailable(option, "bad_answer", maybe_billed=True)
    return body


__all__ = [
    "BATCH",
    "HTTP_TIMEOUT",
    "IN_CALL",
    "RetryPolicy",
    "Sleep",
    "json_body",
    "send",
]
