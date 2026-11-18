Version v13.1.1 · 17 Nov 2026, 21:45 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII (review D-1)

# R13.1 Part D review 1 (fresh context): security, code and look

Reviewed: branch `r13-1-d` @ `bdc17ab` against its base `r13-1-i0` @ `eb8b7e4` (`git diff eb8b7e4..HEAD`,
19 files, +4,255 −61), as `security-reviewer`, `code-reviewer` (frontend) and visual reviewer, against
`BRIEF-COMMON.md` v13.1.2, `BRIEF-D.md` v13.1.2, `INTEGRATION-D.md` v13.1.1 (section 6 included),
`I0-NOTES.md`, the plan `docs/plans/r13-1-try-on.md` v13.1.3 (D1, D4, D7–D9, D11–D13, D16, D21, D22) and
his success checks for rows 350, 353–363, 365, 366 and 388. The reviewer did not build Part D and changed
no code: this file is the only change.

## Verdict

**WARNING: changes requested before I1 takes the branch.** No CRITICAL. Two HIGH (row 388's card is
far too tall to show the figure it opens, and "Wearing it" says "Enjoy the day." when R13's tool refused)
and seven MEDIUM. The security core holds: no untrusted text reaches the DOM except as text, no
`innerHTML`, no inline handler or style, nothing from a CDN, the card is read field by field, a private
slot never reaches the figure, a query, a caption or a list outside his own panel, every picture is
behind his typed YES and a ₹ confirm whose Cancel and Escape send nothing, and the page holds one WebGL
stage at a time. The two HIGH and M1–M7 are each a few lines in D's own files (M6 and M7 also need a
line or two in I0's files at I1).

| Grade | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 2 |
| MEDIUM | 7 |
| LOW | 12 |

## How this was checked

- Read every line of D's six console files, the card hook in `console-media.js`, I0's door
  (`console-r7-send.js`), I0's hook (`console-helpers-wardrobe.js`), the builders in
  `console-helpers.js`, the share tray's hand-over (`console-r7-share.js:174–175, 191`),
  `JarvisPrivacy.remove`, `JarvisConsole.api`, D's fakes, the fake engine, the Node DOM and the eval.
- Looked at the Workshop's 76 PNGs, and made new evidence with a review probe (Playwright, the
  browser tests' Python, D's own fake server and fake engine, drawn data only; not committed): the panel's
  computed background by night and day, R13's own sections and the Today tab in the same place, the
  card as it lands on a laptop and a phone (sizes measured), images right after a control press, the
  requests a press makes, keyboard focus after a press, and "Wearing it" against a refusing `wear_log`.
- Ran, behind the shared heavy-run lock: D's unit tests (`test_r131_d_static`, `_logic`, `_door`):
  **36 passed** (Python 3.11); the browser file `tests/browser/test_r131_d_card.py`: **11 passed**
  (136.7 s); `evals/r13_1/run.py --mock --part console`: **13/13**, the negative control failed the
  part, each of its four controls on its own checks (AVT-15 `checklist`, `why`; AVT-06 `thumbnail_w2`;
  AVT-11 `each_readiness`; row 388 `opened`, `pieces`, `covered`). Not run here: the other four browser
  files (37 tests; INTEGRATION-D reports them green) and the seam suites.

## What holds (checked)

- **XSS.** Every server word, piece word, garment word and card field reaches the page through
  `H.mk`/`H.row`/`H.note` (`textContent`, `txt()` strips and cuts) or an attribute; no `innerHTML`,
  `outerHTML`, `insertAdjacentHTML`, `eval` or `element.style` in D's files (grep). An `<img>` gets a
  `src` only when it is `data:image/(png|jpeg);base64,…` (`console-tryon-list.js:58`,
  `console-tryon-me.js:54, 197`, `console-tryon.js:401`), so an SVG or a stray URL is never loaded.
- **The card** (`console-tryon-card.js:19–30`) keeps only TryOnCard's fields, each matched (`wi_` +
  12 hex, slot words, `op_` plan, a code of letters), at most 12 slots and two pieces a slot; a private
  slot passes with no id; the first `tryon` card only, once a row; it asks the server for nothing itself.
  `test_r131_d_logic.py` pins a forged card.
- **Private pieces.** The figure gets `{slot, private: true}` and nothing else (`console-tryon.js:145`);
  private slots never enter a `?pieces=` query, a saved comparison, the confirm or See it on me
  (`pairs()` :59, :310, :360; `console-tryon-me.js:141–146`); the caption says "Base layer (covered)"
  (`console-tryon-list.js:134`); his own checklist names a private basic only behind "Show private
  basics", and the card never offers it (`console-tryon.js:224, 229`).
- **The paid flow.** "Make the picture" exists only in See it on me; nothing in `console-tryon.js` or
  the card can make a picture. Each press: his typed YES once (checked by the server: "yes" is refused),
  a fresh estimate, a `.bdialog` with the ₹; Cancel and Escape resolve to nothing sent
  (`console-tryon-me.js:269, 274–285, 307`); the body is exactly PictureIn's five fields with a
  `tq_` + 16 hex id from `crypto.getRandomValues`; `M.busy` stops a second press while one is in flight.
  The browser test asserts no POST after Cancel and the exact body.
- **Uploads on the device.** JPEG or PNG only by type before decoding; one bitmap; freed afterwards;
  bytes leave only through the door, which redraws them (EXIF gone) down to `photo_max_kb`
  (`console-tryon-photo.js:41–91`); a garment photo with any face is refused, also on four
  two-thirds crops.
- **One stage.** A viewer taking the stage gives the other's back; a hidden tab (ResizeObserver),
  a hidden page and `pagehide` give the context back; a second look reuses the same stage
  (`console-tryon.js:155–207`); `test_r131_d_stage.py` pins it.
- **Sizes.** `console-tryon.js` 592/600, `-list` 139/300, `-me` 335/400, `-photo` 91/300, `-card`
  63/150, CSS 48/200; no function over 50 lines; the CSS uses only `var(--…)` for colour and radius.

## The Workshop's four notes, judged

| Note | Judgement | Evidence | Finding |
|---|---|---|---|
| (1) Raw "Choose File · No file chosen" in See it on me | **A defect.** The console chooses a photo with a themed button over a hidden input | shots `07-seeme-garment-and-pairing-*`, `09-seeme-rupee-confirm-*`; `console-wardrobe-scan.js:144`, `console-camera-panel.js:211`, `console.html:169` | M4 |
| (2) "GOOD MORNING" and chips show through the Helpers panel | **Not new: the console's own night card.** The panel is `rgba(7, 12, 20, 0.9)` with no backdrop blur at night (`console.css:63`, `console-deck.css:114–116`: "Night cards are 90 % opaque"), `rgba(255, 255, 255, 0.9)` with `blur(14px)` by day (computed in the probe). R13's own Laundry and Pieces sections and Helpers → Today show the same lines through at the same place (probe shots `r13-laundry-section-laptop-night.png`, `helpers-today-tab-laptop-night.png`). The panel CSS is byte-identical to `main` (`git diff origin/main..HEAD` on `console.css`, `console-deck.css`, `console-helpers.css`, `console-media.css`, `console-wardrobe.css` is empty). The `*-detail.png` shots exaggerate it: an element shot of a section taller than its scrolled panel captures the page outside the panel's clip | L1 (the shots only) |
| (3) Photo slots show "Front photo", "Detail photo" alt text | **Two causes, only one is the fakes.** D's fakes serve real 48 × 48 drawn PNGs for crops (settled: `naturalWidth` 48). The alt text is D's own render: 50 ms after pressing Side, all four `img.tr-thumb` have no `src` (Chromium paints the alt and a broken-image icon) because every redraw rebuilds the list and fetches every crop again (12 requests for three view presses). The broken See it on me picture (`10-seeme-picture-*`, `naturalWidth` 0) IS a fake: I0's provider PNG is a signature and text (`tests/r131_fake_tryon.py:29`) | M2 (render), L2 (fake) |
| (4) The card under a reply fills the conversation | **Yes, and worse than "fills": 2,704 px tall on a laptop, 2,942 px on a phone.** The reply text stays visible as it lands (100 %), but 43 % (laptop) / 50 % (phone) of the figure shows and none of its controls | probe numbers below; shots `card-as-it-lands-*-night.png`. The Workshop's `04-card-*` shots were taken after `scroll_into_view_if_needed()`, so they hide the reply | H1 |

## CRITICAL

None.

## HIGH

### H1 · Row 388's card is 5.8 conversation-heights tall: as it lands, half the figure and none of its controls show

**Where:** `console-tryon.css:8` (`.tr-stage{height:480px}`) and `:44` (`56vh`) apply to the card as well as
the section; `console-tryon.js:210–231` `draw()` gives a card everything the section has: three rows of
buttons, the full checklist with every reference card, "No back photo of it yet … Open Camera" per piece.
The card sits in the media cards' narrow `.mcard` (≈ 285 px wide on a laptop).

**Measured** (probe, D's fake server, "what should I wear today?", night, no scrolling after the reply):

| | Conversation viewport | Card | Stage seen | Tools seen | Reply text seen |
|---|---|---|---|---|---|
| Laptop 1280 × 800 | 467 px | 2,704 px | 43 % | 0 % | 100 % |
| Phone 360 × 800 | 484 px | 2,942 px | 50 % | 0 % | 100 % |

**Failure:** his row 388 words are "open up the card, decide and show me on the 3D model". What he sees is
the reply, the card's title and the figure's head and shoulders; Front/Side/Back, "Show as a list" and
"Wearing it" are 400–600 px below, and the card then pushes every later message 2.7k px down. The brief's
480 px / 56 % is the **section's** stage (BRIEF-D section 2, plan D1); the plan gives the card no size.

**Fix (D's files):** a compact card. `.tr-card .tr-stage{height:min(320px,40vh)}`; in `draw()` for
`v.kind === 'card'`: tools in one row (Front, Side, Back, Turn around, Show as a list), tuck/open/layers
and Compare behind one "More" button, the pieces as one line each (slot, words, readiness; no reference
cards, no Camera prompts: those stay in the section), "Use this look" / "Wearing it" kept, plus "Open in
Helpers" (`open(plan)`) for the full view. After the first paint, if he has not scrolled, keep the reply's
top in view. **Test:** in `test_r131_d_look.py`, on both sizes, the landed card is ≤ 1.2 × the
conversation's height, the whole stage is visible once the reply's row is scrolled to the top, and the
reply text is visible; replace the phone test's 56 % pin for the card.

### H2 · "Wearing it" says "Enjoy the day." when R13's `wear_log` refused

**Where:** `console-tryon.js:322`:

```js
if (S.ctx && typeof S.ctx.tool === 'function') { await S.ctx.tool('wear_log', args, 'Enjoy the day.'); say(v, 'ok', 'Enjoy the day.'); return; }
```

I0's `tool()` (`console-helpers-wardrobe.js:72–81`) returns nothing: it writes the outcome in the tab's
own note at the top of the Wardrobe tab and reloads.

**Failure (reproduced):** `wear_log` answering `{"status": "error", "message": "The navy shirt is in the
laundry, Sir."}` → the tab's note says the refusal (out of sight while the section is in view) and the
Try it on status says **"Enjoy the day."** with class `ok` (green). Whenever the Wardrobe tab has been
mounted (every section press, and a card's press after Helpers was opened) a refusal reads as success.
AVT-15's check ("the user can still confirm a ready outfit") depends on that word being true.

**Fix:** always use the direct path that already exists (`:323–326`, which reports `r.status` like
`confirm()`), then let the tab reload (`S.ctx.show(S.priv)` re-runs its load) — or I1 makes `tool()`
return `r` and D reports it. **Test:** the AVT-15 browser test with a refusing `wear_log` asserts the
refusal's words in the viewer's status and no "Enjoy the day.".

## MEDIUM

### M1 · A retry after a lost answer pays for a second picture: the `request_id` is new on every confirm

**Where:** `console-tryon-me.js:313` (`request_id: requestId()` inside `make()`), `:316–319`.
**Failure:** the server makes and settles the picture, the answer is lost (a dropped connection, a proxy
timeout inside the 120 s call, a 502/503 after sending) → "Can't reach JARVIS." → he presses again,
confirms the ₹ again, and a NEW `tq_` id makes and charges a second picture. The plan's replay
(D13.6: "`done {request_id: outcome}` answers a repeated `request_id` with the same result") never helps,
because D never repeats an id. The cap and his limit bound it to about ₹9–11 a time, which is why this is
not HIGH. **Fix:** keep `M.pending = {key: garment|pieces|inr_shown, id}`; after a non-final failure
(TypeError, 5xx, timeout) the next confirmed press with the same key reuses `id` ("Checking whether the
last picture was made…"); clear it on success or a final 4xx refusal; set `M.busy` at the top of
`press()` too (it now covers only `make()`). **Test:** Playwright lets the first `POST /v1/seeme/pictures`
reach the fake (`route.fetch()`) and then aborts its answer; the second press sends the same
`request_id` and the fake shows one picture and one spend.

### M2 · Every control press re-downloads every reference card and flashes its alt text

**Where:** `console-tryon-list.js:53–60` creates `<img>` with no `src` until the door's data URL arrives;
`console-tryon.js:210–231` `draw()` rebuilds the whole list on every `turn()` (:248), `spin()` (:241–247),
`restyle()` (:258), Undo and Change; `console-tryon-me.js:191–198` likewise.
**Measured:** 50 ms after Side, all four thumbs have no `src` (`complete`, `naturalWidth` 0: Chromium
draws "Front photo", "Detail photo" and a broken-image icon); three view presses made **12** requests to
`/v1/wardrobe/photos/…`. On his phone that is a visible flicker and wasted data on every press, and it is
what the Workshop's detail shots caught. **Fix:** a page-memory `Map` photo id → data URL (dropped on
`jarvis:wardrobe-fresh` and `reload()`; nothing stored on the device), set `src` at once when known; keep
the `<img>` `hidden` until it loads; Front/Side/Back, Turn around and zoom update only the tools row, not
the list. **Test:** after three view presses, zero new crop requests and no visible `<img>` without `src`.

### M3 · The garment he adds is never shown back

**Where:** `door.garmentPhoto(id)` is never called (grep over D's files; the probe saw no
`GET /v1/seeme/garments/tg_…`). The garment list (`console-tryon-me.js:137–138`), the pairing (:153)
and the ₹ confirm (:303) show only "a new navy shirt, not in your wardrobe". **Failure:** with two navy
shirts from two shops (up to 20 kept), the rows are identical and the confirm does not show which one is
sent to Google. BRIEF-D section 2 asks for it ("read back with `door.garmentPhoto(id)`"). **Fix:** a 56 px
image card (`.tr-ref`/`.tr-thumb`, the M2 cache) from `door.garmentPhoto(g.id)` in each garment row,
beside the pairing's title and in the confirm. **Test:** the D22 browser test asserts the row's image is a
`data:image/jpeg` and the confirm shows it.

### M4 · Raw browser file inputs ("Choose File · No file chosen") break the look

**Where:** `console-tryon-me.js:110–113` (his photo) and `:122–125` (the garment), `console-tryon.css:38`.
Shots `07-seeme-garment-and-pairing-*`, `09-seeme-rupee-confirm-*` by day and night. **The console's way:**
Camera → Wardrobe's "Choose a photo" is a `.btn` that opens the system picker (`console-wardrobe-scan.js:144`,
`console-camera-panel.js:211`); the paperclip is a button over the hidden `#attachInput`
(`console.html:169`). R13's one visible file input is the backup restore row, not a photo
(`console-helpers-wardrobe.js:238`). **Fix:** `input.hidden = true; input.tabIndex = -1;` plus
`btn('Choose a photo of you' | 'Choose a photo of the garment', () => input.click())`; after a choice, a
line "A photo is chosen (JPEG, 1.2 MB)", never its name (D22.4); drop the CSS rule at `:38`. **Test:** no
visible `input[type=file]` in `.tr-me` (static or browser); the 44 px test covers the buttons.

### M5 · Keyboard focus is lost after every control press

**Where:** `console-tryon.js:218–221`: `draw()` replaces every button. **Reproduced:** focus "Side",
Enter → `document.activeElement` is `BODY`. The same after Tuck, a layer, Undo, Change and Compare, so a
keyboard or screen-reader user starts again from the top of the page on each press. **Fix:** give each
button a stable `data-k` (label + slot); in `draw()`, if focus was inside `v.view`, focus the new button
with the same key (or update `aria-pressed` in place for the view and layer toggles instead of
rebuilding). **Test:** Enter on Side leaves focus on Side with `aria-pressed="true"`.

### M6 · A picture shared in is dropped without a word when Try-on or See it on me is off

**Where:** the share tray presses `await T.garment(f); await done(it)` (`console-r7-share.js:175`;
`done` deletes the shared item and closes the sheet, `:191`); `console-tryon-card.js:57–61` returns
nothing; `console-tryon.js:579–586` keeps the file in `S.file`. **Failure:** Try-on off → `start()` returns
at `:533`, See it on me is never loaded, the file is never used and the section is hidden; See it on me
switched off → `render()` (`console-tryon-me.js:77–78`) draws no garment rows, only "Say what it is and
its colour…"; a shared WebP shows only its alt text and is refused later (`console-tryon-photo.js:72`). In
every case the tray has already deleted it. **Fix (D):** `garment(file)` resolves `{ok, why}` after
checking Try-on on, See it on me on and JPEG/PNG, and says why when not; **(I1, one line in I0's tray):**
`const r = await T.garment(f); if (r && r.ok) await done(it); else` show `r.why`. **Test:** with Try-on off
the tray item stays and the words say why.

### M7 · With Try-on off, R13's plan rows still show "Show in 3D", and the proposed fix races

**Where:** I0's hook `console-helpers-wardrobe.js:129`; INTEGRATION-D section 6 item 3. BRIEF-COMMON
section 5: "the existing tabs' screenshots with Try-on off stay R13's". The proposed condition
`!(UI.secs.tryon && UI.secs.tryon.hidden)` holds only if D's `GET /v1/tryon` answers before the tab's four
reads (`:62–63`); when they answer first, the tab draws the button and keeps it until the next load.
`test_with_try_on_off_the_wardrobe_tab_is_laid_out_as_r13s` compares boxes within this build, so it
cannot see the button. **Fix:** D exports `state()` (`'on' | 'off' | 'unknown'`) and dispatches
`jarvis:tryon-state` after `readTryon()`; I1's hook draws the button only when `UI.tryon &&
UI.tryon.state() === 'on'` and redraws on the event (two lines in I0's file). **Test:** Try-on off → no
"Show in 3D" in any `.wd-plan`; turn `test_with_try_on_off_show_in_3d_says_so_and_loads_nothing` into
"has no Show in 3D".

## LOW

1. **L1 · The detail shots mislead.** `*-detail.png` are element shots of `.tr-view` / `.tr-me`, which are
   taller than the scrolled Helpers panel, so they capture the HUD and the conversation outside the
   panel's clip (note 2 above). For the next review, shoot the `.panel` (or the viewport) after
   `scroll_into_view_if_needed()`, and add one shot of the card as it lands without scrolling.
2. **L2 · The See it on me picture in the shots is a fake that can't decode** (I0's provider PNG,
   `tests/r131_fake_tryon.py:29`). D's own fakes can answer `GET /v1/seeme/pictures/{id}` ahead of I0's
   with `png((90, 110, 160), 96, 128)` (`tests/r131_fakes_d.py:76`), as they already do for crops; the
   shots then show the real layout. The same for the SOF-only `jpeg()` uploads if M3 draws the garment.
3. **L3 · The status line loses its class after its first message.** `H.note()` sets `className`
   (`console-helpers.js:54–58`), so `tr-status` (`console-tryon.js:90`; `.tr-status:empty{display:none}`,
   `console-tryon.css:11`) is gone and an emptied status keeps its margin. Re-add the class in `say()`.
4. **L4 · A 503 hides the whole section** (`console-tryon.js:79`: 404 or 503 → `S.off`). In the contract
   503 is "unavailable", not "off" (`wardrobe/tryon/http.py:74`). Hide on 404 only; on 503 say "Try it on
   can't load right now." with a way to try again.
5. **L5 · A re-planned look keeps its old pieces.** `jarvis:wardrobe-fresh` re-reads by the pieces shown
   (`console-tryon.js:125–131, 588`), so a plan changed from the chat shows the old pieces under the same
   plan, and "Use this look" confirms them. When `same(pairs(v.look), v.planPairs)` (no unconfirmed swap),
   re-read by `v.src`.
6. **L6 · Two stage-lifetime edges.** A stage mounted while its tab was hidden during the engine import
   (`console-tryon.js:163–171`) keeps the context (the ResizeObserver already fired): check
   `document.hidden || v.view.offsetParent === null` after the `await` and pause. Old card viewers stay in
   `S.views` with live observers for the life of the page (`:99–102`): disconnect and drop them once
   `!view.isConnected`.
7. **L7 · No size check before decoding.** `console-tryon-photo.js:41–48` and the garment preview
   (`console-tryon-me.js:53, 240`) decode or read any size; a very large PNG can exhaust a phone's memory
   before the door's limit applies. Refuse over, say, 25 MB in plain words first.
8. **L8 · Deletes on one press.** "Delete my photo and my YES" (it also withdraws his consent), a kept
   picture's Delete and a garment's Delete (`console-tryon-me.js:107, 138, 213, 221, 327–335`) have no
   confirm; the project's rule is a confirmation step for deletes. The Camera's kept results set the
   one-press precedent, hence LOW: reuse `ask()` with Delete / Cancel for the photo and a kept picture.
9. **L9 · The ₹ confirm's question doesn't say what it makes.** The title is "Make 1 picture?"
   (`console-tryon-me.js:306`); the plan's words (D13.3) are "Make 1 picture of you in a new navy shirt,
   with your charcoal trousers? About ₹9 with GST. ₹54.3 of ₹300 used this month." Compose the title from
   `M.garment.words` and `est.sent`. ("this month" and "₹0.00" come from C's words.)
10. **L10 · The eval's controls accept any failure.** `evals/r13_1/console.py:260` counts a control as
    red on any failure, so a copy that crashes, or Node missing ("node is not installed"), also "turns it
    red". Today each turns its own checks red (listed above). Map each control to the checks it must fail
    and require those, with no `error`.
11. **L11 · The door's proposed lines** (INTEGRATION-D section 6 item 1) are sound for `keep`, `forget`
    and `garments` (ids checked, JSON only, the door stays the one caller), but `make` posts any body
    although its comment says "ids checked": check `garment` (`tg_`), `pieces` (≤ 2 `wi_`), `request_id`
    (`tq_` + 16 hex), `confirm_cost === true` and a finite `inr_shown`, and pass only those five keys. The
    lines are packed past 200 characters to stay at 165; raising the guard to 170 reads better.
12. **L12 · Smaller things.** "No photo yet" then "No front photo of it yet: add one…" say the same twice
    (`console-tryon-list.js:68–71`); `M.why` is not declared in `M` (`console-tryon-me.js:29, 58`); a
    failed first look leaves "Loading the look…" beside the error (`console-tryon.js:223, 508, 577`);
    `when`, `failed`, `btn`, `field`, `select` and the FileReader-to-data-URL step are written twice in
    D's files and a third time in R13's hook, whose `ctx` already offers `field`, `select` and `when`;
    `console-tryon.js` at 592/600 has no room for H1, H2, M2 and M5: move the measurements form, the
    shapes and OPS-05 (`:413–494`, about 80 lines) into a module of their own, with a size guard I1 adds.

## Tests: do they pin the behaviour?

Mostly yes: the browser tests drive the real modules against the fake server and assert ids, bodies and
words exactly (PictureIn's five fields and `inr_shown` 8.9; Cancel sends no POST; the figure's slot →
piece ids; the covered base slot; one live stage), and the eval's four controls each fail their own
checks. Gaps, each tied to a finding: the landed card's size and what is visible (H1); a refused
`wear_log` (H2); a retried press (M1); requests and images after a press (M2); the garment's image (M3);
the file-picker buttons (M4); focus after a press (M5); the tray with Try-on off (M6); the plan button with Try-on off (M7).

## Next steps

1. D fixes H1 and H2 (and M2, M5, which touch the same `draw()`), each test first, on `r13-1-d`.
2. D fixes M1, M3, M4, M6's half and M7's half; I1 takes the two one-line changes in I0's files (tray,
   hook) with the door's lines.
3. Review D-2 on the new head: the probe's numbers again, the shots retaken as L1 says.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 21:45 IST | R13.1 | Part D review 1 on `r13-1-d` @ `bdc17ab`: verdict WARNING (0 CRITICAL, 2 HIGH, 7 MEDIUM, 12 LOW); the Workshop's four look notes judged with evidence (the night show-through is the console's own 90 % card; the alt text is D's redraw, the broken picture is I0's fake; the card is 2.7k–2.9k px); the checks run (36 unit, 11 browser, the eval 13/13 with its controls) | 🛠 Mark XXIII (review D-1) |
