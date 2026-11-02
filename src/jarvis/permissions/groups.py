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

Slice 11 D5: deleting the owner's own events and to-dos is undo-able (Recently deleted, 30 days)
and so R2, with an Allow default (the owner's "all rights"). Every irreversible group matches ONLY
irreversible calls (`_r3`), so an R2 delete never lands in an Ask-first R3 row; those rows keep
their ids (`calendar_delete`, `todo_delete`) so stored choices carry over.

Slice 11 fix HIGH-1: an undo-able delete has its OWN R2 row (`calendar_remove`, `todo_remove`);
the "change" rows never match a delete tool (`Matcher.exclude`). Before the split every delete was
in the R3 row, so an owner's earlier "Never" there meant "never delete": until the owner sets the
new row, it reads as Never too (`INHERITS`, applied by `stored_choices` and `rules_for`). A write
pins the new rows (`pinned`): from then on each row means only what it says. A restore
(`deleted_restore`) is in both change rows — strictest wins; `deleted_list` is a calendar read.

Slice 12 D8: one R1 row per integration — Contacts and WhatsApp drafts after the Email rows (the
people JARVIS writes to), Drive after Documents, then Maps and YouTube. Each matches its whole
tool family at any risk, so "Never" switches every tool of it off (a later write tool in the
family is at least as strict as today: an R3 call still always asks). A WhatsApp draft by NAME
also obeys the Contacts row (the look-up names `contacts_search`, `Preview.also`): Never there
refuses it, Ask first makes it a card (review S1).
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
    exclude: tuple[str, ...] = ()  # tool names the pattern covers but another row decides


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
            except_tools=list(m.exclude),
        )

    def rules(self, effect: Effect) -> list[PolicyRule]:
        if effect is Effect.ALLOW and self.irreversible:
            return []  # never a standing allow for something that can't be undone
        return [self._rule(m, effect) for m in self.matchers]


def _m(pattern: str, *risks: ActionRisk, exclude: tuple[str, ...] = ()) -> Matcher:
    return Matcher(pattern, frozenset(risks) if risks else None, exclude)


def _r3(*patterns: str) -> tuple[Matcher, ...]:
    """An irreversible group's matchers: irreversible calls only (slice 11 D5)."""
    return tuple(_m(p, R3) for p in patterns)


UNDO_HINT = "Can't be undone, so JARVIS always asks first — or never does it."
EVENT_DELETE, TASK_DELETE = "calendar_delete_event", "task_delete"
RESTORE, DELETED_LIST = "deleted_restore", "deleted_list"

GROUPS: tuple[PermissionGroup, ...] = (
    PermissionGroup(
        "calendar_read",
        "Calendar",
        "Look at your calendar",
        "Read events and find free time, and see what is in Recently deleted.",
        R1,
        (_m("calendar_*", R1), _m("get_calendar"), _m(DELETED_LIST)),
    ),
    PermissionGroup(
        "calendar_change",
        "Calendar",
        "Add and change your events",
        "Events only you are in. Also bringing back what was deleted (Recently deleted).",
        R2,
        (
            _m("calendar_create_event"),
            _m("calendar_update_event"),
            _m(RESTORE),
            _m("calendar_*", R2, exclude=(EVENT_DELETE,)),
        ),
    ),
    PermissionGroup(  # slice 11 fix HIGH-1: undo-able deletes have their own row
        "calendar_remove",
        "Calendar",
        "Delete your own events — kept 30 days in Recently deleted",
        "Events only you are on that don't repeat (a JARVIS reminder may). You can undo a "
        "delete for 30 days; it comes back as a new copy.",
        R2,
        (_m(EVENT_DELETE, R2),),
    ),
    PermissionGroup(
        "calendar_delete",
        "Calendar",
        "Invite people, and change or delete events that can't be undone",
        "Shared, repeating or special events, and ones you don't organise: Google emails the "
        "other people, or a delete can't be fully undone. " + UNDO_HINT,
        R3,
        _r3("calendar_*"),
    ),
    PermissionGroup(  # slice 11 B (D4/D5): its own row, after the Calendar rows
        "reminders",
        "Reminders",
        "Set, change and delete reminders",
        "Pop-ups on your phone from the Google Calendar app. Never also stops the Calendar "
        "tools changing or deleting a reminder. A reminder is deleted like an event, so Undo "
        "works for 30 days.",
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
        _r3("gmail_send", "send_message", "gmail_*"),
    ),
    PermissionGroup(  # slice 12 D8 (D5)
        "contacts",
        "Contacts",
        "Look up your contacts",
        "Names, phone numbers and email addresses from Google Contacts, read only — after you "
        "press Grant next to Contacts in Integrations. What JARVIS looks up is kept only in that "
        "conversation and deleted with it.",
        R1,
        (_m("contacts_*"),),
    ),
    PermissionGroup(  # slice 12 D8 (D6)
        "whatsapp",
        "WhatsApp",
        "Write WhatsApp drafts",
        "JARVIS writes the message; you open it in WhatsApp and press Send yourself. Nothing is "
        "sent by JARVIS.",
        R1,
        (_m("whatsapp_*"),),
    ),
    PermissionGroup(
        "todo_change",
        "To-do list",
        "Read and change your to-dos",
        "Add, edit and tick off to-dos, and bring back deleted ones (Recently deleted).",
        R2,
        (
            _m("tasks_*", exclude=(TASK_DELETE,)),
            _m("task_*", exclude=(TASK_DELETE,)),
            _m("list_tasks"),
            _m("create_reminder"),
            _m(RESTORE),
        ),
    ),
    PermissionGroup(  # slice 11 fix HIGH-1: undo-able deletes have their own row
        "todo_remove",
        "To-do list",
        "Delete your own to-dos — kept 30 days",
        "Kept in Recently deleted with their subtasks, so you can undo a delete for 30 days.",
        R2,
        (_m(TASK_DELETE, R2),),
    ),
    PermissionGroup(
        "todo_delete",
        "To-do list",
        "Delete to-dos that can't be undone",
        "Assigned from Docs or Chat (deleting one also deletes it there, for other people), or "
        "with subtasks JARVIS can't all keep. " + UNDO_HINT,
        R3,
        _r3("task_*", "tasks_*"),
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
        _r3("memory_forget"),
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
    PermissionGroup(  # slice 12 D8 (D1)
        "drive",
        "Drive",
        "Read your chosen Drive folders",
        "Only folders you shared with JARVIS and ticked Use in Integrations. Read only: JARVIS "
        "can't change, add or delete files there.",
        R1,
        (_m("drive_*"),),
    ),
    PermissionGroup(  # slice 12 D8 (D3)
        "maps",
        "Maps",
        "Search places and travel times",
        "Your search words, and the start and end of a route, go to Google Maps.",
        R1,
        (_m("maps_*"),),
    ),
    PermissionGroup(  # slice 12 D8 (D4)
        "youtube",
        "YouTube",
        "Search YouTube and read your playlists",
        "Search words go to YouTube. Your own playlists only after you press Grant in "
        "Integrations. Nothing plays until you press Play.",
        R1,
        (_m("youtube_*"),),
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


# slice 11 fix HIGH-1: new row → the row its calls were in before the split. A stored Never on
# the old row reads as Never on the new one until the owner sets the new one (or a write pins it).
INHERITS: dict[str, str] = {"calendar_remove": "calendar_delete", "todo_remove": "todo_delete"}


def _inherit(choices: Mapping[str, Effect]) -> dict[str, Effect]:
    out = dict(choices)
    for new, old in INHERITS.items():
        if new not in out and out.get(old) is Effect.DENY:
            out[new] = Effect.DENY
    return out


def _parsed(raw: object) -> dict[str, Effect]:
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


def stored_choices(raw: object) -> dict[str, Effect]:
    """Choices read from storage, field by field: an unknown group, an unknown effect or an
    Allow on an irreversible group (hand-edited) is dropped, i.e. reads as the default. A new
    delete row nobody set reads as Never when its old row is Never (`INHERITS`)."""
    return _inherit(_parsed(raw))


def inherited_ids(raw: object) -> set[str]:
    """The rows that read as Never only because their old row is Never (the view says so)."""
    return set(stored_choices(raw)) - set(_parsed(raw))


def pinned(choices: Mapping[str, Effect]) -> dict[str, Effect]:
    """What a write stores: the new delete rows explicitly (their current value, the default
    when unset), so a Never set on an old row later means only what that row says."""
    out = _inherit(choices)
    for new in INHERITS:
        out.setdefault(new, _BY_ID[new].default)
    return out


def rules_for(choices: Mapping[str, Effect]) -> list[PolicyRule]:
    """Policy rules for the owner's choices. A choice equal to the default adds nothing."""
    rules: list[PolicyRule] = []
    for gid, effect in _inherit(choices).items():
        group = _BY_ID.get(gid)
        if group is None or effect is group.default:
            continue
        rules.extend(group.rules(effect))
    return rules


__all__ = [
    "GROUPS",
    "INHERITS",
    "Matcher",
    "PermissionGroup",
    "PermissionRejected",
    "get_group",
    "group_ids",
    "groups_for",
    "inherited_ids",
    "pinned",
    "rules_for",
    "stored_choices",
    "validate_choices",
]
