# src/jarvis/calls/answering.py
"""Answering the calls he misses (R18 A1; row 104; docs/plans/r18-calls.md section 4, "Answering
calls you miss"; BUILD-BRIEF.md "Answering missed calls"; Layer 5 Communication).

Off by default (`CallSettings.answering_on`, switched by the `calls_answer_mode` tool or in the
Calls panel). When on, `AnsweringPolicy.should_answer` decides for each `call.state` "ringing"
event the phone reports (the engine and the phone side call it on every ring):

- only an incoming call JARVIS did not place, with the caller's number shown (a withheld number
  can't be matched to his rules, so it is left to ring);
- only after `answer_after_rings` rings (default 5) — before that the answer is "wait";
- the caller policy: everyone, saved contacts only, or everyone except saved contacts. A
  contacts look-up that fails decides "don't answer" (fail closed, both ways);
- not when his first name is missing (JARVIS says whose assistant it is) or this month's calls
  cap is reached (or can't be read).

`message_card` is the card such a call runs under: JARVIS says it is his AI assistant, takes a
message (name, reason, call-back number) and never agrees to anything (`may_agree` is empty).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from jarvis.calls.limits import ist_month
from jarvis.calls.models import (
    AnswerPolicy,
    CallCard,
    CallSettings,
    CardLimits,
    Direction,
)
from jarvis.calls.ports import CallStore
from jarvis.calls.protocol import CallStateEvent
from jarvis.logging import get_logger

log = get_logger(__name__)

ANSWER_MAX_MINUTES = 3  # a message, not a conversation
Code = Literal[
    "answer",
    "off",
    "not_ringing",
    "wait",
    "withheld",
    "contact",
    "not_contact",
    "contacts_down",
    "no_name",
    "month_cap",
    "unreadable",
]
_WORDS: dict[str, str] = {
    "answer": "JARVIS answers and takes a message.",
    "off": "Answering missed calls is off.",
    "not_ringing": "Not a ringing incoming call.",
    "wait": "Still ringing: not yet.",
    "withheld": "The caller's number is withheld, so it is left to ring.",
    "contact": "A saved contact: answering is for everyone except saved contacts.",
    "not_contact": "Not a saved contact: answering is for saved contacts only.",
    "contacts_down": "JARVIS couldn't check your contacts, so it is left to ring.",
    "no_name": "Add your first name in Calls → Settings so JARVIS can say whose assistant it is.",
    "month_cap": "This month's ₹ cap for calls is reached.",
    "unreadable": "JARVIS can't read the call settings, so it is left to ring.",
}


@dataclass(frozen=True)
class AnswerDecision:
    answer: bool
    code: Code
    words: str


def _no(code: Code) -> AnswerDecision:
    return AnswerDecision(False, code, _WORDS[code])


def decide(settings: CallSettings, *, rings: int, saved: bool | None) -> AnswerDecision:
    """The pure rule for a ringing call from a shown number. `saved`: is the caller a saved
    contact (None: could not tell)."""
    if not settings.answering_on:
        return _no("off")
    if rings < settings.answer_after_rings:
        return _no("wait")
    if not settings.owner_first_name.strip():
        return _no("no_name")
    policy = settings.answer_policy
    if policy is not AnswerPolicy.ALL and saved is None:
        return _no("contacts_down")
    if policy is AnswerPolicy.CONTACTS and not saved:
        return _no("not_contact")
    if policy is AnswerPolicy.NOT_CONTACTS and saved:
        return _no("contact")
    return AnswerDecision(True, "answer", _WORDS["answer"])


class ContactBook(Protocol):
    """Is this number one of his saved contacts? Raises when it can't tell."""

    async def is_saved(self, uid: str, e164: str) -> bool: ...


class _ContactsSearch(Protocol):
    async def require(self, uid: str) -> None: ...

    async def search(self, uid: str, name: str) -> Any: ...


class GoogleContactBook:
    """`ContactBook` over `jarvis.contacts.ContactsClient`: Google's contact search matches phone
    numbers too; a match counts only when one of its numbers is exactly this one."""

    def __init__(self, client: _ContactsSearch) -> None:
        self._client = client

    async def is_saved(self, uid: str, e164: str) -> bool:
        await self._client.require(uid)
        national = e164[3:] if e164.startswith("+91") else e164.lstrip("+")
        found = await self._client.search(uid, national)
        return any(e164 in tuple(c.phones) for c in found.contacts)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AnsweringPolicy:
    def __init__(
        self,
        store: CallStore,
        contacts: ContactBook | None,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.store, self.contacts, self._clock = store, contacts, clock

    async def _saved(self, uid: str, number: str, policy: AnswerPolicy) -> bool | None:
        if policy is AnswerPolicy.ALL:
            return None  # not needed: no look-up at all
        if self.contacts is None:
            return None
        try:
            return await self.contacts.is_saved(uid, number)
        except Exception as exc:  # noqa: BLE001 - can't tell: left to ring
            log.warning("contacts unreadable for answering", extra={"error": type(exc).__name__})
            return None

    async def should_answer(self, uid: str, event: CallStateEvent) -> AnswerDecision:
        """For one phone event. Never raises: anything it can't tell leaves the call ringing."""
        if event.state != "ringing" or event.call_id is not None:
            return _no("not_ringing")
        if not event.number_e164:
            return _no("withheld")
        try:
            settings = await self.store.settings(uid)
            if not settings.answering_on:
                return _no("off")
            month = await self.store.month_spend(uid, ist_month(self._clock()))
        except Exception as exc:  # noqa: BLE001 - fail closed: not answered
            log.error("call settings unreadable for answering", extra={"error": type(exc).__name__})
            return _no("unreadable")
        if month >= settings.month_cap_inr:
            return _no("month_cap")
        if event.rings < settings.answer_after_rings:
            return _no("wait")
        saved = await self._saved(uid, event.number_e164, settings.answer_policy)
        return decide(settings, rings=event.rings, saved=saved)


def message_card(settings: CallSettings, number: str) -> CallCard:
    """The card an answered call runs under: a message only, never an agreement."""
    name = " ".join(settings.owner_first_name.split()) or "the owner"
    return CallCard(
        direction=Direction.INCOMING,
        number_e164=number,
        purpose=(f"Take a message for {name}: who is calling, why, and a number to call back"),
        may_say=(
            f"{name} can't take the call just now.",
            f"JARVIS will pass the message on to {name}.",
        ),
        may_agree=(),
        languages=settings.default_languages,
        limits=CardLimits(
            max_minutes=min(ANSWER_MAX_MINUTES, settings.call_max_minutes),
            max_inr=settings.call_cap_inr,
        ),
    )


__all__ = [
    "ANSWER_MAX_MINUTES",
    "AnswerDecision",
    "AnsweringPolicy",
    "ContactBook",
    "GoogleContactBook",
    "decide",
    "message_card",
]
