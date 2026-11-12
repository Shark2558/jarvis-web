# tests/test_r11_1_c_import.py -- R11.1 O6 (plan D14): 2,000 picked photos, imported as a
# background job in steps. One call never does the whole import; a restart or a sleeping laptop
# resumes where it stopped and no photo is sent twice; Google's links are asked for again and
# never kept; a session that ends part-way stops cleanly and keeps what was done; the owner's
# limit is the cap; the progress line says honestly what is happening.
from __future__ import annotations

import json

from faces_fakes import UID, add_adult, enrol
from photos_fakes import C1, C2, JPEG, FakeEdge, FakePicker, rig

from jarvis.photos.imports import ImportStore, describe
from jarvis.photos.models import FaceHit, ImportLimits
from jarvis.photos.service import PhotosService, PhotosState

STEPS_OF_TEN = ImportLimits(batch=10, most=10)  # a step's ceiling at the setting (fixed steps)


async def picked(items: int, **kw: object):  # noqa: ANN202
    r = rig(items=items, **kw)  # type: ignore[arg-type]
    r.svc.limits = STEPS_OF_TEN  # these tests are about resuming, not how much a step reads
    await r.svc.begin(UID)
    return r


async def test_two_thousand_photos_import_in_steps_of_ten_never_in_one_call() -> None:
    r = await picked(2000)
    assert r.picker.max_items == [2000]  # the pick itself allows Google's 2,000
    first = await r.svc.collect(UID)
    assert (first.status, first.photos, first.total) == ("reading", 10, 2000)
    assert len(r.edge.received) == 10  # one step, ten photos: the rest wait for the next step
    steps = 1
    while (await r.svc.collect(UID)).status == "reading":
        steps += 1
        assert steps < 400
    done = await r.svc.progress(UID)
    assert (done.status, done.photos, done.total) == ("done", 2000, 2000) and steps + 1 == 200
    sent = [image.removeprefix(JPEG).decode() for image in r.edge.received]
    assert sent == [f"m{i}" for i in range(2000)]  # every photo once, in order
    assert r.picker.deleted == ["sess1"] and (await r.state.get(UID)).session_id is None
    assert r.picker.pages <= 20 + 200 + 20  # a page or two a step, never the whole list each time


async def test_a_small_pick_is_done_in_the_first_step_as_before() -> None:
    r = await picked(3)
    res = await r.svc.collect(UID)
    assert (res.status, res.photos, res.total) == ("done", 3, 3)
    assert (await r.svc.collect(UID)).status == "no_session"  # the next ask starts a new pick


async def test_it_resumes_after_a_restart_and_sends_nothing_twice() -> None:
    r = await picked(35)
    for _ in range(2):
        await r.svc.collect(UID)
    # the cloud instance restarts: a new service over the same documents
    again = PhotosService(
        r.picker, r.edge, r.f.svc, r.contacts, PhotosState(r.f.docs), limits=STEPS_OF_TEN
    )  # type: ignore[arg-type]
    statuses = [(await again.collect(UID)).status for _ in range(2)]
    assert statuses == ["reading", "done"]
    sent = [image.removeprefix(JPEG).decode() for image in r.edge.received]
    assert sent == [f"m{i}" for i in range(35)]


async def test_a_sleeping_laptop_pauses_the_import_and_nothing_is_downloaded_for_it() -> None:
    r = await picked(25)
    await r.svc.collect(UID)
    r.edge.online = False
    before = list(r.picker.events)
    res = await r.svc.collect(UID)
    assert res.status == "laptop_offline" and res.photos == 10 and res.total == 25
    assert r.picker.events == before  # no photo left Google for a laptop that is asleep
    assert "paused: laptop not reachable" in res.line and "10 of 25 read" in res.line
    assert (await r.state.get(UID)).session_id == "sess1"  # kept for when it wakes
    r.edge.online = True
    assert [(await r.svc.collect(UID)).status for _ in range(2)] == ["reading", "done"]
    assert len(r.edge.received) == 25 and len(set(r.edge.received)) == 25


async def test_an_older_home_kit_is_named_instead_of_laptop_not_reachable() -> None:
    r = await picked(5)
    r.edge.kit = "kit_old"
    res = await r.svc.collect(UID)
    assert res.status == "kit_old" and r.picker.events == []
    assert "update the home kit" in res.line
    r.edge.kit = "ready"
    r.edge.reader_off = True
    res = await r.svc.collect(UID)
    assert res.status == "reader_off" and res.photos == 0 and "face reader" in res.line


async def test_the_session_ending_part_way_stops_cleanly_and_keeps_what_was_done() -> None:
    r = await picked(30)
    await r.svc.collect(UID)
    r.picker.gone = True  # Google ended the session (they last a limited time)
    res = await r.svc.collect(UID)
    assert res.status == "expired" and res.photos == 10 and res.total == 30
    assert "pick again to continue" in res.line and "10 of 30 read" in res.line
    assert (await r.state.get(UID)).session_id is None
    assert (await r.svc.progress(UID)).status == "expired"  # the panel keeps saying so
    assert (await r.svc.collect(UID)).status == "no_session"
    doc = await ImportStore(r.f.docs).get(UID)
    assert doc.todo == () and doc.done == 10  # the ids still to do are dropped, the count kept


async def test_googles_links_are_asked_for_again_and_never_kept() -> None:
    r = await picked(25)
    pages_before = r.picker.pages
    await r.svc.collect(UID)
    await r.svc.collect(UID)
    assert r.picker.pages >= pages_before + 2  # each step reads its page afresh
    stored = json.dumps(r.f.docs._data, default=str)  # noqa: SLF001
    assert "googleusercontent" not in stored and "https://" not in stored
    assert '"m24"' in stored and '"m3"' not in stored  # the ids still to do, and only those
    assert JPEG.decode("latin-1") not in stored


async def test_the_owners_limit_is_the_cap_and_the_rest_is_said() -> None:
    r = rig(items=40)
    r.svc.limits = ImportLimits(max_picked=25, batch=10, most=10)
    await r.svc.begin(UID)
    assert r.picker.max_items == [25]
    statuses = [(await r.svc.collect(UID)).status for _ in range(3)]
    assert statuses == ["reading", "reading", "done"]
    res = await r.svc.progress(UID)
    assert (res.photos, res.total, res.over) == (25, 25, 15)
    assert "15 more were picked than your limit of 25" in res.line


async def test_a_step_reads_as_many_as_fit_its_time_at_least_the_setting() -> None:
    # review C-code M6: the setting is not a ceiling while the time allows more (up to 50)
    r = rig(items=120)
    r.svc.limits = ImportLimits(max_picked=2000, batch=5)  # as the part sets it: most = 50
    await r.svc.begin(UID)
    assert [(await r.svc.collect(UID)).photos for _ in range(3)] == [50, 100, 120]


async def test_a_step_never_starts_a_photo_it_cannot_finish_in_its_time() -> None:
    r = rig(items=40)
    r.picker.slow = 0.2  # each photo takes 0.2 s; the step has about 1 s
    await r.svc.begin(UID)
    res = await r.svc.collect(UID, budget_s=2.0)
    assert res.status == "reading" and 2 <= res.photos <= 5  # time decided, not the setting
    downloads = [e for e in r.picker.events if e.startswith("download")]
    assert len(downloads) == len(r.edge.received) == res.photos  # nothing begun and dropped
    assert "left; keep the Connectors panel open to go faster" in res.line  # the honest pace


async def test_faces_and_known_people_add_up_across_steps() -> None:
    r = rig(items=20)
    r.svc.limits = STEPS_OF_TEN
    p = await add_adult(r.f)
    await enrol(r.f, p)
    hits = [(FaceHit(C1, p.id, 0.95),), (FaceHit(C2, None, 0.0),), ()] * 7
    r.edge.script = hits[:20]
    await r.svc.begin(UID)
    await r.svc.collect(UID)
    res = await r.svc.collect(UID)
    assert res.status == "done" and res.faces_found == 14 and res.unknown == 7
    assert [x.name for x in res.recognised] == ["Anjali"]
    assert res.line == "20 of 20 read · 14 faces found"
    stored = json.dumps(r.f.docs._data, default=str)  # noqa: SLF001
    assert "Anjali" not in stored  # the progress holds ids and counts, never a name


async def test_a_photo_the_laptop_cannot_read_is_skipped_and_the_rest_go() -> None:
    r = await picked(4)
    r.edge.refuse = {JPEG + b"m1"}
    r.picker.fail = {"m2"}
    res = await r.svc.collect(UID)
    assert (res.status, res.photos, res.skipped) == ("done", 2, 2)
    assert "2 could not be read" in res.line


async def test_photos_that_vanished_from_the_pick_do_not_stall_the_import() -> None:
    r = await picked(15)
    await r.svc.collect(UID)
    r.picker.items = r.picker.items[:12]  # three were removed at Google's end meanwhile
    res = await r.svc.collect(UID)
    assert (res.status, res.photos, res.skipped) == ("done", 12, 3)


async def test_stop_ends_the_import_and_forgets_the_ids() -> None:
    r = await picked(30)
    await r.svc.collect(UID)
    await r.svc.stop(UID)
    assert r.picker.deleted == ["sess1"] and (await r.state.get(UID)).session_id is None
    assert (await r.svc.progress(UID)).status == "no_session"
    assert not any("photo_imports" in k for k in r.f.docs._data)  # noqa: SLF001
    assert (await r.svc.collect(UID)).status == "no_session"


async def test_a_new_pick_replaces_an_unfinished_import() -> None:
    r = await picked(30)
    await r.svc.collect(UID)
    await r.svc.begin(UID)
    res = await r.svc.progress(UID)
    assert (res.status, res.photos, res.total) == ("waiting", 0, 0)
    assert r.picker.deleted == ["sess1"]


async def test_purge_also_forgets_the_import() -> None:
    r = await picked(30)
    await r.svc.collect(UID)
    await r.svc.purge(UID)
    assert not any("photo" in k for k in r.f.docs._data)  # noqa: SLF001


def test_the_progress_line_in_plain_words() -> None:
    from jarvis.photos.imports import ImportDoc

    doc = ImportDoc("s", "reading", total=2000, done=312, faces=41, paused="laptop")
    assert describe(doc, 2000) == (
        "312 of 2,000 read · 41 faces found · paused: laptop not reachable"
    )
    assert describe(ImportDoc("s", "picking"), 2000) == "Waiting for you to choose photos."
    assert describe(ImportDoc("s", "listing", todo=("a",) * 150), 2000) == (
        "Reading the list of what you picked (150 so far)."
    )
    one = ImportDoc("s", "done", total=1, done=1, faces=1)
    assert describe(one, 2000) == "1 of 1 read · 1 face found"
    assert describe(ImportDoc(), 2000) == ""


async def test_rig_types() -> None:
    assert isinstance(rig().picker, FakePicker) and isinstance(rig().edge, FakeEdge)
