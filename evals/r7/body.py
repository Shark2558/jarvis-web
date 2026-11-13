# evals/r7/body.py
"""R7 eval, Part D (`body`, BUILT): watch, sleep and SOS on fakes (docs/plans/r7-mobile.md D17-D20,
"Tests and evals per part"). Every case drives Part D's real code (`watch.part.build`, its door
handlers, its SOS service and the Telegram front door with Part D's hook) on in-memory fakes:

- intake: the contract's body is kept; out-of-range numbers and a day outside the last 35 refused;
- sleep: across midnight, beside a nap, two sessions, a time-zone change, no stages; one writer a
  night (the watch before the phone) and the brief's line names it; no sleep line in the e-mailed
  copy or the Helpers section;
- sealed: no watch value in a stored document or a log line;
- SOS: a join word joins once and never touches the pairing counter; a send reaches each contact
  once with the fixed template (this file's OWN copy of it) and a pin; a refused or failed send
  is never "sent"; no coordinate in any document, log record, audit line, alert or address; the
  fourth real SOS in an hour is refused and still offers SMS and 112; a real SOS goes out after
  three tests; no tool sends.

Negative controls (each must make its case fail, or the suite proves nothing):
  model_text      the message is built from a model's words (`jarvis.sos.message.message_for`)
  location_logged the send's log line carries the coordinates (`jarvis.sos.service._log_extra`)
  hourly_cap_off  `jarvis.sos.service.HOURLY_CAP = False`
  tests_in_real   `jarvis.sos.service.OWN_TEST_BUDGET = False` (tests count in the real budget)
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "src", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import r7_fakes_d as F  # noqa: E402
from r7_fakes import FakeDoor  # noqa: E402
from telegram_fakes import STRANGER_TG, build_world, message  # noqa: E402

import jarvis.sos.message as sos_message  # noqa: E402
import jarvis.sos.service as sos_service  # noqa: E402
from jarvis.brief.models import BriefData  # noqa: E402
from jarvis.brief.render import render_text  # noqa: E402
from jarvis.mobile.ports import MobileContext  # noqa: E402
from jarvis.sos.models import Location  # noqa: E402
from jarvis.storage.docs import MemoryDocs  # noqa: E402
from jarvis.tools.audit import AuditLog  # noqa: E402
from jarvis.watch import part as body_part  # noqa: E402

PART = "body"
BUILT = True
UID = F.UID
HERE = Location(lat_e6=F.LAT_E6, lon_e6=F.LON_E6, accuracy_m=20, age_s=0)
# This eval's OWN copy of D19's template (never imported from the code it checks)
LINK = "https://maps.google.com/?q=-31.415926,-17.320508"
EXPECTED_REAL = (
    f"SOS from Kiran Example: I need help. My location at 14:05: {LINK} (within about 20 m). "
    "Sent by my JARVIS assistant."
)
IST = "+05:30"


def _night(start: str, end: str, writer: str = "com.noisefit", stages: Any = None) -> dict:
    return {"start": start, "end": end, "writer": writer, "stages": stages}


def _health(days: list[dict[str, Any]]) -> bytes:
    return json.dumps({"v": 1, "days": days}).encode()


DAY = {
    "date": "2026-11-12",
    "steps": {"count": 8123, "writer": "com.noisefit"},
    "heart": {"min": 58, "avg": 74, "max": 131, "writer": "com.noisefit"},
    "sleep": [_night(f"2026-11-11T23:50:00{IST}", f"2026-11-12T06:30:00{IST}")],
}


class Capture(logging.Handler):
    """Every log record whole (message and every extra field), as text."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.rows: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.rows.append(json.dumps(record.__dict__, default=str))


@contextmanager
def captured() -> Iterator[Capture]:
    cap = Capture()
    root = logging.getLogger()
    root.addHandler(cap)
    try:
        yield cap
    finally:
        root.removeHandler(cap)


class Rig:
    def __init__(self) -> None:
        self.clock = F.Clock()
        self.notes = F.Notes()
        self.bot = F.PinBot()
        self.docs = MemoryDocs()
        self.audit = AuditLog()
        holder = type("Tg", (), {})()
        holder.client = self.bot.client()
        state = {"telegram": holder, "helpers_now": self.clock}
        ctx = MobileContext(
            s=F.settings(),
            docs=self.docs,
            audit=self.audit,
            state=state.get,
            notifier=lambda: self.notes,
        )
        self.part = body_part.build(ctx)
        self.door = FakeDoor(self.part.services["door"], uid=UID)
        self.watch = self.part.services["watch"]
        self.sos = self.part.services["sos"]
        self.hook = self.part.services["sos_hook"]

    async def contacts(self) -> None:
        await self.sos.set_label(UID, "Kiran Example")
        for label, phone, tg in (F.ASHA, F.RAVI, F.MEERA):
            c = await self.sos.add_contact(UID, label, phone)
            word = (await self.sos.join_link(UID, c.id))["link"].split("start=", 1)[1]
            await self.hook.join(word, tg_user_id=tg, chat_id=tg)
        self.bot.calls.clear()


Check = Callable[[], Awaitable[list[str]]]


async def intake_ranges() -> list[str]:
    rig, out = Rig(), []
    if (await rig.door.call("health", _health([DAY]))).status != 200:
        out.append("the contract's own day was refused")
    bad_days = [
        {**DAY, "steps": {"count": -1, "writer": "com.noisefit"}},
        {**DAY, "heart": {"min": 10, "avg": 70, "max": 120, "writer": "com.noisefit"}},
        {**DAY, "date": "2026-10-01"},
    ]
    for bad in bad_days:
        if (await rig.door.call("health", _health([bad]))).status != 422:
            out.append(f"accepted: {sorted(bad)}")
    return out


async def sleep_sums() -> list[str]:
    rig, out = Rig(), []
    nights = {
        "across midnight": (
            [_night(f"2026-11-11T23:50:00{IST}", f"2026-11-12T06:30:00{IST}")],
            400,
        ),
        "beside a nap": (
            [
                _night(f"2026-11-11T23:00:00{IST}", f"2026-11-12T06:00:00{IST}"),
                _night(f"2026-11-12T12:00:00{IST}", f"2026-11-12T13:00:00{IST}"),
            ],
            420,
        ),
        "two sessions": (
            [
                _night(f"2026-11-11T23:00:00{IST}", f"2026-11-12T02:00:00{IST}"),
                _night(f"2026-11-12T03:00:00{IST}", f"2026-11-12T07:15:00{IST}"),
            ],
            255,
        ),
        "a time-zone change": (
            [_night(f"2026-11-11T23:50:00{IST}", "2026-11-12T03:30:00+04:00")],
            310,
        ),
    }
    for name, (sessions, minutes) in nights.items():
        await rig.door.call("health", _health([{"date": "2026-11-12", "sleep": sessions}]))
        n = await rig.watch.night(UID, date(2026, 11, 12))
        if n is None or n.minutes != minutes or n.stages is not None:
            out.append(f"{name}: {None if n is None else n.minutes} minutes")
    return out


async def one_writer() -> list[str]:
    rig, out = Rig(), []
    both = [
        _night(f"2026-11-11T22:30:00{IST}", f"2026-11-12T07:00:00{IST}", "android"),
        _night(f"2026-11-11T23:50:00{IST}", f"2026-11-12T06:30:00{IST}", "com.noisefit"),
    ]
    await rig.door.call("health", _health([{"date": "2026-11-12", "sleep": both}]))
    line = await rig.part.services["brief"].sleep(UID, None, date(2026, 11, 12))
    if line is None or line.source != "watch" or line.minutes != 400:
        out.append(f"both writers: {line}")
    await rig.door.call("health", _health([{"date": "2026-11-12", "sleep": both[:1]}]))
    line = await rig.part.services["brief"].sleep(UID, None, date(2026, 11, 12))
    if line is None or line.source != "phone":
        out.append(f"the phone alone: {line}")
    text = render_text(BriefData(date="2026-11-12", tz="Asia/Kolkata", sleep=line))
    if "Sleep" in text or (await rig.part.services["brief"].lines(UID, None, date(2026, 11, 12))):
        out.append("a sleep line reached the e-mailed copy or the Helpers section")
    return out


async def sealed_no_value() -> list[str]:
    rig = Rig()
    with captured() as cap:
        await rig.door.call("health", _health([DAY]))
    # plain fields and log lines are scanned for the short values; the random ciphertext only for
    # a long one (a 3-character needle is in a random blob by chance, about 0.3% of the runs)
    plain = {p: {k: v for k, v in d.items() if k != "blob"} for p, d in rig.docs._data.items()}
    blobs = " ".join(str(d.get("blob", "")) for d in rig.docs._data.values())
    seen = json.dumps(plain, default=str) + "\n".join(cap.rows)
    found = [f"{v} in clear" for v in ("8123", "131", "com.noisefit") if v in seen]
    return found + (["com.noisefit in a blob"] if "com.noisefit" in blobs else [])


async def join_once() -> list[str]:
    rig, out = Rig(), []
    c = await rig.sos.add_contact(UID, *F.ASHA[:2])
    word = (await rig.sos.join_link(UID, c.id))["link"].split("start=", 1)[1]
    w = build_world()
    w.service.sos = rig.hook
    await w.send(message(1, f"/start {word}", user=STRANGER_TG, chat=STRANGER_TG))
    await w.send(message(2, f"/start {word}", user=STRANGER_TG + 1, chat=STRANGER_TG + 1))
    if len(w.bot.texts) != 1:
        out.append(f"the word joined {len(w.bot.texts)} times")
    if await w.docs.get("jarvis_telegram_pairing_tries/all") is not None:
        out.append("a wrong SOS word moved the pairing counter")
    if w.provider.calls:
        out.append("a contact reached the brain")
    return out


async def send_template_pin() -> list[str]:
    rig, out = Rig(), []
    await rig.contacts()
    res = await rig.sos.send(UID, "real", HERE, via="web")
    for _, _, tg in (F.ASHA, F.RAVI, F.MEERA):
        texts = [p["text"] for p in rig.bot.to(tg)]
        if texts != [EXPECTED_REAL]:
            out.append(
                f"contact {tg % 10}: {len(texts)} messages, template kept: {EXPECTED_REAL in texts}"
            )
        if len(rig.bot.to(tg, "sendLocation")) != 1:
            out.append(f"contact {tg % 10}: no single pin")
    if res.outcome != "sent":
        out.append(f"outcome {res.outcome}")
    return out


async def honest_failures() -> list[str]:
    rig, out = Rig(), []
    await rig.contacts()
    rig.bot.refuse_text.add(F.RAVI[2])
    res = await rig.sos.send(UID, "real", HERE, via="web")
    status = {r.label: r.status for r in res.results}
    if status.get(F.RAVI[0]) != "failed" or res.outcome != "partial" or res.reached != 2:
        out.append(f"a failed contact was reported as {status.get(F.RAVI[0])}")
    rig.bot.fail.add("sendMessage")
    res = await rig.sos.send(UID, "test", HERE, via="web")
    if res.view()["sent"] or res.outcome != "failed":
        out.append("nothing delivered, yet it said sent")
    return out


async def no_coordinates() -> list[str]:
    rig = Rig()
    await rig.contacts()
    with captured() as cap:
        await rig.sos.send(UID, "real", HERE, via="web")
        body = json.dumps(
            {"v": 1, "kind": "test", "at": int(rig.clock().timestamp()),
             "location": {"lat_e6": F.LAT_E6, "lon_e6": F.LON_E6, "accuracy_m": 20, "age_s": 0}}
        ).encode()  # fmt: skip
        await rig.door.call("sos", body)
    seen = F.everything_written(
        rig.docs, rig.audit, [*cap.rows, *(m for _, _, m in rig.notes.sent)]
    )
    seen += "\n".join(rig.bot.paths)  # the addresses Telegram was called at
    return [f"{n} written down" for n in F.needles() if n in seen]


async def hourly_cap() -> list[str]:
    rig, out = Rig(), []
    await rig.contacts()
    for _ in range(3):
        await rig.sos.send(UID, "real", HERE, via="web")
        rig.clock.move(minutes=5)
    rig.bot.calls.clear()
    res = await rig.sos.send(UID, "real", HERE, via="web")
    v = res.view()
    if res.outcome != "refused" or rig.bot.calls:
        out.append(f"the fourth real SOS in an hour: {res.outcome}")
    if not v["sms"]["numbers"] or v["call"]["emergency"] != "112":
        out.append("a refusal without the SMS screen or 112")
    return out


async def real_after_tests() -> list[str]:
    rig = Rig()
    await rig.contacts()
    for _ in range(3):
        await rig.sos.send(UID, "test", HERE, via="web")
    res = await rig.sos.send(UID, "real", HERE, via="web")
    return [] if res.outcome == "sent" else [f"a real SOS after three tests: {res.outcome}"]


async def no_tool_sends() -> list[str]:
    tools = Rig().part.tools
    sends = [t.name for t in tools if "sos" in t.name and t.name != "sos_status"]
    irreversible = [t.name for t in tools if t.risk.name == "IRREVERSIBLE"]
    return [f"tool {n}" for n in sends + irreversible]


CASES: dict[str, Check] = {
    "intake_ranges": intake_ranges,
    "sleep_sums": sleep_sums,
    "one_writer_and_brief": one_writer,
    "sealed_no_value": sealed_no_value,
    "join_once": join_once,
    "send_template_pin": send_template_pin,
    "honest_failures": honest_failures,
    "no_coordinates": no_coordinates,
    "hourly_cap": hourly_cap,
    "real_after_tests": real_after_tests,
    "no_tool_sends": no_tool_sends,
}


async def _run() -> list[dict[str, Any]]:
    results = []
    for name, check in CASES.items():
        try:
            failures = await check()
        except Exception as exc:  # noqa: BLE001 - a case that breaks is a failed case
            failures = [f"raised {type(exc).__name__}"]
        results.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return results


async def cases() -> list[dict[str, Any]]:
    return await _run()


# ---- the negative controls --------------------------------------------------------------------
@contextmanager
def _swap(module: Any, name: str, value: Any) -> Iterator[None]:
    old = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, old)


def _model_text(kind: str, label: str, loc: Any, fixed_at: str) -> str:
    return f"SOS from {label}: stay calm, the assistant thinks you are fine. {fixed_at}"


def _logged_place(kind: str, outcome: str, reached: int, joined: int, located: bool) -> dict:
    return {"kind": kind, "lat": HERE.lat_e6, "lon": HERE.lon_e6, "reached": reached}


CONTROLS: dict[str, tuple[Any, str, Any, str]] = {
    "model_text": (sos_message, "message_for", _model_text, f"{PART}:send_template_pin"),
    "location_logged": (sos_service, "_log_extra", _logged_place, f"{PART}:no_coordinates"),
    "hourly_cap_off": (sos_service, "HOURLY_CAP", False, f"{PART}:hourly_cap"),
    "tests_in_real": (sos_service, "OWN_TEST_BUDGET", False, f"{PART}:real_after_tests"),
}


async def control() -> dict[str, Any]:
    failed: list[str] = []
    every = True
    for name, (module, attr, value, target) in CONTROLS.items():
        with _swap(module, attr, value):
            got = [r["id"] for r in await _run() if not r["passed"]]
        failed += [f"{name} -> {case}" for case in got]
        every = every and target in got
    return {
        "name": "body: message from model text; location logged; hourly cap off; tests in the "
        "real budget",
        "suite_failed": every,
        "failed_cases": failed,
    }
