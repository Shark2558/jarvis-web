# src/jarvis/vitals/own.py
"""JARVIS's own keys and connections on the Vitals board (R5.1 D2: "Vitals tracks itself").

One automatic item per thing JARVIS itself uses: the Claude and Gemini keys, the Google sign-in,
the Telegram bot, the web-search credits, the GitHub token and the home laptop link. Each is left
out when that thing is not set up at all. Reads are cheap and free: in-process state (the LLM
router's own record of its last call), stored records, the LAST stored systems-check report, and
the web vendor's free usage report (cached 10 minutes per process). No model call, no new vendor
call, no key value. Every reason here is fixed words; a source that fails or is slow makes its
item "unknown" (its error text never reaches the board). The integrator wires the sources
(`INTEGRATION-r51.md`) through the small Protocols below.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.vitals.auto import UNREADABLE, next_month_start
from jarvis.vitals.models import Group, Kind, Provider, Status

log = get_logger(__name__)

SOURCE_TIMEOUT_S = 3.0  # each source's deadline: a slow one is "unknown", never a slow board
WEB_CACHE_S = 600.0  # the vendor's usage report, at most once per 10 minutes per process
WEB_RETRY_S = 60.0  # after a failed report, wait this long before asking again
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60

LABELS: Mapping[str, str] = {
    "brain_claude": "Claude (paid AI) key",
    "brain_gemini": "Gemini (free AI) key",
    "google_link": "Google sign-in",
    "telegram_bot": "Telegram bot",
    "web_credits": "Web search credits",
    "github_token": "GitHub token",
    "home_link": "Home laptop link",
}
OWN_IDS = frozenset(LABELS)
# Watched and rung by the systems check or the home watchdog already: Vitals never rings for them.
QUIET_IDS = frozenset({"brain_claude", "brain_gemini", "google_link", "telegram_bot", "home_link"})
UNKNOWN_REASON = "can't be read now"
RUN_CHECK = "Run a systems check to test it."
NEXT_USE = "JARVIS sees its limits the next time it reads GitHub."
NO_EXPIRY = "This token doesn't expire."
BRAIN_STATES: Mapping[str, tuple[Status, str]] = {
    "refused": ("red", "was refused"),
    "busy": ("amber", "is busy right now"),
    "odd": ("amber", "answered oddly"),
    "unreachable": ("amber", "could not be reached"),
    "ok": ("ok", ""),
    "unknown": ("ok", ""),
}
BRAIN_NOTES = {
    "ok": "The last AI call worked.",
    "unknown": "No AI call has failed since JARVIS started.",
}
PROBE_STATES: Mapping[str, tuple[Status, str]] = {
    "ok": ("ok", ""),
    "degraded": ("amber", "is slow or limited"),
    "down": ("red", "is not answering"),
}


# ---- what the integrator hands in (structural: no import of the features themselves) ----------
class BrainHealthLike(Protocol):
    @property
    def state(self) -> str: ...

    @property
    def on_laptop(self) -> bool: ...


BrainReader = Callable[[], BrainHealthLike]  # `ModelRouter.health` of that brain: free, no call


class StatusReader(Protocol):  # GoogleConnector / GithubClient: {connected, needs_reconnect, ...}
    async def status(self, uid: str) -> Mapping[str, Any]: ...


class ProbeResultLike(Protocol):
    @property
    def key(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def at(self) -> float: ...


class HealthReportLike(Protocol):
    @property
    def results(self) -> Sequence[ProbeResultLike]: ...


class HealthReader(Protocol):  # HealthService.last: the LAST stored report, no new check
    async def last(self, uid: str) -> HealthReportLike | None: ...


class VendorUsageLike(Protocol):
    @property
    def used(self) -> int: ...

    @property
    def limit(self) -> int | None: ...

    @property
    def exhausted(self) -> bool: ...


class UsageReporterLike(Protocol):  # the web vendor's free usage report (no search is made)
    async def usage(self) -> VendorUsageLike: ...


class TokenMetaLike(Protocol):  # jarvis.integrations.github_meta.TokenMeta
    @property
    def expires_at(self) -> float | None: ...

    @property
    def rate_limit(self) -> int | None: ...

    @property
    def rate_used(self) -> int | None: ...

    @property
    def rate_reset(self) -> float | None: ...


class GithubLike(StatusReader, Protocol):
    async def token_meta(self, uid: str) -> TokenMetaLike | None: ...


class HomeStatusLike(Protocol):
    @property
    def state(self) -> str: ...

    @property
    def last_seen_at(self) -> float | None: ...


class HomeReader(Protocol):  # HomeStore.status
    async def status(self, uid: str) -> HomeStatusLike | None: ...


@dataclass(frozen=True)
class OwnSources:
    """Each None means "not wired": a configured key without its reader shows as unknown."""

    claude: BrainReader | None = None
    gemini: BrainReader | None = None
    google: StatusReader | None = None
    health: HealthReader | None = None
    web: UsageReporterLike | None = None
    github: GithubLike | None = None
    home: HomeReader | None = None


@dataclass(frozen=True)
class OwnItem:
    provider: Provider
    base: tuple[Status, str]  # the thing's own state + its fixed reason
    group: Group = "keys"


class CachedUsage:
    """The vendor's usage report, kept for `WEB_CACHE_S` (a failure for `WEB_RETRY_S`)."""

    def __init__(self, reporter: UsageReporterLike) -> None:
        self._reporter = reporter
        self._lock = asyncio.Lock()
        self._at = -math.inf
        self._value: VendorUsageLike | None = None

    async def get(self, now: float) -> VendorUsageLike:
        async with self._lock:
            fresh = now - self._at < (WEB_CACHE_S if self._value is not None else WEB_RETRY_S)
            if not fresh:
                self._at = now
                self._value = None
                self._value = await self._reporter.usage()
            if self._value is None:
                raise LookupError("usage report unavailable")
            return self._value


def _item(pid: str, base: tuple[Status, str], *, note: str = "", **kw: Any) -> OwnItem:
    kind: Kind = "quota" if pid == "web_credits" else "key"
    p = Provider(id=pid, label=LABELS[pid], kind=kind, source="auto", note=note, **kw)
    return OwnItem(p, base, "allowances" if kind == "quota" else "keys")


def unknown(pid: str, note: str = UNREADABLE, reason: str = UNKNOWN_REASON) -> OwnItem:
    return _item(pid, ("unknown", reason), note=note)


def _span(seconds: float) -> str:
    minutes = max(0, math.floor(seconds / SECONDS_PER_MINUTE))
    if minutes >= MINUTES_PER_HOUR * 2:
        return f"{minutes // MINUTES_PER_HOUR} hours"
    return f"{minutes} minute{'' if minutes == 1 else 's'}" if minutes else "less than a minute"


def _ago(seconds: float) -> str:
    return "just now" if seconds < SECONDS_PER_MINUTE else f"{_span(seconds)} ago"


def _when(at: float, tz: ZoneInfo) -> str:
    d = datetime.fromtimestamp(at, tz)
    return f"{d.day} {d:%b}, {d:%H:%M}"


class Own:
    """Builds the automatic items for one owner; each source on its own deadline."""

    def __init__(self, sources: OwnSources, settings: Settings) -> None:
        self._src = sources
        self._s = settings
        self._web = CachedUsage(sources.web) if sources.web is not None else None

    async def items(self, uid: str, now: datetime, tz: ZoneInfo) -> list[OwnItem]:
        s = self._s
        jobs: list[tuple[str, Callable[[], Awaitable[OwnItem | None]]]] = [
            ("brain_claude", lambda: self._brain("brain_claude", s.anthropic_api_key, False)),
            ("brain_gemini", lambda: self._brain("brain_gemini", s.gemini_api_key, True)),
            ("google_link", lambda: self._google(uid)),
            ("telegram_bot", lambda: self._telegram(uid, tz)),
            ("web_credits", lambda: self._web_credits(now, tz)),
            ("github_token", lambda: self._github(uid, now)),
            ("home_link", lambda: self._home(uid, now)),
        ]
        got = await asyncio.gather(*(self._guard(pid, job) for pid, job in jobs))
        return [i for i in got if i is not None]

    @staticmethod
    async def _guard(pid: str, job: Callable[[], Awaitable[OwnItem | None]]) -> OwnItem | None:
        try:
            return await asyncio.wait_for(job(), SOURCE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - one source never breaks the board
            log.warning(
                "vitals: source unreadable", extra={"item": pid, "error": type(exc).__name__}
            )
            return unknown(pid)

    async def _brain(self, pid: str, key: object, free: bool) -> OwnItem | None:
        if key is None:
            return None  # that key is not configured: not set up at all
        reader = self._src.gemini if free else self._src.claude
        if reader is None:
            return unknown(pid)
        seen = reader()
        state = seen.state if isinstance(seen.state, str) else ""
        if state not in BRAIN_STATES:
            return unknown(pid)
        base = BRAIN_STATES[state]
        if state == "busy" and free:
            base = ("amber", "has reached its free limit for now")
        if state == "unreachable" and seen.on_laptop is True:
            base = ("amber", "could not be reached; the laptop is answering")
        return _item(pid, base, note=BRAIN_NOTES.get(state, ""))

    async def _google(self, uid: str) -> OwnItem | None:
        if self._src.google is None:
            return None
        st = await self._src.google.status(uid)
        if st.get("needs_reconnect") is True:
            return _item("google_link", ("red", "needs reconnecting"))
        if st.get("connected") is not True:
            return None
        return _item("google_link", ("ok", ""), note="Connected.")

    async def _telegram(self, uid: str, tz: ZoneInfo) -> OwnItem | None:
        if self._s.telegram_bot_token is None:
            return None
        if self._src.health is None:
            return unknown("telegram_bot", note=RUN_CHECK, reason="hasn't been checked yet")
        report = await self._src.health.last(uid)
        if report is None:  # no systems check has run yet
            return unknown("telegram_bot", note=RUN_CHECK, reason="hasn't been checked yet")
        found = next((r for r in report.results if r.key == "telegram"), None)
        if found is None:  # the check left it out: not set up (no paired chat, R5.1 D4)
            return None
        if found.status not in PROBE_STATES:
            return unknown("telegram_bot", note=RUN_CHECK, reason="hasn't been checked yet")
        note = f"Last checked {_when(found.at, tz)}." if math.isfinite(found.at) else ""
        return _item("telegram_bot", PROBE_STATES[found.status], note=note)

    async def _web_credits(self, now: datetime, tz: ZoneInfo) -> OwnItem | None:
        if self._web is None:
            return None
        u = await self._web.get(now.timestamp())
        used, limit = float(u.used), None if u.limit is None else float(u.limit)
        spent = limit is not None and used >= limit
        base: tuple[Status, str] = (
            ("red", "are used up") if u.exhausted and not spent else ("ok", "")
        )
        reset = next_month_start(now, tz)
        return _item("web_credits", base, limit=limit, used=used, unit="credits", reset_at=reset)

    async def _github(self, uid: str, now: datetime) -> OwnItem | None:
        gh = self._src.github
        if gh is None:
            return None
        st = await gh.status(uid)
        if st.get("needs_reconnect") is True:
            return _item("github_token", ("red", "needs reconnecting"))
        if st.get("connected") is not True:
            return None
        meta = await gh.token_meta(uid)
        if meta is None:
            return unknown("github_token", note=NEXT_USE, reason="hasn't been used yet")
        ts = now.timestamp()
        expires = None if meta.expires_at is None else datetime.fromtimestamp(meta.expires_at, UTC)
        rate: dict[str, Any] = {}
        reset = meta.rate_reset
        if meta.rate_limit and meta.rate_used is not None and reset is not None and reset > ts:
            rate = {
                "limit": float(meta.rate_limit),
                "used": float(meta.rate_used),
                "unit": "calls this hour",
                "reset_at": datetime.fromtimestamp(reset, UTC),
            }
        note = "" if expires is not None else NO_EXPIRY
        return _item("github_token", ("ok", ""), note=note, expires_at=expires, **rate)

    async def _home(self, uid: str, now: datetime) -> OwnItem | None:
        if self._src.home is None:
            return None
        st = await self._src.home.status(uid)
        if st is None:
            return None  # no home linked
        if st.last_seen_at is None:
            return _item("home_link", ("red", "has never reported in"))
        age = max(0.0, now.timestamp() - st.last_seen_at)
        if st.state == "offline" or age > self._s.home_offline_after_s:
            return _item("home_link", ("red", f"is offline: no heartbeat for {_span(age)}"))
        base: tuple[Status, str] = (
            ("amber", "reports a problem") if st.state == "degraded" else ("ok", "")
        )
        return _item("home_link", base, note=f"Last heartbeat {_ago(age)}.")


__all__ = [
    "LABELS",
    "OWN_IDS",
    "QUIET_IDS",
    "BrainReader",
    "CachedUsage",
    "GithubLike",
    "HealthReader",
    "HomeReader",
    "Own",
    "OwnItem",
    "OwnSources",
    "StatusReader",
    "UsageReporterLike",
]
