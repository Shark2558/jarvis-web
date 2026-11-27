# R8 / R8.1 mockups: the four new screens

Version v8.0.1 · 28 Nov 2026, 04:05 IST · Release R8 · Status: Draft · Owner: 🛠 Mark XXVI

Mockups only, for the owner's approval stop. No product code. They show where each new screen lives, what it says and
how it looks in every key state, in the console's own look (Workshop theme), Night and Day.

**Contact sheet:** [`contact-sheet.png`](contact-sheet.png) (all 50 shots on one page).

## Where they live (no new dock tab, ADR-35)

| Screen | Rows | Where | Opens from |
|---|---|---|---|
| 1. Camera setup | 217, 184, 377 | Camera panel, **Cameras** tab (extended) | Camera tab, or `?open=camera` |
| 2. Desk coach | 181, 224, 227, 238, 248, 262, 268, 276 | Camera panel, new **Desk** tab | Camera tab, or a new launch word `?do=desk` |
| 3. Workout session | R8.1's 20 rows | Camera panel, new **Workout** tab; a running session fills the phone screen | Camera tab on the phone, or a new launch word `?do=workout` |
| 4. Your day and screen time | 182, 183 (+ camera health, 217) | **Vitals**, a "Your day" card directly under "This month", then a "Cameras" health card | Vitals tab, or `?open=vitals` |

Privacy rows for the new health results (184 and the kept counts) use the existing Privacy panel pattern; no mockup.

## Files

| File | What it is |
|---|---|
| `camera-setup.html` | Screen 1. `?v=laptop\|phone&s=night\|day&st=first\|active\|off\|warn\|error\|check` |
| `desk-coach.html` | Screen 2, laptop only (the desk camera is on the laptop). `?s=…&st=first\|active\|off\|warn\|error\|bp\|game` |
| `workout-phone.html` | Screen 3, phone only (390 × 844). `?s=…&st=first\|active\|off\|warn\|error` |
| `activity-timeline.html` | Screen 4. `?v=laptop\|phone&s=…&st=first\|active\|off\|warn\|error` |
| `png/` | 50 screenshots, named `<screen>-<page>-<view>-<state>-<theme>.png` |
| `contact-sheet.png` | every shot on one sheet |
| `tools/kit.py` | copies the console's own CSS (`console.css`, `console-deck.css`, `console-memory.css`, `console-helpers.css`, `console-vitals.css`, `console-camera.css`) and its OFL fonts into each page, so each page is self-contained |
| `tools/r8-common.css` | the only new styling: the pieces these screens add, in the console's tokens only |
| `tools/deck.js` | draws the deck around the screens (top bar, ruler, rails, Core, dock or tab bar) with fixed example numbers |
| `tools/shoot.py` | takes every screenshot with Playwright and checks each one: contrast of every text line in the new panels (WCAG, from the rendered colours), cut text, sideways overflow, script errors; builds the contact sheet |

Each page opens on its own in a browser (markup, styles, fonts and script are inside it). To rebuild:
`python3 -I tools/kit.py` then `python -I tools/shoot.py` (Playwright with Chromium).

## States shown (each in Night and Day)

| Screen | First use | Active | Camera off | Warning | Error: camera blocked | More |
|---|---|---|---|---|---|---|
| 1. Camera setup (laptop) | no spots yet; name this laptop's camera, add the phone, the home camera | three cameras with health; room switches; camera-on chip | Study switched off; Allow | too dark, phone not seen 3 days, home kit offline | the browser blocked the desk camera, with the fix | the no-cloud check, expanded with a result; phone: the tripod phone's own view |
| 2. Desk coach (laptop) | 3 setup steps: camera, learn your upright, nudges | upright, water 3 of 8, breath pacer running, sessions | paused; breathing and water still work | slouching for 6 min: body lines with the head forward | blocked, with the fix | BP posture checklist (a reading kept only if typed); reaction game |
| 3. Workout (phone) | place the phone, clear the space, the exercise picker | squats 8 of 15, tempo, a form tip | counting paused, reps kept | "knees well past your toes" | blocked, with the Android fix | — |
| 4. Your day (laptop) | no day yet | the day strip and totals; screen time off until ActivityWatch | camera off since 15:20, shown as such | 2 h 35 m without a break, the stretch outlined | blocked, the strip stopped at 14:50 | phone: the same card |

Every screen carries the one-line promise: "Only you are tracked. Nothing is recorded; only counts and times are kept."
Every cost here is ₹0 (all on the device, no AI call).

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

## Change log

| Version | Date | Change |
|---|---|---|
| v8.0.1 | 28 Nov 2026 | First draft: four screens, 50 states (Night and Day), contact sheet, the kit and the checks. |
