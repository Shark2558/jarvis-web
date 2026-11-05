# tests/test_notify_service.py -- R3 D10/D12: storm control, held alerts, settings store, the
# notifier (both channels, contained failures, names, photo), the Telegram adapter's buckets.
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from notify_fakes import MIDNIGHT, NOON, build
from telegram_fakes import UID

from jarvis.alerts import AlertSink
from jarvis.notify.held import summary
from jarvis.notify.models import NotifySettings, Snapshot
from jarvis.notify.policy import decide
from jarvis.notify.ports import Decision, Notifier, Signal
from jarvis.notify.sink import PolicyAlerts
from jarvis.notify.store import MAX_HELD, NotifyUnavailable
from jarvis.notify.storm import MAX_URGENT_IN_WINDOW, Storm, summary_text
from jarvis.notify.telegram_out import URGENT_PER_HOUR


def intruder(camera: str = "gate") -> Signal:
    return Signal(source="home", kind="home_intruder", camera=camera)


# ---- storm control ---------------------------------------------------------------------------


def test_one_intruder_alert_per_camera_per_minute() -> None:
    s, d = Storm(), Decision(action="ring", reason="intruder", urgency="urgent")
    assert s.admit(UID, intruder(), d, NOON).admit
    assert not s.admit(UID, intruder(), d, NOON + timedelta(seconds=59)).admit
    assert s.admit(UID, intruder("door"), d, NOON + timedelta(seconds=59)).admit
    assert s.admit(UID, intruder(), d, NOON + timedelta(seconds=60)).admit


def test_fifty_detections_in_two_minutes_give_few_rings_and_one_summary() -> None:
    s, d = Storm(), Decision(action="ring", reason="intruder", urgency="urgent")
    rings = 0
    for i in range(50):
        cam = f"c{i % 20}"  # different cameras so only the 10-in-10-minutes cap bites
        rings += s.admit(UID, intruder(cam), d, NOON + timedelta(seconds=i * 2)).admit
    assert rings == MAX_URGENT_IN_WINDOW
    assert s.due_summary(UID, NOON + timedelta(minutes=5)) == 0
    assert s.due_summary(UID, NOON + timedelta(minutes=11)) == 40
    assert s.due_summary(UID, NOON + timedelta(minutes=30)) == 0


def test_the_window_slides() -> None:
    s, d = Storm(), Decision(action="ring", reason="x", urgency="urgent")
    sig = Signal(source="home", kind="home_hazard")
    for i in range(10):
        assert s.admit(UID, sig, d, NOON + timedelta(seconds=i)).admit
    assert not s.admit(UID, sig, d, NOON + timedelta(minutes=9)).admit
    assert s.admit(UID, sig, d, NOON + timedelta(minutes=11)).admit


def test_packages_are_ten_minutes_apart_and_greetings_thirty_per_person() -> None:
    s, d = Storm(), Decision(action="silent", reason="x", urgency="important")
    pkg = Signal(source="home", kind="home_package")
    assert s.admit(UID, pkg, d, NOON).admit
    assert not s.admit(UID, pkg, d, NOON + timedelta(minutes=9)).admit
    assert s.admit(UID, pkg, d, NOON + timedelta(minutes=10)).admit
    g1 = Signal(source="home", kind="home_greeting", person_ref="fp_aaaaaaaaaaaa")
    g2 = Signal(source="home", kind="home_greeting", person_ref="fp_bbbbbbbbbbbb")
    assert s.admit(UID, g1, d, NOON).admit and s.admit(UID, g2, d, NOON).admit
    assert not s.admit(UID, g1, d, NOON + timedelta(minutes=29)).admit
    assert s.admit(UID, g1, d, NOON + timedelta(minutes=30)).admit


def test_owners_do_not_share_a_storm() -> None:
    s, d = Storm(), Decision(action="ring", reason="x", urgency="urgent")
    assert s.admit("a", intruder(), d, NOON).admit and s.admit("b", intruder(), d, NOON).admit


def test_summary_text_is_short_and_plain() -> None:
    assert "12 more alerts" in summary_text(12) and "1 more alert " in summary_text(1)
    assert summary_text(3).isascii() and len(summary_text(500)) <= 300


# ---- settings store --------------------------------------------------------------------------


async def test_settings_default_update_and_rev() -> None:
    w = await build()
    assert (await w.store.get(UID)) == NotifySettings()
    got = await w.store.update(UID, lambda s: s.model_copy(update={"ring_for": "important"}))
    assert got.rev == 1 and (await w.store.get(UID)).ring_for == "important"
    await w.store.reset(UID)
    assert (await w.store.get(UID)).rev == 0


async def test_a_bad_stored_document_fails_closed_and_is_not_overwritten() -> None:
    w = await build()
    w.docs._data["jarvis_notify/owner"] = {"ring_for": "bogus"}
    with pytest.raises(NotifyUnavailable):
        await w.store.get(UID)
    with pytest.raises(NotifyUnavailable):
        await w.store.update(UID, lambda s: s)
    assert w.docs._data["jarvis_notify/owner"] == {"ring_for": "bogus"}


async def test_an_invalid_change_is_refused_by_the_model() -> None:
    w = await build()
    with pytest.raises(ValueError):
        await w.store.update(UID, lambda s: s.model_copy(update={"kinds": {"nope": "on"}}))


async def test_a_bad_owner_id_is_refused() -> None:
    w = await build()
    with pytest.raises(NotifyUnavailable):
        await w.store.get("../x")
    with pytest.raises(ValueError):
        await w.store.take_urgent("../x", NOON, per_hour=1, per_day=1)


async def test_held_is_kept_as_kinds_and_times_and_capped() -> None:
    w = await build()
    for i in range(MAX_HELD + 5):
        await w.store.held_add(UID, {"kind": "home_package", "at": f"t{i}"})
    assert len(await w.store.held_list(UID)) == MAX_HELD
    assert await w.store.held_owners() == [UID]
    taken = await w.store.held_take(UID)
    assert len(taken) == MAX_HELD and await w.store.held_take(UID) == []


async def test_sweep_removes_old_rate_documents() -> None:
    w = await build()
    await w.store.take_urgent(UID, NOON - timedelta(days=10), per_hour=5, per_day=5)
    await w.store.take_urgent(UID, NOON, per_hour=5, per_day=5)
    assert await w.store.sweep(NOON) == 2
    assert len([k for k in w.docs._data if "notify_rate" in k]) == 2


async def test_storage_failures_are_plain_words() -> None:
    w = await build()

    async def boom(*a: object, **k: object) -> None:
        raise RuntimeError("secret detail")

    w.docs.get = boom  # type: ignore[method-assign]
    with pytest.raises(NotifyUnavailable) as e:
        await w.store.get(UID)
    assert "secret" not in str(e.value)
    w.docs.transaction = boom  # type: ignore[method-assign]
    with pytest.raises(NotifyUnavailable):
        await w.store.held_add(UID, {"kind": "x", "at": "t"})
    with pytest.raises(NotifyUnavailable):
        await w.store.held_take(UID)
    with pytest.raises(NotifyUnavailable):
        await w.store.update(UID, lambda s: s)


# ---- the notifier ----------------------------------------------------------------------------


async def test_it_is_a_notifier_and_the_sink_is_an_alert_sink() -> None:
    w = await build()
    assert isinstance(w.service, Notifier) and isinstance(PolicyAlerts(w.service), AlertSink)


async def test_a_burglar_alert_goes_to_telegram_and_every_browser_loudly() -> None:
    w = await build()
    d = await w.service.notify(UID, intruder(), "Someone is at the Gate.")
    assert (d.action, d.telegram, d.push) == ("ring", True, 1)
    [(_, sent)] = [c for c in w.tg.bot.calls if c[0] == "sendMessage"]
    assert sent["text"] == "Someone is at the Gate." and sent["disable_notification"] is False
    assert w.push.requests[0].headers["urgency"] == "high"
    assert d.feed_decision == "ring"


async def test_important_alerts_are_silent_by_default_on_both_channels() -> None:
    w = await build()
    d = await w.service.notify(UID, Signal(source="home", kind="home_package"), "A package.")
    assert d.action == "silent" and d.telegram and d.push == 1
    assert w.tg.bot.of("sendMessage")[-1]["disable_notification"] is True
    assert w.push.requests[0].headers["urgency"] == "low"


async def test_quiet_hours_hold_then_one_summary_when_they_end() -> None:
    w = await build(MIDNIGHT)
    for _ in range(3):
        d = await w.service.notify(UID, Signal(source="home", kind="home_package"), "A package.")
        assert d.action == "hold" and not d.telegram and d.push == 0
    assert w.tg.bot.of("sendMessage") == []
    assert await w.service.flush_held(UID) is False  # still night
    w.clock.now = NOON
    assert await w.service.flush_held(UID) is True
    [msg] = w.tg.bot.texts
    assert "3 alerts" in msg and "package" in msg
    assert await w.service.flush_held(UID) is False
    assert await w.service.flush_all_held() == 0


async def test_flush_all_held_sends_each_owner_once() -> None:
    w = await build(MIDNIGHT)
    await w.service.notify(UID, Signal(source="home", kind="home_offline"), "Laptop off.")
    w.clock.now = NOON
    assert await w.service.flush_all_held() == 1 and len(w.tg.bot.texts) == 1


async def test_a_failed_hold_rings_instead_of_losing_the_alert() -> None:
    w = await build(MIDNIGHT)

    async def boom(*a: object, **k: object) -> None:
        raise NotifyUnavailable("x")

    w.service.store.held_add = boom  # type: ignore[method-assign]
    d = await w.service.notify(UID, Signal(source="home", kind="home_offline"), "Laptop off.")
    assert d.reason == "hold_failed" and d.telegram


async def test_dropped_decisions_send_nothing_but_are_reported() -> None:
    w = await build()
    d = await w.service.notify(UID, Signal(source="home", kind="home_greeting"), "Anjali arrived.")
    assert (d.action, d.reason, d.feed_decision) == ("drop", "feed_only", "dropped")
    assert w.tg.bot.calls == [] and w.push.requests == []


async def test_a_failing_push_never_blocks_telegram() -> None:
    w = await build()

    async def boom(*a: object, **k: object) -> int:
        raise RuntimeError("push down")

    w.push.service.send = boom  # type: ignore[method-assign]
    d = await w.service.notify(UID, intruder(), "Someone.")
    assert d.telegram is True and d.push == 0


async def test_a_failing_telegram_never_blocks_push() -> None:
    w = await build()
    w.tg.bot.raise_transport = True
    d = await w.service.notify(UID, intruder(), "Someone.")
    assert d.telegram is False and d.push == 1


async def test_a_raising_sink_is_contained_too() -> None:
    w = await build()

    async def boom(*a: object, **k: object) -> None:
        raise RuntimeError("sink down")

    w.alerts.send = boom  # type: ignore[method-assign]
    d = await w.service.notify(UID, intruder(), "Someone.")
    assert d.telegram is False and d.push == 1


async def test_no_channels_at_all_is_a_quiet_failure() -> None:
    w = await build(with_push=False)
    w.service._telegram = None
    d = await w.service.notify(UID, intruder(), "Someone.")
    assert (d.telegram, d.push) == (False, 0)


async def test_unreadable_settings_still_let_a_burglar_alert_through() -> None:
    w = await build()
    w.docs._data["jarvis_notify/owner"] = {"ring_for": "bogus"}
    d = await w.service.notify(UID, intruder(), "Someone.")
    assert d.action == "ring" and d.telegram
    assert w.docs._data["jarvis_notify/owner"] == {"ring_for": "bogus"}


async def test_storm_suppresses_a_repeat_and_a_later_alert_carries_the_summary() -> None:
    w = await build()
    assert (await w.service.notify(UID, intruder(), "Someone.")).action == "ring"
    d = await w.service.notify(UID, intruder(), "Someone.")
    assert (d.action, d.reason) == ("drop", "storm")
    w.clock.advance(minutes=11)
    await w.service.notify(UID, intruder(), "Someone.")
    assert any("1 more alert" in t for t in w.tg.bot.texts)


async def test_the_tick_sends_a_due_summary_without_a_new_alert() -> None:
    w = await build()
    await w.service.notify(UID, intruder(), "Someone.")
    await w.service.notify(UID, intruder(), "Someone.")
    assert await w.service.flush_summaries() == 0
    w.clock.advance(minutes=11)
    assert await w.service.flush_summaries() == 1
    assert "1 more alert" in w.tg.bot.texts[-1]


# ---- names and the photo ---------------------------------------------------------------------


async def test_names_only_with_the_switch_and_never_for_a_child() -> None:
    w = await build()
    sig = Signal(source="home", kind="home_intruder", camera="gate", person_ref="fp_aaaaaaaaaaaa")
    await w.service.notify(UID, sig, "A person JARVIS recognised.", named_message="Anjali is here.")
    assert w.tg.bot.texts[-1] == "A person JARVIS recognised."
    await w.store.update(UID, lambda s: s.model_copy(update={"names_in_alerts": True}))
    w.clock.advance(minutes=2)
    await w.service.notify(UID, sig, "A person JARVIS recognised.", named_message="Anjali is here.")
    assert w.tg.bot.texts[-1] == "Anjali is here."
    w.clock.advance(minutes=2)
    child = sig.model_copy(update={"child": True})
    await w.service.notify(UID, child, "A child from your family.", named_message="Kid is here.")
    assert w.tg.bot.texts[-1] == "A child from your family."
    assert all("Kid" not in r.content.decode("latin-1") for r in w.push.requests)


async def test_text_is_cleaned_and_capped() -> None:
    w = await build()
    await w.service.notify(UID, intruder(), "a\n\n" + "b" * 500)
    assert "\n" not in w.tg.bot.texts[-1] and len(w.tg.bot.texts[-1]) <= 300


async def test_the_photo_needs_the_opt_in_a_burglar_alert_and_a_ring() -> None:
    w = await build()
    jpg = b"\xff\xd8JPEGBYTES"
    d = await w.service.notify(UID, intruder(), "Someone.", photo=jpg)
    assert d.photo_sent is False and w.photos == []  # off by default (D20)
    await w.store.update(
        UID, lambda s: s.model_copy(update={"snapshot": Snapshot(on=True, at="t")})
    )
    w.clock.advance(minutes=2)
    d = await w.service.notify(UID, intruder(), "Someone.", photo=jpg)
    assert d.photo_sent is True and w.photos == [(555001234, jpg, "Someone.")]
    n = len(w.tg.bot.of("sendMessage"))
    w.clock.advance(minutes=2)
    d = await w.service.notify(UID, Signal(source="home", kind="home_package"), "Pkg.", photo=jpg)
    assert d.photo_sent is False and len(w.photos) == 1 and len(w.tg.bot.of("sendMessage")) == n + 1


async def test_the_photo_never_reaches_push_audit_docs_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = await build()
    await w.store.update(
        UID, lambda s: s.model_copy(update={"snapshot": Snapshot(on=True, at="t")})
    )
    jpg = b"\xff\xd8NEEDLEJPEG"
    await w.service.notify(UID, intruder(), "Someone.", photo=jpg)
    assert all(b"NEEDLEJPEG" not in r.content for r in w.push.requests)
    assert "NEEDLEJPEG" not in json.dumps(w.docs._data, default=str)
    assert "NEEDLEJPEG" not in repr(w.tg.audit._entries) + repr(w.push.audit.args) + caplog.text


async def test_a_failing_photo_falls_back_to_the_text() -> None:
    w = await build()
    await w.store.update(
        UID, lambda s: s.model_copy(update={"snapshot": Snapshot(on=True, at="t")})
    )

    async def boom(*a: object) -> None:
        raise RuntimeError("no photo")

    w.alerts._photo_sender = boom
    d = await w.service.notify(UID, intruder(), "Someone.", photo=b"x")
    assert d.telegram and not d.photo_sent and w.tg.bot.texts[-1] == "Someone."


async def test_without_a_photo_sender_the_photo_is_dropped() -> None:
    w = await build()
    await w.store.update(
        UID, lambda s: s.model_copy(update={"snapshot": Snapshot(on=True, at="t")})
    )
    w.alerts._photo_sender = None
    d = await w.service.notify(UID, intruder(), "Someone.", photo=b"x")
    assert d.telegram and not d.photo_sent


# ---- the Telegram adapter --------------------------------------------------------------------


async def test_every_r3_kind_reaches_telegram_when_the_policy_lets_it() -> None:
    w = await build(with_push=False)
    for kind in (
        "home_intruder",
        "home_hazard",
        "home_summary",
        "home_package",
        "home_offline",
        "home_arm_failed",
        "home_online",
    ):
        res = await w.alerts.send(UID, f"{kind} text", kind=kind)  # type: ignore[arg-type]
        assert res.sent, kind


async def test_r1_per_kind_telegram_switches_still_apply() -> None:
    w = await build(with_push=False)
    assert (await w.alerts.send(UID, "Brief.", kind="brief_ready")).reason.startswith(
        "switched off"
    )
    assert (await w.alerts.send(UID, "Wait.", kind="approval_waiting")).sent
    assert (await w.alerts.send(UID, "Test.", kind="test")).sent


async def test_not_paired_and_unreadable_link_say_so() -> None:
    w = await build(paired=False, with_push=False)
    assert "pair" in (await w.alerts.send(UID, "x", kind="test")).reason.lower()

    async def boom(uid: str) -> None:
        raise RuntimeError("x")

    w.alerts._store.get = boom  # type: ignore[method-assign]
    assert (await w.alerts.send(UID, "x", kind="test")).sent is False


async def test_the_urgent_bucket_is_not_used_up_by_normal_alerts() -> None:
    w = await build(with_push=False)
    sent = [(await w.alerts.send(UID, "w", kind="approval_waiting")).sent for _ in range(12)]
    assert sent.count(True) == 10
    assert (await w.alerts.send(UID, "w", kind="approval_waiting")).reason.startswith("alert limit")
    assert (await w.alerts.send(UID, "Someone.", kind="home_intruder")).sent


async def test_urgent_has_its_own_hourly_cap() -> None:
    w = await build(with_push=False)
    res = [
        (await w.alerts.send(UID, "x", kind="home_hazard")).sent for _ in range(URGENT_PER_HOUR + 3)
    ]
    assert res.count(True) == URGENT_PER_HOUR


async def test_urgent_counter_unreadable_still_sends_with_a_local_cap() -> None:
    w = await build(with_push=False)

    async def boom(*a: object, **k: object) -> bool:
        raise RuntimeError("down")

    w.alerts._notify.take_urgent = boom  # type: ignore[method-assign]
    ticks = iter(range(10_000))
    w.alerts._clock = lambda: float(next(ticks))
    res = [
        (await w.alerts.send(UID, "x", kind="home_intruder")).sent
        for _ in range(URGENT_PER_HOUR + 2)
    ]
    assert res.count(True) == URGENT_PER_HOUR
    w.alerts._clock = lambda: 4000.0  # an hour on, the local cap has room again
    assert (await w.alerts.send(UID, "x", kind="home_intruder")).sent


async def test_normal_counter_unreadable_is_not_sent() -> None:
    w = await build(with_push=False)

    async def boom(*a: object, **k: object) -> bool:
        raise RuntimeError("down")

    w.tg.store.count_alert = boom  # type: ignore[method-assign]
    res = await w.alerts.send(UID, "w", kind="approval_waiting")
    assert res.sent is False and "limit" in res.reason and w.tg.bot.calls == []


async def test_a_telegram_failure_is_audited_without_text() -> None:
    w = await build(with_push=False)
    w.tg.bot.raise_transport = True
    res = await w.alerts.send(UID, "SECRETTEXT", kind="home_intruder")
    assert res.sent is False
    [e] = [x for x in w.tg.audit._entries if x.tool == "telegram_alert"]
    assert e.outcome == "failed" and "SECRETTEXT" not in repr(e)


async def test_a_broken_audit_does_not_undo_a_sent_alert() -> None:
    w = await build(with_push=False)

    async def boom(**k: object) -> None:
        raise RuntimeError("audit down")

    w.alerts._audit.append = boom  # type: ignore[method-assign]
    assert (await w.alerts.send(UID, "x", kind="home_intruder")).sent is True


async def test_every_delivery_is_audited_with_counts_not_content() -> None:
    w = await build()
    await w.service.notify(UID, intruder(), "SECRETWORD at the gate")
    [e] = [x for x in w.tg.audit._entries if x.tool == "notify_delivery"]
    assert e.agent == "alerts" and e.outcome == "ring" and "SECRETWORD" not in repr(e)


async def test_a_broken_delivery_audit_is_contained() -> None:
    w = await build()

    async def boom(**k: object) -> None:
        raise RuntimeError("down")

    w.service._audit.append = boom  # type: ignore[method-assign]
    assert (await w.service.notify(UID, intruder(), "x")).telegram is True


# ---- the sink --------------------------------------------------------------------------------


async def test_the_sink_holds_an_approval_at_midnight_and_sends_it_by_day() -> None:
    w = await build(MIDNIGHT)
    sink = PolicyAlerts(w.service)
    res = await sink.send(UID, "Something is waiting.", kind="approval_waiting")
    assert res.sent is False and "held" in res.reason and w.tg.bot.calls == []
    w.clock.now = NOON
    res = await sink.send(UID, "Something is waiting.", kind="approval_waiting")
    assert res.sent is True


async def test_the_sink_reports_reasons_in_plain_words_and_never_raises() -> None:
    w = await build()
    sink = PolicyAlerts(w.service)
    await w.store.update(UID, lambda s: s.model_copy(update={"kinds": {"brief_ready": "off"}}))
    assert "switched off" in (await sink.send(UID, "b", kind="brief_ready")).reason
    w.tg.bot.raise_transport = True
    w.push.status = 500
    assert (await sink.send(UID, "b", kind="home_offline")).reason == "no channel could deliver it"

    class Broken:
        async def notify(self, *a: object, **k: object) -> None:
            raise RuntimeError("x")

    assert (await PolicyAlerts(Broken()).send(UID, "b", kind="test")).sent is False  # type: ignore[arg-type]


async def test_the_test_button_reaches_both_channels() -> None:
    w = await build(MIDNIGHT)
    d = await PolicyAlerts(w.service).send(UID, "Test alert.", kind="test")
    assert d.sent is True and w.tg.bot.texts == ["Test alert."] and len(w.push.requests) == 1


def test_summary_text_counts_kinds() -> None:
    assert "1 alert " in summary([{"kind": "home_package", "at": "t"}])
    assert "2 package" in summary([{"kind": "home_package"}, {"kind": "home_package"}])
    assert "alert" in summary([{"kind": "weird"}])


def test_the_policy_never_calls_a_model() -> None:
    import jarvis.notify.policy as p
    import jarvis.notify.service as s

    for mod in (p, s):
        src = open(mod.__file__).read()  # noqa: SIM115
        assert "jarvis.llm" not in src and "anthropic" not in src.lower()
    assert decide(intruder(), NotifySettings(), NOON).action == "ring"
