# tests/test_vault_inbox_service.py -- R2 D9: picking the DigiLocker inbox (own folder, not a
# Use folder, not inside one), importing through the vault port, and the guarantee that Drive tools
# can never read the inbox -- while parents walk, owner-shared roots and read-only still hold.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from drive_fakes import DOCX, PDF
from inbox_fakes import OWNER, PDF_BYTES, UID, FakeIntake, Rig, rig

from jarvis.drive.ports import DriveError, NotInRoots
from jarvis.drive.service import DriveRejected
from jarvis.vault.ports import IntakeResult
from jarvis.vault_inbox.service import WHY_TOO_BIG, WHY_UNSUPPORTED
from jarvis.vault_inbox.store import Inbox


async def _picked(r: Rig | None = None) -> Rig:
    r = r or rig()
    await r.inbox.pick(UID, OWNER, "inbox1")
    return r


def _calls(r: Rig) -> int:
    return len(r.drive.requests)


# ---- picking ----------------------------------------------------------------------------------


async def test_view_before_a_folder_explains_the_steps_and_offers_owner_folders() -> None:
    r = rig()
    v = await r.inbox.view(UID, OWNER)
    assert v["configured"] is False and v["folder"] is None
    assert {f["id"] for f in v["offered"]} == {"inbox1", "use1"}
    assert "Viewer" in v["note"] and "stranger" not in str(v)


async def test_pick_stores_the_folder_and_view_shows_it() -> None:
    r = await _picked()
    v = await r.inbox.view(UID, OWNER)
    assert v["configured"] is True and v["folder"] == {"id": "inbox1", "name": "JARVIS Vault inbox"}
    assert v["offered"] == [] and v["imported_total"] == 0


async def test_a_folder_shared_by_another_account_is_refused() -> None:
    r = rig()
    with pytest.raises(DriveRejected) as e:
        await r.inbox.pick(UID, OWNER, "evil")
    assert e.value.code == "not_owner" and e.value.status == 403
    assert await r.store.load(UID) is None


async def test_unknown_folder_file_and_bad_id_are_refused() -> None:
    r = rig()
    r.drive.file("f1", "a file", "inbox1", b"x", mime=PDF)
    for fid, code in (("nope", "not_offered"), ("f1", "not_a_folder"), ("bad id", "bad_id")):
        with pytest.raises(DriveRejected) as e:
            await r.inbox.pick(UID, OWNER, fid)
        assert e.value.code == code
    with pytest.raises(DriveRejected) as e:
        await r.inbox.pick(UID, None, "inbox1")
    assert e.value.code == "no_owner_email"


async def test_a_folder_ticked_use_is_refused() -> None:
    r = rig()
    await r.svc.set_use(UID, OWNER, "use1", True)
    with pytest.raises(DriveRejected) as e:
        await r.inbox.pick(UID, OWNER, "use1")
    assert e.value.code == "in_use_folder" and e.value.status == 409
    assert "outside the folders JARVIS reads" in str(e.value)


async def test_a_folder_inside_a_use_folder_is_refused() -> None:
    r = rig()
    await r.svc.set_use(UID, OWNER, "use1", True)
    with pytest.raises(DriveRejected) as e:
        await r.inbox.pick(UID, OWNER, "sub1")
    assert e.value.code == "in_use_folder"


async def test_the_inbox_cannot_be_ticked_use() -> None:
    r = await _picked()
    with pytest.raises(DriveRejected) as e:
        await r.svc.set_use(UID, OWNER, "inbox1", True)
    assert e.value.code == "is_inbox"
    v = await r.svc.view(UID, OWNER)
    assert {f["id"]: f.get("inbox") for f in v["folders"]}["inbox1"] is True
    assert "inbox" not in {f["id"]: f for f in v["folders"]}["use1"]  # only the inbox is marked


async def test_offered_leaves_out_use_folders_and_clear_switches_off() -> None:
    r = rig()
    await r.svc.set_use(UID, OWNER, "use1", True)
    assert {f["id"] for f in (await r.inbox.view(UID, OWNER))["offered"]} == {"inbox1"}
    await r.inbox.pick(UID, OWNER, "inbox1")
    await r.inbox.clear(UID)
    assert (await r.inbox.view(UID, OWNER))["configured"] is False


# ---- importing --------------------------------------------------------------------------------


async def test_no_drive_call_is_made_before_a_folder_is_picked() -> None:
    r = rig()
    before = _calls(r)
    res = await r.inbox.check(UID)
    assert res.imported == 0 and _calls(r) == before


async def test_a_new_pdf_is_imported_once_and_not_again() -> None:
    r = await _picked()
    r.drive.file("p1", "Driving Licence 1234567890.pdf", "inbox1", PDF_BYTES, mime=PDF)
    first = await r.inbox.check(UID)
    assert first.imported == 1 and r.intake.calls[0][2:] == ("digilocker", "p1")
    again = await r.inbox.check(UID)
    assert again.imported == 0 and len(r.intake.calls) == 1
    v = await r.inbox.view(UID, OWNER)
    assert v["imported_total"] == 1 and v["last_check_at"] is not None


async def test_a_changed_checksum_is_imported_again() -> None:
    r = await _picked()
    item = r.drive.file("p1", "scan.pdf", "inbox1", PDF_BYTES, mime=PDF)
    await r.inbox.check(UID)
    item.content = PDF_BYTES + b" renewed"
    res = await r.inbox.check(UID)
    assert res.imported == 1 and len(r.intake.calls) == 2


async def test_a_same_bytes_copy_is_reported_duplicate_not_added() -> None:
    r = await _picked()
    r.drive.file("p1", "a.pdf", "inbox1", PDF_BYTES, mime=PDF)
    r.drive.file("p2", "b.pdf", "inbox1", PDF_BYTES, mime=PDF)
    res = await r.inbox.check(UID)
    assert res.imported == 1 and res.skipped == 1
    assert (await r.inbox.view(UID, OWNER))["skipped"][0]["why"] == "Already in your vault."


async def test_big_and_unsupported_files_are_skipped_with_reasons_and_not_retried() -> None:
    r = await _picked()
    r.drive.file("big", "big.pdf", "inbox1", b"x", mime=PDF, size=11 * 1024 * 1024)
    r.drive.file("doc", "letter.docx", "inbox1", b"x", mime=DOCX)
    res = await r.inbox.check(UID)
    assert res.imported == 0 and res.skipped == 2 and r.intake.calls == []
    whys = {s["why"] for s in (await r.inbox.view(UID, OWNER))["skipped"]}
    assert whys == {WHY_TOO_BIG, WHY_UNSUPPORTED}
    requests = _calls(r)
    await r.inbox.check(UID)  # not looked at again: only the folder checks and the listing
    assert not [q for q in r.drive.requests[requests:] if q.url.params.get("alt") == "media"]
    assert "letter" not in str(r.docs._data) and "big.pdf" not in str(r.docs._data)  # type: ignore[attr-defined]


async def test_at_most_three_downloads_a_run_and_the_rest_next_time() -> None:
    r = await _picked()
    for i in range(5):
        r.drive.file(f"p{i}", f"{i}.pdf", "inbox1", PDF_BYTES + bytes([i]), mime=PDF)
    first = await r.inbox.check(UID)
    assert first.imported == 3 and first.more is True
    second = await r.inbox.check(UID)
    assert second.imported == 2 and second.more is False


async def test_the_run_budget_stops_the_loop() -> None:
    r = await _picked()
    for i in range(2):
        r.drive.file(f"p{i}", f"{i}.pdf", "inbox1", PDF_BYTES + bytes([i]), mime=PDF)
    clock = iter([0.0, 0.0, 999.0, 999.0, 999.0])
    r.inbox._mono = lambda: next(clock)
    res = await r.inbox.check(UID)
    assert res.imported == 1 and res.more is True


async def test_subfolders_and_shortcuts_are_not_followed() -> None:
    r = await _picked()
    r.drive.folder("inner", "Inner", "inbox1")
    r.drive.file("deep", "deep.pdf", "inner", PDF_BYTES, mime=PDF)
    r.drive.shortcut("sc", "link", "inbox1", "deep")
    assert (await r.inbox.check(UID)).imported == 0


async def test_a_full_or_missing_vault_stops_with_words_and_retries_later() -> None:
    r = await _picked()
    r.drive.file("p1", "a.pdf", "inbox1", PDF_BYTES, mime=PDF)
    r.intake.answer = IntakeResult(
        status="skipped", code="vault_full", message="The vault is full."
    )
    res = await r.inbox.check(UID)
    assert res.imported == 0 and res.stopped == "The vault is full."
    assert (await r.inbox.view(UID, OWNER))["note"] == "The vault is full."
    r.intake.answer = None
    assert (await r.inbox.check(UID)).imported == 1  # not recorded as seen: tried again


async def test_a_file_the_vault_refuses_is_skipped_with_its_words() -> None:
    r = await _picked()
    r.drive.file("p1", "a.pdf", "inbox1", PDF_BYTES, mime=PDF)
    r.intake.answer = IntakeResult(status="skipped", code="unsupported", message="Not a real PDF.")
    res = await r.inbox.check(UID)
    assert res.skipped == 1
    assert (await r.inbox.view(UID, OWNER))["skipped"][0]["why"] == "Not a real PDF."


async def test_a_download_that_fails_skips_that_file_only() -> None:
    r = await _picked()
    r.drive.file("p1", "a.pdf", "inbox1", PDF_BYTES, mime=PDF)
    r.drive.file("p2", "b.pdf", "inbox1", PDF_BYTES + b"2", mime=PDF)
    r.drive.fail["p1"] = 500
    res = await r.inbox.check(UID)
    assert res.imported == 1 and res.skipped == 1
    assert "VENDOR" not in str(await r.inbox.view(UID, OWNER))


# ---- the folder stops being the owner's -------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "words"),
    [
        (
            lambda d: d.items["inbox1"].__setattr__("shared_by", "colleague@example.com"),
            "shared from your",
        ),
        (lambda d: d.items["inbox1"].__setattr__("trashed", True), "trash"),
        (lambda d: d.items["inbox1"].__setattr__("shared_by", None), "no longer see"),
    ],
)
async def test_an_unshared_or_changed_folder_stops_imports_with_words(change, words) -> None:  # type: ignore[no-untyped-def]
    r = await _picked()
    r.drive.file("p1", "a.pdf", "inbox1", PDF_BYTES, mime=PDF)
    change(r.drive)
    r.drive.items["inbox1"].owner = "someone@else.example"
    res = await r.inbox.check(UID)
    assert res.imported == 0 and r.intake.calls == [] and words in (res.stopped or "")
    assert words in (await r.inbox.view(UID, OWNER))["note"]


async def test_a_folder_that_became_a_use_folder_stops_imports() -> None:
    r = await _picked()
    r.drive.file("p1", "a.pdf", "inbox1", PDF_BYTES, mime=PDF)
    r.drive.move("inbox1", "use1")  # now below a folder the owner can tick Use
    await r.svc.roots.confirm(UID, "use1", "Registry", email=OWNER)
    res = await r.inbox.check(UID)
    assert res.imported == 0 and "inside a folder JARVIS reads" in (res.stopped or "")


async def test_drive_unavailable_is_said_plainly() -> None:
    r = await _picked()
    r.drive.fail["inbox1"] = 403
    r.drive.fail_reason["inbox1"] = "SERVICE_DISABLED"
    res = await r.inbox.check(UID)
    assert "couldn't be reached" in (res.stopped or "") and "VENDOR" not in str(res.public())


# ---- Drive tools can never read the inbox (and every slice 12 guarantee still holds) ----------


async def _with_pan(r: Rig) -> None:
    r.drive.file("pan", "PAN card", "inbox1", "ABCDE1234F permanent account number", mime=PDF)
    r.drive.file("note", "Minutes", "sub1", "Budget is four crore.")
    await r.svc.set_use(UID, OWNER, "use1", True)


async def test_drive_read_search_and_list_of_an_inbox_file_are_refused() -> None:
    r = rig()
    await r.inbox.pick(UID, OWNER, "inbox1")
    await _with_pan(r)
    with pytest.raises(NotInRoots):
        await r.svc.read(UID, "pan")
    with pytest.raises(NotInRoots):
        await r.svc.list_folder(UID, "inbox1")
    found = await r.svc.search(UID, "ABCDE1234F")
    assert found["results"] == []
    assert (await r.svc.read(UID, "note"))["file"] == "note"  # the Use folder still reads


async def test_an_inbox_below_a_use_folder_is_denied_even_though_a_root_is_above_it() -> None:
    r = rig()
    r.drive.folder("inbox2", "Inbox in a Use folder", "use1")
    await r.svc.set_use(UID, OWNER, "use1", True)
    r.drive.file("pan2", "PAN", "inbox2", "ABCDE1234F", mime=PDF)
    assert (await r.svc.read(UID, "pan2"))["file"] == "pan2"  # not an inbox yet: Use reads it
    await r.store.change(UID, lambda _o: Inbox("inbox2", "x", OWNER, datetime.now(UTC)))
    with pytest.raises(NotInRoots):
        await r.svc.read(UID, "pan2")
    listing = await r.svc.list_folder(UID, "use1")
    assert "inbox2" not in str(listing)


async def test_a_shortcut_to_an_inbox_file_is_refused() -> None:
    r = await _picked()
    await _with_pan(r)
    r.drive.shortcut("sc", "link", "sub1", "pan")
    with pytest.raises(NotInRoots):
        await r.svc.read(UID, "sc")


async def test_unreadable_inbox_record_makes_drive_tools_fail_closed() -> None:
    r = await _picked()
    await _with_pan(r)
    r.docs._data[f"jarvis_vault_inbox/{UID}"]["folder_id"] = "bad id!"  # type: ignore[attr-defined]
    with pytest.raises(DriveError):
        await r.svc.read(UID, "note")


async def test_slice12_guarantees_still_hold_with_an_inbox_wired() -> None:
    r = await _picked()
    await _with_pan(r)
    r.drive.folder("other", "Personal", shared_by=OWNER)
    r.drive.file("diary", "Diary", "other", "private words")
    with pytest.raises(NotInRoots):  # not under an owner-chosen root
        await r.svc.read(UID, "diary")
    r.drive.folder("evil2", "Evil", shared_by="stranger@evil.example")
    with pytest.raises(DriveRejected):  # a stranger's folder can't be ticked Use
        await r.svc.set_use(UID, OWNER, "evil2", True)
    assert [q.method for q in r.drive.requests] == ["GET"] * len(r.drive.requests)  # read-only


async def test_a_fake_intake_defaults() -> None:
    assert FakeIntake().answer is None
