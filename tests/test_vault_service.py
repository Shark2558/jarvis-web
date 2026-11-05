# tests/test_vault_service.py -- R2 D1-D8: intake, proposal, confirm, caps, delete/restore/purge
from __future__ import annotations

import datetime as dt

import pytest
from vault_fakes import JPEG, NOW, OTHER, PDF, PNG, UID, Bin, make, pdf_with_text, scan

from jarvis.documents.extract import extract
from jarvis.vault.models import VaultRejected, VaultUnavailable
from jarvis.vault.ports import IntakeResult, VaultIntake
from jarvis.vault.service import VaultPurger, VaultRestorer, sniff_mime

DL_TEXT = "Driving Licence\nValid Till: 14-03-2034\nKL-07-2015-0001234"


async def real_extract(data: bytes, kind: str):  # the real extractor, in-process
    return extract(data, kind)


async def test_magic_bytes_and_types() -> None:
    assert sniff_mime(PDF) == "application/pdf" and sniff_mime(JPEG) == "image/jpeg"
    assert sniff_mime(PNG) == "image/png" and sniff_mime(b"GIF89a") is None


async def test_unsupported_empty_and_too_big_are_refused_in_plain_words() -> None:
    svc, docs, _ = make()
    with pytest.raises(VaultRejected) as e:
        await svc.add_file(UID, b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    assert e.value.status == 415 and "PDF or JPEG" in e.value.detail
    with pytest.raises(VaultRejected) as e:
        await svc.add_file(UID, b"")
    assert e.value.code == "empty"
    with pytest.raises(VaultRejected) as e:
        await svc.add_file(UID, PDF + b"0" * (10 * 1024 * 1024))
    assert e.value.status == 413
    assert not docs._data


async def test_add_stores_ciphertext_only_and_opens_back() -> None:
    svc, docs, _ = make(text=DL_TEXT)
    needle = b"SECRET-ID-0001234-BYTES"
    data = PDF + needle * 20
    added = await svc.add_file(UID, data, type_hint="driving_licence")
    assert added.item.type == "driving_licence" and not added.duplicate
    assert not scan(docs, needle) and not scan(docs, "0001234") and not scan(docs, "Valid Till")
    dl = await svc.stream_file(UID, added.item.id, added.item.files[0].fid)
    out = b"".join([c async for c in dl.body])
    assert out == data and dl.filename == "driving-licence-you-1.pdf"


async def test_proposal_is_not_applied_until_confirm() -> None:
    svc, _, _ = make(text=DL_TEXT)
    added = await svc.add_file(UID, PDF)
    view = (await svc.view(UID))["items"][0]
    assert added.item.type == "driving_licence"
    assert view["needs_check"] and view["expires_on"] is None and view["last4"] is None
    assert view["proposal"]["expires_on"] == "2034-03-14" and view["proposal"]["last4"] == "1234"
    assert (await svc.due(UID, within_days=4000)) == []  # unconfirmed: no reminders
    done = await svc.update(UID, added.item.id, {"confirm": True})
    assert done["expires_on"] == "2034-03-14" and done["ends"] == "••1234"
    assert done["dates_confirmed"] and done["proposal"] is None
    assert len(await svc.due(UID, within_days=4000)) == 1


async def test_owner_values_win_over_the_proposal_on_confirm() -> None:
    svc, _, _ = make(text=DL_TEXT)
    added = await svc.add_file(UID, PDF)
    done = await svc.update(UID, added.item.id, {"confirm": True, "expires_on": "2035-01-01"})
    assert done["expires_on"] == "2035-01-01"


async def test_a_pdf_without_text_gives_no_proposal() -> None:
    async def none(data: bytes, kind: str):
        raise RuntimeError("no text layer")

    svc, _, _ = make()
    svc._extract = none
    added = await svc.add_file(UID, PDF)
    assert added.proposal is None and added.item.type == "other"


async def test_images_get_no_proposal() -> None:
    svc, _, _ = make(text=DL_TEXT)
    added = await svc.add_file(UID, JPEG, type_hint="passport")
    assert added.proposal is None and added.item.type == "passport"


async def test_real_pdf_end_to_end() -> None:
    svc, _, _ = make()
    svc._extract = real_extract
    pdf = pdf_with_text(["Driving Licence", "Valid Till: 14-03-2034", "KL-07-2015-0001234"])
    added = await svc.add_file(UID, pdf)
    assert added.proposal is not None and added.proposal.expires_on == dt.date(2034, 3, 14)


async def test_same_file_twice_is_a_duplicate() -> None:
    svc, docs, _ = make()
    first = await svc.add_file(UID, PDF)
    again = await svc.add_file(UID, PDF)
    assert again.duplicate and again.item.id == first.item.id
    assert len([p for p in docs._data if "vault_chunks" in p]) == 1


async def test_second_file_on_an_item_and_the_two_file_cap() -> None:
    svc, _, _ = make()
    first = await svc.add_file(UID, PDF)
    back = await svc.add_file(UID, JPEG, item_id=first.item.id)
    assert len(back.item.files) == 2 and back.item.id == first.item.id
    with pytest.raises(VaultRejected) as e:
        await svc.add_file(UID, PNG, item_id=first.item.id)
    assert e.value.code == "files_full" and e.value.status == 409


async def test_item_cap_and_total_cap() -> None:
    svc, _, _ = make(max_mb=10)
    await svc.add_file(UID, PDF + b"a" * 5_000_000)
    with pytest.raises(VaultRejected) as e:
        await svc.add_file(UID, PDF + b"b" * 6_000_000)
    assert e.value.code == "vault_full"
    svc2, _, _ = make()
    for n in range(100):
        await svc2.add_file(UID, PDF + str(n).encode())
    with pytest.raises(VaultRejected) as e2:
        await svc2.add_file(UID, PDF + b"extra")
    assert e2.value.code == "vault_full"


async def test_failed_chunk_write_leaves_nothing_visible() -> None:
    svc, docs, store = make()

    async def fail(*a: object, **k: object) -> None:
        raise VaultUnavailable("down")

    store.put_chunks = fail  # type: ignore[method-assign]
    with pytest.raises(VaultUnavailable):
        await svc.add_file(UID, PDF)
    assert (await svc.view(UID))["items"] == []
    _, index = await store.load(UID)
    assert index.pending == ()


async def test_intake_port_returns_plain_results() -> None:
    svc, _, _ = make()
    assert isinstance(svc, VaultIntake)
    got = await svc.intake(UID, PDF, source="digilocker", drive_id="d1")
    assert got == IntakeResult(status="added", item_id=got.item_id) and got.item_id
    view = (await svc.view(UID))["items"][0]
    assert view["from_digilocker"] and view["title"] == "Document"
    assert (await svc.intake(UID, PDF, source="digilocker")).status == "duplicate"
    bad = await svc.intake(UID, b"nope", source="digilocker")
    assert bad.status == "skipped" and bad.code == "unsupported" and "nope" not in bad.message


async def test_edits_validate_in_plain_words() -> None:
    svc, _, _ = make()
    item = (await svc.add_file(UID, PDF, type_hint="passport")).item
    for patch, code in [
        ({"last4": "123456"}, "invalid"),
        ({"title": "ABCDE1234F"}, "sensitive"),
        ({"note": "aadhaar 2363 1234 5678"}, "sensitive"),
        ({"type": "nonsense"}, "invalid"),
        ({"expires_on": "12/02/2031"}, "invalid"),
        ({"reminders": [5]}, "invalid"),
        ({"holder_id": "h_deadbeef"}, "invalid"),
        ({"title": ""}, "invalid"),
        ({"title": "x" * 61}, "invalid"),
    ]:
        with pytest.raises(VaultRejected) as e:
            await svc.update(UID, item.id, patch)
        assert e.value.code == code, patch
    with pytest.raises(VaultRejected) as e:
        await svc.update(UID, item.id, {"last4": "123456"})
    assert "only the last 4" in e.value.detail
    ok = await svc.update(UID, item.id, {"last4": " ab-12 ", "reminders": [7, 90, 90]})
    assert ok["last4"] == "AB12" and ok["reminders"] == [90, 7]


async def test_expiry_before_issue_refused_and_changed_dates_need_confirming() -> None:
    svc, _, _ = make()
    item = (await svc.add_file(UID, PDF)).item
    with pytest.raises(VaultRejected):
        await svc.update(UID, item.id, {"issued_on": "2030-01-01", "expires_on": "2029-01-01"})
    ok = await svc.update(UID, item.id, {"expires_on": "2031-01-01", "confirm": True})
    assert ok["dates_confirmed"]
    changed = await svc.update(UID, item.id, {"expires_on": "2032-01-01"})
    assert not changed["dates_confirmed"]


async def test_set_dates_confirms() -> None:
    svc, _, _ = make()
    item = (await svc.add_file(UID, PDF, type_hint="vehicle_insurance")).item
    done = await svc.set_dates(UID, item.id, expires_on="2027-03-03")
    assert done["dates_confirmed"] and done["days_left"] == (dt.date(2027, 3, 3) - NOW.date()).days


async def test_holders() -> None:
    svc, _, _ = make()
    h = await svc.add_holder(UID, "Anjali")
    item = (await svc.add_file(UID, PDF, holder_id=h.id)).item
    view = (await svc.view(UID))["items"][0]
    assert view["holder"] == "Anjali" and item.holder_id == h.id
    with pytest.raises(VaultRejected) as e:
        await svc.remove_holder(UID, h.id)
    assert e.value.code == "in_use"
    with pytest.raises(VaultRejected):
        await svc.add_holder(UID, "anjali")
    with pytest.raises(VaultRejected):
        await svc.add_holder(UID, "ABCDE1234F")
    with pytest.raises(VaultRejected):
        await svc.add_file(UID, PDF + b"2", holder_id="h_00000000")
    for n in range(11):
        await svc.add_holder(UID, f"P{n}")
    with pytest.raises(VaultRejected) as e2:
        await svc.add_holder(UID, "one too many")
    assert e2.value.code == "holders_full"


async def test_settings() -> None:
    svc, _, _ = make()
    got = await svc.update_settings(UID, {"alert_detail": "type", "inbox_copy": True})
    assert got == {"alert_detail": "type", "brief": True, "inbox_copy": True}
    with pytest.raises(VaultRejected):
        await svc.update_settings(UID, {"alert_detail": "everything"})


async def test_delete_is_soft_with_a_bin_entry_then_restore_in_place() -> None:
    bin_ = Bin()
    svc, _, _ = make(undo=bin_)
    item = (await svc.add_file(UID, PDF, type_hint="passport")).item
    undo_id = await svc.remove(UID, item.id)
    assert undo_id.startswith("del_")
    assert bin_.kept == [(UID, "vault_item", "Vault item: passport", {"ref": item.id})]
    assert (await svc.view(UID))["items"] == []
    with pytest.raises(VaultRejected):
        await svc.stream_file(UID, item.id, item.files[0].fid)  # a deleted item can't be opened
    await svc.restore(UID, item.id)
    assert [i["id"] for i in (await svc.view(UID))["items"]] == [item.id]
    await svc.restore(UID, item.id)  # repeat is fine


async def test_delete_fails_closed_without_a_bin() -> None:
    svc, _, _ = make(undo=Bin(fail=True))
    item = (await svc.add_file(UID, PDF)).item
    with pytest.raises(VaultUnavailable):
        await svc.remove(UID, item.id)
    assert len((await svc.view(UID))["items"]) == 1
    svc._undo = None
    with pytest.raises(VaultUnavailable):
        await svc.remove(UID, item.id)


async def test_purge_shreds_index_entry_then_chunks() -> None:
    svc, docs, store = make()
    item = (await svc.add_file(UID, PDF + b"z" * 900_000)).item
    assert len([p for p in docs._data if "vault_chunks" in p]) == 2
    assert await svc.purge(UID, item.id) is True
    assert not [p for p in docs._data if "vault_chunks" in p]
    _, index = await store.load(UID)
    assert index.items == () and index.orphans == ()
    assert await svc.purge(UID, item.id) is False  # repeat is safe


async def test_purge_with_failing_chunk_deletes_keeps_orphans_for_the_sweep() -> None:
    svc, docs, store = make()
    item = (await svc.add_file(UID, PDF)).item
    real = store.drop_chunks

    async def fail(*a: object, **k: object) -> None:
        raise RuntimeError("down")

    store.drop_chunks = fail  # type: ignore[method-assign]
    assert await svc.purge(UID, item.id) is True  # the index entry is gone: crypto-shredded
    _, index = await store.load(UID)
    assert index.items == () and len(index.orphans) == 1
    store.drop_chunks = real  # type: ignore[method-assign]
    assert await store.sweep(UID) == 1
    assert not [p for p in docs._data if "vault_chunks" in p]


async def test_undo_adapters() -> None:
    from jarvis.undo.models import DeletedItem

    svc, _, _ = make()
    item = (await svc.add_file(UID, PDF)).item
    await svc.remove(UID, item.id)
    rec = DeletedItem(
        id="del_" + "0" * 20, user_id=UID, kind="vault_item", title="t",
        snapshot={"ref": item.id}, deleted_at=NOW, expires_at=NOW,
    )  # fmt: skip
    got = await VaultRestorer(svc).restore(UID, rec)
    assert got.new_id == item.id
    await svc.remove(UID, item.id)
    await VaultPurger(svc).purge(UID, rec)
    assert (await svc.index(UID)).items == ()
    await VaultPurger(svc).purge(UID, rec)  # repeat is safe
    with pytest.raises(RuntimeError):
        await VaultRestorer(svc).restore(UID, rec)


async def test_wipe_removes_everything_for_that_owner_only() -> None:
    svc, docs, _ = make()
    await svc.add_holder(UID, "Anjali")
    await svc.add_file(UID, PDF)
    await svc.add_file(UID, JPEG)
    await svc.add_file(OTHER, PNG)
    assert await svc.wipe(UID) == 2
    assert [p for p in docs._data if UID in p] == []
    assert len((await svc.view(OTHER))["items"]) == 1
    assert (await svc.view(UID))["items"] == [] and (await svc.view(UID))["holders"][0][
        "count"
    ] == 0


async def test_another_owners_item_is_not_found() -> None:
    svc, _, _ = make()
    item = (await svc.add_file(UID, PDF)).item
    with pytest.raises(VaultRejected) as e:
        await svc.stream_file(OTHER, item.id, item.files[0].fid)
    assert e.value.status == 404
    with pytest.raises(VaultRejected):
        await svc.update(OTHER, item.id, {"title": "x"})
    with pytest.raises(VaultRejected):
        await svc.remove(OTHER, item.id)


async def test_a_swapped_or_missing_chunk_stops_the_download_before_any_byte() -> None:
    svc, docs, _ = make()
    a = (await svc.add_file(UID, PDF + b"a" * 100)).item
    b = (await svc.add_file(UID, PDF + b"b" * 100)).item
    pa = f"jarvis_vault/{UID}/vault_chunks/{a.files[0].fid}_00"
    pb = f"jarvis_vault/{UID}/vault_chunks/{b.files[0].fid}_00"
    docs._data[pa], docs._data[pb] = docs._data[pb], docs._data[pa]
    with pytest.raises(VaultUnavailable):
        await svc.stream_file(UID, a.id, a.files[0].fid)
    del docs._data[pb]
    with pytest.raises(VaultUnavailable):
        await svc.stream_file(UID, b.id, b.files[0].fid)


async def test_a_wrong_checksum_cuts_the_stream() -> None:
    from jarvis.vault.models import FileRef

    svc, _, store = make()
    item = (await svc.add_file(UID, PDF)).item
    ref: FileRef = item.files[0]

    def fn(index):  # type: ignore[no-untyped-def]
        bad = ref.model_copy(update={"sha256": "0" * 64})
        new = item.model_copy(update={"files": (bad,)})
        return index.model_copy(update={"items": (new,)}), None

    await store.change(UID, fn)
    dl = await svc.stream_file(UID, item.id, ref.fid)
    with pytest.raises(VaultUnavailable):
        [c async for c in dl.body]


async def test_export_zip_has_every_file_and_a_manifest() -> None:
    import io
    import json
    import zipfile

    svc, _, _ = make()
    h = await svc.add_holder(UID, "Anjali")
    a = (await svc.add_file(UID, PDF + b"1" * 900_000, type_hint="passport")).item
    await svc.add_file(UID, JPEG, item_id=a.id)
    await svc.add_file(UID, PNG, type_hint="pan", holder_id=h.id)
    dl = await svc.stream_export(UID)
    blob = b"".join([c async for c in dl.body])
    assert dl.filename == "jarvis-vault.zip" and dl.files == 3
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert zf.testzip() is None
        names = sorted(zf.namelist())
        assert names == [
            "pan-anjali-1.png", "passport-you-1.pdf", "passport-you-2.jpg", "vault.json",
        ]  # fmt: skip
        assert zf.read("passport-you-1.pdf") == PDF + b"1" * 900_000
        meta = json.loads(zf.read("vault.json"))
    assert len(meta["documents"]) == 2


async def test_no_plaintext_metadata_in_any_document() -> None:
    svc, docs, _ = make()
    item = (await svc.add_file(UID, PDF, type_hint="passport")).item
    await svc.update(
        UID, item.id, {"title": "Akash passport", "last4": "4821", "note": "blue folder"}
    )
    for needle in ("Akash passport", "4821", "blue folder", "passport"):
        assert not scan(docs, needle), needle
