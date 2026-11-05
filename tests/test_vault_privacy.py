# tests/test_vault_privacy.py -- R2 D14: the vault's privacy row
from __future__ import annotations

from vault_fakes import JPEG, OTHER, PDF, UID, make, scan

from jarvis.privacy import PrivacyRegistry, PrivacySource
from jarvis.vault.privacy import VaultPrivacy


async def test_describe_counts_only_this_owner_and_never_leaks() -> None:
    svc, docs, _ = make()
    h = await svc.add_holder(UID, "Anjali")
    await svc.add_file(UID, PDF, type_hint="passport")
    await svc.add_file(UID, JPEG, type_hint="pan", holder_id=h.id)
    await svc.add_file(OTHER, PDF)
    src = VaultPrivacy(svc)
    assert isinstance(src, PrivacySource)
    view = await src.describe(UID)
    assert view.id == "vault" and view.count == 2 and view.unit == "documents"
    assert view.delete == "passkey" and view.encrypted_by_jarvis and not view.recoverable
    assert view.size_hint == "0.0 MB of 150 MB"
    assert "you: 1" in view.note and "Anjali: 1" in view.note
    assert view.rev and not scan(docs, "Anjali")


async def test_rev_changes_when_the_data_changes() -> None:
    svc, _, _ = make()
    src = VaultPrivacy(svc)
    before = (await src.describe(UID)).rev
    await svc.add_file(UID, PDF)
    assert (await src.describe(UID)).rev != before


async def test_export_has_metadata_but_no_files_or_ids() -> None:
    svc, _, _ = make()
    item = (await svc.add_file(UID, PDF, type_hint="passport")).item
    await svc.update(UID, item.id, {"last4": "4821"})
    out = await VaultPrivacy(svc).export(UID)
    assert out is not None and out["documents"][0]["last4"] == "4821"
    assert "files" not in out["documents"][0] and "Vault" in out["note"]


async def test_delete_removes_everything_and_only_for_that_owner() -> None:
    svc, docs, _ = make()
    await svc.add_file(UID, PDF)
    await svc.add_file(OTHER, JPEG)
    assert await VaultPrivacy(svc).delete(UID) == 1
    assert (await VaultPrivacy(svc).describe(UID)).count == 0
    assert (await VaultPrivacy(svc).describe(OTHER)).count == 1
    assert not [p for p in docs._data if UID in p]


async def test_registers_with_the_registry() -> None:
    svc, _, _ = make()
    reg = PrivacyRegistry()
    reg.register(VaultPrivacy(svc))
    (view,) = await reg.describe_all(UID)
    assert view.available and view.id == "vault"
