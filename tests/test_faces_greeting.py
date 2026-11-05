# tests/test_faces_greeting.py -- R3 D13/D10: greeting words and the 30-minute gap.
from __future__ import annotations

from faces_fakes import UID, add_adult, add_child, enrol, faces

from jarvis.faces.greeting import GreetingLimiter, alert_line, feed_line
from jarvis.faces.ports import FAMILY_CHILD, RECOGNISED_PERSON, UNKNOWN, UNKNOWN_PERSON


async def test_the_console_feed_names_an_enrolled_person_and_nobody_else() -> None:
    f = faces()
    p = await add_adult(f)
    await enrol(f, p)
    who = await f.directory.resolve(UID, p.id, 0.95)
    assert feed_line(who, "Gate", "18:42") == "Anjali arrived at Gate, 18:42"
    assert feed_line(UNKNOWN, "Gate", "18:42") == f"{UNKNOWN_PERSON} arrived at Gate, 18:42"
    assert feed_line(UNKNOWN, "  ", "18:42").startswith(f"{UNKNOWN_PERSON} arrived at the camera")


async def test_alert_words_follow_the_names_switch_and_never_name_a_child() -> None:
    f = faces()
    a, k = await add_adult(f), await add_child(f)
    await enrol(f, a)
    await enrol(f, k)
    adult = await f.directory.resolve(UID, a.id, 0.95)
    kid = await f.directory.resolve(UID, k.id, 0.95)
    assert alert_line(adult, "Gate", "18:42", say_names=False).startswith(RECOGNISED_PERSON)
    assert alert_line(adult, "Gate", "18:42", say_names=True).startswith("Anjali")
    for on in (True, False):
        text = alert_line(kid, "Gate", "18:42", say_names=on)
        assert text.startswith(FAMILY_CHILD) and "Mini" not in text
        assert alert_line(UNKNOWN, "Gate", "18:42", say_names=on).startswith(UNKNOWN_PERSON)
    assert len(alert_line(adult, "x" * 500, "18:42", say_names=True)) <= 300


async def test_one_greeting_per_person_per_30_minutes_and_never_for_unknown() -> None:
    f = faces()
    a, b = await add_adult(f), await add_adult(f, "Ravi")
    await enrol(f, a)
    await enrol(f, b)
    clock = [1000.0]
    lim = GreetingLimiter(now=lambda: clock[0])
    wa = await f.directory.resolve(UID, a.id, 0.95)
    wb = await f.directory.resolve(UID, b.id, 0.95)
    assert lim.allow(wa) is True and lim.allow(wa) is False and lim.allow(wb) is True
    clock[0] += 29 * 60
    assert lim.allow(wa) is False
    clock[0] += 2 * 60
    assert lim.allow(wa) is True
    assert lim.allow(UNKNOWN) is False


def test_the_limiter_forgets_old_people_instead_of_growing() -> None:
    import time

    from jarvis.faces.ports import Resolved

    clock = [time.time()]
    lim = GreetingLimiter(now=lambda: clock[0])
    for i in range(205):
        lim.allow(Resolved(name=f"P{i}", person=f"fp_{i:012x}"))
        clock[0] += 20 * 60  # each earlier person is past the gap soon enough
    assert len(lim._last) < 20  # type: ignore[attr-defined]
