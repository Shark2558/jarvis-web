# tests/test_r11_d_diet.py -- R11 Part D (plan D15): the diet check is code and has the last word.
from __future__ import annotations

import pytest

from jarvis.helpers.kitchen import diet
from jarvis.helpers.kitchen.models import Ingredient, Recipe


def _recipe(*names: str, d: str = "veg", steps: tuple[str, ...] = ("Cook.",)) -> Recipe:
    return Recipe(
        id="r0000001",
        title="Idea",
        diet=d,  # type: ignore[arg-type]
        minutes=20,
        ingredients=tuple(Ingredient(name=n, grams=100) for n in names),
        steps=steps,
    )


@pytest.mark.parametrize(
    "word",
    ["chicken", "Mutton", "fish", "prawns", "beef", "pork", "kozhi", "meen", "chingudi", "keema",
     "murgh", "gosht", "chemmeen", "machha", "shrimp", "anchovy", "gelatin", "fish sauce",
     "കോഴി", "മീൻ", "ମାଛ", "चिकन", "मछली"],
)  # fmt: skip
def test_a_veg_request_refuses_every_meat_and_fish_word(word: str) -> None:
    assert diet.hits(f"200 g {word}", "veg")
    assert diet.hits(word, "egg")
    assert not diet.hits(word, "nonveg")


@pytest.mark.parametrize("word", ["egg", "Eggs", "omelette", "anda", "mutta", "muttai", "अंडा"])
def test_egg_is_refused_for_veg_and_allowed_for_eggetarian(word: str) -> None:
    assert diet.hits(word, "veg")
    assert not diet.hits(word, "egg")


@pytest.mark.parametrize(
    "text",
    ["eggplant", "Eggplant curry", "eggless cake", "egg-free batter", "red kidney beans",
     "coconut meat", "paneer", "toor dal", "mushroom"],
)  # fmt: skip
def test_vegetarian_words_that_look_alike_pass(text: str) -> None:
    assert diet.hits(text, "veg") == []


def test_the_check_reads_title_ingredients_and_steps() -> None:
    assert not diet.allows(_recipe("onion", steps=("Add the chicken.",)), "veg")
    assert not diet.allows(_recipe("chicken"), "veg")
    assert diet.allows(_recipe("onion", "tomato"), "veg")


def test_a_recipe_that_says_nonveg_is_refused_for_veg_even_with_veg_ingredients() -> None:
    assert not diet.allows(_recipe("onion", d="nonveg"), "veg")
    assert not diet.allows(_recipe("onion", d="egg"), "veg")
    assert diet.allows(_recipe("onion", d="veg"), "nonveg")


def test_stricter_picks_the_stricter_diet() -> None:
    assert diet.stricter("nonveg", "veg") == "veg"
    assert diet.stricter("egg", "nonveg") == "egg"
    assert diet.stricter("veg", None) == "veg"


def test_switching_the_check_off_is_the_eval_control(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diet, "DIET_CHECK", False)
    assert diet.allows(_recipe("chicken"), "veg")
