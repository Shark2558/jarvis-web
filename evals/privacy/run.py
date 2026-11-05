# evals/privacy/run.py
"""R2 D14 eval - the privacy dashboard over a seeded owner (real stores on the in-process Docs
twin, the real PermissionsService with a software passkey, the real PrivacyService).

    python evals/privacy/run.py --mock

Every case gets a fresh world: an owner and another owner, every existing and R1 category seeded
(plus stand-ins for the R2 vault, notes and things that workstreams A, B and C register at I1).
  counts     every category's count is right, and another owner's data is never counted
  exports    each export holds exactly the seeded data; no export or view holds a secret
  deletes    each delete -> count 0, the data gone from the Docs (path scan), the other owner and
             the other categories untouched; this month's spend never deleted; faces is listed
  gating     a passkey-class delete without a proof is refused and deletes nothing; a proof for
             category A cannot delete B; a replayed proof is refused; a changed rev is a conflict;
             without a passkey the typed word and a fresh sign-in are needed; unsafe categories
             refuse; every delete has an audit entry without content; a bearer token is refused
Negative controls (each MUST make the suite fail): the proof's binding ignored, the owner filter
off, the rev check off, the single-export proof off, the read-back after a delete off.
(Over the soft 800 lines on purpose: each case is a short, independent scenario.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "permissions"))
from authenticator import SoftAuthenticator  # noqa: E402
from r1d_common import finish  # noqa: E402

from jarvis.activity.models import ActivityItem  # noqa: E402
from jarvis.activity.store import ActivityStore  # noqa: E402
from jarvis.billing.meter import UsageMeter  # noqa: E402
from jarvis.brief.store import BriefStore  # noqa: E402
from jarvis.core.guardrails import ActionRisk, ConfirmationGate, InputRejected, PendingAction  # noqa: E402
from jarvis.core.models import Session, Turn  # noqa: E402
from jarvis.drive.roots import RootsStore  # noqa: E402
from jarvis.family.models import Member  # noqa: E402
from jarvis.family.store import FamilyStore  # noqa: E402
from jarvis.groceries.store import GroceryStore  # noqa: E402
from jarvis.integrations.vault import GoogleTokens, MemoryTokenStore, TokenCipher  # noqa: E402
from jarvis.llm.base import Role  # noqa: E402
from jarvis.llm.brains import BrainRegistry, BrainSpec  # noqa: E402
from jarvis.llm.mock_provider import MockProvider  # noqa: E402
from jarvis.llm.router import ModelTier  # noqa: E402
from jarvis.logging import configure_logging  # noqa: E402
from jarvis.offline.store import LocalBrainStore  # noqa: E402
from jarvis.permissions.ceremony import RelyingParty  # noqa: E402
from jarvis.permissions.errors import PasskeyRejected, PasskeyRequired, ProofRequired  # noqa: E402
from jarvis.permissions.models import ChallengeRequest, PasskeyProof, RegisterRequest  # noqa: E402
from jarvis.permissions.passkeys import ChallengeStore, PasskeyStore  # noqa: E402
from jarvis.permissions.service import PermissionsService  # noqa: E402
from jarvis.permissions.store import PermissionsStore  # noqa: E402
from jarvis.places.store import MapsPlaces  # noqa: E402
from jarvis.privacy import CategoryView, PrivacyRegistry  # noqa: E402
from jarvis.privacy import sources as sources_mod  # noqa: E402
from jarvis.privacy.service import (  # noqa: E402
    Changed,
    NotDeletable,
    PrivacyService,
)
from jarvis.privacy.sources import ExistingParts, existing_sources  # noqa: E402
from jarvis.privacy.sources_r1 import R1Parts, r1_sources  # noqa: E402
from jarvis.recall.service import MemoryService  # noqa: E402
from jarvis.recall.store import MemoryStore  # noqa: E402
from jarvis.storage.docs import MemoryDocs  # noqa: E402
from jarvis.storage.sessions import DocSessionStore  # noqa: E402
from jarvis.telegram.store import TelegramStore  # noqa: E402
from jarvis.tools.audit import AuditLog  # noqa: E402
from jarvis.tools.task_marks import OutsideTasks  # noqa: E402
from jarvis.undo.service import UndoBin  # noqa: E402
from jarvis.undo.store import DeletedStore  # noqa: E402

UID, OTHER = "u_owner", "u_other"
RP = RelyingParty(id="jarvis.example.com", origin="https://jarvis.example.com")
FRESH = 240
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)
TODAY = date(2026, 11, 15)
N = {  # needles: text that must be in an export and gone after a delete
    "memory": "NEEDLE-MEM-5521",
    "conversations": "NEEDLE-CHAT-5522",
    "deleted": "NEEDLE-BIN-5523",
    "activity": "NEEDLE-ACT-5524",
    "family": "NEEDLE-FAM-5525",
    "places": "NEEDLE-PLACE-5526",
    "notes": "NEEDLE-NOTE-5527",
}
SECRETS = ("ACCESSSECRET-77", "REFRESHSECRET-78", "OFFLINEKEY-79", "https://laptop.secret.example")


class StandIn:
    """A stand-in for a category the R2 workstreams register at I1 (vault, notes, things)."""

    filter_owner = True  # the owner-filter negative control turns this off

    def __init__(self, id: str, cls: str, exportable: bool, items: dict[str, list[str]]) -> None:
        self.id, self.section, self.label = id, "Your documents and things", id.title()
        self.cls, self.exportable, self.items = cls, exportable, items

    def _mine(self, uid: str) -> list[str]:
        if StandIn.filter_owner:
            return list(self.items.get(uid, []))
        return [x for v in self.items.values() for x in v]

    async def describe(self, uid: str) -> CategoryView:
        mine = self._mine(uid)
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what="items",
            count=len(mine),
            unit="items",
            retention="Until deleted.",
            where="Firestore",
            encrypted_by_jarvis=True,
            export=self.exportable,
            delete=self.cls,  # type: ignore[arg-type]
            rev=sources_mod.fingerprint(self.id, mine),
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return {"items": self._mine(uid)} if self.exportable else None

    async def delete(self, uid: str) -> int:
        n = len(self.items.get(uid, []))
        self.items[uid] = []
        return n


class World:
    def __init__(self, *, passkey: bool = True) -> None:
        self.docs = MemoryDocs()
        self.audit = AuditLog()
        self.auth = SoftAuthenticator(origin=RP.origin)
        self.perms = PermissionsService(
            store=PermissionsStore(self.docs),
            passkeys=PasskeyStore(self.docs),
            challenges=ChallengeStore(self.docs),
            rp=RP,
            can_reauth=True,
            audit=self.audit,
        )
        self.use_passkey = passkey
        self.standins = {
            "vault": StandIn("vault", "passkey", False, {UID: ["v1", "v2", "v3"], OTHER: ["vx"]}),
            "notes": StandIn("notes", "passkey", True, {UID: [N["notes"], "n2"], OTHER: ["nx"]}),
            "things": StandIn("things", "passkey", True, {UID: ["t1"], OTHER: ["tx", "ty"]}),
        }
        self.reg = PrivacyRegistry(budget_s=2.0)
        self.svc = PrivacyService(self.reg, permissions=self.perms, audit=self.audit)

    async def build(self) -> World:
        d = self.docs
        brains = BrainRegistry(
            [BrainSpec("mock", "Mock", MockProvider(), {t: f"mock-{t.value}" for t in ModelTier})],
            default_id="mock",
        )
        self.memory = MemoryService(
            store=MemoryStore(d), brains=brains, billing=None, audit=self.audit, max_runs=0
        )
        await self.memory.add_fact(UID, f"Likes tea {N['memory']}", "preferences")
        await self.memory.add_fact(UID, "Has a dog", "people")
        await self.memory.add_fact(OTHER, "Other fact", "people")
        self.sessions = DocSessionStore(d)
        for sid, uid, text in (
            ("sess_a1", UID, f"hi {N['conversations']}"),
            ("sess_a2", UID, "yo"),
            ("sess_b1", OTHER, "theirs"),
        ):
            s = Session(id=sid, user_id=uid)
            s.append(Turn(role=Role.USER, content=text))
            await self.sessions.save(s)
        self.undo = UndoBin(DeletedStore(d))
        await self.undo.keep(UID, "task", f"Milk {N['deleted']}", {"title": "Milk"})
        await self.undo.keep(OTHER, "task", "theirs", {})
        self.tokens = MemoryTokenStore()
        await self.tokens.put(
            UID,
            GoogleTokens(
                email="o@example.com",
                access_token="ACCESSSECRET-77",  # type: ignore[arg-type]
                refresh_token="REFRESHSECRET-78",
                expires_at=4e9,
                scopes=["gmail"],  # type: ignore[arg-type]
            ),
        )
        self.roots = RootsStore(d)
        await self.roots.confirm(UID, "1AbCdEfGhIjKlMnOpQrStUv", "Receipts", email="o@example.com")
        self.places = MapsPlaces(d, key=bytes(range(1, 33)))
        await self.places.put(UID, home=N["places"], work=None)
        self.briefs = BriefStore(d)
        for uid, day in ((UID, "2026-11-15"), (UID, "2026-11-12"), (OTHER, "2026-11-15")):
            await self.briefs.claim(
                uid,
                day,
                tz="Asia/Kolkata",
                trigger="manual",
                force=True,
                now=NOW,
                max_generations=5,
            )
        await self.briefs.update_settings(UID, lambda s: s.model_copy(update={"ai_summary": True}))
        self.meter = UsageMeter(d)
        for when in (datetime(2026, 9, 3, tzinfo=UTC), datetime(2026, 10, 3, tzinfo=UTC), NOW):
            await self.meter.add(UID, brain_id="b", cost_usd=0.1, cost_inr=9.5, now=when)
        self.gate = ConfirmationGate()
        for uid, aid in ((UID, "card_a"), (OTHER, "card_b")):
            await self.gate.store.put(
                PendingAction(
                    id=aid,
                    tool="gmail_send",
                    arguments={"body": "x"},
                    risk=ActionRisk.IRREVERSIBLE,
                    summary="Send",
                    scope=f"{uid}:sess_x",
                )
            )
        self.marks = OutsideTasks(d)
        await self.marks.add(UID, ["t1", "t2"])
        self.telegram = TelegramStore(d)
        code, _ = await self.telegram.start_pairing(UID)
        await self.telegram.finish_pairing(code, tg_user_id=424242, chat_id=434343)
        self.activity = ActivityStore(d)
        for i, (uid, words) in enumerate(
            ((UID, f"Looked {N['activity']}"), (UID, "Looked"), (OTHER, "theirs")), 1
        ):
            await self.activity.add(
                ActivityItem(
                    id=f"act_{i:020x}",
                    user_id=uid,
                    at=datetime(2026, 11, 14, 9, i, tzinfo=UTC),
                    tool="calendar_list",
                    risk="read_only",
                    kind="read",
                    outcome="done",
                    words=words,
                ),
                "20261114",
            )
        self.family = FamilyStore(d)
        for i, name in enumerate((N["family"], "Arun")):
            await self.family.add(
                UID,
                Member(
                    id=f"m{i}",
                    name=name,
                    calendar_id=f"p{i}@example.com",
                    access="reader",
                    added_at="2026-11-01",
                    verified_at="2026-11-01",
                ),
            )
        self.offline = LocalBrainStore(d, TokenCipher(bytes(range(1, 33))))
        from pydantic import SecretStr

        await self.offline.put(
            url="https://laptop.secret.example",
            key=SecretStr("OFFLINEKEY-79"),
            model="llama3",
            enabled=True,
            set_by="owner",
        )
        self.groceries = GroceryStore(d)
        await self.groceries.remember(UID, "list_abc")
        await self.groceries.remember(OTHER, "list_other")
        if self.use_passkey:
            await self.register_passkey()
        parts = ExistingParts(
            memory=self.memory,
            sessions=self.sessions,
            undo=self.undo,
            tokens=self.tokens,
            roots=self.roots,
            places=self.places,
            briefs=self.briefs,
            meter=self.meter,
            gate=self.gate,
            permissions=self.perms,
            audit=self.audit,
            marks=self.marks,
            today=lambda: TODAY,
            clock=lambda: NOW,
        )
        existing = existing_sources(parts)
        r1 = r1_sources(
            R1Parts(
                telegram=self.telegram,
                activity=self.activity,
                offline=self.offline,
                groceries=self.groceries,
                family=self.family,
                today=lambda: TODAY,
            )
        )
        for s in [*existing[:-2], *r1, *self.standins.values(), *existing[-2:]]:
            self.reg.register(s)
        return self

    async def register_passkey(self) -> None:
        opts = await self.perms.register_options(UID, user_name="o@example.com", fresh_left_s=FRESH)
        cred = self.auth.create(opts.public_key)
        await self.perms.register(
            UID,
            RegisterRequest.model_validate(
                {"challenge_id": opts.challenge_id, "credential": cred, "label": "Laptop"}
            ),
        )

    async def proof(self, purpose: str, target: str) -> PasskeyProof:
        ch = await self.perms.challenge(
            UID, ChallengeRequest(purpose=purpose, target=target), approvals=None
        )  # type: ignore[arg-type]
        cred = self.auth.get(ch.public_key)
        return PasskeyProof.model_validate({"challenge_id": ch.challenge_id, "credential": cred})

    async def views(self, uid: str = UID) -> dict[str, CategoryView]:
        return {v.id: v for v in await self.reg.describe_all(uid)}

    async def delete(self, cid: str, uid: str = UID) -> Any:
        """The honest path: the right proof for this category and its current rev."""
        view = (await self.views(uid))[cid]
        proof = None
        if view.delete == "passkey" and self.use_passkey:
            proof = await self.proof("privacy_delete", f"{cid}:{view.rev}")
        return await self.svc.delete(
            uid, cid, rev=view.rev, confirm="DELETE", proof=proof, fresh_left_s=FRESH
        )

    async def export(self, cid: str, uid: str = UID) -> dict[str, Any]:
        """The honest export: a content category with its own proof (target export:<id>)."""
        view = (await self.views(uid))[cid]
        proof = None
        if view.delete == "passkey" and self.use_passkey:
            proof = await self.proof("privacy_export", f"export:{cid}")
        return await self.svc.export(uid, cid, proof=proof, fresh_left_s=FRESH)

    def dump(self) -> str:
        return repr(self.docs._data)


Case = Callable[[World], Awaitable[list[str]]]
CASES: list[tuple[str, Case, bool]] = []  # (id, fn, passkey world)


def case(cid: str, *, passkey: bool = True) -> Callable[[Case], Case]:
    def wrap(fn: Case) -> Case:
        CASES.append((cid, fn, passkey))
        return fn

    return wrap


# ---- counts -----------------------------------------------------------------------------------

COUNTS: dict[str, tuple[int | None, int | None]] = {  # id -> (owner count, other owner count)
    "memory": (2, 1),
    "conversations": (2, 1),
    "deleted": (1, 1),
    "google": (1, 0),
    "drive": (1, 0),
    "places": (1, 0),
    "briefs": (2, 1),
    "settings": (1, 0),
    "spend": (3, 0),
    "approvals": (1, 1),
    "passkeys": (1, 0),
    "marks": (2, 0),
    "counters": (None, None),
    "faces": (0, 0),
    "telegram": (1, 0),
    "activity": (2, 1),
    "family": (2, 0),
    "groceries": (1, 1),
    "packages": (0, 0),
    "vault": (3, 1),
    "notes": (2, 1),
    "things": (1, 2),
}


def _count_case(cid: str, want: int | None, other: int | None) -> None:
    async def run(w: World) -> list[str]:
        mine, theirs = (await w.views())[cid], (await w.views(OTHER))[cid]
        out = []
        if not mine.available or mine.count != want:
            out.append(f"{cid}: owner count {mine.count}, wanted {want}")
        if theirs.count != other:
            out.append(f"{cid}: another owner sees {theirs.count}, wanted {other}")
        return out

    CASES.append((f"count-{cid}", run, True))


for _cid, (_a, _b) in COUNTS.items():
    _count_case(_cid, _a, _b)


@case("count-offline-is-set-without-showing-it")
async def _offline_view(w: World) -> list[str]:
    v = (await w.views())["offline"]
    blob = v.model_dump_json()
    return [
        m
        for ok, m in (
            (v.count == 1, "offline count"),
            (not v.export, "offline exportable"),
            (v.encrypted_by_jarvis, "badge"),
            (not any(s in blob for s in SECRETS), "a secret in the view"),
        )
        if not ok
    ]


@case("count-every-category-is-listed-in-the-table")
async def _all_listed(w: World) -> list[str]:
    want = set(COUNTS) | {"offline", "audit"}
    got = set(w.reg.ids())
    return [f"missing {sorted(want - got)} extra {sorted(got - want)}"] if want != got else []


@case("count-faces-placeholder-is-listed")
async def _faces(w: World) -> list[str]:
    v = (await w.views())["faces"]
    return [] if v.note == "Not built yet. Nothing is stored." and v.delete == "none" else ["faces"]


# ---- exports ----------------------------------------------------------------------------------

EXPORT_NEEDLES = {
    "memory": "memory",
    "conversations": "conversations",
    "deleted": "deleted",
    "activity": "activity",
    "family": "family",
    "places": "places",
    "notes": "notes",
}


@case("export-each-holds-exactly-the-seeded-data")
async def _exports(w: World) -> list[str]:
    out = []
    for cid, key in EXPORT_NEEDLES.items():
        text = json.dumps((await w.export(cid))["data"])
        if N[key] not in text:
            out.append(f"{cid}: needle missing from its export")
    for cid in ("memory", "conversations", "activity", "notes"):
        text = json.dumps((await w.export(cid))["data"])
        if "theirs" in text or "Other fact" in text or "nx" in text:
            out.append(f"{cid}: another owner's data in the export")
    return out


@case("export-no-secret-in-any-export-or-view")
async def _no_secrets(w: World) -> list[str]:
    blobs = [v.model_dump_json() for v in (await w.views()).values()]
    for cid, v in (await w.views()).items():
        if v.export:
            blobs.append(json.dumps(await w.export(cid)))
    blobs.append(
        json.dumps(
            await w.svc.export_all(
                UID, proof=await w.proof("privacy_export", "all"), fresh_left_s=None
            )
        )
    )
    return [f"secret {s!r} found" for s in SECRETS for b in blobs if s in b][:3]


@case("export-all-has-every-exportable-category-and-no-vault-files")
async def _export_all(w: World) -> list[str]:
    out = await w.svc.export_all(
        UID, proof=await w.proof("privacy_export", "all"), fresh_left_s=None
    )
    want = {i for i, v in (await w.views()).items() if v.export}
    got = set(out["categories"])
    bad = []
    if got != want:
        bad.append(f"categories {sorted(got ^ want)}")
    if "vault" in got or "Export" not in out["vault_files"]:
        bad.append("vault files")
    return bad


@case("export-all-needs-a-proof-for-privacy-export")
async def _export_all_gate(w: World) -> list[str]:
    out = []
    try:
        await w.svc.export_all(UID, proof=None, fresh_left_s=FRESH)
        out.append("ran without a proof")
    except PasskeyRequired:
        pass
    try:
        await w.svc.export_all(UID, proof=await w.proof("privacy_delete", "all"), fresh_left_s=None)
        out.append("a delete proof served an export")
    except PasskeyRejected:
        pass
    return out


@case("export-one-content-category-needs-its-own-proof")
async def _export_one_gate(w: World) -> list[str]:
    out = []
    for proof_for in (None, ("privacy_export", "all"), ("privacy_delete", "export:notes")):
        proof = await w.proof(*proof_for) if proof_for else None
        try:
            await w.svc.export(UID, "notes", proof=proof, fresh_left_s=FRESH)
            out.append(f"notes exported with proof {proof_for}")
        except (PasskeyRequired, PasskeyRejected):
            pass
    try:  # a category he can make again stays a plain export
        await w.svc.export(UID, "places", proof=None, fresh_left_s=None)
    except Exception as exc:  # noqa: BLE001
        out.append(f"places needed a proof: {type(exc).__name__}")
    return out


@case("export-one-without-a-passkey-needs-a-fresh-sign-in", passkey=False)
async def _export_one_fresh(w: World) -> list[str]:
    try:
        await w.svc.export(UID, "notes", proof=None, fresh_left_s=None)
        return ["notes exported with no sign-in"]
    except ProofRequired:
        return []


# ---- deletes ----------------------------------------------------------------------------------

DELETE_WANT: dict[str, tuple[int, str | None]] = {  # id -> (deleted, needle gone from the Docs)
    "memory": (2, N["memory"]),
    "conversations": (2, N["conversations"]),
    "deleted": (1, N["deleted"]),
    "google": (1, "ACCESSSECRET"),
    "drive": (1, None),
    "places": (1, None),
    "briefs": (2, None),
    "settings": (1, None),
    "spend": (2, None),
    "approvals": (1, None),
    "telegram": (1, "424242"),
    "activity": (2, N["activity"]),
    "family": (2, N["family"]),
    "offline": (1, "laptop.secret"),
    "groceries": (1, "list_abc"),
    "vault": (3, None),
    "notes": (2, None),
    "things": (1, None),
}
AFTER_ZERO = {"spend": 1}  # this month's row stays


def _delete_case(cid: str, want: int, needle: str | None) -> None:
    async def run(w: World) -> list[str]:
        def counts(views: dict[str, CategoryView], skip: str) -> dict[str, int | None]:
            return {k: v.count for k, v in views.items() if k not in (skip, "audit")}  # audit grows

        before_other = counts(await w.views(OTHER), "")
        before_cats = counts(await w.views(), cid)
        out = []
        res = await w.delete(cid)
        if res.deleted != want:
            out.append(f"{cid}: deleted {res.deleted}, wanted {want}")
        left = (await w.views())[cid].count
        if left != AFTER_ZERO.get(cid, 0):
            out.append(f"{cid}: count after is {left}")
        if needle and needle in w.dump():
            out.append(f"{cid}: needle {needle!r} still in the Docs")
        if cid not in ("offline",) and before_other != counts(await w.views(OTHER), ""):
            out.append(f"{cid}: another owner's data changed")
        if before_cats != counts(await w.views(), cid):
            out.append(f"{cid}: another category changed")
        return out

    CASES.append((f"delete-{cid}", run, True))


for _cid, (_n, _needle) in DELETE_WANT.items():
    _delete_case(_cid, _n, _needle)


@case("delete-this-months-spend-is-kept")
async def _spend(w: World) -> list[str]:
    await w.delete("spend")
    m = await w.meter.get(UID, "2026-11")
    return [] if m.calls == 1 and (await w.meter.get(UID, "2026-09")).calls == 0 else ["month rows"]


@case("delete-categories-with-no-delete-refuse")
async def _refuse(w: World) -> list[str]:
    out = []
    for cid in ("audit", "marks", "passkeys", "counters", "faces", "packages"):
        view = (await w.views())[cid]
        try:
            await w.svc.delete(
                UID, cid, rev=view.rev, confirm="DELETE", proof=None, fresh_left_s=FRESH
            )
            out.append(f"{cid} was deletable")
        except NotDeletable:
            pass
    return out


@case("delete-audit-entry-per-delete-without-content")
async def _audited(w: World) -> list[str]:
    await w.delete("memory")
    await w.delete("places")
    rows = [e for e in (await w.audit.tail(200)).entries if e.tool == "privacy_delete"]
    text = " ".join(e.detail for e in rows)
    bad = []
    if len(rows) != 2 or any(e.agent != "owner" for e in rows):
        bad.append(f"{len(rows)} audit rows")
    if any(n in text for n in N.values()):
        bad.append("content in the audit detail")
    return bad


# ---- gating -----------------------------------------------------------------------------------


@case("gate-passkey-class-without-a-proof-deletes-nothing")
async def _noproof(w: World) -> list[str]:
    view = (await w.views())["notes"]
    try:
        await w.svc.delete(
            UID, "notes", rev=view.rev, confirm="DELETE", proof=None, fresh_left_s=FRESH
        )
        return ["deleted without a proof"]
    except PasskeyRequired:
        pass
    return [] if (await w.views())["notes"].count == 2 else ["data changed"]


@case("gate-a-proof-for-category-a-cannot-delete-b")
async def _binding(w: World) -> list[str]:
    v = await w.views()
    proof = await w.proof("privacy_delete", f"notes:{v['notes'].rev}")
    try:
        await w.svc.delete(
            UID, "things", rev=v["things"].rev, confirm=None, proof=proof, fresh_left_s=None
        )
        return ["a proof for notes deleted things"]
    except PasskeyRejected:
        pass
    return [] if (await w.views())["things"].count == 1 else ["things changed"]


@case("gate-a-replayed-proof-is-refused")
async def _replay(w: World) -> list[str]:
    v = (await w.views())["notes"]
    proof = await w.proof("privacy_delete", f"notes:{v.rev}")
    await w.svc.delete(UID, "notes", rev=v.rev, confirm=None, proof=proof, fresh_left_s=None)
    w.standins["notes"].items[UID] = ["again"]
    v2 = (await w.views())["notes"]
    try:
        await w.svc.delete(UID, "notes", rev=v2.rev, confirm=None, proof=proof, fresh_left_s=None)
        return ["a proof was used twice"]
    except PasskeyRejected:
        return []


@case("gate-a-changed-rev-is-a-conflict")
async def _changed(w: World) -> list[str]:
    v = (await w.views())["places"]
    await w.places.put(UID, home="Elsewhere", work=None)  # changed since he looked
    try:
        await w.svc.delete(UID, "places", rev=v.rev, confirm=None, proof=None, fresh_left_s=None)
        return ["deleted data that changed"]
    except Changed:
        pass
    return [] if (await w.views())["places"].count == 1 else ["places changed"]


@case("gate-data-that-moves-while-the-proof-is-checked-is-a-conflict")
async def _moves(w: World) -> list[str]:
    v = (await w.views())["notes"]
    proof = await w.proof("privacy_delete", f"notes:{v.rev}")
    real = w.perms.check_purpose

    async def moving(*a: Any, **k: Any) -> Any:
        w.standins["notes"].items[UID].append("n3")  # a note arrives during the check
        return await real(*a, **k)

    w.perms.check_purpose = moving  # type: ignore[method-assign]
    try:
        await w.svc.delete(UID, "notes", rev=v.rev, confirm=None, proof=proof, fresh_left_s=None)
        return ["deleted data that arrived after he looked"]
    except Changed:
        return [] if (await w.views())["notes"].count == 3 else ["notes changed"]


@case("delete-reports-what-is-left-and-never-a-false-all-gone")
async def _left(w: World) -> list[str]:
    out = []
    res = await w.delete("places")
    if (res.deleted, res.remaining) != (1, 0):
        out.append(f"clean delete reported {res.deleted}/{res.remaining}")
    real = w.activity.sweep

    async def swallowed(*a: Any, **k: Any) -> int:
        return 0  # the real sweep logs and returns 0 when Firestore fails

    w.activity.sweep = swallowed  # type: ignore[method-assign]
    res = await w.delete("activity")
    w.activity.sweep = real  # type: ignore[method-assign]
    if res.deleted != 0 or not res.remaining:
        out.append(f"a swallowed failure reported {res.deleted}/{res.remaining}")
    res = await w.delete("spend")  # this month's row stays: that is not "left"
    if res.remaining != 0:
        out.append(f"spend reported {res.remaining} left")
    return out


@case("gate-a-proof-for-an-old-rev-cannot-delete-newer-data")
async def _old_rev(w: World) -> list[str]:
    old = (await w.views())["notes"]
    proof = await w.proof("privacy_delete", f"notes:{old.rev}")
    w.standins["notes"].items[UID].append("n3")
    new = (await w.views())["notes"]
    try:
        await w.svc.delete(UID, "notes", rev=new.rev, confirm=None, proof=proof, fresh_left_s=None)
        return ["an old proof deleted newer data"]
    except PasskeyRejected:
        return []


@case("gate-without-a-passkey-the-typed-word-and-a-fresh-sign-in-are-needed", passkey=False)
async def _typed(w: World) -> list[str]:
    v = (await w.views())["notes"]
    out = []
    for confirm, fresh, exc in (
        (None, FRESH, InputRejected),
        ("delete", FRESH, InputRejected),
        ("DELETE", 0, ProofRequired),
        ("DELETE", None, ProofRequired),
    ):
        try:
            await w.svc.delete(
                UID, "notes", rev=v.rev, confirm=confirm, proof=None, fresh_left_s=fresh
            )
            out.append(f"deleted with confirm={confirm!r} fresh={fresh!r}")
        except exc:
            pass
    if (await w.views())["notes"].count != 2:
        out.append("data changed")
    res = await w.svc.delete(
        UID, "notes", rev=v.rev, confirm="DELETE", proof=None, fresh_left_s=FRESH
    )
    return out if res.deleted == 2 else [*out, "the honest path failed"]


@case("gate-bearer-token-cannot-export-or-delete")
async def _bearer(w: World) -> list[str]:
    import httpx
    from pydantic import SecretStr

    from jarvis.api import create_app
    from jarvis.api.privacy import install_privacy
    from jarvis.config import LLMBackend, SessionBackend, Settings
    from jarvis.memory.inmemory import InMemorySessionStore

    s = Settings(
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
        api_token=SecretStr("eval-token"),
    )
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    install_privacy(app)
    out = []
    async with app.router.lifespan_context(app):
        app.state.privacy = w.svc
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://t",
            headers={"Authorization": "Bearer eval-token"},
        ) as c:
            for method, url, body in (
                ("GET", "/v1/privacy/places/export", None),
                ("POST", "/v1/privacy/export-all", {}),
                ("POST", "/v1/privacy/places/delete", {"rev": "x"}),
            ):
                r = await c.request(method, url, json=body)
                if r.status_code != 403 or r.json().get("error") != "console_only":
                    out.append(f"{url}: {r.status_code}")
    return out


# ---- running ----------------------------------------------------------------------------------


async def run_all() -> list[dict[str, Any]]:
    results = []
    for cid, fn, passkey in CASES:
        w = await World(passkey=passkey).build()
        try:
            failures = await fn(w)
        except Exception as exc:  # noqa: BLE001 - a case that raises failed
            failures = [f"raised {type(exc).__name__}: {str(exc)[:120]}"]
        results.append({"id": cid, "passed": not failures, "failures": failures})
    return results


@contextmanager
def binding_off() -> Any:
    """A privacy_delete proof is bound to the same fixed target for every category (the binding to
    category and rev is not checked)."""
    from jarvis.permissions import service as perm_service

    original = perm_service.purpose_binding

    def loose(uid: str, purpose: str, target: str | None) -> str:
        return original(uid, purpose, "any" if purpose == "privacy_delete" else target)

    perm_service.purpose_binding = loose  # type: ignore[assignment]
    try:
        yield
    finally:
        perm_service.purpose_binding = original  # type: ignore[assignment]


@contextmanager
def owner_filter_off() -> Any:
    StandIn.filter_owner = False
    try:
        yield
    finally:
        StandIn.filter_owner = True


@contextmanager
def rev_check_off() -> Any:
    saved = sources_mod.fingerprint
    sources_mod.fingerprint = lambda *a, **k: "0" * 16  # type: ignore[assignment]
    try:
        yield
    finally:
        sources_mod.fingerprint = saved


@contextmanager
def export_gate_off() -> Any:
    """A single-category export passes without proof (the review H1 bypass)."""
    orig = PrivacyService._prove

    async def loose(self: Any, uid: str, purpose: str, target: str, **k: Any) -> str:
        if purpose == "privacy_export" and target.startswith("export:"):
            return "open"
        return await orig(self, uid, purpose, target, **k)

    PrivacyService._prove = loose  # type: ignore[method-assign]
    try:
        yield
    finally:
        PrivacyService._prove = orig  # type: ignore[method-assign]


@contextmanager
def verify_off() -> Any:
    """The delete does not read back what is left (reports a clean success)."""
    orig = PrivacyService._left

    async def blind(self: Any, uid: str, source: Any) -> int | None:
        return 0

    PrivacyService._left = blind  # type: ignore[method-assign]
    try:
        yield
    finally:
        PrivacyService._left = orig  # type: ignore[method-assign]


async def controls() -> dict[str, Any]:
    failed: dict[str, list[str]] = {}
    for name, ctx in (
        ("binding_off", binding_off),
        ("owner_filter_off", owner_filter_off),
        ("rev_check_off", rev_check_off),
        ("export_gate_off", export_gate_off),
        ("verify_off", verify_off),
    ):
        with ctx():
            failed[name] = [r["id"] for r in await run_all() if not r["passed"]]
    return {"suite_failed": all(failed.values()), "failed_cases": failed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.parse_args()
    configure_logging()
    results = asyncio.run(run_all())
    return finish(HERE, "privacy", results, asyncio.run(controls()))


if __name__ == "__main__":
    sys.exit(main())
