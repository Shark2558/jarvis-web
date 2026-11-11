# tests/test_r11_d_nutrition.py -- R11 Part D (plan D15): nutrition per dish from a bundled USDA
# FoodData Central subset (CC0), plain sums; and the converter from the official FDC CSV download.
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest
from r11_fakes_d import FIXTURES

from jarvis.helpers.kitchen import nutrition
from jarvis.helpers.kitchen.models import Ingredient
from jarvis.helpers.kitchen.nutrition import (
    NOT_INSTALLED,
    Nutrition,
    describe,
    describe_full,
    parse_ingredients,
)

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


ZIP = "FoodData_Central_sr_legacy_food_csv_2018-04.zip"
ZIP_SHA256 = "b80817294b8850530aaedf2e515c02593b1824f763a0ff356e5c2081643e6fd0"
LABEL = "US reference values (USDA FoodData Central); Indian varieties and home recipes can differ."


def _bundled() -> dict[str, object]:
    with nutrition.DATA.open("rb") as f:
        data: dict[str, object] = json.loads(f.read())
    return data


def test_the_bundled_subset_is_installed_with_its_source_and_cc0_attribution() -> None:
    """I1: the owner's SR Legacy zip, converted; small enough to ship as plain JSON."""
    raw = _bundled()
    assert raw["installed"] is True and raw["format"] == 2
    src = raw["sources"]["usda_sr_legacy"]  # type: ignore[index]
    assert src["file"] == ZIP and src["file_sha256"] == ZIP_SHA256
    assert src["licence"] == "CC0 1.0 (public domain)" and "FoodData Central" in src["citation"]
    assert src["region"] == "US" and src["label"] == LABEL
    assert set(src["sha256"]) == {"food.csv", "food_nutrient.csv", "nutrient.csv"}
    foods = raw["foods"]
    assert isinstance(foods, list) and 300 <= len(foods) <= 600
    assert {f["group"] for f in foods} >= {
        "cereals and millets", "pulses and dals", "vegetables", "fruits", "nuts and seeds",
        "spices and herbs", "dairy and eggs", "oils and ghee", "poultry", "fish and seafood",
        "meat",
    }  # fmt: skip
    assert all(f["source"] == "usda_sr_legacy" for f in foods)
    with nutrition.DATA.open("rb") as f:
        assert len(f.read()) < 2_000_000  # stored as plain JSON, not gzipped


def test_three_real_foods_answer_with_the_files_own_values() -> None:
    """Rice, red lentils (masoor dal) and whole milk, per 100 g, as SR Legacy's CSV gives them
    (fdc_id 169756, 174284, 171265), with every other nutrient kept too."""
    n = Nutrition.load()
    assert n.installed
    want = {
        "chawal": (169756, {"kcal": 365.0, "protein_g": 7.13, "fat_g": 0.66, "carb_g": 79.95,
                            "fibre_g": 1.3, "sodium_mg": 5.0}, 28.0),
        "masoor dal": (174284, {"kcal": 358.0, "protein_g": 23.91, "fat_g": 2.17, "carb_g": 63.1,
                                "fibre_g": 10.8, "sodium_mg": 7.0}, 48.0),
        "doodh": (171265, {"kcal": 61.0, "protein_g": 3.15, "fat_g": 3.25, "carb_g": 4.8,
                           "fibre_g": 0.0, "sodium_mg": 43.0}, 113.0),
    }  # fmt: skip
    for name, (fid, per, calcium) in want.items():
        food = n.find(name)
        assert food is not None and food.fdc_id == fid, name
        assert dict(food.per100) == per, name
        assert food.all[1087] == calcium and len(food.all) >= 60, name  # calcium, and the rest
    assert n.nutrients[1087] == ("Calcium, Ca", "mg")
    d = n.dish((Ingredient(name="rice", grams=200), Ingredient(name="masoor dal", grams=50)))
    assert d.totals["kcal"] == pytest.approx(365 * 2 + 358 * 0.5)
    line = describe(d)
    assert line.startswith("About 909 kcal, 26 g protein") and LABEL in line


def test_the_full_panel_has_every_nutrient_and_the_label() -> None:
    n = Nutrition.load()
    d = n.dish((Ingredient(name="milk", grams=200),))
    panel = dict(n.panel(d))
    assert panel["Calcium, Ca"] == "226 mg" and panel["Water"] == "176 g" and len(panel) >= 60
    full = describe_full(d, n)
    assert full.startswith("Full nutrition, about: Water 176 g; Energy 122 kcal") and LABEL in full


def test_an_indian_source_when_installed_wins_over_usda_and_says_its_own_label(
    tmp_path: Path,
) -> None:
    """I1: the structure only. A fake source marked "IN" is preferred; USDA is the fallback."""
    fake = tmp_path / "nutrition_fake_in.json"
    fake.write_text(json.dumps({
        "installed": True,
        "sources": {"fake_in": {"region": "IN", "label": "Indian test values (not real)."}},
        "foods": [{"key": "rice", "source": "fake_in", "fdc_id": 0, "names": ["chawal"],
                   "per100g": {"kcal": 100.0, "protein_g": 1.0}, "all": [[1008, 100.0]]}],
    }))  # fmt: skip
    n = Nutrition.load(nutrition.DATA, fake)
    rice = n.find("chawal")
    assert rice is not None and rice.source == "fake_in" and n.region_of(rice) == "IN"
    milk = n.find("milk")
    assert milk is not None and milk.source == "usda_sr_legacy"  # the fallback
    d = n.dish((Ingredient(name="rice", grams=100), Ingredient(name="milk", grams=100)))
    assert d.totals["kcal"] == pytest.approx(100 + 61)
    line = describe(d)
    assert "Indian test values (not real)." in line and LABEL in line
    only_usda = Nutrition.load(nutrition.DATA)
    assert only_usda.find("chawal").source == "usda_sr_legacy"  # type: ignore[union-attr]


def test_with_no_data_file_every_answer_says_not_installed(tmp_path: Path) -> None:
    n = Nutrition.load(tmp_path / "missing.json")
    assert n.installed is False
    assert n.dish((Ingredient(name="rice", grams=100),)).installed is False
    assert describe(n.dish((Ingredient(name="rice", grams=100),))) == NOT_INSTALLED
    off = tmp_path / "off.json"
    off.write_text(json.dumps({"installed": False, "foods": []}))
    assert Nutrition.load(off).installed is False


def test_the_subset_ships_as_package_data() -> None:
    """The deploy installs non-editable (`pip install .`): the JSON must be package data."""
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    data = cfg["tool"]["setuptools"]["package-data"]
    assert "data/*.json" in data["jarvis.helpers.kitchen"]
    shipped = files("jarvis.helpers.kitchen").joinpath("data", "fdc_subset.json")
    assert shipped.is_file() and str(nutrition.DATA) == str(shipped)


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


@pytest.mark.parametrize(("name", "near"), [("coconut milk", "milk"), ("sweet potato", "potato")])
def test_a_longer_name_is_never_read_as_its_last_word(
    tmp_path: Path, name: str, near: str
) -> None:  # code review M3: no "about" a different food
    food = {"key": near, "fdc_id": 333, "names": [], "per100g": {"kcal": 60}}
    n = Nutrition.load(_data(tmp_path, [*FOODS, food]))
    assert n.find(name) is None and n.find(near) is not None
    d = n.dish((Ingredient(name=name, grams=200), Ingredient(name="rice", grams=100)))
    assert d.matched == 1 and d.unmatched == (name,) and d.totals["kcal"] == pytest.approx(365)
    line = describe(d)
    assert "partial" in line and f"not found: {name}" in line and "1 of 2 ingredients" in line


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
         "--food-nutrient", str(FIXTURES / "d_fdc_food_nutrient.csv"),
         "--nutrient", str(FIXTURES / "d_fdc_nutrient.csv"), "--out", str(out), *extra],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip


def test_the_converter_builds_the_subset_from_the_official_csv_shape(tmp_path: Path) -> None:
    r = _convert(tmp_path, "--allow-missing")
    assert r.returncode == 0, r.stderr
    data = json.loads((tmp_path / "subset.json").read_text())
    src = data["sources"]["usda_sr_legacy"]
    assert data["installed"] is True and src["licence"].startswith("CC0")
    assert len(src["sha256"]["food.csv"]) == 64 and src["region"] == "US"
    by_key = {f["key"]: f for f in data["foods"]}
    rice = by_key["rice"]
    assert rice["per100g"] == {
        "kcal": 365.0, "protein_g": 7.13, "fat_g": 0.66, "carb_g": 79.95,
        "fibre_g": 1.3, "sodium_mg": 5.0,
    }  # fmt: skip
    assert [1062, 1527.0] in rice["all"] and rice["source"] == "usda_sr_legacy"  # every value
    assert data["nutrients"]["1062"] == ["Energy", "kJ"]  # with its name and unit
    assert "chawal" in rice["names"]
    assert "chicken breast" in by_key  # mapped for non-veg kitchens too
    n = Nutrition.load(tmp_path / "subset.json")
    assert n.installed and n.find("chawal") is not None


def test_the_converter_fails_when_mapped_foods_are_missing_unless_allowed(tmp_path: Path) -> None:
    r = _convert(tmp_path)
    assert r.returncode == 1 and "not found in the FDC file" in r.stderr


def _strict(path: Path) -> dict[str, object]:
    def no_constants(word: str) -> object:
        raise ValueError(f"not JSON: {word}")

    data: dict[str, object] = json.loads(path.read_text(), parse_constant=no_constants)
    return data


def test_the_converter_never_writes_infinity_or_nan(tmp_path: Path) -> None:  # security L4
    nutrients = tmp_path / "food_nutrient.csv"
    rows = (FIXTURES / "d_fdc_food_nutrient.csv").read_text().splitlines()
    rows = [r for r in rows if not r.startswith('"1",')]  # rice's kcal, replaced below
    rows += ['"99","900001","1008","inf","","","","","","",""', '"98","900001","1003","nan"']
    nutrients.write_text("\n".join(rows) + "\n")
    out = tmp_path / "subset.json"
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--food", str(FIXTURES / "fdc_sample.csv"),
         "--food-nutrient", str(nutrients), "--out", str(out), "--allow-missing"],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    rice = {f["key"]: f for f in _strict(out)["foods"]}["rice"]  # type: ignore[attr-defined]
    assert rice["per100g"]["kcal"] is None  # inf is not a value
    assert rice["per100g"]["protein_g"] == 7.13  # a later nan row is skipped


def test_the_converter_says_so_when_a_csv_cannot_be_read(tmp_path: Path) -> None:
    food = tmp_path / "food.csv"
    food.write_text(
        '"fdc_id","data_type","description"\n"1","sr_legacy_food","' + "x" * 200_000 + '"\n'
    )
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--food", str(food),
         "--food-nutrient", str(FIXTURES / "d_fdc_food_nutrient.csv"),
         "--out", str(tmp_path / "o.json")],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 2 and "can't read" in r.stderr and "Traceback" not in r.stderr
