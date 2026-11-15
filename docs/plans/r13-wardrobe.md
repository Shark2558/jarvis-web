Version v13.0.1 · 15 Nov 2026, 16:42 IST · Release R13 · Status: Draft · Owner: 🛠 Mark XXI

# Release R13 — Wardrobe & laundry, phone first (`v13.0.0`)

**Phase:** 5 groundwork (camera checkpoints, built in their phone form) on Phase 2 tools and Phase 3
memory, with Phase 7 evals. **Type:** free: ₹0 a month fixed, no new paid service, no new secret, no
new Cloud Scheduler job; the optional AI tagging is off by default and shows its ₹ first. **Scope
(approved by the owner, 15 Nov 2026, ≈ 16:35 IST):** the 54 Catalog and Styling use cases of his
wardrobe workbook; Try-on (15) is R13.1 `v13.1.0`; Extras (11) later. **Branches:** I0 `r13-i0`
(from `main` @ `9a8392b`, R14 live as `v14.0.2`) → parts `r13-a` … `r13-d` → integration `r13-i1` →
PR `v13.0.0 · R13 Wardrobe & laundry, phone first · Mark XXI`, rebased on `main` after R6.2's PR
(`v6.2.0`) merges first. Every commit carries `JARVIS-Version: v13.0.0` and `JARVIS-Mark: XXI`.
Read on `9a8392b`; every file:line below is from that commit.

## Summary for the owner (plain words)

1. **Every piece you own gets its own number**: each shirt, each sock and each shoe. A pair of
   socks or shoes is two pieces plus one pair; a kurta set is its pieces plus one set. A piece is
   always in one of your workbook's 10 states (Ready, In use, In laundry, Washing, Drying, Needs
   prep, With laundry provider, Needs repair, Missing or in review, Archived).
2. **Your phone is the camera.** In the JARVIS app, Camera gets a fourth tab, **Wardrobe**: "Add
   pieces", "To laundry", "Back clean", "Find" and "Read a label". Or you just tap ("to laundry",
   "back clean", "worn today") in Helpers → **Wardrobe**, or say it. A fixed basket camera can be
   added later without changing anything: every event already says where it came from (phone,
   tap, later camera).
3. **Recognition is free.** You tap the kind (shirt, vest, sock, shoe, belt, watch, kurta …) and
   JARVIS suggests the colour. "Have I seen this before?" is answered **on the phone** by a small
   picture model (3.5 MB, Apache licence) that never sends the picture anywhere to compare. For
   identical copies (two black vests) JARVIS prints a sheet of small numbered QR labels; the phone
   already reads QR codes. Size and care labels are read on the phone; a wash symbol stays
   "unverified" until you confirm it.
4. **Laundry, start to finish**: the basket, a wash load, drying, pressing, a dry-cleaner or
   laundry shop (with a due date and a "short delivery" flag), pieces coming back in parts, a
   sock whose partner is missing. JARVIS prepares and reminds; it **never orders, pays, calls or
   sends a WhatsApp message**.
5. **What to wear**, by fixed rules that explain themselves (the AI stylist stays in R17, paid):
   "what should I wear tomorrow" uses your own timezone, the one calendar you pick (only the
   fields you pick), the weather for your home area (Open-Meteo, already in R11), and rules for a
   formal meeting, Diwali, Holi ("okay to stain" pieces only) and a rainy day. If a planned piece
   goes into the basket the night before, the plan is fixed at once and you are told.
6. **Private stays private.** Underwear, vests and anything you mark private need no photo and
   never get one; they appear only in your own Wardrobe checklist, never by name in an alert, on
   Telegram, on the lock screen or in what the AI is shown. A photo with a person or a face in it
   is refused; a saved photo is cropped to the piece, locked with JARVIS's keyring and listed in
   the Privacy panel with export and delete. Nothing is kept about anyone else.
7. **Archive, restore, merge and remove always ask you first** (a card); a removed piece waits 30
   days in Recently deleted. You can download a sealed wardrobe backup and restore it without
   duplicates.
8. **Cost: ₹0 a month.** About 15–20 MB of photos and history for 150 pieces, inside Firestore's
   free 1 GiB; with R14's backups switched on about ₹0.6–0.8 a month more. Optional AI tagging, off
   by default: about ₹0.01 a photo on the fast model, about ₹0.3 at most, capped at ₹30 a month.
   Your phone downloads about 13 MB of model files once (about 27 MB if the "Hey Jarvis" runtime is
   not on it yet), on Wi-Fi.
9. **The console looks exactly as it does today**: the Wardrobe is a new tab inside Helpers and a
   new tab inside Camera, built only from the components already there. No new dock button.

## What is built: the 54 use cases, and where all 80 go

| Group | Use cases | Part |
|---|---|---|
| Inventory | INV-01–17 (17) | A · Catalog and the ledger |
| Controls: ordering and recovery, backup | OPS-03, OPS-06 (2) | A (D4: the order rule lives with the store) |
| Laundry lifecycle | LND-01–08, LND-10–15 (14) | B · Laundry |
| Controls: blind periods | OPS-02 (1) | B |
| Styling | STY-01–17 (17) | C · Styling |
| Shortage before an event | LND-16 (1) | C (D0: it reads plans, which C owns) |
| Controls: calendar and notifications | OPS-04 (1) | C |
| Controls: item-only capture | OPS-01 (1) | D · Phone and panel |
| **Total** | **54** | |

All 80 IDs (the workbook's sheet "Use Cases"):

| IDs | Goes to | Why |
|---|---|---|
| INV-01 … INV-17 | **R13** (A) | Everything stands on item IDs, states and events |
| LND-01 … LND-08, LND-10 … LND-15 | **R13** (B) | Phone form of the checkpoints (D5) |
| LND-16 | **R13** (C) | A Styling use case in the workbook |
| STY-01 … STY-17 | **R13** (C) | Rule-based, ₹0 (D12) |
| OPS-01, OPS-02, OPS-03, OPS-04, OPS-06 | **R13** (D, B, A, C, A) | OPS-01 and OPS-02 in their phone form (D5) |
| AVT-02 (no-photo form), AVT-03 … AVT-11, AVT-14, AVT-15, OPS-05 | **R13.1** `v13.1.0` (13) | Needs Catalog's IDs and photos; three.js 0.187.0 (MIT) is already vendored |
| AVT-01 (a body model from his photos) | **Declined** | SMPL-X is licensed for non-commercial research only and may not be redistributed; the repository is public. The mannequin from typed measurements (AVT-02, AVT-03) replaces it |
| AVT-12 (photo-style try-on) | **Later, optional, paid, with consent** | IDM-VTON is CC BY-NC-SA and needs a ≥ 16 GB graphics card: a rented cloud GPU, about ₹2 a picture |
| EXT-01 … EXT-09, LND-09, AVT-13 | **Later** (11) | The workbook: "prioritize additions based on actual use"; LND-09 needs a connected washer (R12) |

Total 54 + 13 + 1 + 1 + 11 = 80.

## How it fits the architecture

| Feature | Layer · skill | Phase | Verdict |
|---|---|---|---|
| Wardrobe catalog: one ID a piece, pairs, sets, places, QR labels, counts, search | L5 Skills, L7 sealed · Task & Productivity | 2/3 | Build now |
| The ordered event ledger and the 10 states | L7 Data, L3 Context · Task & Productivity | 3 | Build now |
| Laundry lifecycle, outside laundry, review queue and holds | L5 Skills · Task & Productivity | 2/4 | Build now (phone and tap; camera later) |
| Rule-based outfits, plans, reservations, refresh on change | L5 Skills, L3 · Decision Support | 4 | Build now |
| Selected calendar, selected fields | L6 Integration (governed background read) · Decision Support | 2/4 | Build now; off until he picks a calendar |
| Phone Wardrobe mode: fingerprint, colour, person and face checks, QR, labels | L1 device, L2 Input Processing (the R7 vision engine) · Task & Productivity | 5 groundwork, 6 | Build now |
| Optional AI tagging | L4 (the LLM interface, fast tier) · Task & Productivity | 7 cost | Build now; off by default |
| Fixed basket and return cameras | L2 Input, L6 home bridge | 5 | Not built: the event model takes them later (D5) |
| AI stylist | L4 · Creative | 4 | Not built (R17, paid) |

No change to the reference architecture: the wardrobe is a Layer 5 skill on the R7 vision engine (L2)
and the R14 skill register; a fixed camera later only adds a `camera` event source.

## What the code says today (`main` @ `9a8392b`)

1. **Version and limits.** `__version__ = "14.0.2"` (`src/jarvis/__init__.py:3`; pinned in
   `tests/test_about.py:24`, `test_r11_1_seams.py:73`, `test_r14_seams.py:98`, `test_r7_seams.py:110`);
   persona `p14.0` (`core/prompts.py:62`, pinned in 21 test files). Sizes: `api/app.py` **727** (guard
   ≤ 735, `test_r14_seams.py:475`), `tools/gateway.py` **760** (guard 760, `test_r14_seams.py:476`,
   `test_r1_seams.py:649`), `core/brain.py` 713 (guard ≤ 741, `test_r11_1_a_brain.py:301`),
   `console.html` **782** (guard ≤ 782, `test_r7_seams.py:607`, `test_r11_1_seams.py:246`,
   `test_r14_seams.py:477`), every `console*.js` ≤ 800 (`test_r7_seams.py:653`, `test_r14_seams.py:480`;
   the largest are `console.js` 769, `console-brief.js` 764), `config.py` 729 (guard < 800,
   `test_r14_seams.py:478`). The dock has 22 buttons (`test_console_assets.py:514`,
   `test_arch_coverage.py:529`, `test_r7_seams.py:619`).
2. **Things ("where did I keep it?", R2).** `belongings/models.py:16–17` `MAX_LIVE = 500` things,
   `MAX_HISTORY = 50` moves; a thing is free text (`name`, `place`, `note`) plus `holder_id` (whose
   it is). `belongings/store.py` keeps ONE sealed index document per owner (purpose `belongings`)
   and one sealed history document per thing, written together in one transaction
   (`BelongingsStore.change`, `:143`). `belongings/text.py` `thing_key` (NFKC, plurals, synonyms),
   `recall/retrieval.py` `bm25` and `recall/sensitive.py` `sensitive_reason` do the matching and the
   "IDs go in the Vault" refusal. No ID for a place, no state, no event.
3. **The vision engine (R7).** `console-vision.js` is the one port: tasks see pixels, use cases
   never do (`:1–15`); `register()` is sealed after the built-in tasks (`:8`, `sealRegistry()` at
   `:349`), so a new task is added by editing the Part B section, never from a use case. A Result's
   data is copied by `plain()` (`:27–34`): **arrays are cut at 100 items and strings at 2,000
   characters**. The I0 core (everything before `// ==== R7 Part B`) is pinned by SHA-256
   (`tests/test_r7_b_console.py:38`). Tasks: `text` (tesseract.js 7.0.0), `code` (zxing-wasm 3.1.6),
   `quality` (arithmetic), `objects` and `pose` (MediaPipe; their models never arrived, so "not
   installed": `vision/assets.py:1–8`). Files come from `/static/vendor/vision/<release>/` (`BASE`,
   `:137`, release `r7-1`), served by `api/console.py:325–413` (`console_vision`, `:403`) only when MANIFEST.json lists them with
   a matching SHA-256; the route already accepts any release folder and `application/octet-stream`
   (`VISION_TYPES`). The server's contract is `vision/results.py:22–23` (`TaskName`, `TASKS`, the
   five; pinned `test_r7_seams.py:996`, `test_r7_b_console.py:209`, `:259`, `test_r7_b_dom.py:161`);
   `vision/tools.py:34` uses `TASKS` as the kept-results enum.
4. **The camera and the picture door.** `console-camera.js` is the only file that asks for a
   camera (`test_r7_b_console.py` pins it); `console-camera-panel.js:20` has three sub-tabs (Look,
   Results, Cameras) and redraws a photo before anything uses it. A picture leaves the device only
   through I0's door `console-r7-send.js` (`ask`, `attach`, `vault`, `:100`), which redraws it with
   R11.1's `shrink` and counts "Pictures sent from this device today". The camera's privacy row says
   "Never kept: a camera frame or a picture" (`vision/privacy.py:23–26`); the guide's C63 says "a
   frame is never stored and never leaves the device" (`docs/architecture/JARVIS-Architecture.md:364`).
5. **onnxruntime-web 1.30.0** (MIT) is vendored for the wake word: the single-threaded WASM build
   only (`static/vendor/ort/MANIFEST.txt`), served at `/static/vendor/ort-1.30.0/`
   (`api/console.py:195`).
6. **The keyring.** 22 cipher purposes, the last `backup_probe` (`keyring.py:42–78`), plus
   `webpush_vapid` (`:79`). Pinned: `test_r7_seams.py:294`, `test_r11_seams.py:166`,
   `test_r14_seams.py:258` (the last is `backup_probe`) and `:259`, the whole set in
   `test_r3_seams.py:850`.
7. **Privacy panel.** `privacy/ports.py` `PrivacySource` (`describe`, `export`, `delete`; delete
   classes none / simple / confirm / passkey); `privacy/sources.py` `CallbackSource`; the list is
   `api/personal.py:239–289` (`r14_privacy_sources` at `:287`, home's last). Sections come from the
   server (`console-privacy.js:90–94`); the export is scrubbed (`privacy/export.py`).
8. **Permissions.** 49 rows (`permissions/groups.py`), R11.1's `pictures` (`:567–575`) before
   Maps and YouTube, which stay last (`:576–592`). Pinned 49 in `test_r1_seams.py:231`,
   `test_r2_seams.py:576`, `test_r3_seams.py:913`, `test_r11_1_seams.py:139`, `test_r7_seams.py:259`,
   `test_r14_seams.py:264`. The save cap `PermissionsPatch.groups` is 51 (`permissions/models.py:133`).
   The console draws the rows the server sends (`console-permissions.js:148`, `:374–376`).
9. **The gateway** (`tools/gateway.py`, read in full): ASK for `Tool.ask_when` (`:239–240`), a
   spoken turn and a tainted round (`:243–247`, `spoken_ok` relaxes only a spoken, untainted
   turn), the 11th undo-able delete is a card (`:446–447`), a card runs only as the owner saw it
   (`:589–630`), arguments reach the audit as a hash only (`tools/audit.py:82`). It needs no change
   for R13. "Approve all" skips `NO_BULK_TOOLS` (`core/guardrails.py:69`, `:119`).
10. **Recently deleted.** `undo/models.py:30` `Kind = event | task | vault_item | note | thing`;
    in-place kinds and passkey purges (`:39`, `:42`); `api/personal.py:111–124` `register_undo`;
    the console's kind words `console-deleted.js:25–26`.
11. **Telegram.** `telegram/rules.py:66` `PERSONAL_PATTERNS = vault_*, kb_*, belongings_*` (reads
    and writes) behind its own switch, default off; `PRIVATE_PATTERNS` (`:41–63`) and
    `HOME_PATTERNS`; `tests/test_telegram_tool_guard.py` makes every read tool pick a side.
12. **Alerts.** 52 kinds (`alerts.py:22–96`), pinned in `test_r3_seams.py:166`, `test_r6_seams.py:142`,
    `test_r11_seams.py:67`, `test_r11_1_seams.py:119`, `test_r7_seams.py:232`, `test_r14_seams.py:198`;
    daytime rings `notify/policy.py:27` (exact set pinned `test_r51_seams.py:45`); held words
    `notify/held.py:14`; Web Push targets `webpush/service.py:77` (every kind but `test`,
    `test_r7_a_push.py:43`), the helpers' kinds open `helpers` (`:100`); book words
    `buildbook/plain.py:155`; the Alerts card's list `console-alerts.js:20`. Alert text is a fixed
    template written by code (`alerts.py:1–6`).
13. **No-AI.** Phrase routers are tried in the order they were added: `offline/mode.py:70–73`
    `add_phrases` only appends (at most 64, `:40`). R14's `things` router (`offline/phrases_r14.py:201`,
    `:218`) takes "where is my black belt" today and sends it to `belongings_where`.
14. **Calendar reads in the background.** `helpers/nudges/calendar.py` reads the PRIMARY calendar
    only (`EVENTS_URL`, `:37`), through the governed path `tools/background.py` (the gateway's
    policy and the owner's row for `calendar_list_events`, "Allow" only, one kind-only audit line);
    "an event's title is used only to match his own words in code; it is never put in a message, a
    log or a stored document" (`:6–9`). The `calendar.readonly` scope is already required
    (`integrations/google.py:36–41`), so listing his calendars needs no new Grant.
15. **Weather.** R11's `helpers/house/weather.py` asks Open-Meteo for 2 days (`request_params`,
    `forecast_days: "2"`), but `summarize` keeps **today only** (`:202–218`: `day`, `t_max`,
    `rain_from`), and `RainHint` (`helpers/house/rain.py`) answers for today. Nothing knows
    tomorrow's weather.
16. **The seeing brain.** `picture/eyes.py` `BrainEyes`: fast tier, no tools, fixed instructions,
    No-AI refuses, only a brain that sees and never trains, `Billing.ensure_allowed` first, one
    recorded cost. Prices `llm/pricing.py:29–31` (Haiku 5.5 $0.10/$0.50, Sonnet 5.5 $2/$10 per
    million tokens).
17. **Pictures on the server** are cleaned by structure, never decoded: `photos/imaging.py:67`
    `sanitise_jpeg` (EXIF, GPS, XMP, ICC and comments gone). segno 1.6.6 (BSD-3) makes QR codes on
    the server already (`helpers/today/qr.py`).
18. **Wiring.** R14's pattern: `api/r14_wiring.py` builds parts through a contract
    (`hardening/ports.py`: `TOOL_FAMILIES`, `JOB_OWNER`, `SERVICE_OWNER`, …) and leaves out a part that
    breaks it ("setup failed"); `api/tick_wiring.py` holds the morning-tick list and the one 5-minute
    clock (`clock_jobs`, run for the brief's owners, Home on or off); `app.py:377` passes `r14=` to
    `build_gateway`, `:496` awaits `wire_r14`, `:687` installs its routes.
19. **Helpers frame.** `console-helpers.js:15` five sub-tabs (Today, Home, Nudges, Kitchen, Watch;
    Watch was R7's I0 seam, `test_r7_seams.py:715`), loaded by `import()` (`:106–110`), one set of
    builders (`row`, `toggle`, `section`, `note`); `.hp-tabs` is a 4-column grid
    (`console-helpers.css:6`), so a sixth tab sits on the second row as Watch does now.
20. **R14's drill** counts every root collection it finds and compares samples on a document's own
    `updated_at` / `updated` / `at` / `ts` (`backup/walk_checks.py:47`); sub-collections must be listed
    (`:31`). A flat document id (`{uid}_{x}`) needs no change there.
21. **Evals.** `evals/run_all_mock.py` lists gated suites; R14's runner shape is `evals/r14/run.py`
    (`PART`, `BUILT`, `cases()`, `control()`; an unbuilt part fails; a built part's control must make
    it fail).
22. **The R14 hotfix-2 lesson** (`docs/plans/r14-integration/I1-NOTES.md`, section 14): a test that
    reads today's date is a date bomb; a whole-suite run with the clock moved forward (`time-machine`
    in a plugin outside the repo) caught two more.

## The model files (verified 15 Nov 2026 in this workspace)

Hugging Face and Google's storage host refuse this workspace; GitHub answers. All three files are in
the ONNX Model Zoo (`github.com/onnx/models`, repository licence Apache-2.0) at commit
`c5cae0f1942c8d7727372c7b1f6b485aa39e4421`; each was downloaded, its SHA-256 matched the Git LFS pointer
the repository holds, and each ran on the **vendored** onnxruntime-web 1.30.0 WASM build, single
thread (Node 22, this workspace's CPU; a phone is likely 3–6× slower, an estimate the pilot measures).

| Task | Upstream file (zoo path under `validated/vision/`) | Licence (the zoo's model page) | Upstream SHA-256 · bytes | Served file | Measured |
|---|---|---|---|---|---|
| `embed` ("seen before?") | `classification/mobilenet/model/mobilenetv2-12-int8.onnx` (MobileNet v2-1.0 int8) | Apache-2.0 (`SPDX-License-Identifier: Apache-2.0`, "License: Apache 2.0") | `cc028fe6cae7bc11a4ff53cfc9b79c920e8be65ce33a904ec3e2a8f66d77f95f` · 3,655,033 | `mobilenetv2-int8-embed.onnx`: the graph cut after the global average pool and its `Reshape` (output `472_quantized`, uint8 × 1,280; the classifier removed, weights byte-identical): `c32ba47ca0cadf3845f771da1e429aa992e7b92d598b1e1a68054ed6b54e4ab0` · 2,368,080 (cut with onnx 1.23.2) | 70 ms |
| `face` | `body_analysis/ultraface/models/version-RFB-320.onnx` (UltraFace) | MIT (`SPDX-License-Identifier: MIT`, "License: MIT") | `34cd7e60aeff28744c657de7a3dc64e872d506741de66987f3426f2b79f88017` · 1,270,727 | as upstream | 82 ms |
| `person` | `object_detection_segmentation/ssd-mobilenetv1/model/ssd_mobilenet_v1_12-int8.onnx` (SSD-MobileNetV1, COCO's 90 classes, "person" is 1) | MIT (`SPDX-License-Identifier: MIT`, "MIT License") | `2b79e6a7fb1ec6a33f332b9b10d82d9de4b7b49dcd26b5946921bb356895c954` · 9,540,809 | as upstream | 113 ms |
| `colour` | none: plain arithmetic | JARVIS's own | — | — | — |

Considered and not chosen: DINOv2-small (Apache-2.0, better at "same piece?", but about 22 MB int8,
about 60× the compute, and on Hugging Face, which this workspace can't reach: an R8 candidate);
CLIP ViT-B/32 (MIT, about 88 MB quantized: too big for a phone); MediaPipe's image embedder (Apache,
but a `.tflite` on Google's storage host, unreachable, and not on ONNX Runtime); MobileNet v2 fp32
(Apache, 13.9 MB, `c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5`): the fallback if
a phone's browser mis-runs a quantized operator (D8).

## Decisions (binding)

**D0 · Scope, parts and order.** R13 builds the 54 use cases above in four parts after I0: **A ·
Catalog and the ledger**, **B · Laundry**, **C · Styling**, **D · Phone and panel**. Two moves from the
brief's split, because the code argues for them: **OPS-03 goes to A** (the order rule is the store's
own fold: the belongings pattern writes the state and its history in ONE transaction,
`belongings/store.py:143`, and OPS-03 says "persist status and event details together"), and **LND-16
goes to C** (it is a Styling use case in the workbook and reads plans, which C owns; B supplies each
piece's expected return through A's view). Everything is plain code; the only model call is the
optional AI tagging (D7). No new Scheduler job: R13's jobs ride the morning tick and the 5-minute
clock (`api/tick_wiring.py`). Nothing spends money unless he switches AI tagging on and presses the
button that shows its ₹.

**D1 · Where it lives in the console: inside Helpers and Camera; `console.html` untouched.** A new
dock panel would need a `<section>` and a dock button in `console.html` (at its 782-line guard) and a
23rd dock button (three pins and the dock-fit browser test). Instead:
- **Helpers → Wardrobe** (a sixth sub-tab, as R7 added Watch: `console-helpers.js:15`, `:106–110`):
  sections "Needs a check" (the review queue), "Today and tomorrow" (plans and their reasons),
  "Laundry" (basket, loads, drying, prep, outside), "Pieces" (search, counts by category, pairs and
  sets, places, private basics behind a tap), "Labels" (the QR sheet), "Settings" (calendar and
  fields, alert lead, private display, AI tagging). Built only with the frame's builders (`row`,
  `toggle`, `section`, `note`) and existing classes (`.btn`, `.bsw`, `.hp-*`, `.sfine`).
- **Camera → Wardrobe** (a fourth sub-tab in `console-camera-panel.js:20`): the phone checkpoints
  (D5).
- **Zero lines of `console.html` are needed**, so none are freed; the dock stays 22. I0's seam test
  pins `console.html` byte-identical to `9a8392b` for R13. Web Push targets open `helpers`
  (`webpush/service.py:100`); the frame remembers the last sub-tab (`jarvis_helpers_tab`).
- **The look does not change**: new CSS (`console-wardrobe.css`, ≤ 200 lines) only places things,
  using the theme's tokens; a static test refuses a colour literal, a font, a shadow or a radius
  not taken from a `var(--…)`, and `ui_checks.py` audits the new tabs (touch targets, overflow).

**D2 · One ID per physical piece; the store.** Records (frozen, JSON in and out, I0's
`wardrobe/model.py`):

| Record | Id | Holds |
|---|---|---|
| Piece | `wi_` + 12 hex | category, type (the workbook's 8 categories and their types; `unknown`; custom types he adds), label ≤ 60 (his words), colour and pattern (fixed lists) with a `locked` set, features (sleeve, collar, strap colour …, fixed lists), size, brand, fabric, care (each `verified` or not), formality 1–5, occasion and weather tags, `mess_ok`, `delicate`, `private`, place id and when confirmed, state and `back_to`, hold, wears and last worn, label code, photo ids |
| Pair | `wp_` + 8 hex | two piece ids (left/right or a sock pair), `paired_on`; wearable only while both pieces are eligible |
| Set | `ws_` + 8 hex | 2–6 piece ids, "parts can be worn alone" (yes/no per part) |
| Place | `wl_` + 8 hex | label ≤ 40 (Drawer 2, Shoe rack, Accessory tray, Travel bag), kind `storage` / `intake` / `basket` / `return` / `travel` / `out`, `baseline_at` (INV-02 coverage), `camera: null` (later) |
| Label | number + 8-character random code | the QR's payload `jw1:<code>` and the piece it is stuck on (or none) |
| Event | `we_` + 20 hex, plus the client's own id | D4 |

Storage (prefix `jarvis_`; no sub-collections, every document carries `updated_at`, so R14's drill
counts and samples them unchanged, fact 20): the **index** `wardrobe/{uid}` (pieces, pairs, sets,
places, labels, his custom types, settings) is one sealed document like Things' (`belongings/store.py`),
at most **600 live pieces** (a 600-piece index is ≈ 560 KB sealed, under Firestore's 1 MiB with a
margin; the 601st is refused in plain words); each piece's **event log** is `wardrobe_log/{uid}_{piece}_{page}`,
pages of 200 sealed events, append-only. An event and the index change are written in **one
transaction** (`Docs.transaction`), every read first (the belongings rule). Not reusing Things: D6.

**D3 · The 10 states, as data.** I0's `wardrobe/states.py` is the workbook's "Item status and
availability" table: the 10 states, which are eligible for an outfit (Ready only, and only when
accessible, complete if paired, and not reserved for an overlapping event), and the transitions each
event kind may make (e.g. `deposited`: Ready / In use → In laundry; `returned`: Drying / Needs prep
/ Washing / In laundry → Ready with a place; `received`: With laundry provider → Ready or Needs prep;
`archived`: any → Archived; `restored`: Archived → Missing or in review until he confirms the
condition, INV-17). "Missing or in review" remembers `back_to`, the latest verified state, so a
cleared hold returns there (LND-04). `wearable(pair)` and `wearable(set, parts)` are pure functions
there, used by A's counts, B's half-pair rule and C's engine alike.

**D4 · The ledger: ordered, append-only, the newer verified event wins (OPS-03, LND-05; Part A).**
An event is `{id, client_id, piece | null, kind, at (when it happened, UTC), recorded, source, via,
verified, evidence {how: qr | match | tap | label | owner, score}, place, load, batch, voids, note ≤ 120}`.
`apply(uid, events)` in A's store:
1. **Deduplicate**: a `client_id` or an `id` already in the log is ignored (two phones, a retry, a
   restore, a camera that sends twice).
2. **Order by item**: events fold in `(at, recorded, id)` order. `at` from a device is clamped to
   the server's time ± 5 minutes; one in the future is refused.
3. **The newer verified event wins**: an event older (by `at`) than the piece's newest verified
   state-setting event is kept in the log, marked `superseded`, and changes nothing (an old basket
   message after a confirmed clean return can't make the shirt dirty again).
4. **A transition the table refuses** is kept as `conflict` and opens a review entry; the state
   stays.
5. **An unverified event that would change availability** becomes a hold ("Missing or in review",
   `back_to` kept), never a state change.
6. **A correction** (`corrected`, `voids: we_…`) re-folds that piece from its valid history; later
   verified events stay authoritative; if two later events conflict, a rescan is asked for.
After the commit, A tells the observers (I0's `ChangeObserver`, called once per changed piece, never
raising, never inside the transaction): C's plan refresh (STY-15) is one of them.

**D5 · Checkpoints in their phone form; the camera later.** Every event's `source` is `phone` |
`tap` | `camera` (`via`: panel / chat / voice / telegram for a tap; the device's random id for a
phone). The workbook's three camera checkpoints are Camera → Wardrobe modes or one tap:

| Checkpoint | Phone form now | What a fixed camera adds later |
|---|---|---|
| Wardrobe intake | "Add pieces" (one or several laid apart; a box per piece) | `camera` events from R8's camera setup into the same `apply()` |
| Dirty basket | "To laundry" scan, or a tap / "my navy shirt is in the laundry" | a crossing and a release seen over the rim |
| Clean return | "Back clean": the place it goes to, and dry / needs pressing | the return surface |

- **LND-02 (a deposit, not a hover):** on the phone a deposit exists only when he presses "Put in
  laundry"; a scan he leaves or cancels changes nothing. The model already holds the camera's
  evidence fields (`crossed`, `released`); a `camera` event without a release goes to review.
- **LND-03 (a bundle):** in one photo each box with enough evidence (a QR read, or a match he
  confirms) becomes a deposit; "and N more I couldn't show" makes a **pending deposit with no piece
  id** (never a guess) and holds only the plausible pieces: those of the category he names that are
  In use or were worn in the last 24 hours (STY-17); none plausible → no hold, a review entry.
- **OPS-02 (a blind period):** "I moved things without scanning" (a tap, with the places or
  categories touched) holds the affected pieces until a rescan or his correction; and a piece whose
  last verified sighting is older than `wardrobe_stale_days` (14) makes any plan using it ask for a
  quick check (STY-10). A camera outage later marks its zones blind the same way.
- **OPS-01 (item-only capture):** D9's person and face refusal, the crop, on-device processing,
  the camera's existing Stop and lock (`console-camera.js`), photo retention, and the rule for later
  fixed cameras: only the intake surface, the basket rim and the return surface, never where he
  changes (a place's `kind`; R8 checks the framing).

**D6 · Things is not reused as the store; its text tools are.** Why not: Things is one free-text
place per thing (no place ids for "Drawer 2"), no state, no event log, at most 500 things and 50 moves
shared with everything else he notes, and a `holder` that is about other people (`belongings/models.py`);
a wardrobe of 150–600 pieces, each with a 200-event history, would crowd it and break INV-13's "last
confirmed place" and OPS-03. Reused: `belongings.text.thing_key` for names, `recall.retrieval.bm25`
for "blue striped shirt" (INV-09, INV-15), `recall.sensitive.sensitive_reason` on his free text. "Where
is my black belt": with the AI on, the persona sends a piece of clothing, footwear or an accessory to
`wardrobe_find`; with it off, R13's phrase router runs **before** R14's `things` router (I0 adds
`add_phrases(routers, *, first=True)` to `offline/mode.py:70`) and takes only "where is/are my <a
wardrobe type word>" (shirt, belt, watch, sock …); everything else still reaches Things.

**D7 · Recognition, free by default.**
- **Kind by one tap**: chips from the workbook's categories (shirt, T-shirt, trousers, jeans, vest,
  underpants, sock, shoe, sneaker, sandal, belt, watch, kurta, blazer, jacket, rainwear …, and
  Unknown); he may add a type; changing the type never changes the id (INV-04).
- **Colour suggested** by the `colour` task (arithmetic: the median of the box's centre in Lab, the
  nearest of 18 named colours by ΔE; "multicolour" when two clusters are close in size): a
  suggestion he confirms or locks (INV-09).
- **"Seen before?" on the phone**: the `embed` task returns the piece's 1,280-number fingerprint
  (uint8, minus the zero point, as a 1,708-character base64 string: inside `plain()`'s 2,000 limit,
  fact 3). The Wardrobe mode fetches his saved fingerprints (`GET /v1/wardrobe/fingerprints`: sealed
  at rest, decrypted for the signed-in console, kept in memory only), compares by cosine (the best
  of each piece's views) and shows at most 3 candidates; **nothing is decided without his tap**.
  The query fingerprint never leaves the phone; a fingerprint is stored only with a photo he saves.
  Starting bands (calibrated in the pilot): ≥ 0.86 "likely this one", 0.72–0.86 "maybe", below "new?".
  Two candidates of one type within 0.02 of each other: "identical copies: read its label or tap
  which one", and a basket event holds both until he says (LND-04).
- **QR labels for identical copies (INV-07)**: `GET /v1/wardrobe/labels.svg` (segno, already a
  dependency) prints 24 numbered labels a page; the QR holds `jw1:` and a random code, nothing else;
  the R7 `code` task reads it; a read label is the strongest evidence (verified).
- **Care and size labels (INV-10)**: "Read a label" runs the R7 `text` task; size, brand, fabric and
  care words are offered as **unverified** fields he confirms or types; wash symbols are pictures
  tesseract can't read, so a symbol is never inferred. Read text is other people's words: fenced,
  never obeyed.
- **Optional AI tagging**: off; on only by his setting and his press of "Ask the AI to tag this
  piece (about ₹N)", N from `llm/pricing.py` for the brain that would answer (a 512-px crop ≈ 350
  image tokens + 400 instruction tokens + 120 out: ≈ ₹0.01 on Haiku 5.5, ≈ ₹0.26 on Sonnet 5.5). A's
  `wardrobe/catalog/tagging.py` mirrors `picture/eyes.py` (fact 16): fast tier through `jarvis.llm`
  (a tier, never a model id), no tools, fixed instructions, strict JSON from the same fixed lists, a
  brain that sees and never trains, `Billing.ensure_allowed` first, a cap `wardrobe_ai_tag_month_inr`
  (₹30), never in No-AI mode; the answer is a suggestion, never a locked field; the picture is not
  kept by tagging (only "Save photo" keeps one).

**D8 · The model files: pinned, fetched by a script, served by the existing route.** Part D's
`scripts/wardrobe_assets.py` (standard library plus `onnx==1.23.2`, a dev tool run by hand, never in
the image) downloads the three files from
`https://media.githubusercontent.com/media/onnx/models/c5cae0f1942c8d7727372c7b1f6b485aa39e4421/validated/vision/...`,
refuses any whose SHA-256 differs from the table above, cuts the MobileNet graph (keep the nodes that
feed `472_quantized`, output uint8 `[batch, 1280]`), checks the cut's SHA-256 (`c32ba47c…`; if another
onnx release serialises differently, it prints the new sum, which D records with the reason in
INTEGRATION-D), and writes `static/vendor/vision/r13-1/MANIFEST.json` (`sha256`, `bytes`, `type`
`application/octet-stream`, `source`, `licence`, `changes`) with the licence texts beside them (the
zoo's Apache-2.0 LICENSE; MIT texts from the upstream projects at pinned commits; Apache-2.0 §4's
notice of the cut in `changes`). The route `api/console.py:403` (`console_vision`) serves them once they match; the
runtime stays `/static/vendor/ort-1.30.0/`. `tests/test_r13_d_assets.py` re-hashes every file;
`buildbook/gen/libs.py` lists them. If a phone's browser mis-runs a quantized operator (the pilot's
first scan on his phone), D switches `embed` to the fp32 cut (same licence, its upstream sum above)
and records why. ImageNet, WIDER FACE and COCO, which trained the weights, have their own terms for
the data; JARVIS uses the published weights under the zoo's stated licences for one person,
non-commercially (the position R7 took for MediaPipe's COCO-trained detector).

**D9 · A photo is a press, a crop and a seal; a person or a face is refused.**
- **The checks**: before any "Save photo" or fingerprint, the whole frame goes through `person`
  (SSD, "person" ≥ 0.5) and `face` (UltraFace, ≥ 0.7, NMS). Either found → nothing is saved, no
  fingerprint is kept, no event is made: "This picture shows a person. Lay the piece on a surface or
  hang it, and take the photo again." Without the two model files, saving a photo is off ("not
  installed") and taps still work. A test hook can only add refusals, never remove one.
- **The crop**: the Wardrobe mode draws the piece's box into a ≤ 512-px JPEG (quality 0.8, ≈ 35 KB) in
  memory and hands it to **the one door**: I0 adds `wardrobe(blob, {piece, view})` to
  `console-r7-send.js`, which counts it in "Pictures sent from this device today" and posts to
  `POST /v1/wardrobe/photos`. The button says so: "Save this photo with the piece (sealed; only you)".
  The scan module never posts picture bytes itself (a static test).
- **On the server** (A): JPEG only, ≤ 768 px a side, ≤ 200 KB, cleaned by `sanitise_jpeg` (fact 17),
  sealed with the new purpose `wardrobe_photos` (AAD `wardrobe/photo/{uid}/{photo}/v1`) in
  `wardrobe_photo/{uid}_{photo}`, at most 3 views a piece (front, back, detail); its fingerprint in
  `wardrobe_fp/{uid}_{shard}` (200 a shard, same purpose). **A private piece never has a photo**: the
  mode skips the step and the route refuses one (422).
- **Promises that change, said plainly**: C63's "a frame is never stored" stays true for frames; a
  wardrobe photo is a crop he chose to save, through the door. I1 edits C63 and the camera's privacy
  note to say so; the persona's camera line names the one exception.

**D10 · Private pieces: count-only everywhere but his own checklist.** Private by default:
underpants, briefs, boxers, vests, undershirts, thermals (he may change any piece). I0's pure
`wardrobe/redact.py` decides what each sink may show:

| Sink | A non-private piece | A private piece |
|---|---|---|
| Helpers → Wardrobe, Camera → Wardrobe (his signed-in console) | everything | everything, behind "Show private basics" |
| What the AI is shown (tool results) | id, his label (fenced), type, colour, state, place | id, slot and state only ("a private basic") |
| Alerts, Telegram, Web Push, the lock screen, the morning brief | type and colour words from the fixed lists ("a navy shirt"), never his label | "a private basic", never a type or colour |
| Logs, audit, Activity | ids and counts only (audit keeps an argument hash, `tools/audit.py:82`) | the same |
| Approval cards | fixed words + type and colour | "a private basic (No. 17)" |

The AI is never told a private piece's name or look, so it can't repeat it; a spoken reply follows
the same view. The Telegram switch for personal reads gates every R13 tool (D18); with it on, the
redaction still holds.

**D11 · Laundry: prepare, never order or pay (Part B).** Deposits (LND-01), lifting out of the basket
keeps the hold (LND-06), a load holds only confirmed ids (LND-07), each step moves only the pieces
named (LND-08, LND-10), a clean return restores the same id with its place and triggers the plan
check (LND-11), parts of a load come back separately (LND-12), a half pair stays out of pairs
(LND-13; a replacement half only by his explicit re-pairing), outside laundry and dry-cleaning are
records: his label for the shop (≤ 40, no phone number: a run of 5+ digits is refused), a bag
reference, the pieces, a due date, "overdue" and "short delivery" flags, each piece checked back in
(LND-14); the history shows verified events, corrections and the current step (LND-15). No call, no
WhatsApp, no order, no payment: there is no tool that could. A pending deposit, a hold and a
conflict are entries in B's review queue (`wardrobe_review/{uid}`), resolved by a scan, a label, a
tap among the candidates or "there was no deposit" (which clears the hold to `back_to`). LND-05's
correction uses A's `correct()`.

**D12 · Styling by fixed rules (Part C).** `wardrobe/styling/rules.json` (data, checked at start):
slots (base: vest/undershirt and underwear, both private; top; bottom; outer; socks; shoes; belt;
watch; extras: tie, cap, scarf), dress codes (business formal, business casual, smart casual, casual,
festive / traditional, mess-tolerant, sport), event rules (formal meeting → business formal, shoes +
belt + watch; Diwali and other festivals → festive, sets checked whole; Holi → only `mess_ok`
pieces, never `delicate`; rain likely → rain-ok shoes and an outer layer; heat → light fabrics), a
small colour-pairing table, and rewear defaults (trousers, jeans, outerwear, belts, shoes and the
watch reusable; shirts, T-shirts, vests, underwear and socks to laundry after a wear). The engine
(`styling/engine.py`, pure) applies hard exclusions first (state, holds, reservations, his "never"
rules such as "no tight collars", STY-08), fills required slots, ranks by dress-code fit, weather,
colour pairing, recent wear and his preferences, ties broken by piece id, and returns a primary look
and up to two alternatives, each with its **reasons** and the **actual piece ids** (STY-11), its
compromises, and any **gap** with a next action ("press the white shirt", "collect from the
dry-cleaner tomorrow", STY-16, LND-16). Plans (`wardrobe_plans/{uid}`): a date or an event, the
dress code (tentative until he sets it, STY-03), locked slots (STY-12), reservations by time window
with conflicts and deliberate transfer (STY-14), several events in a day with shared pieces and
"change these" lines (STY-13). **Refresh (STY-15)**: C's observer on A's ledger (D4) marks a plan
using a changed piece "needs a new …", proposes a ready substitute (auto-swap off by default), and
sends `outfit_changed` when the event starts within 36 hours. **Wear (STY-17)**: only his "I wore
these" records a wear; saving or previewing a plan changes no count; after a wear each piece goes to
laundry or back to Ready by the rewear rule, or as he says. The AI stylist stays in R17.

**D13 · Only the calendar he picks, only the fields he picks (OPS-04; Part C).** Settings → "Outfits
from a calendar": none by default (manual planning always works). He picks one calendar from his
`calendarList` (the `calendar.readonly` scope is already granted, fact 14) and the fields: start and
end (always), title (on by default: matched against the rules' words in code only), location (off;
"indoor/outdoor" from it when on). Description and attendees are never fetched: the request names
only the chosen fields (Google's `fields` parameter). C's reader follows `helpers/nudges/calendar.py`:
the governed path `tools/background.py` on the `calendar_list_events` row ("Allow" only, one kind-only
audit line), at most every `wardrobe_calendar_refresh_min` (60) per owner, the next 48 hours,
cancelled events skipped, edited ones refreshed by their `updated` stamp. **A title is never stored,
sent or logged**: a plan keeps the event's fingerprint, its times and the dress code; the panel shows
the title live from a read while he looks. Disabling the calendar stops automatic plans from it at
once; existing plans stay, marked "manual".

**D14 · Weather for tomorrow, from R11's helper.** C adds `next_day` (`day`, `t_max`, `rain_from`) to
`helpers/house/models.py` `WeatherSummary` (optional, so stored summaries still read) and fills it in
`helpers/house/weather.py` `summarize` from the 2 days already fetched (fact 15); C's new read port
`helpers/house/outlook.py` `WeatherOutlook.for_day(uid, day)` reads his sealed summary (R11 B's store,
no new outside call). It is the weather of his home place (R11's `outside/{uid}`): every look says
"Weather for your home area: rain likely from 15:00" or "Weather unknown: I assumed indoors"
(STY-07). No place set: no weather rule, the assumption shown.

**D15 · His timezone, everywhere a day is said.** "Tomorrow" is the next calendar day in his zone
(the brief store's zone for him, else `user_timezone`, `config.py:608`), read through the context
(`ctx.zone(uid)`), never UTC: R14's No-AI "Recently deleted" date is UTC and names the day before
between 00:00 and 05:30 IST (I1-NOTES follow-up); R13 does not repeat it. Tests run at 23:30 and
00:30 IST.

**D16 · Confirm before commit.** `wardrobe_merge` (INV-16) and `wardrobe_retire` (archive and restore,
INV-17) are R2 with `ask_when` always (a card, as `vitals_drill_start`), in `NO_BULK_TOOLS` (never
"Approve all"); a merge keeps one active id with both histories (the merged-away id becomes a
`merged` tombstone that points at it) and can be undone from Recently deleted for 30 days; restore
reuses the same id and lands in "Missing or in review" until he confirms the condition.
`wardrobe_remove` is R2 `undoable`: the piece goes to Recently deleted (new kind `wardrobe_item`,
in place, purge with the passkey like a thing), and its photos, fingerprints and log go only when the
bin entry is purged. Deleting everything is a Privacy row (passkey).

**D17 · Backup and restore of the wardrobe (OPS-06; Part A).** `GET /v1/wardrobe/backup` downloads one
file sealed with the `wardrobe` key (AAD `wardrobe/backup/{uid}/v1`): pieces, pairs, sets, places,
labels, states and the whole event log, plus photos and fingerprints **only when he ticks "include
photos"**. It opens only on this JARVIS (the same token key; R14's Firestore backups cover a lost
database). `POST /v1/wardrobe/restore` checks the seal and the schema first, then merges: ids kept,
events deduplicated by id and client id, the fold of D4 re-run, so a newer local verified event
stays authoritative and nothing is duplicated; it reports counts (added, already there, superseded).
A plain JSON export without photos is the Privacy panel's export.

**D18 · Permission rows, Telegram, the skill register.** Three new R2 rows after `pictures`, before
Maps and YouTube (which stay last): **`wardrobe`** ("Your wardrobe: pieces, places, labels, pairs
and sets"; `wardrobe_*`), **`laundry`** ("Laundry: the basket, loads, drying, outside laundry";
`laundry_*`), **`outfits`** ("Outfits: suggestions, plans, reservations and what you wore";
`outfit_*`, `wear_*`; the hint says the calendar read obeys the Calendar row). 49 → 52; the save cap
51 → 54. Telegram: all four families join `PERSONAL_PATTERNS` (`telegram/rules.py:66`, the switch for
the vault, notes and things, default off), and `deleted_list` hides `wardrobe_item` entries while it
is off. Skill register (`skills/catalogue.json`): group `wardrobe` (`wardrobe_*`, `laundry_*`) under
**Task & Productivity** and group `outfits` (`outfit_*`, `wear_*`) under **Decision Support**, with
words (wardrobe, shirt, trouser, jeans, kurta, vest, sock, shoe, belt, watch, laundry, wash, iron,
press, dry clean, dhobi, outfit, wear, dress code, kapde, pehen …); none is `telegram_open`; the
No-AI tools are listed under `no_ai`; I0 names all 18 under `planned`.

**D19 · Alerts: four kinds (52 → 56).** Fixed templates, never his label, never a title, never a
private piece (D10):

| Kind | Level | When (claim written before the send, `wardrobe_told`) | Text (example) |
|---|---|---|---|
| `outfit_ready` | important, daytime ring, held at night | a plan for an event on his chosen calendar is ready, at `wardrobe_plan_evening` (20:00) the evening before, once a plan | "Tomorrow's outfit for your 10:00 event is ready in Helpers, Wardrobe." |
| `outfit_changed` | important, daytime ring, held at night | a planned or reserved piece left Ready within 36 h of the event; once a plan per 2 hours | "A navy shirt in tomorrow's 10:00 outfit went to the laundry. A ready one is suggested." |
| `laundry_overdue` | important, daytime ring, held at night | an outside-laundry batch is past its due date, or came back short; once a batch a day | "2 pieces at the laundry shop are a day overdue." |
| `wardrobe_review` | info (feed only) | open review entries the morning after; once a day | "3 pieces wait for a quick check." |

Each has an Alerts-card switch (`console-alerts.js`), held words, a Web Push target (`helpers`) and
book words. They use the normal Telegram bucket (`notify/telegram_out.py`); no storm table change.

**D20 · No-AI sentences (pass 3; Part D).** `offline/phrases_r13.py`, anchored like R14's (the whole
message is the phrase), installed first (D6). Each ends in one gateway call:

| He says (examples) | Tool |
|---|---|
| "what should I wear tomorrow / today / for Diwali / for the meeting" | `outfit_suggest(day, occasion)` |
| "where is my black belt" / "where are my brown shoes" | `wardrobe_find(query)` |
| "my navy shirt is in the laundry" / "put the white shirt in the wash" | `laundry_move(step=basket, query)` |
| "the white shirt is back" / "the white shirt is clean" | `laundry_move(step=ready, query)` |
| "what's in the laundry" / "laundry status" | `laundry_status` |
| "I'm wearing the blue shirt" / "I wore the blue shirt today" | `wear_log(query)` |
| "how many shirts do I have" / "how many socks are ready" | `wardrobe_count(type)` |

A name that fits several pieces makes a review entry (and holds, for the basket), never a guess.
R14's `WITHOUT_AI` gains "your wardrobe: where a piece is, laundry, today's outfit" (I0, one line).

**D21 · Version, persona, guide.** `__version__ = "13.0.0"` at I0 (lower than 14.0.2: nothing
compares versions, as with R7's 7.0.0 after 11.1.1); the four pins move. Persona **p13.0** at I1
(`WARDROBE_RULE`): "A piece of clothing, footwear or an accessory is in the wardrobe: use
`wardrobe_find`, not Things. Never name a private piece outside the Wardrobe tab; say 'a private
basic'. An outfit comes from wardrobe rules with their reasons; say a piece is ready only when the
tool says so. Laundry is prepared, never ordered, paid or called. Archive, restore, merge and remove
are cards." Guide cards **C69** Wardrobe catalog and the ledger, **C70** Laundry, **C71** Outfits, and
the Camera → Wardrobe mode in C63; I0 lists them PLANNED with every collection; I1 fills them.

**D22 · Deferred, with reasons.**

| Item | Why not now |
|---|---|
| Fixed basket and return cameras (LND-02, LND-03, OPS-02 in their camera form) | Needs a camera at the basket and R8's camera setup; the events and holds are built |
| A brief line "Today's outfit" | The `outfit_ready` alert and the tab cover it; a brief section is a later small change |
| A dedicated dock button for the Wardrobe | `console.html` has no lines to spare; Helpers holds it (D1) |
| A launch word `?do=wardrobe` and an Android shortcut | R7's launch words and the native shortcut list are Part A of R7's files; later |
| DINOv2 fingerprints, fabric labels (RFID or washable tags) | R8 or the owner's purchase decision; QR labels and taps cover INV-07 |
| Auto-swap on by default | He decides after the pilot |
| AI stylist | R17, paid |

## Data model (prefix `jarvis_`; every collection named in the guide's cards before code uses it)

| Collection | Part | Holds | Sealed | Kept |
|---|---|---|---|---|
| `wardrobe/{uid}` | A | the index: pieces, pairs, sets, places, labels, custom types, settings (calendar choice, fields, lead, AI tagging, private display) | `wardrobe` | until deleted |
| `wardrobe_log/{uid}_{piece}_{page}` | A | that piece's events, 200 a page, append-only | `wardrobe` | until the piece is purged |
| `wardrobe_photo/{uid}_{photo}` | A | one cleaned ≤ 512-px JPEG of a non-private piece | `wardrobe_photos` | until the piece is purged or he deletes it |
| `wardrobe_fp/{uid}_{shard}` | A | fingerprints (1,280 bytes each), 200 a shard, with piece and view | `wardrobe_photos` | as its photo |
| `wardrobe_laundry/{uid}` | B | open loads (≤ 50), outside batches (≤ 20); closed ones 90 days | `wardrobe` | 90 days after closing |
| `wardrobe_review/{uid}` | B | open review entries (≤ 100): pending deposits, holds, conflicts, stale checks | `wardrobe` | until resolved, then 30 days |
| `wardrobe_plans/{uid}` | C | plans (≤ 60: from 14 days back to 30 ahead), reservations, his rule words and preferences | `wardrobe` | 90 days after the event |
| `wardrobe_cal/{uid}` | C | the last calendar read: event fingerprints, times, the dress code found (never a title) | `wardrobe` | overwritten |
| `wardrobe_told/{uid}_{key}` | C (B for `laundry_overdue`, `wardrobe_review`) | once-only claims (a hash) | no | 30 days |

Keyring purposes 22 → **24** (`wardrobe`, `wardrobe_photos`). Never stored: a calendar title,
description or attendee, a frame, a picture of a private piece, a picture with a person, the query
fingerprint of a scan, anything about another person, a phone number or address of a laundry shop.
Sizes (estimates): an event ≈ 250 bytes sealed; 150 pieces × ≈ 1.3 photos × ≈ 47 KB sealed ≈ 9 MB;
logs ≈ 4 MB a year; ≈ 15–20 MB in the first year.

## Tools (18; every call through the gateway)

| Tool | Risk | Row | Part | Card | No-AI |
|---|---|---|---|---|---|
| `wardrobe_find` | R1 | wardrobe | A | — | yes |
| `wardrobe_count` | R1 | wardrobe | A | — | yes |
| `wardrobe_add` | R2 | wardrobe | A | tainted / spoken rules | — |
| `wardrobe_edit` (type, attributes, lock, verify a care field, private, place, label, pair, set) | R2 | wardrobe | A | as above | — |
| `wardrobe_places` | R2 | wardrobe | A | as above | — |
| `wardrobe_merge` | R2 | wardrobe | A | always (`ask_when`), never Approve all | — |
| `wardrobe_retire` (archive / restore) | R2 | wardrobe | A | always, never Approve all | — |
| `wardrobe_remove` | R2, undoable | wardrobe | A | the 11th delete / tainted | — |
| `laundry_status` (the list, or one piece's history) | R1 | laundry | B | — | yes |
| `laundry_move` (basket, lifted, load, washing, drying, prep, ready + place) | R2, `spoken_ok` | laundry | B | tainted rounds | yes |
| `laundry_review` (list, resolve) | R2 | laundry | B | as above | — |
| `laundry_correct` (LND-05) | R2 | laundry | B | as above | — |
| `laundry_send_out` (send, receive per piece, due date) | R2 | laundry | B | as above | — |
| `outfit_suggest` | R1 | outfits | C | — | yes |
| `outfit_plans` | R1 | outfits | C | — | — |
| `outfit_plan` (save, lock a slot, change one, reserve, transfer, release) | R2 | outfits | C | as above | — |
| `outfit_prefs` (dress code for an event, rules, fit and colour preferences) | R2 | outfits | C | as above | — |
| `wear_log` | R2, `spoken_ok` | outfits | C | tainted rounds | yes |

Every result lists at most 20 pieces (the gateway cuts at 12,000 characters, `gateway.py:106`), fences
his words, follows D10's view, and shows fixed Activity words (`Tool.activity_words`).

## The I0 seam list (branch `r13-i0`; the integrator owns these files)

1. **Version** `13.0.0` (`__init__.py`; the four pins of fact 1).
2. **Alert kinds** +4 (D19): `alerts.py` `R13_ALERT_KINDS`, `notify/ports.py` `DEFAULT_URGENCY`,
   `notify/policy.py` `DAYTIME_RING_KINDS` (+3), `notify/held.py` (+3 held words; `wardrobe_review` is
   feed only), `console-alerts.js` `KINDS` (+4 rows), `webpush/service.py` `TARGETS` (+4 → `helpers`),
   `buildbook/plain.py` `ALERT_WORDS` (+4); the pins 52 → **56** in the six tests of fact 12, the
   exact `DAYTIME_RING_KINDS` (`test_r51_seams.py:45`) and `TARGETS` (`test_r7_a_push.py:43`).
3. **Keyring** +2 → **24** (`keyring.py`; `test_r7_seams.py:294`, `test_r11_seams.py:166`,
   `test_r14_seams.py:258` (the last purpose becomes `wardrobe_photos`) and `:259`, the set in
   `test_r3_seams.py:850`).
4. **Permissions** +3 rows → **52** (D18; the six pins of fact 8), save cap 51 → **54**
   (`permissions/models.py:133`); `tests/test_permissions_policy.py` `EXPECTED` / `RISK_OF` / `TOOL_OF`
   for the 18 tools; the nouns (wardrobe, piece, laundry, outfit, plan, label) join `TOOL_NOUNS`
   (`tests/test_r11_1_b_guard.py`).
5. **Undo**: kind `wardrobe_item` in `undo/models.py` (`Kind`, `KINDS`, `KIND_WORDS`,
   `IN_PLACE_KINDS`, `PASSKEY_PURGE_KINDS`), `console-deleted.js:25–26` ("Wardrobe piece"), the
   registration in `api/personal.py` `register_undo` through R13's wiring.
6. **Telegram**: `PERSONAL_PATTERNS` += `wardrobe_*`, `laundry_*`, `outfit_*`, `wear_*`; the refusal
   names the wardrobe; `deleted_list` hides `wardrobe_item` while the switch is off;
   `test_telegram_tool_guard.py` `linked_gateway` gains `r13=`.
7. **Guardrails**: `NO_BULK_TOOLS` += `wardrobe_merge`, `wardrobe_retire` (`core/guardrails.py:69`).
8. **Settings** (`config.py`, ≈ 14 lines, stays < 800): `wardrobe_enabled` (on),
   `wardrobe_max_pieces` 600 (50–600), `wardrobe_stale_days` 14 (3–90), `wardrobe_plan_evening`
   "20:00", `wardrobe_change_window_h` 36 (6–72), `wardrobe_calendar_refresh_min` 60 (15–360),
   `wardrobe_photo_side` 512 (256–768), `wardrobe_photo_max_kb` 200 (50–400),
   `wardrobe_photos_per_piece` 3 (1–3), `wardrobe_ai_tag_month_inr` 30 (0–200; 0 = never),
   `wardrobe_review_keep_days` 30, `wardrobe_backup_max_mb` 50 (5–200). His own choices (calendar,
   fields, AI tagging on/off, auto-swap, private display) live in his sealed index, not in settings.
9. **The contract** `wardrobe/ports.py`: `WardrobePart` (tools, clock jobs, daily jobs, privacy data,
   observers, services, ready word), `WardrobeContext` (settings, docs, keyring, audit, late
   `state(name)`, the notifier, `zone(uid)`, the governed calendar reads, the weather outlook, the
   store read port), `PARTS` (`catalog`, `laundry`, `styling`, `phone`), `TOOL_FAMILIES`
   (`wardrobe_*` A, `laundry_*` B, `outfit_*` and `wear_*` C, none for D), `ROUTE_PREFIX`
   (`/v1/wardrobe` A, `/v1/laundry` B, `/v1/outfits` C), `COLLECTIONS` (the data model), `JOB_OWNER`
   (`wardrobe_sweep` A daily, `laundry_daily` B daily, `outfit_clock` C 5-minute), `SERVICE_OWNER`
   (`store` A, `review` B, `refresh` C, `phrases` D), `KIND_OWNER`, and the Protocols
   `WardrobeStore` (`view`, `apply`, `correct`, `transact`), `ChangeObserver`, `PhotoVault`,
   `WardrobeData` (count, export, delete for the Privacy rows). Plus `wardrobe/model.py` (D2),
   `wardrobe/states.py` (D3), `wardrobe/redact.py` (D10), and the stub parts
   `wardrobe/{catalog,laundry,styling,phone}/part.py` ("not built yet").
10. **Wiring**: `api/r13_wiring.py` (`wire_r13` after R14's parts and before the gateway, the
    contract check, `r13_tools`, `r13_tick_jobs`, `r13_clock_jobs`, `r13_privacy_sources`,
    `install_r13_routes` with I0's `GET /v1/r13` (each part's ready word), `install_r13_phrases`
    (first), the observers joined to A's store, the bin's `wardrobe_item` restorer and purger);
    `api/tick_wiring.py` (+ R13's daily and clock jobs); `api/app.py` +4 lines (the import, `await
    r13.wire_r13(…)`, `r13=` to `build_gateway`, the routes) → **731 ≤ 735**; `tools/setup.py`
    (`r13=`); `api/personal.py` (the `r13_privacy_sources` slot before home's);
    `offline/mode.py` (`add_phrases(…, first=False)`); `offline/phrases_r14.py` (`WITHOUT_AI` +1).
11. **The vision contract**: `vision/results.py` adds `WARDROBE_TASKS = ("embed", "colour",
    "person", "face")` and their schemas (embed: `{v: base64 ≤ 1,708, dims: 1280, model:
    "mnv2-int8-1"}`; colour: `{name, second?, share}` from the 18 names; person / face: `{found,
    count ≤ 20, boxes}`); the `Result` model accepts both lists; **`TASKS` stays the five** (the
    kept-results enum, `vision/tools.py:34`, and the pin `test_r7_seams.py:996`): a wardrobe result is
    never a kept vision result.
12. **Console** (each file stays ≤ 800): `console-helpers.js` (+ the `wardrobe` tab and its import,
    +2 lines), `console-camera-panel.js` (a fourth sub-tab whose pane a module mounts through
    `window.JarvisCameraModes.register('wardrobe', {mount, stop})`, ≤ 15 lines), `console-r7.js`
    (+ `console-wardrobe-scan.js` and `console-wardrobe.css`), `console-r7-send.js` (+
    `wardrobe(blob, meta)` and `tag(blob)` through `prepared()`'s rules, ≤ 30 lines),
    `api/console.py` `APP_ASSETS` (+ the new files, stubs at I0); `console.html` **unchanged (782)**;
    the dock stays 22.
13. **Skill register**: the two groups, words, `no_ai`, `planned` (D18); `test_r14_skill_coverage.py`
    passes with the stubs.
14. **Guide and book**: C69–C71 PLANNED (every collection), the L5 row, edition line, change log;
    `scripts/arch_coverage.json`; build book `layers.py` (`wardrobe` → L5).
15. **Evals and fakes**: `evals/r13/run.py` (R14's shape), stubs `catalog`, `laundry`, `styling`,
    `phone`, `e2e`, `needles`, and I0's built `contract`; gated in `evals/run_all_mock.py` as `("r13
    (gated)", […, "evals/r13/run.py", "--mock"], True)` after R14's line; `tests/r13_fakes.py` (the
    pilot set as fixtures, an in-memory `WardrobeStore` for B and C before A lands, IST clocks);
    `tests/test_r13_seams.py`, `tests/test_r13_wiring.py`.
16. `docs/plans/r13-integration/BRIEF-COMMON.md` (R14's rules plus: **every test takes a clock**; a
    sentence with a day is asserted whole from that clock; no `datetime.now()` in a test) and
    `I0-NOTES.md`.

## Part split (four builders; worktrees; branches `r13-a` … `r13-d` from `r13-i0`; disjoint files)

Each part plugs in through `build(ctx: WardrobeContext) -> WardrobePart` in its `part.py`;
`api/r13_wiring.py` leaves out a part that breaks the contract. B and C build against I0's in-memory
store until A lands; I1 swaps in A's.

- **A · Catalog and the ledger** (INV-01–17, OPS-03, OPS-06). `wardrobe/catalog/{part,store,fold,
  service,search,counts,places,labels,photos,fingerprints,tagging,backup,merge,undo,data,pilot,
  tools,jobs}.py`, `api/wardrobe.py` (items, places, labels and `labels.svg`, photos, fingerprints,
  tag and its estimate, backup, restore, pilot counts; 30 changes a minute per owner),
  `tests/test_r13_a_*.py`, `tests/r13_fakes_a.py`, `evals/r13/catalog.py`, INTEGRATION-A.md.
  `security-reviewer` required (photos, the backup seal, the tag call).
- **B · Laundry** (LND-01–08, LND-10–15, OPS-02). `wardrobe/laundry/{part,flows,review,holds,loads,
  providers,blind,history,store,texts,tools,jobs}.py`, `api/laundry.py`, `tests/test_r13_b_*.py`,
  `tests/r13_fakes_b.py`, `evals/r13/laundry.py`, INTEGRATION-B.md.
- **C · Styling** (STY-01–17, LND-16, OPS-04). `wardrobe/styling/{part,rules.json,rules,engine,
  plans,reserve,refresh,calendar,outlook_use,wear,prefs,texts,tools,jobs}.py`, `api/outfits.py`,
  `helpers/house/models.py` (`next_day`), `helpers/house/weather.py` (`summarize`),
  `helpers/house/outlook.py` (new), `tests/test_r11_b_weather.py` (its summary pins, if any move),
  `tests/test_r13_c_*.py`, `tests/r13_fakes_c.py`, `evals/r13/styling.py`, INTEGRATION-C.md.
- **D · Phone and panel** (OPS-01, and the UI, privacy rows, Telegram and No-AI of all parts).
  `wardrobe/phone/{part,privacy}.py` (the Privacy rows over each part's `WardrobeData`: "Wardrobe
  pieces and places", "Laundry, outfits and wear history", "Wardrobe photos and fingerprints",
  "Only on this device: the Wardrobe mode's last choices"; section "Wardrobe"; export and passkey
  delete), `offline/phrases_r13.py`, `console-helpers-wardrobe.js`, `console-wardrobe-pieces.js`,
  `console-wardrobe-scan.js`, `console-wardrobe.css` (≤ 200), the Part B section of
  `console-vision.js` (the four tasks, before `sealRegistry()`; the I0 core's hash unchanged),
  `tests/test_r7_b_console.py` and `tests/test_r7_b_dom.py` (the nine-task pins, with a line in
  INTEGRATION-D), `static/vendor/vision/r13-1/**`, `scripts/wardrobe_assets.py`,
  `buildbook/gen/libs.py` (the licences), `tests/test_r13_d_*.py`, `tests/browser/test_r13_d_*.py`,
  `tests/fixtures/r13/**`, `evals/r13/phone.py`, INTEGRATION-D.md. `security-reviewer` required (the
  door, the scan module, the redaction views).
- **All parts**: test first; functions ≤ 50 lines, modules ≤ 400, files ≤ 800; only the planned
  collections, job names, kinds and tool names; alerts only through the notifier with fixed
  templates; never a wiring file (only I0 and I1 touch them).

## Tests and evals (mock; each control must make its suite fail)

**Every acceptance check of the 54 is a named test** (paraphrased from the workbook; the test file
is the part's):

| ID | Test (what must hold) |
|---|---|
| INV-01 | a belt put in "Drawer 2" is found there by `wardrobe_find("belt")` |
| INV-02 | scanning a shirt rack and the accessory tray gives the catalog plus a separate list of unresolved scans; places without a baseline scan are listed |
| INV-03 | a belt and a watch in one photo become two records; a piece hidden under the belt is a later scan, never a guess |
| INV-04 | two shirts, a vest, underpants, socks, shoes, a belt and a watch are each found under their category; a type change keeps the id |
| INV-05 | a new kurta gets one id; scanning it again leaves the owned count unchanged |
| INV-06 | one patterned shirt keeps its id across front, back and folded fingerprints (fixture vectors; the real model in D's Node test) |
| INV-07 | two identical black vests get two ids; only the copy whose label was read enters laundry |
| INV-08 | 20 frames of one shirt make one piece and one registration event |
| INV-09 | "blue striped shirt" finds the right piece once its colour and pattern are verified; a suggestion never overwrites a locked attribute |
| INV-10 | an unclear wash symbol stays unverified; the typed instruction is kept as verified |
| INV-11 | two shoes count as two pieces and one wearable pair only while both are ready |
| INV-12 | a kurta and its bottoms are two pieces and one set; the set is unavailable when the bottoms go to laundry, and says whether the kurta can go alone |
| INV-13 | a watch moved from the tray to the travel bag shows the bag after the move; an unobserved move shows "last known" |
| INV-14 | one missing sock leaves the owned sock count unchanged and reduces complete pairs by one; laundry stays in owned totals; scope covered is shown |
| INV-15 | "where is my black belt" returns its drawer and its state; two black belts are told apart by place or label |
| INV-16 | merging two records of one watch (a card) leaves one active id with a continuous history; confirmed separate copies stay two |
| INV-17 | an archived belt (a card) drops out of active counts; restoring it reuses the id and asks for its condition |
| LND-01 | the navy shirt stays owned but leaves ready pieces and the next suggestions when its deposit is logged |
| LND-02 | a "To laundry" scan of a clean shirt that he cancels leaves it Ready; a `camera` event without a release goes to review |
| LND-03 | a jacket hiding a shirt: one verified deposit plus a pending deposit with no piece id |
| LND-04 | when either of two near-identical shirts could be dirty, both are withheld until he says which; "no deposit" clears to the last verified state |
| LND-05 | correcting an old basket event never overwrites a later clean return |
| LND-06 | a shirt taken from the hamper to the sorting table stays unavailable |
| LND-07 | a mixed load moves its five confirmed pieces to Washing; the rest stay In laundry |
| LND-08 | three of five moved to drying change only those three |
| LND-10 | a damp shirt and one marked Needs pressing stay unavailable until their returns pass |
| LND-11 | the navy shirt returns with its original id and the same owned count, and reappears in suggestions |
| LND-12 | four of six returned restore four ids; two stay unavailable after the basket is empty |
| LND-13 | the clean left sock stays in inventory; the pair stays out until a ready matching half is recorded |
| LND-14 | two of three back from dry-cleaning: only those two can become ready; the batch is flagged short and, past its date, overdue |
| LND-15 | "where is my white shirt" shows Drying and its latest verified movement |
| LND-16 | a shirt due back tomorrow shows as an outstanding action while a ready shirt is offered for the meeting |
| OPS-02 | after a reported blind period, the pieces touched are verified before they appear in a ready plan |
| OPS-03 | an old basket event delivered after a confirmed clean return can't make the shirt dirty; a repeated event is applied once |
| OPS-06 | restoring a test backup keeps ids and pair links and duplicates nothing |
| OPS-01 | a frame with a person or a face saves nothing (no photo, fingerprint or event); a saved photo is ≤ 512 px and holds only the box |
| OPS-04 | switching the calendar off stops automatic plans from it; a laundry alert never names a private piece; only the chosen fields are requested |
| STY-01 | "what should I wear tomorrow" at 23:30 and 00:30 IST resolves to the next local day and shows the occasion |
| STY-02 | an important meeting on the chosen calendar makes a plan for the right date; a cancelled one doesn't; an edited one refreshes |
| STY-03 | changing "Catch-up" to business formal gives a business-formal outfit; the calendar is not changed |
| STY-04 | a ready light-blue shirt, charcoal trousers and matching shoes, belt and watch make the meeting look |
| STY-05 | a Diwali plan uses his festive pieces and checks every part of the set |
| STY-06 | a delicate favourite he excluded stays out of the Holi options |
| STY-07 | a rainy outdoor plan offers his ready rain-ok shoes and outer layer and says the weather assumption |
| STY-08 | "no tight collars" filters the pieces tagged tight at the neck; the constraint that leaves no match is named |
| STY-09 | the meeting look lists shoes, belt and watch, and the private basics only in his view |
| STY-10 | a dirty belt or a pair missing a shoe never appears in a recommended or ready outfit |
| STY-11 | each look explains why and shows its actual piece ids |
| STY-12 | changing the shoes keeps the shirt, trousers and watch when still eligible |
| STY-13 | a meeting and an evening function get two plans with the pieces to change and the reuse said |
| STY-14 | reserved shoes appear for their event and make a conflict for a second plan at the same time |
| STY-15 | a white shirt dropped in the basket leaves tomorrow's active outfit and a ready alternative is shown |
| STY-16 | "no ready formal shoes" is said when the only pair is out, with the eligible pieces apart |
| STY-17 | saving a plan changes no wear count until he confirms what he wore |

**The workbook's end-to-end tests** (`evals/r13/e2e.py` through the wired app on fakes, and
`tests/test_r13_i1_e2e.py`): **1** one shirt's whole life (register, suggest, deposit, clean return:
excluded, then eligible on its id; owned count constant); **2** two identical vests (one label hidden →
review; the label read → exactly that vest is dirty; the other available); **3** unobserved movement in
its phone form (a reported blind period over a planned garment → held; a rescan resolves); **4** an
incomplete pair and load (a pair into laundry; one piece back; the load marked done by his tap, the
phone form of the washer's "finished": only the dry returned piece is eligible alone, the pair stays
out, other load pieces stay unavailable); **5** a meeting outfit update (approve a formal outfit for
tomorrow; one piece into laundry; the plan is incomplete or offers a substitute; the checklist names
the same ids; the avatar half is R13.1); **7** private items and photos (a look with private layers:
alerts, Telegram, Web Push and the model's view show only approved details; deleting all wardrobe
photos leaves the catalog usable; the avatar half is R13.1); **8** pilot measurements (from the
events: item-id match rate, wrong status changes, unavailable pieces suggested, manual corrections
per use; the pilot run reports them, D's `GET /v1/wardrobe/pilot` counts).

**Browser (Playwright, Chromium's fake camera).** `--use-fake-ui-for-media-stream
--use-fake-device-for-media-stream --use-file-for-fake-video-capture=tests/fixtures/r13/<clip>.y4m`
(clips made by the test from drawn garments: a striped shirt on a plain surface, two identical
vests with one QR label, a belt and a watch apart). Flows: add a piece (chip, colour, "new"), rescan
("seen before" → same id), to laundry, back clean, a QR label read, the person / face refusal (the
test hook forces a detection; the hook can only refuse), the crop's size, the door's counter, the
Wardrobe tab's sections at 360 × 800 and 1280 × 800, screenshots compared with the R14 baseline for
the existing tabs (unchanged look). D's Node test runs the three real models on the vendored runtime
(as measured above) and the fingerprint of one drawn shirt under rotation and folding (INV-06's real
half). Whether a drawn face fires UltraFace is checked first; if none does, the face task's decoding
is tested on recorded model outputs and the real face check moves to the pilot (say so in
INTEGRATION-D).

**Needles** (`evals/r13/needles.py`, I1): one simulated week of the four parts on the fakes; needle
classes: a private piece's label and colour, his free-text labels, a calendar title, a laundry
shop's label, a planted phone number, photo bytes (raw and base64), a fingerprint, the backup file's
plaintext; each searched raw, lower-cased, URL-encoded, hex and base64 in every R13 document write
(beyond its sealed blob), every log record, the audit detail, alerts, Telegram text, Web Push
payloads, approval cards, Activity rows and every tool result for the model; a positive control per
sink. **Control**: `redact.py`'s model view swapped for the panel view → exactly the private-label
cases in tool results fail.

| Suite | Cases (examples) | Control that must fail it |
|---|---|---|
| `contract` (I0, built) | every part builds through the real wiring and owns only its tools, jobs, services | the contract check off: a stray tool is accepted |
| `catalog` (A) | INV-01–17, OPS-03, OPS-06 | the dedup off: INV-05, INV-08 and OPS-03 fail |
| `laundry` (B) | LND-01–15, OPS-02 | holds off: LND-03, LND-04 and OPS-02 fail |
| `styling` (C) | STY-01–17, LND-16, OPS-04 | the availability check off: STY-10, STY-15, STY-16 fail |
| `phone` (D) | D20's sentences with zero provider calls; D10's views; OPS-01 refusals | the person check off: OPS-01 fails |
| `e2e` (I1) | the seven workbook tests | the fold in arrival order: tests 1 and 3 fail |
| `needles` (I1) | above | above |

## Size guards

`api/app.py` ≤ 735 (727 + 4 = 731), `tools/gateway.py` 760 unchanged (no edit), `core/brain.py`
≤ 741 (713, no edit), `console.html` ≤ 782 (782, no edit), every `console*.js` ≤ 800 (the biggest edits:
`console-camera-panel.js` 468 → ≤ 483, `console-alerts.js` 462 → 466, `console-helpers.js` 236 → 238,
`console-r7-send.js` 100 → ≤ 130; the new wardrobe files ≤ 600 each), new CSS ≤ 300 in all
(`console-wardrobe.css` ≤ 200), `config.py` < 800 (≈ 743), every new Python module ≤ 400. I0's
`test_r13_seams.py` pins each.

## Risks and known limits

- **"Seen before?" on near-identical pieces**: ImageNet features tell colours and patterns apart, not
  two copies of one vest. Mitigation: candidates only, his tap decides, QR labels for copies, both
  held when unsure. The pilot measures the match rate (exit check).
- **The person check is a detector, not a guarantee**: SSD misses some partial bodies and UltraFace
  some angled faces; a printed face on a T-shirt is refused (he saves it without a photo). Either
  detection refuses the whole frame; photos are cropped, sealed and his alone.
- **Phone speed and memory**: three ONNX sessions, tesseract and zxing on one page; sessions load on
  first use and are released on `pagehide` (R7's rule); measured 70–113 ms here, likely 0.2–0.7 s on a
  phone (estimate).
- **A quantized operator on his phone's browser** may differ from Node's: the fp32 fallback (D8).
- **Device clocks**: `at` from the phone is clamped to ± 5 minutes of the server; a phone hours off
  would reorder events, so the clamp is tested.
- **The index's size**: 600 pieces is the ceiling for one sealed document; past it a later release
  shards by category (refused in plain words until then).
- **Calendar titles are other people's words** (an invite): read in memory for keywords only, never
  stored, sent or logged; shown fenced in his panel.
- **Alert noise**: four kinds, once-only claims, a 2-hour gap for changes, the Alerts card's switches.
- **Repository size**: ≈ 13.2 MB of model files (R7 added ≈ 23 MB).
- **Training data terms** (ImageNet, WIDER FACE, COCO) bind the data, not the zoo's licensed weights;
  personal, non-commercial use (D8).
- **Pins churn**: 6 alert, 4 keyring, 6 permission and 4 version pins move at I0; every other part
  edits none.
- **2 CPUs here**: targeted tests only while building; the whole suites queue (the side-by-side
  Build Book work shares the machine).
- **Date bombs**: every test takes a clock (BRIEF-COMMON); the clock sweep before the PR.

## Needs the owner (safe defaults; none blocks the build)

1. **Where the Wardrobe lives**: Helpers → Wardrobe and Camera → Wardrobe (default); a dock button of
   its own would cost console lines (later).
2. **Private by default**: underpants, briefs, boxers, vests, undershirts, thermals (default); socks
   not private. Change any piece in its settings.
3. **Outfits from a calendar**: none until you pick one; then title on, location off, description
   and guests never (default).
4. **The evening reminder**: 20:00 the evening before an event on that calendar (default), or off.
5. **Auto-swap** when a planned piece goes to the laundry: off; JARVIS suggests and you tap (default).
6. **Rewear**: trousers, jeans, outerwear, belts, shoes and the watch are worn again; shirts,
   T-shirts, vests, underwear and socks go to the laundry after a wear (default).
7. **Holi**: only pieces you mark "okay to stain" (default).
8. **Photos**: one front photo a piece (back and detail optional), 512 px, kept until the piece is
   removed (default); never for private pieces.
9. **QR labels**: print a sheet of 24 (default); washable fabric labels are a purchase for later.
10. **AI tagging**: off (default); when on, at most ₹30 a month.
11. **"Needs a quick check"** after 14 days without a scan of a planned piece (default).
12. **The wardrobe backup file**: sealed to this JARVIS, photos left out unless you tick them
    (default).
13. **The tracker**: the 80 use cases as their own rows, replacing rows 169–174 (the proposal's
    default), or "keep the 6 rows".
14. **The pilot**: 20–30 pieces including a watch, a belt, shoes, two near-identical vests and a few
    socks; print one label sheet first.

## Exit check (before the PR)

1. **The pilot** on his phone: 20–30 pieces as above; the pilot counts (e2e 8) are written into
   INTEGRATION notes with the bands D7 ends up using.
2. **The workbook's end-to-end tests** 1–5, 7 and 8 pass (`evals/r13/e2e.py`; the gated runner, every
   built part's control failing it).
3. **The full browser suite** once, on the joined branch (≈ 75 minutes; queued, never beside another
   whole suite).
4. **Screenshots looked at**: the Wardrobe tab and the Camera → Wardrobe mode at phone and laptop
   sizes, and the unchanged existing tabs against R14's.
5. **The clock sweep**: the whole unit suite once with the clock moved forward (`time-machine` in a
   ten-line plugin outside the repo) to 16 Nov 2026 09:00 IST, and the R13 files also at 20 Dec 2026,
   1 Mar 2027 and 29 Feb 2028; no date bomb.
6. `ruff check`, `ruff format --check`, `mypy src` (the baseline only), `evals/run_all_mock.py` ALL
   PASS, `scripts/check_doc_versions.py`, `scripts/arch_coverage.py`, the coverage floor (95),
   `python -m jarvis.buildbook.gen --check`, the PR title check.

## What can't be verified from this workspace

The models on his phone's browser (speed, memory, a quantized operator); UltraFace on a real face
and SSD on a real partial body (the pilot); his Google calendars and Google's `fields` behaviour on
`events.list` (read from Google's documentation, not called here); Open-Meteo's tomorrow values for
his place; the real match rates; Firestore's real sizes; Telegram and Web Push delivery.

## Sources (read 15 Nov 2026)

| # | Source |
|---|---|
| S1 | The owner's wardrobe workbook: sheets "Use Cases" (80), "Wardrobe Rules" (checkpoints, item status, categories and counting), "Build and Test" (build order, end-to-end tests 1–8) |
| S2 | The approved proposal "What goes in this build: wardrobe (R13) and the Build Book rebuild" v1.1 (15 Nov 2026), section 2 |
| S3 | ONNX Model Zoo, commit `c5cae0f1942c8d7727372c7b1f6b485aa39e4421`: MobileNet, UltraFace and SSD-MobileNetV1 model pages and their Git LFS pointers — https://github.com/onnx/models |
| S4 | onnxruntime-web 1.30.0 as vendored (`static/vendor/ort/MANIFEST.txt`) |
| S5 | Open-Meteo forecast API terms as recorded in R11 (`docs/plans/r11-free-helpers.md`, "External sources") |
| S6 | Google Calendar API v3 `calendarList.list` and `events.list` with the `fields` parameter — https://developers.google.com/workspace/calendar/api/v3/reference |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 16:42 IST | R13 | First edition, from the code at `9a8392b`: the owner's summary with ₹, the 54 use cases mapped to four parts and all 80 IDs placed (R13, R13.1, Later, Declined), 22 code facts with file:line, the three model files downloaded, hash-checked and run on the vendored runtime, D0–D22 (Helpers and Camera tabs with `console.html` untouched, one id a piece, the 10 states as data, the ordered ledger, phone-form checkpoints, Things' text tools reused but not its store, free recognition, pinned models, the photo rules, count-only private pieces, laundry that never orders or pays, rule-based styling, the chosen calendar and fields, tomorrow's weather, his timezone, cards and the bin, the sealed backup, rows and the register, four alert kinds, No-AI pass 3, version and persona), the data model, 18 tools, the I0 seam list, the part split with OPS-03 to A and LND-16 to C, a test per acceptance check, the end-to-end, browser and needles suites with controls, size guards, risks, owner questions, the exit check | 🛠 Mark XXI |
