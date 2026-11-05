# tests/test_privacy_service.py - R2 D14: the dashboard service. View, export, "download
# everything" and delete with the passkey path, the rev check and the audit entries.
from __future__ import annotations

import pytest
from privacy_fakes import FakeSource
from test_permissions_service import FRESH, UID, Rig

from jarvis.core.guardrails import InputRejected
from jarvis.permissions.errors import PasskeyRejected, PasskeyRequired, ProofRequired
from jarvis.privacy import PrivacyRegistry
from jarvis.privacy.service import (
    Changed,
    DeleteFailed,
    NotDeletable,
    NotExportable,
    PrivacyService,
    SourceUnavailable,
)

OTHER = "u_other"


class World:
    def __init__(self, *, passkey: bool = False, with_permissions: bool = True) -> None:
        self.rig = Rig()
        self.reg = PrivacyRegistry(budget_s=1.0)
        self.simple = FakeSource("places", delete="simple", items={UID: ["home"], OTHER: ["x"]})
        self.heavy = FakeSource("notes", delete="passkey", items={UID: ["n1", "n2"], OTHER: ["z"]})
        self.heavy2 = FakeSource("things", delete="passkey", items={UID: ["t1"]})
        self.fixed = FakeSource("audit", delete="none", items={UID: ["a"]})
        self.vault = FakeSource("vault", delete="passkey", exportable=False, items={UID: ["v"]})
        for s in (self.simple, self.heavy, self.heavy2, self.fixed, self.vault):
            self.reg.register(s)
        self.svc = PrivacyService(
            self.reg,
            permissions=self.rig.svc if with_permissions else None,
            audit=self.rig.audit,
        )
        self.passkey = passkey

    async def setup(self) -> World:
        if self.passkey:
            await self.rig.register()
        return self

    async def rev(self, cid: str) -> str:
        view = await self.svc.view(UID)
        return next(c.rev for c in view.categories if c.id == cid)

    async def audit_entries(self) -> list[object]:
        return list((await self.rig.audit.tail(50)).entries)


async def world(**kw: bool) -> World:
    return await World(**kw).setup()


# ---- view -------------------------------------------------------------------------------------


async def test_view_lists_every_category_with_the_owners_counts_only() -> None:
    w = await world()
    v = await w.svc.view(UID)
    assert [c.id for c in v.categories] == ["places", "notes", "things", "audit", "vault"]
    assert {c.id: c.count for c in v.categories} == {
        "places": 1,
        "notes": 2,
        "things": 1,
        "audit": 1,
        "vault": 1,
    }
    assert v.passkey_in_force is False and v.generated_at


async def test_view_says_whether_a_passkey_is_in_force() -> None:
    w = await world(passkey=True)
    assert (await w.svc.view(UID)).passkey_in_force is True


async def test_view_keeps_the_row_of_a_failing_source() -> None:
    w = await world()
    w.heavy.fail_describe = True
    v = await w.svc.view(UID)
    row = next(c for c in v.categories if c.id == "notes")
    assert row.available is False and row.count is None and row.delete == "none"
    assert "boom" not in row.model_dump_json()


# ---- export -----------------------------------------------------------------------------------


async def test_export_returns_the_seeded_data_and_is_audited_without_content() -> None:
    w = await world()
    out = await w.svc.export(UID, "notes", proof=None, fresh_left_s=FRESH)
    assert out["category"] == "notes" and out["data"] == {"items": ["n1", "n2"]}
    last = (await w.audit_entries())[-1]
    assert last.tool == "privacy_export" and last.agent == "owner"  # type: ignore[attr-defined]
    assert "n1" not in last.detail  # type: ignore[attr-defined]
    assert "notes" in last.detail and "2" in last.detail  # type: ignore[attr-defined]


async def test_export_never_contains_a_secret() -> None:
    w = await world()
    w.simple.secret = "sk-SECRETVALUE"
    out = await w.svc.export(UID, "places")
    assert "SECRETVALUE" not in str(out)
    assert out["data"]["nested"] == {"ok": True}


async def test_export_of_a_category_without_export_is_refused() -> None:
    w = await world()
    with pytest.raises(NotExportable):
        await w.svc.export(UID, "vault")


async def test_export_of_an_unknown_category_is_not_found() -> None:
    w = await world()
    with pytest.raises(LookupError):
        await w.svc.export(UID, "nope")


async def test_export_of_an_unavailable_source_says_so() -> None:
    w = await world()
    w.simple.fail_describe = True
    with pytest.raises(SourceUnavailable):
        await w.svc.export(UID, "places")


# ---- download everything ----------------------------------------------------------------------


async def test_export_all_has_every_exportable_category_and_points_to_vault_export() -> None:
    w = await world()
    out = await w.svc.export_all(UID, proof=None, fresh_left_s=FRESH)
    assert set(out["categories"]) == {"places", "notes", "things", "audit"}
    assert out["categories"]["notes"] == {"items": ["n1", "n2"]}
    assert "Vault" in out["vault_files"] and "Export" in out["vault_files"]
    assert "z" not in str(out) and "x" not in out["categories"]["places"]["items"]


async def test_export_all_lists_a_source_that_could_not_be_read() -> None:
    w = await world()
    w.heavy.fail_describe = True
    out = await w.svc.export_all(UID, proof=None, fresh_left_s=FRESH)
    assert "notes" not in out["categories"] and out["unavailable"] == ["notes"]


async def test_export_all_without_passkeys_needs_a_fresh_sign_in() -> None:
    w = await world()
    with pytest.raises(ProofRequired) as e:
        await w.svc.export_all(UID, proof=None, fresh_left_s=0)
    assert e.value.reason == "reauth"
    with pytest.raises(ProofRequired):
        await w.svc.export_all(UID, proof=None, fresh_left_s=None)


async def test_export_all_with_a_passkey_needs_a_proof_for_privacy_export() -> None:
    w = await world(passkey=True)
    with pytest.raises(PasskeyRequired):
        await w.svc.export_all(UID, proof=None, fresh_left_s=FRESH)
    proof = await w.rig.proof("privacy_export", target="all")
    out = await w.svc.export_all(UID, proof=proof, fresh_left_s=None)
    assert "notes" in out["categories"]
    with pytest.raises(PasskeyRejected):  # replay
        await w.svc.export_all(UID, proof=proof, fresh_left_s=None)
    wrong = await w.rig.proof("privacy_delete", target="all")
    with pytest.raises(PasskeyRejected):
        await w.svc.export_all(UID, proof=wrong, fresh_left_s=None)


# ---- delete: classes --------------------------------------------------------------------------


async def test_a_simple_delete_needs_no_proof_and_is_audited_without_content() -> None:
    w = await world()
    out = await w.svc.delete(
        UID, "places", rev=await w.rev("places"), confirm=None, proof=None, fresh_left_s=None
    )
    assert out.deleted == 1 and out.category == "places"
    assert (await w.svc.view(UID)).categories[0].count == 0
    assert w.simple.items[OTHER] == ["x"]  # another owner's data untouched
    last = (await w.audit_entries())[-1]
    assert last.tool == "privacy_delete" and last.agent == "owner"  # type: ignore[attr-defined]
    assert "home" not in last.detail  # type: ignore[attr-defined]


async def test_a_category_with_no_delete_is_refused_and_nothing_goes() -> None:
    w = await world()
    with pytest.raises(NotDeletable):
        await w.svc.delete(
            UID, "audit", rev=await w.rev("audit"), confirm="DELETE", proof=None, fresh_left_s=FRESH
        )
    assert w.fixed.deleted_calls == []


async def test_an_unknown_category_is_not_found() -> None:
    w = await world()
    with pytest.raises(LookupError):
        await w.svc.delete(UID, "nope", rev="x", confirm=None, proof=None, fresh_left_s=FRESH)


async def test_a_changed_rev_is_a_conflict_and_deletes_nothing() -> None:
    w = await world()
    rev = await w.rev("places")
    w.simple.items[UID].append("work")  # changed since he looked
    with pytest.raises(Changed):
        await w.svc.delete(UID, "places", rev=rev, confirm=None, proof=None, fresh_left_s=None)
    assert w.simple.deleted_calls == []


async def test_an_unavailable_source_is_never_deleted() -> None:
    w = await world()
    rev = await w.rev("places")
    w.simple.fail_describe = True
    with pytest.raises(SourceUnavailable):
        await w.svc.delete(UID, "places", rev=rev, confirm=None, proof=None, fresh_left_s=None)
    assert w.simple.deleted_calls == []


async def test_a_failing_delete_is_audited_as_an_error_and_raised() -> None:
    w = await world()
    w.simple.fail_delete = True
    with pytest.raises(DeleteFailed):
        await w.svc.delete(
            UID, "places", rev=await w.rev("places"), confirm=None, proof=None, fresh_left_s=None
        )
    last = (await w.audit_entries())[-1]
    assert last.outcome == "error" and "home" not in last.detail  # type: ignore[attr-defined]


# ---- delete: the passkey class ----------------------------------------------------------------


async def test_passkey_class_without_a_proof_is_refused_when_a_passkey_is_in_force() -> None:
    w = await world(passkey=True)
    with pytest.raises(PasskeyRequired):
        await w.svc.delete(
            UID,
            "notes",
            rev=await w.rev("notes"),
            confirm="DELETE",
            proof=None,
            fresh_left_s=FRESH,
        )
    assert w.heavy.deleted_calls == []


async def test_passkey_class_with_a_proof_bound_to_this_category_and_rev() -> None:
    w = await world(passkey=True)
    rev = await w.rev("notes")
    proof = await w.rig.proof("privacy_delete", target=f"notes:{rev}")
    out = await w.svc.delete(UID, "notes", rev=rev, confirm=None, proof=proof, fresh_left_s=None)
    assert out.deleted == 2 and w.heavy.items[UID] == []
    assert w.heavy2.items[UID] == ["t1"]  # other categories untouched
    last = (await w.audit_entries())[-1]
    assert "passkey" in last.detail  # type: ignore[attr-defined]


async def test_a_proof_for_category_a_cannot_delete_category_b() -> None:
    w = await world(passkey=True)
    proof = await w.rig.proof("privacy_delete", target=f"notes:{await w.rev('notes')}")
    with pytest.raises(PasskeyRejected):
        await w.svc.delete(
            UID, "things", rev=await w.rev("things"), confirm=None, proof=proof, fresh_left_s=None
        )
    assert w.heavy2.deleted_calls == []


async def test_a_proof_for_an_old_rev_cannot_delete_newer_data() -> None:
    w = await world(passkey=True)
    old = await w.rev("notes")
    proof = await w.rig.proof("privacy_delete", target=f"notes:{old}")
    w.heavy.items[UID].append("n3")
    new = await w.rev("notes")
    with pytest.raises(PasskeyRejected):  # same proof, the caller claims the new rev
        await w.svc.delete(UID, "notes", rev=new, confirm=None, proof=proof, fresh_left_s=None)
    assert w.heavy.deleted_calls == []


async def test_a_replayed_proof_is_refused() -> None:
    w = await world(passkey=True)
    rev = await w.rev("notes")
    proof = await w.rig.proof("privacy_delete", target=f"notes:{rev}")
    await w.svc.delete(UID, "notes", rev=rev, confirm=None, proof=proof, fresh_left_s=None)
    w.heavy.items[UID] = ["again"]
    with pytest.raises(PasskeyRejected):
        await w.svc.delete(
            UID, "notes", rev=await w.rev("notes"), confirm=None, proof=proof, fresh_left_s=None
        )


async def test_a_changed_rev_does_not_burn_the_proof() -> None:
    w = await world(passkey=True)
    rev = await w.rev("notes")
    proof = await w.rig.proof("privacy_delete", target=f"notes:{rev}")
    w.heavy.items[UID].append("n3")
    with pytest.raises(Changed):
        await w.svc.delete(UID, "notes", rev=rev, confirm=None, proof=proof, fresh_left_s=None)
    assert w.heavy.deleted_calls == []


# ---- delete: no passkey in force --------------------------------------------------------------


async def test_without_passkeys_a_passkey_class_delete_needs_typed_delete_and_a_fresh_sign_in() -> (
    None
):
    w = await world()
    rev = await w.rev("notes")
    with pytest.raises(InputRejected):
        await w.svc.delete(UID, "notes", rev=rev, confirm=None, proof=None, fresh_left_s=FRESH)
    with pytest.raises(InputRejected):
        await w.svc.delete(UID, "notes", rev=rev, confirm="delete", proof=None, fresh_left_s=FRESH)
    with pytest.raises(ProofRequired) as e:
        await w.svc.delete(UID, "notes", rev=rev, confirm="DELETE", proof=None, fresh_left_s=0)
    assert e.value.reason == "reauth"
    with pytest.raises(ProofRequired):  # a bearer caller has no sign-in
        await w.svc.delete(UID, "notes", rev=rev, confirm="DELETE", proof=None, fresh_left_s=None)
    assert w.heavy.deleted_calls == []
    out = await w.svc.delete(
        UID, "notes", rev=rev, confirm="DELETE", proof=None, fresh_left_s=FRESH
    )
    assert out.deleted == 2


async def test_with_no_permissions_service_a_passkey_class_delete_still_needs_the_same_proof() -> (
    None
):
    w = await world(with_permissions=False)
    rev = await w.rev("notes")
    with pytest.raises(ProofRequired):
        await w.svc.delete(UID, "notes", rev=rev, confirm="DELETE", proof=None, fresh_left_s=None)
    out = await w.svc.delete(
        UID, "notes", rev=rev, confirm="DELETE", proof=None, fresh_left_s=FRESH
    )
    assert out.deleted == 2
    assert (await w.svc.view(UID)).passkey_in_force is False


# ---- review fixes: H1 single export proof, M2 rev recheck, M4 verify, M5 delete count ---------


async def test_h1_passkey_class_export_needs_a_fresh_sign_in_when_there_is_no_passkey() -> None:
    w = await world()
    for fresh in (None, 0):
        with pytest.raises(ProofRequired) as e:
            await w.svc.export(UID, "notes", proof=None, fresh_left_s=fresh)
        assert e.value.reason == "reauth"
    out = await w.svc.export(UID, "notes", proof=None, fresh_left_s=FRESH)
    assert out["data"]["items"] == ["n1", "n2"]


async def test_h1_simple_class_export_stays_open() -> None:
    w = await world()
    out = await w.svc.export(UID, "places", proof=None, fresh_left_s=None)
    assert out["data"]["items"] == ["home"]


async def test_h1_with_a_passkey_in_force_the_export_needs_a_proof_for_this_category() -> None:
    w = await world(passkey=True)
    with pytest.raises(PasskeyRequired):
        await w.svc.export(UID, "notes", proof=None, fresh_left_s=FRESH)
    wrong = await w.rig.proof("privacy_export", target="export:things")
    with pytest.raises(PasskeyRejected):
        await w.svc.export(UID, "notes", proof=wrong, fresh_left_s=None)
    proof = await w.rig.proof("privacy_export", target="export:notes")
    out = await w.svc.export(UID, "notes", proof=proof, fresh_left_s=None)
    assert out["data"]["items"] == ["n1", "n2"]
    with pytest.raises(PasskeyRejected):  # replay
        await w.svc.export(UID, "notes", proof=proof, fresh_left_s=None)
    all_proof = await w.rig.proof("privacy_export", target="all")  # export-all's proof is not this
    with pytest.raises(PasskeyRejected):
        await w.svc.export(UID, "notes", proof=all_proof, fresh_left_s=None)


async def test_m2_data_that_changes_while_the_proof_is_checked_is_a_conflict() -> None:
    w = await world()

    async def moving(uid: str, purpose: str, target: str, proof: object) -> str | None:
        w.heavy.items[UID].append("added-after-rev-check")
        return "passkey abcd"

    w.svc.permissions = type("P", (), {"check_purpose": staticmethod(moving)})()  # type: ignore[assignment]
    with pytest.raises(Changed):
        await w.svc.delete(
            UID,
            "notes",
            rev=await w.rev("notes"),
            confirm=None,
            proof=None,
            fresh_left_s=None,
        )
    assert w.heavy.items[UID] == ["n1", "n2", "added-after-rev-check"]
    assert w.heavy.deleted_calls == []


async def test_m4_a_delete_that_removed_nothing_reports_what_is_left() -> None:
    w = await world()
    w.simple.noop_delete = True
    out = await w.svc.delete(
        UID, "places", rev=await w.rev("places"), confirm=None, proof=None, fresh_left_s=None
    )
    assert out.deleted == 0 and out.remaining == 1
    last = (await w.audit_entries())[-1]
    assert "places: 0" in last.detail  # type: ignore[attr-defined]


async def test_m4_a_clean_delete_reports_zero_remaining() -> None:
    w = await world()
    out = await w.svc.delete(
        UID, "places", rev=await w.rev("places"), confirm=None, proof=None, fresh_left_s=None
    )
    assert out.deleted == 1 and out.remaining == 0


async def test_m4_a_delete_that_raises_after_removing_some_is_reported_as_partial() -> None:
    w = await world()

    async def half(uid: str) -> int:
        w.simple.items[uid] = w.simple.items[uid][1:]
        raise RuntimeError("boom")

    w.simple.items[UID] = ["a", "b", "c"]
    w.simple.delete = half  # type: ignore[method-assign]
    out = await w.svc.delete(
        UID, "places", rev=await w.rev("places"), confirm=None, proof=None, fresh_left_s=None
    )
    assert out.deleted == 1 and out.remaining == 2
    last = (await w.audit_entries())[-1]
    assert "places: 1" in last.detail  # type: ignore[attr-defined]


async def test_m5_the_delete_count_is_what_the_delete_removes() -> None:
    w = await world()
    view = await w.svc.view(UID)
    notes = next(c for c in view.categories if c.id == "notes")
    assert notes.delete_count == 2
