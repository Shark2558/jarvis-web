# tests/test_telegram_alerts.py -- R1 D6: TelegramAlerts implements the alerts port. Fixed-template
# text (<= 300 characters, plain), at most 10 an hour and 50 a day, an unreadable counter fails
# closed, every alert audited (agent "alerts", tool telegram_alert, R1).
from __future__ import annotations

from typing import Any

from telegram_fakes import UID, World, build_world

from jarvis.alerts import AlertSink
from jarvis.core.guardrails import ActionRisk
from jarvis.telegram.alerts import (
    ALERT_TEXT,
    MAX_ALERT_CHARS,
    MAX_PER_DAY,
    MAX_PER_HOUR,
    TelegramAlerts,
)


async def _w() -> World:
    w = build_world()
    await w.pair()
    return w


async def test_it_is_an_alert_sink() -> None:
    w = await _w()
    assert isinstance(w.service.alerts, AlertSink)
    assert isinstance(w.service.alerts, TelegramAlerts)


async def test_an_alert_is_sent_to_the_bound_chat_and_audited() -> None:
    w = await _w()
    res = await w.service.alerts.send(UID, ALERT_TEXT["test"], kind="test")
    assert res.sent is True
    assert w.bot.texts == [ALERT_TEXT["test"]]
    [e] = w.audited("telegram_alert")
    assert e.agent == "alerts" and e.risk is ActionRisk.READ_ONLY and e.outcome == "sent"


async def test_not_paired_says_so() -> None:
    w = build_world()
    res = await w.service.alerts.send(UID, "x", kind="test")
    assert res.sent is False and "pair" in res.reason.lower() and w.bot.calls == []


async def test_a_kind_the_owner_switched_off_is_not_sent() -> None:
    w = await _w()
    res = await w.service.alerts.send(UID, "Brief ready.", kind="brief_ready")  # default off
    assert res.sent is False and "off" in res.reason.lower()
    await w.store.set_settings(UID, alerts={"brief_ready": True})
    assert (await w.service.alerts.send(UID, "Brief ready.", kind="brief_ready")).sent is True
    await w.store.set_settings(UID, alerts={"offline": False})
    assert (await w.service.alerts.send(UID, "Offline.", kind="offline_on")).sent is False
    assert (await w.service.alerts.send(UID, "Offline.", kind="offline_off")).sent is False
    await w.store.set_settings(UID, alerts={"approval_waiting": False})
    assert (await w.service.alerts.send(UID, "Wait.", kind="approval_waiting")).sent is False
    assert (await w.service.alerts.send(UID, "Test.", kind="test")).sent is True  # always


async def test_ten_an_hour_then_refused_then_allowed_next_hour() -> None:
    w = await _w()
    for _ in range(MAX_PER_HOUR):
        assert (await w.service.alerts.send(UID, "n", kind="test")).sent
    res = await w.service.alerts.send(UID, "n", kind="test")
    assert res.sent is False and "limit" in res.reason.lower()
    w.clock.advance(hours=1)
    assert (await w.service.alerts.send(UID, "n", kind="test")).sent


async def test_fifty_a_day() -> None:
    w = await _w()
    sent = 0
    for _hour in range(20):  # 03:00-22:59 UTC: one counter day
        for _ in range(MAX_PER_HOUR):
            if (await w.service.alerts.send(UID, "n", kind="test")).sent:
                sent += 1
        w.clock.advance(hours=1)
    assert MAX_PER_DAY == 50 and MAX_PER_HOUR == 10 and sent == 50


async def test_an_unreadable_counter_fails_closed() -> None:
    w = await _w()

    async def broken(*a: Any, **k: Any) -> Any:
        raise RuntimeError("firestore down")

    w.docs.transaction = broken  # type: ignore[method-assign]
    res = await w.service.alerts.send(UID, "n", kind="test")
    assert res.sent is False and w.bot.calls == []


async def test_text_is_plain_and_capped() -> None:
    w = await _w()
    await w.service.alerts.send(UID, "line one\n\n\n  line   two " + "z" * 600, kind="test")
    text = w.bot.texts[0]
    assert len(text) <= MAX_ALERT_CHARS == 300
    assert "\n" not in text and "  " not in text
    assert "parse_mode" not in w.bot.of("sendMessage")[0]


async def test_a_telegram_failure_is_a_plain_reason_without_vendor_text() -> None:
    w = await _w()
    w.bot.fail.add("sendMessage")
    res = await w.service.alerts.send(UID, "n", kind="test")
    assert res.sent is False and "VENDOR" not in res.reason and res.reason
    [e] = w.audited("telegram_alert")
    assert e.outcome == "failed"


async def test_templates_are_fixed_words() -> None:
    assert set(ALERT_TEXT) >= {
        "approval_waiting",
        "offline_on",
        "offline_off",
        "brief_ready",
        "test",
    }
    assert all(len(t) <= MAX_ALERT_CHARS and "\n" not in t for t in ALERT_TEXT.values())
