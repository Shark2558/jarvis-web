# tests/test_r11_1_c_part.py -- R11.1 Part C's join with the app (plan D14, D15, D21-C): the
# part's contract (its own tools, jobs, privacy rows and collections), the two privacy rows (a
# delete of the face groups is reported done only when the laptop has confirmed it), the two
# clock jobs (one step of an import inside the clock's time; the poll) and the two read tools.
from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from faces_fakes import UID
from photos_fakes import rig
from r11_1_fakes_c import Cloud, build_cloud, consent, leaks, picture

import jarvis.facegroups as package
from jarvis.api.r11_1_wiring import check_part
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.facegroups.jobs import FaceGroupsPollJob, PhotosImportJob
from jarvis.facegroups.part import build
from jarvis.facegroups.privacy import PENDING, FaceGroupsPrivacy, PhotoImportPrivacy
from jarvis.facegroups.tools import face_group_tools
from jarvis.fixes.ports import COLLECTIONS, TOOL_FAMILIES, FixContext, tool_allowed
from jarvis.integrations.google import GoogleAPIError
from jarvis.photos.models import ImportLimits
from jarvis.privacy.ports import PrivacyRegistry
from jarvis.privacy.service import PrivacyService
from jarvis.storage.docs import MemoryDocs
from jarvis.ticks import TickJob, run_jobs
from jarvis.tools.context import tool_context
from jarvis.tools.provenance import unwrap


def ctx(state: dict[str, Any], docs: MemoryDocs | None = None, **settings: Any) -> FixContext:
    s = Settings(_env_file=None, **settings)
    return FixContext(s=s, docs=docs or MemoryDocs(), audit=None, state=state.get)


# ---- the contract -------------------------------------------------------------------------------


def test_the_part_brings_only_what_it_owns() -> None:
    part = check_part("photos", build(ctx({})))
    assert part.ready == "ready"
    assert [t.name for t in part.tools] == ["faces_groups", "photos_import_status"]
    assert all(tool_allowed("photos", t.name) for t in part.tools)
    assert all(t.risk is ActionRisk.READ_ONLY for t in part.tools)  # nothing here writes
    assert [j.name for j in part.clock_jobs] == ["photos_import", "face_groups_poll"]
    assert all(isinstance(j, TickJob) and 0 < j.budget_s <= 20 for j in part.clock_jobs)
    assert part.daily_jobs == ()
    assert [p.id for p in part.privacy] == ["photo_imports", "face_groups"]
    assert {p.section for p in part.privacy} == {"Faces"}
    assert set(part.services) == {"groups", "photos", "limit", "limits"}
    assert TOOL_FAMILIES["photos"] == ("faces_groups", "faces_group_*", "photos_import_*")


def test_without_a_document_store_the_part_is_off_in_plain_words() -> None:
    s = Settings(_env_file=None)
    part = build(FixContext(s=s, docs=None, audit=None, state=lambda n: None))
    assert part.tools == () and part.clock_jobs == () and "off" in part.ready


def test_the_part_names_only_its_two_collections() -> None:
    source = ""
    for module in ("store", "service", "privacy", "jobs", "tools", "part"):
        source += inspect.getsource(__import__(f"jarvis.facegroups.{module}", fromlist=["x"]))
    assert COLLECTIONS["photos"] == ("photo_imports", "face_groups")
    assert 'f"{prefix}face_groups"' in source and package.__doc__
    import jarvis.photos.import_store as imports

    assert 'f"{prefix}photo_imports"' in inspect.getsource(imports)


def test_the_owners_settings_reach_the_photos_service_whoever_drives_the_import() -> None:
    r = rig(items=5)
    part = build(ctx({"photos": r.svc}, photos_max_picked=500, photos_import_batch=4))
    assert r.svc.limits == ImportLimits()  # nothing is read from the app while the part is built
    assert part.services["photos"]() is r.svc
    assert r.svc.limits == ImportLimits(max_picked=500, batch=4)
    assert build(ctx({"photos": object()})).services["photos"]() is None  # not Photos: "off"


# ---- the privacy rows -------------------------------------------------------------------------


async def privacy(c: Cloud) -> tuple[FaceGroupsPrivacy, PrivacyService]:
    row = FaceGroupsPrivacy(lambda: c.groups)
    registry = PrivacyRegistry()
    registry.register(row)
    registry.register(PhotoImportPrivacy(lambda: c.photos))
    return row, PrivacyService(registry)


async def test_face_groups_row_counts_what_the_laptop_keeps_never_a_face(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    await c.group_of(1)
    await c.at_home(2)
    row, _ = await privacy(c)
    view = await row.describe(UID)
    assert (view.count, view.delete, view.section, view.label) == (
        2,
        "confirm",
        "Faces",
        "Face groups",
    )
    assert "only on your laptop" in view.what and "90 days" in view.retention
    export = await row.export(UID)
    assert export is not None and export["faces"] == "only on your laptop"
    assert [g["photos"] for g in export["groups"]] == [3] and export["stray_faces"] == 1
    assert leaks(json.dumps(export) + view.model_dump_json()) == []
    await c.home.aclose()


async def test_delete_all_is_done_when_the_laptop_confirms(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    named = await c.group_of(2, start=10)
    await c.groups.name(UID, named, **consent())
    await c.at_home(3)
    row, service = await privacy(c)
    view = await row.describe(UID)
    assert view.count == 2  # one unnamed group, one stray; the named person is another row
    done = await service.delete(
        UID, "face_groups", rev=view.rev, confirm=None, proof=None, fresh_left_s=None
    )
    assert (done.deleted, done.remaining) == (2, 0)
    after = await row.describe(UID)
    assert (after.count, after.delete) == (0, "none")
    listed = c.home.groups.groups_view()
    assert listed["groups"] == [] and listed["strays"] == 0 and listed["named"] == 1
    assert gid not in json.dumps(listed)
    await c.home.aclose()


async def test_with_the_laptop_off_a_delete_is_not_reported_done_and_is_retried(
    tmp_path: Path,
) -> None:
    c = await build_cloud(tmp_path)
    await c.group_of(1)
    await c.at_home(2)
    row, service = await privacy(c)
    view = await row.describe(UID)
    c.home.online = False
    done = await service.delete(
        UID, "face_groups", rev=view.rev, confirm=None, proof=None, fresh_left_s=None
    )
    assert (done.deleted, done.remaining) == (0, 2)  # the panel says "2 are still there"
    waiting = await row.describe(UID)
    assert waiting.count == 2 and waiting.note == PENDING and "NOT done" in waiting.note
    assert waiting.rev != view.rev
    assert len(c.home.groups.groups_view()["groups"]) == 1  # the laptop still has them
    shown = await c.groups.view(UID)
    assert shown.groups == () and shown.forgets_waiting == 2  # asked: no longer offered to name
    c.home.online = True
    assert (await c.groups.poll(UID))["forgotten"] == 2  # as R3's face delete: retried, then done
    final = await row.describe(UID)
    assert (final.count, final.delete) == (0, "none") and final.note != PENDING
    assert c.home.groups.groups_view()["groups"] == []
    await c.home.aclose()


async def test_a_sleeping_laptop_never_hides_the_row(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    await c.group_of(1)
    row, _ = await privacy(c)
    await row.describe(UID)
    c.home.online = False
    view = await row.describe(UID)
    assert view.available and view.count == 1 and view.delete == "confirm"
    off = await FaceGroupsPrivacy(lambda: None).describe(UID)
    assert off.count == 0 and off.delete == "none" and "home kit" in off.note
    await c.home.aclose()


STEPS_OF_TEN = ImportLimits(batch=10, most=10)  # fixed steps: these tests are about the rows/jobs


async def test_photos_being_read_row_and_its_delete_stop_the_import() -> None:
    r = rig(items=30)
    r.svc.limits = STEPS_OF_TEN
    row = PhotoImportPrivacy(lambda: r.svc)
    idle = await row.describe(UID)
    assert (idle.count, idle.delete, idle.note) == (0, "none", "No import is running.")
    await r.svc.begin(UID)
    await r.svc.collect(UID)
    view = await row.describe(UID)
    assert (view.count, view.delete, view.delete_count) == (20, "simple", 20)
    assert "10 of 30 read" in view.note and "Never a picture" in view.what
    assert await row.export(UID) == {
        "state": "reading",
        "picked": 30,
        "read": 10,
        "faces_found": 0,
        "could_not_be_read": 0,
        "still_to_read": 20,
    }
    assert await row.delete(UID) == 20
    assert (await row.describe(UID)).delete == "none" and r.picker.deleted == ["sess1"]
    assert (await PhotoImportPrivacy(lambda: None).describe(UID)).count == 0


# ---- the clock jobs -----------------------------------------------------------------------------


async def test_the_import_job_does_one_step_a_tick_for_each_owner_with_an_import() -> None:
    r = rig(items=25)
    r.svc.limits = STEPS_OF_TEN
    job = PhotosImportJob(lambda: r.svc)
    assert await job.run([UID]) == {"steps": 0, "photos": 0, "paused": 0, "failed": 0}
    assert r.picker.pages == 0  # nothing running: one document read, nobody is called
    await r.svc.begin(UID)
    assert await job.run([UID, "u_other"]) == {"steps": 1, "photos": 10, "paused": 0, "failed": 0}
    assert (await job.run([UID]))["photos"] == 10
    assert await job.run([UID]) == {"steps": 1, "photos": 5, "paused": 0, "failed": 0}
    assert (await r.svc.progress(UID)).status == "done"
    assert (await job.run([UID]))["steps"] == 0  # finished: idle again


async def test_a_laptop_known_to_be_asleep_costs_nothing_and_is_a_pause_not_a_failure() -> None:
    r = rig(items=25)
    r.svc.limits = STEPS_OF_TEN
    asleep = {"on": False}

    async def online(uid: str) -> bool:
        return asleep["on"]

    job = PhotosImportJob(lambda: r.svc, lambda: online)
    await r.svc.begin(UID)
    asleep["on"] = True
    await job.run([UID])
    asleep["on"] = False
    events = list(r.picker.events)
    assert await job.run([UID]) == {"steps": 0, "photos": 0, "paused": 1, "failed": 0}
    assert r.picker.events == events
    r.edge.online = False  # the probe is wrong (it lags): the step itself finds out
    asleep["on"] = True
    out = await job.run([UID])
    assert (out["steps"], out["photos"], out["paused"], out["failed"]) == (1, 0, 1, 0)
    assert "paused: laptop not reachable" in (await r.svc.progress(UID)).line


async def test_google_trouble_pauses_and_only_the_unexpected_fails_the_job() -> None:
    r = rig(items=25)
    job = PhotosImportJob(lambda: r.svc)
    await r.svc.begin(UID)

    async def limited(uid: str, sid: str, token: str = "") -> Any:
        raise GoogleAPIError("Google is limiting requests for now; try again later.")

    r.picker.list_page = limited  # type: ignore[method-assign]
    assert await job.run([UID]) == {"steps": 0, "photos": 0, "paused": 1, "failed": 0}
    assert "google photos isn't answering" in (await r.svc.progress(UID)).line.lower()

    async def broken(uid: str, sid: str, token: str = "") -> Any:
        raise RuntimeError("boom")

    r.picker.list_page = broken  # type: ignore[method-assign]
    assert (await job.run([UID]))["failed"] == 1
    assert await run_jobs([job], [UID]) == {"photos_import": "failed"}
    assert await PhotosImportJob(lambda: None).run([UID]) == {
        "steps": 0,
        "photos": 0,
        "paused": 0,
        "failed": 0,
    }


async def test_the_step_stays_inside_what_the_clock_has_left() -> None:
    r = rig(items=25)
    r.picker.slow = 0.2  # ten photos would take two seconds
    job = PhotosImportJob(lambda: r.svc)
    await r.svc.begin(UID)
    assert await run_jobs([job], [UID], total_budget_s=2.2) == {"photos_import": "ok"}
    part_way = await r.svc.progress(UID)
    assert 0 < part_way.photos < 10 and part_way.status == "reading"  # kept, not lost
    r.picker.slow = 0.0
    while (await r.svc.collect(UID)).status == "reading":
        pass
    assert len(set(r.edge.received)) == 25  # the photo that was cut off was read again, once


async def test_the_poll_job_runs_for_every_owner_and_counts(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    await c.group_of(1)
    job = FaceGroupsPollJob(c.groups)
    out = await job.run([UID])
    assert (out["told"], out["away"], out["failed"]) == (1, 0, 0)
    assert await run_jobs([job], [UID]) == {"face_groups_poll": "ok"}

    async def boom(uid: str) -> dict[str, int]:
        raise RuntimeError("boom")

    c.groups.poll = boom  # type: ignore[method-assign]
    assert (await job.run([UID]))["failed"] == 1
    await c.home.aclose()


# ---- the two tools ------------------------------------------------------------------------------


async def test_faces_groups_says_how_many_and_where_to_look_never_who(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    await c.group_of(1)
    groups_tool, status_tool = face_group_tools(c.groups, lambda: c.photos)
    with tool_context(f"{UID}:s1"):
        out = unwrap(await groups_tool.run({}))[0]
        assert out["to_name"] == 1 and out["groups"] == [{"group": "Group 1", "photos": 3}]
        assert "localhost:8098/faces" in out["note"] and out["laptop"] == "online"
        assert "c_" not in json.dumps(out) and leaks(json.dumps(out)) == []
        c.home.online = False
        assert "stale" in unwrap(await groups_tool.run({}))[0]
        assert unwrap(await status_tool.run({}))[0]["status"] == "none"
    await c.home.aclose()


async def test_photos_import_status_reads_the_progress_and_names_nobody(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    await c.groups.name(UID, gid, **consent(name="Mini", child=True, given_by="parent_guardian"))
    await c.import_all([picture(1, n=20), picture(5, n=20)])
    _, status_tool = face_group_tools(c.groups, lambda: c.photos)
    with tool_context(f"{UID}:s1"):
        out, vouched = unwrap(await status_tool.run({}))
    assert vouched is True  # JARVIS's own counts: reading them taints nothing
    assert out["status"] == "done" and out["progress"] == "2 of 2 read · 2 faces found"
    assert (out["photos_read"], out["faces_found"], out["people_recognised"]) == (2, 2, 1)
    assert "Mini" not in json.dumps(out)
    off = face_group_tools(c.groups, lambda: None)[1]
    with tool_context(f"{UID}:s1"):
        assert (await off.run({}))["status"] == "unavailable"
    await c.home.aclose()


@pytest.mark.parametrize("name", ["faces_groups", "photos_import_status"])
def test_the_tools_take_no_arguments(name: str) -> None:
    tools = {t.name: t for t in face_group_tools(None, lambda: None)}  # type: ignore[arg-type]
    assert tools[name].input_schema == {"type": "object", "properties": {}}
    assert tools[name].may_vouch is True


async def test_the_retention_is_the_laptops_own_number_of_days(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path, env={"FACE_GROUPS_KEEP_DAYS": "30"})
    await c.group_of(1)
    row, _ = await privacy(c)
    view = await row.describe(UID)
    assert "at most 30 days" in view.retention and "90" not in view.retention
    assert "finishes when it is back" in view.note  # said before the owner presses Delete
    await c.home.aclose()
