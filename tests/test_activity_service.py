# tests/test_activity_service.py -- R1 B: the Activity view (plan D8): Undo only where Recently
# deleted can really restore, a reason everywhere else, grouped reads, owner scoping.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from test_activity_store import item

from jarvis.activity.service import ActivityService
from jarvis.activity.store import ActivityStore
from jarvis.storage.docs import MemoryDocs
from jarvis.undo.models import RestoreOutcome, RestoreStatus
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
DEL = "del_" + "b" * 20


async def rig(with_bin: bool = True) -> tuple[ActivityService, ActivityStore, UndoBin | None]:
    st = ActivityStore(MemoryDocs())
    undo = UndoBin(DeletedStore(MemoryDocs()), clock=lambda: NOW) if with_bin else None
    svc = ActivityService(st, undo, timezone="Asia/Kolkata", clock=lambda: NOW)
    return svc, st, undo


async def test_today_lists_newest_first_with_plain_fields_only() -> None:
    svc, st, _ = await rig()
    await st.add(item(1, at=NOW), "20261105")
    await st.add(item(2, at=NOW + timedelta(minutes=1)), "20261105")
    view = await svc.view("owner", "today")
    assert view.day == "today" and view.available is True
    assert [r.words for r in view.items] == ["Add a to-do 2", "Add a to-do 1"]
    assert set(view.items[0].model_dump()) == {
        "id",
        "at",
        "words",
        "outcome",
        "channel",
        "offline",
        "undo",
        "undo_note",
    }
    assert view.items[0].undo is None
    assert "Can't be undone from here" in view.items[0].undo_note


async def test_yesterday_is_the_previous_local_day() -> None:
    svc, st, _ = await rig()
    await st.add(item(1, at=NOW - timedelta(days=1)), "20261104")
    assert (await svc.view("owner", "today")).items == []
    assert len((await svc.view("owner", "yesterday")).items) == 1


async def test_a_live_bin_item_gets_an_undo_and_a_restored_one_says_restored() -> None:
    svc, st, undo = await rig()
    assert undo is not None
    kept = await undo.keep("owner", "event", "Dentist", {"summary": "Dentist"})
    await st.add(
        item(1, kind="delete", tool="calendar_delete_event", words="Delete", undo_id=kept.id),
        "20261105",
    )
    [row] = (await svc.view("owner", "today")).items
    assert row.undo is not None and row.undo.state == "available" and row.undo.id == kept.id
    assert row.undo_note == ""
    await undo.store.settle("owner", kept.id, restored_id="new1", now=NOW)
    [row] = (await svc.view("owner", "today")).items
    assert row.undo is not None and row.undo.state == "restored"


async def test_an_expired_or_purged_item_has_no_button_and_says_why() -> None:
    svc, st, undo = await rig()
    assert undo is not None
    kept = await undo.keep("owner", "event", "Dentist", {})
    old = kept.model_copy(update={"expires_at": NOW - timedelta(seconds=1)})
    await undo.store.remove("owner", [kept.id])
    await undo.store.add(old)
    await st.add(item(1, kind="delete", undo_id=kept.id), "20261105")
    await st.add(item(2, kind="delete", undo_id=DEL), "20261105")  # never existed / purged
    rows = {r.undo.state for r in (await svc.view("owner", "today")).items if r.undo}
    assert rows == {"expired", "gone"}
    assert all("Recently deleted" in r.undo_note for r in (await svc.view("owner", "today")).items)


async def test_no_bin_on_the_server_means_gone_never_a_button() -> None:
    svc, st, _ = await rig(with_bin=False)
    await st.add(item(1, kind="delete", undo_id=DEL), "20261105")
    [row] = (await svc.view("owner", "today")).items
    assert row.undo is not None and row.undo.state == "gone"


async def test_a_delete_without_a_bin_copy_says_it_cannot_be_undone() -> None:
    svc, st, _ = await rig()
    await st.add(item(1, kind="delete", tool="memory_forget", undo_id=None), "20261105")
    [row] = (await svc.view("owner", "today")).items
    assert row.undo is None and "can't be undone" in row.undo_note.lower()


async def test_reads_of_one_tool_in_one_request_are_grouped() -> None:
    svc, st, _ = await rig()
    for n in (1, 2, 3):
        await st.add(
            item(n, kind="read", tool="calendar_list_events", words="Looked at your calendar"),
            "20261105",
        )
    await st.add(
        item(
            4,
            kind="read",
            tool="calendar_list_events",
            words="Looked at your calendar",
            trace_id="t2",
        ),
        "20261105",
    )
    words = [r.words for r in (await svc.view("owner", "today")).items]
    assert sorted(words) == ["Looked at your calendar", "Looked at your calendar \u00b7 3 times"]


async def test_a_waiting_row_disappears_once_the_same_call_finished() -> None:
    svc, st, _ = await rig()
    await st.add(item(1, outcome="waiting", words="Waiting for your OK: Add a to-do 5"), "20261105")
    await st.add(
        item(2, outcome="done", words="Add a to-do 5", at=NOW + timedelta(minutes=2)),
        "20261105",
    )
    await st.add(item(3, outcome="waiting", words="Waiting for your OK: Other"), "20261105")
    words = [r.words for r in (await svc.view("owner", "today")).items]
    assert "Waiting for your OK: Add a to-do 5" not in words
    assert "Waiting for your OK: Other" in words


async def test_other_owners_rows_never_appear() -> None:
    svc, st, _ = await rig()
    await st.add(item(1, "alice"), "20261105")
    assert (await svc.view("bob", "today")).items == []


async def test_record_restore_writes_a_you_restored_row() -> None:
    svc, st, _ = await rig()
    out = RestoreOutcome(
        status=RestoreStatus.RESTORED,
        message="m",
        undo_id=DEL,
        kind="event",
        title="Dentist",
        new_id="n1",
    )
    await svc.record_restore("owner", out, session_id=None)
    [row] = (await svc.view("owner", "today")).items
    assert row.words == "You restored the event \u201cDentist\u201d"
    assert "Delete it again" in row.undo_note and row.outcome == "done"


async def test_record_restore_ignores_a_restore_that_did_not_happen() -> None:
    svc, _, _ = await rig()
    out = RestoreOutcome(status=RestoreStatus.ALREADY_RESTORED, message="m", undo_id=DEL)
    await svc.record_restore("owner", out, session_id=None)
    assert (await svc.view("owner", "today")).items == []


async def test_an_unknown_day_is_today() -> None:
    svc, _, _ = await rig()
    assert (await svc.view("owner", "tomorrow")).day == "today"


async def test_a_new_pending_card_stays_visible_after_an_older_identical_one_finished() -> None:
    svc, st, _ = await rig()
    await st.add(item(1, outcome="done", words="Dentist", at=NOW), "20261105")
    later = NOW + timedelta(hours=1)
    await st.add(
        item(2, outcome="waiting", words="Waiting for your OK: Dentist", at=later), "20261105"
    )
    words = [r.words for r in (await svc.view("owner", "today")).items]
    assert "Waiting for your OK: Dentist" in words and "Dentist" in words


async def test_a_waiting_card_and_the_call_it_became_match_by_call_key_not_words() -> None:
    svc, st, _ = await rig()
    await st.add(
        item(
            1,
            outcome="waiting",
            words="Waiting for your OK: Send an email to a@b.com",
            call_key="k1",
        ),
        "20261105",
    )
    await st.add(
        item(
            2,
            outcome="done",
            words="Sent an email to a@b.com",
            call_key="k1",
            at=NOW + timedelta(minutes=1),
        ),
        "20261105",
    )
    words = [r.words for r in (await svc.view("owner", "today")).items]
    assert words == ["Sent an email to a@b.com"]
