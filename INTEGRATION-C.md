# INTEGRATION-C — R6.1 Part C: technical-writer agent, Markdy tooling, the 14 diagrams

Branch `r6-1-c` (from `r6-1-i0`). Plan: `docs/plans/r6-1-architecture-guide.md` D1, D2, decision 5,
"Diagrams".

## What was built

| Deliverable | Files |
|---|---|
| D1 agent | `.claude/agents/technical-writer.md` — the brief's text; frontmatter like the other agents (`name`, `description`, `tools`, `model: opus`) plus the shared Prompt Defense Baseline; a short "Tools you run" section for the export script |
| D2 dev-only tool | `tools/markdy/package.json` + `package-lock.json` — `@markdy/cli` 1.5.7 pinned exactly (48 packages, all MIT, `private: true`) |
| D2 script | `scripts/markdy_export.py` (388 lines) — privacy rule (`player: chrome: badge false`, no `share true`, no web address or e-mail in a source), `lint --strict`, `verify --quality showcase --json`, export, `exports.json` manifest, `--check`, `--lint-only`; `scripts/markdy_render.py` (149 lines) — headless Chromium via Python Playwright, the page and pinned modules served from `tools/markdy/node_modules` by a route, every other request blocked and reported |
| D2 tests | `tests/test_markdy_export.py` (44 tests) + `tests/markdy_fakes.py` (stub CLI and renderer): discovery, privacy rule, lint/verify reporting, export, idempotence, staleness (missing, source changed, export edited, other Markdy version, unreadable manifest), orphans, exit codes, the pinned version, dev-only boundaries, the CI job |
| D2 CI | `.github/workflows/ci.yml` job `docs` (see below) |
| Docker | `.dockerignore` gains `tools` and `**/node_modules` (the Dockerfile copies only `src`, `deploy/home` and the lock anyway) |
| git | `.gitignore` gains `tools/markdy/node_modules/` |
| Diagrams | `docs/architecture/diagrams/01-context … 14-privacy-map` (`.markdy` + `.svg` + `.png`), `exports.json`, `README.md` (numbered caption + one plain paragraph per figure, version line v6.1.1 · 11 Nov 2026, change log, Owner 🛠 Mark XIII) |

## How it is wired

- Run locally (sandbox): `npm ci --prefix tools/markdy` once, then
  `/tmp/venv-c/bin/python scripts/markdy_export.py [names]` (exports) or `--check` / `--lint-only`
  (any Python 3.11+, no browser). The CLI is run as `node tools/markdy/node_modules/@markdy/cli/dist/index.js`
  (its `.bin` link can exit 0 silently). Exit 0 ok, 1 a diagram problem (`<diagram>: <step>: <what>`),
  2 tools missing.
- Staleness is decided by `docs/architecture/diagrams/exports.json` (Markdy version + SHA-256 of each
  source, SVG and PNG), not file times. Exports are deterministic here (same bytes twice).
- CI job `docs`: `if: github.event_name == 'pull_request'`, no `needs`, not in deploy's `needs`, default
  read-only token; checkout (fetch-depth 0), setup-python 3.12, `actions/setup-node@249970729cb0ef3589644e2896645e5dc5ba9c38 # v6.5.0`
  (Node 22), `npm ci --prefix tools/markdy --ignore-scripts`. A PR that changes `docs/architecture/**`
  (git diff against `origin/$BASE_REF`; a git failure counts as changed) runs `--check`; any other PR
  runs `--lint-only`. Both lint + verify all 14 diagrams. No browser in CI: exports are made and looked
  at locally, CI only proves they match their sources (the plan's "needs headless Chromium" risk no
  longer applies to CI).
- Nothing Markdy-related reaches the app: `grep -ri markdy src/` is empty (pinned by
  `test_nothing_the_app_ships_mentions_markdy`, which also bans `esm.sh`); the console and the build
  book load no Markdy code.
- Build book: its Libraries & licences list comes from `requirements.lock` +
  `requirements.licences.json` and the console's vendored files only, so it does **not** gain Markdy
  (checked: a generated `book.json` has 70 libraries, none Markdy/html2canvas; pinned by
  `test_the_build_book_licence_list_does_not_gain_markdy`). The Stack section lists CI job names, so it
  gains `ci job: docs`. `source.zip` (the sealed code copy of every tracked file) now includes
  `tools/markdy/package*.json`, the `.markdy`/`.svg` files and the scripts; PNGs are left out as binaries.
  `python -m jarvis.buildbook.gen --check` passes on this branch (two builds byte-identical).

## For the integrator (shared files and other parts)

1. **ci.yml**: Part B also edits it (PR-title check). Both only add jobs; keep both. Keep `docs` out of
   deploy's `needs`.
2. **Part D's secret scan** (`scripts/arch_coverage.py` on `r6-1-d`, `SCAN_SUFFIXES` includes `.svg` and
   `.json`): the build-book scrubber flags `digits` (and sometimes `phone`) on SVG path coordinates and
   on the SHA-256 hashes in `exports.json` — false positives in generated files. Please scan only the
   human-written `.md` and `.markdy` under `docs/architecture/` (every word in an SVG comes from its
   `.markdy`), or skip `*.svg` and `exports.json`. With `.md`/`.markdy` only, the scan is clean today.
3. **Linking**: Part D checks for `diagrams/<name>.svg` + `*Figure N.` — fine. The PNG is the rendering
   that was looked at; the SVG uses the reader's system fonts, so text may sit slightly differently.
   The README embeds the PNG and links the SVG; the guide may do the same.
4. **Figure 13** shows CI as it is on `r6-1-i0` (+ `docs`). When Part B's PR-title check lands, add it
   to `13-release-flow.markdy` (e.g. `test Title "Title check" sub="version and Mark in the PR title"`
   and `PR -> Title "every time"`), run `python scripts/markdy_export.py 13-release-flow`, look at the
   PNG, and update the Figure 13 paragraph in `diagrams/README.md`.
5. **Pre-existing failure, not from Part C**: `tests/test_book_gen_determinism.py::test_the_real_repo_builds_and_the_show_is_about_six_thousand_characters`
   asserts the release label `R6`; the real label is now `R6.1` (fails identically on `r6-1-i0`). Part B
   (versioning) or I1 should update it.
6. Upgrading Markdy: bump `CLI_VERSION` in `scripts/markdy_export.py`, `tools/markdy/package.json` and
   the lock together (a test pins them equal), re-export every diagram and look at every PNG.

## Grounding (what each figure was drawn from)

01 `config.py`, `deploy/cloudrun.sh`, `api/`, `integrations/`, `web/`, `billing/fx.py`, `home/`, `offline/`;
02 `buildbook/gen/layers.py` + `buildbook/sections.py` LAYERS; 03 `deploy/cloudrun.sh` (asia-south1,
min 0 / max 1 instance, 512Mi, secrets, 2 Scheduler jobs), `ci.yml` deploy, `deploy/home`,
`deploy/local-brain/Caddyfile`, `docker-compose.yml` (Redis local only); 04 `buildbook/gen/flows.py`
chat_turn + `core/brain.py`, `llm/router.py`, `billing/service.py`, `tools/gateway.py`; 05 flow
approval + `tools/policy.py` (R1/R2 allow, R3 ask), `tools/gmail.py` (`gmail_send` R3),
`permissions/service.py`, `api/routes.py` approve, `telegram/service.py`; 06 flow voice_turn +
`api/voice.py`, `voice/*`, `static/console-wakeword.js`, `-barge.js`, `-micoff.js`, `-capture.js`;
07 flow learning + `recall/*`, `api/memory.py`; 08 flow vault_open + `vault/*`, `vault_inbox/*`,
`keyring.py`, `documents/isolation.py`, `api/vault.py`; 09 flow morning_tick + `api/brief.py`,
`ticks.py`, `app.py::_tick_jobs`, `home/watchdog.py`, `notify/policy.py`, `notify/ports.py`;
10 flow home_alert + `homebridge/*`, `home/webhook.py`, `home/signing.py`, `camera/events.py`,
`camera/alarm.py`, `deploy/home/docker-compose.yml`; 11 flow systems_check + `health/*`, `vitals/*`;
12 flow build_book + `buildbook/*`, `api/book_*.py`, `config.py` book limits; 13 `.github/workflows/ci.yml`;
14 `keyring.py` users (vault, kb, belongings, faces, home, camera, notify, webpush, places, offline,
integrations, buildbook), `recall/store.py`, `storage/*`, `llm/brains.py` + `recall/gate.py` (Gemini
free: no tools, no notes), `voice/*`, `webpush/ece.py`.

## Checks run

- `tests/test_markdy_export.py` (44, on 3.11 and 3.12), `tests/test_deploy_config.py tests/test_book_gen_cli.py
  tests/test_deploy_home.py tests/test_wakeword_assets.py` (3.11): 202 passed, 1 skipped.
- `tests/test_book_gen_libs.py tests/test_book_gen_snapshot.py tests/test_book_gen_code.py
  tests/test_r6_seams.py tests/test_book_gen_determinism.py`: all pass except the pre-existing label test (item 5).
- `ruff check` + `ruff format --check` clean on the new Python files; `mypy` (strict) clean on
  `scripts/markdy_export.py`, `scripts/markdy_render.py`, `tests/markdy_fakes.py`.
- `python scripts/markdy_export.py --check`: 14 diagrams, 0 problems (real CLI 1.5.7).
- `python -m jarvis.buildbook.gen --check`: passes.
- Every PNG opened and inspected; layouts reworked until no label was cut or hidden.

## The 14 PNGs to inspect

- `docs/architecture/diagrams/01-context.png`
- `docs/architecture/diagrams/02-layers.png`
- `docs/architecture/diagrams/03-deployment.png`
- `docs/architecture/diagrams/04-chat-turn.png`
- `docs/architecture/diagrams/05-approvals-passkeys.png`
- `docs/architecture/diagrams/06-voice-loop.png`
- `docs/architecture/diagrams/07-memory.png`
- `docs/architecture/diagrams/08-vault-digilocker.png`
- `docs/architecture/diagrams/09-brief-ticks.png`
- `docs/architecture/diagrams/10-home-alarm.png`
- `docs/architecture/diagrams/11-systems-vitals.png`
- `docs/architecture/diagrams/12-build-book-guest.png`
- `docs/architecture/diagrams/13-release-flow.png`
- `docs/architecture/diagrams/14-privacy-map.png`

## Unverified / known limits

- The CI `docs` job has not run on GitHub yet (YAML and job shape are tested locally).
- 09 (4160 px) and 03/08 (3600+ px) are wide; readable at full size, small if squeezed to page width.
- Markdy `annotation` lines did not appear in the still export, so no figure uses them.
- The SVG copies were not viewed with other fonts (e.g. on GitHub); the PNGs are the checked rendering.
