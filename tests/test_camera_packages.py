# tests/test_camera_packages.py -- R3 D16: empty -> package alerts once; a repeat or a flap in 10
# minutes does not; package -> empty is only remembered; a zone that isn't the doorstep is ignored;
# without the trained model the owner is told in plain words.
from __future__ import annotations

from camera_fakes import T0, UID, Rig, rig

from jarvis.camera.packages import NO_MODEL_NOTE, model_note
from jarvis.home.ports import Package


def pkg(state: str, at: float, *, zone: str = "doorstep", delivered: bool = False) -> Package:
    return Package(
        type="package",
        id=f"p-{state}-{int(at)}",
        camera="gate",
        zone=zone,
        state=state,  # type: ignore[arg-type]
        at=at,
        delivered=delivered,
    )


async def alerts(r: Rig) -> list[str]:
    return [s.message for s in r.notifier.sent if s.signal.kind == "home_package"]


async def test_empty_to_package_is_one_important_alert() -> None:
    r = await rig()
    await r.events.handle(UID, pkg("package", T0))
    got = await alerts(r)
    assert len(got) == 1 and got[0].startswith("A package was left at Gate, ")
    assert r.notifier.sent[0].signal.camera == "gate"


async def test_package_again_is_no_second_alert() -> None:
    r = await rig()
    await r.events.handle(UID, pkg("package", T0))
    await r.events.handle(UID, pkg("package", T0 + 3600))
    assert len(await alerts(r)) == 1


async def test_flapping_inside_ten_minutes_is_one_change() -> None:
    r = await rig()
    await r.events.handle(UID, pkg("package", T0))
    await r.events.handle(UID, pkg("empty", T0 + 60))
    await r.events.handle(UID, pkg("package", T0 + 120))
    assert len(await alerts(r)) == 1


async def test_a_real_second_parcel_after_ten_minutes_alerts_again() -> None:
    r = await rig()
    await r.events.handle(UID, pkg("package", T0))
    await r.events.handle(UID, pkg("empty", T0 + 700))
    await r.events.handle(UID, pkg("package", T0 + 800))
    assert len(await alerts(r)) == 2


async def test_package_gone_is_logged_only() -> None:
    r = await rig()
    await r.events.handle(UID, pkg("empty", T0))
    assert r.notifier.sent == [] and await r.feed.view(UID, "today") == []


async def test_a_zone_that_is_not_the_doorstep_is_ignored() -> None:
    r = await rig()
    await r.events.handle(UID, pkg("package", T0, zone="gate"))
    assert r.notifier.sent == []


async def test_a_delivery_is_marked_in_the_feed() -> None:
    r = await rig()
    await r.events.handle(UID, pkg("package", T0, delivered=True))
    line = (await r.feed.view(UID, "today"))[0]
    assert line["words"] == "A package was left at Gate (a delivery)"


async def test_without_the_model_the_note_says_what_to_do() -> None:
    r = await rig()
    s = await r.config.get(UID)
    assert model_note(s) == NO_MODEL_NOTE and "step 12" in NO_MODEL_NOTE
    await r.events.handle(UID, (await _hb(True)))
    assert model_note(await r.config.get(UID)) is None


async def _hb(model: bool):  # noqa: ANN202
    from jarvis.home.ports import Heartbeat, HeartbeatParts

    return Heartbeat(
        type="heartbeat",
        id="h",
        at=T0,
        bridge_version="1.0.0",
        state_rev=0,
        parts=HeartbeatParts(doorstep_model=model),
    )


async def test_quiet_hours_hold_is_recorded_in_the_feed() -> None:
    r = await rig()
    r.notifier.action = "hold"
    await r.events.handle(UID, pkg("package", T0))
    line = (await r.feed.view(UID, "today"))[0]
    assert line["decision"] == "held"
