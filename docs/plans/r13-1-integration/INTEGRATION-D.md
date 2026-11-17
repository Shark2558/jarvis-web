Version v13.1.1 · 17 Nov 2026, 21:00 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — Part D: Console and phone (INTEGRATION-D)

Builder D's notes for I1 (branch `r13-1-d`, from `r13-1-i0` @ `eb8b7e4`). Plan:
`docs/plans/r13-1-try-on.md` v13.1.3 (D1, D4, D7, D8, D9, D11–D13, D16, D21, D22); brief:
`BRIEF-COMMON.md` v13.1.2 and `BRIEF-D.md` v13.1.2. The first builder was stopped by a server
restart; the Workshop saved its work as `2761e9d`. A second builder ran that work (its 27 browser
tests were green), reviewed it, fixed what was wrong and finished the part.

## 1. The plan (written before the code)

What D builds, all inside its own files (`console-tryon.js`, `console-tryon-list.js`,
`console-tryon-me.js`, `console-tryon-photo.js`, `console-tryon-card.js`, `console-tryon.css`), in
this order, each behaviour test first:

1. **The fakes** (`tests/r131_fakes_d.py`): D's routes ahead of I0's fake server (a plan in
   "Today and tomorrow", drawn crops for the image cards, a jacket in the laundry, both watches
   with photos, a recording tools route, a fake `/v1/chat` that answers "what should I wear?"
   with I0's real `TryOnCard` builder, a reset hook), and a contract-keeping fake engine
   (`tests/fixtures/r13_1/d_engine.mjs`: records every call, honours `__glFail`, draws a labelled
   stand-in), loaded in the browser in place of B's file by Playwright's routing only.
2. **Row 388** (`console-tryon-card.js`, `inline()`): a reply's `tryon` card opens the figure
   under the reply with no tap, dressed through `GET /v1/tryon/look?pieces=`; a private slot
   covered; the checklist under `__glFail`; a spoken reply the same; no card, nothing drawn; one
   stage on the page.
3. **The viewer and AVT-15** (`console-tryon.js`, `console-tryon-list.js`): the section opens
   dressed in the first look by itself; the stage; the checklist when 3D can't run (no WebGL2,
   a lost context, an asset, a 10 s first render, I0's throwing stub), with each piece's image
   card and readiness, Change, Wearing it (confirm first after a swap), Use this look, Retry 3D
   once a page.
4. **The controls** (D7): Front, Side, Back, Turn around, Closer look, zoom, Full screen; tuck,
   open, layers; swap with readiness words, Remove, undo (≤ 20); compare (one `show` with two
   figures, two lists with readiness), Save this comparison, saved comparisons re-opened.
5. **The measurements form** (D4) and the template choice (AVT-05), Delete all my try-on data
   (OPS-05, `JarvisPrivacy.remove('tryon_all')`).
6. **Save a picture of this look** (D9): the caption lines to `snapshot({caption})`, previewed
   from a `data:` URL, saved to Downloads.
7. **See it on me** (`console-tryon-me.js`, D11–D13, D22): the new garment's photo (file or the
   share tray), type and colour from lists, the device check, the pairing, his photo panel
   (`console-tryon-photo.js`, the third pixel panel), the YES dialog, the ₹ estimate and
   `.bdialog` confirm (Cancel sends nothing), progress, the picture with its words, Keep and
   delete, his garment photos.
8. **The eval** (`evals/r13_1/console.py`), the screenshots, the reviews, this file.

## 2. What was built (head of `r13-1-d`)

### The console (D's six files; the look unchanged: existing components, `var(--…)` only)

| File | Lines (limit) | What it does |
|---|---|---|
| `static/console-tryon.js` | 592 (600) | The section in Helpers → Wardrobe, mounted ONCE, opening dressed by itself in the first look "Today and tomorrow" shows (a plan's, else `?day=`); `open(plan)` (Show in 3D), `inline(el, card)` (row 388), `garment(file)` (D22). A viewer per place (the section, each card) holds one look on B's stage through the engine contract only: Front, Side, Back, Turn around (still under Motion Off, with the words), Closer look, zoom, Full screen (only where `requestFullscreen` exists); tuck, open, layers; swap with each option's fresh readiness, Remove, undo ≤ 20 in page memory; compare (one `show()` with two figures), Save this comparison, saved comparisons re-opened; the measurements form (six whole-cm fields, range words, typed or estimated, Use these / Keep the current); each piece's shape (AVT-05, `PUT /v1/tryon/assets/{piece}`); Delete all my try-on data (Privacy's own delete of `tryon_all`); Save a picture of this look (B's `snapshot({caption})`, previewed from a `data:` URL, Downloads); Use this look (A's confirm) and Wearing it (the confirm first after a swap, L10, then R13's `wear_log`). ONE stage on the page: the viewer taking it gives the other's back ("Show it here"); a viewer whose tab hides (another Helpers tab, the panel shut: a ResizeObserver), the page hidden or `pagehide` gives the context back and takes it again when shown. The checklist by itself on no WebGL2, a lost context, a file failing its check, a first render over 10 s, or an engine that throws; Retry 3D once a page. "Show private basics" (R13 D10's row) names a private basic in his own checklist only; the figure and the caption never do; a card under a reply never offers it. With Try-on off the section takes no room, and Show in 3D says "Try it on is off on this server." |
| `static/console-tryon-list.js` | 139 (300) | The item list, which is the checklist (AVT-15): each slot, the piece's fixed words, its readiness, what is approximate, its image cards (the views kept, `door.thumb`), the useful view still missing with a way to Camera (AVT-04), Change with the slot's options and their readiness; two lists side by side for compare; `caption()` (D9: the day or the event's time, non-private pieces in fixed words, "Base layer (covered)", his labels only when ticked and never a private one, never an id); `draft()`. |
| `static/console-tryon-me.js` | 335 (400) | See it on me for a garment he is thinking of BUYING (D11–D13, D22): his photo (checked on the device, sent only by `door.person`), the garment's photo from a JPEG/PNG file or the share tray (no URL field; its file name never shown), its type (`NEW_TYPES`) and colour (R13's colours) from lists, the face refusal, `door.garment`; the pairing (R13's pick; swap or untick; every piece it would send is shown, never one in the garment's slot); his typed YES (`ConsentView.words`, `{typed, template_version}`); the estimate and the `.bdialog` confirm (Cancel sends nothing; Make the picture sends exactly PictureIn's five fields with a `tq_` + 16 hex id); progress; the picture with "Generated 2D style preview — not a photo; the fit is not exact", the made-at time, the ₹, the new garment's words, his pieces sent and not sent with their image cards, Content Credentials; Keep, delete; his garment photos with Delete; See it on me settings (his switch; his monthly limit, lowered at once, raised only after a `.bdialog` with the ₹ and about how many pictures). Refusals branch on `err.code`. |
| `static/console-tryon-photo.js` | 91 (300) | The third pixel panel (the scan module's rules, ASCII): `person(file, maxKb)` (one bitmap; exactly one person and at most one face; under 60 % of the height is advice; the models missing → nothing sent), `garment(file)` (the whole photo and four overlapping two-thirds: any face refuses), `decide()` (the decision alone, for tests on recorded outputs). |
| `static/console-tryon-card.js` | 63 (150) | Row 388: `window.JarvisTryOnCard = Object.freeze({ cards, garment })`; takes a reply's FIRST `tryon` card, cut to TryOnCard's checked fields (`wi_` ids, slot words, `op_` plan, a private slot with no id), and has `inline()` draw it under the reply with no tap; asks the server for nothing itself. |
| `static/console-tryon.css` | 48 (200) | Places only: the stage 480 px on a laptop and 56 vh on a phone (≤ 899 px); every button and switch in the section and the card 44 × 44 px on a laptop too; the two-column compare. |

### Tests, fakes, eval

| File | Lines | What it holds |
|---|---|---|
| `tests/r131_fakes_d.py` | 341 | D's routes ahead of I0's fake server; `serve_d(token)`; `patched_door()` (the door with the three lines proposed for I1) |
| `tests/fixtures/r13_1/d_engine.mjs` | 103 | A contract-keeping fake engine (records every call, honours `__glFail`, draws a labelled stand-in); never shipped |
| `tests/fixtures/r13_1/d_dom.mjs` | 247 | A small DOM to run D's real modules in Node by behaviour (the eval) |
| `tests/browser/test_r131_d_card.py` | 357 | Row 388 (typed, spoken, no card, no WebGL2, one stage) and AVT-15 (5 failure ways, Retry 3D once) |
| `tests/browser/test_r131_d_section.py` | 381 | The section opens dressed; AVT-02 … AVT-14's UI halves; OPS-05 |
| `tests/browser/test_r131_d_seeme.py` | 345 | D22 (lists, face refused, the share tray's hand-over), his photo (the real SSD and UltraFace on drawn figures), AVT-12 (YES, ₹, Cancel, the picture, thumbnails), the pairing, settings |
| `tests/browser/test_r131_d_stage.py` | 190 | The stage given back on tab hide, page hidden and `pagehide`; Full screen only where it exists; Motion Off; a fresh load keeps the cards; private basics; one stage for a second look |
| `tests/browser/test_r131_d_look.py` | 162 | 44 px targets (1280 and 360 wide); the stage 480 px / 56 % by night and day, no sideways scroll; row 388 on a phone; Try-on off laid out as R13's; Show in 3D says so when off |
| `tests/test_r131_d_static.py` | 117 | D's static rules (17 cases) |
| `tests/test_r131_d_logic.py` | 225 | The photo decision, the caption, the card's check, in Node (16 cases) |
| `tests/test_r131_d_door.py` | 114 | The door's three proposed lines keep every pin and behave (3 cases) |
| `evals/r13_1/console.py` | 272 | The `console` part, BUILT (section 3) |

## 3. The checks (behind `/tmp/jarvis-heavy.lock`, one browser file at a time)

| Check | Result |
|---|---|
| Browser, Python 3.13 + Playwright (`JARVIS_BROWSER_TESTS=1`) | card 11, section 12, seeme 7, stage 9, look 9: **48 passed** (the run at the head is in section 7's last line) |
| Unit, Python 3.12 and 3.11 (`test_r131_d_static`, `_logic`, `_door`) | **36 passed** on each |
| Seams (`test_r131_seams.py`, `test_r13_seams.py`) | **501 passed** (the size guards, the pixel panels and drawing modules, the door the only caller of `/v1/seeme/photo|pictures|garments`, `console.html` byte-identical) |
| `evals/r13_1/run.py --mock --part console` (`/tmp/venv-b`, no Playwright) | **13/13 passed**, 42 s; the negative control failed the part: each of its four controls turned its own case red on its own check (AVT-15 `checklist`, `why`; AVT-06 `thumbnail_w2`; AVT-11 `each_readiness`; row 388 `opened`, `pieces`, `covered`) |
| The same with `JARVIS_R131_CONSOLE_BROWSER=1` and the Playwright Python | the look's browser cases added: **10/10** |
| `test_r131_seams.py -k "runner or gate"` (the whole R13.1 runner under plain pytest) | **3 passed**, 41 s |
| `ruff check`, `ruff format --check` | clean on every changed Python file (D has no `src` Python, so `mypy src` is unchanged) |
| Mutations | the Node tests: a face only one part finds, and a private slot's id passed on, each turn a case red |

Fixed in the WIP while finishing (each test first, red then green):
- **Two stages on the page.** A second look in the section ("Show in 3D", a saved comparison) mounted a SECOND stage without disposing the first: two WebGL contexts, two figures. `to3d()` now re-paints the stage the viewer holds.
- **A fresh wardrobe load dropped reference cards** (the crops' list was cleared and not re-read before the redraw).
- **Show in 3D with Try-on off did nothing** (the off check sat behind the "still loading" return).
- **The stage was never given back on tab hide.** This was not handled; the first try with IntersectionObserver failed: the Helpers panel's scroll container makes it report the section as out of view while on screen. Now a ResizeObserver plus the rendered check, and `pagehide` / `pageshow`.
- **The pairing could send a piece it didn't show** (one in none of the look's slots).
- **A piece with no photo showed a broken image** in the picture's list ("No photo yet" now).
- **The private-basics switch had no words beside it**: it now sits in R13's "Private basics" row.

## 4. Deviations from the plan and the brief, with reasons

1. **The eval runs by behaviour in Node, not in a browser.** The brief calls the `console` suite "browser", but I0's `tests/test_r131_seams.py` runs the whole R13.1 runner under plain pytest (300 s, no Playwright) and BRIEF-COMMON's own command runs it with `/tmp/venv-b` (no Playwright). A browser-only part failed both (`4f0ac43`, fixed in `5f9468c`). As R13's `phone` part did, it runs D's REAL modules in Node over `d_dom.mjs` against D's fake server. The cases that need a real page are the browser tests in CI's browser job, and `JARVIS_R131_CONSOLE_BROWSER=1` adds them to the part: 44 px, the sizes by night and day, Try-on off, and a spoken reply.
2. **Spoken replies** reach `cards()` through `console.js` exactly as typed ones do. The browser test drives `JarvisChat.send(t, {channel: 'voice'})`, not the microphone.
3. **`tryon_keep_days` is not drawn.** `SeeMeView` does not carry the current value, so a control for it could only show a guess. See section 6, item 4.
4. **Drag, pinch and the keyboard turn the figure on B's own canvas** (B's controls). D's Front, Side and Back call `view(name)`.

## 5. What D needs from A, B and C

- **A:** `GET /v1/tryon/look` must accept `?pieces=…&plan=…` together. After a swap in a plan's look, D sends the plan's pieces with the plan; the pieces win, and the plan is the context for readiness, so its own reservation isn't a draft. D also sends `&private=1` with `?plan=` / `?day=` once he taps "Show private basics" (A's contract: the private slot's piece only then). `POST /v1/tryon/saved` takes `{looks: [SavedLook, SavedLook]}`. `GET /v1/tryon`'s `assets` carries his shape choices (D re-reads it after a `PUT`). If A chose otherwise, D's `query()` is one line.
- **B:** the engine contract as pinned. `stats().triangles > 0` once the first frame is drawn (D's 10 s watch reads it). `dispose()` frees everything, and a second `mount()` after it works (D disposes on tab hide and remounts). `onLost()` for a lost context, an asset failure or the governor (D reads any reason as the checklist). `snapshot({caption})` resolves to a PNG Blob. D never calls `spin(true)` under Motion Off.
- **C:** `SeeMeView` as in the contract (`photo_max_kb`, `typical_inr`, `month.cap_inr`, `consent.words` and `version`). Refusals keep `{error, detail}`: D branches on `consent_needed` and `price_changed` and shows `detail` for the rest. `Pairing.pieces` never names a private piece or one in the garment's slot (D drops the latter anyway).

## 6. Needs I1

1. **The door's three lines** (`console-r7-send.js`, I0's file; D never edits it). The seam tests let ONLY the door name `/v1/seeme/photo|pictures|garments`, and the door has no call for the paid press, Keep, the deletes or the garment list. Until these lines are in, See it on me's press, Keep and Delete say "This arrives with the next JARVIS update." and send nothing, and the garment list is not drawn. The diff keeps every pin on the door (162 → 165 lines, the ≤ 165 guard). `tests/test_r131_d_door.py` holds it, and the browser tests serve exactly this through `r131_fakes_d.patched_door()`:

   ```diff
   --- a/src/jarvis/api/static/console-r7-send.js
   +++ b/src/jarvis/api/static/console-r7-send.js
   @@ -159,4 +159,7 @@
    }
    const line = () => 'Pictures sent from this device today: ' + readCount();
    
   -if (M) M.part('send', Object.freeze({ canAsk, ask, attach, vault, wardrobe, tag, thumb, drop, person, garment, picture, garmentPhoto, myPhoto, sentToday: readCount, line }));
   +// R13.1 D (I1): See it on me's press (ids and the rupees he confirmed), Keep, the deletes and the garment list: ids checked, JSON only
   +const SEE = /^t[pg]_[0-9a-f]{12}$/, seeme = (p, o) => window.JarvisConsole.api('/v1/seeme/' + p, o), make = (b) => seeme('pictures', { body: b }), garments = () => seeme('garments');
   +const keep = (id, on) => (SEE.test(String(id)) && id[1] === 'p' ? seeme('pictures/' + id + '/keep', { body: { keep: on === true } }) : no()), forget = (id) => (id === 'photo' ? seeme('photo', { method: 'DELETE' }) : SEE.test(String(id)) ? seeme((id[1] === 'p' ? 'pictures/' : 'garments/') + id, { method: 'DELETE' }) : no());
   +if (M) M.part('send', Object.freeze({ canAsk, ask, attach, vault, wardrobe, tag, thumb, drop, person, garment, picture, garmentPhoto, myPhoto, make, keep, forget, garments, sentToday: readCount, line }));
   ```
2. **Move D's browser tests to the wired app** (I0-NOTES section 5, item 2). The tests route `/static/console-tryon-3d.js` to D's fake engine. Run them once on B's engine too (`fake_engine=False` and real WebGL in Chromium), and run row 388 end to end through the mock brain. Test console-only on the garment, photo and picture routes there.
3. **With Try-on off, I0's plan rows still show "Show in 3D"**: the one visible difference from R13's Wardrobe tab (D's section itself takes no room; pressing the button says why). A proposed one-word change to I0's hook (`console-helpers-wardrobe.js:129`): `if (!p.cancelled && !(UI.secs.tryon && UI.secs.tryon.hidden))`. The tab's next draw then leaves the button out.
4. **`keep_days`:** if he should change it in the console, C adds `keep_days` to `SeeMeView`, and D draws a 1–30 control beside the limit (`PUT /v1/seeme/settings {keep_days}`).
5. **The reviews.** `code-reviewer`, `python-reviewer` and the REQUIRED `security-reviewer` (the pixel panel, the door) were not run in a fresh context. This builder had no way to start another agent. The Workshop should run them on `eb8b7e4..r13-1-d`. Read first: `console-tryon-card.js` `checked()`, `console-tryon-photo.js`, `console-tryon-me.js` `press`/`make`/`limit`, and the door diff above.
6. **The eval at I1:** `evals/r13_1/console.py` needs `node` (as R13's `phone` part does). Set `JARVIS_R131_CONSOLE_BROWSER=1` with a Playwright Python (`JARVIS_BROWSER_PYTHON`) for the full browser half.

## 7. Known limits and what could not be verified here

- **B's real figure:** every 3D test and screenshot uses D's fake engine (a flat, labelled stand-in). The figure itself, its triangles, its timing on his phone's GPU and real context loss are B's, and I1's to check together.
- **His real full-length photo:** the person and face checks ran on drawn figures (the real SSD and UltraFace fired on them). A real photo, a child's photo and a shop photo with a small face remain the pilot's. The decision logic is tested on recorded outputs.
- **The share tray on his phone:** the hand-over (`JarvisTryOnCard.garment(file)`) is tested from the page, not from Android's share sheet.
- **Fullscreen and Escape** are the browser's own. Only the button's presence is tested; there is no iPhone here.
- **The picture in the screenshots shows as broken**: I0's fake provider PNG is a signature and text, not a decodable image. D shows whatever `door.picture()` returns as a `data:` URL.
- **Swapping shoes** replaces the pair with the chosen piece. A's look decides the pair, or says "Draft: one shoe missing".

## 8. Screenshots (not committed: drawn data only, the fake engine's stand-in)

`/tmp/r131-d-shots/` has 76 PNGs, made at laptop (1280 × 800) and phone (360 × 800) width, by night and by day:
- `01-section-3d-*` (the section opened dressed by itself), `02-compare-*`, `03-measurements-*`;
- `04-card-opens-by-itself-*` (row 388 under a reply);
- `05-card-checklist-*` and `06-section-checklist-*` (AVT-15, no WebGL2);
- `07-seeme-garment-and-pairing-*`, `08-seeme-yes-consent-*`, `09-seeme-rupee-confirm-*`, `10-seeme-picture-*`, `11-seeme-raise-limit-*`.

`*-detail.png` files are element shots, and some of them are cropped by the panel's scroll; the full-viewport shots are the ones to judge. They were looked at: the look is the console's own in both surfaces. That review found two defects, both fixed above: the private-basics switch had no words, and a no-photo piece showed a broken image.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.0 | 17 Nov 2026, 18:20 IST | R13.1 | The plan, before the code | 🛠 Mark XXIII |
| v13.1.1 | 17 Nov 2026, 21:00 IST | R13.1 | Status Current: what was built (files and line counts), the checks with their numbers, the WIP's fixes, deviations (the eval by behaviour in Node), what D needs from A, B and C, Needs I1 (the door's three lines as a diff, the wired-app browser run, the Try-on-off plan button, `keep_days`, the reviews, the eval's needs), limits, the screenshots | 🛠 Mark XXIII |
