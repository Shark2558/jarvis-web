# R6.1 Part D — integration notes

Branch `r6-1-d` from `r6-1-i0`. Plan `docs/plans/r6-1-architecture-guide.md`: D3, D6, decision 6,
the guide's contents and the acceptance checks 1, 2, 3 (for the guide) and 5.

## What was built

| File | What |
|---|---|
| `docs/architecture/JARVIS-Architecture.md` | D3: "JARVIS Architecture & Technology Guide", first edition **v6.1.1** (version line at the top, change log at the end). 12 sections as the plan lists them; 59 component cards (11 fields each); 14 figures linked by their fixed names (`[![Figure N. …](diagrams/<name>.png)](diagrams/<name>.svg)` plus a `*Figure N. …*` caption); technology table with the plan's 8 columns (35 rows); outside services and free limits; plan vs build and the release list; decisions log; data and privacy (every Firestore collection, Redis, the keyring purposes, retention); security; operations; costs (estimates in ₹); known limits; roadmap (R7 onward marked PLANNED, incl. the 11th skill "Health & Wellbeing", the Layer-2 vision engine and mobile as a wrapped console, decision 6); glossary. |
| `scripts/arch_coverage.py` | D6: the coverage, completeness and paperwork check and the CLI (standard library plus the R6 scrubber). |
| `scripts/arch_inventory.py` | D6 (R6.1 review fix): the code side, what the repository has (packages, console modules, Scheduler jobs, outside services, collections). Split out so each module stays under 400 lines. |
| `scripts/arch_files.py` | D6 (R6.1 review fix): the reverse check (every cited path and linked diagram file exists) and the secret scan. |
| `scripts/arch_coverage.json` | Its tables: settings and API hosts → outside services, the 14 diagram names. A new outside service is one line here. |
| `tests/test_arch_coverage.py` | 48 tests on small fixture repos and guides (a missing package, console module, Scheduler job, service, collection; matches only inside the right card field; a file never covers its package; a service only as an item of the list; cited paths and diagram files that don't exist; placeholders; unreadable files exit 2; an empty card field; a short tech row; wrong columns; a bad version line; no change log; a missing caption; the scan on text and SVG) and one test that runs the real guide. |

## How the check works

`python scripts/arch_coverage.py [--repo DIR] [--guide FILE] [--scan DIR]` (defaults: this checkout,
`docs/architecture/JARVIS-Architecture.md`, the guide's folder). Exit 0 pass, 1 problems (a plain
list), 2 no guide or a file that can't be read or parsed (bad UTF-8, a syntax error, a missing or
broken `arch_coverage.json`). With Part C's diagrams beside the guide: `OK - 49 packages/modules,
68 console modules, 2 Scheduler jobs, 28 outside services, 73 Firestore collections`.

- Packages and top-level modules: every directory under `src/jarvis/` holding a `.py` file (with
  or without `__init__.py`; `__pycache__` skipped) and `src/jarvis/*.py` → a card's "Where in the
  code" must name the package itself, `src/jarvis/<name>` or `src/jarvis/<name>/`. A file inside
  it (`src/jarvis/<name>/x.py`) does not count, and a prefix never counts for a longer name.
- Console modules: `src/jarvis/api/static/console*.js` → "Where in the code" (word boundaries).
- Scheduler jobs: `gcloud scheduler jobs create … <name>` in `deploy/*.sh`, with `$VAR` and
  `${VAR:-default}` resolved → a card's "Where in the code" (no longer anywhere in the catalogue).
- Outside services: `Settings` fields in `config.py` (AST) mapped by `service_fields`; a SecretStr
  or `*_key` / `*_token` / `*_secret` / `*_url` setting that maps to nothing fails. Plus API hosts
  in the code's string literals (not docstrings) mapped by `api_hosts`; an unknown `api.*`,
  `*.googleapis.com` or `*.internal` host fails → one ITEM of a card's "Outside services" list
  (`service_names`: split at top-level `,` `;` " and " " or ", the name before any bracket; no
  substring match, so "Redisplay" or "(as the Cloud Run account)" never count).
- Firestore collections: `{prefix}name` / `{self._p}name` / `_path("name"` / `*_COLLECTION = "name"`
  / `.collection("name")` / `.collection(f"{prefix}name")` in `src/jarvis/**/*.py` → a code span in
  a card's "Data it keeps".
- Reverse (`arch_files.py`): every code span in a card's "Where in the code" that is a path (has a
  `/`, a file extension, or is `Dockerfile` / `Makefile`; `*` globs must match) must exist; a bare
  name is looked up next to the path before it, then in `api/static/`, `api/`, `src/jarvis/` and
  the root. Every `diagrams/…` link in the guide, and an `.svg` and `.png` for each of the 14
  names, must exist in `docs/architecture/diagrams/`; no folder at all is one problem.
- Placeholders: `TBC`, `todo`, `...`, `…` (and `None` outside "Depends on", "Data it keeps" and
  "Outside services") count as empty fields.
- Secret scan: `jarvis.buildbook.gen.scrub` (`default_scrubber`, the R6 build book scrubber with
  its hashed name list) on `.md .markdy .svg .txt .json` under `docs/architecture/`. Secret shapes
  are checked on every raw line; the personal-data rules read an SVG's drawn words only (tags
  blanked, line numbers kept) and skip SHA-256 hashes. This answers Part C's INTEGRATION-C item 2:
  I ran the scan on Part C's `docs/architecture/` at `c251ff9` (all 14 diagrams, `exports.json`,
  `README.md`): 0 findings. Reports name file, line and kind, never the text.

## For the integrator

0. **Part D alone fails on one line, by design.** `r6-1-d` has no `docs/architecture/diagrams/`
   (Part C's). There the check prints exactly one problem, `diagram files: no diagrams/ folder
   next to the guide (Part C exports them)`, and `test_the_real_guide_passes` asserts exactly that
   one problem. Once C is merged it asserts no problem at all. I verified the full pass with the
   guide copied next to `origin/r6-1-c` @ `ae219fd`'s diagrams (all 14 `.svg` + `.png`): OK.
1. **CI step (I did not edit `ci.yml`).** Add to the `test` job, after the build book check, so it
   runs on every pull request (a new package anywhere must reach the guide, not only docs changes):
   ```yaml
         # R6.1 D6: the architecture guide covers every package, console module, Scheduler job,
         # outside service and Firestore collection; complete cards and rows; R6 secret scan
         - run: python scripts/arch_coverage.py
   ```
   `tests/test_arch_coverage.py::test_the_real_guide_passes` enforces the same thing inside
   `pytest -q`; the step gives the readable list.
2. **Part A (dock):** A adds `console-dock.js` (i1 note 22): add it to card **C01**'s "Where in
   the code" in the guide AFTER merging A (the reverse check now fails a cited file that doesn't
   exist, so it can't go in on `r6-1-d`). Any other new `console*.js`, package, collection or
   setting from A–C needs the same one-line update (B's `src/jarvis/about.py` → its card; B's
   `scripts/check_*.py` → C58 Delivery).
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
- Tick jobs that ride only the morning clock (Vitals poll, vault reminders, DigiLocker import, the
  sweeps of old data) run only 04:00–11:30 IST; with Home on, the systems check and book sealing
  also ride the 5-minute watchdog — recorded as a known limit.
- **No default monthly ₹ limit.** `billing/budget.py`: "Unset = no JARVIS limit (Anthropic's own
  spend limit stays the hard backstop)"; the console shows "No limit set". The guide now says so
  on page 1. If the owner wants a default (for example ₹500), that is a code change for a later
  release, not this guide.

## R6.1 review fixes (fixer pass, 11 Nov 2026)

All checked against the code on `r6-1-d`; paths relative to the repo root.

**Fact check (review-d-facts.md).** S1 morning window: only the Vitals poll, vault reminders,
DigiLocker import and data sweeps are morning-only; systems check and `book_seal`/`book_sweep` also
ride the watchdog (`api/r6_wiring.py:198-215`, `home/watchdog.py:80`). K1 the CLI prints and carries
on (`cli.py:87-92`). K2 `local_brain` URL and key sealed with the token key (`offline/store.py:2-7`;
C17, §6.2, §6.4, page 1). K3 Tavily 900 *credits*, searches and reads (`web/allowance.py:4-8,34-36`;
C20, §5.1, §5.2). K4 Secret Manager: R2 plan (`r2-memory-vault.md:916-919`, US$0.06 a version,
disabled count), 4 secrets always + up to 7 (`deploy/cloudrun.sh`) → ₹0–30 (C49, §5.1, §5.2, §9,
page 1). K5 `deploy` needs only test/firestore/browser; eval gate main-only and non-blocking
(`ci.yml:74-76,101-102`; Fig. 13, C59, §8). K6 C11 lists every watchdog job (`home_wiring.py:
225-241,319-338`, `camera/service.py:87`). K7 C21 up to two fast-tier calls (`people/research.py:
11-13`). K8 CSP `script-src 'self' 'wasm-unsafe-eval'` (`api/console.py:165-176`; §2.1, §7.4). K9
face attempts 72 h unknown / 7 days enrolled (`homebridge/retention.py:2-6,23-24`; C08, §6.1). K10
only the first passkey via a 5-minute sign-in (`permissions/service.py:5-7,15-17`; C52). Nits S5,
S16, S19 taken.

**10 more claims (sections the sample missed).** Correct: C05 voice allowance and prices
(`config.py:365-389` × 95.24); C12 30 days, swept by the tick (`undo/models.py:23`,
`api/brief.py:138-139`); C47 404/410 removes a browser (`webpush/service.py:7,40`); C48 Activity 7
days (`config.py:219-221`); C53 409 burns no proof (`privacy/service.py:17,60`); C55 amber at 80 % /
30 days (`config.py:279-284`); C57 45/10 minutes, 20 questions, 60 MB (`config.py:393-404`); §7.3 and
§8 the build account loses secret/database access, old pre-slice-5 revisions fail
(`cloudrun.sh:11-13,550-557`); §8 re-runs ask nothing, three flags ask again (`cloudrun.sh:19-26,
59-62,102-122`). **Wrong:** C40 quoted "the alarm could not be armed"; the real text is "JARVIS
couldn't arm your home at HH:MM: the laptop didn't answer." (`camera/alarm.py:331-351`) — fixed.
Also checked and right: C56 15 minutes / two checks (`health/tick.py:8-14`), C46 four languages
(`notify/terms.py:1-3`), certifi MPL-2.0 (`requirements.licences.json:27-29`); the §8 CI table was
imprecise (only the Phase 0 mock eval; pushes are to main only) — fixed.

**Plain-language read (review-d-plain.md).** Page 1 rewritten: one monthly total (about ₹110, plus
₹0–30 Secret Manager) with worst cases (web-search replies ₹300–1,200; listening ₹2.29 a minute after
54 free minutes, about ₹560 at 10 minutes a day; speech ₹2,857 per million characters after 900,000);
no limit until the owner sets one (₹1–₹1,00,000, `billing/budget.py:4-8,31-32`); Claude prepaid and
Vitals' red "out of credit" (`vitals/words.py:16`); the ₹1 budget alert only warns
(`cloudrun.sh:369-390`); who sees data (Anthropic, Gemini, Tavily, Google voice, Maps/YouTube,
Telegram, from §6.5); no backups (nothing in `deploy/`, `.github/` or `src/` makes one); what JARVIS
does not lock (conversations, memory, attachment text, audit: no cipher in `storage/sessions.py`,
`recall/store.py`, `documents/store.py`, `storage/audit.py`); no payment tool (grep: none); where
the laptop-offline alert arrives (`notify/ports.py:50,60`, `notify/policy.py:25-27`); passkey and
approval card explained; "approve from Telegram" reworded; "Owner: Mark XIII" explained (the
version line format is fixed, so it stays); R1/R2/R3 note moved to §7.1. §2.1's plain-words column
and C01 de-jargoned; "himself" → "yourself"; "Home Assistant version 2026.10"; every decisions-log
row dated (plan status dates); one wording for owner decision 10. Glossary: 59 terms added (slice,
both tokens, quota, free tier, billing account, Haiku/Sonnet/Opus, guest show, visual gate, fails
closed, prepaid credit and the rest of the reviewer's list) plus a pointer to §5.1 for tool names.

**Code review (review-cd-code.md, Part D items).** MEDIUM: jobs inside a card field; services as
list items with word boundaries; packages not covered by a sub-path; reverse check for cited paths
and diagram files. LOW: unreadable/unparsable files exit 2 (tables load safely at import); `TBC`,
`todo`, `...`, `None` placeholders; `*_key`/`*_token`/`*_secret` settings, packages without
`__init__.py` and `.collection(...)` literals detected; the `type: ignore` removed (typed tables,
`isinstance` narrowing). The `markdy_export.py` / `markdy_render.py` / `docs` job items are Part C's.

**Unverified (marked in the guide).** How soon Google sends the ₹1 budget e-mail; the Secret
Manager price is the R2 plan's 5 Nov 2026 figure.

## Tests run

- `tests/test_arch_coverage.py`: 48 passed on Python 3.11 and 3.12.
- `ruff check` and `ruff format --check` clean on the files I touched; `mypy --strict` clean on
  `scripts/arch_coverage.py`, `arch_files.py`, `arch_inventory.py`.
- `python scripts/arch_coverage.py`: on `r6-1-d` alone, the one expected problem (no `diagrams/`
  folder); with the guide next to Part C's diagrams (`origin/r6-1-c` @ `ae219fd`): OK, secret scan
  of the `.md`, `.markdy`, `.svg` and `.json` files clean.
