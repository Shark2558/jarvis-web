# tests/test_r7_d_part.py -- R7 Part D's one join (docs/plans/r7-mobile.md "The I0 seams" 8, 15,
# 20, 23): `watch.part.build` keeps I0's contract (its own tools, door routes, the SOS hook),
# its door handlers answer on I0's fake door, the brief's sleep line rides the pinned slot and never
# the e-mailed copy or Telegram, the jobs and privacy rows work, and no tool or tainted round can
# ever send an SOS: the brain's one SOS tool is the read `sos_status`, which names no one.
from __future__ import annotations

import ast
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from r7_fakes import FakeDoor
from r7_fakes_d import ASHA, LAT_E6, LON_E6, UID, Clock, Notes, PinBot, needles, settings

from jarvis.api import r7_wiring
from jarvis.brief.models import BriefData, SleepLine
from jarvis.brief.render import render_text
from jarvis.helpers.brief import HelpersBrief
from jarvis.mobile.ports import TOOL_FAMILIES, MobileContext
from jarvis.sos.contacts_hook import ContactHook
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.alerts import ALERT_TEXT
from jarvis.tools.audit import AuditLog
from jarvis.watch import part as part_mod
from jarvis.watch.jobs import STALE_AFTER

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
IST = ZoneInfo("Asia/Kolkata")
HEALTH = {
    "v": 1,
    "days": [
        {
            "date": "2026-11-12",
            "steps": {"count": 8123, "writer": "com.noisefit"},
            "heart": {"min": 58, "avg": 74, "max": 131, "writer": "com.noisefit"},
            "sleep": [
                {
                    "start": "2026-11-11T23:50:00+05:30",
                    "end": "2026-11-12T06:30:00+05:30",
                    "writer": "com.noisefit",
                    "stages": None,
                }
            ],
        }
    ],
}


class Rig:
    def __init__(self, **over: Any) -> None:
        self.clock = Clock()
        self.notes = Notes()
        self.bot = PinBot()
        client = self.bot.client()
        self.docs = MemoryDocs()
        self.audit = AuditLog()

        class Tg:
            pass

        tg = Tg()
        tg.client = client  # type: ignore[attr-defined]
        state = {"telegram": tg, "helpers_now": self.clock}
        self.ctx = MobileContext(
            s=settings(**over),
            docs=self.docs,
            audit=self.audit,
            state=state.get,
            notifier=lambda: self.notes,
        )
        self.part = r7_wiring.check_part("body", part_mod.build(self.ctx))
        self.door = FakeDoor(self.part.services["door"], uid=UID)

    @property
    def sos(self) -> Any:
        return self.part.services["sos"]


def test_the_part_keeps_i0s_contract() -> None:
    p = Rig().part
    assert p.ready == "ready"
    assert {t.name for t in p.tools} == {
        "sleep_last_night",
        "sleep_week",
        "watch_today",
        "sleep_note",
        "sos_status",
    }
    assert set(p.services["door"]) == {"health", "sos"}
    assert isinstance(p.services["sos_hook"], ContactHook)
    assert [j.name for j in p.clock_jobs] == ["watch_stale"]
    assert [j.name for j in p.daily_jobs] == ["body_sweep"]
    assert [x.id for x in p.privacy] == ["watch_days", "sos"]


def test_no_tool_can_send_an_sos() -> None:
    p = Rig().part
    sos_tools = [t.name for t in p.tools if "sos" in t.name]
    assert sos_tools == ["sos_status"] and TOOL_FAMILIES["body"][-1] == "sos_status"
    assert all(t.risk.name != "IRREVERSIBLE" for t in p.tools)


def test_nothing_the_brain_runs_can_reach_the_send() -> None:
    """No module of the brain, the gateway, the tools or No-AI mode imports the SOS service: the
    only callers are Part D's routes, the door's handler and the part's join."""
    allowed = {"api/sos.py", "watch/part.py", "watch/door.py", "watch/jobs.py", "watch/privacy.py"}
    allowed |= {"sos/contacts_hook.py", "sos/tools.py", "sos/service.py"}
    allowed |= {"sos/limits.py", "sos/after.py"}  # the limits and the post-send tasks, split out
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mod = node.module if isinstance(node, ast.ImportFrom) else None
            if mod in ("jarvis.sos.service", "jarvis.sos.store") and rel not in allowed:
                offenders.append(rel)
    assert offenders == []
    tool_src = (SRC / "sos" / "tools.py").read_text(encoding="utf-8")
    assert ".send(" not in tool_src  # the one SOS tool only reads


def test_without_a_store_or_a_key_it_says_why() -> None:
    ctx = MobileContext(s=settings(), docs=None, audit=None, state=lambda _: None)
    assert part_mod.build(ctx).ready == part_mod.NO_STORE
    assert Rig(token_key=None).part.ready == part_mod.NO_KEY


async def test_the_health_door_keeps_a_day_and_logs_no_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    with caplog.at_level(logging.DEBUG):
        ok = await rig.door.call("health", json.dumps(HEALTH).encode())
        bad = await rig.door.call("health", b'{"v":1,"days":[{"date":"2026-11-12","steps":-1}]}')
    assert (ok.status, ok.body) == (200, {"ok": True, "days": 1})
    assert bad.status == 422 and bad.body["error"] == "invalid"
    for value in ("8123", "131", "-1"):
        assert value not in caplog.text + json.dumps(bad.body)
    watch = rig.part.services["watch"]
    night = await watch.night(UID, date(2026, 11, 12))
    assert night is not None and night.source == "watch"


async def test_the_health_door_says_when_watch_data_is_off() -> None:
    off = await Rig(watch_enabled=False).door.call("health", json.dumps(HEALTH).encode())
    nokey = await Rig(token_key=None).door.call("health", json.dumps(HEALTH).encode())
    assert (off.status, off.body["error"]) == (503, "watch_off")
    assert (nokey.status, nokey.body["error"]) == (503, "watch_off")


async def test_the_sos_door_sends_and_keeps_no_place(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig()
    c = await rig.sos.add_contact(UID, *ASHA[:2])
    word = (await rig.sos.join_link(UID, c.id))["link"].split("start=", 1)[1]
    await rig.part.services["sos_hook"].join(word, tg_user_id=ASHA[2], chat_id=ASHA[2])
    body = {
        "v": 1,
        "kind": "test",
        "at": int(rig.clock().timestamp()),
        "location": {"lat_e6": LAT_E6, "lon_e6": LON_E6, "accuracy_m": 20, "age_s": 8},
    }
    with caplog.at_level(logging.DEBUG):
        reply = await rig.door.call("sos", json.dumps(body).encode())
    assert reply.status == 200 and reply.body["outcome"] == "sent" and reply.body["sent"] is True
    assert reply.body["reached"] == 1  # how many contacts Telegram really took it for
    assert reply.body["call"]["emergency"] == "112" and reply.body["sms"]["numbers"] == [ASHA[1]]
    written = json.dumps(rig.docs._data, default=str) + caplog.text
    written += "".join(e.detail for e in rig.audit._entries)
    assert not [n for n in needles() if n in written]
    assert rig.bot.to(ASHA[2], "sendLocation")  # the pin went, in Telegram's POST body only


@pytest.mark.parametrize(
    "raw",
    [b"", b"[]", b'{"v":1,"kind":"panic","at":1,"location":null}'],
)
async def test_a_bad_sos_body_is_refused_and_nothing_is_sent(raw: bytes) -> None:
    rig = Rig()
    reply = await rig.door.call("sos", raw)
    assert reply.status == 422 and rig.bot.calls == [] and rig.notes.sent == []
    assert "112" in reply.body["detail"]  # the phone still opens its SMS screen and 112


async def test_sos_status_names_no_one_and_says_how_to_send() -> None:
    from jarvis.tools.context import tool_context

    rig = Rig()
    await rig.sos.add_contact(UID, *ASHA[:2])
    (tool,) = [t for t in rig.part.tools if t.name == "sos_status"]
    with tool_context(f"{UID}:s1"):
        said = (await tool.run({}))["message"]
    assert said.startswith("Emergency SOS has 1 emergency contact; 0 joined on Telegram.")
    assert "I can never send an SOS myself" in said and "112" in said
    assert ASHA[0] not in said and ASHA[1] not in said


async def test_the_sleep_line_rides_the_pinned_slot_and_never_the_emailed_copy() -> None:
    rig = Rig()
    await rig.door.call("health", json.dumps(HEALTH).encode())
    brief = rig.part.services["brief"]
    day = date(2026, 11, 12)
    assert await brief.lines(UID, IST, day) == ()
    line = await brief.sleep(UID, IST, day)
    assert line == SleepLine(minutes=400, start="23:50", end="06:30", source="watch")
    section = await HelpersBrief(lambda: [brief]).section(UID, IST, day)
    assert section is None  # nothing in the Helpers section, which is e-mailed and on Telegram
    text = render_text(BriefData(date="2026-11-12", tz="Asia/Kolkata", sleep=line))
    assert "Sleep" not in text and "6 h 40" not in text and "23:50" not in text
    assert "sleep" not in ALERT_TEXT.get("brief_ready", "").lower()


async def test_no_night_and_off_give_no_sleep_line() -> None:
    assert await Rig().part.services["brief"].sleep(UID, IST, date(2026, 11, 12)) is None
    off = Rig(watch_enabled=False).part.services["brief"]
    assert await off.sleep(UID, IST, date(2026, 11, 12)) is None


async def test_the_stale_watch_is_told_once_and_never_for_a_phone_that_never_synced() -> None:
    rig = Rig()
    (job,) = rig.part.clock_jobs
    assert await job.run([UID]) == {
        "told": 0,
        "no_notifier": 0,
        "failed": 0,
    }  # never synced: nothing
    await rig.door.call("health", json.dumps(HEALTH).encode())
    rig.clock.move(hours=STALE_AFTER.total_seconds() / 3600 + 1)
    assert (await job.run([UID]))["told"] == 1
    assert (await job.run([UID]))["told"] == 0  # once per silence
    assert rig.notes.kinds() == ["watch_stale"] and "8123" not in rig.notes.sent[0][2]
    await rig.door.call("health", json.dumps(HEALTH).encode())  # it synced again ...
    rig.clock.move(hours=27)
    assert (await job.run([UID]))["told"] == 1  # ... and stopped again


async def test_the_sweep_and_the_privacy_rows() -> None:
    rig = Rig()
    await rig.door.call("health", json.dumps(HEALTH).encode())
    await rig.sos.add_contact(UID, *ASHA[:2])
    await rig.sos.send(UID, "real", None, via="web")
    (sweep,) = rig.part.daily_jobs
    assert await sweep.run([UID]) == {"watch_days": 0, "sos": 0, "failed": 0}
    rig.clock.at = datetime(2027, 12, 31, tzinfo=UTC)  # far past 400 days
    got = await sweep.run([UID])
    assert got["watch_days"] == 1 and got["sos"] == 2  # the entry and its "last" copy
    watch_row, sos_row = rig.part.privacy
    view = await sos_row.describe(UID)
    assert view.count == 1 and view.delete == "confirm" and view.encrypted_by_jarvis
    exported = await sos_row.export(UID)
    assert exported is not None and exported["contacts"][0]["label"] == ASHA[0]
    assert await sos_row.delete(UID) == 1
    assert (await watch_row.describe(UID)).delete == "none"  # nothing left to delete
    assert (await rig.sos.view(UID))["contacts"] == []


async def test_the_wiring_hands_the_hook_to_telegram_and_the_door_its_handlers() -> None:
    from fastapi import FastAPI

    rig = Rig()
    app = FastAPI()
    app.state.r7_parts = {"body": rig.part}
    assert set(r7_wiring.door_handlers(app)) == {"health", "sos"}
    assert r7_wiring.mobile_phrases(app) == (part_mod.watch_phrases,)
    assert len(r7_wiring.mobile_brief(app)) == 1


async def test_the_hello_reply_can_read_the_sms_list() -> None:
    rig = Rig()
    await rig.sos.set_label(UID, "Kiran Example")
    await rig.sos.add_contact(UID, *ASHA[:2])
    await rig.sos.add_contact(UID, "No Number Example", None)
    got = await rig.part.services["sos_contacts"](UID)
    assert got == {"label": "Kiran Example", "contacts": [{"label": ASHA[0], "phone": ASHA[1]}]}


async def test_a_door_reply_never_counts_an_undelivered_message_as_reached() -> None:
    rig = Rig()
    c = await rig.sos.add_contact(UID, *ASHA[:2])
    word = (await rig.sos.join_link(UID, c.id))["link"].split("start=", 1)[1]
    await rig.part.services["sos_hook"].join(word, tg_user_id=ASHA[2], chat_id=ASHA[2])
    rig.bot.refuse_text.add(ASHA[2])
    body = {"v": 1, "kind": "real", "at": int(rig.clock().timestamp()), "location": None}
    reply = await rig.door.call("sos", json.dumps(body).encode())
    assert reply.body["reached"] == 0 and reply.body["sent"] is False
    assert reply.body["results"][0]["status"] == "failed"
