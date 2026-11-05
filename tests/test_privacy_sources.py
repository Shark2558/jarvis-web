# tests/test_privacy_sources.py - R2 D14: the existing categories on the Docs twin. For each: the
# count is the owner's alone, the export holds the seeded data and no secret, the delete empties it
# (data gone from MemoryDocs, other owners untouched) and the class is the plan's.
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from billing_fakes import Clock
from google_fakes import google_tokens
from memory_fakes import NOW, UID, rig

from jarvis.billing.meter import UsageMeter
from jarvis.brief.models import BriefSettings
from jarvis.brief.store import BriefStore
from jarvis.core.guardrails import ActionRisk, ConfirmationGate, PendingAction
from jarvis.core.models import Session, Turn
from jarvis.drive.roots import RootsStore
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.llm.base import Role
from jarvis.places.store import MapsPlaces
from jarvis.privacy import PrivacyRegistry
from jarvis.privacy.export import scrub
from jarvis.privacy.sources import (
    ExistingParts,
    approvals_source,
    audit_source,
    briefs_source,
    conversations_source,
    counters_source,
    deleted_source,
    drive_source,
    existing_sources,
    faces_source,
    google_source,
    marks_source,
    memory_source,
    passkeys_source,
    places_source,
    settings_source,
    spend_source,
)
from jarvis.storage.docs import MemoryDocs
from jarvis.storage.sessions import DocSessionStore
from jarvis.tools.audit import AuditLog
from jarvis.tools.task_marks import OutsideTasks
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore

OTHER = "u_other"
NEEDLE = "NEEDLE-4821-xyz"


def dump(docs: MemoryDocs) -> str:
    return repr(docs._data)


# ---- memory -----------------------------------------------------------------------------------


async def test_memory_counts_exports_and_deletes_only_the_owners_facts() -> None:
    r = rig()
    await r.svc.add_fact(UID, f"Likes tea {NEEDLE}", "preferences")
    await r.svc.add_fact(UID, "Has a dog", "people")
    await r.svc.add_fact(OTHER, "Other owner fact", "people")
    src = memory_source(r.svc)
    v = await src.describe(UID)
    assert (v.id, v.count, v.delete, v.export) == ("memory", 2, "passkey", True)
    assert NEEDLE in str(await src.export(UID))
    assert await src.delete(UID) == 2
    after = await src.describe(UID)
    assert after.count == 0 and after.delete == "none" and after.rev != v.rev
    assert NEEDLE not in dump(r.docs)
    assert (await src.describe(OTHER)).count == 1


# ---- conversations ----------------------------------------------------------------------------


class FilesStub:
    def __init__(self) -> None:
        self.forgotten: list[tuple[str, str]] = []

    async def forget_session(self, owner: str, session_id: str) -> int:
        self.forgotten.append((owner, session_id))
        return 1


async def _chat(store: DocSessionStore, uid: str, sid: str, text: str) -> None:
    s = Session(id=sid, user_id=uid)
    s.append(Turn(role=Role.USER, content=text))
    s.append(Turn(role=Role.ASSISTANT, content="Done, Sir."))
    await store.save(s)


async def test_conversations_count_export_newest_first_and_delete_with_files_first() -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs)
    files = FilesStub()
    await _chat(store, UID, "sess_a1", f"hello {NEEDLE}")
    await _chat(store, UID, "sess_a2", "second")
    await _chat(store, OTHER, "sess_b1", "not yours")
    src = conversations_source(store, files)  # type: ignore[arg-type]
    v = await src.describe(UID)
    assert v.count == 2 and v.delete == "passkey" and "Google" in v.note
    exp = await src.export(UID)
    assert exp is not None and len(exp["conversations"]) == 2
    assert NEEDLE in str(exp) and "not yours" not in str(exp)
    assert await src.delete(UID) == 2
    assert sorted(files.forgotten) == [(UID, "sess_a1"), (UID, "sess_a2")]
    assert (await src.describe(UID)).count == 0
    assert NEEDLE not in dump(docs) and "not yours" in dump(docs)


async def test_conversations_export_is_the_newest_200_only() -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs)
    for i in range(203):
        await _chat(store, UID, f"sess_{i:04d}", "x")
    exp = await conversations_source(store).export(UID)
    assert exp is not None and len(exp["conversations"]) == 200


# ---- recently deleted -------------------------------------------------------------------------


async def test_deleted_lists_exports_and_empties_now() -> None:
    docs = MemoryDocs()
    bin_ = UndoBin(DeletedStore(docs))
    await bin_.keep(UID, "task", f"Buy milk {NEEDLE}", {"title": "x"})
    await bin_.keep(OTHER, "task", "theirs", {})
    src = deleted_source(bin_)
    v = await src.describe(UID)
    assert v.count == 1 and v.delete == "passkey" and v.recoverable
    assert NEEDLE in str(await src.export(UID))
    assert await src.delete(UID) == 1
    assert (await src.describe(UID)).count == 0 and (await src.describe(OTHER)).count == 1


# ---- google, drive, places --------------------------------------------------------------------


async def test_google_export_is_status_only_and_delete_forgets_the_tokens() -> None:
    tokens = MemoryTokenStore()
    t = google_tokens()
    await tokens.put(UID, t)
    src = google_source(tokens)
    v = await src.describe(UID)
    assert v.count == 1 and v.delete == "simple"
    exp = await src.export(UID)
    assert exp is not None and exp["connected"] is True
    blob = str(scrub(exp))
    assert t.access_token.get_secret_value() not in blob
    assert t.refresh_token.get_secret_value() not in blob
    assert await src.delete(UID) == 1
    assert (await src.describe(UID)).count == 0 and await tokens.get(UID) is None


async def test_drive_folders_are_listed_exported_and_removed() -> None:
    roots = RootsStore(MemoryDocs())
    await roots.confirm(UID, "1AbCdEfGhIjKlMnOpQrStUv", "Receipts", email="me@example.com")
    src = drive_source(roots)
    assert (await src.describe(UID)).count == 1
    exp = await src.export(UID)
    assert exp is not None and exp["folders"][0]["name"] == "Receipts"
    assert await src.delete(UID) == 1
    assert (await src.describe(UID)).count == 0


async def test_places_home_and_work_are_exported_and_cleared() -> None:
    docs = MemoryDocs()
    places = MapsPlaces(docs, key=bytes(range(1, 33)))
    await places.put(UID, home="Kowdiar, Thiruvananthapuram", work=None)
    src = places_source(places)
    v = await src.describe(UID)
    assert v.count == 1 and v.delete == "simple" and v.encrypted_by_jarvis
    exp = await src.export(UID)
    assert exp == {"home": "Kowdiar, Thiruvananthapuram", "work": None}
    assert await src.delete(UID) == 1
    after = await src.describe(UID)
    assert after.count == 0 and after.delete == "none"


# ---- briefs and settings ----------------------------------------------------------------------


async def _brief(store: BriefStore, uid: str, day: str) -> None:
    await store.claim(
        uid,
        day,
        tz="Asia/Kolkata",
        trigger="manual",
        force=True,
        now=NOW,
        max_generations=5,
    )


async def test_briefs_cover_the_last_week_and_delete_all() -> None:
    docs = MemoryDocs()
    store = BriefStore(docs)
    today = date(2026, 11, 15)
    await _brief(store, UID, "2026-11-15")
    await _brief(store, UID, "2026-11-10")
    await _brief(store, OTHER, "2026-11-15")
    src = briefs_source(store, lambda: today)
    v = await src.describe(UID)
    assert v.count == 2 and v.delete == "passkey"
    exp = await src.export(UID)
    assert exp is not None and len(exp["briefs"]) == 2
    assert "claim_id" not in str(scrub(exp))
    assert await src.delete(UID) == 2
    assert (await src.describe(UID)).count == 0 and (await src.describe(OTHER)).count == 1


async def test_settings_count_changed_choices_and_reset_only_the_brief() -> None:
    store = BriefStore(MemoryDocs())
    await store.update_settings(UID, lambda s: s.model_copy(update={"ai_summary": True}))
    src = settings_source(store)
    v = await src.describe(UID)
    assert v.count == 1 and v.delete == "simple"
    assert await src.delete(UID) == 1
    assert (await store.get_settings(UID)).ai_summary is BriefSettings().ai_summary
    assert (await src.describe(UID)).delete == "none"


# ---- spend ------------------------------------------------------------------------------------


async def test_spend_never_deletes_this_months_row() -> None:
    docs = MemoryDocs()
    meter = UsageMeter(docs)
    clock = Clock(datetime(2026, 11, 15, 6, 0, tzinfo=UTC))
    for month_day in (datetime(2026, 9, 3, tzinfo=UTC), datetime(2026, 10, 3, tzinfo=UTC), clock()):
        await meter.add(UID, brain_id="b", cost_usd=0.1, cost_inr=9.5, now=month_day)
    await meter.add(
        OTHER, brain_id="b", cost_usd=0.1, cost_inr=9.5, now=datetime(2026, 9, 3, tzinfo=UTC)
    )
    src = spend_source(meter, clock)
    v = await src.describe(UID)
    assert v.count == 3 and v.delete == "passkey" and "This month stays" in v.note
    exp = await src.export(UID)
    assert exp is not None and [m["month"] for m in exp["months"]] == [
        "2026-09",
        "2026-10",
        "2026-11",
    ]
    assert await src.delete(UID) == 2
    after = await src.describe(UID)
    assert after.count == 1 and after.delete == "none"  # only this month's row is left
    assert (await meter.get(UID, "2026-11")).calls == 1
    assert (await meter.get(OTHER, "2026-09")).calls == 1


async def test_m5_spend_delete_count_is_the_past_months_only() -> None:
    meter = UsageMeter(MemoryDocs())
    clock = Clock(datetime(2026, 11, 15, 6, 0, tzinfo=UTC))
    for day in (datetime(2026, 9, 3, tzinfo=UTC), datetime(2026, 10, 3, tzinfo=UTC), clock()):
        await meter.add(UID, brain_id="b", cost_usd=0.1, cost_inr=9.5, now=day)
    v = await spend_source(meter, clock).describe(UID)
    assert v.count == 3 and v.delete_count == 2


async def test_m5_a_category_with_no_separate_delete_count_uses_its_count() -> None:
    v = await settings_source(BriefStore(MemoryDocs())).describe(UID)
    assert v.delete_count == v.count


async def test_m4_conversations_delete_counts_only_what_went_when_one_fails() -> None:
    docs = MemoryDocs()
    store = DocSessionStore(docs)
    await _chat(store, UID, "sess_a1", "one")
    await _chat(store, UID, "sess_a2", "two")
    real = store.delete

    async def flaky(sid: str) -> bool:
        if sid == "sess_a2":
            raise RuntimeError("firestore down")
        return await real(sid)

    store.delete = flaky  # type: ignore[method-assign]
    src = conversations_source(store)
    assert await src.delete(UID) == 1  # reports the one that went; never raises with it lost
    assert (await src.describe(UID)).count == 1


async def test_m4_conversations_that_report_not_deleted_are_not_counted() -> None:
    store = DocSessionStore(MemoryDocs())
    await _chat(store, UID, "sess_a1", "one")

    async def nothing(sid: str) -> bool:
        return False

    store.delete = nothing  # type: ignore[method-assign]
    assert await conversations_source(store).delete(UID) == 0


# ---- approvals, passkeys, audit, marks, counters, faces ---------------------------------------


async def test_approvals_waiting_can_be_declined() -> None:
    gate = ConfirmationGate()
    mine = PendingAction(
        tool="gmail_send",
        arguments={"body": NEEDLE},
        risk=ActionRisk.IRREVERSIBLE,
        summary="Send",
        scope=f"{UID}:sess_1",
    )
    theirs = mine.model_copy(update={"id": "other_card", "scope": f"{OTHER}:sess_2"})
    await gate.store.put(mine)
    await gate.store.put(theirs)
    src = approvals_source(gate)
    v = await src.describe(UID)
    assert v.count == 1 and v.delete == "simple"
    exp = await src.export(UID)
    assert exp is not None and exp["waiting"][0]["tool"] == "gmail_send"
    assert NEEDLE not in str(exp)  # the card's words are not part of the export
    assert await src.delete(UID) == 1
    assert (await src.describe(UID)).count == 0 and (await src.describe(OTHER)).count == 1


async def test_approvals_say_a_waiting_card_is_kept_as_written() -> None:
    """R2 review S4 / plan D13: the documented limit is said where the owner looks for it."""
    v = await approvals_source(ConfirmationGate()).describe(UID)
    words = f"{v.what} {v.where} {v.note}"
    assert v.encrypted_by_jarvis is False
    assert "as written" in words and "not encrypted by JARVIS" in words
    assert "until you decide" in words and "Declining does nothing" in words


async def test_passkeys_are_listed_but_managed_elsewhere() -> None:
    from test_permissions_service import Rig as PermRig

    pr = PermRig()
    await pr.register("Laptop")
    src = passkeys_source(pr.svc)
    v = await src.describe("u_owner")
    assert v.count == 1 and v.delete == "none" and "Permissions" in v.note
    exp = await src.export("u_owner")
    assert exp == {"passkeys": [{"label": "Laptop", "added": exp["passkeys"][0]["added"]}]}  # type: ignore[index]
    with pytest.raises(PermissionError):
        await src.delete("u_owner")


async def test_audit_is_view_and_export_only() -> None:
    log = AuditLog()
    await log.append(
        agent="owner", tool="x", risk=ActionRisk.READ_ONLY, outcome="executed", args={"a": NEEDLE}
    )
    src = audit_source(log)
    v = await src.describe(UID)
    assert v.count == 1 and v.delete == "none" and v.export
    exp = await src.export(UID)
    assert exp is not None and exp["entries"][0]["tool"] == "x" and NEEDLE not in str(exp)


async def test_marks_are_counted_and_never_deletable() -> None:
    marks = OutsideTasks(MemoryDocs())
    await marks.add(UID, ["t1", "t2"])
    src = marks_source(marks)
    v = await src.describe(UID)
    assert v.delete == "none" and not v.export and v.count == 2
    assert (await src.describe(OTHER)).count == 0


async def test_counters_and_faces_placeholders() -> None:
    c = await counters_source().describe(UID)
    assert c.delete == "none" and c.count is None and not c.export
    f = await faces_source().describe(UID)
    assert f.id == "faces" and f.count == 0 and f.delete == "none"
    assert f.note == "Not built yet. Nothing is stored."


# ---- the set ----------------------------------------------------------------------------------


async def test_existing_sources_register_without_clashes_and_skip_what_is_off() -> None:
    docs = MemoryDocs()
    reg = PrivacyRegistry()
    parts = ExistingParts(
        sessions=DocSessionStore(docs),
        tokens=MemoryTokenStore(),
        briefs=BriefStore(docs),
        meter=UsageMeter(docs),
        gate=ConfirmationGate(),
        audit=AuditLog(),
    )
    for s in existing_sources(parts):
        reg.register(s)
    ids = reg.ids()
    assert ids[-2:] == ["counters", "faces"]
    assert {"conversations", "google", "briefs", "settings", "spend", "approvals", "audit"} <= set(
        ids
    )
    assert "memory" not in ids and "drive" not in ids
    views = await reg.describe_all(UID)
    assert all(v.available for v in views)


async def test_every_source_describes_with_a_stable_rev() -> None:
    docs = MemoryDocs()
    src = settings_source(BriefStore(docs))
    a, b = await src.describe(UID), await src.describe(UID)
    assert a.rev == b.rev and len(a.rev) == 16
