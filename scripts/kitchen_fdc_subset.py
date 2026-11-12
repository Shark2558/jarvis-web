#!/usr/bin/env python3
# scripts/kitchen_fdc_subset.py
# ruff: noqa: E501 -- MAP and GROUPS are tables, one food or one group a line
"""Build the kitchen's nutrition subset (docs/plans/r11-free-helpers.md D15, item 14; R11 I1) from
the OFFICIAL USDA FoodData Central SR Legacy CSV download, and commit the output:

    unzip FoodData_Central_sr_legacy_food_csv_2018-04.zip -d fdc
    python3 -I scripts/kitchen_fdc_subset.py --dir fdc/<the folder holding food.csv> \
        --zip-name FoodData_Central_sr_legacy_food_csv_2018-04.zip --zip-sha256 <its sha256>

It reads `food.csv` (fdc_id, data_type, description, food_category_id), `food_nutrient.csv`
(fdc_id, nutrient_id, amount) and `nutrient.csv` (id, name, unit_name, rank). The foods are
(1) every food of `MAP` by its exact description, with its key and its Hindi, Malayalam and Odia
names, and (2) the raw foods an Indian kitchen uses, picked per FDC food category by `GROUPS`
(cereals and millets, pulses and dals, vegetables, fruits, nuts and seeds, spices and herbs,
dairy and eggs, oils and ghee, poultry, fish and seafood, meat, sugar and drinks). For each it
keeps EVERY nutrient the file reports, per 100 g (`all`: [nutrient id, amount]; names and units
once in `nutrients`), and the six key values (`per100g`: kcal 1008, protein 1003, fat 1004,
carbohydrate by difference 1005, total dietary fibre 1079, sodium 1093 mg). Each food carries
its `source` id; `sources` records the dataset, its region ("US"), the CC0 licence, the citation,
the zip's name and SHA-256 and each CSV's SHA-256. A mapped food that isn't found is listed on
stderr and the exit code is 1 (unless `--allow-missing`). FDC data is CC0 1.0 (public domain);
citation requested. Standard library only; run with `python3 -I` (the CSVs are untrusted data).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src/jarvis/helpers/kitchen/data/fdc_subset.json"
SOURCE_ID = "usda_sr_legacy"
KEY_NUTRIENTS = {
    1008: "kcal",
    1003: "protein_g",
    1004: "fat_g",
    1005: "carb_g",
    1079: "fibre_g",
    1093: "sodium_mg",
}
TYPES = ("sr_legacy_food", "foundation_food")  # preferred first
LABEL = "US reference values (USDA FoodData Central); Indian varieties and home recipes can differ."
CITATION = (
    "U.S. Department of Agriculture, Agricultural Research Service. FoodData Central. "
    "fdc.nal.usda.gov."
)
# (key, exact FDC description, other names "a|b|c": Hindi, Malayalam, Odia ... in Latin letters)
MAP: tuple[tuple[str, str, str], ...] = (
    ("rice", "Rice, white, long-grain, regular, raw, unenriched", "chawal|ari|chaula|basmati rice|white rice"),
    ("brown rice", "Rice, brown, long-grain, raw (Includes foods for USDA's Food Distribution Program)", "matta rice|red rice"),
    ("wheat flour", "Wheat flour, whole-grain (Includes foods for USDA's Food Distribution Program)", "atta|gehun ka atta|gotambu podi"),
    ("maida", "Wheat flour, white, all-purpose, enriched, bleached", "all purpose flour|plain flour"),
    ("semolina", "Semolina, enriched", "rava|sooji|suji"),
    ("oats", "Oats (Includes foods for USDA's Food Distribution Program)", "oat|rolled oats"),
    ("millet", "Millet, raw", "bajra|pearl millet|proso millet"),
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
    ("split pea", "Peas, green, split, mature seeds, raw", "matar dal|yellow split pea"),
    ("tofu", "Tofu, raw, firm, prepared with calcium sulfate", "soya paneer"),
    ("onion", "Onions, raw", "pyaz|pyaaz|savala|ulli|piaja"),
    ("tomato", "Tomatoes, red, ripe, raw, year round average", "tamatar|thakkali|bilati baigana"),
    ("potato", "Potatoes, flesh and skin, raw", "aloo|alu|urulakizhangu|batata"),
    ("sweet potato", "Sweet potato, raw, unprepared (Includes foods for USDA's Food Distribution Program)", "shakarkandi|madhurakizhangu|kandamula"),
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
    ("apple", "Apples, raw, with skin (Includes foods for USDA's Food Distribution Program)", "seb"),
    ("papaya", "Papayas, raw", "papita|omakka|amruta bhanda"),
    ("guava", "Guavas, common, raw", "amrood|pera|pijuli"),
    ("pomegranate", "Pomegranates, raw", "anar|mathalanaranga|dalimba"),
    ("orange", "Oranges, raw, all commercial varieties", "santra|naranga|kamala"),
    ("grapes", "Grapes, red or green (European type, such as Thompson seedless), raw", "angoor|munthiri"),
    ("watermelon", "Watermelon, raw", "tarbooz|thannimathan|tarbhuja"),
    ("pineapple", "Pineapple, raw, all varieties", "ananas|kaithachakka|sapuri"),
    ("dates", "Dates, medjool", "khajoor|eenthapazham|khajuri"),
    ("raisins", "Raisins, dark, seedless (Includes foods for USDA's Food Distribution Program)", "kishmish|unakka munthiri"),
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
    ("chicken breast", "Chicken, broiler or fryers, breast, skinless, boneless, meat only, raw", "chicken|murgh|kozhi|kukuda"),
    ("chicken thigh", "Chicken, broilers or fryers, dark meat, thigh, meat only, raw", ""),
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
    # I1: more of an Indian kitchen, each checked against the SR Legacy file (11 Nov 2026)
    ("amaranth leaves", "Amaranth leaves, raw", "chaulai|cheera|marisa saga"),
    ("ridge gourd", "Gourd, dishcloth (towelgourd), raw", "turai|peechinga|janhi"),
    ("taro leaves", "Taro leaves, raw", "arbi patta|chembila|saru patra"),
    ("moong sprouts", "Mung beans, mature seeds, sprouted, raw", "sprouts|mulapicha cherupayar"),
    ("papad", "Papad", "appalam|pappadam|papadum"),
    ("coconut water", "Nuts, coconut water (liquid from coconuts)", "tender coconut|elaneer|daab"),
    ("buffalo milk", "Milk, indian buffalo, fluid", "bhains ka doodh|erumappaal"),
    ("buttermilk", "Milk, buttermilk, fluid, whole", "chaas|mattha|moru"),
    ("cottage cheese", "Cheese, cottage, creamed, large or small curd", ""),
    ("pistachio", "Nuts, pistachio nuts, raw", "pista"),
    ("walnut", "Nuts, walnuts, english", "akhrot"),
    ("flaxseed", "Seeds, flaxseed", "alsi|flax seeds"),
    ("pumpkin seeds", "Seeds, pumpkin and squash seed kernels, dried", "kaddu ke beej"),
    ("rice flour", "Rice flour, white, unenriched", "chawal ka atta|ari podi"),
    ("corn flour", "Corn flour, whole-grain, yellow", "makki ka atta|maize flour"),
    ("tapioca pearls", "Tapioca, pearl, dry", "sabudana|sago|chowari"),
    ("poha", "Rice, white, long-grain, parboiled, unenriched, dry", "parboiled rice|ukda chawal|puzhukkalari"),
    ("goat liver", "Lamb, variety meats and by-products, liver, raw", "kaleji"),
    ("chicken liver", "Chicken, liver, all classes, raw", "kozhi karal"),
    ("duck egg", "Egg, duck, whole, fresh, raw", "batakh ka anda|tharavu mutta"),
    ("sardine", "Fish, herring, Atlantic, raw", "mathi|chaala|herring"),
    ("pomfret", "Fish, pompano, florida, raw", "avoli|pompano"),
    ("tilapia", "Fish, tilapia, raw", "jilebi meen"),
    ("crab", "Crustaceans, crab, blue, raw", "kekda|njandu|kankada"),
    ("squid", "Mollusks, squid, mixed species, raw", "koonthal|calamari"),
    ("green tea", "Beverages, tea, green, brewed, regular", "hari chai"),
    ("tea", "Beverages, tea, black, brewed, prepared with tap water", "chai|chaya"),
    ("coffee", "Beverages, coffee, brewed, prepared with tap water", "kaapi"),
    ("brown sugar", "Sugars, brown", "khandsari"),
)  # fmt: skip

# (group, FDC food category ids, include regex, exclude regex): the raw foods of an Indian kitchen
GROUPS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("cereals and millets", ("20",), r"\b(raw|uncooked|dry|flour|crude)\b|^(Oats|Sorghum grain|Buckwheat$|Rye grain|Triticale$|Corn grain|Wheat, (durum|hard|soft|sprouted)|Semolina|Cornstarch|Arrowroot flour)",
     r"cooked|industrial|UNCLE BEN|self-rising|masa|tortilla|canned|restaurant|fresh-refrigerated|gluten-free|fortified|KAMUT|instant|chinese|japanese|Spaghetti|Macaroni|Pasta, whole grain|homemade|cake|Noodles, egg|spinach|vegetable|bolted|glutinous|Rye flour|Triticale flour|harina"),
    ("pulses and dals", ("16",), r"mature seeds, raw|^Lentils, raw|^Peanuts, all types, raw|^Papad|^Tofu, raw|^Soy flour|^Peas, green, split", r"canned|cooked|boiled|roasted|salted|meatless"),
    ("vegetables", ("11",), r", raw\b",
     r"canned|frozen|cooked|boiled|Seaweed|Alaska|Lambsquarters|Pokeberry|jew's ear|Fireweed|Nopales|Hawaii|Mountain yam|Arrowhead|Burdock|Cardoon|Chrysanthemum|Dock|Epazote|Fiddlehead|Hearts of palm|Mushroom, (oyster|enoki|maitake|chanterelle|morel)|Salsify|Sesbania|Swamp cabbage|Wasabi|leafy tips|Pumpkin, flowers|Grape leaves|Vinespinach|Yautia|Peppers, (hungarian|ancho|pasilla)|Cabbage, (savoy|japanese)|Kohlrabi|Jicama|Rutabagas|Parsnips|Turnip greens|Collards|Kale, scotch|Radishes, white icicle|Artichokes|Chicory|Endive|Escarole|Watercress|Brussels|Celeriac|Tomatillos|Tomatoes, (orange|yellow)|Beans, (kidney|navy|pinto), mature seeds, sprouted|Purslane|Borage|Butterbur|Kanpyo|Malabar|New Zealand"),
    ("fruits", ("9",), r", raw\b|^(Dates|Raisins|Figs, dried|Apricots, dried|Plums, dried \(prunes\), uncooked)",
     r"canned|frozen|juice|sweetened|cooked|stewed|Alaska|syrup|nectar|Acerola|Feijoa|Rowal|Sapote|Cherimoya|Durian|Groundcherries|Loganberries|Mammy|Nance|Natal|Oheloberries|Pitanga|Prickly|Quinces|Rose-apples|Roselle|Soursop|Breadfruit|Boysenberries|Crabapples|Elderberries|Huckleberries|Java-plum|Kumquats|Persimmons, native|Pummelo|Currants|peel|Plantains, yellow|dehydrated|Raisins, (golden|seeded)|Abiyuch|Carissa|Cloudberries|Candied|Pears, asian|Plums, wild"),
    ("nuts and seeds", ("12",), r"\b(raw|dried)\b|^(Nuts, almonds$|Nuts, pecans$|Nuts, walnuts, english$|Nuts, hazelnuts or filberts$|Seeds, flaxseed$)",
     r"roasted|salt|sweetened|toasted|canned|meal|defatted|butter|paste|flour|formulated|glazed|frozen|boiled|acorn|beechnut|butternut|hickory|ginkgo|pilinut|breadfruit|breadnut|sisymbrium|cottonseed|safflower|chestnuts|brazilnut|pinyon|coconut cream|walnuts, black"),
    ("spices and herbs", ("2",), r".", r"imitation|poultry seasoning|pumpkin pie|Seasoning mix|Mustard, prepared|Capers|Horseradish|Vinegar, (red wine|balsamic)|chervil|savory|marjoram|tarragon|sage|allspice"),
    ("dairy and eggs", ("1",), r"^Milk, (whole|reduced fat|lowfat|nonfat|buttermilk|goat|indian buffalo|sheep|canned, evaporated|dry, whole)|^Yogurt, (plain|Greek, plain)|^Cheese, (cottage, creamed|cheddar|mozzarella, whole milk|parmesan, grated|ricotta, whole milk|cream$)|^Butter, (salted|without salt)|^Butter oil|^Cream, fluid, (heavy|light|half)|^Cream, sour, cultured|^Egg, (whole|white|yolk), raw|^Egg, (duck|quail), whole, fresh, raw|^Whey, (acid|sweet), fluid",
     r"chocolate|flavor|fruit|imitation|substitute|sweetened|low sodium|frozen|cooked|fried|scrambled|poached|hard-boiled|protein fortified|calcium fortified|lactose|filled|shredded|low moisture|sliced|reduced fat \(Includes"),
    ("oils and ghee", ("4",), r"^Oil, |^Butter oil", r"industrial|PAM|ENOVA|hydrogenated|lecithin|babassu|sheanut|cocoa|tomatoseed|teaseed|nutmeg|apricot|Natreon|spray|flaxseed|corn, peanut, and olive|corn and canola|cupu assu|ucuhuba|oat|poppyseed|hazelnut|walnut|grapeseed|wheat germ|almond|avocado|safflower, salad or cooking, linoleic|sunflower, linoleic \(less"),
    ("poultry", ("5",), r"^Chicken, broilers? or fryers, .*meat only, raw|^Chicken, (liver|gizzard), all classes, raw|^Turkey, whole, meat only, raw|^Duck, domesticated, meat only, raw", r"with added solution"),
    ("fish and seafood", ("15",), r", raw\b",
     r"Alaska|roe|caviar|snail|Turtle|Frog|shark|eel|halibut, Greenland|seatrout|shad|monkfish|milkfish|croaker|anchovy|perch|trout, brook|crab, (dungeness|queen|alaska king)|oyster|mussel|scallop|mahimahi|striped|cod, Pacific|butterfish|catfish, channel, farmed"),
    ("meat", ("17", "13", "10"), r"^Game meat, goat, raw|^Lamb, ground, raw|^Lamb, (composite of trimmed retail cuts|leg, whole \(shank and sirloin\)|shoulder, whole \(arm and blade\)), separable lean only, trimmed to 1/4\" fat, choice, raw|^Lamb, variety meats and by-products, (liver|kidneys|heart), raw|^Beef, ground, (80|90)% lean meat / (20|10)% fat, raw|^Pork, fresh, ground, raw", r"^$"),
    ("sugar and drinks", ("19", "14"), r"^Sugars?, (granulated|brown|powdered|turbinado)|^Honey$|^Molasses$|^Beverages, (tea, (black|green), brewed, (prepared with tap water|regular)$|coffee, brewed, prepared with tap water$)", r"^$"),
)  # fmt: skip
GROUP_OF = {cat: name for name, cats, _, _ in GROUPS for cat in cats}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_foods(food_csv: Path) -> dict[int, tuple[str, str]]:
    """fdc_id -> (description, food category id), SR Legacy / Foundation rows only."""
    out: dict[int, tuple[str, str]] = {}
    with food_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("data_type") or "") not in TYPES:
                continue
            try:
                fid = int(row.get("fdc_id") or "")
            except ValueError:
                continue
            out[fid] = (
                (row.get("description") or "").strip(),
                (row.get("food_category_id") or "").strip(),
            )
    return out


def by_description(foods: dict[int, tuple[str, str]]) -> dict[str, int]:
    """description (case-folded) -> fdc_id, the lowest id on a tie."""
    best: dict[str, int] = {}
    for fid in sorted(foods):
        best.setdefault(foods[fid][0].casefold(), fid)
    return best


def read_nutrient_names(path: Path | None) -> dict[int, tuple[str, str, float]]:
    """nutrient id -> (name, unit, rank) from nutrient.csv (empty without the file)."""
    out: dict[int, tuple[str, str, float]] = {}
    if path is None:
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                nid = int(row.get("id") or "")
                rank = float(row.get("rank") or "inf")
            except ValueError:
                continue
            name, unit = (
                (row.get("name") or "").strip()[:80],
                (row.get("unit_name") or "").strip()[:12],
            )
            if name and unit:
                out[nid] = (name, unit, rank if math.isfinite(rank) else 1e9)
    return out


def read_amounts(path: Path, ids: set[int]) -> dict[int, dict[int, float]]:
    """fdc_id -> {nutrient id: amount per 100 g}: finite, not negative; the first row wins."""
    out: dict[int, dict[int, float]] = {i: {} for i in ids}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                fid, nid = int(row.get("fdc_id") or ""), int(row.get("nutrient_id") or "")
                amount = float(row.get("amount") or "")
            except ValueError:
                continue
            if fid in out and math.isfinite(amount) and amount >= 0:
                out[fid].setdefault(nid, round(amount, 3))
    return out


def head_name(desc: str) -> str:
    """'Kale, raw' -> 'kale': the description's first part, a name he may type."""
    return re.sub(r"\s*\(.*?\)", "", desc.split(",")[0]).strip().casefold()


def plain(desc: str) -> str:
    """The description as a name: case-folded, without FDC's distribution-program note."""
    return re.sub(
        r"\s*\(includes foods for usda's food distribution program\)", "", desc.casefold()
    ).strip()


def stem(name: str) -> str:
    """'Carrots' and 'carrot' are one name (the app's lookup drops a plural too)."""
    return re.sub(r"(?<=[a-z])(es|s)$", "", name)


def select(foods: dict[int, tuple[str, str]]) -> tuple[list[tuple[int, str, list[str]]], list[str]]:
    """(fdc_id, key, names) for MAP's foods, then GROUPS' foods; and MAP's misses. A picked
    food's key is its first word(s) when no other food has them, else its whole description."""
    index, chosen, missing, seen = by_description(foods), [], [], set()
    for key, desc, names in MAP:
        fid = index.get(desc.casefold())
        if fid is None:
            missing.append(f"{key} ({desc})")
        elif fid not in seen:
            seen.add(fid)
            chosen.append((fid, key, [a for a in dict.fromkeys(names.split("|")) if a]))
    taken = {stem(k) for _, k, ns in chosen for k in (k, *ns)}
    picked = [
        fid for fid, (desc, cat) in sorted(foods.items()) if fid not in seen and _grouped(desc, cat)
    ]
    heads: dict[str, int] = {}
    for fid in picked:
        h = stem(head_name(foods[fid][0]))
        heads[h] = heads.get(h, 0) + 1
    for fid in picked:
        full, head = plain(foods[fid][0]), head_name(foods[fid][0])
        key = head if heads[stem(head)] == 1 and stem(head) not in taken else full
        chosen.append((fid, key, [] if key == full else [full]))
        taken.add(stem(key))
    return chosen, missing


def _grouped(desc: str, cat: str) -> bool:
    return any(
        cat in cats and re.search(inc, desc) and not re.search(exc, desc)
        for _, cats, inc, exc in GROUPS
    )


def food_entry(
    fid: int,
    key: str,
    names: list[str],
    foods: dict[int, tuple[str, str]],
    amounts: dict[int, float],
) -> dict[str, object]:
    desc, cat = foods[fid]
    return {
        "key": key,
        "source": SOURCE_ID,
        "fdc_id": fid,
        "description": desc,
        "group": GROUP_OF.get(cat, "other"),
        "names": names,
        "per100g": {short: amounts.get(nid) for nid, short in KEY_NUTRIENTS.items()},
        "all": [[nid, amounts[nid]] for nid in sorted(amounts)],
    }


def build(
    files: dict[str, Path | None], zip_name: str, zip_sha: str
) -> tuple[dict[str, object], list[str]]:
    food_csv, nutrient_csv = files["food.csv"], files["food_nutrient.csv"]
    assert food_csv is not None and nutrient_csv is not None
    foods = read_foods(food_csv)
    chosen, missing = select(foods)
    amounts = read_amounts(nutrient_csv, {fid for fid, _, _ in chosen})
    names = read_nutrient_names(files.get("nutrient.csv"))
    out_foods = [food_entry(fid, key, al, foods, amounts[fid]) for fid, key, al in chosen]
    used = sorted(
        {nid for a in amounts.values() for nid in a},
        key=lambda n: (names.get(n, ("", "", 1e9))[2], n),
    )
    source = {
        "id": SOURCE_ID,
        "region": "US",
        "dataset": "USDA FoodData Central, SR Legacy (April 2018 CSV download)",
        "licence": "CC0 1.0 (public domain)",
        "citation": CITATION,
        "label": LABEL,
        "file": zip_name,
        "file_sha256": zip_sha,
        "sha256": {k: sha256(v) for k, v in files.items() if v is not None},
        "converted": datetime.now(UTC).date().isoformat(),
        "mapped": len(MAP),
        "foods": len(out_foods),
    }
    data: dict[str, object] = {
        "about": "Per 100 g of the raw food, built by scripts/kitchen_fdc_subset.py. Do not edit.",
        "installed": True,
        "format": 2,
        "sources": {SOURCE_ID: source},
        "nutrients": {str(n): list(names[n][:2]) for n in used if n in names},
        "foods": out_foods,
    }
    return data, missing


def write(data: dict[str, object], out: Path) -> None:
    """Compact JSON, one food a line (small, and a change reads as a diff of foods)."""
    foods = data["foods"]
    assert isinstance(foods, list)
    head = {k: v for k, v in data.items() if k != "foods"}
    dump = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"), allow_nan=False)  # noqa: E731
    lines = [dump(f) for f in foods]
    out.write_text(
        dump(head)[:-1] + ',"foods":[\n' + ",\n".join(lines) + "\n]}\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument(
        "--dir", type=Path, help="the folder holding food.csv, food_nutrient.csv, nutrient.csv"
    )
    ap.add_argument("--food", type=Path, help="food.csv")
    ap.add_argument("--food-nutrient", type=Path, help="food_nutrient.csv")
    ap.add_argument("--nutrient", type=Path, help="nutrient.csv (the nutrients' names and units)")
    ap.add_argument("--zip-name", default="", help="the official zip's file name, recorded")
    ap.add_argument("--zip-sha256", default="", help="the official zip's SHA-256, recorded")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--allow-missing", action="store_true", help="write even if foods are missing")
    a = ap.parse_args(argv)
    food = a.food or (a.dir / "food.csv" if a.dir else None)
    amounts = a.food_nutrient or (a.dir / "food_nutrient.csv" if a.dir else None)
    names = a.nutrient or (a.dir / "nutrient.csv" if a.dir else None)
    if food is None or amounts is None or not food.is_file() or not amounts.is_file():
        print("give --dir, or --food and --food-nutrient (the official FDC CSVs)", file=sys.stderr)
        return 2
    if a.zip_sha256 and not re.fullmatch(r"[0-9a-f]{64}", a.zip_sha256):
        print("--zip-sha256 must be 64 hex digits", file=sys.stderr)
        return 2
    files = {
        "food.csv": food,
        "food_nutrient.csv": amounts,
        "nutrient.csv": names if names and names.is_file() else None,
    }
    try:
        data, missing = build(files, a.zip_name[:120], a.zip_sha256)
    except (csv.Error, UnicodeDecodeError) as exc:
        print(f"can't read the FDC CSV files ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 2
    for m in missing:
        print(f"not found in the FDC file: {m}", file=sys.stderr)
    if missing and not a.allow_missing:
        return 1
    write(data, a.out)
    print(f"wrote {a.out} ({len(data['foods'])} foods, {a.out.stat().st_size} bytes)")  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    sys.exit(main())
