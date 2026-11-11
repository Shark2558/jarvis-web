#!/usr/bin/env python3
# scripts/kitchen_fdc_subset.py
# ruff: noqa: E501 -- MAP is a table, one food a line
"""Build the kitchen's nutrition subset (docs/plans/r11-free-helpers.md D15, item 14) from the
OFFICIAL USDA FoodData Central CSV download. Run once, where fdc.nal.usda.gov can be reached
(the build sandbox can't), and commit the output:

    curl -LO https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip
    unzip FoodData_Central_sr_legacy_food_csv_2018-04.zip -d fdc
    python3 scripts/kitchen_fdc_subset.py --dir fdc/<the folder holding food.csv>

It reads `food.csv` (fdc_id, data_type, description, ...) and `food_nutrient.csv` (id, fdc_id,
nutrient_id, amount, ...), finds each food of `MAP` by its exact FDC description (SR Legacy
preferred, then Foundation; the lowest fdc_id on a tie), and writes per 100 g: energy kcal
(nutrient 1008), protein (1003), total fat (1004), carbohydrate by difference (1005), total
dietary fibre (1079) and sodium (1093, mg), plus the SHA-256 of each input file and the CC0
citation, to `src/jarvis/helpers/kitchen/data/fdc_subset.json`. A mapped food that isn't found is
listed on stderr and the exit code is 1 (unless `--allow-missing`): fix its description in MAP.

EVERY description in MAP is *unverified*: written from knowledge of SR Legacy's naming, not
checked against the file (the sandbox has no copy). FDC data is CC0 1.0 (public domain);
citation requested. Standard library only; runs with `python3 -I`.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src/jarvis/helpers/kitchen/data/fdc_subset.json"
NUTRIENT_IDS = {
    "1008": "kcal",
    "1003": "protein_g",
    "1004": "fat_g",
    "1005": "carb_g",
    "1079": "fibre_g",
    "1093": "sodium_mg",
}
TYPES = ("sr_legacy_food", "foundation_food")  # preferred first
CITATION = (
    "U.S. Department of Agriculture, Agricultural Research Service. FoodData Central. "
    "fdc.nal.usda.gov."
)
# (key, exact FDC description, other names "a|b|c": Hindi, Malayalam, Odia ... in Latin letters)
MAP: tuple[tuple[str, str, str], ...] = (
    ("rice", "Rice, white, long-grain, regular, raw, unenriched", "chawal|ari|chaula|basmati rice|white rice"),
    ("brown rice", "Rice, brown, long-grain, raw", "matta rice|red rice"),
    ("wheat flour", "Wheat flour, whole-grain", "atta|gehun ka atta|gotambu podi"),
    ("maida", "Wheat flour, white, all-purpose, enriched, bleached", "all purpose flour|plain flour"),
    ("semolina", "Semolina, enriched", "rava|sooji|suji"),
    ("oats", "Oats", "oat|rolled oats"),
    ("millet", "Millet, raw", "bajra|ragi|finger millet"),
    ("sorghum", "Sorghum grain", "jowar|cholam"),
    ("barley", "Barley, pearled, raw", "jau"),
    ("quinoa", "Quinoa, uncooked", ""),
    ("pasta", "Pasta, dry, enriched", "macaroni|spaghetti"),
    ("toor dal", "Pigeon peas (red gram), mature seeds, raw", "arhar dal|tuvar dal|red gram|thuvara parippu|harada dali"),
    ("masoor dal", "Lentils, pink or red, raw", "red lentil|masur dal"),
    ("lentil", "Lentils, raw", "whole masoor|brown lentil"),
    ("moong dal", "Mung beans, mature seeds, raw", "moong|green gram|cherupayar|muga dali"),
    ("urad dal", "Mungo beans, mature seeds, raw", "urad|black gram|uzhunnu|biri dali"),
    ("chana", "Chickpeas (garbanzo beans, bengal gram), mature seeds, raw", "chickpea|kabuli chana|kadala|chana dal|bengal gram|buta dali"),
    ("rajma", "Beans, kidney, red, mature seeds, raw", "kidney bean|red kidney bean"),
    ("lobia", "Cowpeas, common (blackeyes, crowder, southern), mature seeds, raw", "black eyed pea|vanpayar|chawli"),
    ("soybean", "Soybeans, mature seeds, raw", "soya bean"),
    ("split pea", "Peas, split, mature seeds, raw", "matar dal|yellow split pea"),
    ("tofu", "Tofu, raw, firm, prepared with calcium sulfate", "soya paneer"),
    ("onion", "Onions, raw", "pyaz|pyaaz|savala|ulli|piaja"),
    ("tomato", "Tomatoes, red, ripe, raw, year round average", "tamatar|thakkali|bilati baigana"),
    ("potato", "Potatoes, flesh and skin, raw", "aloo|alu|urulakizhangu|batata"),
    ("sweet potato", "Sweet potato, raw, unprepared", "shakarkandi|madhurakizhangu|kandamula"),
    ("garlic", "Garlic, raw", "lahsun|veluthulli|rasuna"),
    ("ginger", "Ginger root, raw", "adrak|inji|ada"),
    ("green chili", "Peppers, hot chili, green, raw", "hari mirch|pachamulaku|lanka|green chilli"),
    ("capsicum", "Peppers, sweet, green, raw", "shimla mirch|bell pepper"),
    ("spinach", "Spinach, raw", "palak|palanga saga|cheera"),
    ("cauliflower", "Cauliflower, raw", "gobi|phool gobi|kobi"),
    ("cabbage", "Cabbage, raw", "patta gobi|bandhakopi"),
    ("carrot", "Carrots, raw", "gajar"),
    ("eggplant", "Eggplant, raw", "brinjal|baingan|vazhuthananga|baigana"),
    ("okra", "Okra, raw", "bhindi|vendakka|bhendi|lady finger"),
    ("green peas", "Peas, green, raw", "matar|pattani|motor"),
    ("green beans", "Beans, snap, green, raw", "french beans|string beans"),
    ("bottle gourd", "Gourd, white-flowered (calabash), raw", "lauki|dudhi|churakka|lau"),
    ("bitter gourd", "Balsam-pear (bitter gourd), pods, raw", "karela|pavakka|kalara"),
    ("pumpkin", "Pumpkin, raw", "kaddu|mathanga|kakharu"),
    ("radish", "Radishes, raw", "mooli|mula"),
    ("beetroot", "Beets, raw", "beet|chukandar"),
    ("cucumber", "Cucumber, with peel, raw", "kheera|vellarikka|kakudi"),
    ("mushroom", "Mushrooms, white, raw", "khumb|koon"),
    ("sweet corn", "Corn, sweet, yellow, raw", "corn|makka|bhutta"),
    ("drumstick", "Drumstick pods, raw", "moringa|muringakka|sajana chhuin"),
    ("drumstick leaves", "Drumstick leaves, raw", "moringa leaves|muringa ila|sajana saga"),
    ("lettuce", "Lettuce, cos or romaine, raw", ""),
    ("cilantro", "Coriander (cilantro) leaves, raw", "dhania|kothamalli|dhania patra"),
    ("mint", "Spearmint, fresh", "pudina|pudina ila"),
    ("lemon", "Lemons, raw, without peel", "nimbu|cherunaranga|lembu"),
    ("banana", "Bananas, raw", "kela|pazham|kadali"),
    ("plantain", "Plantains, green, raw", "kacha kela|nendran|kancha kadali"),
    ("jackfruit", "Jackfruit, raw", "kathal|chakka|panasa"),
    ("mango", "Mangos, raw", "aam|manga|amba"),
    ("apple", "Apples, raw, with skin", "seb"),
    ("papaya", "Papaya, raw", "papita|omakka|amruta bhanda"),
    ("guava", "Guavas, common, raw", "amrood|pera|pijuli"),
    ("pomegranate", "Pomegranates, raw", "anar|mathalanaranga|dalimba"),
    ("orange", "Oranges, raw, all commercial varieties", "santra|naranga|kamala"),
    ("grapes", "Grapes, red or green (European type, such as Thompson seedless), raw", "angoor|munthiri"),
    ("watermelon", "Watermelon, raw", "tarbooz|thannimathan|tarbhuja"),
    ("pineapple", "Pineapple, raw, all varieties", "ananas|kaithachakka|sapuri"),
    ("dates", "Dates, medjool", "khajoor|eenthapazham|khajuri"),
    ("raisins", "Raisins, seedless", "kishmish|unakka munthiri"),
    ("coconut", "Nuts, coconut meat, raw", "nariyal|thenga|nadia|grated coconut"),
    ("coconut milk", "Nuts, coconut milk, raw (liquid expressed from grated meat and water)", "thengapaal|nadia kheera"),
    ("cashew", "Nuts, cashew nuts, raw", "kaju|andiparippu|kaju badam"),
    ("almond", "Nuts, almonds", "badam"),
    ("peanut", "Peanuts, all types, raw", "moongphali|nilakkadala|china badam|groundnut"),
    ("sesame", "Seeds, sesame seeds, whole, dried", "til|ellu|rasi"),
    ("tamarind", "Tamarinds, raw", "imli|puli|tentuli"),
    ("milk", "Milk, whole, 3.25% milkfat, with added vitamin D", "doodh|paal|dudha"),
    ("yogurt", "Yogurt, plain, whole milk", "curd|dahi|thairu|dahi"),
    ("butter", "Butter, salted", "makhan|venna|lahuni"),
    ("ghee", "Butter oil, anhydrous", "neyyu|ghia"),
    ("cream", "Cream, fluid, heavy whipping", "malai|fresh cream"),
    ("egg", "Egg, whole, raw, fresh", "anda|mutta|anda"),
    ("chicken breast", "Chicken, broilers or fryers, breast, meat only, raw", "chicken|murgh|kozhi|kukuda"),
    ("chicken thigh", "Chicken, broilers or fryers, thigh, meat only, raw", ""),
    ("mutton", "Game meat, goat, raw", "goat meat|gosht|aattirachi|chheli mansa"),
    ("lamb", "Lamb, ground, raw", "keema"),
    ("salmon", "Fish, salmon, Atlantic, farmed, raw", ""),
    ("tuna", "Fish, tuna, fresh, yellowfin, raw", "choora"),
    ("mackerel", "Fish, mackerel, Atlantic, raw", "bangda|ayala|ayila"),
    ("shrimp", "Crustaceans, shrimp, raw", "prawn|jhinga|chemmeen|chingudi"),
    ("coconut oil", "Oil, coconut", "velichenna|nadia tela"),
    ("mustard oil", "Oil, mustard", "sarson ka tel|sorisa tela"),
    ("sunflower oil", "Oil, sunflower, linoleic, (approx. 65%)", "refined oil"),
    ("groundnut oil", "Oil, peanut, salad or cooking", "peanut oil|kadala enna"),
    ("olive oil", "Oil, olive, salad or cooking", ""),
    ("sugar", "Sugars, granulated", "cheeni|panchasara|chini"),
    ("honey", "Honey", "shahad|then|mahu"),
    ("salt", "Salt, table", "namak|uppu|luna"),
    ("turmeric", "Spices, turmeric, ground", "haldi|manjal|haladi"),
    ("cumin", "Spices, cumin seed", "jeera|jeerakam|jira"),
    ("coriander seed", "Spices, coriander seed", "dhania seed|malli|dhania gunda"),
    ("chili powder", "Spices, chili powder", "lal mirch|mulaku podi|lanka gunda"),
    ("black pepper", "Spices, pepper, black", "kali mirch|kurumulaku|gol maricha"),
    ("mustard seed", "Spices, mustard seed, ground", "rai|kaduku|sorisa"),
    ("cardamom", "Spices, cardamom", "elaichi|elakkaya|aleicha"),
    ("cinnamon", "Spices, cinnamon, ground", "dalchini|karuvapatta"),
    ("clove", "Spices, cloves, ground", "laung|grambu|labanga"),
    ("fenugreek", "Spices, fenugreek seed", "methi|uluva|methi gunda"),
    ("fennel", "Spices, fennel seed", "saunf|perinjeerakam|panamadhuri"),
    ("vinegar", "Vinegar, distilled", ""),
)  # fmt: skip


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_foods(food_csv: Path) -> dict[str, int]:
    """description (case-folded) -> fdc_id, SR Legacy preferred, lowest id on a tie."""
    wanted = {d.casefold() for _, d, _ in MAP}
    best: dict[str, tuple[int, int]] = {}
    with food_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            desc = (row.get("description") or "").strip().casefold()
            kind = row.get("data_type") or ""
            if desc not in wanted or kind not in TYPES:
                continue
            try:
                fid = int(row.get("fdc_id") or "")
            except ValueError:
                continue
            rank = (TYPES.index(kind), fid)
            if desc not in best or rank < best[desc]:
                best[desc] = rank
    return {d: r[1] for d, r in best.items()}


def read_nutrients(path: Path, ids: set[int]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {i: {} for i in ids}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = NUTRIENT_IDS.get(row.get("nutrient_id") or "")
            if name is None:
                continue
            try:
                fid, amount = int(row.get("fdc_id") or ""), float(row.get("amount") or "")
            except ValueError:
                continue
            if fid in out and amount >= 0:
                out[fid][name] = round(amount, 2)
    return out


def build(food_csv: Path, nutrient_csv: Path) -> tuple[dict[str, object], list[str]]:
    found = find_foods(food_csv)
    values = read_nutrients(nutrient_csv, set(found.values()))
    foods, missing = [], []
    for key, desc, names in MAP:
        fid = found.get(desc.casefold())
        if fid is None:
            missing.append(f"{key} ({desc})")
            continue
        per = {n: values[fid].get(n) for n in NUTRIENT_IDS.values()}
        alias = [a for a in dict.fromkeys(names.split("|")) if a]
        foods.append(
            {"key": key, "fdc_id": fid, "description": desc, "names": alias, "per100g": per}
        )
    source = {
        "dataset": "USDA FoodData Central (SR Legacy / Foundation CSV download)",
        "licence": "CC0 1.0 (public domain)",
        "citation": CITATION,
        "sha256": {"food.csv": sha256(food_csv), "food_nutrient.csv": sha256(nutrient_csv)},
        "converted": datetime.now(UTC).date().isoformat(),
        "mapped": len(MAP),
        "found": len(foods),
    }
    about = "Per 100 g of the raw food, built by scripts/kitchen_fdc_subset.py. Do not edit."
    return {"about": about, "installed": True, "source": source, "foods": foods}, missing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--dir", type=Path, help="the folder holding food.csv and food_nutrient.csv")
    ap.add_argument("--food", type=Path, help="food.csv")
    ap.add_argument("--food-nutrient", type=Path, help="food_nutrient.csv")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--allow-missing", action="store_true", help="write even if foods are missing")
    a = ap.parse_args(argv)
    food = a.food or (a.dir / "food.csv" if a.dir else None)
    nutrient = a.food_nutrient or (a.dir / "food_nutrient.csv" if a.dir else None)
    if food is None or nutrient is None or not food.is_file() or not nutrient.is_file():
        print("give --dir, or --food and --food-nutrient (the official FDC CSVs)", file=sys.stderr)
        return 2
    data, missing = build(food, nutrient)
    for m in missing:
        print(f"not found in the FDC file: {m}", file=sys.stderr)
    if missing and not a.allow_missing:
        return 1
    a.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.out} ({data['source']['found']} foods)")  # type: ignore[index]
    return 0


if __name__ == "__main__":
    sys.exit(main())
