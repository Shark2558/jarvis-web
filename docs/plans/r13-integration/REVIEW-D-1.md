Version v13.0.1 · 16 Nov 2026, 10:12 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI (fresh-context security + code review, Part D)

# R13 Part D (Phone and panel): security + code review 1

**Scope.** The reviewer did not write this code, and this is a fresh-context review.
- Branch `r13-d` @ `42574c6`, in the detached, read-only worktree `/tmp/rv-d-sec`.
- Diff `r13-i0..r13-d`: 26 files, +4,580 / -52.
- The review followed:
  - `.claude/agents/security-reviewer.md`, `code-reviewer.md` and `python-reviewer.md`;
  - `CLAUDE.md` and `.claude/rules/ecc/` (common and python);
  - the plan `docs/plans/r13-wardrobe.md` v13.0.2 (Part D, D5–D10, D20, H2, H5, H6) and `PLAN-REVIEW-1.md`;
  - `BRIEF-COMMON.md`, `I0-NOTES.md` and `INTEGRATION-D.md`;
  - the owner's use cases (OPS-01, OPS-06, INV-05–07, INV-10, LND-01–04);
  - a sample of the 28 screenshots in `/tmp/r13-d-shots/`.

**Verdict: WARNING (changes requested). No CRITICAL, 3 HIGH, 6 MEDIUM, 10 LOW.**

Most of the design holds:
- only the two named panels touch pixels;
- picture bytes leave only through the door's `wardrobe()` and `tag()`, after a press on a button that names the photo;
- the scan module uses `textContent` only, holds no storage, and makes no `fetch`;
- private pieces never get a photo, a fingerprint or a tag;
- OCR text and foreign QR payloads never leave the phone;
- the models are served only when their SHA-256 matches, and each self-checks before use;
- the No-AI phrases call only read tools or reversible moves through the gateway.

**Before I1 merges Part D:**
- Fix H1 and H2. Both are local to `console-wardrobe-scan.js`.
- H3 is the integration blocker behind Needs I1 item 4. Make D fail closed now, and settle the contract at I1.
- Fix M1–M6, or have the Workshop accept them in writing.

**Verified here** (each Python run behind `flock /tmp/heavy.lock`, `PYTHONPATH=$PWD/src`):
- `ruff check` and `ruff format --check` on D's Python: clean. `mypy` on `offline/phrases_r13.py` and `wardrobe/phone/`: no issue.
- D's five unit files (`test_r13_d_{scan,vision,phrases,part,assets}.py`), venv-b: **155 passed**. This includes the real models in Node.
- `evals/r13/run.py --mock --part phone`: **15/15**, and the negative control fails the suite.
- Browser, venv-c with Playwright: `test_r13_d_camera.py -k "laundry or keeps_and_sends_nothing"`, **3 passed**.
- Probes, written outside the repo in `/tmp/rv-d-probe/`:
  - D's own Node harness, with one extra output field;
  - a Playwright probe;
  - the real models in Node;
  - the phrase routers.
- The whole suites were not run (I1 runs them).

## CRITICAL

None.

## HIGH

### H1. After the first "Put in laundry" or "Put away clean", the live reader calls his own labels "not a JARVIS label"

**Where.** `console-wardrobe-scan.js:478`: `S.view = (r && r.view) || null;`

**Why it breaks.**
- The contract's `ScanReply.view` is `None` unless `already_done` (`wardrobe/http_views.py:218`). I0's fake server answers the same way (`tests/r13_fake_server.py:167`).
- So every successful send sets `S.view = null`.
- In To laundry and Back clean, the camera and the QR reader stay on after a send (see M1). `readCodes()` then calls `labelPiece(value, S.view && S.view.labels)` with no labels.
- Nothing calls `loadView()` again until the next photo, camera start or tap.

**What he sees.**
- Every one of his labels is ignored, with "A code here is not a JARVIS label, so it was ignored."
- Rows read "A piece".
- The "Where it goes" list disappears in Back clean.
- The next send carries `rev_seen: null`.

**Proof.** In real Chromium, on D's fake server (`/tmp/rv-d-probe/bp/test_probe_live.py`): To laundry → Start the camera → label read → Put in laundry → wait 1.5 s gave:
- videos 1 → 0;
- camera live: true;
- "not a JARVIS label" shown;
- the same label's row offered again (see M1).

The Node harness gives the same result (`probe_view.py`). No test covers a second scan in one live session.

**Fix.** Keep his list until a fresh one arrives:
```js
// flush(), on success
if (r && r.view) S.view = r.view;
else refreshView(); // in the background: S.view is replaced only by a list that arrived
async function refreshView() { try { const v = await M.api('/v1/wardrobe?private=1'); if (v) S.view = v; } catch (_) {} }
```
Add a scan test: live To laundry → Put in laundry → a second label of his is read and offered. FOREIGN is never said, and names stay his.

### H2. The person and face check runs only on the whole frame at 320×240 / 300×300, so a small face that is large in the saved crop is missed

**Where.**
- `console-wardrobe-scan.js:247-253` and `:285`: `check(cv)` runs once on the whole photo.
- `console-vision.js:611` scales that photo to 320×240 for UltraFace, and `:600` to 300×300 for SSD.
- The crop that leaves (`crop(cv, b, 512)`, `:254`) is never checked.

**Proof.** The real UltraFace through the engine's own preprocessing (`/tmp/rv-d-probe/probe_small_face.mjs`): a navy piece and a drawn face beside it in a 1600×1200 photo. That is "Choose a photo" up to `LOOK_SIDE` 2000; a 1920×1080 camera frame is similar.

| Face width | Whole-frame check | The 512-px crop around the piece |
|---|---|---|
| 60 px | not found | **found** |
| 80 px | not found | **found** |
| 100 px | found | found |
| 130 px | found | found |

**Scenario.**
- A shirt on a bed, with a child's face or a mirror at the edge of its box.
- The frame check passes, so Save, "Remember how it looks" and the AI tag are all offered.
- `door.tag` sends that crop to an outside AI provider. The server never decodes pixels (A), so nothing catches it later.
- The plan accepts a check that "can miss". This miss is systematic and cheap to close.

**Fix.** Check the exact canvas that leaves, at the press (the save already shows "Checking…"):
```js
async function cropOk(card) { // the bytes that leave are the bytes that were checked
  if (!card.cropGate) card.cropGate = await check(card.crop);
  return card.cropGate.checked && !card.cropGate.refused;
}
// savePhoto, remember, tag: after `if (!allowed(card))`
say(UI.state, CHECKING);
if (!(await cropOk(card))) { say(UI.state, card.cropGate.checked ? PERSON : NO_CHECK, 'bad'); paintBody(); return; }
```
Keep the whole-frame check: it gates the card. Add two tests:
- a Node harness case where `face` fires only for the crop's `src`, so nothing is sent;
- a real-model Node case with a 70-px face beside a piece.

### H3. The Privacy rows sort sources by name and fall back to "history" silently; A's real source is named `catalog`, so its photos are "Nothing kept yet" and a history delete wipes the catalog

**Where.** `wardrobe/phone/privacy.py:31-46`.
- `PIECES_DATA = {"pieces"}` and `PHOTOS_DATA = {"photos"}`.
- `_history` takes every other name.

**What A does.** A's branch (`r13-a` @ `b8de963`, `wardrobe/catalog/data.py:22-23`) has ONE source, `name = "catalog"`.
- Its `count` is the pieces.
- Its `delete` drops every log page, every photo, every fingerprint and the index.
- C names its source `outfits`.

**What happens at I1 as written.**
- "Wardrobe pieces and places" says "Nothing kept yet".
- "Wardrobe photos and fingerprints" says "Nothing kept yet", while photos exist. That is a false privacy statement.
- "Laundry, outfits and wear history" counts his pieces. Its passkey delete erases the whole catalog and every photo, irreversibly, under a label that promises history only.
- No test catches it: D's tests use made-up names, and INTEGRATION-D's Needs I1 item 4 only states an expectation.

**Fix now, in D.** Fail closed:
- add `HISTORY_DATA = frozenset({"laundry", "outfits"})`;
- treat a source in none of the three sets as "Not available";
- never count or delete it under another row;
- test that an unknown name lands in no row.

**Fix at I1.** See "Needs I1 item 4" below.

## MEDIUM

### M1. A step change, a send or Cancel while the camera is live removes the preview but leaves the camera and the QR reader on

**Where.** `choose()` (`:165-170`), `send()` (`:465`) and Cancel (`:426`) call `clearScan()` (`:171-177`).
- `clearScan()` empties `UI.stage`, which removes the `<video>`.
- It never stops `S.codes`, never stops the camera, and never re-attaches the video.

**Proof.** The Node harness probe (`probe_flow.py`):
- To laundry → Start the camera → Add pieces gives videos 0, camera live, streams 1, stops 0. The QR reader keeps filling `S.found` inside Add pieces.
- After Put in laundry, the label still in view is re-added at once and "Put in laundry" is enabled again.
- The Playwright probe confirms both.

**Effects.**
- The camera stays on with no live view (privacy UX).
- A second press sends a duplicate deposit with a new `client_id`.
- The phone keeps working (CPU and battery).

**Fix.**
- In `choose()`, `if (S.live && id !== S.flow) stop();`.
- In `send()` and Cancel while live, clear only `S.found`, `S.more` and `S.cards`; keep the stage.
- Keep a session set of ids just sent, so a label still in view is not offered again.
- Test: streams = streamStops after a step change; the video is still in the stage after a live send.

### M2. When the split finds no piece, the "crop" is the whole frame, so "cropped to the piece" is not true

**Where.** `boxesOf` returns `[{x: 0, y: 0, w: 1, h: 1}]` when nothing differs from the border (`:103`). D's own test pins it: "a bare surface: the whole frame".

**Scenario.**
- A white shirt on a white sheet (`FG` 60 is not reached), a busy background, or a piece touching most of the border.
- The result is one box ≈ the whole frame: his room, papers, a screen.
- That box is offered for Save and the AI tag at 512 px.
- The intro, the button and C63's promised words all say "cropped to the piece". The card never shows the crop that will leave; only the full photo is on the stage.

**Fix.**
- Mark `card.whole` when the box is the fallback or covers more than 85 % of the frame. `allowed(card)` refuses it with "JARVIS couldn't find the piece's edges: lay it on a plain surface of another colour so the photo can be cropped to it." Taps and matches still work.
- Draw `card.crop` itself on the card above Save (the panel may show pixels).
- Test: a bare scene → no Save, no Tag, nothing sent.

### M3. "about ₹0.30 at most" is not an upper bound

**Where.** `:40-41`.

**The arithmetic.** The plan's token figures (≈ 750 in, 120 out), `llm/pricing.py` and `usd_inr_rate` 95.24 give, for one crop:
- Haiku 5.5: ≈ ₹0.01;
- Sonnet 5.5: ≈ ₹0.26;
- Opus 5.5 (4/20 $/Mtok): **≈ ₹0.51**.

If a strong, seeing brain answers, the button under-states the cost it shows "first" (H2). The cap holds on the server, but the shown figure is wrong.

**Fix.** Show the server's own figure (Needs I1 item 2: the view's `settings.tag_estimate_inr`). Until then, word it "about ₹0.01–₹0.51, depending on the brain" and use 0.51 in the client's limit check.

### M4. Wardrobe words still reach Things through R14's other put forms, so "where is my watch" can disagree (D6)

**Where.** `offline/phrases_r13.py:235-238`.
- R13's `PUT` takes `kept|put|placed|stored|hung` and `in|inside|on|at|into`.
- R14's takes `hid|hidden` and `on top of|under|behind|with|near|beside|next to` too.

**Proof.** `/tmp/rv-d-probe/probe_phrases.py`, with R13's routers first, then R14's:
- "I hid my watch in the drawer", "I put my watch under the pillow", "I kept my shoes near the door", "I put my watch next to the bed", "I kept my shirt with the suits" and "I put my black belt behind the door" → `belongings_put`.
- "I put my belt on top of the cupboard" → `wardrobe_edit(place="top of the cupboard")`.
- Then "where is my watch" answers from the wardrobe first (D6) and contradicts what he said.
- Also "my wifes shirt is in the laundry" (no apostrophe) → `laundry_move`. `_NOT_A_THING` has `wife`, not `wifes`.

**Fix.**
- R13's PUT takes R14's verb and preposition lists exactly, with "on top of" before "on". Pin the two lists equal with a test. An unknown place is refused by A, with his places listed.
- Add a matrix test: every R14 PUT verb × preposition × a wardrobe word never yields `belongings_put` with R13 first.
- Strip a trailing `s` before the `_NOT_A_THING` check, the way R14's `_a_thing` strips `'s`.

### M5. The match bands do not fit INV-06's own numbers, so the right piece's button reads "(new?)"

**Where.** `:42`, `:47` and `:72-81`.

**The numbers.**
- INV-06's real half: the same striped shirt rotated 25° scores 0.43, folded 0.53 and from the back 0.81 (centred).
- It is always candidate 1, with margins of 0.37–0.78.
- With the bands at 0.80 and 0.60, two of its three views show "This one: Striped shirt (new?)", unhighlighted.
- With a single saved print, `candidates` falls back to the raw cosine (`:75`). The real model gives 0.49–0.69 between unrelated drawn pieces ("maybe") and only 0.77 for the same piece rotated (probe). So raw scores do not separate.

**Is it sensible?** The ranking is sound. The absolute bands and the "new?" word on a candidate are not.

**Fix (the pilot still calibrates).**
- Never print "new?" on a candidate. Use "(a weak match)", or no band word at all.
- Lift candidate 1 to "maybe" when its margin over candidate 2 is at least 0.25.
- With fewer than 3 saved prints, show no band words and do not centre.
- Keep the 0.80 / 0.60 / 0.03 numbers as the plan's starting point, recorded raw and centred in the pilot.

### M6. Three of D's four catalog tool calls do not fit A's tools, and "Save as a new piece" can create duplicates at I1 (Needs I1 item 3)

**Compared with `r13-a` @ `b8de963`, `wardrobe/catalog/tools_write.py` and `tools.py`:**

| Call | D sends | A has | At I1 |
|---|---|---|---|
| `wardrobe_add` | flat `{type, private, colour}`, reads `result.piece` (`:503-512`) | `{pieces: [{type, private?, colour?, client_id?, ...}]}`, returns `{ids, new}` | the piece is made, the card never moves on, and a second press makes a second piece (no `client_id`) |
| `wardrobe_edit` label fields | `{piece, label_field, value: {v, pct?, ok}}` (`:585`) | `size`, `fabric`, `care`, `read` and `verify` | refused or ignored |
| `wardrobe_edit {settings}` (Helpers `:198`) | settings through the tool | not a field of the tool | refused (item 5) |
| `wardrobe_count` | `{category}` or `{ready: true}` (`phrases_r13.py:219-226`) | `{type}` only, where the word may be a category | counts everything |

`wardrobe_edit {query, place}` matches A. B's and C's argument names match D's.

**Fix.** See item 3 below. Add an I1 test that replays the tool calls D's harness records through each part's real tool schema.

## LOW

1. **The door test misses two spellings** (`tests/test_r13_seams.py:518-526`, I0's). It looks only for `'`-quoted literals, so a backtick or `"` path (for example `` `/v1/wardrobe/tag?piece=${id}` ``) passes. The scan module's rules also do not ban `JarvisChat`, `.raw(` or `FormData`. **Fix at I1:** match `[\'"\`]/v1/wardrobe/(photos|tag)\b`, and ban those three in the scan module.
2. **Use cases can subscribe to the wardrobe tasks** (`console-vision.js:69-84, 115-120`). `tell()` gives every Result to every use case that lists the task. A future R8–R10 use case could list `embed` and receive his query fingerprints, against "the query fingerprint never leaves the phone" (latent: there are no use cases today). **Fix now:** a static test in D's file that no console module calls `use()` with `embed`, `colour`, `person` or `face`. **At I1:** the core skips `tell()` for photo-only wardrobe tasks.
3. **The phone never hashes the model bytes** (`console-vision.js:522-527`). The server verifies them, and the self-checks test behaviour: exactly for `embed`, with a tolerance for `face` and `person`. A model that passes its self-check on the ramp but misses real faces would still be used. **Fix:** `model13()` compares `sha256hex(bytes)` with the manifest sum pinned beside `SELF13`; the helper already exists.
4. **`remember()` labels every fingerprint int8** (`:526` sends `model: MODEL`, not the embed's own `model`). If the fp32 fallback is ever vendored, its prints are stored as `mnv2-int8-1` (D8: never compared across models). **Fix:** keep `card.model = e.data.model` and send it.
5. **Browser tests: no page clock, fixed sleeps, a /tmp default.**
   - They do not pin the page clock (BRIEF §5). "Pictures sent from this device today: 1" reads the door's per-UTC-day counter, so a run across 05:30 IST can fail.
   - There are fixed sleeps (`_audit` 400 ms, before sign-in 1,500 ms).
   - Screenshots default to `/tmp/r13-d-shots`, against BRIEF §1's no local paths. Use the env var only, and skip the shots when it is unset.
6. **The Camera strip's four columns are set in D's stylesheet** (`console-wardrobe.css:52` overrides R7's `#p-camera .hp-tabs`). R7's visual gate checks overlap, clipping and wrap (DOM checks), not the look against R14. **Fix at I1:** move the rule into `console-camera.css` (3 → 4), and compare the Camera screenshot with R14's. Only the strip should differ.
7. **Every photo is saved as `view: 'front'`** (`:520, :526`). The door and A allow `back` and `detail`, up to 3 views a piece. A second photo cannot be a back view. **Fix:** a Front / Back / Detail choice, defaulting to the first view not yet saved.
8. **The Photos row's note** ("delete here if one slipped through", `privacy.py:109`) deletes EVERY wardrobe photo, because there is no single-photo delete until item 2. **Fix:** say so plainly.
9. **No "Telegram tests" for D.** D's part-split row names them, but no D test or eval case sends a D20 sentence over Telegram with the personal switch off and on, and INTEGRATION-D lists no deviation for it. **Fix:** add the case, or record the deviation.
10. **Small code points.**
    - `flush()` (`:472`) returns while busy and does not drain the queue afterwards, so a scan queued during a send waits for "Send now".
    - The gap-closing comment (`:88`) says one cell, but dilation from both sides closes two-cell gaps (≈ 3 % of the long side).
    - `tag()` does not re-check No-AI at the press; the server refuses anyway.
    - The tag button does not say a photo is sent. Prefer "Send this photo to the AI to tag it (about ₹N)", per H6's "a button that says so".

## Needs I1, items 2–6: the cleanest option for each (item 11)

**Item 2 — the door-test narrowing: do not adopt it.** It opens paths for a picture to leave without the door.
- The `?`-suffixed literals stop catching `JarvisChat.raw('/v1/wardrobe/photos' + '?piece=' + id, {method: 'POST', body})`.
- They also stop catching `M.api('/v1/wardrobe/photos', {body: {...}})`.
- The probe (`probe_door.py`) shows both missed after narrowing and caught today.

Cleanest instead:
- (a) **the ₹ rides in A's view**: `settings.tag_estimate_inr`, computed by A from `llm/pricing.py` for the brain that would answer. No new client route, and it also fixes M3.
- (b) **thumbnails and the single-photo delete go through the door**: `thumb(id)` (GET, returned as a `data:` URL, because the CSP's `img-src 'self' data:` needs no `blob:`) and `drop(id)` (DELETE). That is ≈ 10 lines; the door's guard moves 130 → 140, in the open.
- (c) **the door test is widened**, per LOW 1.

**Item 3 — the tool arguments: D moves to A's shapes.** A owns the tools, and its shapes carry batch add and `client_id` idempotency.
- `wardrobe_add {pieces: [{type, private, colour?, client_id: 'wd' + random}]}`, reading `result.ids[0]`.
- A label read `{piece, size | fabric | care, read: true}`; Confirm `{piece, verify: [field]}`.
- `wardrobe_count {type: word}` (a type or a category; "ready" is in A's counts).
- The move `{query, place}` already matches.
- Write `wardrobe_edit {query, place}` into D10's list of query tools and the needles eval's allowed places. It is the No-AI move that D6 and D20 already name, and the one-step spoken path keeps his words in a card's stored arguments, like Things' put.
- B and C need no change.

**Item 4 — `WardrobeData` names: an explicit row in the contract.**
- `ports.WardrobeData` gains `row: Literal["pieces", "history", "photos"]`. The contract check refuses a part whose data has no row or another value ("setup failed", never a silent "history"). `privacy.py` picks by `d.row`.
- A exposes two sources:
  - `pieces`: the index and its logs. Delete drops the photos too, and the row says so.
  - `photos`: photos and fingerprints only. Delete leaves the catalog usable (e2e 7).
- B's `laundry` and C's `outfits` are `history`.
- The History row's words then lose "each piece's history" (it moves to the Pieces row's words).

**Item 5 — A's settings: `PUT /v1/wardrobe/settings`.** Make it owner-only and rate-limited, with `record_change`, mirroring C's `PUT /v1/outfits/settings`. A's `tagging.update_settings` already exists.
- Settings that unlock spending (AI tagging) and the private display stay off the tool surface the model can call.
- With the AI on, a tainted round could otherwise ask for `wardrobe_edit {settings: {ai_tagging: true}}`.

**Item 6 — the backup's photos: the contract gains `photos: bool = False` on `GET /v1/wardrobe/backup`.**
- `?photos=1` parses as true.
- A's `backup.lines(uid, photos=...)` already takes it.
- OPS-06 says photos are included only "when specifically selected".
- The tick's words should say the file then holds his photos (sealed) and is larger.
- Restore's purged-piece ticks (`RestoreCheck.purged` → `include_purged`) can follow in the same change.

## The asked checks (items 1–12): what holds

1. **Pixels (H6).** `PANELS` and the scan module's rules hold: no `fetch`, XHR, beacon, WebSocket or storage; `M.api` only to `/v1/wardrobe` and `/v1/laundry`; `textContent` only; ASCII.
   - Helpers' modules use no pixel API and no `JarvisCamera`.
   - Picture bytes leave only through `door.wardrobe` and `door.tag`, each after `allowed(card)` and a press on a button that names the photo; the door redraws and counts.
   - The checks gate Save, Remember and Tag, and a check that is not installed refuses (`check()` fails closed).
   - QR-only and tap-only events are not blocked (OPS-01 test).
   - The "can miss: look before you save" wording is honest, except "cropped to the piece" (M2) and the miss band H2 closes.
2. **Crops.**
   - At most 512 px, in memory; the camera and the canvas redraw strip EXIF, and so does the door's shrink.
   - The whole frame is used only in M2's fallback.
   - A private piece never gets a photo, a fingerprint or a tag: `allowed()` checks the record and the type, and the card says why.
3. **AI tagging.** Offered only for a saved, non-private piece; absent in No-AI; ₹ and the month's counter shown before the press; refused at the cap. The figure is wrong for Opus (M3).
4. **Front end.** No inline handlers, no `innerHTML`.
   - Labels, OCR text, QR payloads, shop names and calendar titles reach the page via `textContent` (`H.txt` bounds them).
   - CSP: `script-src 'self' 'wasm-unsafe-eval'`, `worker-src 'self'`, `connect-src 'self'`. ORT runs with one thread and no proxy, so no worker, and its wasm comes from the same origin.
   - The models' SHA-256 is checked on the server per folder change (`api/console.py` `_check_vision`). `scripts/wardrobe_assets.py manifest` refuses a differing file. The phone checks behaviour, not the bytes (LOW 3).
5. **The rest of the panel.**
   - The four Privacy rows exist with passkey deletes. H3 is the risk.
   - "(No. N)" appears only in his own console and in D10's card form.
   - The device row is accurate.
   - The No-AI phrases end in R1 reads or reversible R2 moves (`laundry_move`, `wear_log`, `wardrobe_edit`) through the gateway; none deletes, archives or merges.
6. **The door-test narrowing** opens two paths (item 2 above).
7. **Flows.** Every flow (Add pieces, To laundry, Back clean, Find, Read a label, the review queue, the Pieces list, the private-basics switch) runs end to end on the fake server.
   - The Node harness drives each by button presses with spies on every request and door call.
   - The browser tests drive real Chromium, and the waits poll a condition.
   - Gaps: a second live scan (H1), a step change while live (M1), and the page clock (LOW 5).
8. **Vision code.**
   - Box arithmetic: padding and clamping are correct; see M2 and LOW 10.
   - Load errors map to "not installed" or "could not load", and a failed self-check releases its session.
   - Sessions are released on `pagehide`.
   - Stop, the sub-tab and a hidden panel stop the camera through `stopModes` and `console-camera.js`. A flow change does not (M1).
   - INV-06: see M5.
   - Splits:
     - `console-vision.js` (641): move the `WARDROBE-PURE` region (~100 lines: Lab and `twoMeans`, `iou`/`nms`, box decoding, `ramp`/`silhouette`, `chw`/`rgb`/`b64`/`quantize`) to `console-vision-r13.js`. Import it statically from the R13 section (ES imports hoist; the I0 core's bytes and hash stay the same). That gives ≈ 540 lines.
     - `console-wardrobe-scan.js` (595/600): move the non-pixel pure region (`LABEL`/`labelPiece`, `unb64`/`meanOf`/`cosine`/`band`/`candidates`, `FABRICS13`/`CARE13`/`SIZES`/`parseLabel`, ≈ 60 lines) to `console-wardrobe-words.js`. Keep `boxesOf` (it reads pixel bytes) in the named panel. That gives ≈ 535 lines, with room for H1, H2, M1 and M2.
     - Both new files need `APP_ASSETS` at I1, and the tests import them instead of slicing text.
9. **Existing screens.**
   - The new CSS is 52 lines with no literal colour, font, radius or shadow.
   - Helpers' six sub-tabs wrap 4 + 2.
   - The Camera strip's four labels fit at 390 px.
   - No overlap or clipping in the sampled screenshots (night and day, 390 and 1440).
   - The strip change: LOW 6.
10. **Python.**
    - Router order: outfit, laundry (before put), wear, count, where, put; installed first and once.
    - Collisions with R14: only M4's gaps; every R14 phrase test still routes the same.
    - Functions ≤ 50 lines; modules 277 / 167 / 36 (≤ 400).
    - Typed; ruff and mypy clean; bounded input; no ReDoS shape.
    - `NoAICall.arguments` is typed `dict[str, str]` but receives a `bool` (`ready`): I0's type, harmless; it goes with M6.
11. **Needs I1 items 2–6:** above.
12. **Ownership.** `git diff --name-only r13-i0..r13-d` stays inside D's row in BRIEF-COMMON §3:
    - `wardrobe/phone/*`, `offline/phrases_r13.py` and the four console files;
    - the Part B section of `console-vision.js` (the I0 core's hash test passes);
    - `vendor/vision/r13-1/MANIFEST.json`, `scripts/wardrobe_assets.py` and `buildbook/gen/libs.py`;
    - D's tests, fakes, fixtures and eval;
    - the two R7 test files it may move;
    - `INTEGRATION-D.md`.
    - No wiring or shared file was edited, and the licence texts are unchanged.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 16 Nov 2026, 10:12 IST | R13 | First edition: fresh-context security + code review of Part D at `42574c6`; 3 HIGH, 6 MEDIUM, 10 LOW with file:line, scenario and fix; recommendations for Needs I1 items 2–6; the twelve asked checks | 🛠 Mark XXI |
