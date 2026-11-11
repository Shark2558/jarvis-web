# tests/test_r11_d_nutrition.py -- R11 Part D (plan D15): nutrition per dish from a bundled USDA
# FoodData Central subset (CC0), plain sums; and the converter from the official FDC CSV download.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from r11_fakes_d import FIXTURES

from jarvis.helpers.kitchen import nutrition
from jarvis.helpers.kitchen.models import Ingredient
from jarvis.helpers.kitchen.nutrition import NOT_INSTALLED, Nutrition, describe, parse_ingredients

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kitchen_fdc_subset.py"
FOODS = [
    {
        "key": "rice",
        "fdc_id": 111,
        "description": "Rice, white, long-grain, regular, raw, unenriched",
        "names": ["rice", "chawal", "basmati rice"],
        "per100g": {"kcal": 365, "protein_g": 7.1, "fat_g": 0.7, "carb_g": 80.0,
                    "fibre_g": 1.3, "sodium_mg": 5},
    },
    {
        "key": "toor dal",
        "fdc_id": 222,
        "description": "Pigeon peas (red gram), mature seeds, raw",
        "names": ["toor dal", "arhar dal"],
        "per100g": {"kcal": 343, "protein_g": 21.7, "fat_g": 1.5, "carb_g": 62.8,
                    "fibre_g": 15.0, "sodium_mg": None},
    },
]  # fmt: skip


def _data(tmp_path: Path, foods: list[dict[str, object]], installed: bool = True) -> Path:
    path = tmp_path / "fdc.json"
    path.write_text(json.dumps({"installed": installed, "source": {}, "foods": foods}))
    return path


def test_the_bundled_file_is_a_clearly_marked_empty_subset_until_i1_fetches_the_data() -> None:
    raw = json.loads(nutrition.DATA.read_text())
    assert raw["installed"] is False and raw["foods"] == []
    assert "not installed" in raw["about"].lower()
    n = Nutrition.load()
    assert n.installed is False
    assert n.dish((Ingredient(name="rice", grams=100),)).installed is False
    assert describe(n.dish((Ingredient(name="rice", grams=100),))) == NOT_INSTALLED


def test_a_dish_is_the_sum_of_grams_times_the_per_100g_values(tmp_path: Path) -> None:
    n = Nutrition.load(_data(tmp_path, FOODS))
    d = n.dish((Ingredient(name="Chawal", grams=200), Ingredient(name="toor dal", grams=50)))
    assert d.totals["kcal"] == pytest.approx(365 * 2 + 343 * 0.5)
    assert d.totals["protein_g"] == pytest.approx(7.1 * 2 + 21.7 * 0.5)
    assert d.totals["sodium_mg"] == pytest.approx(10)  # an unknown value counts as nothing
    assert d.matched == 2 and d.unmatched == ()
    line = describe(d)
    assert line.startswith("About 902 kcal") and "USDA FoodData Central" in line


def test_unknown_ingredients_are_named_not_guessed(tmp_path: Path) -> None:
    n = Nutrition.load(_data(tmp_path, FOODS))
    d = n.dish(
        (Ingredient(name="basmati rice", grams=100), Ingredient(name="dragonfruit", grams=50))
    )
    assert d.matched == 1 and d.unmatched == ("dragonfruit",)
    assert "1 of 2 ingredients" in describe(d)


def test_a_broken_or_missing_file_reads_as_not_installed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert Nutrition.load(bad).installed is False
    assert Nutrition.load(tmp_path / "missing.json").installed is False


def test_typed_ingredients_are_parsed_with_their_grams() -> None:
    got = parse_ingredients("200 g rice, 50g toor dal; 1 kg potato, onion 80 g")
    assert [(i.name, i.grams) for i in got] == [
        ("rice", 200),
        ("toor dal", 50),
        ("potato", 1000),
        ("onion", 80),
    ]
    with pytest.raises(ValueError):
        parse_ingredients("some rice")


# ---- the converter (scripts/kitchen_fdc_subset.py) -------------------------------------------
def _convert(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    out = tmp_path / "subset.json"
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--food", str(FIXTURES / "fdc_sample.csv"),
         "--food-nutrient", str(FIXTURES / "d_fdc_food_nutrient.csv"), "--out", str(out), *extra],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip


def test_the_converter_builds_the_subset_from_the_official_csv_shape(tmp_path: Path) -> None:
    r = _convert(tmp_path, "--allow-missing")
    assert r.returncode == 0, r.stderr
    data = json.loads((tmp_path / "subset.json").read_text())
    assert data["installed"] is True and data["source"]["licence"].startswith("CC0")
    assert len(data["source"]["sha256"]["food.csv"]) == 64
    by_key = {f["key"]: f for f in data["foods"]}
    rice = by_key["rice"]
    assert rice["per100g"] == {
        "kcal": 365.0, "protein_g": 7.13, "fat_g": 0.66, "carb_g": 79.95,
        "fibre_g": 1.3, "sodium_mg": 5.0,
    }  # fmt: skip
    assert "chawal" in rice["names"]
    assert "chicken breast" in by_key  # mapped for non-veg kitchens too
    n = Nutrition.load(tmp_path / "subset.json")
    assert n.installed and n.find("chawal") is not None


def test_the_converter_fails_when_mapped_foods_are_missing_unless_allowed(tmp_path: Path) -> None:
    r = _convert(tmp_path)
    assert r.returncode == 1 and "not found in the FDC file" in r.stderr
