# tests/test_r11_d_recipes.py -- R11 Part D (plan D1, D15, item 13): recipe ideas from what he has.
# One metered balanced-tier call through `jarvis.llm` on a brain that doesn't learn from what it's
# told; pantry and notes fenced as data; the reply must parse as JSON; the CODE diet check has the
# last word (a veg kitchen is never shown chicken); No-AI answers from his saved recipes only.
from __future__ import annotations

from typing import Any

import pytest
from r11_fakes import UID
from r11_fakes_d import CHICKEN, DAL, brains, kctx, recipe_json

from jarvis.billing.budget import BudgetPatch
from jarvis.helpers.kitchen import diet
from jarvis.helpers.kitchen.models import Ingredient, Kitchen, Prefs, Recipe
from jarvis.helpers.kitchen.nutrition import Nutrition
from jarvis.helpers.kitchen.recipes import (
    AI_OFF_LINE,
    LIMIT_LINE,
    MAX_TOKENS,
    NO_PRIVATE_LINE,
    SYSTEM,
    RecipeService,
)
from jarvis.helpers.kitchen.store import KitchenStore

SAVED = Recipe(
    id="saved0001",
    title="Avial",
    cuisine="Kerala",
    diet="veg",
    minutes=40,
    ingredients=(Ingredient(name="carrot", grams=100), Ingredient(name="coconut", grams=80)),
    steps=("Cut the vegetables.", "Cook with coconut and curd."),
)
SAVED_FISH = SAVED.model_copy(update={"id": "saved0002", "title": "Meen curry", "diet": "nonveg"})


async def _service(
    *replies: str,
    prefs: Prefs | None = None,
    train_default: bool = False,
    private: bool = True,
    **kw: Any,
) -> tuple[Any, ...]:
    reg, safe, training = brains(*replies, train_default=train_default, private=private)
    c, _, docs, _ = kctx(reg=reg, **kw)
    store = KitchenStore(docs, c.keyring, now=c.now)
    if c.keyring is not None:
        kitchen = Kitchen(
            pantry=("toor dal", "onion", "tomato", "carrot", "coconut"),
            prefs=prefs or Prefs(diet="veg", spice=2, note="NEEDLE-NOTE no mushrooms"),
            recipes=(SAVED, SAVED_FISH),
        )
        await store.change(UID, lambda _: kitchen)
    svc = RecipeService(
        store,
        brains=c.brains,
        billing=c.billing,
        mode=c.brain_mode,
        nutrition=Nutrition((), installed=False),
    )
    return svc, safe, training, c


async def test_an_idea_comes_from_one_metered_balanced_call_with_the_pantry_fenced() -> None:
    svc, private, training, c = await _service(DAL)
    out = await svc.suggest(UID, {})
    assert out["from"] == "ai" and out["recipe"]["title"] == "Dal tadka"
    assert out["message"].startswith("Here's an idea, Sir: Dal tadka")
    assert len(private.calls) == 1 and training.calls == []
    call = private.calls[0]
    assert call.system == SYSTEM and call.tools is None and call.max_tokens == MAX_TOKENS == 700
    assert call.model == "claude-sonnet-5-5"  # the balanced tier, never a model id in the skill
    prompt = call.messages[0].text()
    assert "<<EXTERNAL CONTENT from the owner's pantry" in prompt and "toor dal" in prompt
    assert "NEEDLE-NOTE" in prompt.split("<<EXTERNAL CONTENT from the owner's notes")[1]
    assert "vegetarian (no meat, fish or egg)" in prompt and "medium" in prompt
    month = c.billing.meter.month_of(c.now())
    assert (await c.billing.meter.get(UID, month)).inr_total > 0


async def test_a_veg_kitchen_answered_with_chicken_asks_once_more_then_shows_the_veg_idea() -> None:
    svc, private, _, _ = await _service(CHICKEN, DAL)
    out = await svc.suggest(UID, {})
    assert out["recipe"]["title"] == "Dal tadka" and len(private.calls) == 2
    assert "broke the diet rule" in private.calls[1].messages[0].text()
    assert "chicken" not in str(out).lower()


async def test_a_veg_kitchen_answered_with_chicken_twice_is_refused_by_code() -> None:
    svc, private, _, _ = await _service(CHICKEN, CHICKEN, CHICKEN)
    out = await svc.suggest(UID, {})
    assert out["refused"] is True and "recipe" not in out and len(private.calls) == 2
    assert "chicken" not in str(out).lower()


async def test_with_the_diet_check_off_the_chicken_would_be_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # what the eval's negative control relies on
    monkeypatch.setattr(diet, "DIET_CHECK", False)
    svc, _, _, _ = await _service(CHICKEN)
    assert (await svc.suggest(UID, {}))["recipe"]["title"] == "Chicken curry"


async def test_a_request_can_only_make_the_diet_stricter() -> None:
    svc, private, _, _ = await _service(DAL)
    await svc.suggest(UID, {"diet": "nonveg", "cuisine": "Kerala"})
    prompt = private.calls[0].messages[0].text()
    assert "vegetarian (no meat, fish or egg)" in prompt and "Kerala" in prompt
    svc, private, _, _ = await _service(recipe_json("Egg roast", ("egg", 120), diet="egg"),
                                        prefs=Prefs(diet="nonveg"))  # fmt: skip
    out = await svc.suggest(UID, {"diet": "egg"})
    assert out["recipe"]["diet"] == "egg"


async def test_a_reply_that_is_not_a_recipe_is_dropped() -> None:
    svc, private, _, _ = await _service("Sure! Here's a lovely dal: boil it.", '{"title": 5}')
    out = await svc.suggest(UID, {})
    assert out["refused"] is True and "recipe" not in out and len(private.calls) == 2


async def test_links_and_addresses_in_a_reply_are_removed() -> None:
    sneaky = recipe_json("Dal", ("toor dal", 100)).replace(
        "Serve hot.", "Serve hot. See https://evil.example/x or mail a@evil.example"
    )
    svc, _, _, _ = await _service(sneaky)
    out = await svc.suggest(UID, {})
    text = " ".join(out["recipe"]["steps"])
    assert "https://" not in text and "a@evil.example" not in text and "evil.example" not in text


async def test_no_ai_answers_from_saved_recipes_with_the_ai_off_line_and_no_call() -> None:
    svc, private, training, _ = await _service(DAL, no_ai=True)
    out = await svc.suggest(UID, {})
    assert out["message"].startswith(AI_OFF_LINE) and out["from"] == "saved"
    assert [r["title"] for r in out["recipes"]] == ["Avial"]  # the fish curry isn't veg
    assert private.calls == [] and training.calls == []


async def test_a_brain_that_may_learn_from_what_it_is_told_is_never_used() -> None:
    svc, private, training, _ = await _service(DAL, train_default=True)
    assert (await svc.suggest(UID, {}))["from"] == "ai"
    assert training.calls == [] and len(private.calls) == 1
    svc, private, training, _ = await _service(DAL, private=False)
    out = await svc.suggest(UID, {})
    assert out["message"].startswith(NO_PRIVATE_LINE) and training.calls == []


async def test_at_the_monthly_limit_no_call_is_made() -> None:
    svc, private, _, c = await _service(DAL)
    await c.billing.set_limit(UID, BudgetPatch(monthly_limit_inr=1))
    month = c.billing.meter.month_of(c.now())
    await c.billing.meter.add(UID, brain_id="anthropic", cost_usd=1.0, cost_inr=95.0, now=c.now())
    assert (await c.billing.meter.get(UID, month)).inr_total >= 1
    out = await svc.suggest(UID, {})
    assert out["message"].startswith(LIMIT_LINE) and private.calls == []


async def test_without_billing_or_a_keyring_nothing_is_called() -> None:
    svc, private, _, _ = await _service(DAL, metered=False)
    assert "spending meter" in (await svc.suggest(UID, {}))["message"] and private.calls == []
    svc, private, _, _ = await _service(DAL, sealed=False)
    assert "kitchen is off" in (await svc.suggest(UID, {}))["message"] and private.calls == []


async def test_a_suggestion_marks_what_he_has() -> None:
    svc, _, _, _ = await _service(recipe_json("Dal", ("toor dal", 100), ("ghee", 10)))
    got = {i["name"]: i["have"] for i in (await svc.suggest(UID, {}))["recipe"]["ingredients"]}
    assert got == {"toor dal": True, "ghee": False}
