Version v13.1.1 · 17 Nov 2026, 16:15 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — Part D brief: Console and phone (Opus)

Read `BRIEF-COMMON.md` first. Branch `r13-1-d` from `origin/r13-1-i0`. `security-reviewer` is
REQUIRED (the pixel panel, the door).

You build Try it on's console: the section in Helpers → Wardrobe, the measurements form, every
control, swaps, undo, compare, settings and the OPS-05 button, the checklist (AVT-15) with image
cards and the share caption's words, his photo panel (the third pixel panel), the YES dialog, the ₹
estimate and confirm, progress and the pictures. Plan sections: D1, D4 (the form), D7, D8, D9 (the
words), D11–D13 (the UI), D16 (the button), "Per part" D, the `console` suite, "Browser".

## 1. Your files (only these)

`src/jarvis/api/static/console-tryon.js` (≤ 600 lines), `console-tryon-list.js` (≤ 300),
`console-tryon-me.js` (≤ 400), `console-tryon-photo.js` (≤ 300), `console-tryon.css` (≤ 200; places
only) — I0's stubs, yours to replace — `tests/test_r131_d_*.py`, `tests/browser/test_r131_d_*.py`,
`tests/r131_fakes_d.py`, `tests/fixtures/r13_1/d_*` (your own fixtures), `evals/r13_1/console.py`
(I0's stub: replace it), the mockup screenshots (to the orchestrator, never committed with personal
data), `docs/plans/r13-1-integration/INTEGRATION-D.md`.

## 2. Your contracts

- **The hook (I0's, `console-helpers-wardrobe.js`):** it imports `./console-tryon.js` ONCE in its
  `mount()` and calls `mount(host, ctx)` (the section's host is the seventh `.hp-sec`, between
  "Today and tomorrow" and "Laundry"; `ctx` is the tab's `{H, view, priv, nameOf, placeOf, tool,
  btn, acts, field, select, when, show, detail}`); never from `draw()`. Export `mount(host, ctx)`,
  `seeOn()` (true while See it on me is on: the plan rows then show its button) and `open(plan,
  {see})`. Listen for `jarvis:tryon-open` `{plan, see}` (a plan row's "Show in 3D" / "See it on
  me") and `jarvis:wardrobe-fresh` (re-read the look: readiness comes from the server, never the
  render). Keep the loads tests pin: `console-tryon.js` loads `'./console-tryon-list.js'`,
  `'./console-tryon-me.js'` and `'./console-tryon-3d.js'`; `console-tryon-me.js` loads
  `'./console-tryon-photo.js'`.
- **The engine (B's) through its contract only** (`tests/fixtures/r13_1/engine_contract.mjs`):
  `window.JarvisTryOn3D.supported()`, `mount(host, {release, onLost})` → Stage `{show(figures,
  opts), view(name), spin(on), zoom(step), closer(), snapshot({caption}), stats(), dispose()}`;
  `figures[i] = {body: {weights, typed}, look: {slots: [{slot, piece, template, variant, rgb,
  pattern, photo, private}]}}` built from `GET /v1/tryon` and `GET /v1/tryon/look` (a private slot
  is `{slot, private: true}` only); `opts = {tucked, open, layers, view}`. I0's stub throws on
  `mount()`: your checklist path is real from day one. One stage, one WebGL context; dispose on
  tab hide and `pagehide`; "Turn around" still under Motion Off; Full screen (the Fullscreen API on
  the stage, Escape returns) hidden where `requestFullscreen` is missing (an iPhone).
- **The checklist (D8, AVT-15)** is always one tap away ("Show as a list") and shown by itself when
  WebGL2 is missing, the engine or an asset fails to load or its sum, the context is lost
  (`onLost`), a first render takes more than 10 s, or the governor retires 3D. Each row: the slot,
  the piece's words (private ones as R13 shows them, behind "Show private basics"), its image card
  (`door.thumb`), its readiness; actions **Change** (the same options as the figure) and the plan's
  **Wearing it** / **Use this look** (R13's `POST /v1/wardrobe/tools/{tool}` and A's
  `POST /v1/tryon/confirm`). "Preparing the 3D view…" stays separate. **Retry 3D** once a page.
  "Wearing it" after a swap that isn't confirmed runs the confirm first (L10). The failure hooks
  B honours: `window.__glFail` (`'no-webgl2'`, `'lost'`, `'asset'`, `'timeout'`).
- **Controls (D7):** Front, Side, Back, drag, zoom, Turn around, Closer look; tuck / untuck (a kurta
  says "A kurta is worn out"), open / closed; layers All, Without the outer layer, Base layer only;
  swap from a slot's options (each with its readiness word; a draft is shown "Draft: …" and can't be
  confirmed), Remove (outer, belt, watch, socks), undo (≤ 20 steps in page memory; an undo that lands
  on a pick no longer eligible lands as a draft); compare two looks (one call to `show` with two
  figures), "Save this comparison" (A's `POST /v1/tryon/saved`); the measurements form (six whole-cm
  fields, the range words from `GET /v1/tryon`'s `ranges`, "estimated" on untyped ones, "Use these
  measurements" / "Keep the current"); his template choice per piece (A's `PUT
  /v1/tryon/assets/{piece}`); "Delete all my try-on data" opens `window.JarvisPrivacy.remove(
  'tryon_all')` (I0's: the category's own passkey and words).
- **"Save a picture of this look" (D9):** you pass B's `snapshot({caption})` the caption LINES (the
  date or the event's time, each non-private piece in fixed words: "Navy shirt · Charcoal trousers ·
  Brown belt", "Base layer (covered)" for a private slot, never his labels unless he ticks "Use my
  own labels", never a piece id); preview it from a `data:` URL or a canvas B gives (`blob:` is not
  in `img-src`); save it to his Downloads like the label sheet. Your modules use NO pixel API.
- **His photo panel** `console-tryon-photo.js` (D12, the third pixel panel): `<input type=file
  accept="image/jpeg,image/png">` (no `capture`); R13's `person` (SSD ≥ 0.5) and `face` (UltraFace ≥
  0.7) tasks on one bitmap (`JarvisVision` on a still, as Camera → Wardrobe's "Choose a photo"):
  exactly one person and at most one face pass; none or several → "This photo should show only
  you"; a person box under 60 % of the height → "Step back so your whole body is in the picture"
  (advice); the words say JARVIS can't tell ages. Send ONLY through `door.person(blob, {maxKb})`
  (`maxKb` from `GET /v1/seeme`'s `photo_max_kb`; the door redraws down to it and says "This photo
  is too detailed to send: try a plainer background"). The scan module's rules (BRIEF-COMMON 4;
  ASCII source). The models missing → "The photo check isn't available on this device" (no photo is
  saved).
- **See it on me (D11, D13):** the YES dialog shows `ConsentView.words` and posts `{typed,
  template_version}`; the estimate's words; the `.bdialog` confirm ("Make 1 picture of you in the
  navy shirt and charcoal trousers? About ₹9 with GST. ₹54.3 of ₹300 used this month."): **Make the
  picture** posts `confirm_cost: true`, `inr_shown` and a fresh `request_id` (`tq_` + 16 hex);
  **Cancel** sends NOTHING; progress; the picture through `door.picture(id)` with "Generated 2D
  style preview — not a photo; the fit is not exact", the made-at time, the ₹, the pieces sent and
  not sent (with their thumbnails), "Google adds Content Credentials (C2PA)"; Keep / delete; the 3D
  view stays. Branch on `err.code` (`Refusal`'s `error`).
- **The look does not change:** only existing components (`.hp-sec`, `.hp-h`, `.hp-row`,
  `.btn.sact`, `.sacts`, `.bsw`, `.minput`, `.snote`, `.sfine`, `.bdialog`); `textContent` only;
  44 px targets; the stage 56 % of the viewport's height on a phone, 480 px on a laptop; day and
  night. The existing tabs' screenshots with Try-on OFF stay R13's.

## 3. Your row (his acceptance check, word for word) and its named test

| Row · ID | His acceptance check | Your test (what must hold) |
|---|---|---|
| 366 · AVT-15 | If a render fails, the user can still confirm a ready outfit or change a piece from its checklist. | **`test_avt15_a_failed_render_leaves_a_checklist_that_can_change_a_piece_and_confirm`**: with no WebGL (the `__glFail` hook), a lost context, an asset that fails its sum, or a 10 s render timeout, the checklist shows each piece with its image card and readiness; "Change" swaps a piece and "Wearing it" confirms the ready outfit through R13's tools |
| every row (your UI half) | (as in the plan's first table) | `test_avt02_controls_*` (Front, Side, Back, drag), `test_avt03_form_*`, `test_avt04_cards_*` (both reference cards, "ask for the back view only" with its link), `test_avt05_card_*`, `test_avt06_swap_*` (W1 → W2: the slot's thumbnail is W2's), `test_avt08_*`, `test_avt09_swap_undo_*`, `test_avt10_toggles_*`, `test_avt11_lists_*` (two item lists with each piece's readiness word), `test_avt12_card_*`, `test_avt14_share_*` (the caption's words: no private label, colour or id), `test_ops05_button_*` |

The eval case of the same name for AVT-15 is in `evals/r13_1/console.py`.

## 4. Your eval (`evals/r13_1/console.py`, browser) and its controls

Cases: each row's UI half; the checklist under `__glFail`, missing WebGL2, a lost context and an
asset 404; the YES dialog; the ₹ confirm with Cancel sending nothing; the share caption passed to
`snapshot`; 44 px targets; 360 × 800 and 1280 × 800, day and night; the existing tabs' screenshots
with Try-on off unchanged against R13's. **Control that must turn it red:** the engine stub that
throws, with the checklist hook removed (AVT-15 fails). **The rows' own controls (M8) that are
yours:** AVT-06 the slot's thumbnail stays W1's after the swap; AVT-11 the second figure's readiness
words are dropped; AVT-15 the checklist hook removed. Until B's engine lands, run against I0's stub
and a fake engine of your own that keeps the contract (in `tests/r131_fakes_d.py` or a
`tests/fixtures/r13_1/d_*.mjs`), against `tests/r131_fake_server.py` (`serve(token)`).

## 5. Limits

The photo check is tested first on a drawn full-length figure fixture and the R13 test hook that
can only add refusals; if a drawn figure doesn't fire SSD and UltraFace (check it first, as R13
did), test the panel's decision logic on recorded task outputs and leave the real check to the pilot
(say so in INTEGRATION-D). ₹ only. Browser tests pin the page clock, carry `-m browser`, run one file
at a time behind the lock. INTEGRATION-D: the mockups sent, what you need from A, B and C, "Needs
I1", what you could not verify (a real full-length photo, his phone's GPU).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 16:15 IST | R13.1 | First edition, written at I0: Part D's files, contracts (I0's hook and events, the engine through its contract, the checklist and its failure hooks, every control, the share caption's words, the photo panel's rules and the door, See it on me's dialogs, the look unchanged), its row and its UI halves, the `console` eval with its controls, limits | 🛠 Mark XXIII |
