# tests/test_r11_1_c_import_lease.py -- review C-code H2 and M1: an import is stepped by one step
# at a time, whoever asks (the clock, the panel, two Cloud Run instances during a deploy): a step
# claims it in a transaction first, every save checks the claim, and a stale writer can never move
# a finished import back or mark it expired. A photo Google fails to hand over for a moment (5xx,
# 429, a timeout) is tried again, then waits for the next step; it is never dropped as unreadable.
from __future__ import annotations

import asyncio

import httpx
import pytest
from faces_fakes import UID
from photos_fakes import JPEG, rig

from jarvis.photos.errors import PickerError, PickerRetry
from jarvis.photos.import_store import ImportDoc, ImportStore, LeaseLost
from jarvis.photos.imports import MAX_STUCK_STEPS
from jarvis.photos.models import ImportLimits
from jarvis.photos.picker import PickerClient
from jarvis.photos.service import PhotosService, PhotosState

TEN = ImportLimits(batch=10, most=10)


def twin(r):  # noqa: ANN001, ANN202 - a second instance over the same documents
    return PhotosService(r.picker, r.edge, r.f.svc, r.contacts, PhotosState(r.f.docs), limits=TEN)


async def test_two_instances_stepping_at_once_send_each_photo_once() -> None:
    r = rig(items=40)
    r.svc.limits = TEN
    r.picker.slow = 0.01  # each download yields, so the two really interleave
    other = twin(r)
    await r.svc.begin(UID)
    for _ in range(8):
        a, b = await asyncio.gather(r.svc.collect(UID), other.collect(UID))
        assert {a.status, b.status} <= {"reading", "done", "no_session"}  # no_session: finished
        if (await r.svc.progress(UID)).status == "done":
            break
    done = await r.svc.progress(UID)
    assert (done.status, done.photos, done.total) == ("done", 40, 40)
    sent = [image.removeprefix(JPEG).decode() for image in r.edge.received]
    assert sorted(sent) == sorted(f"m{i}" for i in range(40)) and len(sent) == 40  # once each


async def test_a_step_does_nothing_while_another_live_step_holds_the_import() -> None:
    r = rig(items=30)
    await r.svc.begin(UID)
    store = r.svc.imports
    held = await store.claim(UID, "sess1", "someone-else", 60.0)
    assert held is not None
    res = await r.svc.collect(UID)
    assert res.photos == 0 and r.edge.received == []  # busy: nothing downloaded, nothing sent
    await store.release(UID, "someone-else")
    assert (await r.svc.collect(UID)).photos > 0


async def test_a_claim_left_by_a_step_that_died_runs_out() -> None:
    r = rig(items=5)
    await r.svc.begin(UID)
    clock = {"t": 1_000.0}
    store = ImportStore(r.f.docs, now=lambda: clock["t"])
    assert await store.claim(UID, "sess1", "dead-step", 30.0) is not None
    assert await store.claim(UID, "sess1", "new-step", 30.0) is None
    clock["t"] += 31
    assert await store.claim(UID, "sess1", "new-step", 30.0) is not None


async def test_a_stale_writer_cannot_overwrite_a_finished_import() -> None:
    r = rig(items=5)
    await r.svc.begin(UID)
    store = r.svc.imports
    stale = await store.claim(UID, "sess1", "stale", 30.0)
    assert stale is not None
    await store.release(UID, "stale")  # its lease is gone (ran out, or taken over)
    assert (await r.svc.collect(UID)).status == "done"
    with pytest.raises(LeaseLost):  # the stale step's next save
        await store.put(UID, ImportDoc("sess1", "reading", total=5, done=1), "stale", 30.0)
    assert (await store.get(UID)).state == "done"


async def test_a_finished_import_is_never_marked_expired() -> None:
    r = rig(items=3)
    await r.svc.begin(UID)
    assert (await r.svc.collect(UID)).status == "done"
    after = await r.svc.imports.expire(UID, "sess1")  # Google's 404 seen by a late step
    assert after.state == "done" and (await r.svc.imports.get(UID)).state == "done"


async def test_a_late_expire_never_touches_a_newer_pick() -> None:
    r = rig(items=3)
    await r.svc.begin(UID)
    await r.svc.begin(UID)  # picked again: sess2
    kept = await r.svc.imports.expire(UID, "sess1")
    assert kept.session_id == "sess2" and kept.state == "picking"


async def test_a_stop_during_a_step_is_not_undone_by_the_step() -> None:
    r = rig(items=30)
    r.svc.limits = TEN
    await r.svc.begin(UID)
    gate, release = asyncio.Event(), asyncio.Event()
    real = r.picker.download

    async def slow(uid: str, item: object) -> bytes:
        gate.set()
        await release.wait()
        return await real(uid, item)  # type: ignore[arg-type]

    r.picker.download = slow  # type: ignore[method-assign]
    stepping = asyncio.create_task(twin(r).collect(UID))
    await gate.wait()
    await r.svc.imports.delete(UID)  # the owner pressed Stop (or Privacy -> delete)
    release.set()
    await stepping
    assert (await r.svc.imports.get(UID)).state == "none"  # the step did not write it back


# ---- M1: a photo Google can't hand over just now is tried again, never dropped ------------------


async def test_a_passing_failure_is_retried_in_the_step_then_waits_never_skipped() -> None:
    r = rig(items=3)
    calls = {"m0": 0}
    real = r.picker.download

    async def flaky(uid: str, item: object) -> bytes:
        if getattr(item, "id", "") == "m0":
            calls["m0"] += 1
            raise PickerRetry("Google answered 503")
        return await real(uid, item)  # type: ignore[arg-type]

    r.picker.download = flaky  # type: ignore[method-assign]
    naps: list[float] = []

    async def nap(s: float) -> None:
        naps.append(s)

    r.svc._importer._sleep = nap  # type: ignore[union-attr]  # noqa: SLF001
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert calls["m0"] == 3 and naps == [1.0, 3.0]  # tried again with a backoff
    doc = await r.svc.imports.get(UID)
    assert "m0" in doc.todo and doc.skipped == 0 and doc.paused == "google"
    assert res.status == "reading" and "Google Photos isn't answering" in res.line
    r.picker.download = real  # type: ignore[method-assign]
    done = await r.svc.collect(UID)
    assert (done.status, done.photos, done.skipped) == ("done", 3, 0)


async def test_a_photo_that_keeps_failing_is_counted_after_several_steps_not_one() -> None:
    r = rig(items=2)

    async def never(uid: str, item: object) -> bytes:
        if getattr(item, "id", "") == "m0":
            raise PickerRetry("429")
        return JPEG + b"m1"

    async def nap(s: float) -> None:
        return None

    r.picker.download = never  # type: ignore[method-assign]
    r.svc._importer._sleep = nap  # type: ignore[union-attr]  # noqa: SLF001
    await r.svc.begin(UID)
    for step in range(1, MAX_STUCK_STEPS):
        await r.svc.collect(UID)
        assert (await r.svc.imports.get(UID)).skipped == 0, step
    res = await r.svc.collect(UID)
    assert (res.status, res.skipped) == ("done", 1)


async def test_a_bad_photo_is_still_skipped_at_once() -> None:
    r = rig(items=2)
    r.picker.fail = {"m0"}  # PickerError: not a JPEG, too large, 403/404
    await r.svc.begin(UID)
    res = await r.svc.collect(UID)
    assert (res.status, res.photos, res.skipped) == ("done", 1, 1)


class _Google:
    """The Google connector, as far as a download goes: one canned answer."""

    def __init__(self, handler: object) -> None:
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]

    async def access_token(self, uid: str) -> str:
        return "token"

    async def request(self, *a: object, **k: object) -> dict[str, object]:
        return {}


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_the_picker_says_try_later_for_googles_own_trouble(status: int) -> None:
    from jarvis.photos.models import PickedItem

    client = PickerClient(_Google(lambda req: httpx.Response(status)))  # type: ignore[arg-type]
    client._require = lambda uid: asyncio.sleep(0)  # type: ignore[method-assign]  # noqa: SLF001
    with pytest.raises(PickerRetry):
        await client.download(
            UID, PickedItem("m0", "image/jpeg", "https://lh3.googleusercontent.com/x")
        )


@pytest.mark.parametrize("status", [403, 404, 410])
async def test_the_picker_says_bad_photo_for_a_refusal(status: int) -> None:
    from jarvis.photos.models import PickedItem

    client = PickerClient(_Google(lambda req: httpx.Response(status)))  # type: ignore[arg-type]
    client._require = lambda uid: asyncio.sleep(0)  # type: ignore[method-assign]  # noqa: SLF001
    with pytest.raises(PickerError) as err:
        await client.download(
            UID, PickedItem("m0", "image/jpeg", "https://lh3.googleusercontent.com/x")
        )
    assert not isinstance(err.value, PickerRetry)


async def test_the_picker_says_try_later_for_a_timeout() -> None:
    from jarvis.photos.models import PickedItem

    def slow(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    client = PickerClient(_Google(slow))  # type: ignore[arg-type]
    client._require = lambda uid: asyncio.sleep(0)  # type: ignore[method-assign]  # noqa: SLF001
    with pytest.raises(PickerRetry):
        await client.download(
            UID, PickedItem("m0", "image/jpeg", "https://lh3.googleusercontent.com/x")
        )
