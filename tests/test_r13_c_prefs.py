# tests/test_r13_c_prefs.py -- R13 Part C's `outfit_prefs` (docs/plans/r13-wardrobe.md D12, STY-06,
# STY-08): his "never" rules on fixed words only, a piece excluded from one occasion (or all) and
# back again, colours he likes or avoids; a word that isn't on the fixed lists is refused and
# nothing is written. Fixed clocks.
from __future__ import annotations

from typing import Any

from r13_fakes import UID
from r13_fakes_c import N, World, ist, world

from jarvis.tools.gateway import GatewayOutcome


async def ok(w: World, name: str, **args: Any) -> dict[str, Any]:
    got = await w.call(name, **args)
    assert got.outcome is GatewayOutcome.EXECUTED, (got.outcome, got.error)
    return got.result  # type: ignore[no-any-return]


def _ids(got: dict[str, Any]) -> set[str]:
    looks = (*got["looks"], *got["alternatives"])
    return {i for look in looks for p in look["pieces"] for i in p["ids"]}


async def test_never_and_allow_take_fixed_words_only() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    got = await ok(w, "outfit_prefs", action="never", feature="neck", value="tight")
    assert got == {"message": "Noted: never tight at the neck."}
    bad = await ok(w, "outfit_prefs", action="never", feature="mood", value="grumpy")
    assert bad["refused"] is True
    doc = await w.styling.plans.read(UID)
    assert [(n.feature, n.value) for n in doc.prefs.never] == [("neck", "tight")]
    back = await ok(w, "outfit_prefs", action="allow", feature="neck", value="tight")
    assert back == {"message": 'Removed your rule "never tight at the neck".'}
    assert (await w.styling.plans.read(UID)).prefs.never == ()


async def test_sty06_a_favourite_excluded_from_holi_stays_out_and_comes_back() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    await w.edit(N.shirt_navy, mess_ok=True)
    first = await ok(w, "outfit_suggest", day="tomorrow", occasion="Holi")
    assert N.shirt_navy in _ids(first)
    got = await ok(w, "outfit_prefs", action="exclude", piece=N.shirt_navy, occasion="holi")
    assert got == {"message": f"{N.shirt_navy} is left out for Holi."}
    holi = await ok(w, "outfit_suggest", day="tomorrow", occasion="Holi")
    assert N.shirt_navy not in _ids(holi)
    casual = await ok(w, "outfit_suggest", day="tomorrow", code="smart_casual")
    assert N.shirt_navy in _ids(casual)  # only Holi
    await ok(w, "outfit_prefs", action="include", piece=N.shirt_navy, occasion="holi")
    assert N.shirt_navy in _ids(await ok(w, "outfit_suggest", day="tomorrow", occasion="Holi"))


async def test_an_unknown_occasion_is_refused_in_words() -> None:
    w = await world()
    got = await w.call("outfit_prefs", action="exclude", piece=N.tee, occasion="moon landing")
    assert got.outcome is GatewayOutcome.ERROR  # the gateway's check: one of the rules' keys
    assert got.error == "occasion must be one of: holi, festival, meeting, sport, function."


async def test_colours_he_avoids_rank_lower_never_out() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    before = await ok(w, "outfit_suggest", day="tomorrow", code="smart_casual")
    top = next(p for p in before["looks"][0]["pieces"] if p["slot"] == "top")["ids"]
    assert top == [N.shirt_navy]
    await ok(w, "outfit_prefs", action="avoid", value="navy")
    after = await ok(w, "outfit_suggest", day="tomorrow", code="smart_casual")
    new_top = next(p for p in after["looks"][0]["pieces"] if p["slot"] == "top")["ids"]
    assert new_top != [N.shirt_navy]
    for pid in (N.shirt_lb, N.shirt_white, N.tee):
        await w.move(pid, "deposited")
    only = await ok(w, "outfit_suggest", day="tomorrow", code="smart_casual")
    assert N.shirt_navy in _ids(only)  # avoided ranks lower, it is never an exclusion
    liked = await ok(w, "outfit_prefs", action="like", value="navy")
    assert liked == {"message": "Noted: you like navy."}
    doc = await w.styling.plans.read(UID)
    assert doc.prefs.likes == ("navy",) and doc.prefs.avoids == ()


async def test_a_plans_dress_code_must_be_a_known_one() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    plan = (await ok(w, "outfit_plan", action="save", day="tomorrow"))["plan"]
    got = await ok(w, "outfit_prefs", action="code", plan=plan["id"], code="black_tie")
    assert got == {"refused": True, "message": "That isn't one of the dress codes."}
    gone = await ok(w, "outfit_prefs", action="code", plan="op_00000000", code="casual")
    assert gone["refused"] is True
