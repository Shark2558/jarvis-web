# src/jarvis/calls/limits.py
"""Call limits and caps (R18 A1; docs/plans/r18-calls.md sections 6 and 7 item 4; BUILD-BRIEF.md
"Limits" and "Caps"; Layer 4 guardrail over the Layer 7 counters in `jarvis.calls.store`).

Checked twice for every outgoing call: when the owner approves the card (`check_approval`: the
card says why it can't be placed, nothing is issued) and when the call is about to be dialled
(`admit_dial`: the same checks again, and the day's counters are counted in ONE transaction with
them, so two dials racing at the limit can't both pass).

- A day (IST): 10 calls, 2 to the same number, 3 numbers never called before, at most one redial
  to a number that did not answer.
- Quiet hours: no call starts between 21:00 and 08:00 IST, and none that could run past 21:00
  at its full length.
- Money: the card's estimate must be known (an unknown price is never ₹0), within the card's own
  ₹ cap and the per-call cap, within what is left of this month's calls cap, and within what is
  left of the owner's overall monthly limit for paid AI (`OwnerBudget`; no limit set: no check;
  a limit or a month that can't be read refuses: fail closed).
- During a call (`cap_reached`, called by the call engine): the call's minutes, the call's ₹ and
  the month's ₹ — at a cap JARVIS says goodbye and ends.

Refusals are `LimitRefused` with a stable `code` and plain words that never carry a number.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from jarvis.calls.models import (
    CALLS_PER_DAY,
    CALLS_PER_NUMBER_PER_DAY,
    NEW_NUMBERS_PER_DAY,
    NO_ANSWER_REDIALS_PER_DAY,
    QUIET_FROM,
    QUIET_UNTIL,
    QUIET_ZONE,
    CallCard,
    CallSettings,
    EndReason,
)
from jarvis.calls.ports import CallStore, DayCounts
from jarvis.logging import get_logger

log = get_logger(__name__)
IST = ZoneInfo(QUIET_ZONE)

MSG_DAY = f"JARVIS has placed {CALLS_PER_DAY} calls today, the most for one day. Try tomorrow."
MSG_NUMBER = (
    f"This number has had {CALLS_PER_NUMBER_PER_DAY} calls from JARVIS today, the most for one "
    "day. Try tomorrow."
)
MSG_NEW = (
    f"JARVIS has called {NEW_NUMBERS_PER_DAY} new numbers today, the most for one day. This "
    "number can be called tomorrow."
)
MSG_REDIAL = "This number didn't answer today and was already called again. Try tomorrow."
MSG_QUIET = "No calls between 21:00 and 08:00. JARVIS can place it from 08:00."
MSG_QUIET_SOON = (
    "This call could run past 21:00 at its full length. Shorten it or place it tomorrow from 08:00."
)
MSG_UNKNOWN_COST = (
    "JARVIS can't tell what this call would cost (a price it doesn't know), so it can't place it."
)
MSG_CARD_CAP = "This call's estimate is above its own ₹ cap."
MSG_CALL_CAP = "This call's estimate is above the ₹ cap for one call (Calls → Settings)."
MSG_MONTH_CAP = "This call would go over this month's ₹ cap for calls (Calls → Settings)."
MSG_OWNER_LIMIT = "This call would go over your monthly limit for paid AI (Vitals)."
MSG_UNREADABLE = "JARVIS can't read today's call counters or this month's spend, so no call."


class LimitRefused(Exception):
    """A call that must not be placed now; `str()` is plain words, `code` is stable."""

    def __init__(self, code: str, words: str) -> None:
        super().__init__(words)
        self.code, self.words = code, words


class OwnerBudget(Protocol):
    """What is left of the owner's overall monthly limit for paid AI, in ₹ (None: no limit
    set). Raises when it can't be read (the caller refuses: fail closed)."""

    async def left_inr(self, uid: str) -> float | None: ...


class _BillingLike(Protocol):
    @property
    def budgets(self) -> _BudgetsLike: ...

    async def month(self, uid: str) -> _MonthLike: ...


class _BudgetsLike(Protocol):
    async def get(self, uid: str) -> int | None: ...


class _MonthLike(Protocol):
    @property
    def counted_inr(self) -> float: ...


class BillingBudget:
    """`OwnerBudget` over `jarvis.billing.Billing`: the owner's limit minus this month's counted
    spend (the same figure the spending gate compares)."""

    def __init__(self, billing: _BillingLike) -> None:
        self._billing = billing

    async def left_inr(self, uid: str) -> float | None:
        limit = await self._billing.budgets.get(uid)
        if limit is None:
            return None
        month = await self._billing.month(uid)
        return float(limit) - float(month.counted_inr)


# ---- pure parts ------------------------------------------------------------------------------
def ist(now: datetime) -> datetime:
    return now.astimezone(IST)


def ist_day(now: datetime) -> date:
    return ist(now).date()


def ist_month(now: datetime) -> str:
    return ist(now).strftime("%Y-%m")


def in_quiet_hours(now: datetime) -> bool:
    t = ist(now).time()
    return t >= QUIET_FROM or t < QUIET_UNTIL


def quiet_problem(now: datetime, minutes: int) -> str | None:
    """Words when a call starting `now` (and lasting up to `minutes`) is inside quiet hours."""
    if in_quiet_hours(now):
        return MSG_QUIET
    if in_quiet_hours(now + timedelta(minutes=minutes)):
        return MSG_QUIET_SOON
    return None


def day_problem(counts: DayCounts, ref: str, new: bool) -> tuple[str, str] | None:
    """(code, words) when today's counters refuse one more call to the number `ref`."""
    if counts.calls >= CALLS_PER_DAY:
        return "day_limit", MSG_DAY
    to_number = counts.to_number(ref)
    if to_number >= CALLS_PER_NUMBER_PER_DAY:
        return "number_limit", MSG_NUMBER
    if new and counts.new_numbers >= NEW_NUMBERS_PER_DAY:
        return "new_numbers_limit", MSG_NEW
    unanswered = counts.no_answer.get(ref, 0)
    if unanswered and to_number >= 1 + NO_ANSWER_REDIALS_PER_DAY:
        return "redial_limit", MSG_REDIAL
    return None


def money_problem(
    card: CallCard, settings: CallSettings, month_inr: float, owner_left: float | None
) -> tuple[str, str] | None:
    """(code, words) when the card's ₹ estimate doesn't fit its caps."""
    estimate = card.estimate_inr
    if estimate is None:
        return "cost_unknown", MSG_UNKNOWN_COST
    if estimate > card.limits.max_inr:
        return "card_cap", MSG_CARD_CAP
    if estimate > settings.call_cap_inr:
        return "call_cap", MSG_CALL_CAP
    if month_inr + estimate > settings.month_cap_inr:
        return "month_cap", MSG_MONTH_CAP
    if owner_left is not None and estimate > owner_left:
        return "owner_limit", MSG_OWNER_LIMIT
    return None


def cap_reached(
    card: CallCard,
    settings: CallSettings,
    *,
    seconds: float,
    call_inr: float,
    month_inr: float,
) -> EndReason | None:
    """During a call (the engine asks after each turn): the cap that is reached, or None. At a
    cap JARVIS says goodbye and ends. `month_inr` includes this call's ₹ so far."""
    minutes = min(card.limits.max_minutes, settings.call_max_minutes)
    if seconds >= minutes * 60:
        return EndReason.CAP_MINUTES
    if call_inr >= min(card.limits.max_inr, settings.call_cap_inr):
        return EndReason.CAP_INR
    if month_inr >= settings.month_cap_inr:
        return EndReason.CAP_INR
    return None


# ---- the checks over the store ---------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Admitted:
    """A dial the limits let through, counted: today's counters after it."""

    counts: DayCounts
    new_number: bool


class Limits:
    def __init__(
        self,
        store: CallStore,
        *,
        budget: OwnerBudget | None = None,
        ref: Callable[[str, str], str] | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        """`ref(uid, e164)`: the store's keyed reference of a number (its sealer's `ref`), so a
        day's per-number counters can be read before the counting transaction."""
        self.store, self.budget, self._clock = store, budget, clock
        self._ref = ref if ref is not None else _sealer_ref(store)

    async def _money(self, uid: str, card: CallCard, settings: CallSettings, now: datetime) -> None:
        try:
            month_inr = await self.store.month_spend(uid, ist_month(now))
            owner_left = await self.budget.left_inr(uid) if self.budget is not None else None
        except Exception as exc:  # noqa: BLE001 - can't tell: no call (fail closed)
            log.error("call spend unreadable; no call", extra={"error": type(exc).__name__})
            raise LimitRefused("unreadable", MSG_UNREADABLE) from None
        problem = money_problem(card, settings, month_inr, owner_left)
        if problem is not None:
            raise LimitRefused(*problem)

    async def _common(self, uid: str, card: CallCard) -> tuple[CallSettings, datetime]:
        now = self._clock()
        settings = await self._settings(uid)
        minutes = min(card.limits.max_minutes, settings.call_max_minutes)
        quiet = quiet_problem(now, minutes)
        if quiet is not None:
            raise LimitRefused("quiet_hours", quiet)
        await self._money(uid, card, settings, now)
        return settings, now

    async def _settings(self, uid: str) -> CallSettings:
        try:
            return await self.store.settings(uid)
        except Exception as exc:  # noqa: BLE001 - fail closed
            log.error("call settings unreadable; no call", extra={"error": type(exc).__name__})
            raise LimitRefused("unreadable", MSG_UNREADABLE) from None

    async def check_approval(self, uid: str, card: CallCard) -> None:
        """At his tap: quiet hours, money and today's counters (read, not counted)."""
        _, now = await self._common(uid, card)
        try:
            counts = await self.store.day_counts(uid, ist_day(now))
            new = not await self.store.known_number(uid, card.number_e164)
        except Exception as exc:  # noqa: BLE001 - fail closed
            log.error("call counters unreadable; no call", extra={"error": type(exc).__name__})
            raise LimitRefused("unreadable", MSG_UNREADABLE) from None
        problem = day_problem(counts, self._ref(uid, card.number_e164), new)
        if problem is not None:
            raise LimitRefused(*problem)

    async def admit_dial(self, uid: str, card: CallCard) -> Admitted:
        """Just before the phone dials: the same checks again, and the call counted in the same
        transaction as today's limits (never counted when refused)."""
        _, now = await self._common(uid, card)
        ref = self._ref(uid, card.number_e164)
        seen: list[bool] = []

        def check(counts: DayCounts, new: bool) -> str | None:
            seen.append(new)
            problem = day_problem(counts, ref, new)
            return None if problem is None else problem[0]

        try:
            counts, refused = await self.store.count_call(
                uid, ist_day(now), card.number_e164, check=check
            )
        except Exception as exc:  # noqa: BLE001 - fail closed
            log.error("call counters unwritable; no call", extra={"error": type(exc).__name__})
            raise LimitRefused("unreadable", MSG_UNREADABLE) from None
        if refused is not None:
            words = {
                "day_limit": MSG_DAY,
                "number_limit": MSG_NUMBER,
                "new_numbers_limit": MSG_NEW,
                "redial_limit": MSG_REDIAL,
            }.get(refused, MSG_DAY)
            raise LimitRefused(refused, words)
        return Admitted(counts, bool(seen and seen[-1]))

    async def no_answer(self, uid: str, e164: str) -> None:
        """The engine reports a call nobody answered (the redial rule). Never raises."""
        try:
            await self.store.count_no_answer(uid, ist_day(self._clock()), e164)
        except Exception as exc:  # noqa: BLE001 - a lost count only loosens nothing it shouldn't
            log.error("no-answer not counted", extra={"error": type(exc).__name__})

    async def add_spend(self, uid: str, inr: float, at: datetime | None = None) -> float | None:
        """The engine adds a call's ₹ to this month's calls spend; the new total, or None when
        it could not be written (logged loudly)."""
        try:
            return await self.store.add_spend(uid, ist_month(at or self._clock()), inr)
        except Exception as exc:  # noqa: BLE001 - the call happened; never lose it silently
            log.error("CALL SPEND NOT RECORDED", extra={"error": type(exc).__name__})
            return None


def _sealer_ref(store: CallStore) -> Callable[[str, str], str]:
    sealer = getattr(store, "sealer", None)
    ref = getattr(sealer, "ref", None)
    if ref is None:
        raise TypeError("the call store has no number sealer: pass ref=")
    return ref  # type: ignore[no-any-return]


__all__ = [
    "Admitted",
    "BillingBudget",
    "LimitRefused",
    "Limits",
    "OwnerBudget",
    "cap_reached",
    "day_problem",
    "in_quiet_hours",
    "ist_day",
    "ist_month",
    "money_problem",
    "quiet_problem",
]
