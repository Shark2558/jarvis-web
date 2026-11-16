# evals/r13/styling.py
"""R13 eval, Part C's suite (`styling`, BUILT): STY-01-17, LND-16 and OPS-04 (docs/plans/
r13-wardrobe.md "Tests and evals"), each case on the in-memory fakes (`tests/r13_fakes_c.py`: the
seeded pilot set, a FIXED IST clock, a fake Google Calendar and Open-Meteo, a real gateway), the
tools called through the gateway and the 5-minute `outfit_clock` run as the app runs it.

Negative controls (each must make its cases fail, or the suite proves nothing):
- the availability check off (`engine.AVAILABILITY`): STY-10, STY-15 and STY-16 fail;
- the wear rule off (`refresh.WEAR_RULE`): STY-13 and STY-15's "sends nothing" fail.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from r13_fakes import UID  # noqa: E402
from r13_fakes_c import SHOES, SNEAKERS, FakeGoogle, N, World, forecast, gevent, ist, world  # noqa: E402

from jarvis.wardrobe.styling import engine, refresh  # noqa: E402
from jarvis.wardrobe.styling.plans import Choice  # noqa: E402

PART = "styling"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]
WORK = "work-cal@example.com"


async def _ok(w: World, name: str, **args: Any) -> dict[str, Any]:
    got = await w.call(name, **args)
    if got.outcome.value != "executed" or not isinstance(got.result, dict):
        raise AssertionError(f"{name} did not run: {got.error}")
    return got.result


async def _save(w: World, **args: Any) -> dict[str, Any]:
    return (await _ok(w, "outfit_plan", action="save", **args))["plan"]  # type: ignore[no-any-return]


def _ids(look: dict[str, Any]) -> set[str]:
    return {i for p in look["pieces"] for i in p["ids"]}


def _slot(look: dict[str, Any], slot: str) -> list[str]:
    return next((p["ids"] for p in look["pieces"] if p["slot"] == slot), [])


def _check(fails: list[str], ok: bool, words: str) -> None:
    if not ok:
        fails.append(words)


async def _pick_calendar(w: World) -> None:
    """His pick of the Work calendar (the route's resolve is tested in test_r13_c_calendar)."""
    await w.styling.change(UID, lambda d: d.model_copy(update={"choice": Choice(calendar=WORK)}))


# ---- the cases -----------------------------------------------------------------------------------
async def sty01() -> list[str]:
    f: list[str] = []
    for at, day in (
        (ist(2026, 11, 16, 23, 30), "Tuesday 17"),
        (ist(2026, 11, 17, 0, 30), "Wednesday 18"),
    ):
        w = await world(at=at, place=False)
        got = await _ok(w, "outfit_suggest", day="tomorrow")
        _check(
            f,
            got["message"].startswith(f"Tomorrow, {day} November: casual, no event planned."),
            f"tomorrow at {at}",
        )
    return f


async def sty02() -> list[str]:
    f: list[str] = []
    google = FakeGoogle(
        events={WORK: [gevent("e1", ist(2026, 11, 17, 10, 0), title="Client meeting")]}
    )
    w = await world(at=ist(2026, 11, 16, 18, 0), google=google)
    await _pick_calendar(w)
    job = w.part.clock_jobs[0]
    await job.run([UID])
    plans = (await w.styling.plans.read(UID)).plans
    _check(f, [str(p.day) for p in plans] == ["2026-11-17"], "a plan for the right date")
    google.events[WORK] = []
    w.clock.set(ist(2026, 11, 16, 19, 5))
    await job.run([UID])
    w.clock.set(ist(2026, 11, 16, 20, 0))
    await job.run([UID])
    plans = (await w.styling.plans.read(UID)).plans
    _check(
        f, plans[0].cancelled and w.notifier.sent == [], "a missing event: a draft, no outfit_ready"
    )
    return f


async def sty03() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    plan = await _save(w, day="tomorrow", start="16:00", end="17:00")  # "Catch-up": no rule word
    await _ok(w, "outfit_prefs", action="code", plan=plan["id"], code="business_formal")
    after = (await _ok(w, "outfit_plans"))["plans"][0]
    top = _slot(after["look"], "top")
    ok = after["code"] == "business_formal" and top in ([N.shirt_white], [N.shirt_lb])
    return [] if ok and not w.google.calls else ["a business-formal look, the calendar untouched"]


async def sty04() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    await w.move(N.shirt_white, "deposited")
    look = (await _ok(w, "outfit_suggest", day="tomorrow", occasion="meeting"))["looks"][0]
    want = {
        "top": [N.shirt_lb],
        "bottom": [N.trousers],
        "shoes": list(SHOES),
        "belt": [N.brown_belt],
        "watch": [N.watch],
    }
    return [] if all(_slot(look, s) == v for s, v in want.items()) else ["the meeting look"]


async def sty05() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    look = (await _ok(w, "outfit_suggest", day="tomorrow", occasion="Diwali"))["looks"][0]
    whole = any("ws_00000001" in r for r in look["reasons"])
    return [] if {N.kurta, N.pyjama} <= _ids(look) and whole else ["the festive set, whole"]


async def sty06() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    await w.edit(N.shirt_navy, mess_ok=True, delicate=True)
    got = await _ok(w, "outfit_suggest", day="tomorrow", occasion="Holi")
    ids = set().union(*(_ids(x) for x in (*got["looks"], *got["alternatives"])))
    return [] if N.shirt_navy not in ids and ids - {N.under} <= {N.tee, N.shorts} else ["Holi"]


async def sty07() -> list[str]:
    w = await world(
        at=ist(2026, 11, 16, 18, 0),
        fetch=forecast(ist(2026, 11, 16).date(), [(29, ()), (27, (15, 16))]),
    )
    await w.part.clock_jobs[0].run([UID])
    await _save(w, day="tomorrow", code="casual", start="16:00", end="18:00", setting="outdoor")
    look = (await _ok(w, "outfit_plans"))["plans"][0]
    rainy = _slot(look, "shoes") == list(SNEAKERS) and _slot(look, "outer") == [N.rain_jacket]
    said = look["weather"] == "Weather for your home area: rain likely from 15:00."
    dry = await world(place=False)
    unknown = (await _ok(dry, "outfit_suggest", day="tomorrow"))["looks"][0]["weather"]
    return [] if rainy and said and unknown.startswith("Weather unknown") else ["the rain rule"]


async def sty08() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    for pid in (N.shirt_lb, N.shirt_white):
        await w.edit(pid, features={"neck": "tight"})
    await _ok(w, "outfit_prefs", action="never", feature="neck", value="tight")
    look = (await _ok(w, "outfit_suggest", day="tomorrow", occasion="meeting"))["looks"][0]
    named = any("never tight at the neck" in g for g in look["gaps"])
    return [] if not _slot(look, "top") and named else ["the rule that leaves no top is named"]


async def sty09() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    look = (await _ok(w, "outfit_suggest", day="tomorrow", occasion="meeting"))["looks"][0]
    slots = {p["slot"]: p for p in look["pieces"]}
    ok = {"shoes", "belt", "watch", "underwear"} <= set(slots) and slots["underwear"][
        "words"
    ] == "a private basic"
    return [] if ok else ["shoes, belt, watch and the private basics"]


async def sty10() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    for pid in (N.belt, N.brown_belt, N.shoe_r):
        await w.move(pid, "deposited")
    got = await _ok(w, "outfit_suggest", day="tomorrow", occasion="meeting")
    pieces = await w.pieces()
    ids = set().union(*(_ids(x) for x in (*got["looks"], *got["alternatives"])))
    return (
        [] if all(pieces[i].state == "ready" for i in ids) else ["an unavailable piece suggested"]
    )


async def sty11() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    got = await _ok(w, "outfit_suggest", day="tomorrow", code="smart_casual")
    for look in (*got["looks"], *got["alternatives"]):
        text = " ".join(look["reasons"])
        if not look["reasons"] or any(i not in text for i in _ids(look)):
            return ["a look without its reasons or ids"]
    return []


async def sty12() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    plan = await _save(w, day="tomorrow", occasion="meeting")
    before = {p["slot"]: p["ids"] for p in plan["look"]["pieces"]}
    got = (await _ok(w, "outfit_plan", action="change", plan=plan["id"], slot="belt"))["plan"]
    after = {p["slot"]: p["ids"] for p in got["look"]["pieces"]}
    same = all(after[s] == before[s] for s in ("top", "bottom", "watch"))
    return [] if same and after["belt"] != before["belt"] else ["change one slot, keep the rest"]


async def sty13() -> list[str]:
    w = await world(at=ist(2026, 11, 17, 8, 0))
    meeting = await _save(w, day="today", occasion="meeting", start="10:00", end="12:00")
    evening = await _save(w, day="today", occasion="function", start="19:00", end="22:00")
    await _ok(
        w,
        "outfit_plan",
        action="share",
        plan=evening["id"],
        from_plan=meeting["id"],
        pieces=[N.trousers, N.watch],
    )
    await _ok(w, "wear_log", action="start", plan=meeting["id"])
    plans = (await _ok(w, "outfit_plans", day="today"))["plans"]
    eve = next(p for p in plans if p["id"] == evening["id"])
    ok = {N.trousers, N.watch} <= _ids(eve["look"]) and not eve["needs"] and not w.notifier.sent
    return [] if ok else ["the declared shared base after 'I'm wearing it'"]


async def sty14() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    first = await _save(w, day="tomorrow", occasion="meeting", start="10:00", end="12:00")
    second = await _save(w, day="tomorrow", occasion="meeting", start="11:00", end="13:00")
    got = await _ok(w, "outfit_plan", action="reserve", plan=second["id"], piece=N.shoe_l)
    ok = _slot(first["look"], "shoes") == list(SHOES) and N.shoe_l not in _ids(second["look"])
    return [] if ok and got.get("refused") else ["a reservation and its conflict"]


async def sty15() -> list[str]:
    f: list[str] = []
    w = await world(at=ist(2026, 11, 16, 18, 0))
    plan = await _save(w, day="tomorrow", occasion="meeting", start="10:00", end="12:00")
    await w.move(N.shirt_white, "deposited")
    now = (await _ok(w, "outfit_plans"))["plans"][0]
    _check(
        f,
        N.shirt_white not in _ids(now["look"]) and _slot(now["look"], "top") == [N.shirt_lb],
        "a ready alternative",
    )
    _check(f, [k for k, _ in w.notifier.sent] == ["outfit_changed"], "one outfit_changed")
    w2 = await world(at=ist(2026, 11, 17, 8, 0))
    today = await _save(w2, day="today", occasion="meeting", start="10:00", end="12:00")
    await _ok(w2, "wear_log", action="start", plan=today["id"])
    after = (await _ok(w2, "outfit_plans", day="today"))["plans"][0]
    _check(f, not w2.notifier.sent and not after["needs"], "wearing the plan sends nothing")
    _ = plan
    return f


async def sty16() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    for pid in SHOES:
        await w.move(pid, "deposited")
    look = (await _ok(w, "outfit_suggest", day="tomorrow", occasion="meeting"))["looks"][0]
    said = any(g.startswith("No ready formal shoes") for g in look["gaps"])
    return (
        []
        if said and not _slot(look, "shoes") and _slot(look, "top")
        else ["no ready formal shoes"]
    )


async def sty17() -> list[str]:
    w = await world(at=ist(2026, 11, 17, 8, 0))
    plan = await _save(w, day="today", occasion="meeting")
    zero = {p.wears for p in (await w.pieces()).values()} == {0}
    await _ok(w, "wear_log", action="start", plan=plan["id"])
    w.clock.advance(hours=9)
    await _ok(w, "wear_log", action="done")
    pieces = await w.pieces()
    return [] if zero and pieces[N.trousers].wears == 1 else ["one wear for start then done"]


async def lnd16() -> list[str]:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    await w.move(N.shirt_white, "sent_out")
    await w.edit(N.shirt_white, expected_back=ist(2026, 11, 17).date())
    look = (await _ok(w, "outfit_suggest", day="tomorrow", occasion="meeting"))["looks"][0]
    out = any(g.startswith("Outstanding: collect a white shirt") for g in look["gaps"])
    return [] if out and _slot(look, "top") == [N.shirt_lb] else ["the outstanding laundry action"]


async def ops04() -> list[str]:
    google = FakeGoogle(events={WORK: [gevent("e1", ist(2026, 11, 17, 10, 0), title="Review")]})
    w = await world(at=ist(2026, 11, 16, 18, 0), google=google)
    await _pick_calendar(w)
    await w.part.clock_jobs[0].run([UID])
    calls = [c for c in google.calls if c[1].endswith("/events")]
    fields = calls[0][2]["fields"] if calls else ""
    only = len(calls) == 1 and "work-cal%40example.com" in calls[0][1]
    return (
        []
        if only and fields == "items(id,status,updated,start,end,summary),nextPageToken"
        else ["his calendar and fields only"]
    )


CASES: dict[str, Case] = {
    "STY-01": sty01, "STY-02": sty02, "STY-03": sty03, "STY-04": sty04, "STY-05": sty05,
    "STY-06": sty06, "STY-07": sty07, "STY-08": sty08, "STY-09": sty09, "STY-10": sty10,
    "STY-11": sty11, "STY-12": sty12, "STY-13": sty13, "STY-14": sty14, "STY-15": sty15,
    "STY-16": sty16, "STY-17": sty17, "LND-16": lnd16, "OPS-04": ops04,
}  # fmt: skip
CONTROLS = (
    ("the availability check off", engine, "AVAILABILITY", {"STY-10", "STY-15", "STY-16"}),
    ("the wear rule off", refresh, "WEAR_RULE", {"STY-13", "STY-15"}),
)


async def _run(case: Case) -> list[str]:
    try:
        return await case()
    except Exception as exc:  # noqa: BLE001 - a case that breaks fails, with its class only
        return [f"raised {type(exc).__name__}"]


async def cases() -> list[dict[str, Any]]:
    out = []
    for name, case in CASES.items():
        fails = await _run(case)
        out.append({"id": f"{PART}:{name}", "passed": not fails, "failures": fails})
    return out


async def control() -> dict[str, Any]:
    failed: dict[str, list[str]] = {}
    every = True
    for words, module, flag, expected in CONTROLS:
        setattr(module, flag, False)
        try:
            got = {r["id"].split(":", 1)[1] for r in await cases() if not r["passed"]}
        finally:
            setattr(module, flag, True)
        failed[words] = sorted(got)
        every = every and expected <= got
    names = " + ".join(w for w, *_ in CONTROLS)
    return {"name": names, "suite_failed": every, "failed_cases": failed}
