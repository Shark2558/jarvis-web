# src/jarvis/wardrobe/ports.py
"""The plug-in contract of R13 (docs/plans/r13-wardrobe.md "The I0 seam list" 9, "Part split").

Four parts are built in parallel. Each owns a module whose `build(ctx: WardrobeContext) ->
WardrobePart` gets what it may use and hands back what the app wires for it; no part edits a
wiring file (`api/r13_wiring.py` leaves out a part that breaks this contract: "setup failed").

| Part      | Plan                      | Module                          | Routes under   |
|-----------|---------------------------|---------------------------------|----------------|
| `catalog` | A · INV-01-17, OPS-03, 06 | `jarvis.wardrobe.catalog.part`  | `/v1/wardrobe` |
| `laundry` | B · LND-01-15, OPS-02     | `jarvis.wardrobe.laundry.part`  | `/v1/laundry`  |
| `styling` | C · STY-01-17, LND-16, 04 | `jarvis.wardrobe.styling.part`  | `/v1/outfits`  |
| `phone`   | D · OPS-01, UI, No-AI     | `jarvis.wardrobe.phone.part`    | none           |
| `tryon`   | R13.1 A · try-on data     | `jarvis.wardrobe.tryon.part`    | `/v1/tryon`    |
| `seeme`   | R13.1 C · See it on me    | `jarvis.wardrobe.seeme.part`    | `/v1/seeme`    |

R13.1 (docs/plans/r13-1-try-on.md seam 3) adds `tryon` and `seeme`: no tool, their Privacy rows
on `privacy` only (section "Try-on", `PRIVACY_OWNER`), never `data` (R13's Wardrobe rows fail
closed on a source they don't know, M4), C's daily `seeme_daily`, A's `tryon_looks` and C's
`seeme` services, and `WardrobeContext.tryon` (the try-on provider, built late; L12).

- `WardrobePart`: its tools (names inside its `TOOL_FAMILIES` and `TOOL_OWNER`), its 5-minute
  jobs (`clock_jobs`: only C's `outfit_clock`) and morning-tick jobs (`daily_jobs`: A's
  `wardrobe_sweep`, B's `laundry_daily`), its privacy rows (`privacy`: `PrivacySource`s, built by
  D over each part's `WardrobeData`, or a part's own), its `ChangeObserver`s, the services only it
  may offer (`SERVICE_OWNER`) and one plain ready word.
- Services the wiring joins: `store` (A: the one `WardrobeStore`), `photos` (A: `PhotoVault`),
  `bin` (A: Recently deleted's restorer and purger for `wardrobe_item`), `review_writer` (B: a
  `ReviewWriter`, bound into A's store so a hold is written with its entry, D4.4), `refresh` (C:
  its plan refresh, a `ChangeObserver`), `phrases` (D: No-AI routers, installed FIRST).
- `WardrobeContext`: the settings, the documents, the keyring, the audit chain, `now()` (UTC; the
  ONLY clock under `wardrobe/`, D15), `zone(uid)` (his zone: the brief store's, else
  `user_timezone`), a LATE `state(name)`, the notifier, the governed reads (`BackgroundReads`),
  R11's `OutsideStore` (late, for C's weather) and A's store (late, for B and C).

The store's contract (`WardrobeStore.transact`, plan D4.4): `fn(view, tx) -> Commit` runs inside
A's transaction. `fn` may READ through `tx` (all reads first) and never writes: it returns the
events and B's own writes (`Commit.extra`). A then appends the events, re-folds each piece, asks
the bound `ReviewWriter` for the entries of every `ReviewNeeded` the fold returned (it may read
through `tx` too, still before any write), and writes the index, the log pages, `extra` and the
entries LAST, in one commit: a write that fails rolls all of it back. After the commit each
observer hears each changed piece once (never inside the transaction; one that raises is logged
and the others still hear it). `tests/test_r13_fold_conformance.py` holds every store to the fold.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Any, Literal, Protocol, get_args, runtime_checkable
from zoneinfo import ZoneInfo

from jarvis.storage.docs import DocTx, Op
from jarvis.wardrobe.model import Event, Piece, WardrobeView
from jarvis.wardrobe.states import EventKind, State

if TYPE_CHECKING:
    from jarvis.config import Settings
    from jarvis.keyring import Keyring
    from jarvis.llm.tryon import TryOnProvider
    from jarvis.notify.ports import Notifier
    from jarvis.privacy.ports import PrivacySource
    from jarvis.storage.docs import Docs
    from jarvis.ticks import TickJob
    from jarvis.tools.audit import AuditTrail
    from jarvis.tools.background import BackgroundReads
    from jarvis.tools.base import Tool

PartName = Literal["catalog", "laundry", "styling", "phone", "tryon", "seeme"]
PARTS: tuple[PartName, ...] = get_args(PartName)
NOT_BUILT = "not built yet"

# The 18 tools and their parts (plan "Tools"); every one through the gateway.
TOOL_OWNER: Mapping[str, PartName] = {
    **dict.fromkeys(
        (
            "wardrobe_find",
            "wardrobe_count",
            "wardrobe_add",
            "wardrobe_edit",
            "wardrobe_places",
            "wardrobe_merge",
            "wardrobe_retire",
            "wardrobe_remove",
        ),
        "catalog",
    ),
    **dict.fromkeys(
        ("laundry_status", "laundry_move", "laundry_review", "laundry_correct", "laundry_send_out"),
        "laundry",
    ),
    **dict.fromkeys(
        ("outfit_suggest", "outfit_plans", "outfit_plan", "outfit_prefs", "wear_log"), "styling"
    ),
}
TOOL_FAMILIES: Mapping[PartName, tuple[str, ...]] = {
    "catalog": ("wardrobe_*",),
    "laundry": ("laundry_*",),
    "styling": ("outfit_*", "wear_*"),
    "phone": (),
    "tryon": (),  # R13.1: no model-callable tool (plan "Tools: none new")
    "seeme": (),
}
READ_TOOLS = frozenset({"wardrobe_find", "wardrobe_count", "laundry_status"}) | {
    "outfit_suggest",
    "outfit_plans",
}
CARD_ALWAYS = frozenset({"wardrobe_merge", "wardrobe_retire"})  # `ask_when`, never Approve all
UNDOABLE = frozenset({"wardrobe_remove"})  # Recently deleted, kind `wardrobe_item`
SPOKEN_OK = frozenset({"laundry_move", "wear_log"})  # the gateway's `spoken_ok`
QUERY_TOOLS = frozenset({"laundry_move", "wear_log"})  # D10's one exception: also a `query`
NO_AI_TOOLS = frozenset(
    {"wardrobe_find", "wardrobe_count", "wardrobe_edit", "laundry_status", "laundry_move"}
) | {"outfit_suggest", "wear_log"}
MAX_RESULT_PIECES = 20  # a tool result lists at most 20 pieces

ROUTE_PREFIX: Mapping[PartName, tuple[str, ...]] = {
    "catalog": ("/v1/wardrobe",),
    "laundry": ("/v1/laundry",),
    "styling": ("/v1/outfits",),
    "phone": (),
    "tryon": ("/v1/tryon",),
    "seeme": ("/v1/seeme",),
}
R13_STATUS_ROUTE = "/v1/r13"  # every part's ready word (I0)
# Firestore collections (`{prefix}<name>/...`, flat ids, every document with `updated_at`); the
# guide's cards C69-C71 name every one. `wardrobe_told` is B's and C's: each key starts with its
# part's name (`laundry_...`, `styling_...`).
COLLECTIONS: Mapping[PartName, tuple[str, ...]] = {
    "catalog": ("wardrobe", "wardrobe_log", "wardrobe_photo", "wardrobe_fp", "wardrobe_restore"),
    "laundry": ("wardrobe_laundry", "wardrobe_review", "wardrobe_told"),
    "styling": ("wardrobe_plans", "wardrobe_cal", "wardrobe_outlook", "wardrobe_told"),
    "phone": (),
    "tryon": ("tryon",),  # R13.1 "Data model"; the guide's cards C72-C73 name every one
    "seeme": ("tryon_person", "tryon_consent", "tryon_picture", "tryon_spend"),
}
TOLD_KEY_PREFIX: Mapping[PartName, str] = {"laundry": "laundry_", "styling": "styling_"}
R13_JOB_NAMES: tuple[str, ...] = ("wardrobe_sweep", "laundry_daily", "outfit_clock", "seeme_daily")
JOB_OWNER: Mapping[str, PartName] = {
    "wardrobe_sweep": "catalog",  # from 04:00 local: forgotten wears, holds without an entry
    "laundry_daily": "laundry",  # overdue and short batches, the review queue's morning line
    "outfit_clock": "styling",  # the 5-minute clock: calendar, weather, the evening's alert
    "seeme_daily": "seeme",  # R13.1 D14: pictures past their time, old holds, the end-date notice
}
CLOCK_JOB_NAMES = frozenset({"outfit_clock"})
SERVICE_OWNER: Mapping[str, PartName] = {
    "store": "catalog",
    "photos": "catalog",
    "bin": "catalog",
    "review_writer": "laundry",
    "refresh": "styling",
    "phrases": "phone",
    "tryon_looks": "tryon",  # R13.1 A: looks, the fresh check, OPS-05's `erase_all`
    "seeme": "seeme",  # R13.1 C: his photo, consent, the cap, pictures; `erase` (tryon/ports.py)
}
# R13.1's Privacy rows (section "Try-on", D16) and the part that offers each; `tryon` and `seeme`
# offer them on `WardrobePart.privacy` and never `data` (M4: `NO_DATA_PARTS`).
PRIVACY_OWNER: Mapping[str, PartName] = {
    "tryon_figure": "tryon",
    "tryon_photo": "seeme",
    "tryon_pictures": "seeme",
    "tryon_spend": "seeme",
    "tryon_all": "tryon",
    "tryon_device": "tryon",
}
NO_DATA_PARTS: frozenset[PartName] = frozenset({"tryon", "seeme"})
# Who raises each R13 alert kind (D19): the outfit kinds C, the other two B.
KIND_OWNER: Mapping[str, PartName] = {
    "outfit_ready": "styling",
    "outfit_changed": "styling",
    "laundry_overdue": "laundry",
    "wardrobe_review": "laundry",
}
# What the fold makes of an event (computed on every fold, never written back into the log):
# applied; duplicate (a second record of the current state, D4.2); superseded (unverified and
# older than the newest verified state-setting event); conflict (the table refuses it: an entry,
# no hold); held (unverified and it would change availability: a hold and its entry); voided (a
# `corrected` event names it); known (a retry: its client id or id was already in the log).
Mark = Literal["applied", "duplicate", "superseded", "conflict", "held", "voided", "known"]
NeedKind = Literal["hold", "conflict", "pending_deposit", "stale", "rescan"]


class Refused(ValueError):  # noqa: N818 - a refusal in plain words, not a bug
    """A write the ledger refuses, in plain words (a time outside D4.1's window, an event for a
    piece that isn't in the index): nothing is written."""


def tool_allowed(part: PartName, tool: str) -> bool:
    owner = TOOL_OWNER.get(tool)
    in_family = any(fnmatchcase(tool, pattern) for pattern in TOOL_FAMILIES.get(part, ()))
    return in_family and owner == part


@dataclass(frozen=True)
class Commit:
    """What `fn` returns: the events to append, B's own writes (`extra`, written in the same
    commit), and A's index records to add or replace (`records`: Part A's tools only)."""

    events: tuple[Event, ...] = ()
    extra: tuple[Op, ...] = ()
    records: tuple[Piece, ...] = ()


@dataclass(frozen=True)
class ReviewNeeded:
    """An entry the fold asks for (a hold, a conflict, a pending deposit, a stale check, a rescan).
    B's `ReviewWriter` writes it in the SAME commit, so no hold lives without its entry."""

    kind: NeedKind
    piece: str | None
    event: str | None = None
    candidates: tuple[str, ...] = ()
    back_to: State | None = None
    reason: str = ""  # a fixed word ("unverified", "refused", "blind", ...), never his text


@dataclass(frozen=True)
class Committed:
    """The result of `transact` / `correct`: the events as stored (ids, settled times), each new
    event's mark, the entries asked for, the pieces whose state, place or wear changed, the fresh
    view and `already` (a write the fresh view already shows: "already done", plan M3)."""

    events: tuple[Event, ...]
    marks: Mapping[str, Mark]
    needed: tuple[ReviewNeeded, ...]
    changed: tuple[str, ...]
    view: WardrobeView
    already: bool = False


@dataclass(frozen=True)
class HistoryItem:
    event: Event
    mark: Mark


@dataclass(frozen=True)
class PieceChange:
    """What an observer hears once per changed piece after a commit (never inside it)."""

    uid: str
    piece: str
    kind: EventKind
    before: State | None
    after: State
    plan: str | None = None  # the wear's plan (C: wearing a piece for its plan is no change)


@runtime_checkable
class ChangeObserver(Protocol):
    async def changed(self, change: PieceChange) -> None: ...


@runtime_checkable
class ReviewWriter(Protocol):
    async def entries(
        self, uid: str, view: WardrobeView, tx: DocTx, needed: Sequence[ReviewNeeded]
    ) -> Sequence[Op]: ...


@runtime_checkable
class WardrobeStore(Protocol):
    async def view(self, uid: str) -> WardrobeView: ...

    async def transact(
        self, uid: str, fn: Callable[[WardrobeView, DocTx], Awaitable[Commit]]
    ) -> Committed: ...

    async def correct(
        self, uid: str, piece: str, event_id: str, *, note: str = ""
    ) -> Committed: ...

    async def history(
        self, uid: str, piece: str, *, view: WardrobeView | None = None
    ) -> tuple[HistoryItem, ...]: ...  # `view`: the index the caller holds (N pieces read it once)

    def bind(
        self,
        *,
        review_writer: ReviewWriter | None = None,
        observers: Sequence[ChangeObserver] = (),
    ) -> None: ...


@runtime_checkable
class PhotoVault(Protocol):
    """A's sealed photos and fingerprints (D9): D's door posts to its routes; a private piece
    never has either."""

    async def count(self, uid: str) -> int: ...

    async def delete_all(self, uid: str) -> int: ...

    async def get(self, uid: str, photo: str) -> bytes | None: ...  # R13.1: a crop for C's call


PrivacyRow = Literal["pieces", "history", "plans", "photos"]  # D20: a source's Privacy row


@runtime_checkable
class WardrobeData(Protocol):
    """One part's data for D's Privacy rows (D20): counts, a plain export, delete everything.
    `row` says which of the four server rows it belongs to (a source with none is refused)."""

    name: str
    row: PrivacyRow

    async def count(self, uid: str) -> int: ...

    async def export(self, uid: str) -> dict[str, Any]: ...

    async def delete(self, uid: str) -> int: ...


@dataclass(frozen=True)
class WardrobePart:
    name: PartName
    tools: tuple[Tool, ...] = ()
    clock_jobs: tuple[TickJob, ...] = ()
    daily_jobs: tuple[TickJob, ...] = ()
    privacy: tuple[PrivacySource, ...] = ()
    data: tuple[WardrobeData, ...] = ()
    observers: tuple[ChangeObserver, ...] = ()
    services: Mapping[str, Any] = field(default_factory=dict)
    ready: str = NOT_BUILT


def _no_store() -> WardrobeStore | None:
    return None


def _no_tryon() -> TryOnProvider | None:
    return None


@dataclass(frozen=True)
class WardrobeContext:
    s: Settings
    docs: Docs | None
    keyring: Keyring | None
    audit: AuditTrail | None
    now: Callable[[], datetime]  # UTC: the only clock under wardrobe/ (D15)
    zone: Callable[[str], Awaitable[ZoneInfo]]  # his zone: the brief store's, else user_timezone
    state: Callable[[str], Any]
    notifier: Callable[[], Notifier | None] = lambda: None
    reads: Callable[[], BackgroundReads | None] = lambda: None
    outside: Callable[[], Any] = lambda: None  # R11's OutsideStore (C's weather), read late
    store: Callable[[], WardrobeStore | None] = _no_store  # A's store, read late (B and C)
    tryon: Callable[[], TryOnProvider | None] = _no_tryon  # R13.1: the try-on provider (C), late


__all__ = [
    "CARD_ALWAYS",
    "CLOCK_JOB_NAMES",
    "COLLECTIONS",
    "JOB_OWNER",
    "KIND_OWNER",
    "MAX_RESULT_PIECES",
    "NOT_BUILT",
    "NO_AI_TOOLS",
    "NO_DATA_PARTS",
    "PARTS",
    "PRIVACY_OWNER",
    "QUERY_TOOLS",
    "R13_JOB_NAMES",
    "R13_STATUS_ROUTE",
    "READ_TOOLS",
    "ROUTE_PREFIX",
    "SERVICE_OWNER",
    "SPOKEN_OK",
    "TOLD_KEY_PREFIX",
    "TOOL_FAMILIES",
    "TOOL_OWNER",
    "UNDOABLE",
    "ChangeObserver",
    "Commit",
    "Committed",
    "HistoryItem",
    "Mark",
    "NeedKind",
    "PartName",
    "PhotoVault",
    "PieceChange",
    "Refused",
    "ReviewNeeded",
    "ReviewWriter",
    "WardrobeContext",
    "WardrobeData",
    "WardrobePart",
    "WardrobeStore",
    "tool_allowed",
]
