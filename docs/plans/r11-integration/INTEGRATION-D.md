Version v11.0.0 · 11 Nov 2026, 22:30 IST · Release R11 · Status: Current · Owner: 🛠 Mark XIV

# R11 Part D · Kitchen — integration note for I1

Branch `r11-d` (from `r11-i0` @ 0e2aec7). Items 13–16 of `docs/plans/r11-free-helpers.md` (D1, D15,
D16, D17, D18, D19, D20). Everything is in Part D's own files; no wiring file was edited.

## 1. What was built

| # | Item | Where | State |
|---|---|---|---|
| 13 | Recipes from what he has (veg / egg / non-veg, spice 0–3, oil 0–2, cuisines, a note) | `helpers/kitchen/recipes.py`, `diet.py` | Built. One balanced-tier call through `jarvis.llm` (`router.complete(tier=BALANCED, tools=None, max_tokens=700)`) on a brain that does NOT learn from what it is told (`brief.summarize.choose_brain`), after `billing.ensure_allowed`, recorded with `billing.record`. Pantry, cuisines, note and request words fenced (`wrap_external`); diet, spice and oil are fixed words. Reply must parse as one JSON recipe, else dropped; links, addresses and brackets removed. The CODE diet check (`diet.allows`) has the last word: an idea that breaks his diet is asked for once more, then refused, never shown. A request can only make the diet stricter. No-AI: his saved recipes that fit, with "The AI is off, Sir: these are from your saved recipes. New ideas need the AI switched on." and no provider call. No billing wired → no call (fail closed). |
| 14 | Nutrition per dish (USDA FoodData Central, CC0) | `helpers/kitchen/nutrition.py`, `data/fdc_subset.json`, `scripts/kitchen_fdc_subset.py` | Built; **data not installed**. A dish = Σ grams × per-100 g, "about", raw-ingredient basis, with attribution. The bundled file is a clearly marked empty subset (`"installed": false`), so every answer says "Nutrition data isn't installed yet, Sir (the USDA FoodData Central subset)." until I1 runs the converter (§3.3). |
| 15 | Grocery spend a month from e-mailed receipts | `helpers/kitchen/receipts.py`, `spend.py`, `store.py` | Built. Daily job `grocery_spend` (the morning tick's `helpers_daily`), `ctx.owners` only, OFF until he switches "Read my grocery receipts" on. Both his rows must ALLOW (`gmail_*` "Search and read email" and the Kitchen row `spend_*`); "Ask first", unreadable or unwired rows = skipped (fail closed). Fixed merchants (BigBasket, Blinkit, Zepto, Swiggy Instamart, JioMart, Amazon Fresh, Flipkart Minutes, DMart Ready, Country Delight, Milkbasket; domains *unverified*), Gmail's own DKIM/DMARC alignment via `packages.carriers.authenticated`, card numbers masked before parsing, strong total labels only, one order per keyed hash (order id via `packages.parse.find_order_id`), cancelled orders dropped (`packages.parse.detect_status`). Sealed (`spend`), totals per month, 13 months; a kind-only audit line. |
| 16 | Cooking and washing-up calendar blocks | `helpers/kitchen/blocks.py` | Built. `calendar_kitchen_blocks`, R2, `ask_when` always → an approval card even under "Allow"; card text by code; the approved card adds repeating events (`RRULE` daily or weekly on his days) on his primary calendar through the Calendar client's pieces (`CalendarAPI.owner_tz`, `EVENTS_URL`, `provenance.mark_outside` / `vouch`), no attendees, `sendUpdates=none`. The tab's button saves the plan and asks the gateway for the card; it never writes the calendar. Removing them is the calendar's own delete (a repeating event is R3 there). |

Also: `pantry.py` + `service.py` (one `KitchenService` for tools and routes), `tools.py` (`pantry_list` R1,
`pantry_add` / `pantry_remove` R2, `kitchen_settings` R2, `recipe_suggest` R1, `recipe_save` R2,
`recipe_list` R1, `nutrition_of` R1, `spend_month` R1; fixed Activity words on every one), `phrases.py`
(No-AI), `privacy.py` (`helpers_kitchen` confirm, `helpers_spend` passkey), `brief.py` (last month's
grocery total on the 1st), `part.py` (`build(ctx)`), `api/helpers_kitchen.py` (the tab's routes),
`console-helpers-kitchen.js` (the tab), `evals/r11_helpers/kitchen.py` (`BUILT = True`).

Security choices worth a reviewer's eye (recipes prompt, receipts):
- A diet change from a round that read other people's words is refused, and so is an approved card
  proposed from such a round (`content_tainted()` or `ToolContext.outside`): "Change your diet
  yourself in Helpers, Kitchen, Sir." (A tainted R2 call is already a card by the gateway.)
- Nothing from a mail is stored but the merchant's table name, the day and the amount; the subject,
  sender, items and order id never are (the order id only through the keyed hash). Logs carry class
  names and counts only; the audit detail is `mails= read= orders= ignored=`.
- Masking: 12–19-digit runs not glued to letters, and card-style 4-digit groups (spaces or dashes).
  Order ids such as `OD1234…` and Amazon's `402-1234567-1234567` survive (they key the order); a bare
  12+-digit order id is masked, so that order is keyed by its message (it may count twice if its
  shop sends two mails with totals).
- Heuristics, *unverified* on real mail: a cancel / refund / return mail drops that order's whole
  total (a refund for one item understates the month); a reply from the AI with a diet word in
  another case ("Veg") is read in lower case; promotions are never counted (no strong total label).
- No kitchen tool vouches for its output (`trusted_output` False): a round that read the pantry or
  a recipe stays "untrusted", so later writes in it are cards. Conservative; I1 may relax
  `pantry_list` / `spend_month` if the owner finds it noisy.

## 2. How to check it

```
/tmp/venv-12/bin/pytest -q -p no:cacheprovider tests/test_r11_d_*.py         # 157 passed
/tmp/venv-b/bin/pytest -q -p no:cacheprovider tests/test_r11_*                # 3.11; see §3.2 for 3
PYTHONPATH=src python evals/r11_helpers/run.py --mock --part kitchen          # 11/11; control fails
JARVIS_BROWSER_TESTS=1 PYTHONPATH=$PWD/src /tmp/venv-c/bin/python -m pytest -q tests/browser/test_r11_d_kitchen.py
python3 -I scripts/kitchen_fdc_subset.py --food tests/fixtures/r11/fdc_sample.csv \
  --food-nutrient tests/fixtures/r11/d_fdc_food_nutrient.csv --out /tmp/x.json --allow-missing
```

Coverage of `src/jarvis/helpers/kitchen/` + `api/helpers_kitchen.py`: 93 % (coverage.py over
`tests/test_r11_d_*.py`). Every module ≤ 400 lines, every function ≤ 50.

The eval's control `diet_check_off` (`diet.DIET_CHECK = False`) fails `kitchen:veg-chicken-refused`
and `kitchen:veg-asks-once-more`.

## 3. Needs I1

### 3.1 Ship the data file in the image (`pyproject.toml`)

The deploy installs non-editable (`pip install .`), so the JSON must be package data, or
`Nutrition.load()` finds no file (it then says "not installed", never fails):

```diff
 # R6 D3, D5: the generator's hashed name list and known fakes (the deploy job installs non-editable)
 "jarvis.buildbook.gen" = ["redact.json", "fake_secrets.txt"]
+# R11 D15: the kitchen's USDA FoodData Central subset (CC0), built by scripts/kitchen_fdc_subset.py
+"jarvis.helpers.kitchen" = ["data/*.json"]
```

### 3.2 Three I0 stub assertions in `tests/test_r11_wiring.py`

They pin the I0 stubs; every built part breaks them. Checked: with this diff the file passes on
this branch (12 passed).

```diff
@@ test_the_helpers_start_with_four_empty_parts_and_both_composites (l.68)
-        assert {p.ready for p in st.r11_parts.values()} == {"not built yet"}
+        assert "setup failed" not in {p.ready for p in st.r11_parts.values()}
@@ test_the_four_part_routers_are_stubs_under_their_own_prefix (l.241)
-        assert module.PREFIX == f"/v1/helpers/{part}" and module.router.routes == []
+        assert module.PREFIX == f"/v1/helpers/{part}"
+        assert all(r.path.startswith(module.PREFIX) for r in module.router.routes)
@@ test_a_parts_phrase_answers_in_no_ai_mode_through_its_tool (l.325)
-        assert a.state.brain_mode.phrases == (phrase,)
+        assert phrase in a.state.brain_mode.phrases
```

(`helpers_daily.job_names == ("helpers_sweep",)` at l.70 still holds: with no token key in that
test's settings the kitchen adds no `grocery_spend` job. With a key and Google it would be
`("grocery_spend", "helpers_sweep")`, and B's `breach_watch` before it.)

### 3.3 Fetch the USDA file once and commit the subset

Where `fdc.nal.usda.gov` is reachable (not the build sandbox):

```
curl -LO https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip
unzip FoodData_Central_sr_legacy_food_csv_2018-04.zip -d fdc
python3 -I scripts/kitchen_fdc_subset.py --dir fdc/FoodData_Central_sr_legacy_food_csv_2018-04
```

- File: **SR Legacy, CSV, April 2018**, `FoodData_Central_sr_legacy_food_csv_2018-04.zip` (the name
  and URL were read on fdc.nal.usda.gov/download-datasets on 11 Nov 2026; the folder name inside
  the zip is *unverified*: pass `--dir` the folder that holds `food.csv`).
- Files and columns read: `food.csv` → `fdc_id`, `data_type` (`sr_legacy_food`, or
  `foundation_food`), `description`; `food_nutrient.csv` → `fdc_id`, `nutrient_id`, `amount`.
  Nutrient ids: 1008 energy (kcal), 1003 protein (g), 1004 total fat (g), 1005 carbohydrate by
  difference (g), 1079 total dietary fibre (g), 1093 sodium (mg). Amounts are per 100 g.
- The script matches ~110 foods (with Hindi, Malayalam and Odia names) by their exact SR Legacy
  description; every description is *unverified*. A miss is listed on stderr and exits 1: fix the
  description in `MAP` (or run with `--allow-missing` and accept fewer foods). It records each input
  file's SHA-256, the CC0 licence and the citation in the output, and sets `"installed": true`.
- Commit `src/jarvis/helpers/kitchen/data/fdc_subset.json` (a few tens of KB). Licence row: data,
  not a dependency, so `requirements.licences.json` is unchanged; the guide may cite "USDA
  FoodData Central (CC0 1.0), bundled; no calls".

### 3.4 The guide's card C60 (`docs/architecture/`)

The kitchen is no longer PLANNED: `kitchen/{uid}` (sealed `kitchen`), `spend/{uid}_{yyyymm}` (sealed
`spend`, 13 months), `spend_scan/{uid}` (switch, last scan, keyed hashes) are written now. Its
"Outside services" already names Gmail, Google Calendar and Anthropic; no new host or setting was
added (`scripts/arch_coverage.py` passes on this branch). Suggested "What it does" words for D:
"recipe ideas from your pantry that keep to your diet (a code check decides), rough nutrition from
USDA FoodData Central, grocery spend a month from your e-mailed receipts, and cooking and
washing-up times in your calendar after you approve the card".

### 3.5 Persona p11.0 (D22), optional

Add to `HELPERS_RULE`: "A recipe idea always keeps to his diet; the kitchen's own check decides,
and you never offer a dish it refused."

## 4. Owner checks (after deploy)

1. **Set your diet** in Helpers → Kitchen (default vegetarian, the safe one), and spice, oil, cuisines.
2. **Recipe ideas need Claude** (a brain that doesn't learn from what it's told): the free Gemini
   brain is never used for them (owner decision 3). About ₹0.9 an idea, against your monthly limit.
3. **Switch on "Read my grocery receipts"** if you want the monthly totals. Then tell the builder
   which shops' receipts were missed: every sender domain is *unverified* on real mail (as the
   parcels reader's were). Each morning it reads only those shops' mail, at most 60 messages.
4. **Your rows**: "Search and read email" and "Kitchen" must be Allow for the morning read;
   "Ask first" there means it skips (it can't ask you at 05:00).
5. **Calendar blocks**: press "Ask to add to my calendar", approve the card in Approvals, check the
   events. Delete them from the calendar if you change your mind (Recently deleted keeps a copy).
6. **Nutrition**: once I1 installs the USDA subset, spot-check one dish (e.g. dal): values are
   rough, raw-ingredient, per the grams you give.

## 5. Decisions and departures (all inside Part D)

- Fixtures are `tests/fixtures/r11/d_receipt_*.eml` (BRIEF-COMMON's `d_` prefix, not the plan's
  `receipt_*.eml`), `fdc_sample.csv` (the shape of `food.csv`) and `d_fdc_food_nutrient.csv` (the
  official download has two CSVs, so the converter needs two). Made-up mail shapes, `example.com`
  recipients, the well-known test card number 4111 1111 1111 1111 planted in one.
- `service.py` and `pantry.py` added to the planned module list (one service for tools and routes).
- Receipts amounts above ₹1,00,000 are taken as misreads and dropped.
- `spend_month` and the brief line say "about" and name the shops from the fixed table only.
- The Kitchen tab never calls the AI: new ideas come from the chat ("what can I cook?").

## 6. TDD evidence

| Stage | Commit | Evidence |
|---|---|---|
| RED: diet, nutrition, receipts | 2a4d83a | collection failed: `jarvis.helpers.kitchen.receipts` (etc.) did not exist |
| GREEN | 4509226 | `tests/test_r11_d_{diet,nutrition,receipts}.py` 70 passed |
| RED: store, recipes, spend, blocks | 190d0e3 | collection failed: `...kitchen.blocks` (etc.) did not exist |
| GREEN | 69bdd90 | `tests/test_r11_d_*.py` 114 passed; mypy clean for the package |
| tools, part, routes (tests written first; RED = the modules absent at 69bdd90) | 3cba287 | 157 passed |
| tab, browser gate, eval | a0fd057 | browser 5 passed; eval 11/11, control fails 2 |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.0.0 | 11 Nov 2026, 22:30 IST | R11 | First edition: Part D built (items 13–16), how to check it, Needs I1 (package data, three I0 stub assertions, the USDA fetch, C60, persona), owner checks | 🛠 Mark XIV |
