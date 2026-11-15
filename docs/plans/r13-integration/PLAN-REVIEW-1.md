Version v13.0.1 · 15 Nov 2026, 17:19 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI (fresh-context plan review)

# R13 plan review 1 (fresh context, 15 Nov 2026)

Plan reviewed: `docs/plans/r13-wardrobe.md` v13.0.1 (Draft), all 981 lines, on `r13-plan` @ `f7e1552`
(the code is `main` @ `9a8392b`: `git diff 9a8392b f7e1552` touches only the plan).
Checked against: that code; the owner's workbook (sheets "Use Cases", "Wardrobe Rules", "Build and
Test") and the approved proposal v1.1 as the planner had them; the planner's downloaded model files,
re-hashed; the ONNX Model Zoo at the pinned commit, its Git LFS pointers and the upstream licences,
fetched from GitHub; Google's `events.list` reference and Cloud Run's quotas page, read today.
Reviewer: a fresh-context agent for 🛠 Mark XXI applying `.claude/agents/code-reviewer.md`,
`security-reviewer.md` and `planner.md` to a plan. Read-only apart from this file. "L" numbers are the
plan's lines at `f7e1552`.

**Verdict: APPROVE WITH CHANGES.** No CRITICAL finding. Six HIGH findings (H1–H6) must be written into
the plan before I0; the MEDIUM ones should be, and the LOW ones are the planner's call. None needs the
owner first (M11's pilot pass line takes a safe default). The design holds: one id per physical piece,
the 10 states as data, an ordered ledger with holds, phone-form checkpoints that a fixed camera can
feed later, recognition on the phone, sealed crops through the one door, count-only private pieces,
rule-based outfits, and nothing that orders, pays or calls.

What this review could not check:
- The models on a phone's browser (speed, memory, a quantized operator), UltraFace on a real face and
  SSD on a real partial body, real match rates: the pilot's job, as the plan says (L959–964).
- Google's `fields` behaviour on `events.list` and `calendarList.list` (read from the reference only).
- Cloud Run's internet egress price for `asia-south1` (L2 asks the pilot to measure it).

## What holds (checked against the code and the web)

| Claim (plan) | Result |
|---|---|
| Version `14.0.2` and its four pins; persona `p14.0` in 21 test files (fact 1) | Right (`__init__.py:3`; `test_about.py:24`, `test_r11_1_seams.py:73`, `test_r14_seams.py:98`, `test_r7_seams.py:110`; 21 files) |
| Sizes: `app.py` 727 (≤ 735), `gateway.py` 760 (= 760), `brain.py` 713 (≤ 741), `console.html` 782 (≤ 782), `console.js` 769 and `console-brief.js` 764 the largest JS, `config.py` 729 (< 800); camera panel 468, alerts 462, helpers 236, door 100 | Right (`test_r14_seams.py:409`, `:475–480`; `test_r7_seams.py:605`, `:649–653`; `test_r1_seams.py:649–650`; `test_r11_1_a_brain.py:301`) |
| Alert kinds 52 → 56 in six pins, plus `DAYTIME_RING_KINDS` and `TARGETS` | Right: `get_args(AlertKind)` is 52; the six pins are where the plan says |
| Key purposes 22 → 24 (last `backup_probe`, then `webpush_vapid`) | Right (`keyring.py:42–79`; the four pins) |
| Permission rows 49 → 52 (six pins); save cap 51 → 54 (`permissions/models.py:133`) | Right, but the cap has its own pin the seam list misses (L1) |
| `console.html` untouched; Wardrobe as sub-tabs of Helpers and Camera | Right: both frames build their tab strips in JS (`console-helpers.js:15`, `:34`; `console-camera-panel.js:20`, `:84`); `.hp-tabs` is a 4-column grid (`console-helpers.css:6`); the camera's tap rule counts taps inside `#p-camera`, so a Camera sub-tab can start the camera (`test_r7_b_console.py`, `closest(OWN)`) |
| `plain()` cuts arrays at 100 and strings at 2,000; 1,280 bytes → 1,708 base64 characters | Right (`console-vision.js:27–35`); see M8 for the fp32 fallback |
| The vision route serves any release folder whose MANIFEST lists the file with a matching SHA-256, `application/octet-stream` allowed | Right (`api/console.py:328–413`; `r13-1` matches `_VISION_RELEASE`) |
| CSP needs no change | Right: `script-src 'self' 'wasm-unsafe-eval'`, `worker-src 'self'`, `connect-src 'self'` (`api/console.py:217–222`) cover single-thread ORT and same-origin model files |
| The three model files, their sizes and SHA-256 | Right: each equals the Git LFS pointer at `c5cae0f…` (`mobilenetv2-12-int8.onnx` `cc028fe6…` 3,655,033; `version-RFB-320.onnx` `34cd7e60…` 1,270,727; `ssd_mobilenet_v1_12-int8.onnx` `2b79e6a7…` 9,540,809; fp32 `mobilenetv2-12.onnx` `c0c3f76d…` 13,964,571); the cut is `c32ba47c…` 2,368,080 |
| They run on the vendored onnxruntime-web 1.30.0, one thread | Right: re-run here, `472_quantized:uint8[1,1280]` 78 ms, UltraFace 82 ms, SSD 130 ms |
| Licences "on the zoo's model page" | Right per page (Apache-2.0, MIT, MIT); SSD's upstream is Apache-2.0 (M15) |
| Gateway facts (ASK, spoken, the 11th delete, the 12,000-character cut) | Right (`gateway.py:106`, `:239–247`, `:446–447`) |
| Telegram's personal switch; `deleted_list` hides in-place kinds while it is off | Right (`telegram/rules.py:66`; `undo/tools.py:105`): adding `wardrobe_item` to `IN_PLACE_KINDS` hides it |
| No-AI routers append only, at most 64; R14's `things` takes "where is my black belt" | Right (`offline/mode.py:40`, `:70–73`; `offline/phrases_r14.py` `WHERE`, `things`) |
| Weather: 2 days fetched, the summary keeps today | Right (`helpers/house/weather.py:119`, `:202–218`) |
| Calendar: primary only, governed background path, `calendar.readonly` granted | Right (`helpers/nudges/calendar.py:37`; `tools/background.py`; `integrations/google.py:36–41`) |
| ₹ for AI tagging | Right: (350 + 400) × $0.10/M + 120 × $0.50/M = $0.000135 ≈ ₹0.013 on Haiku 5.5; $0.0027 ≈ ₹0.26 on Sonnet 5.5 (`llm/pricing.py:29–31`, `config.usd_inr_rate` 95.24) |
| Backups ≈ ₹0.6–0.8 a month more | Right: R14's ₹3.8 per 100 MB (`r14-hardening.md` L573) × 15–20 MB |
| Firestore free tier (1 GiB, 50,000 reads, 20,000 writes a day) | Right (as `r2-memory-vault.md` L45); reads are understated (L2) |
| R14's drill needs no change for flat ids | Right (`backup/walk_checks.py:31`, `:47`) |

## Coverage of the 54

All 54 IDs have a named test (L776–831), each matching the workbook's acceptance check. Three are in
their declared phone form (LND-02, OPS-01, OPS-02) and INV-06's real half is a drawn shirt plus the
pilot; that is honest. Two gaps: OPS-01's test drops the workbook's "pause capture at any time" (add:
Stop in Camera → Wardrobe ends the camera before the next frame, and hiding the tab stops it), and
STY-13 and STY-17 have tests that the design as written fails (H1). The end-to-end tests 1–5, 7 and 8
follow the workbook's steps in their R13 form (4: the load's "finished" by his tap; 5 and 7 without
their avatar halves). End-to-end 8 has no pass line (M11).

## CRITICAL

None.

## HIGH

**H1. Wearing the planned outfit breaks the plan and sends a false alert; "In use" and the hand-off
between events are not modelled (D3 L289–297, D12 L478–482, D19 L549, D20 L566).**
- Evidence: D20 sends both "I'm wearing the blue shirt" and "I wore the blue shirt today" to one
  `wear_log`; D12: "after a wear each piece goes to laundry or back to Ready by the rewear rule"
  (shirts: laundry); D3: eligible = Ready only; D12's refresh marks a plan using a changed piece and
  D19's `outfit_changed` fires when "a planned or reserved piece left Ready within 36 h". The
  workbook's status table: In use is "held for other plans until a reusable return or an allowed
  handoff between events".
- Failure: a plan for today 10:00 uses the navy shirt. At 08:30 he says "I'm wearing the navy shirt":
  the shirt goes to In laundry, the same plan becomes "needs a new shirt", and he gets "A navy shirt
  in today's 10:00 outfit went to the laundry". It happens every time he wears what was planned.
  STY-13 (a meeting and an evening function sharing a base) breaks at the first wear.
- Change: (1) two events: `wear_started` ("I'm wearing …": Ready → In use, linked to the plan or
  event when there is one) and `wear_done` ("I wore …", "done for today", or A's daily sweep at a
  fixed local hour: In use → In laundry or Ready by the rewear rule); D20 gets two rows. (2) D3: an
  In-use piece is eligible for a later plan the same day only when that plan declares it shared with
  the plan it is worn for and the rewear rule allows it (the workbook's hand-off). (3) C's refresh
  ignores a change caused by wearing the piece for that plan or a declared hand-off: no
  `outfit_changed`. (4) Tests: "wearing the planned outfit sends nothing"; STY-13's shared base stays
  eligible for the evening after "I'm wearing it"; STY-17 counts one wear for start + done; e2e 1
  passes through In use.

**H2. AI tagging can send a private piece's or a person's picture to the cloud (D7 L383–390; D9
L411–415, L426–428; D10).**
- Evidence: D9's person and face refusal guards "Save photo" and fingerprints; D9's private rule
  covers "a photo or a fingerprint"; the tagging bullet has neither. Tagging is offered in "Add
  pieces", where the kind may still be Unknown, and private-by-default is decided by category (L434).
- Failure: he lays boxers out, has not tapped a kind yet, and presses "Ask the AI to tag this piece
  (about ₹0.01)" to get one: the crop goes to a cloud brain. A frame with his face in a mirror is not
  checked before tagging at all.
- Change: tagging only (a) for a saved piece id that is not private and not of a private-by-default
  category, refused 422 by the server from the piece record, not the client's word; (b) after the
  person and face check on the same bitmap as the crop; (c) with the cap's counter named: month-to-date
  tagging ₹ in the sealed index (the month in his zone), checked with the estimate before the call,
  updated with the recorded cost after. Reuse `picture.eyes.BrainEyes.look()` (it already refuses in
  No-AI, picks a seeing, non-training brain, asks `Billing.ensure_allowed`, records one cost and has a
  timeout) with a wardrobe system prompt, instead of a mirror copy in `tagging.py`. Tests: a private
  piece's tag call → 422 and zero provider calls; a forced face → no tag request leaves the phone;
  the cap refuses once month-to-date + estimate > ₹30.

**H3. OPS-06's restore can't get past today's body cap, and the backup's limits don't fit Cloud Run
(D17 L520–528; seam 8 L686).**
- Evidence: every request body is capped at 2,100,000 bytes before routing (`api/body.py:25`,
  `api/app.py:518–529`; only paths in `routes=` get more, as `**r7.BODY_CAPS`). Cloud Run: "Maximum
  HTTP/1 request size: 32 MiB", and 32 MiB per response unless chunked
  (https://docs.cloud.google.com/run/quotas). The service has `--memory 512Mi --cpu 1`
  (`deploy/cloudrun.sh:543`). A Firestore request is at most 10 MiB. The plan: `wardrobe_backup_max_mb`
  50 (5–200); photos ≈ 9 MB at 150 pieces; logs ≈ 4 MB a year; a restore "merges" with no word on
  transactions.
- Failure: after about six months of history, or any backup with photos, `POST /v1/wardrobe/restore`
  is a 413 before the route runs; 50–200 MB never reaches Cloud Run; a 600-piece restore in one
  transaction is over 10 MiB; a 50 MB file decrypted and parsed in 512 MiB risks the instance.
- Change: (1) `api/r13_wiring.py` `BODY_CAPS = {"/v1/wardrobe/restore": cap}` and `**r13.BODY_CAPS,`
  in `app.py` (+1 line: 732 ≤ 735; update the size-guard table). (2) `wardrobe_backup_max_mb` 25
  (5–30); a larger wardrobe backs up without photos (R14's Firestore backups keep them), or in photo
  parts of ≤ 25 MB. (3) The download is streamed (chunked); the upload is read with `read_capped`.
  (4) Restore in two steps, confirm before commit: `POST …/restore/check` (seal, schema, and the counts
  added / already there / superseded / back from Recently deleted, nothing written), then
  `POST …/restore` with the check's token. (5) Applied in chunks of ≤ 50 pieces a transaction,
  idempotent by event id, so a cut restore can run again. (6) Write the attribute rule: for a piece in
  both, the current record's attributes win and the events are unioned and re-folded; a piece purged
  since the backup comes back only if he ticks it. Tests: a 3 MB backup restores through the real app
  with its middleware; 31 MB is refused in plain words; a restore cut after chunk 2 and re-run
  duplicates nothing.

**H4. No atomic contract between A's ledger and B's review queue and loads (D4 L312–320; D11
L457–459; D0 L245–246; seam 9 L689–697).**
- Evidence: D4 steps 4–5 make A's fold open review entries and holds, but entries live in B's
  `wardrobe_review/{uid}`; observers run "never inside the transaction"; `WardrobeStore.transact` has
  no signature; B's loads and batches (`wardrobe_laundry/{uid}`) change with the same events (LND-07,
  LND-14). D0 says "B supplies each piece's expected return through A's view", but the event (L300–301)
  has no due date and the piece record (L274) no expected return.
- Failure: A commits a hold; the observer that writes B's entry fails (a Firestore error, an instance
  stopping): the piece stays "Missing or in review" with nothing to resolve it, out of every outfit.
  Or a load says Washing while its pieces are still In laundry.
- Change: I0 defines `WardrobeStore.transact(uid, fn)` with `fn(view, tx) -> Commit(events, extra)`
  run inside A's transaction (all reads first, B reading its own document through the same `tx`), and
  the entry for a hold or a conflict written in that same commit (A's fold returns `ReviewNeeded`
  items; B's writer adds them in `extra`). Add `due` to the `sent_out` event and `expected_back` to
  A's piece view, so C reads LND-16's data from A alone. A's daily `wardrobe_sweep` gives any hold
  without an open entry one. I0 ships the fold as a conformance test that both `tests/r13_fakes.py`'s
  in-memory store and A's real store must pass, so B and C don't build on a fake that folds
  differently. Tests: an `extra` write that raises leaves the index, the log and B's document as they
  were; the sweep re-creates a missing entry.

**H5. Part D builds the screens for A, B and C with no HTTP contract pinned at I0 (Part split
L741–766; seam 9's `ROUTE_PREFIX` only).**
- Evidence: D owns `console-helpers-wardrobe.js`, `console-wardrobe-pieces.js`,
  `console-wardrobe-scan.js` and D1's six sections (L255–259), which draw A's pieces, labels, photos
  and fingerprints, B's laundry and review queue, and C's plans and settings, plus D's browser tests.
  A's `api/wardrobe.py`, B's `api/laundry.py` and C's `api/outfits.py` are written at the same time.
  R14's plan review called a shared surface between builders blocking (`r14-integration/PLAN-REVIEW-1.md`,
  A8).
- Failure: D writes the panel against guessed JSON, A–C choose other shapes, and I1 rewrites D's code
  and tests on its last day; D's browser tests can't run end to end before I1.
- Change: I0 adds `wardrobe/http.py` with the Pydantic request and reply models of every route
  (method, path, body, reply, error words) and `tests/r13_fake_server.py` serving them from
  `tests/r13_fakes.py` for D's browser tests; each part's route tests assert those models exactly. A
  change to a model is a seam change with a line in the part's INTEGRATION file.

**H6. The scan module sidesteps R7's "use cases never see pixels" guard instead of changing it in the
open (D9 L416–422; `tests/r7_fakes_b.py:116–123`; `tests/test_r7_b_console.py` `BYPASSES`;
`docs/architecture/JARVIS-Architecture.md:364`).**
- Evidence: `use_case_modules()` finds a use case only by a `JarvisVision.use(` call. The plan's scan
  module "calls `JarvisVision.run` and `stream`, never `use`, so R7's use-case guard still finds no use
  case", while it takes camera frames, draws a crop and hands JPEG bytes to the door: exactly what the
  guard's list forbids a use case (`JarvisVision.run`, `.stream`, `cam.frame()`, `drawImage`,
  `toBlob`). C63 tells the owner "the use cases of R8 to R10 receive results only". Only the camera
  panel carries the panel rules (`test_the_panel_sends_a_picture_only_through_the_one_door`).
- Why it matters: after R13 the guard is opt-in: any module that avoids `.use(` may read pixels
  unchecked, and the wardrobe, R7's first real use case, sets that precedent without saying so.
- Change: (1) a `PANELS` allow-list (`console-camera-panel.js`, `console-wardrobe-scan.js`) and a static
  test that fails any other console module calling `JarvisVision.run|stream`, `JarvisCamera.frame|photo`
  or any API in `D13_APIS`; (2) the camera panel's rules for the scan module: no `fetch`, XHR,
  `sendBeacon`, WebSocket, `localStorage` or `indexedDB`; `M.api` only to `/v1/wardrobe` and
  `/v1/laundry` paths and never with picture bytes; bytes only through `door.wardrobe` / `door.tag`;
  `textContent` only; ASCII; (3) D9 and C63 say it in words: "two panels see pixels: Camera and Camera
  → Wardrobe", with the line in R7's INTEGRATION-B that its contract requires.

## MEDIUM

**M1. The phone-clock rule is written twice, differently, and loses offline scans (D4 L305–308;
Risks L901–902).** D4 refuses a scan more than 10 minutes from the server's clock; the Risks clamp it to
± 5 minutes. A scan made without signal and sent 15 minutes later is lost; one 4 minutes off is clamped
and can reorder. Change: the client sends `at` (capture) and `sent` (its clock at send); the server
stores `at + (server_now − sent)` and refuses only a corrected `at` in the future or older than 24 h;
the mode queues unsent scans in memory (R7 allows no storage) and says that closing the page drops them.
Fix the Risks line. Tests: a phone 3 hours fast; a scan sent 20 minutes late; both fold in true order.

**M2. The fold must be order-independent and its marks computed, not written (D4 L302–318).** "Kept in
the log, marked `superseded`" conflicts with an append-only sealed log. Change: `fold(history) ->
(state, marks)` is pure over the whole sorted history; `superseded`, `conflict` and `voided` are
outputs, never written back; `apply` appends and re-folds the piece. Add a seeded test over 50
permutations of one event set (same state and marks every time) beside OPS-03 and LND-05. Say what time
a stated day gets ("yesterday" → 12:00 local that day, `recorded` breaking ties).

**M3. A second record of the same movement opens a review (D3 L292–294; D4 step 4 L312–313).**
`deposited` is allowed only from Ready / In use and `returned` only into Ready from the laundry
states. A tap in Helpers plus a scan in Camera, the phone plus the laptop, or the AI calling
`laundry_move` after he scanned gives a new client id, passes dedup, is refused by the table and opens
an entry. The workbook's OPS-03 asks to deduplicate repeated observations ("multiple cameras log a
movement"), not only repeated messages. Change: an event whose target equals the current state (and
place, for a return) is a `duplicate`: kept, no entry, no hold. Say whether a conflict holds the piece
(it should not by itself). The client sends the index `rev` it saw; on a stale rev the reply is
"already done" with the fresh view. Test: a tap and a scan of one deposit → one change, no entry.

**M4. Private pieces: three sinks D10 doesn't name (D10 L437–443; D16 L516; D9 L426).**
- Recently deleted is Firestore in clear (`belongings/service.py:69`: `BIN_TITLE = "A thing you noted"
  # the bin shows no name: it is Firestore, in clear`), and `deleted_list` hands titles to the model and
  to Telegram (`undo/tools.py:99–115`). `wardrobe_item` needs a fixed bin title ("A wardrobe piece");
  the panel shows the words from the sealed index.
- Approval cards: `Tool.summarize` is pure, with no I/O (`tools/base.py:58–61`, `preview` at `:66`), so it can't tell
  whether a `query` names a private piece; pending cards are stored as clear JSON
  (`storage/approvals.py:50`) and Telegram prints the summary (`telegram/service.py:474–477`). Write
  tools that can make a card take piece ids, a free-text name is resolved by a read first, and the
  card's words come from `Tool.preview` (async, read-only) through `redact.py`.
- Making a piece private later: `wardrobe_edit(private=true)` deletes its photos and fingerprints in
  the same change; a type change into a private-by-default category asks "make it private?".
- Needles: add the `approvals`, `deleted_items`, `activity` and session-turn stores as sinks for text
  JARVIS writes (tool results, card summaries).

**M5. OCR'd label text and QR payloads are untrusted, but the plan doesn't bound them or decide the
results' trust (D7 L376–382; `tools/base.py:69`, `:83`; `tools/taint.py:1–20`).**
- Label fields: store only parsed forms (size `^[0-9A-Z /.-]{1,12}$`, fabric names and percentages
  from a fixed list, care words from a fixed list, brand ≤ 30 characters of `[A-Za-z0-9 &.'-]`), never
  the raw OCR text, and never return an unverified field to the model.
- QR: accept only `jw1:` plus exactly 8 characters of the stated alphabet (L5) and look it up in the
  index; any other code on a clothing tag is "not a JARVIS label": never sent, opened or shown.
- Trust: say for the 18 tools whether results are `trusted_output` or `may_vouch`. Recommended: untrusted
  by default; `may_vouch` per result only when every string is his typed label or a fixed-list word,
  never when it carries an unverified field. Test both ways.

**M6. "Where is my …": Things and the wardrobe will disagree (D6 L353–357; D20 L556–570;
`offline/phrases_r14.py` `WHERE`/`PUT`; `tests/test_r14_d_phrases.py:193–197`).** With the AI off,
R13 takes "where is my <type>" but not R14's PUT form, so "I put my watch in the travel bag" still goes
to `belongings_put` and INV-13's watch is in two places. Possessives end on a wardrobe word ("where is
my wife's watch", R14's own "the kids' school bags"). Things entries he made for clothes since R2 are
never consulted. Change: R13's router also takes the PUT form for wardrobe words (→ `wardrobe_edit`
place), refuses possessives and R14's `_NOT_A_THING` words, and leaves accessory words that are usually
Things (bag, glasses, keys) to Things unless a piece of that type exists; `wardrobe_find` with no match
says "Not in your wardrobe; Things has 'black belt' in Drawer 2" through a `belongings_where` read;
`WARDROBE_RULE` covers moves, not only finds. Test: every R14 phrase test still routes to Things with
R13's router installed first.

**M7. Nobody owns `vision/assets.py`, which must learn the `r13-1` release (seam 11 L709–714; Part D
L760–763; `vision/assets.py:16–38`; `test_r7_b_console.py`
`test_the_tasks_load_only_jarvis_own_files`).** It knows one `RELEASE = "r7-1"` and five tasks' files;
`installed()` drives the panel's "not installed"; the R7 test requires every Part B `fetch(` to start
with `BASE + ` and the named files to equal `TASK_FILES`. Change: I0 adds `WARDROBE_RELEASE = "r13-1"`,
`WARDROBE_FILES` and `installed()` over both; D owns the folder and the test edits (`BASE13 + '…'`
beside `BASE + '…'`). The wake word and the new tasks import the same ORT module
(`console-wakeword.js:27`, `:183`), whose `env.wasm` is one per page: one shared loader with the wake
word's settings (one thread, no proxy, `wasmPaths` = ORT's folder), tested with both running.

**M8. The fp32 fallback doesn't fit `plain()`, and a model switch strands stored fingerprints (models
table L224–236; D7 L366–375; D8 L404–406).** 1,280 floats are 5,120 bytes, 6,828 base64 characters,
over the 2,000-character cut (an array is cut at 100). Change: `embed` always returns uint8 (fp32
output quantized on the device with a fixed scale in the manifest); `model` names it (`mnv2-int8-1`,
`mnv2-fp32-1`); fingerprints of another model are never compared and are recomputed on the phone from
saved photos (a look kept without a photo is asked for again). To detect a mis-run, each task's
`load()` runs a fixed input and compares its output digest with the value recorded from Node in the
manifest; a mismatch is "not installed" (for person and face: saving off). Pin the cut exactly
(`onnx.utils.extract_model(src, dst, ["input"], ["472_quantized"])`, onnx 1.23.2, as the planner's
`probe.py` did), commit the cut file, and record the fp32 cut's own SHA-256.

**M9. A 600-piece index can pass 1 MiB (D2 L281–287).** A record with D2's fields, a 60-character
Malayalam label (stored as UTF-8: `ensure_ascii=False`, as `belongings/store.py:85–91`) and full
features is about 1.46 KB raw, 1.98 KB sealed; 600 pieces ≈ 1.14 MiB before pairs, sets, places and
labels (a throwaway estimate; short ASCII labels give the plan's ≈ 0.6 MiB). A write over 1 MiB fails;
the belongings rule refuses it cleanly, so the wardrobe stops taking changes between 500 and 600 pieces
with no plain words. Change: a byte guard (refuse at 900 KB sealed, in plain words, whatever the count),
short keys in the stored JSON, and a test of 600 maximal pieces (Indic labels, every field) at ≤ 900 KB;
or a cap of 400 with the guard.

**M10. `WardrobeContext` has no clock (seam 9 L689–691; compare `helpers/ports.py:129`
`now: Callable[[], datetime]`).** BRIEF-COMMON's "every test takes a clock" can't hold if the code reads
the real one. Change: `WardrobeContext.now` (UTC) beside `zone(uid)`; a static test that nothing under
`wardrobe/`, `offline/phrases_r13.py` or `helpers/house/outlook.py` calls `datetime.now(`,
`date.today(`, `time.time(` or `utcnow`; browser tests pin the page clock (Playwright's
`page.clock`), since the exit check's sweep moves only Python's.

**M11. Evals: the gate at I0, the pilot's pass line, one control (seam 15 L726–730; L845–846;
L873; exit 1 L944–945).**
- R14's runner now fails a stub ("Since I1's review follow-ups … the runner marks such a case failed",
  `evals/r14/run.py:30–33`). Copied and gated at I0, `make eval-mock` is red on every branch until I1.
  Say which: stubs report `not_built_yet` and pass until I1, and I1 flips the runner (a seam test pins
  the flip).
- End-to-end 8 has no formulas, pass line or control. Define: item-ID match rate = scans where his tap
  chose candidate 1 ÷ scans with a candidate; wrong status changes = corrections of state events;
  unavailable pieces suggested = suggested pieces not eligible at suggestion time (from the plan log);
  corrections per use = corrections ÷ events. Default pass line (owner question 14): unavailable
  suggested = 0 and wrong status changes ≤ 1 per 50 events. Control: a recorded log with one planted
  bad suggestion fails.
- The `catalog` control "the dedup off: INV-05 … fail" can't fail INV-05: a re-scan makes a new client
  id; INV-05 rests on the candidate and his tap. Use "candidates off (every scan is new)" for INV-05.

**M12. Calendar: the panel's own reads, a cancelled event, the calendar id (D13 L484–495).**
- Listing his calendars and "the title live from a read while he looks" are reads from a console route,
  not a job; D13 names only the background path. Say which governs them: `BackgroundReads` on the
  `calendar_list_events` row (Allow only, one kind-only audit line), or a gateway call from the route as
  `api/helpers_today.py:233` does.
- With `singleEvents=true` and the default `showDeleted=false`, Google doesn't return cancelled events
  (events.list reference: showDeleted "default False",
  https://developers.google.com/workspace/calendar/api/v3/reference/events/list). An automatic plan
  whose event is cancelled later is found only by absence: an event fingerprint missing from a read
  that covers its window → "event cancelled", the plan kept as a draft, no `outfit_ready`. Test it.
- Accept only a calendar id that `calendarList` returned (kept sealed) and URL-encode it into the path.

**M13. The phone checkpoints and the person check (D9 L411–415, L423; OPS-01's test L813).**
- If the check also gates events (L414 "no event is made"), the natural basket scan, a shirt held over
  the basket, is refused because SSD finds the arm. The check should gate what is kept or sent (a
  photo, a fingerprint, an AI tag); a QR read or an on-device match that sends only ids makes its event.
- The check and the crop use one bitmap; test a clean checked frame followed by a frame with a face →
  nothing saved.
- The server allows 768 px a side while the promise and OPS-01's test say 512: enforce
  `wardrobe_photo_side` from the JPEG's SOF marker (structure only; `photos/imaging.py:59–64` reads it)
  and test a 600-px photo refused.
- "Choose a photo" (no camera) gets the same checks and redraw.

**M14. What the owner reads must carry the limits (summary L26–31, L41–45, L54–55; D9 L429–431;
`vision/privacy.py:24–27`).** Summary 6 says a photo with a person or a face "is refused" and "nothing is
kept about anyone else" as certainties; the Risks say "a detector, not a guarantee". Change the summary
to: "JARVIS checks each photo on the phone for a person or a face and refuses it if it finds one; the
check can miss a hand or a turned face, so look before you save, and delete a photo from Privacy if one
slips through." The camera's privacy row ("Never kept: a camera frame or a picture") and C63's two
promises ("a frame is never stored", "use cases receive results only", H6) change in the same I1 commit
that makes saving possible, with the new words pinned. Summary 9: "the same look; Helpers and Camera
each gain one tab".

**M15. Licences: the pages match the plan; SSD's upstream is Apache-2.0, not MIT (models table
L224–229; D8 L399–402).** At `c5cae0f…`: MobileNet's README opens `SPDX-License-Identifier: Apache-2.0`
and ends "License: Apache 2.0"; UltraFace's `MIT` / "License: MIT", its source
Linzaer/Ultra-Light-Fast-Generic-Face-Detector-1MB, whose LICENSE is MIT; SSD-MobileNetV1's `MIT` /
"MIT License", but its "Source: Tensorflow SSD-MobileNetV1 ==> ONNX SSD-MobileNetV1", and
tensorflow/models' LICENSE puts `/research` under Apache-2.0
(https://raw.githubusercontent.com/onnx/models/c5cae0f1942c8d7727372c7b1f6b485aa39e4421/validated/vision/object_detection_segmentation/ssd-mobilenetv1/README.md;
https://raw.githubusercontent.com/tensorflow/models/master/LICENSE). D8's "MIT texts from the upstream
projects" has no MIT upstream for SSD. Change: ship SSD with both texts (the zoo's MIT statement as
stated, and TensorFlow's Apache-2.0 with an attribution line), MANIFEST `licence` "MIT (ONNX Model
Zoo); weights from the TensorFlow Object Detection API (Apache-2.0)", the same in
`buildbook/gen/libs.py`; UltraFace's MIT text from Linzaer's repository at a pinned commit. The
training-data sentence (WIDER FACE and ImageNet are non-commercial research terms) stays and goes into
C63's successor card.

## LOW

**L1. Pins and seams I0 will trip over (seams 4, 12, 13; D6 L356 vs seam 10 L708).**
`tests/test_r3_seams.py:951–953` pins the cap itself (`range(51)` passes, `range(52)` must fail: becomes
54 and 55); `tests/test_r51_console_assets_linked.py` `NOT_IN_PAGE` needs the four files loaded by other
code; say whether `helpers/kinds.py` `TABS` stays five (`test_r7_seams.py:712`, `test_r11_seams.py:264`;
the wardrobe tab can be console-only) or gains it with both pins; `test_r14_skill_coverage.py:49–55`
makes I1 empty `planned`. D6 writes `add_phrases(routers, *, first=True)` and seam 10
`add_phrases(…, first=False)`: write the signature once (`first: bool = False`; R13 passes `True`).

**L2. Reads and egress (cost table L653).** The 5-minute `outfit_clock` alone reads 2–3 documents × 288
runs ≈ 600–900 a day per owner, plus panel opens: "≈ 100 of each a day" is about ten times low (still
inside 50,000). Cloud Run's internet egress (fingerprints ≈ 0.3 MB a scan session at 150 pieces;
thumbnails ≈ 35 KB each) isn't costed: measure it in the pilot.

**L3. A Web Push tap opens Helpers on its last sub-tab (`jarvis_helpers_tab`), not Wardrobe** (D1
L263–264). Add a tab hint to the push target (one I0 line) or say where it lands.

**L4. Weather.** `WeatherSummary` is `extra="forbid"` (`helpers/house/models.py:104–105`, `:233–237`):
after a rollback to v14.0.2 a stored `next_day` makes the summary unreadable; say the runbook clears it,
or keep tomorrow in a sibling field of `WeatherState`. Say where `WeatherOutlook` gets R11 B's store
(the `house` part's services) and that Helpers off means "Weather unknown".

**L5. `labels.svg`.** No text of his on the sheet (numbers and codes only); served with
`Content-Security-Policy: default-src 'none'`, `X-Content-Type-Options: nosniff`,
`Content-Disposition: attachment`; the code alphabet named (8 characters of base32 lower case).

**L6. Console buttons for archive, restore, merge and remove.** The summary promises a card (L46–47):
the panel's buttons go through `gateway.execute` (as `api/helpers_today.py:233`) or show the same
confirm row, and each route writes its kind-only audit line (`record_change`, as `api/belongings.py`).

**L7. Phone timing and the download line.** A save runs three models in a row: 78 + 82 + 130 ms in
Node here, so ≈ 0.9–1.7 s on a phone at the plan's 3–6×; show "Checking…". "On Wi-Fi" (L52–53) can't be
enforced in a browser: say "the first time you save a photo (about 13 MB)".

**L8. Recently deleted.** A restored `wardrobe_item` lands in "Missing or in review" (it was away up to
30 days); a merge never moves the merged-away id's log pages, so its undo only drops the link.

**L9. The backup and a key change.** It opens only with this JARVIS's token key; after a rotation
(`KEY_ID`, `keyring.py:40`) older files can't be read: say it beside the download button.

**L10. "Seen before?" bands.** MobileNet's pooled features are non-negative, so unrelated pieces
already score a high cosine; centre by the mean of his saved fingerprints before comparing, and record
both scores in the pilot.

## Builder split and scope

- Ownership is otherwise disjoint: A, B and C own their packages and routes; C alone touches R11 B's
  weather files; D alone the vision Part B section and its R7 tests; wiring files stay with I0 and I1.
  The gaps are H4 (A↔B writes), H5 (routes for D), M7 (`vision/assets.py`) and M10 (the clock).
- Scope matches the approved 54; nothing of R13.1 is pulled in beyond up to three photo views a piece
  (which AVT-04 reuses). The one thing to simplify for a free, phone-first R13 is the backup with
  photos (H3): leaving photos to R14's Firestore backups removes the size problem.
- Cost stays ₹0 a month fixed. Every ₹ figure checks against `llm/pricing.py` and ₹95.24; only the
  read count (L2) and egress are understated.

## Verdict

**APPROVE WITH CHANGES.** Fold H1–H6 into the plan before I0 (none needs the owner); fold in M1–M15
(M11's pass line ships as the default for owner question 14); the LOW items are the planner's call.
The plan's facts are right where it counts (every pinned count, size guard, file:line, hash and ₹
figure re-checked); what is missing is mostly contract between parts (H4, H5, M7, M10), the wear
lifecycle (H1), the edges of privacy (H2, M4, M5, M13, M14) and the backup's size (H3).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 17:19 IST | R13 | First edition: fresh-context review of `r13-wardrobe.md` v13.0.1 on `f7e1552` (code `9a8392b`). What holds (pins, sizes, file:lines, model hashes re-checked against the zoo's LFS pointers, the three models re-run on the vendored runtime, ₹ recomputed); coverage of the 54; no CRITICAL; HIGH H1–H6 (the wear lifecycle, AI tagging's privacy gate, the restore's size against the body cap and Cloud Run, A↔B atomic writes, D's HTTP contract, R7's pixel guard); MEDIUM M1–M15; LOW L1–L10; verdict APPROVE WITH CHANGES | 🛠 Mark XXI (fresh-context plan review) |
