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
- **A tab shows only while it holds its label with air beside it** (review A, H1/M1; fix round):
  - **Phones (< 900 px):** a tab needs `max(44, label + its borders + LABEL_CLEAR)` px, with
    `LABEL_CLEAR = 8` (More too). Tabs share the bar at `gap:0`, so two neighbouring labels are
    always ≥ 10 px apart (8 px of air + two 1 px borders); before, APPROVALS and ACTIVITY could touch.
  - **Desktop:** tabs keep their usual widths (78/102 px; 66/88 px at 900–1180 px — sizes, fonts and
    colours unchanged, owner rule). A tab whose label is wider than the tab (`ceil(label) + borders >
    width`, so "by even 1 px") **folds behind More wherever it sits**; the other tabs keep their
    order and the last ones fold first for room. With the dock's 4 px gap, neighbouring labels are
    then ≥ 6 px apart. At 900–1180 px this folds **Approvals, Integrations, Connectors, Construct**
    (labels 66.2/88.2/73.5/66.2 px in 66/88 px tabs); at ≥ 1181 px every label fits (Connectors 73.5
    in 78), so nothing changes there.
- **Pinned:** Chat, Brief and Approvals never fold *for lack of room* (`PINNED = 3`). The one
  exception is the rule above: on a 900–1180 px desktop the APPROVALS label overflows its 66 px tab,
  so Approvals moves behind More. Then **More carries the approvals badge**: console-dock.js moves
  the same `#dockBadge` element into More (console-deck.js keeps its count by id; same `.dk .badge`
  look) and More's name says it: `More panels, Approvals 3 waiting` (or `… Approvals could not load`).
  The sheet has an Approvals entry for this (hidden everywhere else). On a 900–1180 px desktop the
  left rail also shows "Approvals N waiting", and a fresh approval still opens its panel (More lit).
- **Phones:** at most eight tabs in the bar, More included (`PHONE_MAX = 8`, the old rule as an
  upper bound). Result now: 768 px seven tabs + More; **390 px six + More** (Integrations folds;
  was seven); **360 px five + More** (Memory and Integrations fold; was seven); 340 and 320 px six +
  More (icons only, names visually hidden: unchanged).
- **Desktop counts:** 1920 px all twenty fit (no More); 1440 px folds 5; 1366/1280 px fold 7;
  1024 and 900 px show Chat, Brief, Activity, History, Memory, Vault … (1024: twelve tabs + More;
  folded: Approvals, Integrations, Connectors, People, Book, Voice, Media, Construct).
- **The chat box's hint (orchestrator, 320 px screenshot):** "Message JARVIS" wrapped onto a cut
  second line in the 99 px chat box beside the attach, mic and send buttons. Now the hint never
  wraps (`.composer textarea::placeholder{white-space:nowrap}`, console-deck.css) and, where the full
  hint is wider than the box, console-dock.js sets the placeholder to **"Message"** (measured with the
  box's own font; re-read when the box changes width, e.g. a mic button appears, and on every
  refit). The box's label stays "Message JARVIS"; no font, size or colour change.
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
  `aria-controls`, `aria-haspopup`, `aria-current` (open panels, now on desktop too) kept. More's
  name lists every open folded panel in dock order (`More panels, Vitals, People shown`).
- **Desktop sheet placement:** the same `.sheet` look, centred at `min(960px, 100vw - 24px)` with
  two entries a row (≥ 900 px only). Phone sheet unchanged.
- **No `<dialog>` support:** nothing folds, More stays hidden, the dock wraps (`.no-sheet`).
- **Look:** no colour, font or size change; existing classes only (`.dk`, `.more`, `.on`, `.sheet`,
  `.sheet-item`). The global `[hidden]{display:none!important}` does the folding.

## Files

| File | Change |
|---|---|
| `src/jarvis/api/static/console-dock.js` | **new** — measure (label + air), fold, More, badge carry, sheet, chat-box hint, triggers (235 lines) |
| `src/jarvis/api/static/console-deck.js` | More/sheet/wheel/`scrollIntoView` code removed (630 → 592 lines); `focusTab` for focus return; `syncDock` only sets `aria-pressed` |
| `src/jarvis/api/static/console-deck.css` | sideways scroll and `ovf`/More display rules removed; desktop sheet placement; `.no-sheet` wrap; the hint's `white-space:nowrap` |
| `src/jarvis/api/static/console.html` | `ovf` class removed from 13 tabs; More `hidden`; 5 sheet entries (Approvals, Activity, History, Memory, Integrations); `<script src="/static/console-dock.js" defer>` right after `console-deck.js` (798 lines: the sheet's `<h2>` joined its `<div>` line to make room) |
| `src/jarvis/api/console.py` | `console-dock.js` added to `APP_ASSETS` (served `no-store`, CSP `script-src 'self'` unchanged) |
| `tests/browser/test_dock_fit.py` | **new** — 10 widths × night/day: fit, order, labels inside their tabs and ≥ 6 px apart, label-overflow folds, the chat-box hint whole on one line; More/focus/resize/no-loop; badge at 1280/1024/320; More's comma list |
| `tests/browser/test_ui_audit.py`, `tests/browser/ui_checks.py` | gate audits `#dock` and the open `#moreSheet` at 1280 and 1024 px (desktop rules) and 360 and 320 px (phone rules, 44 px targets), night and day; two negative tests of the narrowed exemptions |
| `tests/test_console_assets.py`, `tests/test_media_console.py`, `tests/test_r6_wiring_seams.py`, `tests/browser/test_r51_dock.py`, `tests/browser/test_brief.py`, `tests/browser/test_memory.py`, `tests/browser/test_console.py` | the assertions that pinned `ovf` / sideways scroll / 8 tabs at 340 or 390 px / Integrations in a 390 px bar now pin the measured contract |

Gate refinements (documented in the files; every other check still runs on the dock and sheet):
1. The DOM probe treats the screen-reader clip pattern as not painted **only on a 1 × 1 px box**
   (`position:absolute` + `width/height:1px` + `clip: rect(0 0 0 0)` / `clip-path: inset(50%)`; the
   320 px icon-only tabs' names were "hard clip"). The same clip on a full-size box is still
   measured: `test_only_one_pixel_visually_hidden_text_is_exempt_from_the_dom_checks` (a 160 px box
   clipped by mistake is reported as "hard clip"; the 1 px one is not). (Review A, M3.)
2. The "third line" rule holds a `.sheet-item` row to it **by its title**: only the meaning under it
   (`small`) may wrap. `test_a_more_sheet_row_is_held_to_the_third_line_rule_by_its_title` (a title on
   three lines is reported; a long meaning is not). (Review A, M2.)
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
- **Owner decision available (not taken):** on 900–1180 px desktops the 66/88 px tabs are narrower
  than the APPROVALS, INTEGRATIONS, CONNECTORS and CONSTRUCT labels, so those four now sit behind
  More there (Approvals' badge on More). Widening that media block to 70/92 px (a size change, so
  owner's call) would bring them back; the fit code needs no change for it.
- `console.html` stays at 798 lines (review A, L3): the Approvals sheet entry took one line and the
  sheet's `<div class="sheet-in">` and `<h2>` share one line to give it back.

## Review A follow-up (fix round)

| Finding | Done |
|---|---|
| H1 phone labels touch | `LABEL_CLEAR = 8`; phone need `max(44, label + borders + 8)`, More too; test: labels inside their tabs and ≥ 6 px apart at all 10 widths × 2 surfaces |
| M1 desktop labels overflow | a tab whose label overflows (even 1 px) folds behind More; no size change; test pins which fold at 900–1180 px and that none do at ≥ 1181 px |
| M2 `.sheet-item` exemption | title held to the rule, meaning only exempt; negative test |
| M3 clip exemption | 1 × 1 px only; negative test |
| L1 gate widths | `NARROW` adds 1024 px desktop and 360 px phone (dock + open sheet, night and day) |
| L2 comma list | `test_more_names_every_open_folded_panel_in_dock_order` (two panels opened out of order) |
| L3 798 lines | kept at 798 (see above) |
| Orchestrator: 320 px hint | "Message" where the full hint does not fit, never wraps; checked at every width in test_dock_fit.py |

## Tests run

- Fix round (review A): `test_dock_fit.py` 28 passed (new tests red first: labels at 1024/360,
  hint at 320, badge at 1024); `test_r51_dock.py`, `test_r6_seams.py`, `test_console.py`,
  `test_brief.py`, `test_memory.py`, `test_r51a_ui.py` 127 passed (two phone tests re-pinned from 8
  to 7 bar tabs at 390 px, then re-run green); full visual gate `test_ui_audit.py` (incl. 8 dock/sheet
  audits and the 2 negative tests, red first) + `test_book_lock_ui.py` 123 passed.
- Unit: 475 passed on 3.11 (`test_console_assets`, `test_media_console`, `test_r6_wiring_seams`,
  `test_r51_console_assets_linked`, `test_r6_seams`); 441 passed on 3.12 (the first two + linked).
- Not run here (2-CPU sandbox, other builders): the rest of the browser suite. Its tests open panels
  through `Console.open_panel` (tab, else More sheet), which already handles folded tabs.

Commands (only the touched files):
`JARVIS_BROWSER_TESTS=1 PYTHONPATH=$PWD/src /tmp/venv-c/bin/python -m pytest -q -m browser
tests/browser/test_dock_fit.py tests/browser/test_r51_dock.py tests/browser/test_r6_seams.py
tests/browser/test_console.py tests/browser/test_brief.py tests/browser/test_memory.py
tests/browser/test_r51a_ui.py tests/browser/test_ui_audit.py tests/browser/test_book_lock_ui.py`, and `/tmp/venv-b/bin/pytest -q tests/test_console_assets.py
tests/test_media_console.py tests/test_r6_wiring_seams.py tests/test_r51_console_assets_linked.py
tests/test_r6_seams.py`; `ruff check` + `ruff format --check` on every touched Python file.

## Screenshots (orchestrator review, acceptance check 8)

Directory: `/tmp/claude-0/-home-claude/a2921599-8bfd-5e75-9772-28144202d9c3/scratchpad/dock-shots/`
(made by a scratchpad Playwright script, not committed; re-taken after the review-A fix round and
looked at). `dock-<w>-<surface>.png` is the bottom 110 px strip, `full-<w>-<surface>.png` the whole
window, `sheet-<w>-<surface>.png` the open sheet, `badge-<w>-<surface>.png` the strip with 3
approvals waiting.

- Dock strips: `dock-1920-night.png`, `dock-1920-day.png`, `dock-1440-night.png`,
  `dock-1440-day.png`, `dock-1280-night.png`, `dock-1280-day.png`, `dock-1024-night.png`,
  `dock-1024-day.png`, `dock-390-night.png`, `dock-390-day.png`, `dock-360-night.png`,
  `dock-360-day.png`, `dock-320-night.png`, `dock-320-day.png`
- Whole window: `full-1920-night.png`, `full-1920-day.png`, `full-1440-night.png`,
  `full-1440-day.png`, `full-1280-night.png`, `full-1280-day.png`, `full-1024-night.png`,
  `full-1024-day.png`, `full-390-night.png`, `full-390-day.png`, `full-360-night.png`,
  `full-360-day.png`, `full-320-night.png`, `full-320-day.png`
- More sheet open: `sheet-1280-night.png`, `sheet-1280-day.png`, `sheet-1024-night.png`,
  `sheet-1024-day.png` (Approvals first), `sheet-360-night.png`, `sheet-360-day.png`
- Badge on More (Approvals folded at 1024 px): `badge-1024-night.png`, `badge-1024-day.png`
- The chat box's hint at 320 px: `full-320-night.png`, `full-320-day.png` ("Message", one line)
- `probes.json`: per shot, the shown tabs with their widths and label widths, and the hint.
- Before (R6 I0, for comparison): same names under `.../scratchpad/dock-before/`.
