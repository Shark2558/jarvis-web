# R6.1 Part D — integration notes

Branch `r6-1-d` from `r6-1-i0`. Plan `docs/plans/r6-1-architecture-guide.md`: D3, D6, decision 6,
the guide's contents and the acceptance checks 1, 2, 3 (for the guide) and 5.

## What was built

| File | What |
|---|---|
| `docs/architecture/JARVIS-Architecture.md` | D3: "JARVIS Architecture & Technology Guide", first edition **v6.1.1** (version line at the top, change log at the end). 12 sections as the plan lists them; 59 component cards (11 fields each); 14 figures linked by their fixed names (`[![Figure N. …](diagrams/<name>.png)](diagrams/<name>.svg)` plus a `*Figure N. …*` caption); technology table with the plan's 8 columns (35 rows); outside services and free limits; plan vs build and the release list; decisions log; data and privacy (every Firestore collection, Redis, the keyring purposes, retention); security; operations; costs (estimates in ₹); known limits; roadmap (R7 onward marked PLANNED, incl. the 11th skill "Health & Wellbeing", the Layer-2 vision engine and mobile as a wrapped console, decision 6); glossary. |
| `scripts/arch_coverage.py` | D6: the coverage, completeness, paperwork and secret-scan check (≤ 400 lines, standard library plus the R6 scrubber). |
| `scripts/arch_coverage.json` | Its tables: settings and API hosts → outside services, the 14 diagram names. A new outside service is one line here. |
| `tests/test_arch_coverage.py` | 25 tests on small fixture repos and guides (a missing package, console module, Scheduler job, service, collection; an empty card field; a short tech row; wrong columns; a bad version line; no change log; a missing caption; the scan on text and SVG) and one test that runs the real guide. |

## How the check works

`python scripts/arch_coverage.py [--repo DIR] [--guide FILE] [--scan DIR]` (defaults: this checkout,
`docs/architecture/JARVIS-Architecture.md`, the guide's folder). Exit 0 pass, 1 problems (a plain
list), 2 no guide. Today: `OK - 49 packages/modules, 68 console modules, 2 Scheduler jobs, 28 outside
services, 73 Firestore collections`.

- Packages and top-level modules: `src/jarvis/*/__init__.py` dirs and `src/jarvis/*.py` → a card's
  "Where in the code" must name `src/jarvis/<name>` (a prefix never counts for a longer name).
- Console modules: `src/jarvis/api/static/console*.js` → "Where in the code".
- Scheduler jobs: `gcloud scheduler jobs create … <name>` in `deploy/*.sh`, with `$VAR` and
  `${VAR:-default}` resolved → anywhere in the catalogue.
- Outside services: `Settings` fields in `config.py` (AST) mapped by `service_fields`; a secret or
  `*_url` setting that maps to nothing fails. Plus API hosts in the code's string literals (not
  docstrings) mapped by `api_hosts`; an unknown `api.*`, `*.googleapis.com` or `*.internal` host
  fails → a card's "Outside services".
- Firestore collections: `{prefix}name` / `{self._p}name` / `_path("name"` / `*_COLLECTION = "name"`
  in `src/jarvis/**/*.py` → a code span in a card's "Data it keeps".
- Secret scan: `jarvis.buildbook.gen.scrub` (`default_scrubber`, the R6 build book scrubber with
  its hashed name list) on `.md .markdy .svg .txt .json` under `docs/architecture/`. Secret shapes
  are checked on every raw line; the personal-data rules read an SVG's drawn words only (tags
  blanked, line numbers kept) and skip SHA-256 hashes. This answers Part C's INTEGRATION-C item 2:
  I ran the scan on Part C's `docs/architecture/` at `c251ff9` (all 14 diagrams, `exports.json`,
  `README.md`): 0 findings. Reports name file, line and kind, never the text.

## For the integrator

1. **CI step (I did not edit `ci.yml`).** Add to the `test` job, after the build book check, so it
   runs on every pull request (a new package anywhere must reach the guide, not only docs changes):
   ```yaml
         # R6.1 D6: the architecture guide covers every package, console module, Scheduler job,
         # outside service and Firestore collection; complete cards and rows; R6 secret scan
         - run: python scripts/arch_coverage.py
   ```
   `tests/test_arch_coverage.py::test_the_real_guide_passes` enforces the same thing inside
   `pytest -q`; the step gives the readable list.
2. **Part A (dock):** if A adds `console-dock.js` (plan decision 1), add it to card **C01**'s
   "Where in the code" in the guide, or the check (and the real-guide test) fails. Any other new
   `console*.js`, package, collection or setting from A–C needs the same one-line update.
3. **Part B (versioning):** the guide's first line follows the standard (`Version v6.1.1 · 11 Nov
   2026, 11:43 IST · Release R6.1 · Status: Current · Owner: 🛠 Mark XIII`) and it ends with the
   change log, so B's version-line check should pass on it. The guide says the code is v6.1.0. If
   B's PR-title check lands in CI, Figure 13's caption may gain a line (Part C note 4).
4. **Part C (diagrams):** links use the fixed names; figure titles match C's `scene` titles at
   `c251ff9`. Nothing to do unless C renames a figure.
5. **Editing later:** edit the Markdown directly (the cards are plain tables). Bump the version
   line and add a change-log row for every published edit (workshop rules).

## Decisions I made (please confirm)

- **Card fields.** The plan's 11 fields are used exactly (`Name, What it does, Layer, Skill, Where
  in the code, Depends on, Data it keeps, Outside services, Cost (₹ a month), When it fails,
  Since`), because the plan is binding and D6 checks them. The technical-writer skill's card has
  "Where it runs" and "Safety controls" instead of "Layer/Skill/Outside services"; those are folded
  into "What it does" and "When it fails", and the security model (section 7) covers controls.
  The technology table's 8 columns are the same in the plan and the skill.
- **Releases vs risk levels.** Written as "R4 (v4.0.0)" and "R1 read / R2 reversible / R3
  irreversible" to avoid the shared letter.
- **Top-level modules** (`alerts.py`, `cli.py`, `config.py`, `keyring.py`, `logging.py`,
  `ticks.py`) are covered as well as packages.

## Unverified (marked *unverified* in the guide)

Why hosting moved from Render to Cloud Run; Cloud Logging retention and cost; the exact error
wording when Firestore is down; some vendor limits and prices beyond the free tiers (Cloud Run
over-use, Firestore and Secret Manager rates, Artifact Registry per GB, Tailscale's free plan,
Google Workspace API quotas, Porcupine's key). Costs are estimates from the plans and config
(₹0.17 a reply from the owner's Phase 0 run, ₹95.24 to the dollar).

## Found while writing (not changed: outside my scope)

- `CLAUDE.md` still says "Postgres + Redis, MCP for tools"; the code uses Firestore and direct REST
  tools behind the gateway (guide section 2.1 and 10).
- Long-term memory (`memory_shards`), conversations and the audit are not sealed with JARVIS's own
  keys (Google's encryption at rest only) — recorded as a known limit.
- Tick jobs that ride the morning clock (Vitals poll, vault reminders, DigiLocker import, book
  sealing) run only 04:00–11:30 IST — recorded as a known limit.

## Tests run

- `tests/test_arch_coverage.py`: 25 passed on Python 3.11 (`/tmp/venv-b`) and 3.12 (`/tmp/venv-12`).
- `ruff check` and `ruff format --check` clean on the files I touched; `mypy --strict
  scripts/arch_coverage.py` clean.
- `python scripts/arch_coverage.py`: OK (100 % coverage, complete cards and rows, scan clean).
