Version v6.4.1 · 25 Nov 2026, 12:25 IST · Release R6.4 · Status: Approved (stop 4, 25 Nov 12:13 IST) · Owner: 🛠 Mark XXIV

# Release R6.4 — Build Book Part 3: the Book's own look and the full book in narrated chapters (`v6.4.0`)

**Why:** the owner's asks of 14 Nov ("the current Book is not satisfactory": a new look for the Book
only, row 381) and 23 Nov ("the full book explains like the tour": narrated chapters, row 390), and
his answer of 24 Nov, 07:43 IST, "yes, fix both in the later releases", on two findings of R6.3.1
(rows 392 and 393). His go-ahead: 25 Nov, 11:57 IST, "Yes, start R6.4".

**Phase:** 7 (quality, docs), cross-cutting; the Learning skill. **Type:** Free: ₹0 a month, no new
paid service, secret or Scheduler job; narration uses the browser's voice (₹0) unless the owner
switches the Book to the cloud voice (existing setting). **Version:** `v6.4.0`.

**Approval stop 4 — passed 25 Nov 2026, 12:13 IST.** The owner's answers: 1. the new look as in
the mockups (A–K): yes; 2. the flowcharts as the chapters' pictures, the tour keeping its 3D
scenes: yes, *"and with animations and effects which would keep the reader engaged and doesn't feel
monotonous or boring. May use different animations, variations, to keep the reader engaged"*
(new row 394, D11); 3. a spoken script written for each of the 26 chapters: yes.

## 1. Scope (workbook rows)

| Row | What | In R6.4 |
|---|---|---|
| 381 | A new look for the Build Book only | The full book moves to its own full-screen reader with contents, search, page layout and flowcharts in Book-only tokens (D1–D3). New 3D scenes: §8 question 2 |
| 390 | The full book narrated chapter by chapter | The chapter player: voice, captions, the flowchart's boxes lit as they are told, pause and skip (D4–D6) |
| 392 | An AI address on a `*.ts.net` name must use https | `config._is_private_host` stops treating `*.ts.net` as private (D8) |
| 393 | Costs counts paid Gemini and unpriced models | Paid-tier Gemini prices; an unknown model is flagged, never ₹0 (D9) |
| 394 | Varied animations and effects in the narrated chapters (25 Nov) | The effects engine and its catalogue (D11) |

**Not in R6.4** (from Phase A's old list, not in rows 381/390; can be added later on request): a
Simple / Technical toggle, an interactive architecture map, print views, a guest-safe full book,
automated axe runs (keyboard and contrast are checked by hand and by tests instead).

## 2. Design (ui-ux-pro-max)

The repo's design system for "technical documentation reader, narrated walkthrough, sci-fi HUD":
style **HUD / Sci-Fi FUI** (the console's own style), pattern **Immersive/Interactive Experience**
(skip, keyboard, reduced-motion and non-3D paths), typography **Share Tech Mono** for labels. Its
palette (#3B82F6 on #0B0B10) is **not used**: the console's tokens are the brand (repo rule 5), so
both surfaces and all five themes keep working. UX rules applied: line length 65–75 characters,
body line height 1.5–1.75, search with predictions and a helpful "no results", visible focus on
every control, progress shown for multi-step content, pause/next/previous for anything that
advances by itself.

## 3. Decisions

- **D1 — The full book gets its own page,** `/book/read` (owner only), like the show's
  `/book/show`: the same Open (passkey + a fresh Google sign-in), the token in this tab's
  sessionStorage only, cleared at close. The Book panel keeps its status, Open, releases and
  settings, and its cramped in-panel reader is replaced by **Read the full book** and **Short
  tour**. A guest still gets the tour only.
- **D2 — Book-only tokens** in a new `book-read.css` on `html[data-book]` (measure 68ch, 16 px /
  1.65 body, 18 px lead, Orbitron title, Share Tech Mono labels, a raised "now" tint, a search
  mark), all derived from the console's tokens. `console.css`, `console-deck.css` and every other
  screen are not touched.
- **D3 — Layout.** Laptop: top bar (wordmark, search, release chip, Short tour, Close); contents
  rail (Continue card, The story 8, Modules 18 with their pages, Screens 23, Outside services 31,
  read dots, minutes per chapter); the page (breadcrumb, title, who wrote it and when, the
  chapter's Play card, the five sections with the flowchart in "How it works", previous/next);
  "On this page" and "In this chapter" rail at 1280 px and wider. Phone: a contents sheet with
  search, one column, the Play bar appears once the Play card scrolls away.
- **D4 — Search** (`GET /v1/book/pages/search?q=`, owner only, rate-limited, no AI, ₹0): the
  compiled pages of the release (titles, headings, text with facts filled), at most 20 results,
  each with its kind and a short snippet with the words marked; Enter opens the first; a helpful
  line when nothing matches.
- **D5 — A chapter** is a story chapter (1 page) or a module with its parts, screens and outside
  services (for example Vault: 5 pages). 26 chapters, about 4–14 minutes each, about 2½–3 hours in
  all.
- **D6 — Narration scripts are written by the Workshop at build time** (the R6.3.1 way, on the
  owner's subscription, ₹0): one short spoken script per chapter, lines with optional cues to a
  flowchart box, numbers as `{{fact:…}}`, no file paths read aloud. `pages --check` gains the
  narration checks (facts, cues exist, length, stale when a page of its chapter changes);
  compiled with the pages and sealed with the release. I0 picks the sealing that a `v6.3.2`
  server tolerates on a rollback (a new file or a field), and the risk is noted.
- **D7 — The player:** play/pause, previous/next line, previous/next page, a progress bar in page
  segments with time, CC, Sound, speed (0.85×, 1×, 1.25×), Stop (back to reading at the same
  page); keys as the tour (Space, arrows, Page Up/Down, C, M, Esc). The spoken box is lit, the
  boxes already told stay solid, the rest are drawn quieter (colour, never opacity on text: AA on
  both surfaces). Pages without a flowchart show the section's title card. Continue where I left
  off (chapter and line). Reduced motion: no glow pulse, no scroll animation.
- **D8 — Row 392:** `*.ts.net` is no longer a private host for the http rule; plain http stays
  allowed for loopback, RFC 1918 and single-label names. A failing test first; the security
  review checks it.
- **D9 — Row 393:** with `gemini_paid_tier` on, Gemini replies are priced from Google's published
  paid-tier prices (source and date in `llm/pricing.py`); a model with no known price is shown in
  Costs as "price unknown", counted, and never as ₹0. Free tier unchanged (₹0).
- **D10 — The Book's pages** whose code changes are refreshed in the same PR (`pages --check`
  strict, 153 ok), as every release since R6.3.1.
- **D11 — Row 394, effects that keep the listener engaged** (no library: CSS, SVG and the Web
  Animations API, transform and opacity only). A catalogue of families, each with 2–4 variants:
  1. **Path tracing:** the main path draws itself from the told box to the spoken one; a glowing
     "packet" travels along a connector.
  2. **Box entrances:** sonar ping, bracket frame assembling, scan-line wipe, lift-and-glow.
  3. **Kind accents:** a guard's shield locks, a store's cylinder fills, a service's double border
     turns, a person's badge waves.
  4. **Camera:** an establishing overview at a section's start, then a smooth pan and zoom to the
     spoken box; a pull-back at the section's end.
  5. **Section cards:** "In plain words", "Example", "What it costs", "When it fails" enter with
     varied HUD reveals (split, typewriter, glitch-free decode, iris).
  6. **Example as a storyboard:** the made-up person's steps appear as captioned frames.
  7. **Costs:** a ₹ count-up with a bullet bar against the monthly limit.
  8. **Failures:** an amber frame with a soft alert pulse.
  9. **Captions:** the spoken words lit as they are said (the voice's word boundaries; timed
     estimate when a voice sends none).
  10. **Page change:** the chapter stepper slides; a wipe in the theme's accent.
  11. **Ambient:** a slow HUD grid drift behind the stage.
  Variation rule: a deterministic picker (seeded by chapter and line) never repeats an entrance or
  camera move twice in a row and spreads every family across a chapter. Safety: Pause stops all
  motion (WCAG 2.2.2); Motion "Calm" and reduced motion give cross-fades only, Motion "Off" none;
  nothing flashes more than 3 times a second; effects pause when the tab is hidden; a phone keeps
  60 fps by dropping the ambient layer first. Script cues (`node`, `edge`, `show`, `count`) say
  WHAT is shown; the engine picks HOW.

## 4. Builders

1. **I0** (seams): routes and their shapes (`/book/read`, search), the narration file format and
   its checks in `pages`, the sealing choice, `book-read.css` tokens, the panel's two buttons.
2. **A — Reader:** `book-read.html`, `console-book-read.js` (contents, page, continue, keyboard),
   search UI; reuses `console-book-flow.js`.
3. **B — Player and effects:** `console-book-chapter.js` (timeline, browser voice through the
   existing `console-book-voice.js`, captions, cues, controls) and `console-book-fx.js` (D11).
4. **C — Fixes 392 and 393** (tests first).
5. **W1–W4 — Narration writers:** the 26 chapter scripts; then the stale pages refreshed.
6. **I1** join → **one combined security + code review** with the one final check pass →
   screenshots of every new screen (Night/Day, laptop/phone) → PR `v6.4.0 · R6.4 …` → the
   owner merges.

## 5. Tests and evals

Unit: search ranking and refusals (guest 403, release without pages), narration checks, the
private-host rule, pricing. Browser: reader (contents, page, search, keyboard, phone sheet),
player (play, pause, skip, cues lit, Stop returns to the page, reduced motion), the guest still
gets the tour only. Mock evals: "narration scripts compile and pass the checks". Contrast:
computed for every new colour pair (lit box, search mark, captions) on both surfaces.

## 6. Cost (₹)

₹0 a month. Writing the scripts: the owner's Claude subscription, not the API. Listening: the
browser's voice; the cloud voice only if switched on (about ₹2.9 per 1,000 characters past the
free allowance; a 9-minute chapter is about 7,000 characters).

## 7. Risks

- A rollback from `v6.4.0` to `v6.3.2` may show one false "integrity check failed" (as R6.3.1's);
  nothing lost; roll forward.
- Browser voices differ by device; captions always work without sound.
- A flowchart taller than the stage: the stage follows the spoken box.

## 8. Questions for the owner (approval stop 4; defaults in brackets)

1. The new look as in the mockups (laptop A–F, phone G–K) [yes].
2. New 3D scenes: the narrated chapters use the flowcharts as their pictures; the tour keeps its
   current 3D scenes [yes]. New 3D scenes (Fable 5.2) would add about a day; later, if wanted.
   **Answer: yes, with varied animations and effects (D11, row 394).**
3. Narration written by the Workshop at build time, chapter by chapter [yes]; the other way would
   read the page text aloud as it stands (quicker, sounds less natural).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.0 | 25 Nov 2026, 12:45 IST | R6.4 | First edition: scope (rows 381, 390, 392, 393), design (ui-ux-pro-max), decisions D1–D10, builders, tests, cost, risks and the questions for approval stop 4; mockups in `docs/plans/r6-4-mockups/` | 🛠 Mark XXIV |
| v6.4.1 | 25 Nov 2026, 12:25 IST | R6.4 | Approval stop 4 passed (12:13 IST): the owner's three answers; new row 394 and decision D11 (the effects engine, its catalogue and its safety rules); builder B owns the effects |  🛠 Mark XXIV |
