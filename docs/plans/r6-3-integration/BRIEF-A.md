Version v6.3.1 · 23 Nov 2026, 17:24 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3 — Part A brief: the fact pack and the generator (Opus)

Read `BRIEF-COMMON.md` first (the loop, the rules, the seams, the commands). Branch `r6-3-a` from
`origin/r6-3-i0`. Plan sections: D2, D2a, D2b, D3, D10's G3–G8 (and its check (3) kinds), the data
model's `facts.json` row, "The tour's facts" table under the script, the `facts` suite. CI-only,
standard library only, deterministic: **`--check` on the fixture and on the real repository after
every module.**

## 1. Your files (only these)

`src/jarvis/buildbook/gen/facts.py` and `gen/pages_index.py` (replace I0's stubs), `gen/loc.py`,
`gen/inventory.py` (new), changes to `gen/scrub.py` (the new kinds, phrases and domains),
`gen/plans.py` (G4), `gen/code.py` and `gen/libs.py` (G3, G5), `gen/costs.py` (G7),
`tests/test_r63_a_*.py`, `tests/r63_fakes_a.py`, `tests/test_r63_scrub_kinds.py` (turn it green and
remove its `xfail` marks: nothing else in it), `evals/r6_3/facts.py` (I0's stub: replace it),
`docs/plans/r6-3-integration/INTEGRATION-A.md`. You USE `gen/refs.py`, `gen/services.py`,
`gen/modules.py` and `buildbook/facts_model.py` and never edit them (BRIEF-COMMON section 3). Every
module ≤ 400 lines, functions ≤ 50.

## 2. Your contracts

- **`facts.build(repo, scrub) -> FactPack`** (the join calls it so; you may add keyword arguments
  with defaults, e.g. `modules=MODULES` so a fixture can bring its own module table). Leave
  `release` and `pages` unset: the join sets them. Every path SCRUBBED (`scrub.clean(path)`: 46
  Android paths hold the owner's handle, H6); the pack passes `Scrubber.verify` (the join checks).
  - `values`: every key of `facts_model.FACT_TOUR_KEYS` with the plan's sources and forms (the
    table under the script: `loc.python_code` in words, "124 thousand"; `seeme.inr_a_picture` "₹9";
    `tryon.measures` from the `Measure` Literal; `services.count` from `gen/services.inventory`,
    31; `roadmap.next` / `roadmap.after` the guide §11's first two rows, release and content in
    words, I0 refreshed them: R6.3.1 and R6.4); every literal module constant of `src/` as
    `path:NAME` (H5: a literal number, or arithmetic or a unary minus on literals; 1,461 in 506
    files at the plan); every `Settings` field as `settings.<name>` (its default); A's own
    (`cards.count`, `modules.count`, …); a hosting or security fact with `verified=False` (D2: C6's
    facts all False in R6.3).
  - `index`: every tracked path, every top-level function and class of `src/` as `path:symbol`,
    every constant, setting, collection and route (sorted, unique).
  - `routes` (M9): every module-level `APIRouter(...)` and `FastAPI(...)` under `src/jarvis/**`
    by AST, every route decorator on it whatever its name, every `add_api_route`, the router's
    `prefix=` joined. I0's stub routers (`api/book_writer.py`, `api/book_pages.py`) add routes in a
    loop from `writer/http.ROUTES`: read that table for them (a test compares your list with the
    app built with mock settings, with a control).
  - `modules` and `cards` from the guide (`gen/modules.guide_cards`, `modules.check`, the cards'
    fields) with each card's "Where in the code" resolved by `gen/refs.resolve` to full, scrubbed
    paths; `screens` (the 22 `id="p-*"` panels of `console.html` and the show, each with its
    `console-<panel>*.js` modules and route files); `services` (`gen/services.inventory(repo.root)`);
    `collections`; `settings` (179, with bounds); `loc` (D2a); `limitations` (ALL of them, G4).
- **`pages_index.build(repo, facts) -> tuple[IndexedPage, ...]`** (D3): in a fixed order, the 8
  chapters (`facts_model.CHAPTERS`, `pg_chapter_<id>`), the 18 modules (`pg_module_<id>`), the 73
  cards under their modules (`pg_card_c16`, `chapter` = the module id), the 22 screens and the show
  (`pg_screen_<id>`), the 31 services (`pg_service_<slug>`): 152 pages on 47ee8fc. Each page's
  `refs` full and scrubbed (a directory expanded to its files, for D12's change test) and
  `sources` (C-ids, plan paths). A reference that doesn't resolve is a `GenError`.
- **D2a `gen/loc.py`**: Python by `tokenize` (code, docstring, comment-only, blank), JS, CSS, HTML
  and Kotlin by a comment-aware scanner; source / tests / config / generated (vendored left out);
  each file under the one module that owns it; a test pins it on a fixture against a hand count.
  Scene 1's "about 206,413 lines" (raw newlines, G6) becomes the code count.
- **D2b `gen/inventory.py`**: Android (`android/gradle/libs.versions.toml`), the home kit's images
  (`deploy/home/docker-compose.yml`), the bridge's pins (`deploy/home/bridge-requirements.txt`),
  the dev tools (`tools/markdy/package-lock.json`, the `dev` extra); one SPDX spelling a licence; a
  run-time / build-and-maintenance split; into `book.json`'s `libraries` (its reader rows
  unchanged).
- **G3** the book's integrations are the coverage checker's 31 (`gen/services.inventory`), not
  15; **G4** every limitation into `facts.json` `limitations`, `book.json` keeps its first 80;
  **G7** costs: GitHub Actions on a public repository marked Unverified, Firestore's daily free
  reads, writes and deletes from `FREE_TIER`.
- **The scrubber's new kinds** (`gen/scrub.py`, D10 G8; pinned in `tests/test_r63_scrub_kinds.py`,
  `xfail(strict)` until you): `ipv4`, `ipv6`, `pan`, `aadhaar` (12 digits in groups of four, found
  before the plain digits rule), `host` under a listed domain (`Scrubber(redact, domains=…)`, a
  `domains` hash list in `redact.json`, empty today), `project_id`, and **M8's phrases**:
  `load_phrases(path)` reads `redact.json`'s `phrases` (I0 put four in: the owner's several-word
  names, SHA-256 of the words folded as `name_keys` folds them and joined by one space);
  `Scrubber(redact, phrases=…)` and `default_scrubber()` match them as consecutive words (any case,
  spacing or accent) and report `name`; their ordinary words alone stay. Versions, dates, line
  numbers and code paths stay as they are.
- **Determinism**: sorted everywhere; no set iterated unsorted; `--check` builds twice
  byte-identical with `facts.json`; `facts.json` ≤ 1 MiB (≈ 0.6 MB expected).
- **The fixture**: `tests/r63_fakes.FIXTURE_FACTS` is the pack your `facts.build` must compute for
  `r63_fakes.fixture_repo` (with its one-module table); if it is wrong, say so under "Needs I1"
  with the exact diff (the file is I0's; B builds on it).

## 3. Your rows and their named tests

| Row | Your test (what must hold) |
|---|---|
| 379 (your half) | `test_row379_facts_*`: every `path`, `path:symbol`, setting, collection and route a page may cite is in `facts.json`'s index, scrubbed; every number a page quotes is a `values` key (constants included) |
| 380 · grows (your half) | **`test_row380_a_new_card_gets_its_own_page_at_the_next_release`** (the pages-index half): a fixture guide with a C74 card placed in a module → `pg_card_c74` in that module's chapter, with its refs; a C74 in no module → the generator refuses (`GenError`). B proves the update's estimate counts it, C (and I1's e2e) that the reader lists it |
| 380 · tour (your half) | `test_row380_every_tour_key_is_known`: every key of `FACT_TOUR_KEYS` in `values` with the plan's value on this branch (73 cards, 18 modules, 11 others, 26 key purposes, 31 services, …) |

## 4. Your eval (`evals/r6_3/facts.py`) and its controls

Cases: the plan's `facts` row (`--check` twice identical with `facts.json`; every tour key known;
the module map has all 73 cards once; the index; the counter; the inventory's rows with SPDX names;
the scrubber's kinds and phrases found and versions left alone; the constants; every guide reference
resolved and every page's refs full and scrubbed; `facts.json` passes `Scrubber.verify` and every
Android page's references resolve (H6); 31 services (M7); the route list against the built app (M9);
G3's 31; G4's "+N more"). **Controls that must turn it red:** a set iterated unsorted in `facts.py`
(`--check` fails); the IP pattern removed; C69 removed from the map (the generator does not refuse:
the case fails); the raw path stored instead of the scrubbed one (H6); one router name dropped from
the scan (M9); and row 380 (grows)'s own: the pages index reading a fixed list instead of the guide
(C74 gets no page). Set `BUILT = True` only when every control fails its case.

## 5. Limits

No new setting, collection, route, job or keyring purpose; nothing at run time (CI only); no network.
`facts.json` is public package data: never a secret, a name or a place. INTEGRATION-A.md lists the
pack you build for the real repository (its counts and size), every deviation, "Needs I1".

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 17:24 IST | R6.3 | First edition, written at I0: Part A's files, contracts (the pack's fields and keys, the pages index, the counter, the inventory, G3, G4, G7, the scrubber's new kinds and M8's phrases, determinism, the fixture), its rows and named tests, the `facts` eval with its controls, limits | 🛠 Mark XXIV |
