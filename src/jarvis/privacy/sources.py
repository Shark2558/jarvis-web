# src/jarvis/privacy/sources.py
"""The existing categories of the privacy dashboard (R2 D14), through public methods only.

Each category is a `CallbackSource`: a fixed description (`Spec`) plus three small async
functions - look (count and the fingerprint basis), export (optional) and delete (optional) - built
from the feature's own service or store. Nothing here reads a Firestore path directly. A function
that raises makes the registry show "Couldn't check right now" for that row only.

Exports are built from safe fields (never a token, key or the encrypted blob) and `scrub` runs over
them again in the service.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from jarvis.billing.meter import UsageMeter
from jarvis.brief.models import BriefSettings
from jarvis.brief.store import BriefStore
from jarvis.core.guardrails import ConfirmationGate
from jarvis.documents.service import DocumentService, forget_files
from jarvis.drive.roots import RootsStore
from jarvis.drive.roots import describe as describe_roots
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import TokenStore
from jarvis.logging import get_logger
from jarvis.permissions.service import PermissionsService
from jarvis.places.store import MapsPlaces
from jarvis.privacy.export import fingerprint
from jarvis.privacy.ports import CategoryView, DeleteClass
from jarvis.recall.service import MemoryService
from jarvis.storage.sessions import DocSessionStore
from jarvis.tools.audit import AuditTrail
from jarvis.tools.task_marks import OutsideTasks
from jarvis.undo.models import DeletedView
from jarvis.undo.service import PurgeFailed, UndoBin

log = get_logger(__name__)

SEC_MEMORY = "What JARVIS remembers"
SEC_CONNECT = "Connections"
SEC_ACTIVITY = "Activity and messages"
SEC_SAFETY = "Settings and safety"
SEC_FACES = "Faces"

CONVERSATIONS_LISTED = 1000
CONVERSATIONS_EXPORTED = 200
DELETE_PASSES = 5
BRIEF_DAYS = 8
AUDIT_LISTED = 500
GOOGLE_ENC = "Firestore, Google-encrypted"
OURS_ENC = "Firestore, encrypted by JARVIS"


@dataclass(frozen=True)
class Spec:
    id: str
    section: str
    label: str
    what: str
    unit: str
    retention: str
    where: str
    encrypted_by_jarvis: bool = False
    delete: DeleteClass = "none"
    recoverable: bool = False
    note: str = ""


@dataclass(frozen=True)
class Look:
    """What a category holds right now: `basis` is anything that changes when the data does."""

    count: int | None
    basis: Any = ()
    note: str = ""
    size_hint: str | None = None
    deletable: bool = True  # False: nothing to delete now (the class falls back to none)
    delete_count: int | None = None  # what a delete removes, when that is less than `count`


LookFn = Callable[[str], Awaitable[Look]]
ExportFn = Callable[[str], Awaitable[dict[str, Any]]]
DeleteFn = Callable[[str], Awaitable[int]]


@dataclass
class CallbackSource:
    spec: Spec
    look: LookFn
    export_fn: ExportFn | None = None
    delete_fn: DeleteFn | None = None
    id: str = field(init=False)
    section: str = field(init=False)
    label: str = field(init=False)

    def __post_init__(self) -> None:
        self.id, self.section, self.label = self.spec.id, self.spec.section, self.spec.label

    async def describe(self, uid: str) -> CategoryView:
        s, seen = self.spec, await self.look(uid)
        can_delete = self.delete_fn is not None and seen.deletable and s.delete != "none"
        return CategoryView(
            id=s.id,
            section=s.section,
            label=s.label,
            what=s.what,
            count=seen.count,
            unit=s.unit,
            retention=s.retention,
            where=s.where,
            size_hint=seen.size_hint,
            encrypted_by_jarvis=s.encrypted_by_jarvis,
            export=self.export_fn is not None,
            delete=s.delete if can_delete else "none",
            recoverable=s.recoverable,
            note=seen.note or s.note,
            rev=fingerprint(s.id, seen.count, seen.basis),
            delete_count=seen.count if seen.delete_count is None else seen.delete_count,
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None if self.export_fn is None else await self.export_fn(uid)

    async def delete(self, uid: str) -> int:
        if self.delete_fn is None:
            raise PermissionError("This category can't be deleted here.")
        return await self.delete_fn(uid)


def _iso(d: datetime | None) -> str | None:
    return None if d is None else d.isoformat()


# ---- memory and conversations -----------------------------------------------------------------


def memory_source(memory: MemoryService) -> CallbackSource:
    async def look(uid: str) -> Look:
        v = await memory.view(uid)
        basis = ([f.id for f in v.facts], v.profile.model_dump_json())
        return Look(
            len(v.facts), basis, deletable=bool(v.facts) or any(v.profile.model_dump().values())
        )

    async def delete(uid: str) -> int:
        n = (await memory.view(uid)).counts.active
        await memory.forget_all(uid)
        return n

    return CallbackSource(
        Spec(
            "memory",
            SEC_MEMORY,
            "Memory",
            "Facts JARVIS remembers about you, and the About you notes.",
            "facts",
            "Until you delete them; a replaced fact is kept 30 days.",
            GOOGLE_ENC,
            delete="passkey",
            note="Your settings for memory are kept.",
        ),
        look,
        memory.export,
        delete,
    )


CONVERSATION_CAVEAT = (
    "What a tool looked up inside a conversation (a note's text, where something is kept, "
    "document dates) is kept with that conversation, under Google's encryption rather than "
    "JARVIS's, until the conversation is deleted."
)


def conversations_source(
    store: DocSessionStore, documents: DocumentService | None = None
) -> CallbackSource:
    async def look(uid: str) -> Look:
        rows = await store.list_for_user(uid, limit=CONVERSATIONS_LISTED)
        more = len(rows) >= CONVERSATIONS_LISTED
        return Look(
            len(rows),
            [(r.id, r.updated_at.isoformat()) for r in rows],
            note=CONVERSATION_CAVEAT + (" There are at least 1,000." if more else ""),
        )

    async def export(uid: str) -> dict[str, Any]:
        out: list[dict[str, Any]] = []
        for row in (await store.list_for_user(uid, limit=CONVERSATIONS_EXPORTED))[
            :CONVERSATIONS_EXPORTED
        ]:
            session = await store.get(row.id)
            if session is None or session.user_id != uid:
                continue
            out.append(
                {
                    "id": row.id,
                    "title": row.title,
                    "updated_at": row.updated_at.isoformat(),
                    "turns": [
                        {"role": t.role, "content": t.content, "at": t.created_at.isoformat()}
                        for t in session.turns
                    ],
                }
            )
        return {"newest": CONVERSATIONS_EXPORTED, "conversations": out}

    async def delete(uid: str) -> int:
        """Counts only what really went. A conversation that fails is logged and skipped (the
        rest still go); the service then reads what is left."""
        gone, failed = 0, set()
        for _ in range(DELETE_PASSES):
            rows = [r for r in await store.list_for_user(uid, limit=CONVERSATIONS_LISTED)]
            rows = [r for r in rows if r.id not in failed]
            removed = 0
            for r in rows:
                try:
                    await forget_files(documents, uid, r.id)  # its files go first
                    if await store.delete(r.id):
                        removed += 1
                    else:
                        failed.add(r.id)
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "a conversation could not be deleted", extra={"error": type(exc).__name__}
                    )
                    failed.add(r.id)
            gone += removed
            if not rows or removed == 0:
                break
        return gone

    return CallbackSource(
        Spec(
            "conversations",
            SEC_MEMORY,
            "Conversations",
            "Your chats with JARVIS, the files you attached, and what tools looked up in them.",
            "conversations",
            "Until you delete them.",
            GOOGLE_ENC,
            delete="passkey",
        ),
        look,
        export,
        delete,
    )


def deleted_source(undo: UndoBin) -> CallbackSource:
    async def look(uid: str) -> Look:
        items = await undo.recent(uid)
        return Look(len(items), [i.id for i in items], deletable=bool(items))

    async def export(uid: str) -> dict[str, Any]:
        return {
            "items": [DeletedView.of(i).model_dump(mode="json") for i in await undo.recent(uid)]
        }

    async def delete(uid: str) -> int:
        gone = 0
        for item in await undo.recent(uid):
            try:
                if await undo.purge(uid, item.id):
                    gone += 1
            except PurgeFailed:  # that one stays in the list; the rest still go
                log.warning(
                    "a recently deleted item could not be removed", extra={"kind": item.kind}
                )
        return gone

    return CallbackSource(
        Spec(
            "deleted",
            SEC_MEMORY,
            "Recently deleted",
            "Things you deleted that can still be brought back.",
            "items",
            "30 days.",
            "Firestore",
            delete="passkey",
            recoverable=True,
            note="Empty now means they can no longer be brought back.",
        ),
        look,
        export,
        delete,
    )


# ---- connections ------------------------------------------------------------------------------


def google_source(tokens: TokenStore, google: GoogleConnector | None = None) -> CallbackSource:
    async def look(uid: str) -> Look:
        t = await tokens.get(uid)
        return Look(
            0 if t is None else 1, [t is not None and t.needs_reconnect], deletable=t is not None
        )

    async def export(uid: str) -> dict[str, Any]:
        t = await tokens.get(uid)  # status only: the tokens themselves are never exported
        if t is None:
            return {"connected": False}
        return {
            "connected": True,
            "account": t.email,
            "scopes": list(t.scopes),
            "needs_reconnect": t.needs_reconnect,
        }

    async def delete(uid: str) -> int:
        had = await tokens.get(uid) is not None
        if google is not None:
            await google.disconnect(uid)
        else:
            await tokens.delete(uid)
        return 1 if had else 0

    return CallbackSource(
        Spec(
            "google",
            SEC_CONNECT,
            "Google connection",
            "Your Google sign-in for Gmail, Calendar, Tasks and Drive.",
            "connection",
            "Until you disconnect.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="simple",
            recoverable=True,
            note="Disconnecting also asks Google to cancel the access. You can connect again.",
        ),
        look,
        export,
        delete,
    )


def drive_source(roots: RootsStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        r = await roots.load(uid)
        return Look(len(r), [x.id for x in r], deletable=bool(r))

    async def export(uid: str) -> dict[str, Any]:
        return {"folders": describe_roots(await roots.load(uid))}

    async def delete(uid: str) -> int:
        current = await roots.load(uid)
        for r in current:
            await roots.remove(uid, r.id)
        return len(current)

    return CallbackSource(
        Spec(
            "drive",
            SEC_CONNECT,
            "Google Drive folders",
            "The Drive folders you chose for JARVIS to read.",
            "folders",
            "Until you switch them off.",
            "Firestore",
            delete="simple",
            recoverable=True,
            note="Your files stay in Drive.",
        ),
        look,
        export,
        delete,
    )


def places_source(places: MapsPlaces) -> CallbackSource:
    async def look(uid: str) -> Look:
        home, work = await places.get(uid)
        n = sum(1 for p in (home, work) if p)
        return Look(n, [home, work], deletable=n > 0)

    async def export(uid: str) -> dict[str, Any]:
        home, work = await places.get(uid)
        return {"home": home, "work": work}

    async def delete(uid: str) -> int:
        home, work = await places.get(uid)
        await places.put(uid, home=None, work=None)
        return sum(1 for p in (home, work) if p)

    return CallbackSource(
        Spec(
            "places",
            SEC_CONNECT,
            "Home and Work",
            "The two places you saved for travel times.",
            "places",
            "Until you clear them.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="simple",
            recoverable=True,
        ),
        look,
        export,
        delete,
    )


# ---- records ----------------------------------------------------------------------------------


def briefs_source(store: BriefStore, today: Callable[[], date]) -> CallbackSource:
    async def recent(uid: str) -> list[Any]:
        days = [(today() - timedelta(days=i)).isoformat() for i in range(BRIEF_DAYS)]
        found = [await store.get_brief(uid, d) for d in days]
        return [b for b in found if b is not None]

    async def look(uid: str) -> Look:
        b = await recent(uid)
        return Look(len(b), [(x.date, x.status) for x in b], deletable=bool(b))

    async def export(uid: str) -> dict[str, Any]:
        return {"briefs": [b.model_dump(mode="json") for b in await recent(uid)]}

    async def delete(uid: str) -> int:
        return await store.prune(uid, keep_from=date.max)

    return CallbackSource(
        Spec(
            "briefs",
            SEC_ACTIVITY,
            "Morning briefs",
            "The morning briefs JARVIS made for you.",
            "briefs",
            "7 days.",
            "Firestore",
            delete="passkey",
        ),
        look,
        export,
        delete,
    )


def settings_source(briefs: BriefStore, memory: MemoryService | None = None) -> CallbackSource:
    """The brief's choices; resetting them is the only delete (voice and permissions are changed
    in their own panels - a privacy click must never lower a protection)."""

    async def changed(uid: str) -> dict[str, Any]:
        cur = (await briefs.get_settings(uid)).model_dump(mode="json", exclude={"updated_at", "tz"})
        base = BriefSettings().model_dump(mode="json", exclude={"updated_at", "tz"})
        return {k: v for k, v in cur.items() if base.get(k) != v}

    async def look(uid: str) -> Look:
        diff = await changed(uid)
        return Look(len(diff), diff, deletable=bool(diff))

    async def export(uid: str) -> dict[str, Any]:
        out: dict[str, Any] = {"brief": (await briefs.get_settings(uid)).model_dump(mode="json")}
        if memory is not None:
            out["memory"] = (await memory.view(uid)).settings.model_dump(mode="json")
        return out

    async def delete(uid: str) -> int:
        n = len(await changed(uid))
        await briefs.update_settings(uid, lambda _cur: BriefSettings())
        return n

    return CallbackSource(
        Spec(
            "settings",
            SEC_SAFETY,
            "Brief choices",
            "How your morning brief is set up.",
            "changed choices",
            "Until you change them.",
            "Firestore",
            delete="simple",
            recoverable=True,
            note=(
                "Resets the morning brief only. Voice and permission choices "
                "are changed in their own panels."
            ),
        ),
        look,
        export,
        delete,
    )


def _month_row(m: Any) -> dict[str, Any]:
    return {"month": m.month, "rupees": round(m.inr_total, 2), "calls": m.calls}


def spend_source(meter: UsageMeter, clock: Callable[[], datetime]) -> CallbackSource:
    async def split(uid: str) -> tuple[list[Any], list[Any]]:
        now_month = meter.month_of(clock())
        rows = await meter.months(uid)
        return [m for m in rows if m.month < now_month], [m for m in rows if m.month >= now_month]

    async def look(uid: str) -> Look:
        past, current = await split(uid)
        return Look(
            len(past) + len(current),
            [(m.month, m.calls) for m in [*past, *current]],
            deletable=bool(past),
            delete_count=len(past),
        )

    async def export(uid: str) -> dict[str, Any]:
        past, current = await split(uid)
        return {"months": [_month_row(m) for m in sorted([*past, *current], key=lambda m: m.month)]}

    async def delete(uid: str) -> int:
        return await meter.forget_before(uid, meter.month_of(clock()))

    return CallbackSource(
        Spec(
            "spend",
            SEC_ACTIVITY,
            "Spend per month",
            "What JARVIS's AI use cost each month, in rupees.",
            "months",
            "Kept.",
            "Firestore",
            delete="passkey",
            note="This month stays: your spending limit needs it.",
        ),
        look,
        export,
        delete,
    )


def approvals_source(gate: ConfirmationGate) -> CallbackSource:
    async def mine(uid: str) -> list[Any]:
        return [
            a
            for a in await gate.pending()
            if (a.scope or "") == uid or (a.scope or "").startswith(f"{uid}:")
        ]

    async def look(uid: str) -> Look:
        cards = await mine(uid)
        return Look(len(cards), [a.id for a in cards], deletable=bool(cards))

    async def export(uid: str) -> dict[str, Any]:
        return {
            "waiting": [
                {"tool": a.tool, "risk": str(a.risk), "since": a.created_at.isoformat()}
                for a in await mine(uid)
            ]
        }

    async def delete(uid: str) -> int:
        gone = 0
        for a in await mine(uid):
            if await gate.cancel(a.id):
                gone += 1
        return gone

    return CallbackSource(
        Spec(
            "approvals",
            SEC_ACTIVITY,
            "Approvals waiting",
            "Actions JARVIS asked you to approve and that are still waiting, with what each "
            "would do (a note's words, a place) as written.",
            "cards",
            "Until you decide, or 10 minutes.",
            "Firestore, not encrypted by JARVIS",
            delete="simple",
            # R2 review S4 / plan D13: you must see what you approve, so a card is kept as written
            note="A waiting card is kept as written, not encrypted by JARVIS, until you decide. "
            "Declining does nothing to your accounts.",
        ),
        look,
        export,
        delete,
    )


def passkeys_source(permissions: PermissionsService) -> CallbackSource:
    async def look(uid: str) -> Look:
        v = await permissions.view(uid)
        return Look(len(v.passkeys), [p.id for p in v.passkeys])

    async def export(uid: str) -> dict[str, Any]:
        v = await permissions.view(uid)
        return {"passkeys": [{"label": p.label, "added": p.created_at} for p in v.passkeys]}

    return CallbackSource(
        Spec(
            "passkeys",
            SEC_SAFETY,
            "Passkeys",
            "The passkeys that protect deletes and approvals.",
            "passkeys",
            "Until you remove them.",
            "Firestore",
            note="Managed in Approvals, then Permissions.",
        ),
        look,
        export,
    )


def audit_source(audit: AuditTrail) -> CallbackSource:
    async def look(uid: str) -> Look:
        tail = await audit.tail(AUDIT_LISTED)
        full = len(tail.entries) >= AUDIT_LISTED
        return Look(
            None if full else len(tail.entries),
            [e.seq for e in tail.entries[-3:]],
            note="At least 500 entries. " if full else "",
        )

    async def export(uid: str) -> dict[str, Any]:
        tail = await audit.tail(AUDIT_LISTED)
        rows = [
            {
                "seq": e.seq,
                "at": e.at.isoformat(),
                "agent": e.agent,
                "tool": e.tool,
                "risk": str(e.risk),
                "outcome": e.outcome,
            }
            for e in tail.entries
        ]
        return {"newest": AUDIT_LISTED, "entries": rows}

    return CallbackSource(
        Spec(
            "audit",
            SEC_SAFETY,
            "Audit trail",
            "A tamper-evident list of what JARVIS did: the tool and the time, never your words.",
            "entries",
            "Forever; it is append-only.",
            "Firestore",
            note="It is the security record, so it can't be deleted.",
        ),
        look,
        export,
    )


def marks_source(marks: OutsideTasks) -> CallbackSource:
    async def look(uid: str) -> Look:
        s = await marks.read(uid)
        if s is None:
            raise RuntimeError("marks unreadable")
        return Look(len(s.ids), [len(s.ids)])

    return CallbackSource(
        Spec(
            "marks",
            SEC_SAFETY,
            "Safety marks",
            "Marks on to-dos JARVIS wrote from other people's words.",
            "marks",
            "Until the item goes.",
            "Firestore",
            note="Deleting them would weaken protection, so they stay.",
        ),
        look,
    )


def counters_source() -> CallbackSource:
    async def look(uid: str) -> Look:
        return Look(None)

    return CallbackSource(
        Spec(
            "counters",
            SEC_SAFETY,
            "Free-allowance counters",
            "How much of the monthly free web, Maps and voice allowance is used.",
            "",
            "Per month.",
            "Firestore",
            note="Shared by the whole JARVIS, with no content of yours.",
        ),
        look,
    )


def faces_source() -> CallbackSource:
    async def look(uid: str) -> Look:
        return Look(0)

    return CallbackSource(
        Spec(
            "faces",
            SEC_FACES,
            "Faces",
            "Faces JARVIS could recognise at home.",
            "faces",
            "-",
            "-",
            note="Not built yet. Nothing is stored.",
        ),
        look,
    )


__all__ = [
    "CONVERSATION_CAVEAT",
    "CallbackSource",
    "Look",
    "Spec",
    "approvals_source",
    "audit_source",
    "briefs_source",
    "conversations_source",
    "counters_source",
    "deleted_source",
    "drive_source",
    "faces_source",
    "google_source",
    "marks_source",
    "memory_source",
    "passkeys_source",
    "places_source",
    "settings_source",
    "spend_source",
]
