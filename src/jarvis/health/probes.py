# src/jarvis/health/probes.py
"""One probe per integration (R4 D5). No model is called on this path, ever: the brain probe only
READS what `jarvis.llm`'s router already knows (how the last real completion ended, and whether
the laptop is covering for the cloud), which costs nothing. In `brain_mode == "none"` it reads
nothing at all.

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

from pydantic import ValidationError

from jarvis.health.models import LABELS, ProbeOutcome, ProbeResult
from jarvis.home.store import HomeStore
from jarvis.integrations.google import (
    GoogleAPIError,
    GoogleConnector,
    GoogleNotConnected,
    GoogleServiceDisabled,
)
from jarvis.llm.router import BrainHealth
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs
from jarvis.telegram.client import TelegramError
from jarvis.web.ports import UsageReporter

log = get_logger(__name__)

PROBE_TIMEOUT_S = 5.0
SECONDS_PER_MINUTE = 60
GOOGLE_METADATA_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList/primary"
DOCS_PROBE_DOC = "health_last/_probe"
CHECK_FAILED = "the check itself failed"

Check = Callable[[str], Awaitable[ProbeOutcome | None]]
BrainReader = Callable[[], BrainHealth]
Ping = Callable[[], Awaitable[object]]
Clock = Callable[[], float]
Configured = Callable[[str], Awaitable[bool]]


@dataclass(frozen=True)
class Probe:
    key: str
    label: str  # spoken: "the home bridge"
    check: Check
    timeout_s: float = PROBE_TIMEOUT_S


class TelegramLike(Protocol):
    async def call(self, method: str, payload: dict[str, Any] | None = None) -> object: ...


class HomeStatusLike(Protocol):
    async def status(self, uid: str) -> Any: ...


def _ok(reason: str) -> ProbeOutcome:
    return ProbeOutcome("ok", reason)


def _down(reason: str) -> ProbeOutcome:
    return ProbeOutcome("down", reason)


def _slow(reason: str) -> ProbeOutcome:
    return ProbeOutcome("degraded", reason)


def _result(probe: Probe, out: ProbeOutcome, clock: Clock) -> ProbeResult:
    return ProbeResult(
        key=probe.key, label=probe.label, status=out.status, reason=out.reason, at=clock()
    )


def crashed_result(probe: Probe, *, clock: Clock) -> ProbeResult:
    """A probe task that died outside its guard: `down`, fixed words."""
    return _result(probe, _down(CHECK_FAILED), clock)


async def run_probe(probe: Probe, uid: str, *, clock: Clock) -> ProbeResult | None:
    """Run one probe; never raises. A hang, a failure or a malformed answer is `down` with fixed
    words, so one bad probe can never take the whole check with it."""
    try:
        async with asyncio.timeout(probe.timeout_s):
            out = await probe.check(uid)
        if out is None:
            return None
        if not isinstance(out, ProbeOutcome):
            raise TypeError("probe answered with the wrong type")
        return _result(probe, out, clock)
    except TimeoutError:
        return _result(probe, _down("did not answer in time"), clock)
    except (ValidationError, AttributeError, TypeError) as exc:
        log.warning(
            "health probe malformed", extra={"probe": probe.key, "error": type(exc).__name__}
        )
        return _result(probe, _down(CHECK_FAILED), clock)
    except Exception as exc:  # noqa: BLE001 - a probe never fails the check
        log.warning("health probe failed", extra={"probe": probe.key, "error": type(exc).__name__})
        return _result(probe, _down(CHECK_FAILED), clock)


# ---- brain (free: reads the router's own record; never a model call) ----------------------------
_BRAIN_REASONS = {
    "refused": ("down", "the AI key was refused"),
    "busy": ("degraded", "the AI service is busy"),
    "odd": ("degraded", "the AI service answered oddly"),
    "unknown": ("ok", "no AI call has failed since JARVIS started"),
    "ok": ("ok", "the last AI call worked"),
}


def brain_probe(read: BrainReader, brain_mode: Callable[[str], Awaitable[str]]) -> Probe:
    """`read` is `ModelRouter.health` of the brain in use. Nothing is sent to any model.
    `brain_mode` is the async persisted reader (`BrainMode.load`), awaited per owner (I2 F1)."""

    async def check(uid: str) -> ProbeOutcome:
        if await brain_mode(uid) == "none":
            return _ok("the AI is switched off (no-AI mode)")
        seen = read()
        if seen.state == "unreachable":
            if seen.on_laptop:
                return _slow("the cloud AI is down; the laptop is answering")
            return _down("the AI service could not be reached")
        status, reason = _BRAIN_REASONS[seen.state]
        return ProbeOutcome(status, reason)  # type: ignore[arg-type]

    return Probe(key="brain", label=LABELS["brain"], check=check)


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

    return Probe(key="google", label=LABELS["google"], check=check)


# ---- Telegram (R5.1 D4) ------------------------------------------------------------------------
TOKEN_REFUSED = "the bot token was refused"
TELEGRAM_UNREACHABLE = "Telegram could not be reached"
TELEGRAM_REFUSED = "Telegram refused the check"
_REFUSED_TOKEN_REASONS = frozenset({"HTTP 401", "HTTP 404"})  # Bot API: bad / revoked token
_UNREACHABLE_REASON = "could not reach Telegram"  # TelegramClient: network or httpx timeout
TELEGRAM_SLACK_S = 0.5  # the probe's own timeout answers "could not be reached", not run_probe's


def _telegram_failure(exc: TelegramError) -> ProbeOutcome:
    """Our own words from `TelegramError.reason` (itself fixed text from the client)."""
    if exc.reason in _REFUSED_TOKEN_REASONS:
        return _down(TOKEN_REFUSED)
    if exc.reason == _UNREACHABLE_REASON:
        return _down(TELEGRAM_UNREACHABLE)
    return _down(TELEGRAM_REFUSED)


def telegram_probe(
    client: TelegramLike,
    *,
    configured: Configured | None = None,
    timeout_s: float = PROBE_TIMEOUT_S,
) -> Probe:
    """`configured(uid)`: the owner has a paired Telegram chat (the bot token's presence is the
    wiring's: no token, no probe). Not paired -> None (left out of the report: "not set up", never
    "the check itself failed"). None keeps the R4 behaviour (every owner is checked)."""
    slack = TELEGRAM_SLACK_S if timeout_s > 2 * TELEGRAM_SLACK_S else timeout_s / 2
    inner_s = timeout_s - slack

    async def check(uid: str) -> ProbeOutcome | None:
        if configured is not None and not await configured(uid):
            return None
        try:
            async with asyncio.timeout(inner_s):
                await client.call("getMe")
        except TimeoutError:
            return _down(TELEGRAM_UNREACHABLE)
        except TelegramError as exc:
            return _telegram_failure(exc)
        return _ok("Telegram answers")

    return Probe(key="telegram", label=LABELS["telegram"], check=check, timeout_s=timeout_s)


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

    return Probe(key="home", label=LABELS["home"], check=check)


# ---- Docs store, Redis, web search -------------------------------------------------------------
def docs_probe(docs: Docs, *, prefix: str) -> Probe:
    async def check(_uid: str) -> ProbeOutcome:
        await docs.get(f"{prefix}{DOCS_PROBE_DOC}")  # a read; the document need not exist
        return _ok("the document store answers")

    return Probe(key="docs", label=LABELS["docs"], check=check)


def redis_probe(ping: Ping) -> Probe:
    async def check(_uid: str) -> ProbeOutcome:
        await ping()
        return _ok("Redis answers")

    return Probe(key="redis", label=LABELS["redis"], check=check)


def web_probe(reporter: UsageReporter) -> Probe:
    async def check(_uid: str) -> ProbeOutcome:
        usage = await reporter.usage()  # the vendor's free usage report; no search is made
        if usage.exhausted:
            return _slow("web search credits are used up")
        return _ok("web search answers")

    return Probe(key="web", label=LABELS["web"], check=check)


__all__ = [
    "GOOGLE_METADATA_URL",
    "PROBE_TIMEOUT_S",
    "Probe",
    "ProbeResult",
    "brain_probe",
    "crashed_result",
    "docs_probe",
    "google_probe",
    "home_probe",
    "redis_probe",
    "run_probe",
    "telegram_probe",
    "web_probe",
]
