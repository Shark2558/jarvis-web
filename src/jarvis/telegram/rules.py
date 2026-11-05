# src/jarvis/telegram/rules.py
"""Privacy on Telegram (R1 D4). Bot chats are cloud chats on Telegram's servers, not end-to-end
encrypted, so email, Drive, documents and contacts readouts are refused during a Telegram turn
unless the owner switched them on (Integrations -> Telegram). `ChannelRules` wraps the gateway's
`OwnerRules` and appends DENY rules (source "telegram") only while `core.channel.on_telegram()`.
Unpaired or unreadable state fails closed. No gateway change.

R2 D12: the vault list, notes and things (`vault_*`, `kb_*`, `belongings_*`, reads and writes) are
a SECOND group with its own switch (`allow_personal_reads`, default off). Neither switch opens the
other's group, so widening one consent never widens the other silently.

Recently deleted holds entries of both groups (R2 review H1): `deleted_list` needs the first switch
and, while the second is off, hides vault documents, notes and things (`personal_reads_allowed`,
read by the tool); `deleted_restore` of any kind needs BOTH switches.

R3 D15 (decided at R3 I0): a THIRD group with its own switch (`allow_home_reads`, default off):
the home's devices and their states (`home_devices`: a lock's state is security-sensitive), camera
history and the people JARVIS recognises (`camera_*`, `faces_*`). `home_status` (armed or not,
laptop online: what the alerts already say) and `home_arm` stay available; disarming and locks are
R3 and always wait in the console. No other switch opens this group, and it opens no other."""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

from jarvis.core.channel import on_telegram
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.telegram.store import TelegramStore
from jarvis.tools.policy import Effect, OwnerRules, PolicyRule

log = get_logger(__name__)

# Reads that return other people's or private titles (mail, Drive, documents, contacts, family
# members' events, deleted items). gmail_track_packages shapes its own answer (status only while
# these are off), family_free_slots returns names and times only, grocery_list is the owner's own
# list; gmail_create_draft and the rest stay allowed. tests/test_telegram_tool_guard.py makes every
# read tool pick a side, so a new one cannot slip through unclassified.
PRIVATE_PATTERNS: tuple[str, ...] = (
    "gmail_search",
    "gmail_read",
    "gmail_unread_digest",
    "drive_*",
    "doc_*",
    "docs_*",
    "contacts_*",
    "family_calendar_events",
    "deleted_list",
)
REFUSAL = "Not available from Telegram — your choice in Integrations → Telegram; open the console."
# R2 D12: the owner's vault list (metadata only, never files), notes, memos, links and things.
PERSONAL_PATTERNS: tuple[str, ...] = ("vault_*", "kb_*", "belongings_*")
PERSONAL_REFUSAL = (
    "Your vault list, notes and things are not available from Telegram - your choice in "
    "Integrations -> Telegram; open the console."
)
# R3 D15: home devices, camera history and faces (its own switch, default off).
HOME_PATTERNS: tuple[str, ...] = ("home_devices", "camera_*", "faces_*")
HOME_REFUSAL = (
    "Your home devices, camera history and the people JARVIS recognises are not available from "
    "Telegram - your choice in Integrations -> Telegram; open the console."
)
# R2 review H1: a restore can bring back an entry of either group, so it needs both switches.
BOTH_PATTERNS: tuple[str, ...] = ("deleted_restore",)
BOTH_REFUSAL = (
    "Restoring from Recently deleted works on Telegram only when both switches are on in "
    "Integrations -> Telegram; open the console to restore it."
)


# Review: a forwarded or via-bot message is someone else's text. While `outside_message()` is
# active, every reversible write (R2) becomes a card, as in a tainted round; R3 always asks.
_outside: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jarvis_telegram_outside", default=False
)
# A rule that matches no tool. ChannelRules adds it on every Telegram turn, carrying its store's
# token, so the service can prove the rules are INSTALLED on the gateway (fail closed if not).
MARKER = "__telegram_channel_rules__"
OUTSIDE_REASON = "That text came from someone else, so it needs your tap."


@contextmanager
def outside_message() -> Iterator[None]:
    token = _outside.set(True)
    try:
        yield
    finally:
        _outside.reset(token)


# Whether the owner allowed private reads, as of the last time the rules were read in this turn.
# Tools that can shape their own answer (gmail_track_packages) read it; unset means "off".
_reads_allowed: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jarvis_telegram_reads_allowed", default=False
)


def private_reads_allowed() -> bool:
    """True only if the owner switched private reads on and this turn's rules saw it."""
    return _reads_allowed.get()


@contextmanager
def private_reads(allowed: bool) -> Iterator[None]:
    """Set the toggle for a block (tests, and callers that know it)."""
    token = _reads_allowed.set(allowed)
    try:
        yield
    finally:
        _reads_allowed.reset(token)


# The same for the second switch: `deleted_list` hides vault, note and thing entries while it is
# off on a Telegram turn. Unset means "off".
_personal_allowed: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jarvis_telegram_personal_allowed", default=False
)


def personal_reads_allowed() -> bool:
    """True only if the owner switched the second group on and this turn's rules saw it."""
    return _personal_allowed.get()


@contextmanager
def personal_reads(allowed: bool) -> Iterator[None]:
    token = _personal_allowed.set(allowed)
    try:
        yield
    finally:
        _personal_allowed.reset(token)


def _deny_rules(patterns: tuple[str, ...], reason: str) -> list[PolicyRule]:
    return [
        PolicyRule(tool_pattern=p, effect=Effect.DENY, source="telegram", reason=reason)
        for p in patterns
    ]


class ChannelRules:
    """An `OwnerRules` that adds the Telegram privacy rules to another's."""

    def __init__(self, inner: OwnerRules | None, store: TelegramStore) -> None:
        self._inner = inner
        self._store = store

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        rules = list(await self._inner.rules_for(user_id)) if self._inner is not None else []
        if not on_telegram():
            return rules
        try:
            link = await self._store.get(user_id)
            allowed = link is not None and link.allow_private_reads
            personal = link is not None and link.allow_personal_reads
            home = link is not None and link.allow_home_reads
        except Exception as exc:  # noqa: BLE001 - fail closed
            log.warning("telegram settings unreadable", extra={"error": type(exc).__name__})
            allowed = personal = home = False
        _reads_allowed.set(allowed)
        _personal_allowed.set(personal)
        out = list(rules) if allowed else [*rules, *_deny_rules(PRIVATE_PATTERNS, REFUSAL)]
        if not personal:  # R2 D12: its own switch, never opened by the one above
            out += _deny_rules(PERSONAL_PATTERNS, PERSONAL_REFUSAL)
        if not home:  # R3 D15: a third switch, opened by neither of the others
            out += _deny_rules(HOME_PATTERNS, HOME_REFUSAL)
        if not (allowed and personal):  # review H1: a restore spans both groups
            out += _deny_rules(BOTH_PATTERNS, BOTH_REFUSAL)
        if _outside.get():
            out.append(
                PolicyRule(
                    tool_pattern="*",
                    effect=Effect.ASK,
                    risks=[ActionRisk.REVERSIBLE],
                    source="telegram",
                    reason=OUTSIDE_REASON,
                )
            )
        out.append(
            PolicyRule(
                tool_pattern=MARKER,
                effect=Effect.ASK,
                source="telegram",
                reason=self._store.rules_token,
            )
        )
        return out


def wrap_rules(inner: OwnerRules | None, store: TelegramStore) -> ChannelRules:
    """The ONLY supported way to install the Telegram privacy rules: set the gateway's
    `rules` to this (any other layer may wrap it). The service refuses Telegram turns when the
    gateway's rules do not carry this store's marker."""
    return ChannelRules(inner, store)


__all__ = [
    "BOTH_PATTERNS",
    "BOTH_REFUSAL",
    "HOME_PATTERNS",
    "HOME_REFUSAL",
    "MARKER",
    "PERSONAL_PATTERNS",
    "PERSONAL_REFUSAL",
    "PRIVATE_PATTERNS",
    "REFUSAL",
    "ChannelRules",
    "outside_message",
    "personal_reads",
    "personal_reads_allowed",
    "private_reads",
    "private_reads_allowed",
    "wrap_rules",
]
