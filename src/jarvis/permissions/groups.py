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

R11 D16: six rows for the helpers (bills, bill_pay, household, nudges, outdoor, kitchen) after the
R4 block; `bill_pay` is the only irreversible one.

R11.1: two rows after them: `plans` (series_*, R2) and `pictures` (picture_*, R1).
R7 (docs/plans/r7-mobile.md D25): three rows right after Camera, before Vitals (R11.1 pins its two
between Kitchen and Maps, and Maps and YouTube stay last): `vision` (vision_*, R1), `watch`
(watch_* and sleep_*, R2: the typed sleep note is the one write) and `sos` (sos_status, R1: no
tool ever sends an SOS).
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
        "Pop-ups on your phone from the Google Calendar app. Your choice here also applies when "
        "the Calendar tools change or delete a reminder: Ask first asks, Never stops them. A "
        "reminder is deleted like an event, so Undo works for 30 days.",
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
    PermissionGroup(  # R1 D14: after the To-do rows
        "groceries",
        "Groceries",
        "Keep your grocery list",
        "A list called Groceries in Google Tasks (made the first time you add something). By "
        "voice, adding and ticking off items happens without a card; after JARVIS reads an "
        "email or a page it asks first.",
        R2,
        (_m("grocery_*"),),
    ),
    PermissionGroup(  # R1 D15
        "family_read",
        "Family",
        "Look at family calendars",
        "Only calendars your family shared with you and you added in Integrations. Their event "
        "titles are their words, never instructions.",
        R1,
        (_m("family_*", R1),),
    ),
    PermissionGroup(  # R1 D15: adding is irreversible (they see it, Google may email them)
        "family_change",
        "Family",
        "Add events to a family member's calendar",
        "They see it, and Google may email them. " + UNDO_HINT,
        R3,
        _r3("family_*"),
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
    # R2 D7 / D10 / D11: the vault, notes and things rows (after Drive, before Maps). None is
    # irreversible: deletes keep a copy in Recently deleted for 30 days.
    PermissionGroup(
        "vault_read",
        "Vault",
        "Look at your vault list",
        "Document types, whose they are, the last 4 characters and dates \u2014 never the files "
        "or full numbers. Off on Telegram unless you switch it on.",
        R1,
        (_m("vault_*", R1),),
    ),
    PermissionGroup(
        "vault_change",
        "Vault",
        "Change vault dates",
        "Expiry and issue dates you tell JARVIS. Files are added and removed only in the Vault "
        "panel.",
        R2,
        (_m("vault_*", R2),),
    ),
    PermissionGroup(
        "notes_read",
        "Notes",
        "Search and read your notes and links",
        "Text from saved web pages is treated as information, never instructions.",
        R1,
        (_m("kb_*", R1),),
    ),
    PermissionGroup(
        "notes_change",
        "Notes",
        "Save, change and delete notes and links",
        "Deleted notes stay in Recently deleted for 30 days.",
        R2,
        (_m("kb_*", R2),),
    ),
    PermissionGroup(
        "belongings",
        "Things",
        "Remember where you keep things",
        "Where you put your passport, keys or papers. By voice it saves without a card unless "
        "JARVIS just read an email or a page. Off on Telegram unless you switch it on.",
        R2,
        (_m("belongings_*"),),
    ),
    # R3 (docs/plans/r3-home-camera.md "New tools"): the home and camera rows (after Things,
    # before Maps). Disarming and locks, gates, alarms and heaters are irreversible: Ask first or
    # Never only, and the disarm itself also needs the owner's passkey (purpose home_disarm).
    PermissionGroup(
        "home_read",
        "Home",
        "See your home's status and devices",
        "Only while your home laptop is on. Device names come from the devices and are treated "
        "as information.",
        R1,
        (_m("home_*", R1),),
    ),
    PermissionGroup(
        "home_control",
        "Home",
        "Switch lights, fans and other everyday devices",
        "Only devices you exposed and marked Everyday in Integrations -> Home.",
        R2,
        (_m("home_control", R2),),
    ),
    PermissionGroup(
        "home_arm",
        "Home",
        "Arm the burglar alert",
        "By voice it arms without a card unless JARVIS just read an email or a page. Disarming "
        "always asks, in the console.",
        R2,
        (_m("home_arm"),),
    ),
    PermissionGroup(
        "home_secure",
        "Home",
        "Disarm, and control locks, gates, alarms and heaters",
        "JARVIS always asks first in the console, with your passkey if you set one up \u2014 or "
        "never does it.",
        R3,
        _r3("home_*"),
    ),
    PermissionGroup(
        "camera",
        "Camera",
        "Search camera history and say who it recognised",
        "Times and places only \u2014 JARVIS never sees pictures. Off on Telegram unless you "
        "switch it on.",
        R1,
        (_m("camera_*"), _m("faces_*")),
    ),
    # R7 (docs/plans/r7-mobile.md D12, D18, D19): the camera results he kept, his watch and sleep,
    # and the SOS set-up. Sending an SOS is never a tool (his hold and countdown confirm it).
    PermissionGroup(
        "vision",
        "Camera results",
        "Read the camera results you kept",
        "Numbers, labels and read text you pressed Keep on. JARVIS never sees a camera frame.",
        R1,
        (_m("vision_*", R1),),
    ),
    PermissionGroup(
        "watch",
        "Watch and sleep",
        "Your steps, heart rate and sleep, and a sleep time you type",
        "Daily sums from your watch or phone through Health Connect, kept encrypted. Estimates, "
        "never a diagnosis.",
        R2,
        (_m("watch_*", R1, R2), _m("sleep_*", R1, R2)),
    ),
    PermissionGroup(
        "sos",
        "Emergency SOS",
        "See your SOS set-up",
        "Who your emergency contacts are and when an SOS was last sent. JARVIS can never send "
        "one: only your hold and countdown do.",
        R1,
        (_m("sos_status", R1),),
    ),
    # R4 (docs/plans/r4-vitals-health-people.md "New tools"): vitals, self-health, people research
    # and the own-account connectors (after Camera, before Maps — Maps and YouTube stay last). None
    # is irreversible: the only "delete" is a tracked-key record, reversible metadata (re-add it),
    # so vitals change stays R2.
    PermissionGroup(
        "vitals",
        "Vitals",
        "See your keys, quotas, bills and limits",
        "Usage, limits, reset and expiry for everything JARVIS uses, and this month's spend. "
        "Read only.",
        R1,
        (_m("vitals_*", R1),),
    ),
    PermissionGroup(
        "vitals_change",
        "Vitals",
        "Add, edit and remove the keys you track",
        "The limit and expiry you type for a key. Removing a tracked key is reversible "
        "(re-add it).",
        R2,
        (_m("vitals_*", R2),),
    ),
    PermissionGroup(
        "systems",
        "Systems check",
        "Check JARVIS's own health",
        "Pings every connection and reads the result aloud. Read only, and it works with the AI "
        "switched off.",
        R1,
        (_m("systems_*"), _m("health_*", R1)),
    ),
    PermissionGroup(
        "people",
        "People research",
        "Research a person and open their public profiles",
        "Public figures and work due-diligence from public sources. JARVIS opens profiles in your "
        "browser for you to read; it never gathers a private person's private accounts.",
        R1,
        (_m("people_*"), _m("research_*")),
    ),
    PermissionGroup(
        "connectors",
        "Connectors",
        "Connect your own GitHub and Google Photos",
        "Reads your own GitHub (repos, activity) and the photos you pick in Google Photos. Your "
        "GitHub token is kept encrypted, never shown. Read only.",
        R1,
        (_m("connect_*"), _m("github_*"), _m("photos_*")),
    ),
    # R11 D16 (docs/plans/r11-free-helpers.md): the free proactive helpers, after the R4 block and
    # before Maps / YouTube. Only `bill_pay` is irreversible: getting a UPI payment ready (and
    # setting a payee's UPI ID) always asks, in the console, with the passkey when one is in force.
    # Birthdays are `contacts_birthdays` (the Contacts row); the kitchen's calendar blocks are
    # `calendar_kitchen_blocks` (the "Add and change your events" row, always a card).
    PermissionGroup(
        "bills",
        "Bills",
        "See and keep your bills and due dates",
        "Your bills, amounts, due dates and reminders, kept encrypted. JARVIS never pays: it only "
        "gets a payment ready for you.",
        R2,
        (_m("bill_*", R1, R2),),
    ),
    PermissionGroup(
        "bill_pay",
        "Bills",
        "Get a bill payment ready for your UPI PIN",
        "A UPI link and QR you open in your own UPI app and confirm with your PIN; setting a "
        "payee's UPI ID too. " + UNDO_HINT,
        R3,
        _r3("bill_*"),
    ),
    PermissionGroup(
        "household",
        "Home helpers",
        "Chores, home upkeep and your free-time list",
        "The chores rota, the upkeep schedule and the ideas you keep for free time. Reminders go "
        "only to you.",
        R2,
        (_m("chore_*"), _m("maint_*"), _m("freetime_*")),
    ),
    PermissionGroup(
        "nudges",
        "Nudges",
        "Nudges and your top priority",
        "Stand up, drink water, a planned walk that didn't happen, what is pending and your top "
        "priority, within the limits you set. Snooze or stop any of them.",
        R2,
        (_m("nudge_*"), _m("focus_*"), _m("pending_*")),
    ),
    PermissionGroup(
        "outdoor",
        "Weather and alerts",
        "Weather, disaster alerts and breach notices for your area",
        "Your district goes to the weather service; disaster warnings come from the government's "
        "SACHET feed; breach notices are read from your own mail.",
        R2,
        (_m("weather_*"), _m("disaster_*"), _m("breach_*")),
    ),
    PermissionGroup(
        "kitchen",
        "Kitchen",
        "Pantry, recipes, nutrition and grocery spend",
        "What you have, recipe ideas (from the AI, at the cost of a normal reply), rough "
        "nutrition and what your grocery receipts add up to.",
        R2,
        (
            _m("pantry_*"),
            _m("recipe_*"),
            _m("nutrition_*"),
            _m("spend_*"),
            _m("kitchen_*"),
        ),
    ),
    # R11.1 (docs/plans/r11-1-observations.md D7, D17): a study plan or other series of calendar
    # sessions JARVIS follows up, and research on a picture the owner attaches. The batch of
    # events itself is `calendar_create_events` (the "Add and change your events" row) and the
    # inbox summary `gmail_inbox_summary` (the "Search and read email" row).
    PermissionGroup(
        "plans",
        "Calendar plans",
        "Follow a study plan or other series of sessions",
        "JARVIS asks whether each session happened and proposes new dates for skipped ones. "
        "Moving sessions in your calendar still asks first.",
        R2,
        (_m("series_*"),),
    ),
    PermissionGroup(
        "pictures",
        "Pictures",
        "Research a picture you attach",
        "Objects, products, places, text and logos, with a web search. JARVIS never identifies "
        "a person from a picture.",
        R1,
        (_m("picture_*"),),
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
