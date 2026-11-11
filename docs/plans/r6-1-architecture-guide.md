Version v6.1.1 · 11 Nov 2026, 11:20 IST · Release R6.1 · Status: Current · Owner: 🛠 Mark XIII

# R6.1 — The Architecture Guide & versioning (`v6.1.0`)

**Phase:** cross-cutting (Phase 7 quality: documentation, versioning, UI fit). **Type:** free, ₹0 to run.
**Why:** the owner's standing asks of 10 Nov (a real architecture guide written from the code by one
technical-writer agent, Markdy diagrams, one versioning standard incl. GitHub) and his 11 Nov
observation that the dock overflows on small screens.
**Branches:** I0 `r6-1-i0` → parts `r6-1-a` … `r6-1-d` → integration `r6-1-i1` → PR
`v6.1.0 · R6.1 The Architecture Guide & versioning · Mark XIII` (labels `release`, `Mark XIII`).
Every commit carries `JARVIS-Version: v6.1.0` and `JARVIS-Mark: XIII`.

## Deliverables

| # | Deliverable | Part | Done when |
|---|---|---|---|
| D1 | `.claude/agents/technical-writer.md` | C | the agent wrote D3 |
| D2 | Markdy diagram tooling: `docs/architecture/diagrams/*.markdy` + exported `.svg`/`.png`, `scripts/markdy_export.py`, `@markdy/cli@1.5.7` dev-only (`package.json` devDependency or `npx` pinned), CI `docs` job | C | `lint --strict` + `verify --quality showcase` pass for all 14 diagrams in CI |
| D3 | `docs/architecture/JARVIS-Architecture.md` — the JARVIS Architecture & Technology Guide, first edition `v6.1.1` | D | acceptance checks below pass |
| D4 | Versioning rollout: `jarvis.__version__` = `6.1.0`; on-screen version + build date (Vitals "About JARVIS" line); build book carries the version; version line + change log on every `docs/plans/*.md`; GitHub back-fill (`docs/github-backfill.tsv`, `scripts/github_backfill.sh`); `.github/pull_request_template.md`; CI PR-title check | B | tests + practice run list exactly the 21 rows |
| D5 | Publishing (project doc, reading copy, PDF, Drive backup) | orchestrator | owner can open all three |
| D6 | Coverage check `scripts/arch_coverage.py` + CI: fails a PR when a top-level package, console module, Scheduler job, outside service or Firestore collection is missing from the guide's component catalogue | D | the check fails on a fixture with a missing package |
| D7 | **The dock fits every screen** (owner, 11 Nov) | A | browser test: no sideways scroll and every panel reachable at 1920 … 320 px |

## Decisions

1. **D7 — "priority plus" dock.** Today (R6 I0) a desktop narrower than the 22 tabs scrolls the dock
   sideways; phones (< 900 px) move the `ovf` tabs behind **More**. From R6.1 the dock measures itself
   at every width: tabs keep their order, and the tabs that don't fit move into the existing More
   sheet (the phone's sheet, same look), last tabs first. **More** appears only when something is
   hidden and lights up when the open panel is behind it. No sideways scroll anywhere. Phones keep the
   "at most eight" rule as an upper bound. Re-measured on resize, font load and theme change (one
   `requestAnimationFrame` per change, no layout loop). Keyboard order and focus return are kept. The
   look is unchanged (owner rule: never change the aesthetics). `console-deck.js` stays ≤ 800 lines;
   if the dock logic grows, it moves to a new `console-dock.js` (≤ 400 lines).
2. **D4 — version source.** One place: `src/jarvis/__init__.py` `__version__` (and `pyproject.toml`),
   set to `6.1.0` in this release. The build date is the deploy's build time (an env/build-arg written
   by CI, falling back to "unknown" locally — never the request time). Shown read-only as
   "About JARVIS · v6.1.0 · built 11 Nov 2026" on the Vitals panel and returned by an existing
   unauthenticated-safe route only if it already exists; otherwise behind the owner's session.
3. **D4 — build book.** The book keeps its commit id (`RELEASE_ID` stays `^[0-9a-f]{7}$`, so sealed
   R6 books still open) and gains an optional `version` field (`v6.1.0`) shown next to it.
4. **D4 — back-fill runs where GitHub allows it.** The script is a practice run by default. This
   sandbox refuses `POST git/refs`; creating a Release with `target_commitish` creates its tag, so the
   script tries `POST releases` first and reports any refusal with the website steps. Row #27
   (`v6.0.0 · R6 The Build Book · Mark XII`, merge `37c3bfd`) is added to the brief's 20 rows.
5. **D2 — privacy.** `player: chrome: badge false`; never Markdy's share link or online playground;
   Markdy is never loaded in the console or the build book (esm.sh would break the CSP).
6. **D3 — recorded in the guide:** the 11th core skill "Health & Wellbeing" and a vision engine in
   Layer 2 (owner decision 10, safe default yes, from the 11 Nov plan); mobile as a wrapped console
   (Capacitor) rather than React Native, as a *planned* departure.

## Diagrams (fixed names, Part C draws them, Part D links them)

`01-context`, `02-layers`, `03-deployment`, `04-chat-turn`, `05-approvals-passkeys`, `06-voice-loop`,
`07-memory`, `08-vault-digilocker`, `09-brief-ticks`, `10-home-alarm`, `11-systems-vitals`,
`12-build-book-guest`, `13-release-flow`, `14-privacy-map` — each `docs/architecture/diagrams/<name>.markdy`
with `<name>.svg` and `<name>.png` beside it and a numbered caption in the guide.

## The guide's contents (D3)

1. One-page summary (what JARVIS does as built up to R6.1, cost a month in ₹, safety promises, where
   data lives). 2. The eight layers mapped to real components, with departures and why.
3. Component catalogue — one card per component, 11 fields (name, what it does in plain words,
   layer, skill, code location, depends on, data it keeps, outside services, cost ₹, failure
   behaviour, since release). Built from the code. 4. The 14 diagrams. 5. Technology table with
   columns Area | Technology | What it does (plain words) | Why we chose it | Alternatives we could use |
   Why not those (today) | Cost per month (₹) | Since; plus outside services and free limits, original
   plan vs as built, decisions log. 6. Data and privacy, security model, operations, costs, known
   limits and roadmap (planned items marked planned, incl. R7 mobile and the R8–R10 vision releases).
   Glossary. Version line at the top, change log at the end.

## Acceptance checks

1. Coverage 100 % (D6 script). 2. Every card has 11 fields; every tech row 8 cells (script).
3. Version line + change log on every `docs/plans/*.md` and the guide (script). 4. Every diagram
passes `lint --strict` and `verify --quality showcase`, has SVG + PNG and a caption (CI).
5. The R6 secret scanner passes on `docs/architecture/`. 6. A fresh reviewer checks 20 random claims
against the code: zero wrong. 7. A fresh reviewer acting as the non-technical owner answers "what does
JARVIS do, what does it cost, where is my data, what can it never do without me, what if the laptop
is off" from the first three pages. 8. The orchestrator looks at every exported diagram and at the
dock screenshots (desktop 1920/1440/1280/1024, phone 390/360/320, night and day).
9. Unit 3.11 + 3.12, ruff, mypy baseline, mock evals, full browser suite incl. the visual audit.

## Risks

- Markdy export needs Node + headless Chromium: the CI `docs` job runs only when `docs/architecture/**`
  changes; lint/verify are fast. Never blocks a deploy of main.
- The repository is public: the guide, diagrams and back-fill hold no chat links, personal e-mails,
  phone numbers or keys.
- Dock measuring can loop if hiding a tab changes the dock's width: measure against the available
  width (window minus the dock's own padding), never against its current width.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.1.1 | 11 Nov 2026, 11:20 IST | R6.1 | First edition: D1–D7, decisions, diagram names, acceptance checks | 🛠 Mark XIII |
