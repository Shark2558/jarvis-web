# tests/test_r11_b_part.py -- R11 Part B's plug-in (docs/plans/r11-free-helpers.md D2, D16-D18):
# `house.part.build(ctx)` passes I0's contract (its own tool families, job names and privacy ids);
# the tools work through the tool context (R1 reads, R2 writes; SACHET's words fenced as outside
# text); the No-AI phrases are anchored and end in Part B's own tools (and leave other phrases
# alone); the two privacy rows list, export and delete; the brief's lines and the pending items.
from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from r11_fakes import NOON_IST, UID
from r11_fakes_b import PLACE, house_ctx, sachet_fetcher

from jarvis.api.r11_wiring import check_part
from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.house import part as house_part
from jarvis.helpers.house import phrases
from jarvis.helpers.house.models import Place
from jarvis.helpers.house.service import HouseService
from jarvis.helpers.ports import HelperPart
from jarvis.offline.rules import route_no_ai
from jarvis.tools.context import tool_context
from jarvis.tools.external import FENCE_PREFIX


def _built(**over: Any) -> tuple[HelperPart, HouseService, Any, Any, Any]:
    fetcher = over.pop("fetcher", None) or sachet_fetcher()
    hc, notifier, docs, clock = house_ctx(**over)
    built = house_part.build(hc, fetcher=fetcher)
    return built, built.services["house"], hc, notifier, docs


def _tool(p: HelperPart, name: str) -> Any:
    return next(t for t in p.tools if t.name == name)


async def _call(p: HelperPart, name: str, **args: Any) -> Any:
    t = _tool(p, name)
    t.validate(args)
    with tool_context(f"{UID}:s1"):
        return await t.run(args)


# ---- the contract -------------------------------------------------------------------------------
def test_build_passes_the_contract_with_its_own_names() -> None:
    p, *_ = _built()
    assert check_part("house", p) is p
    assert [j.name for j in p.clock_jobs] == [
        "chores_due",
        "maint_due",
        "disaster_poll",
        "weather_poll",
    ]
    assert [j.name for j in p.daily_jobs] == ["breach_watch"]
    assert [s.id for s in p.privacy] == ["helpers_house", "helpers_place"]
    assert {t.name for t in p.tools} == {
        "chore_list", "chore_add", "chore_done", "maint_list", "maint_add", "maint_done",
        "maint_starters", "weather_now", "disaster_status", "breach_status",
    }  # fmt: skip
    risks = {t.name: t.risk for t in p.tools}
    assert {n for n, r in risks.items() if r is ActionRisk.REVERSIBLE} == {
        "chore_add", "chore_done", "maint_add", "maint_done",
    }  # fmt: skip
    assert ActionRisk.IRREVERSIBLE not in risks.values()
    assert p.phrases and p.brief and p.pending and "on" in p.ready


def test_switched_off_feeds_have_no_jobs_and_no_keyring_says_so() -> None:
    p, *_ = _built(weather_enabled=False, disaster_alerts_enabled=False)
    assert [j.name for j in p.clock_jobs] == ["chores_due", "maint_due"]
    off, *_ = _built(keyring_on=False)
    assert "no token key" in off.ready


# ---- the tools ----------------------------------------------------------------------------------
async def test_chores_by_tool_add_list_done() -> None:
    p, svc, *_ = _built()
    added = await _call(
        p, "chore_add", label="Laundry", freq="weekly", days=["tue", "sat"], at="18:00",
        members=["Partner", "Me"],
    )  # fmt: skip
    assert added["chore"]["how_often"] == "on Tue, Sat"
    listed = await _call(p, "chore_list")
    assert listed["chores"][0]["label"] == "Laundry" and listed["chores"][0]["whose"] == "Partner"
    done = await _call(p, "chore_done", chore="laundry")
    assert done["chore"]["done_today"] is True
    with pytest.raises(ValueError):
        await _call(p, "chore_done", chore="the moon")
    with pytest.raises(ValueError):
        _tool(p, "chore_add").validate({"label": "x", "freq": "hourly"})


async def test_upkeep_by_tool_and_the_starters() -> None:
    p, *_ = _built()
    starters = await _call(p, "maint_starters")
    assert [s["label"] for s in starters["starters"]][0] == "Water-purifier filter"
    await _call(p, "maint_add", label="AC service", every=180, last_done="2026-05-14", lead_days=7)
    listed = await _call(p, "maint_list")
    assert listed["upkeep"][0]["due"] == "2026-11-10" and listed["upkeep"][0]["state"] == "due"
    done = await _call(p, "maint_done", item="AC service")
    assert done["item"]["state"] == "ok"
    with pytest.raises(ValueError):
        _tool(p, "maint_add").validate({"label": "x", "every": 0})


async def test_disaster_status_fences_sachets_words() -> None:
    p, svc, hc, _, _ = _built()
    await svc.set_place(UID, Place(**PLACE))
    disaster = next(j for j in p.clock_jobs if j.name == "disaster_poll")
    await disaster.run(())
    got = await _call(p, "disaster_status")
    flat = json.dumps(got)
    assert got["official_first"].startswith("JARVIS is a second channel")
    texts = [w["outside_text"] for w in got["warnings"]]
    assert texts and all(t.startswith(FENCE_PREFIX) for t in texts)
    assert "NEEDLE-CAP" in flat  # shown to him only inside the fence
    weather = await _call(p, "weather_now")
    assert "Open-Meteo" in weather["attribution"]


async def test_the_outside_tools_say_off_without_a_place_or_keyring() -> None:
    p, *_ = _built()
    assert "district" in (await _call(p, "weather_now"))["note"]
    off, *_ = _built(keyring_on=False)
    assert "token key" in (await _call(off, "disaster_status"))["note"]
    assert (await _call(off, "breach_status"))["on"] is False


# ---- No-AI phrases ------------------------------------------------------------------------------
NOW = NOON_IST


@pytest.mark.parametrize(
    ("text", "tool", "args"),
    [
        ("what are my chores today?", "chore_list", {}),
        ("Chores", "chore_list", {}),
        ("show the chore rota", "chore_list", {}),
        ("mark the dishes chore done", "chore_done", {"chore": "dishes"}),
        ("Dishes chore done.", "chore_done", {"chore": "Dishes"}),
        ("I did the laundry chore", "chore_done", {"chore": "laundry"}),
        ("what upkeep is due?", "maint_list", {}),
        ("home maintenance", "maint_list", {}),
        ("mark the AC service upkeep done", "maint_done", {"item": "AC service"}),
        ("what's the weather?", "weather_now", {}),
        ("weather today", "weather_now", {}),
        ("any disaster alerts?", "disaster_status", {}),
        ("weather warnings", "disaster_status", {}),
        ("any breach notices?", "breach_status", {}),
    ],
)
def test_phrases_end_in_part_bs_tools(text: str, tool: str, args: dict[str, str]) -> None:
    route = route_no_ai(text, NOW, phrases.PHRASES)
    assert [(c.tool, c.arguments) for c in route.calls] == [(tool, args)]


@pytest.mark.parametrize(
    "text",
    [
        "remind me to do the dishes at 9",
        "mark the report done",
        "what's the weather in Paris",
        "don't remind me to stand up",
        "draft an email about the chores",
        "the weather was lovely, wasn't it, when we walked by the lake today",
    ],
)
def test_phrases_leave_everything_else_alone(text: str) -> None:
    assert all(r(text, NOW) is None for r in phrases.PHRASES)


# ---- privacy rows -------------------------------------------------------------------------------
async def test_helpers_house_lists_exports_and_deletes_chores_and_upkeep() -> None:
    p, svc, hc, _, docs = _built()
    row = next(s for s in p.privacy if s.id == "helpers_house")
    await svc.add_chore(UID, label="Dishes", freq="daily", members=["Me"])
    await svc.add_upkeep(UID, label="AC service", every=180)
    await svc.store.claim(UID, "chore", "x", NOON_IST)
    await svc.store.claim(UID, "wx", "y", NOON_IST)
    view = await row.describe(UID)
    assert view.count == 2 and view.delete == "confirm" and view.section == "Helpers"
    exported = await row.export(UID)
    assert exported is not None and exported["chores"][0]["label"] == "Dishes"
    assert exported["upkeep"][0]["label"] == "AC service"
    assert await row.delete(UID) == 3  # two docs and the chore claim (the weather one stays)
    assert (await row.describe(UID)).count == 0
    assert len(await svc.store.claims(UID)) == 1


async def test_helpers_place_is_sealed_exported_and_deleted() -> None:
    p, svc, hc, _, docs = _built()
    row = next(s for s in p.privacy if s.id == "helpers_place")
    assert (await row.describe(UID)).count == 0
    await svc.set_place(UID, Place(**PLACE))
    await svc.set_breach(UID, True)
    view = await row.describe(UID)
    assert view.count == 1 and view.encrypted_by_jarvis and view.delete == "simple"
    assert "Ernakulam" not in str(docs._data)  # noqa: SLF001 - sealed
    exported = await row.export(UID)
    assert exported is not None and exported["place"]["district"] == "Ernakulam"
    assert exported["breach"]["on"] is True
    assert await row.delete(UID) == 1
    assert await svc.read_outside(UID) == type(await svc.read_outside(UID))()


async def test_helpers_place_without_a_keyring_says_off() -> None:
    p, *_ = _built(keyring_on=False)
    row = next(s for s in p.privacy if s.id == "helpers_place")
    view = await row.describe(UID)
    assert view.count == 0 and "token key" in view.note


# ---- brief and pending --------------------------------------------------------------------------
async def test_the_brief_lines_are_fixed_templates() -> None:
    p, svc, hc, _, _ = _built()
    await svc.add_chore(UID, label="Dishes", freq="daily", at="21:00", members=["Partner"])
    await svc.add_upkeep(UID, label="AC service", every=180, last_done=date(2026, 5, 14))
    await svc.set_place(UID, Place(**PLACE))
    for j in p.clock_jobs:
        if j.name == "disaster_poll":
            await j.run(())
    tz = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
    lines = [x for c in p.brief for x in await c.lines(UID, tz, date(2026, 11, 10))]
    assert "Chores today: Dishes 21:00." in lines
    assert "Home upkeep: AC service due today." in lines
    assert "Urgent: Landslide warning for Ernakulam until 18:00 (SACHET)." in lines
    assert all("NEEDLE" not in x and "Partner" not in x for x in lines)
    assert all(len(x) <= 160 for x in lines)
    assert len([x for c in p.brief for x in await c.lines(UID, tz, date(2026, 11, 10))]) <= 6


async def test_pending_items_for_top_priority() -> None:
    p, svc, *_ = _built()
    await svc.add_chore(UID, label="Dishes", freq="daily", at="09:00")
    await svc.add_upkeep(UID, label="Gas pipe check", every=365, last_done=date(2025, 11, 1))
    (src,) = p.pending
    items = await src.pending(UID, NOON_IST)
    assert [(i.label, i.urgency) for i in items] == [
        ("Upkeep: Gas pipe check", "overdue"),
        ("Chore: Dishes", "today"),
    ]
    await svc.chore_done(UID, "dishes")
    assert [i.label for i in await src.pending(UID, NOON_IST)] == ["Upkeep: Gas pipe check"]


async def test_the_view_for_the_tab() -> None:
    p, svc, hc, _, _ = _built()
    await svc.add_chore(UID, label="Dishes", freq="daily", members=["Partner", "Me"])
    v = await svc.view(UID)
    assert v["chores"][0]["whose"] == "Partner" and v["adults_only"].startswith("Adults only")
    assert v["outside"]["available"] and v["outside"]["place"] is None
    assert "SACHET app, SMS and cell broadcast" in v["outside"]["official_first"]
    _, svc2, *_ = _built(keyring_on=False)
    assert (await svc2.view(UID))["outside"]["off"].startswith("Weather and alerts are off")


async def test_the_brief_says_the_weather_and_an_outage() -> None:
    from jarvis.helpers.house.models import WeatherSummary

    p, svc, *_ = _built()
    await svc.set_place(UID, Place(**PLACE))
    summary = WeatherSummary(day="2026-11-10", t_max=31.0, rain_from="15:00", at="x")

    def down(o: Any) -> Any:
        return o.model_copy(
            update={
                "weather": o.weather.model_copy(update={"summary": summary}),
                "sachet": o.sachet.model_copy(update={"fail_since": "2026-11-10T06:00:00+00:00"}),
            }
        )

    await svc.outside.change(UID, down)
    tz = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
    outside = next(c for c in p.brief if c.name == "outside")
    lines = await outside.lines(UID, tz, date(2026, 11, 10))
    assert lines == [
        "Weather: up to 31 °C, rain likely after 15:00 · "
        "Weather data by Open-Meteo.com (CC BY 4.0)",
        "Can't reach SACHET since 11:30: the official SACHET app and SMS still warn you.",
    ]
    weather = await _call(p, "weather_now")
    assert weather["summary"]["rain_from"] == "15:00" and weather["district"] == "Ernakulam"
