# src/jarvis/helpers/gate.py
"""The one sender for every helper message, and the nudge limits (docs/plans/r11-free-helpers.md
D4, D6, D21).

`HelperSender.send(uid, kind, text, *, due)` refuses a kind that is not R11's; for a nudge it
first checks the owner's state in `{prefix}helpers_nudge/{uid}` (stopped for today, snoozed, the
per-kind daily cap, the deployment's `nudges_max_per_day` and `nudges_max_per_hour`); then it asks
the one alert policy (`Notifier.notify`, quiet hours, storm control, Telegram caps). A send counts
toward the caps only when a channel took it or it was held. Each attempt is logged, content-free,
in `{prefix}helpers_gate/{uid}_{day}` (kind, due minute, sent minute, outcome), which is what the
exit check reads ("on time for 2 weeks", D21). A part only ever holds a `PartSender`, which may
send that part's own kinds (`kinds.KINDS_OF`). The nudge state can't be read: no nudge (fail
closed); the send log can't be written: the message still went (logged as a class name only).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from jarvis.alerts import R11_ALERT_KINDS, AlertKind
from jarvis.config import Settings
from jarvis.helpers.kinds import DEFAULT_CAPS, KINDS_OF, MAX_CAP, NUDGE_KINDS, PartName
from jarvis.logging import get_logger
from jarvis.notify.ports import Delivery, Notifier, Signal
from jarvis.notify.quiet import local
from jarvis.storage.docs import Delete, Docs, DocTx, Query

log = get_logger(__name__)

STATE = "helpers_nudge"
SENDS = "helpers_gate"
ALL = "*"  # every nudge at once ("no more nudges today")
KEEP_DAYS = 15  # the exit check reads 14
MAX_SENDS_A_DAY = 300
MAX_TEXT = 300
ON_TIME = timedelta(minutes=6)  # one 5-minute clock run plus the Scheduler's jitter
SNOOZE_MINUTES = (15, 720)  # the bounds of a snooze, in minutes
_R11 = frozenset(R11_ALERT_KINDS)
_NUDGES = frozenset(NUDGE_KINDS)
_COUNTED = frozenset({"rang", "silent", "held"})  # a send that counts toward the caps
_TARGETS = frozenset({ALL, *NUDGE_KINDS})


class GateUnavailable(RuntimeError):
    """The nudge state couldn't be read or changed (plain words)."""


class NudgeState(BaseModel):
    """`{prefix}helpers_nudge/{uid}`: caps (kind -> per day), snoozed (kind or "*" -> ISO time),
    stopped (kind or "*" -> local date). Nothing else; no text, no times of day he likes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    caps: dict[str, int] = Field(default_factory=dict)
    snoozed: dict[str, str] = Field(default_factory=dict)
    stopped: dict[str, str] = Field(default_factory=dict)
    rev: int = Field(default=0, ge=0)

    def cap(self, kind: str) -> int:
        return self.caps.get(kind, DEFAULT_CAPS.get(kind, 0))

    def snoozed_until(self, kind: str) -> datetime | None:
        times = [_parse(self.snoozed.get(k)) for k in (kind, ALL)]
        found = [t for t in times if t is not None]
        return max(found) if found else None

    def stopped_on(self, kind: str, day: str) -> bool:
        return day in (self.stopped.get(kind), self.stopped.get(ALL))


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _minute(at: datetime) -> str:
    """A minute in UTC (a naive time is taken as UTC), so logged minutes compare as text."""
    aware = at if at.tzinfo is not None else at.replace(tzinfo=UTC)
    return aware.astimezone(UTC).replace(second=0, microsecond=0).isoformat()


def _target(kind: str) -> str:
    if kind not in _TARGETS:
        raise ValueError("unknown nudge")
    return kind


class GateStore:
    """The nudge state and the send log on the Docs port."""

    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._docs = docs
        self._prefix = prefix

    def _state(self, uid: str) -> str:
        return f"{self._prefix}helpers_nudge/{uid}"

    def _day(self, uid: str, day: str) -> str:
        return f"{self._prefix}helpers_gate/{uid}_{day}"

    async def state(self, uid: str) -> NudgeState:
        try:
            raw = await self._docs.get(self._state(uid))
            return NudgeState.model_validate(raw.get("state", {})) if raw else NudgeState()
        except Exception as exc:  # noqa: BLE001 - fail closed for nudges
            raise GateUnavailable("Your nudge settings couldn't be read just now.") from exc

    async def change(self, uid: str, fn: Callable[[NudgeState], NudgeState]) -> NudgeState:
        path = self._state(uid)

        async def run(tx: DocTx) -> NudgeState:
            raw = await tx.get(path)
            now = NudgeState.model_validate(raw.get("state", {})) if raw else NudgeState()
            new = fn(now).model_copy(update={"rev": now.rev + 1})
            tx.set(path, {"uid": uid, "state": new.model_dump()})
            return new

        return await self._docs.transaction(run)

    async def snooze(self, uid: str, kind: str, minutes: int, now: datetime) -> NudgeState:
        lo, hi = SNOOZE_MINUTES
        if not lo <= minutes <= hi:
            raise ValueError(f"snooze for {lo} to {hi} minutes")
        until, key = _minute(now + timedelta(minutes=minutes)), _target(kind)
        return await self.change(
            uid, lambda s: s.model_copy(update={"snoozed": {**s.snoozed, key: until}})
        )

    async def stop_today(self, uid: str, kind: str, day: str) -> NudgeState:
        key = _target(kind)
        return await self.change(
            uid, lambda s: s.model_copy(update={"stopped": {**s.stopped, key: day}})
        )

    async def resume(self, uid: str, kind: str) -> NudgeState:
        key = _target(kind)

        def drop(s: NudgeState) -> NudgeState:
            if key == ALL:
                return s.model_copy(update={"snoozed": {}, "stopped": {}})
            snoozed = {k: v for k, v in s.snoozed.items() if k != key}
            stopped = {k: v for k, v in s.stopped.items() if k != key}
            return s.model_copy(update={"snoozed": snoozed, "stopped": stopped})

        return await self.change(uid, drop)

    async def set_caps(self, uid: str, caps: Mapping[str, int]) -> NudgeState:
        clean: dict[str, int] = {}
        for kind, n in caps.items():
            if kind not in _NUDGES or isinstance(n, bool) or not isinstance(n, int):
                raise ValueError("unknown nudge or a cap that isn't a whole number")
            if not 0 <= n <= MAX_CAP:
                raise ValueError(f"a nudge cap is 0 to {MAX_CAP} a day")
            clean[kind] = n
        return await self.change(uid, lambda s: s.model_copy(update={"caps": {**s.caps, **clean}}))

    async def sends(self, uid: str, day: str) -> list[dict[str, str]]:
        raw = await self._docs.get(self._day(uid, day))
        got = raw.get("sends") if raw else None
        return [dict(e) for e in got if isinstance(e, dict)] if isinstance(got, list) else []

    async def record(self, uid: str, day: str, entry: dict[str, str]) -> None:
        path = self._day(uid, day)

        async def run(tx: DocTx) -> None:
            raw = await tx.get(path)
            sends = list(raw.get("sends", [])) if raw else []
            if len(sends) < MAX_SENDS_A_DAY:
                sends.append(entry)
            tx.set(path, {"uid": uid, "day": day, "sends": sends})

        await self._docs.transaction(run)

    async def days(self, uid: str) -> list[tuple[str, list[dict[str, str]]]]:
        rows = await self._docs.query(Query(f"{self._prefix}{SENDS}", where=("uid", uid)))
        out = [(str(d.get("day", "")), list(d.get("sends", []))) for _, d in rows]
        return sorted(out)

    async def sweep(self, owners: tuple[str, ...], today: str) -> int:
        cutoff = (datetime.fromisoformat(today) - timedelta(days=KEEP_DAYS)).date().isoformat()
        gone = [self._day(u, day) for u in owners for day, _ in await self.days(u) if day < cutoff]
        if gone:
            await self._docs.write([Delete(p) for p in gone])
        return len(gone)

    async def delete_all(self, uid: str) -> int:
        paths = [self._day(uid, day) for day, _ in await self.days(uid)]
        if await self._docs.get(self._state(uid)) is not None:
            paths.append(self._state(uid))
        if paths:
            await self._docs.write([Delete(p) for p in paths])
        return len(paths)


@dataclass(frozen=True)
class SendResult:
    """`outcome`: rang | silent | held | dropped:<reason> | undelivered | stopped | snoozed |
    capped | unavailable. `retry`: nothing decided it and no channel took it (try next run)."""

    outcome: str
    delivered: bool = False
    counted: bool = False
    retry: bool = False


def _classify(delivery: Delivery) -> SendResult:
    if delivery.telegram or delivery.push:
        word = "rang" if delivery.action == "ring" else "silent"
        return SendResult(word, delivered=True, counted=True)
    if delivery.action == "hold":
        return SendResult("held", counted=True)
    if delivery.action == "drop":
        return SendResult(f"dropped:{delivery.reason}")
    return SendResult("undelivered", retry=True)


def _clean(text: str) -> str:
    one = " ".join("".join(c if c >= " " and c != "\x7f" else " " for c in text).split())
    if not one:
        raise ValueError("a helper message needs words")
    return one if len(one) <= MAX_TEXT else one[: MAX_TEXT - 1].rstrip() + "…"


class HelperSender:
    def __init__(
        self,
        notifier: Notifier,
        store: GateStore,
        settings: Settings,
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._notifier = notifier
        self._store = store
        self._s = settings
        self._now = now

    @property
    def store(self) -> GateStore:
        return self._store

    def for_part(self, part: PartName) -> PartSender:
        return PartSender(self, part)

    def today(self, at: datetime | None = None) -> str:
        return local(at or self._now(), self._s.user_timezone).date().isoformat()

    async def send(
        self,
        uid: str,
        kind: AlertKind,
        text: str,
        *,
        due: datetime,
        named: str | None = None,
        subject: str | None = None,
    ) -> SendResult:
        if kind not in _R11:
            raise ValueError("not a helper alert kind")
        message, now = _clean(text), self._now()
        day = self.today(now)
        if kind in _NUDGES and (refusal := await self._refusal(uid, kind, now, day)) is not None:
            await self._log(uid, day, kind, due, now, refusal.outcome)
            return refusal
        signal = Signal(source="nudge", kind=kind, subject=subject)
        try:
            delivery = await self._notifier.notify(uid, signal, message, named_message=named)
        except Exception as exc:  # noqa: BLE001 - "can't send" is a result, never an error
            log.warning("helper alert not sent", extra={"error": type(exc).__name__})
            return SendResult("unavailable", retry=True)
        got = _classify(delivery)
        await self._log(uid, day, kind, due, now, got.outcome)
        return got

    async def _refusal(self, uid: str, kind: str, now: datetime, day: str) -> SendResult | None:
        try:
            state = await self._store.state(uid)
            sent = [e for e in await self._store.sends(uid, day) if e.get("o") in _COUNTED]
        except Exception as exc:  # noqa: BLE001 - fail closed: no nudge when JARVIS can't tell
            log.warning("nudge state unreadable", extra={"error": type(exc).__name__})
            return SendResult("unavailable", retry=True)
        if state.stopped_on(kind, day):
            return SendResult("stopped")
        until = state.snoozed_until(kind)
        if until is not None and now < until:
            return SendResult("snoozed")
        nudges = [e for e in sent if e.get("k") in _NUDGES]
        hour_ago = _minute(now - timedelta(hours=1))
        if (
            sum(1 for e in nudges if e.get("k") == kind) >= state.cap(kind)
            or len(nudges) >= self._s.nudges_max_per_day
            or sum(1 for e in nudges if e.get("at", "") > hour_ago) >= self._s.nudges_max_per_hour
        ):
            return SendResult("capped")
        return None

    async def _log(
        self, uid: str, day: str, kind: str, due: datetime, now: datetime, outcome: str
    ) -> None:
        entry = {"k": kind, "due": _minute(due), "at": _minute(now), "o": outcome}
        try:
            await self._store.record(uid, day, entry)
        except Exception as exc:  # noqa: BLE001 - the message already went (or didn't)
            log.warning("helper send log not written", extra={"error": type(exc).__name__})


class PartSender:
    """A part's own sender: only the kinds `kinds.KINDS_OF[part]` lists."""

    def __init__(self, sender: HelperSender, part: PartName) -> None:
        self._sender = sender
        self.part = part

    def today(self, at: datetime | None = None) -> str:
        return self._sender.today(at)

    async def send(
        self,
        uid: str,
        kind: AlertKind,
        text: str,
        *,
        due: datetime,
        named: str | None = None,
        subject: str | None = None,
    ) -> SendResult:
        if kind not in KINDS_OF[self.part]:
            raise ValueError(f"the {self.part} helpers may not send that kind of alert")
        return await self._sender.send(uid, kind, text, due=due, named=named, subject=subject)


def fortnight(
    days: list[tuple[str, list[dict[str, str]]]], today: str, *, max_per_day: int
) -> dict[str, int]:
    """D21, over the last 14 local days of the send log: reminders sent on time (in the first
    clock run at or after due: at most `ON_TIME` late, never early) or late, and the days on
    which the nudges that went out stayed inside the day's total cap."""
    start = (datetime.fromisoformat(today) - timedelta(days=13)).date().isoformat()
    on_time = late = early = within = 0
    for day, sends in days:
        if not start <= day <= today:
            continue
        counted = [e for e in sends if e.get("o") in _COUNTED]
        within += int(sum(1 for e in counted if e.get("k") in _NUDGES) <= max_per_day)
        for e in counted:
            due, at = _parse(e.get("due")), _parse(e.get("at"))
            if e.get("k") in _NUDGES or due is None or at is None:
                continue
            gap = at - due
            early += int(gap < timedelta(0))
            on_time += int(timedelta(0) <= gap <= ON_TIME)
            late += int(gap > ON_TIME)
    return {
        "reminders_on_time": on_time,
        "reminders_late": late,
        "reminders_early": early,
        "nudge_days_within_limits": within,
    }


__all__ = [
    "ALL",
    "KEEP_DAYS",
    "ON_TIME",
    "SENDS",
    "STATE",
    "GateStore",
    "GateUnavailable",
    "HelperSender",
    "NudgeState",
    "PartSender",
    "SendResult",
    "fortnight",
]
