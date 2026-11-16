# tests/test_r13_c_cards.py -- R13 Part C's write tools' cards and argument checks (docs/plans/
# r13-wardrobe.md D10, D16, D18; security review 1 M2, M4, L2, L3): a card's words come from the
# tool's read-only preview in fixed words through `redact` (the plan by its day and time, a piece
# by its fixed words, "a private basic"); removing a whole plan is always a card; every argument
# is checked by the gateway before the policy step, in fixed words that never echo his input; an
# occasion on the write tools is one of the rules' keys; a name where an id belongs never reaches
# the audit, the log or the model. Fixed IST clocks.
from __future__ import annotations

import logging
from typing import Any

import pytest
from r13_fakes import UID
from r13_fakes_c import SCOPE, SHOES, N, World, ist, world

from jarvis.llm.base import ToolCall
from jarvis.tools.context import tool_context
from jarvis.tools.gateway import GatewayOutcome

NEEDLE = "my red lace briefs"


async def ok(w: World, name: str, **args: Any) -> dict[str, Any]:
    got = await w.call(name, **args)
    assert got.outcome is GatewayOutcome.EXECUTED, (got.outcome, got.error)
    assert isinstance(got.result, dict)
    return got.result


async def _save(w: World, **args: Any) -> str:
    return str((await ok(w, "outfit_plan", action="save", **args))["plan"]["id"])


async def _card(w: World, tool: str, **args: Any) -> str:
    t = next(x for x in w.part.tools if x.name == tool)
    assert t.preview is not None
    with tool_context(SCOPE):
        return (await t.preview(args)).summary


# ---- security review M4: cards that say what they do --------------------------------------------
async def test_removing_a_whole_plan_is_always_a_card_naming_the_plan() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _save(w, day="tomorrow", occasion="meeting", start="10:00", end="12:00")
    asked = await w.call("outfit_plan", action="release", plan=pid)
    assert asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION and asked.pending is not None
    assert asked.pending.summary == "Remove tomorrow's 10:00 outfit plan."
    assert (await w.styling.plans.read(UID)).plan(pid) is not None  # nothing done yet
    again = ToolCall(id="c2", name="outfit_plan", arguments=asked.pending.arguments)
    done = await w.gw.execute(again, scope=SCOPE, confirmation_id=asked.pending.id)
    assert done.outcome is GatewayOutcome.EXECUTED
    assert (await w.styling.plans.read(UID)).plan(pid) is None


async def test_each_plan_action_card_names_the_plan_and_the_pieces_in_fixed_words() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _save(w, day="tomorrow", occasion="meeting", start="10:00", end="12:00")
    other = await _save(w, day="tomorrow", start="15:00", end="16:00")
    cases = {
        "Save an outfit plan for Tuesday 17 November, 10:00.": {
            "action": "save", "day": "tomorrow", "start": "10:00", "end": "11:00"},
        "Mark tomorrow's 10:00 outfit outdoors.": {
            "action": "save", "plan": pid, "setting": "outdoor"},
        "Lock the watch of tomorrow's 10:00 outfit.": {
            "action": "lock", "plan": pid, "slot": "watch"},
        "Lock a light blue shirt in tomorrow's 10:00 outfit.": {
            "action": "lock", "plan": pid, "piece": N.shirt_lb},
        "Change the shoes of tomorrow's 10:00 outfit.": {
            "action": "change", "plan": pid, "slot": "shoes"},
        "Reserve a pair of brown dress shoes for tomorrow's 15:00 outfit.": {
            "action": "reserve", "plan": other, "piece": SHOES[0]},
        "Move a pair of brown dress shoes to tomorrow's 15:00 outfit.": {
            "action": "transfer", "plan": other, "from_plan": pid, "piece": SHOES[0]},
        "Take a private basic out of tomorrow's 10:00 outfit.": {
            "action": "release", "plan": pid, "piece": N.under},
        "Share 2 pieces of tomorrow's 10:00 outfit with tomorrow's 15:00 outfit.": {
            "action": "share", "plan": other, "from_plan": pid, "pieces": [N.trousers, N.watch]},
        "Remove an outfit plan.": {"action": "release", "plan": "op_00000000"},
    }  # fmt: skip
    for words, args in cases.items():
        assert await _card(w, "outfit_plan", **args) == words, args


async def test_each_rule_card_says_the_rule_in_fixed_words() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    pid = await _save(w, day="tomorrow", occasion="meeting", start="10:00", end="12:00")
    cases = {
        'Add the rule "never tight at the neck".': {
            "action": "never", "feature": "neck", "value": "tight"},
        'Remove the rule "never tight at the neck".': {
            "action": "allow", "feature": "neck", "value": "tight"},
        "Leave a private basic out of Holi looks.": {
            "action": "exclude", "piece": N.under, "occasion": "holi"},
        "Bring a navy shirt back into every look.": {"action": "include", "piece": N.shirt_navy},
        "Prefer navy in looks.": {"action": "like", "value": "navy"},
        "Avoid orange in looks.": {"action": "avoid", "value": "orange"},
        "Set tomorrow's 10:00 outfit to business casual.": {
            "action": "code", "plan": pid, "code": "business_casual"},
        "Add an outfit rule.": {"action": "never", "feature": "mood", "value": "grumpy"},
    }  # fmt: skip
    for words, args in cases.items():
        assert await _card(w, "outfit_prefs", **args) == words, args


# ---- security review L2, L3: the arguments, checked in fixed words -------------------------------
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("outfit_plan", {"action": "delete_all"}),
        ("outfit_plan", {"action": "release", "plan": NEEDLE}),
        ("outfit_plan", {"action": "reserve", "plan": "op_00000001", "piece": NEEDLE}),
        ("outfit_plan", {"action": "save", "day": "tomorrow", "occasion": NEEDLE}),
        ("outfit_plan", {"action": "save", "day": "tomorrow", "setting": NEEDLE}),
        ("outfit_plan", {"action": "save", "day": NEEDLE * 2}),
        ("outfit_prefs", {"action": "exclude", "piece": N.tee, "occasion": NEEDLE}),
        ("outfit_prefs", {"action": "never", "feature": NEEDLE * 2, "value": "x"}),
        ("outfit_plans", {"days": 99}),
        ("outfit_plans", {"days": True}),
        ("outfit_suggest", {"occasion": NEEDLE * 5}),
        ("wear_log", {"action": "start", "pieces": [N.tee, N.tee]}),
        ("wear_log", {"action": "start", "pieces": [f"wi_{i:012x}" for i in range(21)]}),
        ("wear_log", {"action": "start", "query": NEEDLE * 5}),
        ("wear_log", {"action": "start", "plan": NEEDLE}),
    ],
)
async def test_a_bad_argument_is_refused_before_anything_in_words_that_never_echo_it(
    tool: str, args: dict[str, Any]
) -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    got = await w.call(tool, **args)
    assert got.outcome is GatewayOutcome.ERROR and got.error
    assert NEEDLE not in got.error and "delete_all" not in got.error
    assert all(NEEDLE not in e.detail for e in w.audit._entries)  # noqa: SLF001


async def test_an_occasion_on_the_write_tools_is_one_of_the_rules_keys() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    tool = next(t for t in w.part.tools if t.name == "outfit_plan")
    keys = tool.input_schema["properties"]["occasion"]["enum"]
    assert keys == ["holi", "festival", "meeting", "sport", "function"]
    assert await _save(w, day="tomorrow", occasion="festival")


# ---- security review M2: a name where an id belongs never echoes ---------------------------------
async def test_a_name_instead_of_an_id_never_reaches_the_audit_the_log_or_the_model(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    with caplog.at_level(logging.DEBUG):
        got = await w.call("outfit_prefs", action="exclude", piece=NEEDLE)
    assert got.outcome is GatewayOutcome.ERROR
    assert NEEDLE not in str(got.error) and NEEDLE not in str(got.result)
    assert NEEDLE not in caplog.text
    assert all(NEEDLE not in e.detail for e in w.audit._entries)  # noqa: SLF001


def test_the_rules_refuse_a_name_before_building_any_record() -> None:
    from jarvis.wardrobe.styling import prefs
    from jarvis.wardrobe.styling.plans import PlanRefused, Prefs
    from jarvis.wardrobe.styling.rules import load_rules

    for action in ("exclude", "include"):
        with pytest.raises(PlanRefused) as got:
            prefs.apply(Prefs(), load_rules(), {"action": action, "piece": NEEDLE})
        assert str(got.value) == "Name the piece by its id (wi_ and 12 letters or digits)."
        assert got.value.__context__ is None


async def test_excluding_a_piece_not_in_his_wardrobe_is_refused_in_words() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    got = await ok(w, "outfit_prefs", action="exclude", piece="wi_ffffffffffff")
    assert got == {"refused": True, "message": "That piece isn't in your wardrobe."}
    assert (await w.styling.plans.read(UID)).prefs.excluded == ()
