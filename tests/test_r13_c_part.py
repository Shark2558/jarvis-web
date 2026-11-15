# tests/test_r13_c_part.py -- R13 Part C's join (docs/plans/r13-wardrobe.md "Part split", D15, D16,
# D20; BRIEF-COMMON 2-4): built through the real wiring's contract check with only its own tools,
# job, service and data; a rules file that fails its check leaves the part out ("setup failed")
# while the others run; no key or no storage says so; D's Privacy data (count, export, delete);
# the forgotten wear closed from 04:00 his time for A's sweep (STY-17); the package ships its
# rules file (a tripwire for I1).
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from r13_fakes import UID
from r13_fakes_c import N, World, ist, world

import jarvis.api.r13_wiring as wiring
from jarvis.tools.gateway import GatewayOutcome
from jarvis.wardrobe.ports import TOOL_OWNER, WardrobeData
from jarvis.wardrobe.styling import part as styling_part
from jarvis.wardrobe.styling import rules as styling_rules
from jarvis.wardrobe.styling import wear
from jarvis.wardrobe.styling.rules import RulesError, load_rules

ROOT = Path(__file__).resolve().parents[1]


async def test_the_part_passes_the_wirings_contract_check() -> None:
    w = await world()
    checked = wiring.check_part("styling", w.part)
    assert {t.name for t in checked.tools} == {t for t, p in TOOL_OWNER.items() if p == "styling"}
    assert [j.name for j in checked.clock_jobs] == ["outfit_clock"] and not checked.daily_jobs
    assert set(checked.services) == {"refresh"} and checked.ready == "ready"
    assert all(isinstance(d, WardrobeData) for d in checked.data)


async def test_a_rules_file_that_fails_its_check_is_setup_failed_and_others_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = await world()

    def broken(path: Any = None) -> Any:
        raise RulesError("the styling rules failed their check")

    monkeypatch.setattr(styling_part, "load_rules", broken)
    parts = wiring.build_parts(w.ctx)
    assert parts["styling"].ready == "setup failed" and not parts["styling"].tools
    assert parts["catalog"].ready == "not built yet"  # the others still built


async def test_no_key_or_no_storage_is_built_and_says_so() -> None:
    assert (await world(keyring=None)).part.ready == "off: no token key"
    w = await world()
    bare = w.ctx.__class__(**{**w.ctx.__dict__, "docs": None})
    assert styling_part.build_with(bare).ready == "off: no storage"


async def test_the_privacy_data_counts_exports_and_deletes_everything() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    got = await w.call("outfit_plan", action="save", day="tomorrow", occasion="meeting")
    assert got.outcome is GatewayOutcome.EXECUTED
    await w.call("outfit_prefs", action="never", feature="neck", value="tight")
    (data,) = w.part.data
    assert data.name == "outfits" and await data.count(UID) == 1
    export = await data.export(UID)
    assert export["rules"]["never"] == [{"feature": "neck", "value": "tight"}]
    assert export["plans"][0]["dress_code"] == "business_formal"
    await w.styling.told.once(UID, "ready_test")
    assert await data.delete(UID) >= 2
    assert await data.count(UID) == 0 and await w.styling.told.count(UID) == 0
    assert not [p for p in w.docs._data if "wardrobe_plans" in p or "wardrobe_told" in p]  # noqa: SLF001


async def _wearing(w: World) -> None:
    got = await w.call("wear_log", action="start", pieces=[N.shirt_lb, N.trousers])
    assert got.outcome is GatewayOutcome.EXECUTED


async def test_sty17_the_sweep_closes_a_forgotten_wear_at_04_00_his_time() -> None:
    w = await world(at=ist(2026, 11, 16, 9, 0))
    await _wearing(w)
    rules = load_rules()
    store = w.store
    w.clock.set(ist(2026, 11, 17, 3, 55))
    zone = await w.ctx.zone(UID)
    assert (
        await wear.close_forgotten(store, UID, now=w.clock(), zone=zone, close="04:00", rules=rules)
        == 0
    )
    w.clock.set(ist(2026, 11, 17, 4, 0))
    assert (
        await wear.close_forgotten(store, UID, now=w.clock(), zone=zone, close="04:00", rules=rules)
        == 2
    )
    assert (
        await wear.close_forgotten(store, UID, now=w.clock(), zone=zone, close="04:00", rules=rules)
        == 0
    )
    pieces = await w.pieces()
    assert (pieces[N.shirt_lb].state, pieces[N.shirt_lb].wears) == ("in_laundry", 1)
    assert (pieces[N.trousers].state, pieces[N.trousers].wears) == ("ready", 1)


async def test_a_wear_started_today_is_not_closed_tonight() -> None:
    w = await world(at=ist(2026, 11, 17, 4, 30))
    await _wearing(w)
    w.clock.set(ist(2026, 11, 17, 23, 0))
    zone = await w.ctx.zone(UID)
    got = await wear.close_forgotten(
        w.store, UID, now=w.clock(), zone=zone, close="04:00", rules=load_rules()
    )
    assert got == 0


def test_the_rules_file_is_beside_the_module() -> None:
    assert (Path(styling_rules.__file__).parent / "rules.json").is_file()


@pytest.mark.xfail(strict=True, reason="Needs I1: pyproject package-data for rules.json")
def test_the_package_ships_the_rules_file() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"jarvis.wardrobe.styling" = ["rules.json"]' in text
