# tests/test_r13_c_outlook.py -- R13 Part C's weather (docs/plans/r13-wardrobe.md D14, STY-07; plan
# review L4): tomorrow's forecast fetched by C itself for his R11 place with R11's own Open-Meteo
# functions, at most twice a day (from 05:00 and from 18:00 his time), kept sealed in C's own
# `wardrobe_outlook/{uid}`; no R11 document written; Helpers off or no place -> "Weather unknown:
# I assumed indoors."; a rainy outdoor plan takes the rain-ok shoes and outer layer and says so.
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from r13_fakes import UID
from r13_fakes_c import SNEAKERS, N, World, forecast, ist, settings, world

from jarvis.helpers.house.weather import request_params
from jarvis.tools.gateway import GatewayOutcome
from jarvis.wardrobe.styling.outlook import slot_of

MON, TUE = date(2026, 11, 16), date(2026, 11, 17)
RAINY = forecast(MON, [(29, ()), (27, (15, 16, 17))])  # rain tomorrow from 15:00


async def _tick(w: World) -> dict[str, int]:
    return await w.part.clock_jobs[0].run([UID])  # type: ignore[no-any-return]


async def ok(w: World, name: str, **args: Any) -> dict[str, Any]:
    got = await w.call(name, **args)
    assert got.outcome is GatewayOutcome.EXECUTED, (got.outcome, got.error)
    return got.result  # type: ignore[no-any-return]


def test_the_fetch_slots_are_from_05_00_and_from_18_00_his_time() -> None:
    from r13_fakes import IST

    assert slot_of(ist(2026, 11, 16, 4, 59), IST) == "2026-11-15-pm"
    assert slot_of(ist(2026, 11, 16, 5, 0), IST) == "2026-11-16-am"
    assert slot_of(ist(2026, 11, 16, 17, 59), IST) == "2026-11-16-am"
    assert slot_of(ist(2026, 11, 16, 18, 0), IST) == "2026-11-16-pm"


async def test_at_most_twice_a_day_with_r11s_own_request() -> None:
    w = await world(at=ist(2026, 11, 16, 4, 0), fetch=RAINY)
    for _ in range(24 * 12):  # a whole day of 5-minute runs
        await _tick(w)
        w.clock.advance(minutes=5)
    assert len(w.fetcher.calls) == 3  # 04:00 (the evening before's), 05:00 and 18:00
    url, params = w.fetcher.calls[0]
    assert url == "https://api.open-meteo.com/v1/forecast"
    assert params == request_params((18.52, 73.86), "Asia/Kolkata")


async def test_a_failed_fetch_waits_an_hour() -> None:
    w = await world(at=ist(2026, 11, 16, 6, 0))
    w.fetcher.fail = True
    for _ in range(12):
        await _tick(w)
        w.clock.advance(minutes=5)
    assert len(w.fetcher.calls) == 1
    await _tick(w)
    assert len(w.fetcher.calls) == 2


async def test_tomorrow_is_kept_sealed_in_cs_own_document_and_r11s_is_untouched() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), fetch=RAINY)
    assert w.outside is not None
    before = await w.docs.get(f"jarvis_outside/{UID}")
    await _tick(w)
    assert await w.docs.get(f"jarvis_outside/{UID}") == before  # R11's document: not written
    raw = await w.docs.get(f"jarvis_wardrobe_outlook/{UID}")
    assert raw is not None and set(raw) == {"uid", "rev", "blob", "updated_at"}
    doc = await w.styling.outlook.sealed.read(UID)
    assert [(d.day, d.t_max, d.rain_hours) for d in doc.days] == [
        (MON, 29.0, ()),
        (TUE, 27.0, (15, 16, 17)),
    ]


def test_part_c_only_ever_reads_r11s_place() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "wardrobe" / "styling"
    for path in src.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "outside" in line.lower():
                assert ".change(" not in line and ".write(" not in line, (path.name, line)
    text = (src / "outlook.py").read_text(encoding="utf-8")
    assert "await out.read(uid)" in text


async def test_sty07_a_rainy_outdoor_plan_takes_rain_ok_shoes_and_an_outer_layer() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), fetch=RAINY)
    await _tick(w)
    got = await ok(w, "outfit_plan", action="save", day="tomorrow", code="casual",
                   start="16:00", end="18:00")  # fmt: skip
    pid = got["plan"]["id"]
    doc = await w.styling.plans.read(UID)
    outdoors = doc.plan(pid).model_copy(update={"outdoor": True})  # type: ignore[union-attr]
    await w.styling.change(UID, lambda d: d.put(outdoors))
    look = (await ok(w, "outfit_plans"))["plans"][0]
    by = {p["slot"]: p["ids"] for p in look["pieces"]}
    assert by["shoes"] == list(SNEAKERS) and by["outer"] == [N.rain_jacket]
    assert look["weather"] == "Weather for your home area: rain likely from 15:00."


async def test_sty07_no_place_or_helpers_off_assumes_indoors() -> None:
    for w in (
        await world(at=ist(2026, 11, 16, 18, 0), place=False, fetch=RAINY),
        await world(at=ist(2026, 11, 16, 18, 0), fetch=RAINY, s=settings(helpers_enabled=False)),
        await world(at=ist(2026, 11, 16, 18, 0), fetch=RAINY, s=settings(weather_enabled=False)),
    ):
        await _tick(w)
        assert w.fetcher.calls == []
        got = await ok(w, "outfit_suggest", day="tomorrow")
        assert got["looks"][0]["weather"] == "Weather unknown: I assumed indoors."
        assert "outer" not in {p["slot"] for p in got["looks"][0]["pieces"]}


async def test_a_dry_day_says_so_with_its_highest_temperature() -> None:
    w = await world(at=ist(2026, 11, 16, 18, 0), fetch=forecast(MON, [(29, ()), (34, ())]))
    await _tick(w)
    got = await ok(w, "outfit_suggest", day="tomorrow")
    assert got["looks"][0]["weather"] == "Weather for your home area: no rain expected, up to 34°C."
    assert json.dumps(got).count("rain likely") == 0
