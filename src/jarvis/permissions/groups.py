# src/jarvis/permissions/groups.py
"""Tool groups the owner sets Allow / Ask first / Never on (slice 10 D; Layer 4 policy input).

A group is a list of matchers: a tool-name pattern, optionally limited to calls at certain
EFFECTIVE risks (a calendar event with attendees is irreversible: it sends invitations). Patterns,
not a fixed list, so the tools other builders add in parallel fall into the right group when
merged (`web_*`, `task_*` / `tasks_*`, `doc_*`), and each domain's catch-all puts a future
irreversible tool into its "can't be undone" group. A tool no group knows keeps the risk default
(today's behaviour). A call may match two groups (an invitation is both "Add and change events"
and "Delete events and invite people"): the strictest choice wins, as in `Policy.decide`.

Irreversible groups offer only Ask first / Never: `validate_choices` refuses Allow (422), and
`rules_for` drops one that was hand-edited into storage — and `Policy` would refuse it anyway.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from jarvis.core.guardrails import ActionRisk
from jarvis.tools.policy import Effect, PolicyRule

R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
SOURCE_PREFIX = "owner:"


class PermissionRejected(ValueError):
    """A permission change that is not allowed; the message is plain words for the owner."""


@dataclass(frozen=True)
class Matcher:
    pattern: str
    risks: frozenset[ActionRisk] | None = None  # None: any effective risk


@dataclass(frozen=True)
class PermissionGroup:
    id: str
    section: str
    label: str
    hint: str
    risk: ActionRisk  # the most its calls can do: an irreversible group never offers Allow
    matchers: tuple[Matcher, ...]

    @property
    def irreversible(self) -> bool:
        return self.risk is R3

    @property
    def choices(self) -> tuple[Effect, ...]:
        if self.irreversible:
            return (Effect.ASK, Effect.DENY)
        return (Effect.ALLOW, Effect.ASK, Effect.DENY)

    @property
    def default(self) -> Effect:
        return Effect.ASK if self.irreversible else Effect.ALLOW

    def matches(self, tool: str, risk: ActionRisk) -> bool:
        return any(self._rule(m, Effect.DENY).matches(tool, {}, risk) for m in self.matchers)

    def refusal(self) -> str:
        return (
            f"switched off by the owner in Permissions ({self.section}: {self.label} — Never). "
            "Do not try to do it another way; tell the owner it is switched off."
        )

    def _rule(self, m: Matcher, effect: Effect) -> PolicyRule:
        return PolicyRule(
            tool_pattern=m.pattern,
            effect=effect,
            risks=sorted(m.risks) if m.risks is not None else None,
            source=SOURCE_PREFIX + self.id,
            reason=self.refusal() if effect is Effect.DENY else "",
        )

    def rules(self, effect: Effect) -> list[PolicyRule]:
        if effect is Effect.ALLOW and self.irreversible:
            return []  # never a standing allow for something that can't be undone
        return [self._rule(m, effect) for m in self.matchers]


def _m(pattern: str, *risks: ActionRisk) -> Matcher:
    return Matcher(pattern, frozenset(risks) if risks else None)


UNDO_HINT = "Can't be undone, so JARVIS always asks first — or never does it."

GROUPS: tuple[PermissionGroup, ...] = (
    PermissionGroup(
        "calendar_read",
        "Calendar",
        "Look at your calendar",
        "Read events and find free time.",
        R1,
        (_m("calendar_*", R1), _m("get_calendar")),
    ),
    PermissionGroup(
        "calendar_change",
        "Calendar",
        "Add and change events",
        "Events only you are in. Inviting people is the next row.",
        R2,
        (_m("calendar_create_event"), _m("calendar_update_event"), _m("calendar_*", R2)),
    ),
    PermissionGroup(
        "calendar_delete",
        "Calendar",
        "Delete events and invite people",
        UNDO_HINT,
        R3,
        (_m("calendar_delete_event"), _m("calendar_*", R3)),
    ),
    PermissionGroup(  # slice 11 B (D4/D5): its own row, after the Calendar rows
        "reminders",
        "Reminders",
        "Set, change and delete reminders",
        "Pop-ups on your phone from the Google Calendar app. A reminder is deleted like an "
        "event (Calendar), so Undo works for 30 days.",
        R2,
        (_m("reminder_*"), _m("reminders_*")),
    ),
    PermissionGroup(
        "email_read",
        "Email",
        "Search and read email",
        "JARVIS treats what other people wrote as information, never as instructions.",
        R1,
        (_m("gmail_*", R1),),
    ),
    PermissionGroup(
        "email_draft",
        "Email",
        "Write drafts",
        "Drafts wait in Gmail until you send them.",
        R2,
        (_m("gmail_create_draft"), _m("gmail_*", R2)),
    ),
    PermissionGroup(
        "email_send",
        "Email",
        "Send email",
        UNDO_HINT,
        R3,
        (_m("gmail_send"), _m("send_message"), _m("gmail_*", R3)),
    ),
    PermissionGroup(
        "todo_change",
        "To-do list",
        "Read and change your to-do list",
        "Add, edit and tick off to-dos. Never also stops deleting them.",
        R2,
        (_m("tasks_*"), _m("task_*"), _m("list_tasks"), _m("create_reminder")),
    ),
    PermissionGroup(
        "todo_delete",
        "To-do list",
        "Delete to-dos",
        UNDO_HINT,
        R3,
        (_m("task_delete"), _m("task_*", R3), _m("tasks_*", R3)),
    ),
    PermissionGroup(
        "memory_save",
        "Memory",
        "Save memories",
        "Things you ask JARVIS to remember. Text from email or the web always asks first.",
        R2,
        (_m("memory_save"),),
    ),
    PermissionGroup(
        "memory_forget",
        "Memory",
        "Forget memories",
        UNDO_HINT,
        R3,
        (_m("memory_forget"),),
    ),
    PermissionGroup(
        "web",
        "Web",
        "Search and read the web",
        "Your search words go to the web search service.",
        R1,
        (_m("web_*"),),
    ),
    PermissionGroup(
        "documents",
        "Documents",
        "Read your documents",
        "Files you attach in the chat.",
        R1,
        (_m("doc_*"), _m("docs_*")),
    ),
)
_BY_ID = {g.id: g for g in GROUPS}


def group_ids() -> list[str]:
    return [g.id for g in GROUPS]


def get_group(group_id: str) -> PermissionGroup | None:
    return _BY_ID.get(group_id)


def groups_for(tool: str, risk: ActionRisk) -> list[PermissionGroup]:
    """Every group a call to `tool` at this effective risk belongs to (may be none)."""
    return [g for g in GROUPS if g.matches(tool, risk)]


def validate_choices(choices: Mapping[str, object]) -> dict[str, Effect]:
    """The owner's requested choices as effects, or PermissionRejected (plain words)."""
    out: dict[str, Effect] = {}
    for gid, raw in choices.items():
        group = _BY_ID.get(gid) if isinstance(gid, str) else None
        if group is None:
            raise PermissionRejected("Unknown permission group: reload the page and try again.")
        try:
            effect = Effect(raw) if isinstance(raw, str) else None
        except ValueError:
            effect = None
        if effect is None:
            raise PermissionRejected(
                f"{group.label}: choose Allow, Ask first or Never."
                if not group.irreversible
                else f"{group.label}: choose Ask first or Never."
            )
        if effect not in group.choices:
            raise PermissionRejected(
                f"{group.label} can't be set to Allow: it can't be undone, so JARVIS always "
                "asks first (or never does it)."
            )
        out[gid] = effect
    return out


def stored_choices(raw: object) -> dict[str, Effect]:
    """Choices read from storage, field by field: an unknown group, an unknown effect or an
    Allow on an irreversible group (hand-edited) is dropped, i.e. reads as the default."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Effect] = {}
    for gid, value in raw.items():
        group = _BY_ID.get(gid) if isinstance(gid, str) else None
        if group is None or not isinstance(value, str):
            continue
        try:
            effect = Effect(value)
        except ValueError:
            continue
        if effect in group.choices:
            out[gid] = effect
    return out


def rules_for(choices: Mapping[str, Effect]) -> list[PolicyRule]:
    """Policy rules for the owner's choices. A choice equal to the default adds nothing."""
    rules: list[PolicyRule] = []
    for gid, effect in choices.items():
        group = _BY_ID.get(gid)
        if group is None or effect is group.default:
            continue
        rules.extend(group.rules(effect))
    return rules


__all__ = [
    "GROUPS",
    "Matcher",
    "PermissionGroup",
    "PermissionRejected",
    "get_group",
    "group_ids",
    "groups_for",
    "rules_for",
    "stored_choices",
    "validate_choices",
]
