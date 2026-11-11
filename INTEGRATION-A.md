# INTEGRATION-A — R6.1 Part A: D7 "the dock fits every screen"

Branch `r6-1-a` (from `r6-1-i0`). Plan: `docs/plans/r6-1-architecture-guide.md`, decision 1 / D7.
Owner's observation (11 Nov 2026): with twenty panel tabs the dock overflowed on a small screen.

## What was built

A measured **"priority plus"** dock in a new console module, `console-dock.js` (180 lines):

- At every width the tabs keep their order; the ones that do not fit **fold into the existing More
  sheet**, last tabs first. Nothing scrolls sideways anywhere (the R6 I0 `overflow-x:auto`, its
  mouse-wheel handler and the `scrollIntoView` on open are removed).
- **More** shows only while a tab is folded (it starts `hidden` in the markup). It lights up
  (`.on`, the existing pressed look) while a folded panel is open, and its accessible name says
  which: `More panels, Vitals shown` (desktop: every open folded panel, comma-separated).
- **The sheet lists exactly the folded tabs, in dock order** (entries for tabs that show are
  `hidden`). Four entries were added so every foldable tab has one: Activity, History, Memory,
  Integrations (same markup and icons as their tabs; one-line descriptions).
- **Pinned:** Chat, Brief and Approvals never fold (`PINNED = 3`, the first three tabs). This is the
  approvals-badge choice: **Approvals is always visible**, so `#dockBadge` (the waiting count) is
  always on screen; More never needs to carry it. Three pinned tabs plus More fit a 320 px phone
  with room to spare.
- **Phones (< 900 px):** at most eight tabs in the bar, More included (`PHONE_MAX = 8`, the old
  rule as an upper bound), and each tab must be at least a 44 px touch target and as wide as its
  visible label. Result: 390 and 360 px show seven tabs + More (as before); 340 and 320 px show six
  + More (Integrations folds; before, 8 tabs of 39–41 px were below the 44 px gate rule).
- **Desktop:** every shown tab keeps its usual width (78/102 px; 66/88 px at 900–1180 px). Seen:
  1920 px all twenty fit (no More); 1440 px folds 5; 1366/1280 px fold 7; 1024 px folds 8.
- **Measuring:** against the *room the window gives the dock* — the dock's CSS `max-width`
  (`calc(100vw - 24px)`, desktop) or the window width (phone), less the dock's own padding and
  border — never the dock's current width, so folding cannot feed back into the measure. Natural
  sizes are read with every tab unfolded and the result is applied in the same task, before paint.
  Re-measured on window-width change (`ResizeObserver` on `<html>`, width changes only; `resize`
  fallback), `document.fonts.ready` + `loadingdone`, `jarvis:theme` (surface/theme), and the phone
  breakpoint; at most one `requestAnimationFrame` per change. Writes only what changed.
- **Keyboard/a11y:** DOM order unchanged (tabs, then More); folded tabs leave the tab order. Focus
  never falls to the page: a focused tab that folds hands focus to More; closing a folded panel
  (its close button or Esc) returns focus to More (`console-deck.js` `focusTab`); the sheet still
  returns focus to More on Esc/backdrop/Close; a More that disappears hands focus to the last tab;
  an open sheet that empties closes and focus lands on the chosen tab. `aria-expanded`,
  `aria-controls`, `aria-haspopup`, `aria-current` (open panels, now on desktop too) kept.
- **Desktop sheet placement:** the same `.sheet` look, centred at `min(960px, 100vw - 24px)` with
  two entries a row (≥ 900 px only). Phone sheet unchanged.
- **No `<dialog>` support:** nothing folds, More stays hidden, the dock wraps (`.no-sheet`).
- **Look:** no colour, font or size change; existing classes only (`.dk`, `.more`, `.on`, `.sheet`,
  `.sheet-item`). The global `[hidden]{display:none!important}` does the folding.

## Files

| File | Change |
|---|---|
| `src/jarvis/api/static/console-dock.js` | **new** — measure, fold, More, sheet, triggers |
| `src/jarvis/api/static/console-deck.js` | More/sheet/wheel/`scrollIntoView` code removed (630 → 592 lines); `focusTab` for focus return; `syncDock` only sets `aria-pressed` |
| `src/jarvis/api/static/console-deck.css` | sideways scroll and `ovf`/More display rules removed; desktop sheet placement; `.no-sheet` wrap |
| `src/jarvis/api/static/console.html` | `ovf` class removed from 13 tabs; More `hidden`; 4 sheet entries; `<script src="/static/console-dock.js" defer>` right after `console-deck.js` (798 lines) |
| `src/jarvis/api/console.py` | `console-dock.js` added to `APP_ASSETS` (served `no-store`, CSP `script-src 'self'` unchanged) |
| `tests/browser/test_dock_fit.py` | **new** — 10 widths × night/day + More/focus/resize/no-loop/badge tests |
| `tests/browser/test_ui_audit.py`, `tests/browser/ui_checks.py` | gate audits `#dock` and the open `#moreSheet` at 1280 px (desktop rules) and 320 px (phone rules, 44 px targets), night and day |
| `tests/test_console_assets.py`, `tests/test_media_console.py`, `tests/test_r6_wiring_seams.py`, `tests/browser/test_r51_dock.py`, `tests/browser/test_brief.py` | the assertions that pinned `ovf` / sideways scroll / 8 tabs at 340 px now pin the measured contract |

Gate refinements (documented in the files; every other check still runs on the dock and sheet):
1. The DOM probe treats the screen-reader clip pattern (`position:absolute` + `clip: rect(0 0 0 0)`
   / `clip-path: inset(50%)`) as not painted (the 320 px icon-only tabs' names were "hard clip").
2. The "third line" rule skips `.sheet-item` rows as it already skips `.bmopt` (a title plus a
   meaning that wraps on a phone, as since slice 8).
3. `FINISH_ANIMATIONS_JS` now repeats (≤ 4 rounds, style flushed between): finishing the 0.4 s theme
   token transition on `<html>` sets off a tab's own 0.2 s colour transition, which the single pass
   left half-way when the page's clock crawled (desktop + software WebGL on a busy runner) — the
   Chat tab then read 2.9:1 at 1280 px Day, mid-way from Night's ink. Settled, it is 5.2:1.

## For the integrator

- **No shared-file edits needed** (`api/app.py`, CI untouched).
- `console.html` is at **798 lines**; `tests/test_r6_wiring_seams.py` requires `< 800`. If another
  part adds lines to `console.html`, that limit is the first thing to collide.
- **Part D / D6 coverage:** `console-dock.js` is a new console module — the guide's component
  catalogue needs a card for it ("Dock fit", Layer 1, `src/jarvis/api/static/console-dock.js`,
  since R6.1), or `scripts/arch_coverage.py` will flag it.
- Old plans (`r2-memory-vault.md`, `r3-home-camera.md`, `r6-build-book.md`) still describe the
  `ovf` class as history; left as written.
- Observation, unchanged (owner rule): on 900–1180 px desktops the 66 px tabs are 1 px narrower
  than the APPROVALS / INTEGRATIONS labels (pre-existing since R5.1; identical in the "before" shot).

## Tests run

- Browser (Chromium, `/tmp/venv-c`): `test_dock_fit.py` 26 passed; `test_r51_dock.py`,
  `test_r6_seams.py`, `test_console.py`, `test_brief.py`, `test_memory.py` (+ dock-fit) 122 passed;
  full visual gate `test_ui_audit.py` (102, incl. the 4 new dock/sheet audits) + `test_book_lock_ui.py`
  (the other user of `FINISH_ANIMATIONS_JS`) 117 passed.
- Unit: 475 passed on 3.11 (`test_console_assets`, `test_media_console`, `test_r6_wiring_seams`,
  `test_r51_console_assets_linked`, `test_r6_seams`); 433 passed on 3.12 (the first two + linked).
- Not run here (2-CPU sandbox, other builders): the rest of the browser suite. Its tests open panels
  through `Console.open_panel` (tab, else More sheet), which already handles folded tabs.

Commands (only the touched files):
`JARVIS_BROWSER_TESTS=1 PYTHONPATH=$PWD/src /tmp/venv-c/bin/python -m pytest -q -m browser
tests/browser/test_dock_fit.py tests/browser/test_r51_dock.py tests/browser/test_r6_seams.py
tests/browser/test_console.py tests/browser/test_brief.py tests/browser/test_memory.py
tests/browser/test_ui_audit.py`, and `/tmp/venv-b/bin/pytest -q tests/test_console_assets.py
tests/test_media_console.py tests/test_r6_wiring_seams.py tests/test_r51_console_assets_linked.py
tests/test_r6_seams.py`; `ruff check` + `ruff format --check` on every touched Python file.

## Screenshots (orchestrator review, acceptance check 8)

Directory: `/tmp/claude-0/-home-claude/a2921599-8bfd-5e75-9772-28144202d9c3/scratchpad/dock-shots/`
(made by a scratchpad Playwright script, not committed). `dock-<w>-<surface>.png` is the bottom
110 px strip, `full-<w>-<surface>.png` the whole window, `sheet-<w>-<surface>.png` the open sheet.

- Dock strips: `dock-1920-night.png`, `dock-1920-day.png`, `dock-1440-night.png`,
  `dock-1440-day.png`, `dock-1280-night.png`, `dock-1280-day.png`, `dock-1024-night.png`,
  `dock-1024-day.png`, `dock-390-night.png`, `dock-390-day.png`, `dock-360-night.png`,
  `dock-360-day.png`, `dock-320-night.png`, `dock-320-day.png`
- Whole window: `full-1920-night.png`, `full-1920-day.png`, `full-1440-night.png`,
  `full-1440-day.png`, `full-1280-night.png`, `full-1280-day.png`, `full-1024-night.png`,
  `full-1024-day.png`, `full-390-night.png`, `full-390-day.png`, `full-360-night.png`,
  `full-360-day.png`, `full-320-night.png`, `full-320-day.png`
- More sheet open: `sheet-1280-night.png`, `sheet-1280-day.png`, `sheet-360-night.png`,
  `sheet-360-day.png`
- `probes.json`: per shot, the shown tabs with their widths and label widths.
- Before (R6 I0, for comparison): same names under `.../scratchpad/dock-before/`.
