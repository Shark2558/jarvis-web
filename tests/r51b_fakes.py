# tests/r51b_fakes.py -- R5.1 Part B: fakes for the Vitals board's automatic items (JARVIS's own
# keys and connections). Imported bare: `from r51b_fakes import ...`.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import SecretStr
from vitals_fakes import T0, FakeBilling, FakeNotifier

from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs
from jarvis.vitals.own import OwnSources
from jarvis.vitals.service import VitalsService
from jarvis.vitals.store import VitalsStore

SECRET = "sk-ant-api03-SuperSecretValue0123456789abcdefXYZ"


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now = self.now + timedelta(**kw)


@dataclass(frozen=True)
class Health:
    state: str = "ok"
    on_laptop: bool = False


class Brain:
    """A router's `health` reader: returns what the router last saw, or raises."""

    def __init__(self, state: str = "ok", *, on_laptop: bool = False, boom: bool = False) -> None:
        self.state, self.on_laptop, self.boom = state, on_laptop, boom

    def __call__(self) -> Health:
        if self.boom:
            raise RuntimeError(f"vendor said: {SECRET}")
        return Health(self.state, self.on_laptop)


class Google:
    def __init__(
        self, connected: bool = True, needs_reconnect: bool = False, *, boom: bool = False
    ):
        self.st = {"connected": connected, "needs_reconnect": needs_reconnect, "email": "a@b.c"}
        self.boom = boom

    async def status(self, uid: str) -> dict[str, Any]:
        if self.boom:
            raise RuntimeError(f"google said {SECRET}")
        return self.st


@dataclass(frozen=True)
class Result:
    key: str
    status: str
    at: float


@dataclass(frozen=True)
class Report:
    results: tuple[Result, ...] = ()


class HealthLast:
    def __init__(self, report: Report | None = None, *, boom: bool = False) -> None:
        self.report, self.boom, self.calls = report, boom, 0

    async def last(self, uid: str) -> Report | None:
        self.calls += 1
        if self.boom:
            raise RuntimeError(SECRET)
        return self.report


@dataclass(frozen=True)
class Usage:
    used: int
    limit: int | None = None
    exhausted: bool = False


class Web:
    def __init__(self, usage: Usage | None = None, *, boom: bool = False) -> None:
        self.value = usage or Usage(120, 1000)
        self.boom = boom
        self.calls = 0

    async def usage(self) -> Usage:
        self.calls += 1
        if self.boom:
            raise RuntimeError(f"tavily: {SECRET}")
        return self.value


@dataclass(frozen=True)
class Meta:
    seen_at: float
    expires_at: float | None = None
    rate_limit: int | None = None
    rate_used: int | None = None
    rate_reset: float | None = None


class Github:
    def __init__(
        self,
        meta: Meta | None = None,
        *,
        connected: bool = True,
        needs_reconnect: bool = False,
    ) -> None:
        self.meta = meta
        self.st = {"connected": connected, "login": "x", "needs_reconnect": needs_reconnect}

    async def status(self, uid: str) -> dict[str, Any]:
        return self.st

    async def token_meta(self, uid: str) -> Meta | None:
        return self.meta


@dataclass(frozen=True)
class HomeSt:
    state: str = "online"
    last_seen_at: float | None = None


class Home:
    def __init__(self, st: HomeSt | None = None, *, boom: bool = False) -> None:
        self.st, self.boom = st, boom

    async def status(self, uid: str) -> HomeSt | None:
        if self.boom:
            raise RuntimeError(SECRET)
        return self.st


def settings(**over: Any) -> Settings:
    return Settings().model_copy(update=over)


def with_keys(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "anthropic_api_key": SecretStr(SECRET),
        "gemini_api_key": SecretStr("AIzaGeminiSecret0123456789abcdefghij"),
        "telegram_bot_token": SecretStr("123456789:AAbbccddeeffgghhiijjkkllmmnnoopp"),
    }
    base.update(over)
    return settings(**base)


@dataclass
class OwnRig:
    own: OwnSources
    settings: Settings = field(default_factory=with_keys)
    billing: FakeBilling | None = field(default_factory=FakeBilling)
    clock: Clock = field(default_factory=Clock)
    docs: MemoryDocs = field(default_factory=MemoryDocs)
    notifier: FakeNotifier = field(default_factory=FakeNotifier)

    def __post_init__(self) -> None:
        self.store = VitalsStore(self.docs)
        self.svc = VitalsService(
            self.store,
            self.settings,
            billing=self.billing,  # type: ignore[arg-type]
            clock=self.clock,
            own=self.own,
        )

    @property
    def epoch(self) -> float:
        return self.clock().timestamp()
