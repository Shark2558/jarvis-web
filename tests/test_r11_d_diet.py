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
    assert diet.allows(_recipe("jamon"), "veg", pantry=("onion",))


# ---- the security review's probes (H1, M1, M2): every one is refused for a veg kitchen ------
PROBES = [
    # H1: words and compounds the whole-word lists missed
    "goat", "goat curry", "goats", "meatballs", "meat-balls", "Add crabmeat", "crabs", "mince",
    "minced lamb", "hogs", "kebab", "kebabs", "seekh kabab", "tripe", "brain", "paya", "nalli",
    "sushi", "sashimi", "cuttlefish", "carp", "bhetki", "beefsteak", "chicken65", "chicken-65",
    "eggwash", "egg-wash", "eggwhite", "egg white", "egged", "egg yolks", "yolk", "murghi",
    "murgh makhani", "kozhikkari", "maachh", "macchhi", "machli", "gosht", "keema", "foie gras",
    "sea food", "sea-food", "seafood", "trotters", "albumen", "rennet", "squid", "squids",
    "calamari", "crab", "prawn", "prawns", "shrimps", "lobsters", "anchovy paste", "anchovies",
    "fish sauce", "oyster sauce", "fishcake", "fish-fry", "hamburger", "ham", "hams", "bacon bits",
    "lamb's", "venison", "tuna", "pomfret", "hilsa", "clams", "octopuses", "pate", "pâté",
    "mutton", "MUTTON", "mútton", "chilli chicken", "biryani chicken", "anda bhurji", "ande",
    "paneer tikka with mutta", "മുട്ടക്കറി", "മീൻകറി", "मटन", "फिश", "चिकन",
    # M1: spacing, punctuation, marks and look-alike letters
    "Add Chic ken", "c h i c k e n", "C.h.i.c.k.e.n", "chi-cken", "chi\u0307cken", "chi\u010bken",
    "add c\u0430lamari", "\u0441hicken", "ch\u0131cken", "Chic\u200bken curry",
    "\uff23\uff28\uff29\uff23\uff2b\uff25\uff2e", "chi\u00adcken", "add chi\u2060cken pieces",
    "m\u03c5tton", "pr\u0430wn",
]  # fmt: skip


@pytest.mark.parametrize("text", PROBES)
def test_every_probe_is_refused_for_a_veg_kitchen(text: str) -> None:
    assert diet.hits(text, "veg"), text
    assert not diet.allows(_recipe("onion", steps=(f"Add {text}.",)), "veg")


@pytest.mark.parametrize("word", ["eggs", "egg white", "yolk", "anda bhurji", "mayo"])
def test_egg_words_still_pass_an_eggetarian_kitchen(word: str) -> None:
    assert diet.hits(word, "egg") == []


HARMLESS = [
    "eggplant", "Eggplant curry", "egg plant", "eggless cake", "egg-free batter", "egg free",
    "veggies", "veggie burger", "chickpea curry", "chick peas", "kidney beans", "coconut meat",
    "meatless", "oyster mushrooms", "scalloped potatoes", "muttar paneer", "Kozhikode halwa",
    "minced garlic", "minced ginger", "slivered almonds", "papaya salad", "collard greens",
    "kanda poha", "khaman dhokla", "coriander leaves", "cook for several minutes",
    "mineral water", "standard cup", "pandan", "it is fortunate", "reveal the layers",
    "Add the garam masala, mix well.", "Season with salt, pepper, onion.", "black pepper on it",
    "Make sure the oven is on.", "Add a pinch of soda and a little water.",
    "green chili, shredded coconut", "Stir a chilli in.", "Spoon over a chickpea salad.",
    "Heat oil in a thick-bottomed pan.", "Remove from a thick pan.", "nutmeg", "champignon",
    "chamomile tea", "graham crackers", "paneer", "toor dal", "mushroom", "gooseberry",
    "pigeon peas", "chopping board", "a final lime squeeze",
]  # fmt: skip


@pytest.mark.parametrize("text", HARMLESS)
def test_harmless_words_pass(text: str) -> None:
    assert diet.hits(text, "veg") == [], text


RECIPE_LINES = [
    "Wash the toor dal and pressure-cook it with turmeric and salt for 3 whistles.",
    "Heat ghee in a kadai, add cumin seeds, mustard seeds and a pinch of hing.",
    "Add chopped onion, ginger-garlic paste and green chillies; saute till golden.",
    "Add tomatoes, red chilli powder, coriander powder and garam masala; mix well.",
    "Pour in the dal, add water if needed and simmer for 10 minutes.",
    "Temper with curry leaves and dried red chillies, then garnish with coriander.",
    "Soak the rice for 30 minutes, then cook it with whole spices and a bay leaf.",
    "Blend coconut, green chilli and cumin to a smooth paste with a little curd.",
    "Toss the potatoes and cauliflower in oil, salt and pepper; roast at 200 C.",
    "Stir in the paneer cubes and cream, and cook on a low flame for 5 minutes.",
    "Knead the atta with water and a little oil into a soft dough; rest it.",
    "Serve hot with rice or chapati, and a squeeze of lemon on top.",
]


def test_a_corpus_of_ordinary_veg_recipe_lines_passes() -> None:
    for line in RECIPE_LINES:
        assert diet.hits(line, "veg") == [], line


def test_the_cuisine_is_checked_too() -> None:  # M2
    r = _recipe("onion").model_copy(update={"cuisine": "Chicken Chettinad"})
    assert not diet.allows(r, "veg")


# ---- the allow-list: a new idea uses only his pantry and a few fixed staples ----------------
PANTRY = ("toor dal", "Onions", "tomato", "basmati rice", "fresh coriander")


def test_an_idea_made_of_pantry_items_and_staples_is_allowed() -> None:
    r = _recipe(
        "toor dal", "onion", "chopped tomatoes", "rice", "coriander leaves", "salt", "ghee",
        "turmeric powder", "cumin seeds", "red chilli powder", "water", "mustard oil",
    )  # fmt: skip
    assert diet.outside_pantry(r, PANTRY) == []
    assert diet.allows(r, "veg", pantry=PANTRY)


@pytest.mark.parametrize("name", ["jamon", "paneer", "dal makhani mix", "rice wine", "stock"])
def test_an_idea_with_anything_else_is_refused_for_a_veg_or_egg_kitchen(name: str) -> None:
    r = _recipe("toor dal", name)
    assert diet.outside_pantry(r, PANTRY) == [name]
    assert not diet.allows(r, "veg", pantry=PANTRY)
    assert not diet.allows(r.model_copy(update={"diet": "egg"}), "egg", pantry=PANTRY)
    assert diet.allows(r.model_copy(update={"diet": "nonveg"}), "nonveg", pantry=PANTRY)


def test_an_empty_pantry_allows_only_the_staples() -> None:
    assert not diet.allows(_recipe("toor dal", "salt"), "veg", pantry=())
    assert diet.allows(_recipe("salt", "water"), "veg", pantry=())


def test_a_pantry_item_with_a_meat_word_is_still_refused() -> None:
    assert not diet.allows(_recipe("chicken"), "veg", pantry=("chicken",))
