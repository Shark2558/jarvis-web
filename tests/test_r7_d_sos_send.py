# tests/test_r7_d_sos_send.py -- R7 Part D (docs/plans/r7-mobile.md D19): an SOS reaches each joined
# contact ONCE, with the fixed template and a map pin; every failure is reported per contact and
# never as "sent"; coordinates appear in no document, log, audit line or alert (only the POST
# bodies to Telegram); a real SOS is limited to 3 an hour and 10 a day, and tests and "I'm safe"
# have their own budget, so a real SOS still goes out after three tests; a refusal still offers the
# SMS screen and 112; the owner is told on every channel with `sos_sent` (no names).
from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from r7_fakes_d import (
    ASHA,
    LAT_E6,
    LON_E6,
    MEERA,
    RAVI,
    UID,
    BrokenDocs,
    Clock,
    Notes,
    PinBot,
    everything_written,
    needles,
    settings,
)

from jarvis.keyring import Keyring
from jarvis.sos.message import maps_link, message_for
from jarvis.sos.models import Location
from jarvis.sos.service import SosService
from jarvis.sos.store import SosStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

HERE = Location(lat_e6=LAT_E6, lon_e6=LON_E6, accuracy_m=20, age_s=0)


class World:
    def __init__(self, *, docs: Any = None, notes: Notes | None = None, telegram: bool = True):
        self.s = settings()
        self.clock = Clock()
        self.docs = docs if docs is not None else MemoryDocs()
        self.audit = AuditLog()
        self.bot = PinBot()
        self.client = self.bot.client()
        self.notes = notes or Notes()
        ring = Keyring.from_settings(self.s)
        self.store = SosStore(self.docs, ring, prefix=self.s.firestore_prefix, now=self.clock)
        self.svc = SosService(
            self.store,
            self.s,
            telegram=(lambda: self.client) if telegram else (lambda: None),
            notifier=lambda: self.notes,
            audit=self.audit,
            now=self.clock,
        )

    async def contact(self, person: tuple[str, str, int], *, join: bool = True) -> str:
        label, phone, tg = person
        c = await self.svc.add_contact(UID, label, phone)
        if join:
            link = await self.svc.join_link(UID, c.id)
            word = link["link"].split("start=", 1)[1]
            reply = await self.svc.join(word, tg_user_id=tg, chat_id=tg)
            assert reply is not None
        return c.id

    async def three(self) -> None:
        await self.svc.set_label(UID, "Kiran Example")
        for p in (ASHA, RAVI, MEERA):
            await self.contact(p)
        self.bot.calls.clear()


async def test_a_real_sos_reaches_each_contact_once_with_the_template_and_a_pin() -> None:
    w = World()
    await w.three()
    res = await w.svc.send(UID, "real", HERE, via="web")
    assert (res.outcome, res.reached, res.joined) == ("sent", 3, 3)
    text = (
        "SOS from Kiran Example: I need help. My location at 14:05: "
        f"{maps_link(HERE)} (within about 20 m). Sent by my JARVIS assistant."
    )
    assert res.text == text
    for _, _, tg in (ASHA, RAVI, MEERA):
        assert [p["text"] for p in w.bot.to(tg)] == [text]  # once each, the fixed words
        (pin,) = w.bot.to(tg, "sendLocation")
        assert (pin["latitude"], pin["longitude"]) == (-31.415926, -17.320508)
    assert [r.status for r in res.results] == ["sent"] * 3


async def test_two_entries_for_the_same_chat_get_one_message() -> None:
    w = World()
    await w.contact(ASHA)
    await w.contact((ASHA[0] + " again", "+10000000009", ASHA[2]))
    w.bot.calls.clear()
    res = await w.svc.send(UID, "real", HERE, via="web")
    assert len(w.bot.to(ASHA[2])) == 1 and res.reached == 1


async def test_no_location_says_so_and_sends_no_pin() -> None:
    w = World()
    await w.three()
    res = await w.svc.send(UID, "real", None, via="phone")
    assert res.text == (
        "SOS from Kiran Example: I need help. My location is not available. Sent by my JARVIS "
        "assistant."
    )
    assert w.bot.of("sendLocation") == [] and res.outcome == "sent"


async def test_an_old_or_rough_fix_says_how_old_and_how_rough() -> None:
    old = Location(lat_e6=LAT_E6, lon_e6=LON_E6, accuracy_m=1800, age_s=180)
    text = message_for("real", "Kiran Example", old, "14:02")
    assert "My location at 14:02:" in text and "(within about 2 km)" in text


async def test_every_failure_is_reported_per_contact_and_never_as_sent() -> None:
    w = World()
    await w.three()
    w.bot.refuse_text.add(RAVI[2])
    w.bot.refuse_pin.add(MEERA[2])
    res = await w.svc.send(UID, "real", HERE, via="web")
    by = {r.label: r.status for r in res.results}
    assert by == {"Asha Example": "sent", "Ravi Example": "failed", "Meera Example": "sent_no_pin"}
    assert (res.outcome, res.reached, res.joined) == ("partial", 2, 3)
    assert "Ravi Example" in res.words and "not reached" in res.words.lower()
    assert "SMS" in res.words and res.view()["sent"] is True


async def test_when_telegram_takes_nothing_the_answer_is_not_sent() -> None:
    w = World()
    await w.three()
    w.bot.fail.add("sendMessage")
    res = await w.svc.send(UID, "real", HERE, via="web")
    assert (res.outcome, res.reached) == ("failed", 0)
    assert res.view()["sent"] is False and "NOT sent" in res.words
    assert w.notes.sent and "reached no one" in w.notes.sent[-1][2]


async def test_with_telegram_off_nothing_is_claimed_and_the_sms_screen_is_offered() -> None:
    w = World(telegram=False)
    await w.svc.add_contact(UID, *ASHA[:2])
    res = await w.svc.send(UID, "real", HERE, via="web")
    assert res.outcome == "none_joined" and res.reached == 0
    v = res.view()
    assert v["sms"]["numbers"] == [ASHA[1]] and v["call"] == {"first": ASHA[1], "emergency": "112"}


async def test_no_contact_at_all_still_offers_112() -> None:
    w = World()
    res = await w.svc.send(UID, "real", HERE, via="web")
    assert res.outcome == "none_joined" and res.view()["call"]["emergency"] == "112"


async def test_an_unreadable_store_says_so_and_still_offers_112() -> None:
    w = World(docs=BrokenDocs())
    res = await w.svc.send(UID, "real", HERE, via="web")
    assert res.outcome == "unavailable" and res.view()["sent"] is False
    assert "112" in res.words


async def test_the_fourth_real_sos_in_an_hour_is_refused_and_still_offers_sms_and_112() -> None:
    w = World()
    await w.three()
    for _ in range(3):
        assert (await w.svc.send(UID, "real", HERE, via="web")).outcome == "sent"
        w.clock.move(minutes=5)
    w.bot.calls.clear()
    res = await w.svc.send(UID, "real", HERE, via="web")
    assert res.outcome == "refused" and res.reason == "hour" and w.bot.calls == []
    v = res.view()
    assert v["sms"]["numbers"] == [ASHA[1], RAVI[1], MEERA[1]] and v["sms"]["text"] == res.text
    assert v["call"]["emergency"] == "112" and "3 an hour" in res.words
    w.clock.move(minutes=50)  # the hour has passed
    assert (await w.svc.send(UID, "real", HERE, via="web")).outcome == "sent"


async def test_ten_real_sends_a_day() -> None:
    w = World()
    await w.contact(ASHA)
    for _ in range(10):
        assert (await w.svc.send(UID, "real", HERE, via="web")).outcome == "sent"
        w.clock.move(minutes=25)
    res = await w.svc.send(UID, "real", HERE, via="web")
    assert res.outcome == "refused" and res.reason == "day"


async def test_a_real_sos_goes_out_after_three_tests_and_i_am_safe() -> None:
    w = World()
    await w.three()
    for _ in range(3):
        assert (await w.svc.send(UID, "test", HERE, via="web")).outcome == "sent"
    assert (await w.svc.send(UID, "test", HERE, via="web")).outcome == "refused"  # its own cap
    assert (await w.svc.send(UID, "real", HERE, via="web")).outcome == "sent"
    safe = await w.svc.send(UID, "safe", None, via="web")
    assert safe.outcome == "refused"  # "I'm safe" shares the tests' budget, never the real one
    w.clock.move(hours=1, minutes=1)
    safe = await w.svc.send(UID, "safe", None, via="web")
    assert safe.outcome == "sent"
    assert safe.text == "Kiran Example is safe now. Thank you. Sent by my JARVIS assistant."


async def test_a_test_says_it_is_a_test() -> None:
    w = World()
    await w.three()
    res = await w.svc.send(UID, "test", HERE, via="web")
    assert res.text.startswith("TEST from Kiran Example: this is only a test of my JARVIS SOS")


async def test_coordinates_appear_in_no_document_log_audit_line_or_alert(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = World()
    await w.three()
    with caplog.at_level(logging.DEBUG):
        await w.svc.send(UID, "real", HERE, via="web")
        await w.svc.send(UID, "test", HERE, via="phone")
        w.bot.refuse_pin.add(ASHA[2])
        await w.svc.send(UID, "real", HERE, via="web")
    alerts = [m for _, _, m in w.notes.sent]
    seen = everything_written(w.docs, w.audit, [caplog.text, *alerts])
    for needle in needles():
        assert needle not in seen, needle
    assert "location yes" in "\n".join(e.detail for e in w.audit._entries)  # yes / no only
    for p in w.bot.paths:
        assert "31.415" not in p and "17.320" not in p  # never in an address


async def test_the_owner_is_told_with_sos_sent_and_no_name() -> None:
    w = World()
    await w.three()
    await w.svc.send(UID, "real", HERE, via="web")
    (uid, kind, words) = w.notes.sent[-1]
    assert (uid, kind) == (UID, "sos_sent")
    assert words == "SOS sent at 14:05 to 3 of 3 emergency contacts on Telegram."
    for name in ("Asha", "Ravi", "Meera", "Kiran"):
        assert name not in words


async def test_a_notifier_that_fails_never_fails_the_send() -> None:
    w = World(notes=Notes(fail=True))
    await w.three()
    res = await w.svc.send(UID, "real", HERE, via="web")
    assert res.outcome == "sent" and res.told is False


async def test_every_send_is_audited_and_logged_without_a_place() -> None:
    w = World()
    await w.three()
    await w.svc.send(UID, "real", HERE, via="web")
    entry = w.audit._entries[-1]
    assert (entry.agent, entry.tool, entry.outcome) == ("sos", "sos_real", "sent")
    logs = [d for p, d in w.docs._data.items() if "sos_log/" in p and d.get("kind") == "real"]
    assert len(logs) == 1 and logs[0]["location"] is True and logs[0]["reached"] == 3
    assert set(logs[0]) == {"uid", "at", "kind", "outcome", "reached", "joined", "location", "via"}
    last = await w.svc.view(UID)
    assert last["last"]["kind"] == "real" and last["last"]["reached"] == 3


async def test_the_eval_switches_are_constructor_arguments_and_on() -> None:
    w = World()
    assert (w.svc.hourly_cap, w.svc.own_test_budget) == (True, True)  # only the eval builds one off


async def test_the_reply_carries_no_word_of_a_model() -> None:
    w = World()
    await w.three()
    res = await w.svc.send(UID, "real", HERE, via="web")
    body = json.dumps(res.view())
    assert res.text in body and "Kiran Example" in res.text  # his own label, JARVIS's words
