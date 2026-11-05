# src/jarvis/health/probes.py
"""One probe per integration (R4 D5). No LLM reasoning is on this path: the brain probe only asks
the vendor whether it answers (one output token at most; the provider port has no free ping), and
in `brain_mode == "none"` it makes no call at all.

Every probe is read-only, has its own timeout, and answers `ok | degraded | down` with a one-line
reason written HERE (fixed words, never a vendor's or an exception's text). A probe may answer
None: "not set up for this owner", and is then left out of the report.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.health.models import ProbeOutcome, ProbeResult
from jarvis.home.store import HomeStore
from jarvis.integrations.google import (
    GoogleAPIError,
    GoogleConnector,
    GoogleNotConnected,
    GoogleServiceDisabled,
)
from jarvis.llm.base import (
    ChatMessage,
    LLMAuthError,
    LLMError,
    LLMProvider,
    LLMTransientError,
    LLMUnreachable,
    Role,
)
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs
from jarvis.web.ports import UsageReporter

log = get_logger(__name__)

PROBE_TIMEOUT_S = 5.0
SECONDS_PER_MINUTE = 60
GOOGLE_METADATA_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList/primary"
DOCS_PROBE_DOC = "health_last/_probe"
PING_PROMPT = "ping"

Check = Callable[[str], Awaitable[ProbeOutcome | None]]
Ping = Callable[[], Awaitable[object]]
Clock = Callable[[], float]


@dataclass(frozen=True)
class Probe:
    key: str
    label: str  # spoken: "the home bridge"
    check: Check
    timeout_s: float = PROBE_TIMEOUT_S


class TelegramLike(Protocol):
    async def call(self, method: str, payload: dict[str, Any] | None = None) -> Any: ...


class HomeStatusLike(Protocol):
    async def status(self, uid: str) -> Any: ...


def _ok(reason: str) -> ProbeOutcome:
    return ProbeOutcome("ok", reason)


def _down(reason: str) -> ProbeOutcome:
    return ProbeOutcome("down", reason)


def _slow(reason: str) -> ProbeOutcome:
    return ProbeOutcome("degraded", reason)


async def run_probe(probe: Probe, uid: str, *, clock: Clock) -> ProbeResult | None:
    """Run one probe; never raises. A hang or a failure is `down` with fixed words."""
    try:
        async with asyncio.timeout(probe.timeout_s):
            out = await probe.check(uid)
    except TimeoutError:
        out = _down("did not answer in time")
    except Exception as exc:  # noqa: BLE001 - a probe never fails the check
        log.warning("health probe failed", extra={"probe": probe.key, "error": type(exc).__name__})
        out = _down("the check itself failed")
    if out is None:
        return None
    return ProbeResult(
        key=probe.key, label=probe.label, status=out.status, reason=out.reason, at=clock()
    )


# ---- brains ------------------------------------------------------------------------------------
def provider_ping(provider: LLMProvider, model: str) -> Ping:
    """The cheapest call the provider port offers: one output token, no tools, no history."""

    async def ping() -> object:
        return await provider.complete(
            system=PING_PROMPT,
            messages=[ChatMessage(role=Role.USER, content=PING_PROMPT)],
            model=model,
            max_tokens=1,
            tools=None,
        )

    return ping


def brain_probe(ping: Ping, *, brain_mode: str) -> Probe:
    async def check(_uid: str) -> ProbeOutcome:
        if brain_mode == "none":
            return _ok("the AI is switched off (no-AI mode)")
        try:
            await ping()
        except LLMAuthError:
            return _down("the AI key was refused")
        except LLMUnreachable:
            return _down("the AI service could not be reached")
        except LLMTransientError:
            return _slow("the AI service is busy")
        except LLMError:
            return _slow("the AI service answered oddly")
        return _ok("the AI service answers")

    return Probe(key="brain", label="the AI brain", check=check)


# ---- Google ------------------------------------------------------------------------------------
def google_probe(google: GoogleConnector) -> Probe:
    async def check(uid: str) -> ProbeOutcome | None:
        st = await google.status(uid)
        if not st.get("connected"):
            return _slow("Google needs reconnecting") if st.get("needs_reconnect") else None
        try:
            await google.request(uid, "GET", GOOGLE_METADATA_URL, params={"fields": "id"})
        except GoogleNotConnected:
            return _slow("Google needs reconnecting")
        except GoogleServiceDisabled:
            return _slow("a Google service is switched off")
        except GoogleAPIError:
            return _down("Google refused the check")
        return _ok("Google answers")

    return Probe(key="google", label="Google", check=check)


# ---- Telegram ----------------------------------------------------------------------------------
def telegram_probe(client: TelegramLike) -> Probe:
    async def check(_uid: str) -> ProbeOutcome:
        await client.call("getMe")  # a failure is classified by run_probe
        return _ok("Telegram answers")

    return Probe(key="telegram", label="Telegram", check=check)


# ---- home bridge (R3 heartbeat) ----------------------------------------------------------------
def home_probe(store: HomeStatusLike | HomeStore, *, clock: Clock, offline_after_s: float) -> Probe:
    async def check(uid: str) -> ProbeOutcome | None:
        st = await store.status(uid)
        if st is None:
            return None
        seen = st.last_seen_at
        if seen is None:
            return _down("the home laptop has never reported")
        age = clock() - seen
        if st.state == "offline" or age > offline_after_s:
            minutes = max(0, math.floor(age / SECONDS_PER_MINUTE))
            return _down(f"no heartbeat for {minutes} minutes")
        return _ok("the home laptop reports in")

    return Probe(key="home", label="the home bridge", check=check)


# ---- Docs store, Redis, web search -------------------------------------------------------------
def docs_probe(docs: Docs, *, prefix: str) -> Probe:
    async def check(_uid: str) -> ProbeOutcome:
        await docs.get(f"{prefix}{DOCS_PROBE_DOC}")  # a read; the document need not exist
        return _ok("the document store answers")

    return Probe(key="docs", label="the document store", check=check)


def redis_probe(ping: Ping) -> Probe:
    async def check(_uid: str) -> ProbeOutcome:
        await ping()
        return _ok("Redis answers")

    return Probe(key="redis", label="Redis", check=check)


def web_probe(reporter: UsageReporter) -> Probe:
    async def check(_uid: str) -> ProbeOutcome:
        usage = await reporter.usage()  # the vendor's free usage report; no search is made
        if usage.exhausted:
            return _slow("web search credits are used up")
        return _ok("web search answers")

    return Probe(key="web", label="web search", check=check)


__all__ = [
    "GOOGLE_METADATA_URL",
    "PROBE_TIMEOUT_S",
    "Probe",
    "ProbeResult",
    "brain_probe",
    "docs_probe",
    "google_probe",
    "home_probe",
    "provider_ping",
    "redis_probe",
    "run_probe",
    "telegram_probe",
    "web_probe",
]
