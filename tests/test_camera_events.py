# tests/test_camera_events.py -- R3 D8/D9/D12/D13: an armed detection raises ONE urgent alert;
# a disarmed one is dropped and counted; recognition never softens it; labels are untrusted; a child
# is never named; a snapshot is passed through only after the opt-in and never stored.
from __future__ import annotations

import base64
import json

from camera_fakes import CHILD, PERSON, T0, UID, Rig, rig

from jarvis.camera.events import ARM_ACK_PREFIX
from jarvis.camera.models import CameraConfig
from jarvis.faces.ports import Resolved
from jarvis.home.ports import (
    Ack,
    Detection,
    FaceMatch,
    FaceSeen,
    Heartbeat,
    HeartbeatParts,
    parse_event,
)

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100


def det(**kw: object) -> Detection:
    base: dict[str, object] = {
        "type": "detection",
        "id": "evt-1",
        "camera": "gate",
        "zones": ["gate"],
        "label": "person",
        "start": T0,
        "score": 0.9,
    }
    base.update(kw)
    ev = parse_event(json.dumps(base).encode())
    assert isinstance(ev, Detection)
    return ev


async def armed(r: Rig) -> None:
    await r.alarm.arm(UID, "away", "console")


async def test_armed_person_in_the_gate_zone_raises_one_urgent_alert() -> None:
    r = await rig()
    await armed(r)
    await r.events.handle(UID, det())
    assert len(r.notifier.sent) == 1
    s = r.notifier.sent[0]
    assert s.signal.kind == "home_intruder" and s.signal.camera == "gate"
    assert s.message.startswith("Burglar alert at Gate at ") and len(s.message) <= 300
    assert "someone JARVIS didn't recognise" in s.message
    assert s.named is None and s.photo is None


async def test_the_alert_path_takes_no_time_on_the_mock_clock() -> None:
    r = await rig()
    await armed(r)
    before = r.clock.now
    await r.events.handle(UID, det())
    assert r.clock.now - before <= 1.5 and len(r.notifier.sent) == 1


async def test_disarmed_detection_is_dropped_counted_and_never_alerts() -> None:
    r = await rig()
    await r.events.handle(UID, det())
    assert r.notifier.sent == []
    assert (await r.alarm.record(UID)).dropped_disarmed == 1


async def test_a_detection_outside_the_alarm_zones_or_on_an_unknown_camera_is_dropped() -> None:
    r = await rig()
    await armed(r)
    await r.events.handle(UID, det(zones=["road"]))
    await r.events.handle(UID, det(id="evt-2", zones=[]))
    await r.events.handle(UID, det(id="evt-3", camera="back"))
    assert r.notifier.sent == []


async def test_an_unreadable_arm_record_still_alerts() -> None:
    r = await rig()
    await armed(r)
    r.docs._data[f"jarvis_home_arm/{UID}"] = {"armed": "garbage", "rev": "x"}
    await r.events.handle(UID, det())
    assert len(r.notifier.sent) == 1


async def test_unreadable_camera_settings_do_not_stop_the_alert() -> None:
    r = await rig()
    await armed(r)
    r.docs._data[f"jarvis_home_cameras/{UID}"] = {"blob": "not sealed"}
    await r.events.handle(UID, det())
    assert len(r.notifier.sent) == 1
    assert "at gate at" in r.notifier.sent[0].message  # no label known: the id in words


async def test_a_vip_face_at_the_gate_while_armed_still_rings_and_is_marked() -> None:
    r = await rig()
    await armed(r)
    r.faces.people[PERSON] = Resolved(name="Anjali", person=PERSON, vip=True)
    await r.events.handle(UID, det(face={"person": PERSON, "score": 0.95}))
    s = r.notifier.sent[0]
    assert s.signal.vip is True and s.signal.person_ref == PERSON
    assert "a person JARVIS recognised" in s.message and "Anjali" not in s.message
    assert s.named is not None and "Anjali (face matched)" in s.named


async def test_a_child_is_never_named_even_in_the_named_text() -> None:
    r = await rig()
    await armed(r)
    r.faces.people[CHILD] = Resolved(name="Mini", person=CHILD, child=True)
    await r.events.handle(UID, det(face={"person": CHILD, "score": 0.95}))
    s = r.notifier.sent[0]
    assert "a child from your family" in s.message and s.signal.child is True
    assert s.named is None and "Mini" not in s.message


async def test_a_low_score_or_unknown_id_is_a_stranger() -> None:
    r = await rig()
    await armed(r)
    r.faces.people[PERSON] = Resolved(name="Anjali", person=PERSON)
    await r.events.handle(UID, det(face={"person": PERSON, "score": 0.89}))
    assert "someone JARVIS didn't recognise" in r.notifier.sent[0].message
    assert r.notifier.sent[0].named is None


async def test_a_car_while_armed_is_a_feed_line_not_an_alert() -> None:
    r = await rig()
    await armed(r)
    await r.events.handle(UID, det(label="car"))
    assert r.notifier.sent == []
    lines = await r.feed.view(UID, "today")
    assert lines[0]["words"] == "A car at Gate" and lines[0]["decision"] == "dropped"


async def test_alert_text_uses_only_the_owners_label_never_frigate_words() -> None:
    r = await rig()
    await r.config.set_cameras(
        UID, {"gate": CameraConfig(label="Front\ngate‮", alarm_zones=("gate",))}
    )
    await armed(r)
    await r.events.handle(UID, det())
    msg = r.notifier.sent[0].message
    assert "\n" not in msg and "‮" not in msg and "Front gate" in msg


async def test_snapshot_is_passed_through_only_after_the_opt_in() -> None:
    r = await rig()
    await armed(r)
    snap = base64.b64encode(JPEG).decode()
    await r.events.handle(UID, det(snapshot=snap))
    assert r.notifier.sent[0].photo is None
    r.snap.on = True
    await r.events.handle(UID, det(id="evt-2", snapshot=snap))
    assert r.notifier.sent[1].photo == JPEG


async def test_the_snapshot_is_never_stored_anywhere() -> None:
    r = await rig()
    await armed(r)
    r.snap.on = True
    snap = base64.b64encode(JPEG).decode()
    await r.events.handle(UID, det(snapshot=snap))
    dump = json.dumps(r.docs._data, default=str)
    assert snap not in dump and JPEG.hex() not in dump
    line = (await r.feed.view(UID, "today"))[0]
    assert "snapshot" not in json.dumps(line)


async def test_a_failed_send_is_tried_again_once() -> None:
    r = await rig()
    await armed(r)
    r.notifier.fail_times = 1
    await r.events.handle(UID, det())
    assert len(r.notifier.sent) == 1


async def test_a_notifier_that_keeps_failing_never_raises_into_the_webhook() -> None:
    r = await rig()
    await armed(r)
    r.notifier.fail_times = 5
    await r.events.handle(UID, det())
    assert r.notifier.sent == []


async def test_the_feed_line_is_written_after_the_alert_and_holds_ids_not_names() -> None:
    r = await rig()
    await armed(r)
    r.faces.people[PERSON] = Resolved(name="Anjali", person=PERSON)
    await r.events.handle(UID, det(face={"person": PERSON, "score": 0.95}))
    dump = json.dumps(r.docs._data, default=str)
    assert "Anjali" not in dump and "Gate" not in dump  # sealed
    line = (await r.feed.view(UID, "today"))[0]
    assert line["who"] == "Anjali" and line["decision"] == "ring"
    r.faces.people.clear()  # deleted: every old line turns into "someone"
    line = (await r.feed.view(UID, "today"))[0]
    assert line["who"] == "someone JARVIS didn't recognise"


async def test_greeting_while_disarmed_for_a_consented_person() -> None:
    r = await rig()
    r.faces.people[PERSON] = Resolved(name="Anjali", person=PERSON)
    ev = FaceSeen(
        type="face_seen",
        id="f1",
        event="e1",
        camera="gate",
        zones=("gate",),
        at=T0,
        face=FaceMatch(person=PERSON, score=0.95),
    )
    await r.events.handle(UID, ev)
    s = r.notifier.sent[0]
    assert s.signal.kind == "home_greeting" and "Anjali" not in s.message
    assert s.named == "Anjali arrived at Gate."
    again = ev.model_copy(update={"id": "f2", "at": T0 + 600})
    await r.events.handle(UID, again)  # one per person per 30 minutes
    assert len(r.notifier.sent) == 1
    assert len(await r.feed.view(UID, "today")) == 1
    later = ev.model_copy(update={"id": "f3", "at": T0 + 1900})
    await r.events.handle(UID, later)
    assert len(r.notifier.sent) == 2


async def test_greeting_is_only_for_a_named_person_and_off_when_switched_off() -> None:
    r = await rig()
    ev = FaceSeen(
        type="face_seen",
        id="f1",
        event="e1",
        camera="gate",
        zones=("gate",),
        at=T0,
        face=FaceMatch(person=PERSON, score=0.95),
    )
    await r.events.handle(UID, ev)  # nobody enrolled: nothing
    assert r.notifier.sent == [] and await r.feed.view(UID, "today") == []
    r.faces.people[PERSON] = Resolved(name="Anjali", person=PERSON)
    await r.config.set_cameras(UID, (await r.config.get(UID)).cameras, greetings=False)
    await r.events.handle(UID, ev)
    assert r.notifier.sent == []


async def test_a_greeting_while_armed_is_a_feed_line_only() -> None:
    r = await rig()
    await armed(r)
    r.faces.people[PERSON] = Resolved(name="Anjali", person=PERSON)
    ev = FaceSeen(
        type="face_seen",
        id="f1",
        event="e1",
        camera="gate",
        zones=(),
        at=T0,
        face=FaceMatch(person=PERSON, score=0.95),
    )
    await r.events.handle(UID, ev)
    assert r.notifier.sent == [] and len(await r.feed.view(UID, "today")) == 1


async def test_only_the_arm_prefixed_ack_confirms_the_alarm() -> None:
    r = await rig()
    await armed(r)
    other = Ack(type="ack", id="devices-1", at=T0, what="state", rev=1)
    await r.events.handle(UID, other)
    assert (await r.alarm.view(UID)).confirmed is False
    mine = Ack(type="ack", id=f"{ARM_ACK_PREFIX}1:abc", at=T0, what="state", rev=1)
    await r.events.handle(UID, mine)
    assert (await r.alarm.view(UID)).confirmed is True


async def test_heartbeat_parts_are_stored_once_and_not_rewritten_when_unchanged() -> None:
    r = await rig()
    hb = Heartbeat(
        type="heartbeat",
        id="h1",
        at=T0,
        bridge_version="1.0.0",
        state_rev=0,
        parts=HeartbeatParts(doorstep_model=True),
    )
    await r.events.handle(UID, hb)
    sets = r.docs.sets
    await r.events.handle(UID, hb.model_copy(update={"id": "h2"}))
    assert r.docs.sets == sets
    assert (await r.config.get(UID)).status.doorstep_model is True
