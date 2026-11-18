Version v13.1.2 · 17 Nov 2026, 17:50 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — Part D brief: Console and phone (Opus)

Read `BRIEF-COMMON.md` first. Branch `r13-1-d` from `origin/r13-1-i0`. `security-reviewer` is
REQUIRED (the pixel panel, the door).

You build Try it on's console: the section in Helpers → Wardrobe, the measurements form, every
control, swaps, undo, compare, settings and the OPS-05 button, the checklist (AVT-15) with image
cards and the share caption's words, his photo panel (the third pixel panel), the YES dialog, the ₹
estimate and confirm, progress and the pictures, **and the owner's scope of 17 Nov 2026**: the try-on
card that opens by itself under a "what should I wear?" reply (row 388, plan D21), and See it on me
for a garment he is thinking of BUYING (plan D22: its photo, its type and colour, the pairing with his
pieces). Plan sections: D1, D4 (the form), D7, D8, D9 (the words), D11–D13 (the UI), D16 (the
button), **D21, D22**, "Per part" D, the `console` suite, "Browser".

## 1. Your files (only these)

`src/jarvis/api/static/console-tryon.js` (≤ 600 lines), `console-tryon-list.js` (≤ 300),
`console-tryon-me.js` (≤ 400), `console-tryon-photo.js` (≤ 300), `console-tryon-card.js` (≤ 150),
`console-tryon.css` (≤ 200; places only) — I0's stubs, yours to replace — `tests/test_r131_d_*.py`, `tests/browser/test_r131_d_*.py`,
`tests/r131_fakes_d.py`, `tests/fixtures/r13_1/d_*` (your own fixtures), `evals/r13_1/console.py`
(I0's stub: replace it), the mockup screenshots (to the orchestrator, never committed with personal
data), `docs/plans/r13-1-integration/INTEGRATION-D.md`.

## 2. Your contracts

- **The hook (I0's, `console-helpers-wardrobe.js`):** it imports `./console-tryon.js` ONCE in its
  `mount()` and calls `mount(host, ctx)` (the section's host is the seventh `.hp-sec`, between
  "Today and tomorrow" and "Laundry"; `ctx` is the tab's `{H, view, priv, nameOf, placeOf, tool,
  btn, acts, field, select, when, show, detail}`); never from `draw()`. Export `mount(host, ctx)`,
  `open(plan)`, `inline(el, card)` and `garment(file)` (below). Listen for `jarvis:tryon-open`
  `{plan}` (a plan row's "Show in 3D", the only button a plan row has now: "See it on me" is for a
  garment to buy, D22) and `jarvis:wardrobe-fresh` (re-read the look: readiness comes from the
  server, never the render). **The section opens dressed by itself** in the first look "Today and
  tomorrow" shows (a plan's when one exists, else `GET /v1/tryon/look?day=`), no tap (D21.3). Keep the loads tests pin: `console-tryon.js` loads `'./console-tryon-list.js'`,
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
- **Row 388, the card under a reply (D21)** `console-tryon-card.js`: loaded at start by I0's
  `console-r7.js`; it registers `window.JarvisTryOnCard = Object.freeze({ cards, garment })` (keep
  that line: a test pins it). `console-media.js` calls `cards(row, list)` for EVERY reply's
  `ChatResponse.cards` (typed or spoken; `console.js` already does this); take the ONE card of kind
  `tryon` (`{day, plan, code, slots: [{slot, pieces, private}]}`: piece ids only, a private slot
  `private: true` with no id) and, with no extra tap, `import('./console-tryon.js')` and call
  `inline(el, card)`, which draws the figure under the reply dressed in exactly those pieces through
  A's `GET /v1/tryon/look?pieces=slot:wi_…,…` (the fake server serves it; a private slot stays
  covered), with turn, layers, tuck, swap, compare and "Show as a list"; the checklist when 3D can't
  run (D8, `__glFail`). One stage on the page at a time: opening the card disposes the section's
  stage (and back). Read only the card (no `fetch`; `JarvisConsole.api` / the door only, through
  `console-tryon.js`). A reply without a `tryon` card draws nothing; nothing is kept.
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
- **See it on me for a garment he is thinking of buying (D11, D13, D22):** "Add a garment you're
  thinking of buying": `<input type=file accept="image/jpeg,image/png">` (a shop photo, a website
  picture or a screenshot), or a picture shared into the app (the share tray's "See it on me (a
  garment to buy)" calls `window.JarvisTryOnCard.garment(file)`, which hands it to your
  `garment(file)`: open Try it on's See it on me with it; that press sends nothing). JARVIS never
  fetches an address: no URL field. He picks its **type** (`model.NEW_TYPES`' words) and **colour**
  (R13's fixed colours) from lists, never free text; the photo panel's check refuses a face ("This
  photo shows a person: crop it to the garment, or use a photo of the garment alone"); then
  `door.garment(blob, {type, colour, maxKb})` (`POST /v1/seeme/garments`; read back with
  `door.garmentPhoto(id)`); its words are the server's (`GarmentView.words`, "a new navy shirt, not
  in your wardrobe"); never its file name. **Pairing:** `GET /v1/seeme/pair?garment=` gives up to two
  of his pieces with their words; he may swap (his non-private tops, bottoms and outer layers) or
  untick them. The YES dialog shows `ConsentView.words` and posts `{typed, template_version}`; the
  estimate (`?garment=&pieces=`) and its words; the `.bdialog` confirm ("Make 1 picture of you in a
  new navy shirt, with your charcoal trousers? About ₹9 with GST. ₹54.3 of ₹300 used this month."):
  **Make the picture** posts `{garment, pieces, confirm_cost: true, inr_shown, request_id}` (`tq_` +
  16 hex); **Cancel** sends NOTHING; progress; the picture through `door.picture(id)` with
  "Generated 2D style preview — not a photo; the fit is not exact", the made-at time, the ₹, the new
  garment's words, his pieces sent and not sent (with their thumbnails), "Google adds Content
  Credentials (C2PA)"; Keep / delete; his garment photos listed (`GET /v1/seeme/garments`) with
  Delete; the 3D view stays. Nothing here adds the garment to his wardrobe. Branch on `err.code`
  (`Refusal`'s `error`: `no_garment`, `too_many`, `not_a_garment` included).
- **The look does not change:** only existing components (`.hp-sec`, `.hp-h`, `.hp-row`,
  `.btn.sact`, `.sacts`, `.bsw`, `.minput`, `.snote`, `.sfine`, `.bdialog`); `textContent` only;
  44 px targets; the stage 56 % of the viewport's height on a phone, 480 px on a laptop; day and
  night. The existing tabs' screenshots with Try-on OFF stay R13's.

## 3. Your row (his acceptance check, word for word) and its named test

| Row · ID | His acceptance check | Your test (what must hold) |
|---|---|---|
| 388 · (new) | (his words) "whenever I ask what to wear, jarvis should open up the card, decide and show me on the 3D model"; no extra tap; the checklist when 3D can't run; private pieces covered | **`test_row388_asking_what_to_wear_opens_the_card_dressed_in_the_chosen_look`** (browser, on the fake server now and the wired app at I1): a reply carrying a `tryon` card opens the figure under it with no tap, and `stats()` reports exactly the card's slot → piece ids; a private slot covered; with `__glFail` the checklist shows the same pieces; a spoken reply the same; a reply with no `tryon` card draws nothing; Helpers → Wardrobe opens dressed in the first look. **Control:** the card left out of the reply (the server half's control is I0's, in the contract eval) |
| 366 · AVT-15 | If a render fails, the user can still confirm a ready outfit or change a piece from its checklist. | **`test_avt15_a_failed_render_leaves_a_checklist_that_can_change_a_piece_and_confirm`**: with no WebGL (the `__glFail` hook), a lost context, an asset that fails its sum, or a 10 s render timeout, the checklist shows each piece with its image card and readiness; "Change" swaps a piece and "Wearing it" confirms the ready outfit through R13's tools |
| every row (your UI half) | (as in the plan's first table) | `test_avt02_controls_*` (Front, Side, Back, drag), `test_avt03_form_*`, `test_avt04_cards_*` (both reference cards, "ask for the back view only" with its link), `test_avt05_card_*`, `test_avt06_swap_*` (W1 → W2: the slot's thumbnail is W2's), `test_avt08_*`, `test_avt09_swap_undo_*`, `test_avt10_toggles_*`, `test_avt11_lists_*` (two item lists with each piece's readiness word), `test_avt12_card_*` (the new garment's words and his pieces; no URL field; nothing added to the wardrobe), `test_d22_garment_*` (type and colour from lists, the face refusal, the share tray's hand-over sends nothing), `test_avt14_share_*` (the caption's words: no private label, colour or id), `test_ops05_button_*` |

The eval case of the same name for AVT-15 is in `evals/r13_1/console.py`.

## 4. Your eval (`evals/r13_1/console.py`, browser) and its controls

Cases: each row's UI half; the checklist under `__glFail`, missing WebGL2, a lost context and an
asset 404; the YES dialog; the ₹ confirm with Cancel sending nothing; the share caption passed to
`snapshot`; 44 px targets; 360 × 800 and 1280 × 800, day and night; the existing tabs' screenshots
with Try-on off unchanged against R13's. **Control that must turn it red:** the engine stub that
throws, with the checklist hook removed (AVT-15 fails). **The rows' own controls (M8) that are
yours:** AVT-06 the slot's thumbnail stays W1's after the swap; AVT-11 the second figure's readiness
words are dropped; AVT-15 the checklist hook removed; row 388 the card left out of the reply (its
case fails). Until B's engine lands, run against I0's stub
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
| v13.1.2 | 17 Nov 2026, 17:50 IST | R13.1 | The owner's scope of 17 Nov 2026 (plan v13.1.3): row 388's card under a reply, opened by itself (`console-tryon-card.js`, `inline()`, the look by `?pieces=`, the section dressed by itself, its named test and control); See it on me for a garment he is thinking of buying (D22: its photo uploaded or shared in, type and colour from lists, the face refusal, the pairing, the confirm's words); the plan rows keep Show in 3D only (`seeOn` gone) | 🛠 Mark XXIII |
