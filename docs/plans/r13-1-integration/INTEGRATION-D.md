Version v13.1.2 · 18 Nov 2026, 00:45 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

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

## 9. Fix (review D-1)

Two fixers worked through `REVIEW-D-1.md` (2 HIGH, 7 MEDIUM, 12 LOW) on `r13-1-d`, each fix test
first (the failing test run and seen red for the reason expected, then the fix, then green). The
first was stopped by a server restart at about 22:55 IST after `db1cd28..d4fc120` (two refactors
and six fixes) and a saved work in progress (`f8d91e2`); the second checked that work and finished
(`ef4044b..f3d3f5c`). **Sections 2 to 8 describe the first build; where this section differs, this
section is right** (the line counts, "Needs I1", the screenshots).

### Every finding

| # | Finding | Outcome | Commit |
|---|---|---|---|
| H1 | Row 388's card 2,704 / 2,942 px tall | **Fixed.** A compact card (about 347 px): its title, the pieces in one line, the figure (150–260 px, B's minimum kept) beside Turn around, Show as a list, Open in Helpers (the full view) and Wearing it; one line a piece as a checklist; the reply's top kept in view as it lands unless he has moved the conversation. Tests: the card fits the conversation on a laptop and a phone, fresh and under way, with the reply and the whole stage in view | `01621e1` |
| H2 | "Wearing it" said "Enjoy the day." when `wear_log` refused | **Fixed.** Use this look and Wearing it report R13's answer in the viewer (executed, waiting for his OK, or refused in R13's words); the tab then reloads | `25c9a05` |
| M1 | A retry after a lost answer paid twice (a new `request_id` each confirm) | **Fixed.** One id per confirmed picture (its garment, his pieces, the rupees shown), kept while the answer may have been lost (no answer, a 5xx, 408, `busy`) and sent again by the next confirmed press ("Checking whether the last picture was made…"); a picture shown or a final refusal starts a new one; the whole press is one at a time. Test: the first answer reaches the fake and is dropped; the second press sends the same id; one picture, one spend; the next press a new id | `789f803` |
| M2 | Every press re-read every crop and flashed its alt text | **Fixed.** A crop is read once a page (page memory), shown at once when known, hidden until loaded; view presses redraw their own buttons only | `aecc9f8` |
| M3 | The garment he added was never shown back | **Fixed.** A 56 px image card from `door.garmentPhoto(id)` (read once a page) in each garment row, beside the pairing and in the ₹ confirm. Test: each decodes as a JPEG; one read | `291c2cb` |
| M4 | Raw "Choose File · No file chosen" | **Fixed** (the work in progress, checked: red on the code before it). A `.btn` over a hidden input, as Camera → Wardrobe and the paperclip do; "A photo is chosen (PNG, 4 KB)." never its name; the file input's CSS rule gone | `f8d91e2`, `ef4044b` |
| M5 | Keyboard focus lost after every press | **Fixed.** Each button has a stable key; the focus is found again after a redraw | `d289c3a` |
| M6 | A shared picture was dropped in silence when Try-on or See it on me was off | **Fixed in D's files alone.** `JarvisTryOnCard.garment()` checks first (JPEG or PNG, ≤ 25 MB, Try-on on, See it on me on) and throws the words; the tray as I0 wrote it keeps the item and shows them. No change in I0's tray is needed | `d4fc120` |
| M7 | With Try-on off, R13's plan rows still showed "Show in 3D" | **Fixed in D; two lines for I1** (below): `state()` and `jarvis:tryon-state` | `fba5a10` |
| L1 | The detail shots misled | **Done.** The new shots are viewport shots after the place is scrolled into view, and the card as it lands with no scrolling (below) | — |
| L2 | The See it on me picture in the shots couldn't decode | **Fixed in D's fakes.** D serves I0's See it on me routes from its own instance with a drawn PNG for a picture and a drawn JPEG for an I0 SOF-only garment photo | `789f803` |
| L3 | The status line lost `tr-status` | **Fixed** (`say()` puts it back) | `46af646` |
| L4 | A 503 hid the whole section | **Fixed.** Only a 404 is "off"; a 503 or no answer says "Try it on can't load right now." with Try again | `46af646` |
| L5 | A re-planned look kept its old pieces | **Fixed.** While he has not changed the look, a fresh load re-reads it by its plan or day and keeps the plan's picks current | `0e693ac` |
| L6 | Two stage-lifetime edges | **First fixed** (a stage that lands while its tab is hidden rests at once). **Second left:** old card viewers stay in page memory with their observer (now kept as `v.ro`) until the page goes; nothing a test can see, no WebGL context held (a new card already disposes the old card's stage), and `console-tryon.js` is at 599 of 600 lines. I1 can drop `!view.isConnected` viewers in `inline()` with its own size guard | `0e693ac` |
| L7 | No size check before decoding | **Fixed.** Over 25 MB is refused in words before decoding, in the picker, `take()` and the share hand-over | `f8d91e2`, `d4fc120` |
| L8 | Deletes on one press | **Fixed.** His photo (and YES), a picture and a garment photo each behind a `.bdialog` with Delete / Cancel; Cancel and Escape delete nothing | `f6a845a` |
| L9 | The ₹ confirm's question didn't say what it makes | **Not a defect at I1.** The confirm shows the estimate's own words, and C's are the plan's sentence (`wardrobe/seeme/texts.py` `CONFIRM`: "Make 1 picture of you in {garment}{mine}? {about}. {spent} of {cap} used this month."); only I0's fake says less. Composing it again in D would say it twice. Now the garment's photo is in the confirm too (M3) | — |
| L10 | The eval's controls accepted any failure | **Fixed.** Each control names the checks it must turn red (AVT-15 `checklist`, `why`; AVT-06 `thumbnail_w2`; AVT-11 `each_readiness`; row 388 `opened`, `pieces`, `covered`) and counts only with no error; `tests/test_r131_d_eval.py` | `2550204` |
| L11 | The door's proposed `make` posted any body | **Fixed in the proposal.** It sends only PictureIn's five fields, each checked (`tg_`, at most two `wi_`, `confirm_cost === true`, a finite `inr_shown` ≥ 0, `tq_` + 16 hex); anything else is refused before a byte is sent. Still three lines within the 165-line guard; if I1 raises that guard (I0's seam test) to 170 the same code splits into readable lines | `9ed55a9` |
| L12 | Smaller things | **Fixed:** "No photo yet" said once (`d3053a9`); `M.why` declared (`789f803`); no "Loading the look…" beside its error (`46af646`); `when()` shared (`4469d33`). **Left:** the small builders (`btn`, `field`, `select`) written in two of D's modules and R13's hook: See it on me also runs without the hook's `ctx`, so sharing them is a refactor for I1, not a fix. `console-tryon.js` was given room by moving pure helpers and word tables to the list module (`7f269b5`, `4469d33`, `2c3bf19`); it is at 599 of 600 lines, so the measurements form, shapes and OPS-05 (about 80 lines) should move to a module of their own at I1, which owns `arch_coverage.json` and the size guards | — |

### Also fixed while verifying

- **B's `forced`** (INTEGRATION-B section 8, "Needs I1" 1): when `show()` answers `forced: {top: 'tucked'}` the section says "Drawn tucked into the white mundu: the figure can only show it this way." in place of Tuck in / Untuck, and the card says it under its pieces; what he asked stays his. D's fake engine answers `forced` by B's rule (`2c3bf19`).
- **B's 30 s for files** ("Needs I1" 3): while `stats()` says `state: 'loading'`, D's watch waits up to 30 s more behind B's own clock ("Still preparing the 3D view: its files are on their way…"); an engine that says nothing keeps the 10 s rule (`bf6a969`). B's ≥ 150 px host ("Needs I1" 2) was already pinned (`test_r131_d_look.py`, `ENGINE_MIN_PX`).
- **A queued `close` event answered the next confirm** (the eval's See it on me case failed 2 of 25 runs): Cancel then See it on me before the dialog's close task ran made nothing. `ask()` now ignores a close event while its dialog is open again. A deterministic Node test (`d_dom.mjs` `stale_close`) was red, then green; the case then passed 30 of 30 (`bb6956e`).
- **I0's seam pin on `export function garment(file)`** failed since `d4fc120` (it became `async`): a plain function returning the hand-over's promise again (`f3d3f5c`).

### Needs I1 (now; replaces section 6, items 1 and 3)

1. **The door's three lines** (`console-r7-send.js`, 162 → 165 lines; `tests/test_r131_d_door.py` holds every pin, and the browser tests serve exactly this through `r131_fakes_d.patched_door()`):

   ```diff
   --- a/src/jarvis/api/static/console-r7-send.js
   +++ b/src/jarvis/api/static/console-r7-send.js
   @@ -159,4 +159,7 @@
    }
    const line = () => 'Pictures sent from this device today: ' + readCount();
    
   -if (M) M.part('send', Object.freeze({ canAsk, ask, attach, vault, wardrobe, tag, thumb, drop, person, garment, picture, garmentPhoto, myPhoto, sentToday: readCount, line }));
   +// R13.1 D (I1): See it on me's press (PictureIn's five fields, each checked), Keep, the deletes and the garment list: ids checked, JSON only
   +const SEE = /^t[pg]_[0-9a-f]{12}$/, seeme = (p, o) => window.JarvisConsole.api('/v1/seeme/' + p, o), garments = () => seeme('garments'), five = (b) => (b && /^tg_[0-9a-f]{12}$/.test(String(b.garment)) && Array.isArray(b.pieces) && b.pieces.length <= 2 && b.pieces.every((p) => PIECE.test(String(p))) && b.confirm_cost === true && Number.isFinite(b.inr_shown) && b.inr_shown >= 0 && /^tq_[0-9a-f]{16}$/.test(String(b.request_id)) ? { garment: b.garment, pieces: b.pieces.slice(), confirm_cost: true, inr_shown: b.inr_shown, request_id: b.request_id } : null);
   +const make = (b) => (five(b) ? seeme('pictures', { body: five(b) }) : no()), keep = (id, on) => (SEE.test(String(id)) && id[1] === 'p' ? seeme('pictures/' + id + '/keep', { body: { keep: on === true } }) : no()), forget = (id) => (id === 'photo' ? seeme('photo', { method: 'DELETE' }) : SEE.test(String(id)) ? seeme((id[1] === 'p' ? 'pictures/' : 'garments/') + id, { method: 'DELETE' }) : no());
   +if (M) M.part('send', Object.freeze({ canAsk, ask, attach, vault, wardrobe, tag, thumb, drop, person, garment, picture, garmentPhoto, myPhoto, make, keep, forget, garments, sentToday: readCount, line }));
   ```
2. **I0's hook, two lines** (M7; `console-helpers-wardrobe.js` 301 → 302 of 306; `r131_fakes_d.patched_hook()`; the browser tests serve it):

   ```diff
   --- a/src/jarvis/api/static/console-helpers-wardrobe.js
   +++ b/src/jarvis/api/static/console-helpers-wardrobe.js
   @@ -126,7 +126,7 @@
   -  if (!p.cancelled) box.append(acts(btn('Show in 3D', () => tryOn(p.id)))); // R13.1 D1: free (See it on me is for a garment to buy, D22)
   +  if (!p.cancelled && UI.tryon && UI.tryon.state && UI.tryon.state() === 'on') box.append(acts(btn('Show in 3D', () => tryOn(p.id)))); // R13.1 D1: free, while Try-on is on
   @@ -297,5 +297,6 @@
      document.addEventListener('jarvis:ready', () => { if (UI.host) load(); });
   +  document.addEventListener('jarvis:tryon-state', () => { if (UI.host && UI.outfits) draw(); }); // R13.1: Show in 3D follows it
   ```
3. **Unchanged from section 6:** items 2 (the browser tests on the wired app and B's real engine; D's fake now also answers `forced` and a slow `state: 'loading'` like B's), 4 (`keep_days`), 5 (the fresh-context reviews: this fixer could not start another agent either; review D-2 should read `console-tryon-me.js` `press`/`make`/`forget`/`ask` and the door diff above first) and 6 (the eval's needs).
4. **New:** L6's second edge and L12's module split, as in the table.

### The checks at `f3d3f5c` (18 Nov 2026, behind `/tmp/jarvis-heavy.lock`)

| Check | Result |
|---|---|
| Browser, Python 3.13 + Playwright (`JARVIS_BROWSER_TESTS=1`), one file at a time | card **14**, section **18**, seeme **14**, stage **11**, look **15**: **72 passed** at the head. Earlier in the session one run of stage + look had one failure, `test_show_in_3d_follows_try_ons_state_even_when_the_tab_draws_first[on]` (the first fixer's M7 test; its route handler sleeps 1.5 s), which passed alone and in three later runs |
| Unit (`test_r131_d_static`, `_logic`, `_door`, `_eval`), Python 3.12 and 3.11 | **42 passed** on each |
| `evals/r13_1/run.py --mock --part console` (`/tmp/venv-b`) | **13/13**; the negative control failed the part; each of the four controls turned exactly its own checks red with no error (AVT-15 `checklist`, `why`; AVT-06 `thumbnail_w2`; AVT-11 `each_readiness`; row 388 `opened`, `pieces`, `covered`). The See it on me case alone: 30 of 30 after `bb6956e` |
| `tests/test_r131_seams.py` + `test_r13_seams.py` | **495 passed** (the runner aside); the runner and gate cases **3 passed** |
| `ruff check`, `ruff format --check` | clean on the 11 Python files changed since `db1cd28` |

**Sizes now:** `console-tryon.js` 599 (600), `-list` 222 (300), `-me` 371 (400), `-photo` 91 (300), `-card` 97 (150), CSS 56 (200 in all).

### Screenshots (not committed: drawn data, the fake engine's labelled stand-in)

`/tmp/r131-d-shots/` (36 PNGs; the first build's 76 are in `before-fix/`), each at 1280 × 800 and 360 × 800, by night and by day, the viewport after the place is scrolled into view:
`01-card-as-it-lands-*` (no scrolling at all: his reply and the whole figure), `02-section-3d-*`, `03-section-checklist-*` (no WebGL2), `04-card-checklist-*`, `05-seeme-garment-picker-*` (the styled button, "A photo is chosen (PNG, 4 KB).", the lists, the garment row's photo), `06-seeme-pairing-*`, `07-seeme-yes-*`, `08-seeme-rupee-confirm-*` (with the garment's photo), `09-seeme-picture-*` (a drawn picture that decodes).
Looked at by the fixer: the card fits beside the reply on both sizes; the look is the console's own; nothing scrolls sideways. On a laptop the garment row's words wrap in a narrow column beside its image and two buttons (the existing `.hp-row`); legible, left as it is.

**Not verified here:** B's real figure (every shot and test uses D's fake engine), his phone, a real photo; the fresh-context reviews.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.0 | 17 Nov 2026, 18:20 IST | R13.1 | The plan, before the code | 🛠 Mark XXIII |
| v13.1.1 | 17 Nov 2026, 21:00 IST | R13.1 | Status Current: what was built (files and line counts), the checks with their numbers, the WIP's fixes, deviations (the eval by behaviour in Node), what D needs from A, B and C, Needs I1 (the door's three lines as a diff, the wired-app browser run, the Try-on-off plan button, `keep_days`, the reviews, the eval's needs), limits, the screenshots | 🛠 Mark XXIII |
| v13.1.2 | 18 Nov 2026, 00:45 IST | R13.1 | Section 9, Fix (review D-1): every finding's outcome with its commit (2 HIGH and 7 MEDIUM fixed; 10 LOW fixed, L9 not a defect at I1, L6 and L12 in part left with reasons), B's `forced` and 30 s for files honoured, a dialog race and an I0 seam pin found while verifying and fixed, Needs I1 now (the door's three checked lines, the hook's two), the checks at the head, the new screenshots | 🛠 Mark XXIII (fix D-1) |
