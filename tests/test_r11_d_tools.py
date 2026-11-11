# tests/test_r11_d_tools.py -- R11 Part D (plan D1, D15, D16, D18): the kitchen's tools through the
# gateway, and every plain-code feature asked by phrase in No-AI mode with no provider call.
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from google_fakes import FakeGoogle
from r11_fakes import UID
from r11_fakes_d import CHICKEN, DAL, Rules, brains, connector, kctx

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.helpers.kinds import tool_allowed
from jarvis.helpers.kitchen import part as kitchen_part
from jarvis.helpers.kitchen.phrases import route
from jarvis.helpers.kitchen.recipes import AI_OFF_LINE
from jarvis.helpers.kitchen.service import KitchenService
from jarvis.llm.base import ToolCall
from jarvis.offline.no_ai import run_no_ai
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust

SCOPE = f"{UID}:sess_t"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
CAL = "https://www.googleapis.com/calendar/v3"
RISK = {
    "pantry_list": ActionRisk.READ_ONLY,
    "pantry_add": ActionRisk.REVERSIBLE,
    "pantry_remove": ActionRisk.REVERSIBLE,
    "kitchen_settings": ActionRisk.REVERSIBLE,
    "recipe_suggest": ActionRisk.READ_ONLY,
    "recipe_save": ActionRisk.REVERSIBLE,
    "recipe_list": ActionRisk.READ_ONLY,
    "nutrition_of": ActionRisk.READ_ONLY,
    "spend_month": ActionRisk.READ_ONLY,
    "calendar_kitchen_blocks": ActionRisk.REVERSIBLE,
}


async def _rig(*replies: str, no_ai: bool = False) -> tuple[Gateway, KitchenService, Any, Any]:
    reg, private, _ = brains(*replies)
    fake = FakeGoogle()
    fake.on(
        "GET",
        f"{CAL}/users/me/calendarList/primary",
        httpx.Response(200, json={"timeZone": "Asia/Kolkata"}),
    )
    conn = await connector(fake.client())
    c, _, _, _ = kctx(reg=reg, no_ai=no_ai, google=conn, rules=Rules())
    built = kitchen_part.build(c)
    tools = ToolRegistry()
    for t in built.tools:
        tools.register(t)
    gw = Gateway(registry=tools, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    return gw, built.services["kitchen"], private, built


async def _call(gw: Gateway, name: str, **args: Any) -> GatewayResult:
    return await gw.execute(ToolCall(id="t", name=name, arguments=args), scope=SCOPE)


async def test_every_tool_is_in_the_kitchen_families_with_its_planned_risk() -> None:
    gw, _, _, built = await _rig()
    assert {t.name: t.risk for t in built.tools} == RISK
    assert all(tool_allowed("kitchen", t.name) for t in built.tools)
    assert all(t.activity_words for t in built.tools)  # no pantry note or amount in Activity


async def test_pantry_add_list_and_remove_dedupe_by_the_groceries_key() -> None:
    gw, _, _, _ = await _rig()
    out = await _call(gw, "pantry_add", items="Tomatoes, toor dal and onions")
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    again = await _call(gw, "pantry_add", items="tomato, rice")
    assert again.result["message"] == "Added to your pantry: rice. Already there: tomato."
    listed = await _call(gw, "pantry_list")
    assert listed.result["pantry"] == ["Tomatoes", "toor dal", "onions", "rice"]
    gone = await _call(gw, "pantry_remove", items="onion, saffron")
    assert gone.result["message"] == "Taken out of your pantry: onions. Not in it: saffron."


async def test_a_round_that_read_outside_content_cannot_change_his_diet() -> None:
    gw, svc, _, _ = await _rig()
    with context_trust(untrusted=True):  # the gateway already makes it a card ...
        card = await _call(gw, "kitchen_settings", diet="nonveg")
    assert card.outcome is GatewayOutcome.AWAITING_CONFIRMATION and card.pending is not None
    out = await gw.execute(  # ... and even the approved card is refused by the kitchen
        ToolCall(id="t", name="kitchen_settings", arguments={"diet": "nonveg"}),
        confirmation_id=card.pending.id,
        scope=SCOPE,
    )
    assert out.outcome is GatewayOutcome.EXECUTED and out.result["refused"] is True
    assert (await svc.store.load(UID)).prefs.diet == "veg"
    ok = await _call(gw, "kitchen_settings", diet="egg", spice=3, cuisines="Kerala, Odia")
    assert ok.outcome is GatewayOutcome.EXECUTED, ok.error
    prefs = (await svc.store.load(UID)).prefs
    assert (prefs.diet, prefs.spice, prefs.cuisines) == ("egg", 3, ("Kerala", "Odia"))


async def test_suggest_then_save_and_list_a_recipe() -> None:
    gw, svc, private, _ = await _rig(DAL)
    await svc.add(UID, "toor dal, onion, tomato")
    idea = await _call(gw, "recipe_suggest")
    r = idea.result["recipe"]
    saved = await _call(
        gw,
        "recipe_save",
        title=r["title"],
        diet=r["diet"],
        minutes=r["minutes"],
        ingredients=r["ingredients"],
        steps=r["steps"],
    )
    assert saved.outcome is GatewayOutcome.EXECUTED, saved.error
    listed = await _call(gw, "recipe_list")
    assert listed.result["message"] == "Your saved recipes, Sir: Dal tadka (30 min, vegetarian)."
    assert len(private.calls) == 1


async def test_a_recipe_cannot_be_saved_as_veg_with_meat_in_it() -> None:
    gw, _, _, _ = await _rig()
    out = await _call(
        gw,
        "recipe_save",
        title="Curry",
        diet="veg",
        minutes=30,
        ingredients="400 g chicken, 80 g onion",
        steps="Cook.",
    )
    assert out.outcome is GatewayOutcome.ERROR and "vegetarian" in (out.error or "")


async def test_a_veg_kitchen_never_sees_chicken_through_the_gateway() -> None:
    gw, svc, private, _ = await _rig(CHICKEN, CHICKEN)
    await svc.add(UID, "onion, tomato")
    out = await _call(gw, "recipe_suggest")
    assert out.result["refused"] is True and "chicken" not in out.for_model().lower()
    assert len(private.calls) == 2


async def test_nutrition_of_a_typed_dish_says_not_installed_until_the_subset_is() -> None:
    gw, _, _, _ = await _rig()
    out = await _call(gw, "nutrition_of", ingredients="200 g rice, 100 g toor dal")
    assert out.outcome is GatewayOutcome.EXECUTED
    assert "isn't installed" in out.result["message"]
    bad = await _call(gw, "nutrition_of", ingredients="some rice")
    assert bad.outcome is GatewayOutcome.ERROR


async def test_spend_month_answers_off_until_receipts_are_on() -> None:
    gw, _, _, _ = await _rig()
    out = await _call(gw, "spend_month")
    assert out.result["off"] is True
    assert (await _call(gw, "spend_month", month="2026-13")).outcome is GatewayOutcome.ERROR


@pytest.mark.parametrize(
    ("text", "tool", "args"),
    [
        ("What's in my pantry?", "pantry_list", {}),
        ("Jarvis, show my pantry", "pantry_list", {}),
        (
            "add rice, toor dal and onions to my pantry",
            "pantry_add",
            {"items": "rice, toor dal and onions"},
        ),
        ("remove onions from the pantry", "pantry_remove", {"items": "onions"}),
        ("What can I cook tonight?", "recipe_suggest", {}),
        ("suggest a recipe", "recipe_suggest", {}),
        ("what can I make with paneer", "recipe_suggest", {"with": "paneer"}),
        ("show my saved recipes", "recipe_list", {}),
        (
            "calories in 200 g rice, 100 g dal",
            "nutrition_of",
            {"ingredients": "200 g rice, 100 g dal"},
        ),
        ("nutrition of avial", "nutrition_of", {"recipe": "avial"}),
        ("how much did I spend on groceries this month?", "spend_month", {"month": "2026-11"}),
        ("grocery spend last month", "spend_month", {"month": "2026-10"}),
        ("how much did I spend on groceries in March", "spend_month", {"month": "2026-03"}),
        ("block cooking and washing-up time", "calendar_kitchen_blocks", {"only": "both"}),
        ("block my cooking time in my calendar", "calendar_kitchen_blocks", {"only": "cooking"}),
        ("set my diet to vegetarian", "kitchen_settings", {"diet": "veg"}),
        ("I am eggetarian", "kitchen_settings", {"diet": "egg"}),
    ],
)
def test_the_no_ai_phrases_end_in_the_kitchen_tools(
    text: str, tool: str, args: dict[str, str]
) -> None:
    got = route(text, NOW)
    assert got is not None and [(c.tool, c.arguments) for c in got.calls] == [(tool, args)]


@pytest.mark.parametrize(
    "text",
    [
        "remind me to cook at 7",
        "what's for dinner at the office party",
        "add milk to groceries",
        "don't remind me to stand up",
        "block the door",
        "I am at home",
    ],
)
def test_the_phrases_are_anchored_and_leave_everything_else_alone(text: str) -> None:
    assert route(text, NOW) is None


async def test_no_ai_mode_answers_every_plain_kitchen_feature_with_no_provider_call() -> None:
    gw, svc, private, built = await _rig(DAL, no_ai=True)
    await _call(
        gw,
        "recipe_save",
        title="Avial",
        diet="veg",
        minutes=40,
        ingredients="100 g carrot, 80 g coconut",
        steps="Cut. Cook.",
    )
    for text, want in (
        ("add rice and dal to my pantry", "Added to your pantry: rice, dal."),
        ("what's in my pantry", "In your pantry, Sir: rice, dal."),
        ("what can I cook", AI_OFF_LINE),
        ("show my saved recipes", "Your saved recipes, Sir: Avial"),
        ("nutrition of avial", "isn't installed"),
        ("grocery spend this month", "Grocery spend is off"),
        ("block cooking time", "That needs your OK, Sir."),
    ):
        out = await run_no_ai(gw, text, NOW, scope=SCOPE, extra=built.phrases)
        assert want in out.reply, (text, out.reply)
    assert private.calls == []
