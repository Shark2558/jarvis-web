# tests/test_r2_seams.py
"""R2 I0 seams: the shared hooks the four R2 workstreams build on (docs/plans/r2-memory-vault.md).

The keyring, the privacy and vault ports, tick jobs and their hook in the scheduler tick, the
Recently deleted kinds and purgers, the vault_expiry alert kind, the three new passkey purposes
(`check_purpose`), the five permission rows, `Tool.activity_words`, settings and the console words.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from telegram_fakes import UID as TG_UID
from telegram_fakes import build_world
from test_permissions_service import UID, Rig

from jarvis.alerts import AlertKind
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.vault import TokenCipher, VaultError
from jarvis.keyring import KEY_ID, PURPOSES, Keyring
from jarvis.permissions.errors import PasskeyRejected, PasskeyRequired
from jarvis.permissions.groups import GROUPS, PermissionRejected, get_group, groups_for
from jarvis.permissions.models import ChallengeRequest
from jarvis.privacy import CategoryView, PrivacyRegistry, PrivacySource
from jarvis.storage.docs import MemoryDocs
from jarvis.ticks import MAX_BUDGET_S, TickJob, run_jobs
from jarvis.tools.base import Tool
from jarvis.undo.models import (
    IN_PLACE_KINDS,
    KIND_WORDS,
    KINDS,
    PASSKEY_PURGE_KINDS,
    UndoRef,
)
from jarvis.undo.service import PurgeFailed, Restored, UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.vault import (
    MAX_FILE_BYTES,
    VAULT_MIMES,
    IntakeResult,
    NoVaultIntake,
    VaultIntake,
)

R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
STATIC = ROOT / "api" / "static"
KEY = bytes(range(1, 33))


# ---- keyring ---------------------------------------------------------------------------------


def _hkdf(purpose: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"jarvis-keyring-v1",
        info=f"jarvis/{purpose}/v1".encode(),
    ).derive(KEY)


def test_purpose_keys_are_pinned_hkdf_outputs() -> None:
    ring = Keyring(KEY)
    assert KEY_ID == "tk1" and ring.kid == "tk1"
    for purpose in PURPOSES:
        blob = TokenCipher(_hkdf(purpose)).encrypt(b"hello", aad="a")
        assert ring.cipher(purpose).decrypt(blob, aad="a") == b"hello"


def test_purposes_are_allow_listed_and_independent() -> None:
    r2 = {"vault", "vault_index", "notes", "belongings", "tickets"}
    assert r2 <= set(PURPOSES)  # R3 I0 adds its own (tests/test_r3_seams.py pins the whole set)
    ring = Keyring(KEY)
    with pytest.raises(VaultError):
        ring.cipher("tokens")
    with pytest.raises(VaultError):
        ring.mac("nope", b"x")
    blob = ring.cipher("notes").encrypt(b"x", aad="a")
    with pytest.raises(VaultError):
        ring.cipher("belongings").decrypt(blob, aad="a")
    root_blob = TokenCipher(KEY).encrypt(b"x", aad="a")  # the raw root is not a purpose key
    with pytest.raises(VaultError):
        ring.cipher("vault").decrypt(root_blob, aad="a")


def test_root_must_be_32_random_looking_bytes() -> None:
    for bad in (b"", b"x" * 31, b"\x00" * 32, b"ab" * 16):
        with pytest.raises(VaultError):
            Keyring(bad)


def test_the_root_never_shows_in_repr() -> None:
    assert base64.b64encode(KEY).decode() not in repr(Keyring(KEY))
    assert str(KEY) not in repr(Keyring(KEY))


def test_wrap_and_unwrap_a_data_key_with_aad() -> None:
    ring = Keyring(KEY)
    dek, other = ring.new_dek(), ring.new_dek()
    assert len(dek) == 32 and dek != other
    wrapped = ring.wrap(dek, aad="vault/dek/u/v_1/f_1/v1")
    assert dek not in base64.b64decode(wrapped)
    assert ring.unwrap(wrapped, aad="vault/dek/u/v_1/f_1/v1") == dek
    with pytest.raises(VaultError):
        ring.unwrap(wrapped, aad="vault/dek/u/v_1/f_2/v1")
    with pytest.raises(VaultError):
        Keyring(bytes(range(2, 34))).unwrap(wrapped, aad="vault/dek/u/v_1/f_1/v1")
    short = ring.cipher("vault").encrypt(b"short", aad="a")  # authentic, but not a data key
    with pytest.raises(VaultError):
        ring.unwrap(short, aad="a")


def test_mac_is_keyed_domain_separated_and_checkable() -> None:
    ring = Keyring(KEY)
    tag = ring.mac("tickets", b"abc")
    assert tag == ring.mac("tickets", "abc") and len(tag) == 64
    assert tag != ring.mac("notes", b"abc") and tag != ring.mac("tickets", b"abd")
    assert tag != hmac.new(_hkdf("tickets"), b"abc", hashlib.sha256).hexdigest()
    assert ring.mac_matches("tickets", b"abc", tag)
    assert not ring.mac_matches("tickets", b"abc", "0" * 64)
    assert not ring.mac_matches("tickets", b"abc", "")
    assert Keyring(bytes(range(2, 34))).mac("tickets", b"abc") != tag


def test_from_settings() -> None:
    assert Keyring.from_settings(Settings(_env_file=None)) is None
    key = base64.b64encode(KEY).decode()
    ring = Keyring.from_settings(Settings(_env_file=None, token_key=key))
    assert ring is not None
    assert ring.mac("tickets", b"x") == Keyring(KEY).mac("tickets", b"x")


# ---- privacy port ----------------------------------------------------------------------------


def _view(cid: str, **kw: Any) -> CategoryView:
    base: dict[str, Any] = {
        "id": cid,
        "section": "S",
        "label": cid.title(),
        "what": "w",
        "count": 1,
        "unit": "items",
        "retention": "r",
        "where": "w",
    }
    return CategoryView(**{**base, **kw})


class _Src:
    section = "Notes"

    def __init__(self, cid: str, *, count: int = 1, fail: bool = False, slow: bool = False) -> None:
        self.id, self.label = cid, cid.title()
        self.count, self.fail, self.slow = count, fail, slow

    async def describe(self, uid: str) -> CategoryView:
        if self.slow:
            await asyncio.sleep(5)
        if self.fail:
            raise RuntimeError("firestore says SECRET-WORDS")
        return _view(self.id, count=self.count)

    async def export(self, uid: str) -> dict[str, Any] | None:
        return {"n": self.count}

    async def delete(self, uid: str) -> int:
        return self.count


def test_category_view_defaults_and_delete_classes() -> None:
    v = _view("x")
    assert v.delete == "none" and v.available is True and v.encrypted_by_jarvis is False
    assert v.export is False and v.recoverable is False and v.note == "" and v.rev == ""
    for cls in ("none", "simple", "confirm", "passkey"):
        assert _view("x", delete=cls).delete == cls
    with pytest.raises(ValidationError):
        _view("x", delete="sometimes")


def test_a_source_satisfies_the_port() -> None:
    assert isinstance(_Src("a"), PrivacySource)


async def test_registry_describes_all_in_order_and_a_failure_keeps_its_row() -> None:
    reg = PrivacyRegistry(budget_s=0.2)
    reg.register(_Src("a"))
    reg.register(_Src("b", fail=True))
    reg.register(_Src("c", slow=True))
    reg.register(_Src("d", count=4))
    views = await reg.describe_all("u")
    assert [v.id for v in views] == ["a", "b", "c", "d"]
    assert [v.available for v in views] == [True, False, False, True]
    bad = views[1]
    assert bad.label == "B" and bad.section == "Notes" and bad.count is None
    assert bad.delete == "none" and "check right now" in bad.note
    assert "SECRET-WORDS" not in bad.model_dump_json()
    assert views[3].count == 4


async def test_registry_refuses_duplicates_and_mismatched_views() -> None:
    reg = PrivacyRegistry()
    reg.register(_Src("a"))
    with pytest.raises(ValueError):
        reg.register(_Src("a"))

    class Liar(_Src):
        async def describe(self, uid: str) -> CategoryView:
            return _view("someone_else")

    reg.register(Liar("b"))
    views = await reg.describe_all("u")
    assert [v.id for v in views] == ["a", "b"] and views[1].available is False
    assert reg.get("a") is not None and reg.get("zzz") is None and reg.ids() == ["a", "b"]


# ---- tick jobs -------------------------------------------------------------------------------


class _Job:
    def __init__(self, name: str, *, budget_s: float = 1.0, result: Any = None) -> None:
        self.name, self.budget_s = name, budget_s
        self.result = {"done": 1} if result is None else result
        self.seen: list[tuple[str, ...]] = []

    async def run(self, owners: Any) -> dict[str, int]:
        self.seen.append(tuple(owners))
        if isinstance(self.result, BaseException):
            raise self.result
        if callable(self.result):
            await self.result()
        return self.result  # type: ignore[no-any-return]


async def _forever() -> None:
    await asyncio.sleep(30)


async def test_run_jobs_reports_ok_and_failed_per_job_and_never_raises() -> None:
    good = _Job("vault_reminders")
    boom = _Job("inbox", result=RuntimeError("PRIVATE-TEXT"))
    slow = _Job("slow", budget_s=0.05, result=_forever)
    last = _Job("last")
    out = await run_jobs([good, boom, slow, last], ["u1", "u2"])
    assert out == {"vault_reminders": "ok", "inbox": "failed", "slow": "failed", "last": "ok"}
    assert good.seen == [("u1", "u2")] and last.seen == [("u1", "u2")]  # a failure stops no one


async def test_run_jobs_with_nothing_or_garbage() -> None:
    assert await run_jobs((), ["u"]) == {}
    assert await run_jobs(None, ["u"]) == {}  # type: ignore[arg-type]
    out = await run_jobs([object(), _Job("ok")], ["u"])  # type: ignore[list-item]
    assert out == {"ok": "ok"}  # a job with no name is skipped, not reported
    bad_budget = _Job("b", budget_s=float("nan"))
    assert (await run_jobs([bad_budget], ["u"]))["b"] == "failed"
    assert bad_budget.seen == []
    assert MAX_BUDGET_S <= 60


async def test_a_bad_result_shape_is_a_failure_and_a_duplicate_name_fails_both() -> None:
    assert await run_jobs([_Job("a", result={"n": "x"})], ["u"]) == {"a": "failed"}
    out = await run_jobs([_Job("same"), _Job("same", result=RuntimeError("x"))], ["u"])
    assert out == {"same": "failed"}


async def test_tick_reports_failed_when_every_owner_fails() -> None:
    """R2 review M1: a job isolates owners and counts the ones that failed; any such count makes
    the job "failed" in the tick answer (never a silent "ok"). Zero failures stay "ok"."""
    every = _Job("vault_chunks", result={"owners": 2, "swept": 0, "failed": 2})
    one = _Job("digilocker_inbox", result={"owners": 1, "imported": 3, "failed": 1})
    none = _Job("vault_unlocks", result={"owners": 2, "swept": 4, "failed": 0})
    out = await run_jobs([every, one, none], ["u1", "u2"])
    assert out == {"vault_chunks": "failed", "digilocker_inbox": "failed", "vault_unlocks": "ok"}


def test_a_job_satisfies_the_port() -> None:
    assert isinstance(_Job("x"), TickJob)


async def test_the_scheduler_tick_runs_the_jobs_beside_the_sweeps(monkeypatch: Any) -> None:
    from types import SimpleNamespace

    from jarvis.api import brief as api_brief
    from jarvis.brief.models import TickResult

    class Svc:
        owners = ("u1",)

        async def tick(self) -> TickResult:
            return TickResult(checked=1)

    class Brain:
        async def sweep_memory(self, owners: Any) -> None:
            return None

    job = _Job("vault_reminders")
    state = SimpleNamespace(brain=Brain(), tick_jobs=[job, _Job("inbox", result=RuntimeError("x"))])
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    res = await api_brief.tick(request, Svc())  # type: ignore[arg-type]
    assert res.sweeps["memory"] == "ok"
    assert res.sweeps["vault_reminders"] == "ok" and res.sweeps["inbox"] == "failed"
    assert job.seen == [("u1",)]
    bare = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(brain=Brain())))
    res = await api_brief.tick(bare, Svc())  # type: ignore[arg-type]
    assert res.sweeps == {"memory": "ok"}  # no tick_jobs: nothing extra


# ---- vault port ------------------------------------------------------------------------------


def test_vault_constants() -> None:
    assert VAULT_MIMES == ("application/pdf", "image/jpeg", "image/png")
    assert MAX_FILE_BYTES == 10 * 1024 * 1024


async def test_vault_intake_port_and_the_off_switch() -> None:
    class Fake:
        async def intake(
            self, uid: str, data: bytes, *, source: str, drive_id: str | None = None
        ) -> IntakeResult:
            return IntakeResult(status="added", item_id="v_" + "a" * 12)

    assert isinstance(Fake(), VaultIntake)
    off = NoVaultIntake()
    res = await off.intake("u", b"%PDF", source="digilocker", drive_id="d1")
    assert res.status == "skipped" and res.item_id is None and res.code == "unavailable"
    assert res.message and "vault" in res.message.lower()
    with pytest.raises(ValidationError):
        IntakeResult(status="weird")  # type: ignore[arg-type]


# ---- Recently deleted: kinds, purgers --------------------------------------------------------

NEW_KINDS = ("vault_item", "note", "thing")
NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class _Purger:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.purged: list[str] = []

    async def purge(self, uid: str, item: Any) -> None:
        if self.fail:
            raise RuntimeError("storage down")
        self.purged.append(item.snapshot["ref"])


class _InPlace:
    async def restore(self, uid: str, item: Any, *, outside: bool = False) -> Restored:
        return Restored(new_id=item.snapshot["ref"])


def _bin() -> tuple[UndoBin, _Clock, DeletedStore]:
    clock = _Clock()
    store = DeletedStore(MemoryDocs())
    return UndoBin(store, clock=clock), clock, store


def test_new_kinds_have_words_and_an_in_place_restore() -> None:
    for k in NEW_KINDS:
        assert k in KINDS and k in KIND_WORDS
    assert KIND_WORDS["event"] == "event" and KIND_WORDS["task"] == "to-do"
    assert IN_PLACE_KINDS == frozenset(NEW_KINDS)
    assert PASSKEY_PURGE_KINDS == frozenset(NEW_KINDS)
    ref = UndoRef.from_result({"undo_id": "del_" + "a" * 20, "kind": "note"})
    assert ref is not None and ref.kind == "note"
    assert UndoRef.from_result({"undo_id": "del_" + "a" * 20, "kind": "face"}) is None


async def test_a_new_kind_is_kept_and_restored_in_place_without_new_copy_words() -> None:
    bin_, _, _ = _bin()
    bin_.register("note", _InPlace())
    item = await bin_.keep(UID, "note", "A note from 3 Nov", {"ref": "n_abc"}, owner_authored=True)
    out = await bin_.restore(UID, item.id)
    assert out.status.value == "restored" and out.new_id == "n_abc"
    assert "new copy" not in out.message and "note" in out.message
    again = await bin_.restore(UID, item.id)
    assert again.status.value == "already_restored"
    bin_.register("event", _InPlace())  # an old kind keeps its "new copy" words
    ev = await bin_.keep(UID, "event", "Dentist", {"ref": "e1"})
    assert "new copy" in (await bin_.restore(UID, ev.id)).message


async def test_purge_calls_the_kinds_purger_first_and_then_removes_the_entry() -> None:
    bin_, _, store = _bin()
    purger = _Purger()
    bin_.register("vault_item", _InPlace(), purger)
    item = await bin_.keep(UID, "vault_item", "Vault item: passport", {"ref": "v_1"})
    assert await bin_.purge(UID, item.id) is True
    assert purger.purged == ["v_1"] and await store.get(UID, item.id) is None
    assert await bin_.purge(UID, item.id) is False  # gone


async def test_a_kind_without_a_purger_just_loses_its_entry() -> None:
    bin_, _, store = _bin()
    item = await bin_.keep(UID, "task", "t", {"id": "1"})
    assert await bin_.purge(UID, item.id) is True and await store.get(UID, item.id) is None


async def test_a_failed_purge_keeps_the_entry_and_raises_plain_words() -> None:
    bin_, _, store = _bin()
    bin_.register("thing", _InPlace(), _Purger(fail=True))
    item = await bin_.keep(UID, "thing", "Thing: passport", {"ref": "t_1"})
    with pytest.raises(PurgeFailed) as err:
        await bin_.purge(UID, item.id)
    assert "storage down" not in str(err.value) and str(err.value)
    assert await store.get(UID, item.id) is not None


async def test_sweep_purges_expired_items_and_keeps_those_whose_purge_failed() -> None:
    bin_, clock, store = _bin()
    ok, bad = _Purger(), _Purger(fail=True)
    bin_.register("vault_item", _InPlace(), ok)
    bin_.register("thing", _InPlace(), bad)
    a = await bin_.keep(UID, "vault_item", "v", {"ref": "v_1"})
    b = await bin_.keep(UID, "thing", "t", {"ref": "t_1"})
    c = await bin_.keep(UID, "task", "task", {})
    fresh_at = clock.now + timedelta(days=29)
    clock.now += timedelta(days=31)
    d = await bin_.keep(UID, "note", "still fresh", {"ref": "n_1"})
    assert fresh_at < clock.now
    gone = await bin_.sweep([UID, "u_other"])
    assert gone == 2  # a (purged) and c (no purger)
    assert ok.purged == ["v_1"]
    assert await store.get(UID, a.id) is None and await store.get(UID, c.id) is None
    assert await store.get(UID, b.id) is not None and await store.get(UID, d.id) is not None


# ---- alerts ----------------------------------------------------------------------------------


def test_vault_expiry_is_an_alert_kind() -> None:
    from typing import get_args

    assert "vault_expiry" in get_args(AlertKind)


async def test_telegram_refuses_a_kind_it_has_no_switch_for() -> None:
    w = build_world()
    await w.pair()
    res = await w.service.alerts.send(
        TG_UID, "JARVIS: a document in your vault expires in 30 days.", kind="vault_expiry"
    )
    assert res.sent is False and "off" in res.reason.lower() and w.bot.texts == []
    assert (await w.service.alerts.send(TG_UID, "Test.", kind="test")).sent is True


# ---- passkey purposes ------------------------------------------------------------------------


async def _with_passkey() -> Rig:
    rig = Rig()
    await rig.register()
    assert await rig.svc.passkey_required(UID)
    return rig


async def test_check_purpose_without_passkeys_in_force_passes_nothing_to_prove() -> None:
    rig = Rig()
    assert await rig.svc.check_purpose(UID, "vault_unlock", "", None) is None
    assert await rig.svc.check_purpose(UID, "privacy_delete", "memory:3", None) is None


async def test_check_purpose_needs_a_proof_bound_to_purpose_and_target() -> None:
    rig = await _with_passkey()
    with pytest.raises(PasskeyRequired):
        await rig.svc.check_purpose(UID, "privacy_delete", "memory:3", None)
    proof = await rig.proof("privacy_delete", target="memory:3")
    note = await rig.svc.check_purpose(UID, "privacy_delete", "memory:3", proof)
    assert note is not None and note.startswith("passkey ")
    with pytest.raises(PasskeyRejected):  # single use
        await rig.svc.check_purpose(UID, "privacy_delete", "memory:3", proof)


async def test_a_proof_for_one_target_or_purpose_cannot_serve_another() -> None:
    rig = await _with_passkey()
    for purpose, made_for, used_for in (
        ("privacy_delete", "memory:3", "notes:3"),
        ("privacy_delete", "memory:3", "memory:4"),
    ):
        proof = await rig.proof(purpose, target=made_for)
        with pytest.raises(PasskeyRejected):
            await rig.svc.check_purpose(UID, purpose, used_for, proof)
    proof = await rig.proof("vault_unlock")
    with pytest.raises(PasskeyRejected):
        await rig.svc.check_purpose(UID, "privacy_export", "", proof)
    proof = await rig.proof("privacy_export")
    with pytest.raises(PasskeyRejected):
        await rig.svc.check_purpose(UID, "vault_unlock", "", proof)
    rows = await rig.audit_rows()
    assert any(t == "passkey" and o == "check_refused" for t, o, _ in rows)


async def test_a_proof_for_a_purpose_cannot_stand_in_for_an_approval() -> None:
    rig = await _with_passkey()
    card = rig.card()
    proof = await rig.proof("vault_unlock")
    with pytest.raises(PasskeyRejected):
        await rig.svc.check_approval(UID, card, proof)


async def test_check_purpose_fails_closed() -> None:
    rig = await _with_passkey()
    with pytest.raises(PermissionRejected):  # not one of the three purposes
        await rig.svc.check_purpose(UID, "approve", "x", None)
    with pytest.raises(PermissionRejected):  # a delete must name what it deletes
        await rig.svc.check_purpose(UID, "privacy_delete", "", None)

    # unreadable passkey data counts as in force and then refuses the proof
    async def boom(uid: str) -> Any:
        from jarvis.permissions.errors import PasskeyDataUnreadable

        raise PasskeyDataUnreadable("x")

    rig.svc.passkeys.owned = boom  # type: ignore[method-assign]
    with pytest.raises(PasskeyRequired):
        await rig.svc.check_purpose(UID, "vault_unlock", "", None)


async def test_challenge_target_is_validated_and_required_for_a_delete() -> None:
    rig = await _with_passkey()
    with pytest.raises(ValidationError):
        ChallengeRequest(purpose="privacy_delete", target="x" * 65)
    with pytest.raises(ValidationError):
        ChallengeRequest(purpose="privacy_delete", target="a\x00b")
    with pytest.raises(PermissionRejected):
        await rig.svc.challenge(
            UID,
            ChallengeRequest(purpose="privacy_delete"),
            approvals=rig.lookup,  # type: ignore[arg-type]
        )
    ch = await rig.svc.challenge(
        UID,
        ChallengeRequest(purpose="vault_unlock"),
        approvals=rig.lookup,  # type: ignore[arg-type]
    )
    assert ch.challenge_id


# ---- permission rows -------------------------------------------------------------------------

ROWS = {
    "vault_read": ("Vault", "Look at your vault list", R1, "vault_list"),
    "vault_change": ("Vault", "Change vault dates", R2, "vault_set_dates"),
    "notes_read": ("Notes", "Search and read your notes and links", R1, "kb_search"),
    "notes_change": ("Notes", "Save, change and delete notes and links", R2, "kb_update"),
    "belongings": ("Things", "Remember where you keep things", R2, "belongings_where"),
}


def test_five_rows_sit_between_drive_and_maps() -> None:
    ids = [g.id for g in GROUPS]
    # R4 I0: + 5 Vitals..Connectors rows; R11 I0: + 6 helper rows (D16); R11.1 I0: + 2
    assert len(ids) == 46
    at = ids.index("drive")
    assert ids[at + 1 : at + 6] == list(ROWS) and ids.index("maps") > at + 5
    assert ids[-1] == "youtube"


@pytest.mark.parametrize("gid", list(ROWS))
def test_row_texts_risks_and_choices(gid: str) -> None:
    section, label, risk, _ = ROWS[gid]
    g = get_group(gid)
    assert g is not None and (g.section, g.label, g.risk) == (section, label, risk)
    assert not g.irreversible and len(g.choices) == 3
    assert g.hint and "$" not in g.hint


def test_rows_catch_exactly_their_tools() -> None:
    def rows(tool: str, risk: ActionRisk) -> set[str]:
        return {g.id for g in groups_for(tool, risk)}

    assert rows("vault_list", R1) == {"vault_read"}
    assert rows("vault_expiring", R1) == {"vault_read"}
    assert rows("vault_set_dates", R2) == {"vault_change"}
    assert rows("kb_search", R1) == {"notes_read"} and rows("kb_read", R1) == {"notes_read"}
    for tool in ("kb_add_note", "kb_save_link", "kb_update", "kb_remove"):
        assert rows(tool, R2) == {"notes_change"}
    for tool in ("belongings_where", "belongings_put", "belongings_remove"):
        assert rows(tool, R1) == rows(tool, R2) == {"belongings"}
    for older in ("memory_search", "doc_read", "drive_read", "web_search"):
        assert not rows(older, R1) & set(ROWS)


# ---- tool activity words ---------------------------------------------------------------------


def test_tool_activity_words_default_to_none() -> None:
    async def run(_: dict[str, Any]) -> Any:
        return {}

    t = Tool(name="x", description="d", input_schema={}, risk=R1, run=run)
    assert t.activity_words is None
    t2 = Tool(
        name="x",
        description="d",
        input_schema={},
        risk=R1,
        run=run,
        activity_words="Looked at your vault list",
    )
    assert t2.activity_words == "Looked at your vault list"


# ---- config ----------------------------------------------------------------------------------


def test_r2_settings_defaults_and_bounds() -> None:
    s = Settings(_env_file=None)
    assert (s.vault_enabled, s.notes_enabled, s.belongings_enabled) == (True, True, True)
    assert (s.vault_max_total_mb, s.vault_unlock_minutes) == (150, 10)
    for field, good, bad in (
        ("vault_max_total_mb", (10, 500), (9, 501)),
        ("vault_unlock_minutes", (2, 30), (1, 31)),
    ):
        for v in good:
            assert getattr(Settings(_env_file=None, **{field: v}), field) == v
        for v in bad:
            with pytest.raises(ValidationError):
                Settings(_env_file=None, **{field: v})


# ---- console ---------------------------------------------------------------------------------


def test_deleted_panel_knows_the_new_kinds() -> None:
    js = (STATIC / "console-deleted.js").read_text()
    for kind in NEW_KINDS:
        assert f"{kind}:" in js
    assert "Vault document" in js and "Note" in js and "Thing" in js


def test_passkey_prove_is_exposed_for_the_new_purposes_only() -> None:
    js = (STATIC / "console-permissions.js").read_text()
    assert "prove: (purpose, target)" in js
    for purpose in ("vault_unlock", "privacy_delete", "privacy_export"):
        assert purpose in js
    assert "target" in js.split("prove: (purpose, target)")[1][:400]


def test_every_console_script_stays_within_800_lines() -> None:
    for path in STATIC.glob("console*.js"):
        assert len(path.read_text().splitlines()) <= 800, path.name


def test_new_seam_files_are_ascii() -> None:
    names = ("keyring.py", "ticks.py", "privacy/__init__.py", "privacy/ports.py")
    names += ("vault/__init__.py", "vault/ports.py")
    for name in names:
        assert (ROOT / name).read_text().isascii(), name
