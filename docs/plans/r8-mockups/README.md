# R8 / R8.1 mockups: the four new screens and the bar

Version v8.0.2 · 28 Nov 2026, 04:55 IST · Release R8 · Status: Draft · Owner: 🛠 Mark XXVI

Mockups only, for the owner's approval stop. No product code. They show where each new screen lives, what it says and
how it looks in every key state, in the console's own look (Workshop theme), Night and Day.

**Contact sheets:** [`contact-sheet.png`](contact-sheet.png) (screens 1 to 4, all 50 shots on one page) and
[`contact-sheet-bar.png`](contact-sheet-bar.png) (screen 5, the bar: 26 shots).

## Where they live (no new dock tab, ADR-35)

| Screen | Rows | Where | Opens from |
|---|---|---|---|
| 1. Camera setup | 217, 184, 377 | Camera panel, **Cameras** tab (extended) | Camera tab, or `?open=camera` |
| 2. Desk coach | 181, 224, 227, 238, 248, 262, 268, 276 | Camera panel, new **Desk** tab | Camera tab, or a new launch word `?do=desk` |
| 3. Workout session | R8.1's 20 rows | Camera panel, new **Workout** tab; a running session fills the phone screen | Camera tab on the phone, or a new launch word `?do=workout` |
| 4. Your day and screen time | 182, 183 (+ camera health, 217) | **Vitals**, a "Your day" card directly under "This month", then a "Cameras" health card | Vitals tab, or `?open=vitals` |
| 5. Your bar, your way (R8 part I) | the owner's ask of 28 Nov 2026, 04:33 IST | **The bar itself** (the dock on the laptop, the tab bar on the phone) and the **More** sheet; no new panel | More → "Edit the bar"; long-press a tab on touch |

Privacy rows for the new health results (184 and the kept counts) use the existing Privacy panel pattern; no mockup.

## Files

| File | What it is |
|---|---|
| `camera-setup.html` | Screen 1. `?v=laptop\|phone&s=night\|day&st=first\|active\|off\|warn\|error\|check` |
| `desk-coach.html` | Screen 2, laptop only (the desk camera is on the laptop). `?s=…&st=first\|active\|off\|warn\|error\|bp\|game` |
| `workout-phone.html` | Screen 3, phone only (390 × 844). `?s=…&st=first\|active\|off\|warn\|error` |
| `activity-timeline.html` | Screen 4. `?v=laptop\|phone&s=…&st=first\|active\|off\|warn\|error` |
| `bar-edit.html` | Screen 5, the bar. `?v=laptop\|phone&s=…&st=today\|edit\|drag\|tomore\|removed\|hidden\|keyboard` (the phone has no `tomore`) |
| `png/` | 76 screenshots, named `<screen>-<page>-<view>-<state>-<theme>.png` (screen 5: `5-bar-edit-<device>-<state>-<theme>.png`) |
| `contact-sheet.png` | every shot of screens 1 to 4 on one sheet |
| `contact-sheet-bar.png` | every shot of screen 5 on one sheet |
| `tools/kit.py` | copies the console's own CSS (`console.css`, `console-deck.css`, `console-memory.css`, `console-helpers.css`, `console-vitals.css`, `console-camera.css`) and its OFL fonts into each page, so each page is self-contained |
| `tools/r8-common.css` | the only new styling: the pieces these screens add, in the console's tokens only |
| `tools/r8-bar.css` | screen 5's new pieces (edit mode, drop line, the carried item, tips, the hidden bar's handle, the phone's list editor), in the console's tokens only; `kit.py` adds it to `bar-edit.html` alone |
| `tools/deck.js` | draws the deck around the screens (top bar, ruler, rails, Core, dock or tab bar) with fixed example numbers |
| `tools/shoot.py` | takes every screenshot with Playwright and checks each one: contrast of every text line in the new panels (WCAG, from the rendered colours), cut text, sideways overflow, script errors; builds the contact sheets (`--only bar-edit`: screen 5 and its sheet) |
| `tools/squash.py` | shrinks new PNGs in place (Pillow: a 256-colour palette, dithered), about 60 % smaller with the text unchanged; screen 5's shots and sheet went in squashed |

Each page opens on its own in a browser (markup, styles, fonts and script are inside it). To rebuild:
`python3 -I tools/kit.py` then `python -I tools/shoot.py` (Playwright with Chromium); for screen 5,
`python3 -I tools/kit.py bar-edit.html`, `python -I tools/shoot.py --only bar-edit`, then `python3 -I tools/squash.py png/5-*.png contact-sheet-bar.png`.

## States shown (each in Night and Day)

| Screen | First use | Active | Camera off | Warning | Error: camera blocked | More |
|---|---|---|---|---|---|---|
| 1. Camera setup (laptop) | no spots yet; name this laptop's camera, add the phone, the home camera | three cameras with health; room switches; camera-on chip | Study switched off; Allow | too dark, phone not seen 3 days, home kit offline | the browser blocked the desk camera, with the fix | the no-cloud check, expanded with a result; phone: the tripod phone's own view |
| 2. Desk coach (laptop) | 3 setup steps: camera, learn your upright, nudges | upright, water 3 of 8, breath pacer running, sessions | paused; breathing and water still work | slouching for 6 min: body lines with the head forward | blocked, with the fix | BP posture checklist (a reading kept only if typed); reaction game |
| 3. Workout (phone) | place the phone, clear the space, the exercise picker | squats 8 of 15, tempo, a form tip | counting paused, reps kept | "knees well past your toes" | blocked, with the Android fix | — |
| 4. Your day (laptop) | no day yet | the day strip and totals; screen time off until ActivityWatch | camera off since 15:20, shown as such | 2 h 35 m without a break, the stretch outlined | blocked, the strip stopped at 14:50 | phone: the same card |

Every screen carries the one-line promise: "Only you are tracked. Nothing is recorded; only counts and times are kept."
Every cost here is ₹0 (all on the device, no AI call).

## 5. Your bar, your way (R8 part I)

The owner's ask (28 Nov 2026, 04:33 IST): "make every icon editable … drag and drop each item and place it as per my
requirement. Also, the items I remove should be in the More. I should also have the option to hide the bar as well."
The bar is the console's own dock and More sheet (`console.html` `#dock`, `console-dock.js`, `console-deck.css`), drawn
with their own classes; state 1 is exactly today's bar.

| # | State | Laptop 1920 × 1080 | Phone 390 × 844 |
|---|---|---|---|
| 1 | The bar as today | 22 tabs, Chat to Camera; no More (every tab fits); Calls in neither (R18) | six tabs and More |
| 2 | Edit mode | More → "Edit the bar": each item a dashed tile with a grip (top left) and a ✕ (top right); a toolbar above the bar: **Hide the bar · Reset to default · Done**; tips on Chat's and More's dimmed ✕ say why they stay | long-press a tab, or More → "Edit the bar": the More sheet becomes the bar as a list (top = left), each row a 44 px grip, its icon and name, a 44 px ✕; a dashed line where this phone's bar ends; Chat's row says why its ✕ is dimmed |
| 3 | Dragging | Vitals carried between Brief and Approvals: lifted in the console's dragged-panel look, a drop line with diamond caps, its old place an empty dashed slot; the toolbar says what letting go will do, and that Esc puts it back | the Vitals row lifted over the dashed gap it will land in (3rd) |
| 4a | Dropping on More | Construct carried onto More, which lights as the place to drop | (the list: ✕, or drag a row into "Taken off the bar") |
| 4b | Taken off, in More | More's sheet: "Edit the bar" at the top; "Taken off the bar" with **Put back**; "No room on this screen"; the line "Construct is off the bar, so Camera has room on it again" | the same sheet, phone layout |
| 5 | Bar hidden | a slim handle at the bottom edge; its tip: "Show the bar. Click here, or press Ctrl + ." | the handle, and "Tap the line below to bring it back" |
| 6 | The keyboard way | Vitals focused (the console's focus ring); a small panel above it: **Move left** (Shift + ←) · **Move right** (Shift + →) · **Move to More** (Delete); arrows move between items, Esc ends editing | the row selected: **Move up · Move down · Move to More** (44 px), and the same keys on a keyboard |

Rules shown: Chat and More can't be taken off the bar. The order and the items taken off are the same on every device
(a narrower screen shows the first ones that fit and folds the rest into More, as today); hiding the bar is for this
device only. A click on an item in edit mode (no drag) opens the same Move panel as the keyboard, so nothing needs a drag.
Reset to default puts back the first order and every item, with an Undo in the toolbar's status line. Nothing here
spends, sends or deletes; every cost is ₹0.

### Where the console's look forced a choice (the bar)

1. **More is always on the bar from R8, and at 1920 that costs Camera its place by default.** Today at 1920 × 1080
   every tab fits (the dock is 1851 px of the 1896 px the window gives it) and More is hidden; Calls is in neither
   (R18). Edit mode starts from More, items taken off wait in More, and More can't be taken off, so More must always
   show. It needs 82 px (78 + the gap) and the bar is 37 px short, so priority plus (`console-dock.js`) folds the last
   item: Camera waits in More with Calls until the owner moves something or takes one off (state 4b: taking Construct
   off brings Camera back). The tabs keep their 78 px; nothing is narrowed or restyled.
2. **The phone edits a list, not the bar.** At 390 px a tab is 55 px wide: a ✕ with a 44 px target would cover the
   tab's own icon and name, and the tabs folded into More can't be reached on the bar at all. On touch the More sheet
   becomes the editor (the `.sheet-item` material, 44 px grips and ✕); the laptop edits the bar in place. The list runs
   top to bottom, so the phone's keyboard way says Move up / Move down.
3. **The ✕ sits inside each tile** (top right, 20 px, a 24 px target): outside, it would cover the rails' last line
   ("Private by default", the date), 11 px above the bar.
4. **The divider stays after the seventh item**, where `console.html` has it, whatever moves; it is not an item.
5. **Tips are one line on the laptop**, so a tip covers the rail's last line whole rather than half of it; on the phone
   the dimmed ✕'s reason is written in Chat's row (touch has no hover).
6. **The hidden bar's handle is accent ink** (5 px tall; a 168 × 28 px target on the laptop, 180 × 44 on the phone):
   the console's line colour is under 3:1 on the night background. The shortcut is Ctrl + . (full stop): the console
   uses Ctrl + Space and Ctrl + Shift + Space for the microphone, and Chrome has no shortcut on Ctrl + .
7. **No jiggle in edit mode:** the dashed edges say "movable" without motion, so there is nothing to switch off for
   reduced motion; only the carried item follows the pointer.

ui-ux-pro-max for the bar: every drag has a single-pointer and keyboard way (WCAG 2.5.7); a drag starts after 8 px of
movement (a long-press of 500 ms on touch); the drop line and the status line follow the pointer; targets 24 px on the
laptop, 44 px on the phone; the focus ring is the console's `:focus-visible`; Esc cancels a drag; text contrast checked
on every shot.

## Where the console's existing look forced a choice

1. **Six Camera tabs in a 3 × 2 grid.** The Camera panel's tab strip (`.hp-tabs`) is 4 across. With Desk and Workout
   added there are six, and six names in the console's tab type do not fit one row at the panel's 420 px. The strip
   keeps its look and becomes 3 columns × 2 rows (one rule in `console-camera.css`).
2. **The camera-on chip.** R7's chip ("Camera on · Stop") sits fixed under the top bar, over the ruler. On the laptop
   the panels start below it; on the workout screen it moves into the title bar, where it stays on screen.
3. **The workout session takes the whole phone screen.** The phone layout leaves a panel about 620 px tall between the
   top bar and the tab bar, too small for a count read from 2 to 3 metres. A running session uses the panel material
   and title bar edge to edge (the tab bar hides while it runs; Back and Stop are always there).
4. **Amber for warnings.** `console.css` keeps amber for privacy notices and approvals, but Vitals and "This month"
   already use it for warnings; these screens follow Vitals (the same amber and red card mixes as `.spend`).
5. **Long panes scroll.** The Desk pane is taller than the Camera panel's default 720 px, so it scrolls; the shots show
   the panel at 876 px tall (it is resizable). Sessions lower in the list are reached by scrolling.
6. **The day strip is small.** In Vitals' 340 px the strip gets about 17 px an hour, so a 10-minute phone break is a
   sliver. The strip is drawn with pattern and colour, and the totals list under it carries the words and numbers.
7. **Disabled buttons** use the console's own half opacity (inactive controls are exempt from the contrast rule).

## Design rules followed

- **The console's look, unchanged:** its stylesheets are copied verbatim; the new pieces use only its tokens, fonts
  (Orbitron, Rajdhani, Share Tech Mono, the system sans), panel chrome, chips (`.vt-chip`), buttons, switches (`.bsw`),
  disclosure (`.dsc`), notes (`.bnote`, `.inote`) and the Vitals card material.
- **ui-ux-pro-max** (nextlevelbuilder/ui-ux-pro-max-skill): followed for UX and accessibility (text contrast 4.5:1
  checked by computation on every shot, lowest 4.70; status never by colour alone: every chip has a word, the strip has
  patterns and a list; 44 px touch targets on the phone; empty states with one clear action; errors next to their cause
  with the fix; live status regions; reduced motion: shots are taken at the console's Motion Off). Its generated design
  system (Glassmorphism, Caveat / Quicksand, a blue and green palette) was not used: the console's own look is fixed.
- **Plain words** for a non-technical owner; the only technical words are the two a camera box prints (RTSP, ONVIF),
  each explained in one line.
- **Safety:** "Stop if anything hurts. Handstands only with a wall or a spotter." on every workout state; "Not medical
  advice" under the desk sessions; the BP coach checks posture only and never reads meaning into a number.

## Check results

`tools/shoot.py`, 50 shots: no text below 4.5:1 (lowest 4.70, white on the accent button), no cut text, no sideways
overflow, no script errors (`tools/check-report.json` is written locally and not committed). Every PNG was also looked at.
Screen 5, 26 shots (the bar, its toolbar, tips, the Move panel and the More sheet checked too): no text below 4.5:1
(lowest 4.70), no cut text, no sideways overflow, no script errors; every PNG looked at after squashing.

## Change log

| Version | Date | Change |
|---|---|---|
| v8.0.1 | 28 Nov 2026 | First draft: four screens, 50 states (Night and Day), contact sheet, the kit and the checks. |
| v8.0.2 | 28 Nov 2026, 04:55 IST | Screen 5, "your bar, your way" (R8 part I): the bar as today, edit mode, dragging, dropping on More, More with Put back, the hidden bar, the keyboard way; laptop and phone, Night and Day (26 shots), `contact-sheet-bar.png`, `tools/r8-bar.css`, `tools/squash.py`. |
