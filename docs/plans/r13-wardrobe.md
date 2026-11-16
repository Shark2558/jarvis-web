Version v13.0.3 · 16 Nov 2026, 23:30 IST · Release R13 · Status: Ready · Owner: 🛠 Mark XXI

# Release R13 — Wardrobe & laundry, phone first (`v13.0.0`)

**Phase:** 5 groundwork (camera checkpoints, built in their phone form) on Phase 2 tools and Phase 3
memory, with Phase 7 evals. **Type:** free: ₹0 a month fixed, no new paid service, no new secret, no
new Cloud Scheduler job; the optional AI tagging is off by default and shows its ₹ first. **Scope
(approved by the owner, 15 Nov 2026, ≈ 16:35 IST):** the 54 Catalog and Styling use cases of his
wardrobe workbook; Try-on (15) is R13.1 `v13.1.0`; Extras (11) later. **Branches:** I0 `r13-i0`
(from `main` @ `9a8392b`, R14 live as `v14.0.2`) → parts `r13-a` … `r13-d` → integration `r13-i1` →
PR `v13.0.0 · R13 Wardrobe & laundry, phone first · Mark XXI`, rebased on `main` after R6.2's PR
(`v6.2.0`) merges first. Every commit carries `JARVIS-Version: v13.0.0` and `JARVIS-Mark: XXI`.
Read on `9a8392b`; every file:line below is from that commit. v13.0.2 writes in plan review 1
(`docs/plans/r13-integration/PLAN-REVIEW-1.md`: H1–H6, M1–M15, L1–L10; the table "Plan review 1 —
how each finding was handled" near the end) and is Ready for I0.

## Summary for the owner (plain words)

1. **Every piece you own gets its own number**: each shirt, each sock and each shoe. A pair of
   socks or shoes is two pieces plus one pair; a kurta set is its pieces plus one set. A piece is
   always in one of your workbook's 10 states (Ready, In use, In laundry, Washing, Drying, Needs
   prep, With laundry provider, Needs repair, Missing or in review, Archived).
2. **Your phone is the camera.** In the JARVIS app, Camera gets a fourth tab, **Wardrobe**: "Add
   pieces", "To laundry", "Back clean", "Find" and "Read a label". Or you just tap ("to laundry",
   "back clean", "wearing it", "done for today") in Helpers → **Wardrobe**, or say it. A fixed
   basket camera can be added later without changing anything: every event already says where it
   came from (phone, tap, later camera).
3. **Recognition is free.** You tap the kind (shirt, vest, sock, shoe, belt, watch, kurta …) and
   JARVIS suggests the colour. "Have I seen this before?" is answered **on the phone** by a small
   picture model (about 2.4 MB, Apache licence) that never sends the picture anywhere to compare;
   it offers candidates and you tap the right one. For identical copies (two black vests) JARVIS
   prints a sheet of small numbered QR labels; the phone already reads QR codes. Size and care
   labels are read on the phone; a wash symbol stays "unverified" until you confirm it.
4. **Laundry, start to finish**: the basket, a wash load, drying, pressing, a dry-cleaner or
   laundry shop (with a due date and a "short delivery" flag), pieces coming back in parts, a
   sock whose partner is missing. JARVIS prepares and reminds; it **never orders, pays, calls or
   sends a WhatsApp message**.
5. **What to wear**, by fixed rules that explain themselves (the AI stylist stays in R17, paid):
   "what should I wear tomorrow" uses your own timezone, the one calendar you pick (only the
   fields you pick), the weather for your home area (Open-Meteo, as R11 uses it), and rules for a
   formal meeting, Diwali, Holi ("okay to stain" pieces only) and a rainy day. If a planned piece
   goes into the basket the night before, the plan is fixed at once and you are told. Wearing the
   planned outfit is never treated as a problem.
6. **Private stays private.** Underwear, vests and anything you mark private need no photo and
   never get one; they appear only in your own Wardrobe checklist, never by name in an alert, on
   Telegram, on the lock screen or in what the AI is shown. JARVIS checks each photo on the phone
   for a person or a face and refuses it if it finds one; the check can miss a hand or a turned
   face, so look before you save, and delete a photo from Privacy if one slips through. A saved
   photo is cropped to the piece, locked with JARVIS's keyring and listed in the Privacy panel with
   export and delete. JARVIS keeps nothing about anyone else on purpose: no names, no faces.
7. **Archive, restore, merge and remove always ask you first** (a card); a removed piece waits 30
   days in Recently deleted. You can download a sealed wardrobe backup (up to 25 MB) and restore
   it: JARVIS first shows what it would add, and restoring twice adds nothing twice.
8. **Cost: ₹0 a month.** About 15–20 MB of photos and history for 150 pieces, inside Firestore's
   free 1 GiB; with R14's backups switched on about ₹0.6–0.8 a month more. Optional AI tagging, off
   by default, only for a saved piece that is not private: about ₹0.01 a photo on the fast model,
   about ₹0.3 at most, capped at ₹30 a month. The first time you save a photo the phone downloads
   about 13 MB of model files (about 27 MB if the "Hey Jarvis" runtime is not on it yet).
9. **The same look**: Helpers and Camera each gain one tab, built only from the components already
   there. No new dock button.

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
| The ordered event ledger, the 10 states and the wear lifecycle | L7 Data, L3 Context · Task & Productivity | 3 | Build now |
| Laundry lifecycle, outside laundry, review queue and holds | L5 Skills · Task & Productivity | 2/4 | Build now (phone and tap; camera later) |
| Rule-based outfits, plans, reservations, refresh on change | L5 Skills, L3 · Decision Support | 4 | Build now |
| Selected calendar, selected fields | L6 Integration (governed read) · Decision Support | 2/4 | Build now; off until he picks a calendar |
| Phone Wardrobe mode: fingerprint, colour, person and face checks, QR, labels | L1 device, L2 Input Processing (the R7 vision engine; a second pixel panel) · Task & Productivity | 5 groundwork, 6 | Build now |
| Optional AI tagging | L4 (R11.1's `BrainEyes`, fast tier) · Task & Productivity | 7 cost | Build now; off by default |
| Fixed basket and return cameras | L2 Input, L6 home bridge | 5 | Not built: the event model takes them later (D5) |
| AI stylist | L4 · Creative | 4 | Not built (R17, paid) |

No change to the reference architecture: the wardrobe is a Layer 5 skill on the R7 vision engine (L2)
and the R14 skill register. One R7 rule is widened in the open (D9): two named panels may see pixels,
Camera and Camera → Wardrobe; use cases still never do.

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
   (`BelongingsStore.change`, `:143`); its JSON keeps Unicode (`ensure_ascii=False`, `:85–91`).
   `belongings/text.py` `thing_key`, `recall/retrieval.py` `bm25` and `recall/sensitive.py`
   `sensitive_reason` do the matching and the "IDs go in the Vault" refusal. No ID for a place, no
   state, no event. Its bin entries carry a fixed title because "the bin shows no name: it is
   Firestore, in clear" (`belongings/service.py:69`).
3. **The vision engine (R7).** `console-vision.js` is the one port: tasks see pixels, use cases
   never do (`:1–15`); `register()` is sealed after the built-in tasks (`:8`, `sealRegistry()` at
   `:349`). A Result's data is copied by `plain()` (`:27–35`): **arrays are cut at 100 items and
   strings at 2,000 characters**. The I0 core (before `// ==== R7 Part B`) is pinned by SHA-256
   (`tests/test_r7_b_console.py:38`). Tasks: `text` (tesseract.js 7.0.0), `code` (zxing-wasm 3.1.6),
   `quality`, and `objects` / `pose` (MediaPipe; their models never arrived, "not installed":
   `vision/assets.py:1–8`). Files come from `/static/vendor/vision/<release>/` (`BASE`, `:137`,
   release `r7-1`; `vision/assets.py:16–38` knows that one release and the five tasks' files),
   served by `api/console.py:325–413` (`console_vision`, `:403`) only when MANIFEST.json lists them
   with a matching SHA-256; any release folder and `application/octet-stream` are accepted. The
   server's contract is `vision/results.py:22–23` (`TaskName`, `TASKS`, the five; pinned
   `test_r7_seams.py:996`, `test_r7_b_console.py:209`, `:259`, `test_r7_b_dom.py:161`);
   `vision/tools.py:34` uses `TASKS` as the kept-results enum.
4. **The guard is opt-in.** `tests/r7_fakes_b.py:116–123` `use_case_modules()` finds a use case
   only by a `JarvisVision.use(` call; only `console-camera-panel.js` carries the panel rules
   (`test_the_panel_sends_a_picture_only_through_the_one_door`). The guide's C63 says "a frame is
   never stored and never leaves the device" and "the use cases of R8 to R10 receive results only"
   (`docs/architecture/JARVIS-Architecture.md:364`); the camera's privacy row says "Never kept: a
   camera frame or a picture" (`vision/privacy.py:23–26`).
5. **The camera and the picture door.** `console-camera.js` is the only file that asks for a
   camera; `console-camera-panel.js:20` has three sub-tabs (Look, Results, Cameras) and redraws a
   photo before anything uses it. A picture leaves the device only through I0's door
   `console-r7-send.js` (`ask`, `attach`, `vault`, `:100`), which redraws it with R11.1's `shrink` and
   counts "Pictures sent from this device today".
6. **onnxruntime-web 1.30.0** (MIT) is vendored for the wake word: the single-threaded WASM build
   only (`static/vendor/ort/MANIFEST.txt`), at `/static/vendor/ort-1.30.0/` (`api/console.py:195`).
   The wake word imports it (`console-wakeword.js:27`, `:183`) and sets `env.wasm` (one thread, no
   proxy), which is one object per page.
7. **The keyring.** 22 cipher purposes, the last `backup_probe` (`keyring.py:42–78`), plus
   `webpush_vapid` (`:79`). Pinned: `test_r7_seams.py:294`, `test_r11_seams.py:166`,
   `test_r14_seams.py:258` (the last is `backup_probe`) and `:259`, the whole set in
   `test_r3_seams.py:850`. A key change is `KEY_ID` (`keyring.py:40`).
8. **Privacy panel.** `privacy/ports.py` `PrivacySource`; `privacy/sources.py` `CallbackSource`; the
   list is `api/personal.py:239–289` (`r14_privacy_sources` at `:287`, home's last). Sections come
   from the server (`console-privacy.js:90–94`); the export is scrubbed (`privacy/export.py`).
9. **Permissions.** 49 rows (`permissions/groups.py`), R11.1's `pictures` (`:567–575`) before Maps
   and YouTube, which stay last (`:576–592`). Pinned 49 in `test_r1_seams.py:231`,
   `test_r2_seams.py:576`, `test_r3_seams.py:913`, `test_r11_1_seams.py:139`, `test_r7_seams.py:259`,
   `test_r14_seams.py:264`. The save cap is 51 (`permissions/models.py:133`, itself pinned by
   `test_r3_seams.py:951–953`: 51 pass, 52 fail). The console draws the rows the server sends.
10. **The gateway** (`tools/gateway.py`, read in full): ASK for `Tool.ask_when` (`:239–240`), a
    spoken turn and a tainted round (`:243–247`; `spoken_ok` relaxes only a spoken, untainted turn),
    the 11th undo-able delete is a card (`:446–447`), a card runs only as the owner saw it
    (`:589–630`), arguments reach the audit as a hash only (`tools/audit.py:82`), results are cut at
    12,000 characters (`:106`). No change for R13. "Approve all" skips `NO_BULK_TOOLS`
    (`core/guardrails.py:69`, `:119`). `Tool.summarize` is pure; `Tool.preview` is an async read-only
    look-up whose text becomes the card (`tools/base.py:58–66`). A pending card is stored as clear
    JSON (`storage/approvals.py:50`) and Telegram prints its summary (`telegram/service.py:474–477`).
    A console route reaches a tool through `gateway.execute` (`api/helpers_today.py:233`) and logs
    its own changes with `record_change` (`api/settings_audit.py:24`, used by `api/belongings.py`).
11. **Recently deleted.** `undo/models.py:30` `Kind = event | task | vault_item | note | thing`;
    in-place kinds and passkey purges (`:39`, `:42`); `deleted_list` hides in-place kinds on
    Telegram while the personal switch is off (`undo/tools.py:99–115`); `api/personal.py:111–124`
    `register_undo`; the console's kind words `console-deleted.js:25–26`.
12. **Telegram.** `telegram/rules.py:66` `PERSONAL_PATTERNS = vault_*, kb_*, belongings_*` (reads
    and writes) behind its own switch, default off; `PRIVATE_PATTERNS` (`:41–63`), `HOME_PATTERNS`;
    `tests/test_telegram_tool_guard.py` makes every read tool pick a side.
13. **Alerts.** 52 kinds (`alerts.py:22–96`), pinned in `test_r3_seams.py:166`, `test_r6_seams.py:142`,
    `test_r11_seams.py:67`, `test_r11_1_seams.py:119`, `test_r7_seams.py:232`, `test_r14_seams.py:198`;
    daytime rings `notify/policy.py:27` (exact set `test_r51_seams.py:45`); held words
    `notify/held.py:14`; Web Push targets `webpush/service.py:77` (every kind but `test`,
    `test_r7_a_push.py:43`; the helpers' kinds open `helpers`, `:100`); book words
    `buildbook/plain.py:155`; the Alerts card's list `console-alerts.js:20`.
14. **No-AI.** Phrase routers are tried in the order they were added: `offline/mode.py:70–73`
    `add_phrases` only appends (at most 64, `:40`). R14's `things` router (`offline/phrases_r14.py:201`,
    `:205`, `:218`) takes "where is my black belt" and "I put my watch in the travel bag" today.
15. **Calendar reads.** `helpers/nudges/calendar.py` reads the PRIMARY calendar only (`EVENTS_URL`,
    `:37`), through the governed path `tools/background.py` (the gateway's policy and the owner's row
    for `calendar_list_events`, "Allow" only, one kind-only audit line); "an event's title is used
    only to match his own words in code; it is never put in a message, a log or a stored document"
    (`:6–9`). `calendar.readonly` is already required (`integrations/google.py:36–41`). With
    `singleEvents=true` and the default `showDeleted=false`, Google does not return cancelled events.
16. **Weather.** R11's `helpers/house/weather.py` asks Open-Meteo for 2 days (`request_params`,
    `:111–120`), parses them (`parse_forecast`), but `summarize` keeps **today only** (`:202–218`), and
    the stored models are `extra="forbid"` (`helpers/house/models.py:104–105`, `:233–237`): a new
    field in R11's document would make it unreadable after a rollback.
17. **The seeing brain.** `picture/eyes.py` `BrainEyes.look(uid, system, ask, picture, *,
    max_tokens)` (`:158–159`): fast tier, no tools, the caller's instructions, No-AI refuses, only a
    brain that sees and never trains, `Billing.ensure_allowed` first, one recorded cost, its own
    timeout. Prices `llm/pricing.py:29–31`.
18. **Pictures on the server** are cleaned by structure, never decoded: `photos/imaging.py:67`
    `sanitise_jpeg`; the frame's size is read from its SOF marker (`:59–64`). segno 1.6.6 makes QR
    codes on the server already (`helpers/today/qr.py`).
19. **Request bodies.** Every body is capped at 2,100,000 bytes before routing (`api/body.py:25`);
    a path gets more only through `routes=` in `app.py:518–529` (R7 adds `**r7.BODY_CAPS`); routes
    read big bodies with `read_capped` (`api/body.py:47`). Cloud Run: 32 MiB per HTTP/1 request; the
    service has `--memory 512Mi --cpu 1` (`deploy/cloudrun.sh:543`); a Firestore request is at most
    10 MiB.
20. **Wiring.** R14's pattern: `api/r14_wiring.py` builds parts through a contract
    (`hardening/ports.py`) and leaves out a part that breaks it ("setup failed"); `api/tick_wiring.py`
    holds the morning-tick list and the one 5-minute clock (run for the brief's owners, Home on or
    off); `app.py:377` passes `r14=` to `build_gateway`, `:496` awaits `wire_r14`, `:687` installs its
    routes. `home/watchdog.py:82` `ADVISORY_JOBS` never 503 the watchdog.
21. **Helpers frame.** `console-helpers.js:15` five sub-tabs (Today, Home, Nudges, Kitchen, Watch),
    loaded by `import()` (`:106–110`), one set of builders; `.hp-tabs` is a 4-column grid
    (`console-helpers.css:6`). `helpers/kinds.py` `TABS` (pinned `test_r7_seams.py:712`,
    `test_r11_seams.py:264`) feeds `api/helpers.py:125` for the R11 parts only.
22. **R14's drill** counts every root collection and compares samples on a document's own
    `updated_at` / `updated` / `at` / `ts` (`backup/walk_checks.py:47`); sub-collections must be listed
    (`:31`). A flat document id (`{uid}_{x}`) needs no change there.
23. **Evals.** `evals/run_all_mock.py` lists gated suites; R14's runner (`evals/r14/run.py`) fails a
    stub since R14's review follow-ups (`:28–33`).
24. **The R14 hotfix-2 lesson** (`docs/plans/r14-integration/I1-NOTES.md`, section 14): a test that
    reads today's date is a date bomb; a whole-suite run with the clock moved forward found two more.
    The R11 helpers' context takes a clock (`helpers/ports.py:129`).

## The model files (verified 15 Nov 2026 in this workspace and again by plan review 1)

Hugging Face and Google's storage host refuse this workspace; GitHub answers. All files are in the
ONNX Model Zoo (`github.com/onnx/models`, repository licence Apache-2.0) at commit
`c5cae0f1942c8d7727372c7b1f6b485aa39e4421`; each SHA-256 matches the Git LFS pointer there, and each
ran on the **vendored** onnxruntime-web 1.30.0 WASM build, one thread (Node 22, this workspace's CPU:
the review re-ran them at 78, 82 and 130 ms; a phone is likely 3–6× slower, an estimate the pilot
measures).

| Task | Upstream file (under `validated/vision/`) | Licence | Upstream SHA-256 · bytes | Served file | Measured |
|---|---|---|---|---|---|
| `embed` | `classification/mobilenet/model/mobilenetv2-12-int8.onnx` (MobileNet v2-1.0 int8) | Apache-2.0 (the model page: `SPDX-License-Identifier: Apache-2.0`, "License: Apache 2.0") | `cc028fe6cae7bc11a4ff53cfc9b79c920e8be65ce33a904ec3e2a8f66d77f95f` · 3,655,033 | `mobilenetv2-int8-embed.onnx`: the nodes feeding `472_quantized` (after the global average pool and its `Reshape`; uint8 × 1,280, zero point 0, scale 0.019110053777694702), the classifier removed, weights byte-identical: `c32ba47ca0cadf3845f771da1e429aa992e7b92d598b1e1a68054ed6b54e4ab0` · 2,368,080 | 70–78 ms |
| `embed` (fallback) | `classification/mobilenet/model/mobilenetv2-12.onnx` (fp32) | Apache-2.0 | `c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5` · 13,964,571 | `mobilenetv2-fp32-embed.onnx`: the nodes feeding `472` (float × 1,280): `d0049881dc99da166c7519a596df35ca0d25bff5c223fe0c72cd76deb150c793` · 8,840,380; quantized on the phone with the int8 file's scale (D8) | not vendored unless needed |
| `face` | `body_analysis/ultraface/models/version-RFB-320.onnx` (UltraFace) | MIT (the model page; upstream Linzaer/Ultra-Light-Fast-Generic-Face-Detector-1MB `LICENSE`, MIT, at `dffdddda9794a50607cba8f318507a28c1c27cab`) | `34cd7e60aeff28744c657de7a3dc64e872d506741de66987f3426f2b79f88017` · 1,270,727 | as upstream | 82 ms |
| `person` | `object_detection_segmentation/ssd-mobilenetv1/model/ssd_mobilenet_v1_12-int8.onnx` (SSD-MobileNetV1, COCO's classes, "person" is 1) | MIT (ONNX Model Zoo, the model page); weights from the TensorFlow Object Detection API, Apache-2.0 (`tensorflow/models` `LICENSE`, `/research`, at `19f287775ae950e22a9b5fb82727e72cff2e3664`) | `2b79e6a7fb1ec6a33f332b9b10d82d9de4b7b49dcd26b5946921bb356895c954` · 9,540,809 | as upstream | 113–130 ms |
| `colour` | none: plain arithmetic | JARVIS's own | — | — | — |

The cut is made exactly as this plan's probe did, because `onnx.utils.extract_model(…, ["472_quantized"])`
refuses here ("not found in value_infos": the quantized graph has no shape information for it): keep
every node that feeds the output, prune unused initializers, inputs and value_info, set the output's
type, save with onnx 1.23.2. The cut files are committed. Self-check references (Node, the vendored
runtime, a fixed ramp input `((i % 251) / 250) * 2 - 1` over `1 × 3 × 224 × 224`): the int8 cut's
output digest `e5b53d7e5bf35dda17217bb1feed42f900451b5fe1f2db3eca1f50442bf15abd`, the fp32 cut quantized
with the scale above `5785a2efe90c29332a4a68f1c571f75024366ba38b359444f417b82c24f31306`; D records the
face and person references (a fixed input's top scores, with a tolerance) the same way.

Considered and not chosen: DINOv2-small (Apache-2.0, better at "same piece?", ≈ 22 MB int8, ≈ 60× the
compute, on Hugging Face: an R8 candidate); CLIP ViT-B/32 (MIT, ≈ 88 MB quantized); MediaPipe's
image embedder (a `.tflite` on Google's storage host, unreachable, not on ONNX Runtime).

## Decisions (binding)

**D0 · Scope, parts and order.** R13 builds the 54 use cases in four parts after I0: **A · Catalog
and the ledger**, **B · Laundry**, **C · Styling**, **D · Phone and panel**. Two moves from the brief's
split, because the code argues for them: **OPS-03 goes to A** (the order rule is the store's own fold:
the belongings pattern writes the state and its history in ONE transaction, `belongings/store.py:143`,
and OPS-03 says "persist status and event details together"), and **LND-16 goes to C** (a Styling use
case in the workbook that reads plans, which C owns; each piece's `expected_back` is in A's view,
D4). Everything is plain code; the only model call is the optional AI tagging (D7). No new Scheduler
job: R13's jobs ride the morning tick and the 5-minute clock. Nothing spends money unless he switches
AI tagging on and presses the button that shows its ₹.

**D1 · Where it lives in the console: inside Helpers and Camera; `console.html` untouched.** A new
dock panel would need a `<section>` and a dock button in `console.html` (at its 782-line guard) and a
23rd dock button (three pins and the dock-fit browser test). Instead:
- **Helpers → Wardrobe** (a sixth sub-tab, as R7 added Watch: `console-helpers.js:15`, `:106–110`):
  sections "Needs a check" (the review queue), "Today and tomorrow" (plans, their reasons, "wearing
  it" and "done for today"), "Laundry" (basket, loads, drying, prep, outside), "Pieces" (search, counts
  by category, pairs and sets, places, private basics behind a tap), "Labels" (the QR sheet),
  "Settings" (calendar and fields, alert lead, private display, AI tagging, backup and restore).
  Built only with the frame's builders (`row`, `toggle`, `section`, `note`) and existing classes.
  The tab is console-only: `helpers/kinds.py` `TABS` stays the five R11/R7 tabs (fact 21; its two
  pins unchanged).
- **Camera → Wardrobe** (a fourth sub-tab in `console-camera-panel.js:20`): the phone checkpoints
  (D5).
- **Zero lines of `console.html` are needed**, so none are freed; the dock stays 22. I0's seam test
  pins `console.html` byte-identical to `9a8392b` for R13.
- **Where an alert lands**: a Web Push tap opens Helpers on its last sub-tab
  (`jarvis_helpers_tab`); the alert's text says "in Helpers, Wardrobe" (a tab hint in the push link
  would touch R7's launch-word module; not taken, L3).
- **The look does not change**: new CSS (`console-wardrobe.css`, ≤ 200 lines) only places things; a
  static test refuses a colour literal or a font that is not a `var(--…)`; `ui_checks.py` audits the
  new tabs (touch targets, overflow); the existing tabs' screenshots are compared with R14's.
- **Buttons that change things** (archive, restore, merge, remove, and every write the panel offers)
  call the same tools through `gateway.execute` from their route (fact 10, as `api/helpers_today.py:233`),
  so they get the same cards, rows and audit; plain settings changes write `record_change`.

**D2 · One ID per physical piece; the store.** Records (frozen, JSON in and out, I0's
`wardrobe/model.py`; stored with short keys):

| Record | Id | Holds |
|---|---|---|
| Piece | `wi_` + 12 hex | category, type (the workbook's 8 categories and their types; `unknown`; custom types he adds), label ≤ 60 (his words), colour and pattern (fixed lists) with a `locked` set, features (sleeve, collar, strap colour …, fixed lists), size, brand, fabric, care (each `verified` or not; parsed forms only, D7), formality 1–5, occasion and weather tags, `mess_ok`, `delicate`, `private`, place id and when confirmed, state and `back_to`, hold, `expected_back` (from the latest `sent_out` or load), the wear in progress (plan or event), wears and last worn, label code, photo ids, fingerprint model |
| Pair | `wp_` + 8 hex | two piece ids (left/right or a sock pair), `paired_on`; wearable only while both pieces are eligible |
| Set | `ws_` + 8 hex | 2–6 piece ids, "parts can be worn alone" (yes/no per part) |
| Place | `wl_` + 8 hex | label ≤ 40 (Drawer 2, Shoe rack, Accessory tray, Travel bag), kind `storage` / `intake` / `basket` / `return` / `travel` / `out`, `baseline_at` (INV-02 coverage), `camera: null` (later) |
| Label | number + 8 characters of lower-case base32 (`a–z`, `2–7`) | the QR's payload `jw1:<code>` and the piece it is stuck on (or none) |
| Photo | `wh_` + 12 hex | one view (front, back, detail) of a non-private piece (D9) |
| Event | `we_` + 20 hex, plus the client's own id | D4 |

Storage (prefix `jarvis_`; no sub-collections, every document carries `updated_at`, so R14's drill
counts and samples them unchanged, fact 22): the **index** `wardrobe/{uid}` (pieces, pairs, sets,
places, labels, his custom types, settings, the month's tagging ₹) is one sealed document like
Things'. **Its size is guarded in bytes, not only in pieces**: a change that would make the sealed
index larger than 900 KB is refused in plain words ("Your wardrobe list is full: archive or remove a
few pieces first"), whatever the count; `wardrobe_max_pieces` is **400** by default (50–500; maximal pieces with full histories fit only to 500, so the settings stop there), and A's
test writes 600 maximal pieces (60-character Malayalam labels, every field) to show where the guard
bites (the review's estimate: ≈ 1.14 MiB with long keys; short keys are required). Each piece's
**event log** is `wardrobe_log/{uid}_{piece}_{page}`, pages of 200 sealed events, append-only. Not
reusing Things: D6.

**D3 · The 10 states and the wear lifecycle, as data.** I0's `wardrobe/states.py` is the workbook's
"Item status and availability" table: the 10 states, eligibility, and the transitions each event
kind may make:

| Event kind | From → to |
|---|---|
| `registered`, `seen` | — → Ready (or the state he says); `seen` confirms place and time |
| `wear_started` ("I'm wearing …", linked to a plan or event when there is one) | Ready → In use |
| `wear_done` ("I wore …", "done for today", or A's `wardrobe_sweep` from 04:00 local for a wear started before local midnight) | In use → In laundry or Ready, by the rewear rule (D12) or as he says |
| `deposited` | Ready / In use → In laundry |
| `lifted` | In laundry → In laundry (a new place; the hold stays) |
| `load_started`, `dried`, `needs_prep` | In laundry → Washing → Drying → Needs prep |
| `returned` | Washing / Drying / Needs prep / In laundry → Ready, with a place |
| `sent_out` (with `due`, the shop's label, a bag reference) / `received` | → With laundry provider → Ready or Needs prep |
| `damaged` / `repaired` | → Needs repair → Ready |
| `held` / `released` | → Missing or in review (`back_to` kept) → `back_to` |
| `missing` / `found` | → Missing or in review → the state he confirms |
| `archived` / `restored` | any → Archived → Missing or in review until he confirms the condition (INV-17) |
| `merged`, `corrected`, `blind` | D4, D5, D16 |

**Eligible for an outfit**: Ready, accessible, complete if paired (`wearable(pair)`, `wearable(set,
parts)`: pure functions here, used by A's counts, B's half-pair rule and C's engine), and not reserved
for an overlapping event. **In use is eligible only for a later plan the same day that declares it
shared with the plan it is worn for, when the rewear rule allows it** (the workbook: "held for other
plans until a reusable return or an allowed handoff between events"). "Missing or in review"
remembers `back_to`, the latest verified state (LND-04).

**D4 · The ledger: ordered, append-only, the newer verified event wins (OPS-03, LND-05; Part A).**
An event is `{id, client_id, piece | null, kind, at, sent, recorded, source, via, verified, evidence
{how: qr | match | tap | label | owner, score}, place, load, batch, due, plan, voids, rev_seen, note ≤
120}`.
1. **Time, one rule.** A device event carries `at` (its capture time) and `sent` (the device's clock
   when it sent it); the server stores `at + (server_now − sent)`, so a phone hours off still folds in
   true order, and refuses only a corrected `at` in the future or more than 24 hours old. A time he
   states ("I wore it yesterday", a move recorded after a blind period) is taken as he says, at most 30
   days back, never in the future; a stated day without a time is 12:00 local that day. `recorded`
   breaks ties. Camera → Wardrobe keeps unsent scans in memory only (R7 allows the mode no storage) and
   says "Not sent yet: keep this page open" while any wait; closing the page drops them.
2. **Deduplicate.** A `client_id` or an `id` already in the log is ignored (a retry, a restore, a
   camera that sends twice). **A second record of the same movement** (a tap in Helpers and a scan in
   Camera, the phone and the laptop, the AI calling `laundry_move` after his scan): an event whose
   target equals the current state (and place, for a return) is a `duplicate`: kept, no review entry,
   no hold. The client sends the index `rev` it saw; on a stale `rev` a write the fresh view already
   shows answers "already done" with that view.
3. **The fold is pure and order-independent.** `fold(history) -> (state, marks)` runs over the piece's
   whole history sorted by `(at, recorded, id)`; `superseded`, `conflict`, `duplicate` and `voided` are
   its outputs, computed, never written back into the append-only log. `apply` appends and re-folds
   the piece. Its rules: an event older than the piece's newest verified state-setting event changes no
   state (`superseded`; an old basket message after a confirmed clean return can't make the shirt dirty
   again; a superseded `wear_done` still counts as a wear); a transition the table refuses is a
   `conflict` and asks for a review entry but **does not hold the piece by itself**; an unverified event
   that would change availability becomes a hold, never a state change; a `corrected` event (`voids:
   we_…`) re-folds from the valid history, later verified events stay authoritative, and two later
   events that conflict ask for a rescan.
4. **One commit for everything an event changes (the `transact` contract, I0).**
   `WardrobeStore.transact(uid, fn)` runs `fn(view, tx) -> Commit(events, extra)` inside A's Firestore
   transaction: every read first (B reads its own `wardrobe_laundry` / `wardrobe_review` documents
   through the same `tx`), then A appends the events, re-folds, writes the index and the log pages, and
   writes `extra` (B's documents) in the same commit. The fold returns `ReviewNeeded` items (a hold, a
   conflict, a pending deposit); **B's writer must add each one's entry in that same commit**, so a
   hold never exists without the entry that resolves it, and a load never says Washing while its pieces
   are In laundry. An `extra` write that raises rolls back the index, the log and B's documents. A's
   daily `wardrobe_sweep` gives any hold without an open entry one (a crash between versions). I0 ships
   the fold's rules as **one conformance test** that both `tests/r13_fakes.py`'s in-memory store and
   A's real store must pass, so B and C never build on a fake that folds differently.
5. **After the commit** A tells the observers (I0's `ChangeObserver`, once per changed piece, with the
   event's kind and plan link, never raising, never inside the transaction): C's plan refresh (STY-15)
   is one; an observer only reads and alerts, it never writes the ledger.

**D5 · Checkpoints in their phone form; the camera later.** Every event's `source` is `phone` |
`tap` | `camera` (`via`: panel / chat / voice / telegram for a tap; the device's random id for a
phone):

| Checkpoint | Phone form now | What a fixed camera adds later |
|---|---|---|
| Wardrobe intake | "Add pieces" (one or several laid apart; a box per piece) | `camera` events from R8's camera setup into the same `transact` |
| Dirty basket | "To laundry" scan, or a tap / "my navy shirt is in the laundry" | a crossing and a release seen over the rim |
| Clean return | "Back clean": the place it goes to, and dry / needs pressing | the return surface |

- **LND-02 (a deposit, not a hover):** on the phone a deposit exists only when he presses "Put in
  laundry"; a scan he leaves or cancels changes nothing. The model holds the camera's evidence fields
  (`crossed`, `released`); a `camera` event without a release goes to review.
- **LND-03 (a bundle):** each box with enough evidence (a QR read, or a match he confirms) becomes a
  deposit; "and N more I couldn't show" makes a **pending deposit with no piece id** (never a guess)
  and holds only the plausible pieces: those of the category he names that are In use or were worn in
  the last 24 hours; none plausible → no hold, a review entry.
- **OPS-02 (a blind period):** "I moved things without scanning" (a tap, with the places or
  categories touched, at the times he states) holds the affected pieces until a rescan or his
  correction; a planned piece whose last verified sighting is older than `wardrobe_stale_days` (14)
  makes the plan ask for a quick check (STY-10). A camera outage later marks its zones blind the same
  way.
- **OPS-01 (item-only capture):** D9's person and face check, the crop, on-device processing, Stop and
  the camera's lock (`console-camera.js`: Stop ends the camera before the next frame; hiding the tab or
  the page stops it), photo retention, and the rule for later fixed cameras: only the intake surface,
  the basket rim and the return surface, never where he changes (a place's `kind`; R8 checks the
  framing).

**D6 · Things is not reused as the store; its text tools are; "where is my …" never disagrees.** Why
not the store: one free-text place per thing (no place ids), no state, no event log, at most 500
things and 50 moves shared with everything else he notes, and a `holder` about other people; a
wardrobe of 150–400 pieces with 200-event histories would crowd it and break INV-13 and OPS-03.
Reused: `belongings.text.thing_key`, `recall.retrieval.bm25` (INV-09, INV-15),
`recall.sensitive.sensitive_reason` on his free text. Routing with the AI off: I0 gives
`offline/mode.py` `add_phrases(routers, *, first: bool = False)`; R13 installs its routers with
`first=True`, ahead of R14's `things`. They take only:
- "where is/are my <a wardrobe type word>" → **two calls**, `wardrobe_find(query)` then
  `belongings_where(item)`, each through the gateway with its own row (so a "Never" on Things is
  kept); the sentence says the wardrobe's answer and, when it has none, Things' ("Not in your
  wardrobe; Things has 'black belt' in Drawer 2");
- R14's PUT form for a wardrobe type word ("I put my watch in the travel bag") → `wardrobe_find(query)`
  and then `wardrobe_edit(piece, place)` (the move resolves the piece first and edits it by id; a place he named before; an unknown place is refused with his places listed, so a watch is
  never in two lists);
- never a possessive ("my wife's watch", "the kids' shoes"), never R14's `_NOT_A_THING` words, and
  never the accessory words that are usually Things (bag, glasses, spectacles, keys, wallet, umbrella):
  those stay with Things.
With the AI on, `WARDROBE_RULE` (D21) sends finds and moves of clothes, footwear and worn accessories
to the wardrobe and tries Things when the wardrobe has none. A test runs every R14 phrase test with
R13's routers installed first: each still routes as before.

**D7 · Recognition, free by default.**
- **Kind by one tap**: chips from the workbook's categories (shirt, T-shirt, trousers, jeans, vest,
  underpants, sock, shoe, sneaker, sandal, belt, watch, kurta, blazer, jacket, rainwear …, Unknown);
  he may add a type; a type change keeps the id (INV-04); a change into a private-by-default category
  asks "Make it private?".
- **Colour suggested** by the `colour` task (arithmetic: the median of the box's centre in Lab, the
  nearest of 18 named colours by ΔE; "multicolour" when two clusters are close): a suggestion he
  confirms or locks (INV-09).
- **"Seen before?" on the phone**: `embed` returns the piece's fingerprint as **uint8 always** (1,280
  bytes, 1,708 base64 characters: inside `plain()`'s 2,000, fact 3) with its `model`
  (`mnv2-int8-1`, or `mnv2-fp32-1` for the fallback, D8). The mode fetches his saved fingerprints of the
  same model (`GET /v1/wardrobe/fingerprints`: sealed at rest, decrypted for the signed-in console,
  kept in memory only), centres them by their mean (MobileNet's pooled features are non-negative, so
  raw cosines of unrelated pieces are already high), compares by cosine (the best of each piece's
  views) and shows at most 3 candidates; **nothing is decided without his tap**. The pilot records the
  raw and the centred score. Starting bands on the centred score (calibrated in the pilot): ≥ 0.80
  "likely this one", 0.60–0.80 "maybe", below "new?"; two candidates of one type within 0.03: "identical
  copies: read its label or tap which one", and a basket event holds both until he says (LND-04). The
  query fingerprint never leaves the phone; a fingerprint is stored only when he saves the piece's look
  ("Remember how it looks", with or without a photo), never for a private piece.
- **QR labels for identical copies (INV-07)**: `GET /v1/wardrobe/labels.svg` (segno) prints 24 labels a
  page, numbers and codes only (no text of his), served with `Content-Security-Policy: default-src
  'none'`, `X-Content-Type-Options: nosniff` and `Content-Disposition: attachment`. A read code counts
  only when it is `jw1:` plus exactly 8 characters of the alphabet above **and** is one of his labels in
  the index; any other code on a clothing tag is "not a JARVIS label": never sent, opened or shown.
- **Care and size labels (INV-10)**: "Read a label" runs the R7 `text` task; only parsed forms are kept
  — size `^[0-9A-Z /.-]{1,12}$`, fabric names and percentages from a fixed list, care words from a
  fixed list, brand ≤ 30 characters of `[A-Za-z0-9 &.'-]` — never the raw OCR text, and each stays
  **unverified** until he confirms or types it; wash symbols are never inferred. An unverified field is
  never returned to the model.
- **Optional AI tagging**: off; on only by his setting and his press of "Ask the AI to tag this piece
  (about ₹N)", and only (a) for a **saved** piece id that is not private and not of a private-by-default
  category — **the server refuses with 422 from the piece record, not from the client's word** — and (b)
  after the person and face check on **the same bitmap** as the crop (D9). It reuses
  `picture.eyes.BrainEyes.look()` (fact 17) with a wardrobe system prompt (strict JSON from the same
  fixed lists): No-AI refuses, a seeing and non-training brain only, `Billing.ensure_allowed` first, one
  recorded cost, its timeout. The cap's counter is **the month-to-date tagging ₹ in his sealed index**
  (the month in his zone): the call is refused when month-to-date + the estimate > `wardrobe_ai_tag_month_inr`
  (₹30), and the recorded cost is added after it. N comes from `llm/pricing.py` for the brain that
  would answer (a 512-px crop ≈ 350 image tokens + 400 instruction + 120 out: ≈ ₹0.01 on Haiku 5.5,
  ≈ ₹0.26 on Sonnet 5.5). The answer is a suggestion, never a locked field; tagging keeps no picture.

**D8 · The model files: pinned, committed, self-checked, served by the existing route.** Part D's
`scripts/wardrobe_assets.py` (standard library plus `onnx==1.23.2`, a dev tool run by hand, never in
the image) downloads from
`https://media.githubusercontent.com/media/onnx/models/c5cae0f1942c8d7727372c7b1f6b485aa39e4421/validated/vision/...`,
refuses a file whose SHA-256 differs from the table, makes the cut (the table's method), checks the
cut's SHA-256, and writes `static/vendor/vision/r13-1/MANIFEST.json` (`sha256`, `bytes`, `type`
`application/octet-stream`, `source`, `licence`, `changes`, the int8 output's zero point and scale, and
each task's self-check reference) with the licence texts: the zoo's Apache-2.0 LICENSE for MobileNet
(and Apache-2.0 §4's notice of the cut in `changes`); UltraFace's MIT text from Linzaer's repository at
the pinned commit; for SSD both the zoo's MIT statement and TensorFlow's Apache-2.0 LICENSE with the
attribution line, its `licence` reading "MIT (ONNX Model Zoo); weights from the TensorFlow Object
Detection API (Apache-2.0)", the same in `buildbook/gen/libs.py`. I0 teaches `vision/assets.py` the
second release (`WARDROBE_RELEASE = "r13-1"`, `WARDROBE_FILES`, `installed()` over both); D owns the
folder, the files and the R7 test edits (`BASE13 + '…'` beside `BASE + '…'`). The route
(`api/console.py:403`) serves them once they match.
- **Self-check at load**: each task's `load()` runs its fixed input and compares the output with the
  manifest's reference (exact for uint8, a tolerance for floats); a mismatch is "not installed" (for
  `person` and `face`: saving a photo is off). That is how a mis-running quantized operator on his
  phone is found.
- **The fallback**: if `embed` fails its self-check on his phone, D vendors the fp32 cut (sum above)
  and `embed` quantizes its output on the phone with the int8 file's fixed scale, still uint8, now
  `mnv2-fp32-1`. Fingerprints of another model are never compared; the phone recomputes them from his
  saved photos, and a look kept without a photo is asked for again.
- **One runtime per page**: the vision tasks import the same ORT module URL as the wake word and set
  the same `env.wasm` values (one thread, no proxy, `wasmPaths` = ORT's folder) before their first
  session; `console-wakeword.js` is not edited (the R6.2 voice work is beside it); a browser test runs
  the wake word and a wardrobe task in one page.
- **Training data**: ImageNet, WIDER FACE and COCO, which trained the weights, have their own (for some,
  non-commercial research) terms for the data; JARVIS uses the published weights under the stated
  licences for one person, non-commercially (R7's position for MediaPipe's COCO-trained detector). The
  sentence goes into C63's successor text.

**D9 · Pixels: two named panels; a photo is a press, a crop and a seal.**
- **R7's guard, widened in the open**: I0 adds a `PANELS` allow-list (`console-camera-panel.js`,
  `console-wardrobe-scan.js`) and a static test that fails any other console module calling
  `JarvisVision.run` / `stream`, `JarvisCamera.frame` / `photo`, or any API in `D13_APIS`. The scan
  module gets the camera panel's rules: no `fetch`, XHR, `sendBeacon`, WebSocket, `localStorage`,
  `sessionStorage` or `indexedDB`; `JarvisConsole.api` only to `/v1/wardrobe…` and `/v1/laundry…` paths
  and never with picture bytes; picture bytes only through `door.wardrobe` and `door.tag`;
  `textContent` only; ASCII source. R7's INTEGRATION-B gets the line its contract requires.
- **What the check gates**: the person check (`person`, SSD "person" ≥ 0.5) and the face check
  (`face`, UltraFace ≥ 0.7, NMS) gate **what is kept or sent**: a photo, a fingerprint, an AI tag. One
  hit → none of the three for that frame: "This picture shows a person. Lay the piece on a surface or
  hang it, and take the photo again." A QR read or an on-device match that sends only ids still makes
  its event (a shirt held over the basket shows an arm). The checks and the crop use **one bitmap**;
  "Choose a photo" gets the same redraw and checks. Without the two model files, saving a photo is off
  ("not installed") and taps and scans still work. A test hook can only add refusals.
- **The crop**: ≤ `wardrobe_photo_side` (512) px, JPEG quality 0.8 (≈ 35 KB), made in memory and handed
  to **the one door**: I0 adds `wardrobe(blob, {piece, view})` and `tag(blob, {piece})` to
  `console-r7-send.js`, which count in "Pictures sent from this device today" and post to
  `POST /v1/wardrobe/photos` / `…/tag`. The button says so: "Save this photo with the piece (sealed; only
  you)". The save runs three models in a row (≈ 0.3 s here, ≈ 0.9–1.7 s on a phone): the mode shows
  "Checking…".
- **On the server** (A): JPEG only, a side ≤ `wardrobe_photo_side` read from its SOF marker (fact 18;
  a 600-px photo refused), ≤ 200 KB, cleaned by `sanitise_jpeg`, sealed with the new purpose
  `wardrobe_photos` (AAD `wardrobe/photo/{uid}/{photo}/v1`) in `wardrobe_photo/{uid}_{photo}`, at most 3
  views a piece; its fingerprint in `wardrobe_fp/{uid}_{shard}` (200 a shard, same purpose). **A private
  piece never has a photo or a fingerprint**: the mode skips both and the routes refuse them (422).
  Marking a piece private later deletes its photos and fingerprints in the same change.
- **The promises, changed in the same I1 commit that makes saving possible**, with the new words pinned
  by a test: C63 becomes "Two panels see pixels: Camera and Camera → Wardrobe. A frame is never stored.
  A wardrobe photo is kept only when you press Save, cropped to the piece, after a check for a person
  or a face that can miss; the use cases of R8 to R10 receive results only." The camera's privacy row
  keeps "Never kept: a camera frame"; the wardrobe photos have their own row (D20).

**D10 · Private pieces: count-only everywhere but his own checklist.** Private by default: underpants,
briefs, boxers, vests, undershirts, thermals (he may change any piece). I0's pure `wardrobe/redact.py`
decides what each sink may show:

| Sink | A non-private piece | A private piece |
|---|---|---|
| Helpers → Wardrobe, Camera → Wardrobe (his signed-in console) | everything | everything, behind "Show private basics" |
| What the AI is shown (tool results) | id, his label (fenced), type, colour, state, place; never an unverified field | id, slot and state only ("a private basic") |
| Alerts, Telegram, Web Push, the lock screen | type and colour words from the fixed lists ("a navy shirt"), never his label | "a private basic" |
| Approval cards (stored in clear, printed on Telegram) | their words come from `Tool.preview` through `redact.py`: fixed words + type and colour | "a private basic (No. 17)" |
| Recently deleted (Firestore, in clear) | the fixed title "A wardrobe piece"; the panel shows the words from the sealed index | the same |
| Logs, audit, Activity | ids and counts only (the audit keeps an argument hash) | the same |

Every write tool that can make a card takes **piece ids**; a free-text name is resolved by a read
first (`wardrobe_find`, or the tool's own `preview`). The one exception is the spoken / No-AI one-step
path: `laundry_move` and `wear_log` also take a `query` (`wardrobe_edit` does not: D6's move edits by id); if such a call becomes a card, its stored
arguments keep his words as typed (R2's precedent for Things' put), while its summary and Telegram text
come from `preview` through `redact.py`. The needles eval lists that as the one allowed place.

**D11 · Laundry: prepare, never order or pay (Part B).** Deposits (LND-01), lifting out of the basket
keeps the hold (LND-06), a load holds only confirmed ids (LND-07), each step moves only the pieces
named (LND-08, LND-10), a clean return restores the same id with its place and triggers the plan check
(LND-11), parts of a load come back separately (LND-12), a half pair stays out of pairs (LND-13; a
replacement half only by his explicit re-pairing), outside laundry and dry-cleaning are records: his
label for the shop (≤ 40, no phone number: a run of 5+ digits is refused), a bag reference, the pieces,
a `due` date on the `sent_out` event (A's view shows it as `expected_back`), "overdue" and "short
delivery" flags, each piece checked back in (LND-14); the history shows verified events, corrections
and the current step (LND-15). No call, no WhatsApp, no order, no payment: there is no tool that could.
Pending deposits, holds, conflicts and stale checks are entries in B's review queue
(`wardrobe_review/{uid}`), written in the same commit as the event (D4.4), resolved by a scan, a label,
a tap among the candidates or "there was no deposit" (which clears the hold to `back_to`); past 100
open entries the oldest stale checks fold into one "check this place" entry, and a pending deposit is
never dropped. LND-05's correction uses A's `correct()`.

**D12 · Styling by fixed rules (Part C).** `wardrobe/styling/rules.json` (data, checked at start):
slots (base: vest/undershirt and underwear, both private; top; bottom; outer; socks; shoes; belt; watch;
extras: tie, cap, scarf), dress codes (business formal, business casual, smart casual, casual, festive
/ traditional, mess-tolerant, sport), event rules (formal meeting → business formal, shoes + belt +
watch; Diwali and other festivals → festive, sets checked whole; Holi → only `mess_ok` pieces, never
`delicate`; rain likely → rain-ok shoes and an outer layer; heat → light fabrics), a small
colour-pairing table, and rewear defaults (trousers, jeans, outerwear, belts, shoes and the watch
reusable; shirts, T-shirts, vests, underwear and socks to laundry after a wear). The engine
(`styling/engine.py`, pure) applies hard exclusions first (state, holds, reservations, his "never"
rules such as "no tight collars", STY-08), fills required slots, ranks by dress-code fit, weather,
colour pairing, recent wear and his preferences, ties broken by piece id, and returns a primary look
and up to two alternatives, each with its **reasons** and the **actual piece ids** (STY-11), its
compromises, and any **gap** with a next action ("press the white shirt", "collect from the
dry-cleaner tomorrow", STY-16, LND-16 from `expected_back`). Plans (`wardrobe_plans/{uid}`): a date or
an event, the dress code (tentative until he sets it, STY-03), locked slots (STY-12), reservations by
time window with conflicts and deliberate transfer (STY-14), several events in a day with a **declared
shared base** and "change these" lines (STY-13). **Refresh (STY-15)**: C's observer marks a plan using
a changed piece "needs a new …", proposes a ready substitute (auto-swap off by default) and sends
`outfit_changed` when the event starts within `wardrobe_change_window_h` (36); **a change caused by
wearing a piece for that plan, or by a declared hand-off to a shared plan, is not a change for those
plans: nothing is marked and nothing is sent**. **Wear (STY-17)**: `wear_started` and `wear_done` (D3)
make one wear; saving or previewing a plan changes no count. The AI stylist stays in R17.

**D13 · Only the calendar he picks, only the fields he picks (OPS-04; Part C).** Settings → "Outfits
from a calendar": none by default (manual planning always works). He picks one calendar from his
`calendarList` (no new Grant, fact 15): only a calendar id that list returned is accepted (kept sealed,
URL-encoded into the path). Fields: start and end (always), title (on by default: matched against the
rules' words in code only), location (off; "indoor/outdoor" from it when on); description and attendees
are never fetched (the request names only the chosen fields with Google's `fields` parameter). **Every
read** — the 5-minute `outfit_clock`'s (at most every `wardrobe_calendar_refresh_min`, 60, the next 48
hours), listing his calendars, and the live titles in his panel — goes through `tools/background.py` on
the `calendar_list_events` row: "Allow" only, one kind-only audit line; with "Ask first" or "Never" the
panel says "Your Calendar permission is <choice>: allow it, or plan by hand." **A title is never stored,
sent or logged**: a plan keeps the event's fingerprint, its times and the dress code; the panel shows
the title live while he looks. **A cancelled event** is found by absence (Google returns no cancelled
events with `singleEvents=true`, fact 15): an event fingerprint missing from a read that covers its
window → "event cancelled", the plan kept as a draft, no `outfit_ready`; an edited one refreshes by its
`updated` stamp. Disabling the calendar stops automatic plans from it at once; existing plans stay,
marked "manual".
**Owner's decision, 16 Nov 2026 (INTEGRATION-C 6.14b):** a calendar event he declined still gets an
outfit plan, as built: his own response is not read and attendees stay unfetched (above), so a declined
event is planned like any other and he drops the plan by hand (the plan's Release). No code changes.

**D14 · Tomorrow's weather: R11's helper code, C's own small document.** R11's stored weather models
are `extra="forbid"` (fact 16), so C adds nothing to R11's documents (a rollback to v14.0.2 would find
them unreadable). C's `outfit_clock` fetches the forecast for his R11 place (read-only from R11 B's
`OutsideStore`, through the `house` part's services, late) at most twice a day (from 05:00 and from
18:00 local), with R11's own `request_params`, fetch and `parse_forecast` (no new outside service, ≈ 2
calls a day against Open-Meteo's 10,000), and keeps tomorrow's and today's summary (`t_max`,
`rain_from`) sealed in `wardrobe_outlook/{uid}`. It runs only while R11's weather is on for him (his
place set, R11's poll enabled): his consent there is the consent here. Helpers off or no place:
"Weather unknown: I assumed indoors". Every look says its assumption: "Weather for your home area: rain
likely from 15:00" (STY-07). C edits no R11 file.

**D15 · His timezone and the clock, everywhere.** "Tomorrow" is the next calendar day in his zone (the
brief store's zone for him, else `user_timezone`, `config.py:608`) through `ctx.zone(uid)`; the time is
`ctx.now()` (UTC), never the real clock: a static test fails any `datetime.now(`, `date.today(`,
`time.time(` or `utcnow` under `wardrobe/` and `offline/phrases_r13.py`. Browser tests pin the page
clock (Playwright's `page.clock`). R14's No-AI "Recently deleted" names the UTC day between 00:00 and
05:30 IST (I1-NOTES follow-up); R13 does not repeat it: tests run at 23:30 and 00:30 IST.

**D16 · Confirm before commit.** `wardrobe_merge` (INV-16) and `wardrobe_retire` (archive and restore,
INV-17) are R2 with `ask_when` always (a card, as `vitals_drill_start`), in `NO_BULK_TOOLS` (never
"Approve all"); a merge keeps one active id with both histories (the merged-away id becomes a `merged`
tombstone pointing at it; its log pages never move) and can be undone from Recently deleted for 30
days (the undo only drops the link); restore reuses the same id and lands in "Missing or in review"
until he confirms the condition. `wardrobe_remove` is R2 `undoable`: the piece goes to Recently deleted
(new kind `wardrobe_item`, in place, the fixed title "A wardrobe piece", purge with the passkey like a
thing); restored from the bin it lands in "Missing or in review" (it was away up to 30 days); its
photos, fingerprints and log go only when the entry is purged. The panel's buttons call the same tools
through the gateway (D1). Deleting everything is a Privacy row (passkey).

**D17 · Backup and restore of the wardrobe (OPS-06; Part A).**
- **Size**: `wardrobe_backup_max_mb` **25** (5–30). A backup larger than that is offered without photos
  (R14's Firestore backups keep them), or in photo parts of ≤ 25 MB each. The restore route gets its
  own body cap from `api/r13_wiring.py` `BODY_CAPS = {"/v1/wardrobe/restore": …}` through
  `**r13.BODY_CAPS` in `app.py`'s `routes=` (fact 19; +1 line) and reads the body with `read_capped`.
- **Download** (`GET /v1/wardrobe/backup`): streamed in chunks; one file sealed with the `wardrobe` key
  (AAD `wardrobe/backup/{uid}/v1`) holding pieces, pairs, sets, places, labels, states and the event
  log, plus photos and fingerprints **only when he ticks "include photos"** (as their own sealed blobs,
  never opened for the backup). It opens only on this JARVIS with today's key; after a key change
  (`KEY_ID`, fact 7) older files can't be read: the button says so.
- **Restore, confirm before commit, in two steps**: `POST …/restore/check` checks the seal and the
  schema and answers the counts (added, already there, superseded, back from Recently deleted, purged
  since) with a token, **writing nothing**; `POST …/restore` with that token applies it in chunks of ≤ 50
  pieces a transaction (each ≤ 10 MiB), idempotent by event id and client id, so a restore cut after any
  chunk runs again without duplicates. For a piece in both, the current record's attributes win and the
  events are unioned and re-folded (D4); a piece purged since the backup comes back only if he ticks
  it. The Privacy panel's export is a plain JSON without photos.

**D18 · Permission rows, Telegram, the skill register, trust.** Three new R2 rows after `pictures`,
before Maps and YouTube (which stay last): **`wardrobe`** ("Your wardrobe: pieces, places, labels, pairs
and sets"; `wardrobe_*`), **`laundry`** ("Laundry: the basket, loads, drying, outside laundry";
`laundry_*`), **`outfits`** ("Outfits: suggestions, plans, reservations and what you wore"; `outfit_*`,
`wear_*`; the hint says the calendar read obeys the Calendar row). 49 → 52; the save cap 51 → 54.
Telegram: the four families join `PERSONAL_PATTERNS` (the switch for the vault, notes and things,
default off); `wardrobe_item` is an in-place kind, so `deleted_list` hides it while the switch is off.
Skill register: group `wardrobe` (`wardrobe_*`, `laundry_*`) under **Task & Productivity**, group
`outfits` (`outfit_*`, `wear_*`) under **Decision Support**, with words (wardrobe, shirt, trouser, jeans,
kurta, vest, sock, shoe, belt, watch, laundry, wash, iron, press, dry clean, dhobi, outfit, wear, dress
code, kapde, pehen …); none is `telegram_open`; the No-AI tools are listed under `no_ai`; I0 names all 18
under `planned`, and I1 empties `planned` (`test_r14_skill_coverage.py:49–55`). **Trust**: every R13 tool
is untrusted by default (`trusted_output` False); a read is `may_vouch` and vouches per result only when
every string in it is his typed label or a fixed-list word, never when it carries read or unverified
text; tests both ways.

**D19 · Alerts: four kinds (52 → 56).** Fixed templates, never his label, never a title, never a private
piece (D10):

| Kind | Level | When (claim written before the send, `wardrobe_told`) | Text (example) |
|---|---|---|---|
| `outfit_ready` | important, daytime ring, held at night | a plan for an event on his chosen calendar is ready, at `wardrobe_plan_evening` (20:00) the evening before; once a plan; never for a cancelled event | "Tomorrow's outfit for your 10:00 event is ready in Helpers, Wardrobe." |
| `outfit_changed` | important, daytime ring, held at night | a planned or reserved piece left eligibility within 36 h of the event, for a reason other than wearing it for that plan or a declared hand-off; once a plan per 2 hours | "A navy shirt in tomorrow's 10:00 outfit went to the laundry. A ready one is suggested." |
| `laundry_overdue` | important, daytime ring, held at night | an outside-laundry batch is past its `due`, or came back short; once a batch a day | "2 pieces at the laundry shop are a day overdue." |
| `wardrobe_review` | info (feed only) | open review entries the morning after; once a day | "3 pieces wait for a quick check." |

The evening's fourth and later `outfit_ready` alerts are ONE line on the same kind (I1, Workshop
decision 4; INTEGRATION-C 5.13): "Tomorrow's outfits for 17 more events are ready in Helpers, Wardrobe."
(a count, never a title).

Each has an Alerts-card switch, held words, a Web Push target (`helpers`) and book words; the normal
Telegram bucket; no storm-table change. `KIND_OWNER`: the two outfit kinds C, the other two B.

**D20 · No-AI sentences (pass 3; Part D) and the Privacy rows.** `offline/phrases_r13.py`, anchored like
R14's (the whole message is the phrase), installed first (D6). Each ends in gateway calls:

| He says (examples) | Tool |
|---|---|
| "what should I wear tomorrow / today / for Diwali / for the meeting" | `outfit_suggest(day, occasion)` |
| "where is my black belt" / "where are my brown shoes" | `wardrobe_find(query)`, then `belongings_where(item)` (D6) |
| "I put my watch in the travel bag" | `wardrobe_find(query)`, then `wardrobe_edit(piece, place)` (D6: the move resolves the piece first, then edits it by id) |
| "my navy shirt is in the laundry" / "put the white shirt in the wash" | `laundry_move(step=basket, query)` |
| "the white shirt is back" / "the white shirt is clean" | `laundry_move(step=ready, query)` |
| "what's in the laundry" / "laundry status" | `laundry_status` |
| "I'm wearing the blue shirt" / "wearing the meeting outfit" | `wear_log(action=start, query)` |
| "I wore the blue shirt today" / "done for today" | `wear_log(action=done, query)` |
| "how many shirts do I have" / "how many socks are ready" | `wardrobe_count(type)` |

A name that fits several pieces makes a review entry (and holds, for the basket), never a guess. R14's
`WITHOUT_AI` gains "your wardrobe: where a piece is, laundry, today's outfit" (I0, one line). The
Privacy rows (section "Wardrobe", D's `wardrobe/phone/privacy.py` over each part's `WardrobeData`, each
source saying its row): "Wardrobe pieces and places", "Laundry and wear history", "Outfit plans" (C's own
row since I1: a key change costs plans only), "Wardrobe photos and fingerprints",
"Only on this device: the Wardrobe mode's last choices"; export, and delete with the passkey.

**D21 · Version, persona, guide.** `__version__ = "13.0.0"` at I0 (lower than 14.0.2: nothing compares
versions, as with R7's 7.0.0 after 11.1.1); the four pins move. Persona **p13.0** at I1 (pinned in 21
test files, which move then; `WARDROBE_RULE`): "Clothing, footwear and worn accessories are in the
wardrobe: find and move them with the wardrobe tools; try Things when the wardrobe has none. Before a
change, find the piece and use its id. Never name a private piece outside the Wardrobe tab; say 'a
private basic'. An outfit comes from wardrobe rules with their reasons; say a piece is ready only when
the tool says so. Laundry is prepared, never ordered, paid or called. Archive, restore, merge and remove
are cards." Guide cards **C69** Wardrobe catalog and the ledger, **C70** Laundry, **C71** Outfits, and
C63's new words (D9); I0 lists them PLANNED with every collection; I1 fills them.

**D22 · Deferred, with reasons.**

| Item | Why not now |
|---|---|
| Fixed basket and return cameras (LND-02, LND-03, OPS-02 in their camera form) | Needs a camera at the basket and R8's camera setup; the events and holds are built |
| A brief line "Today's outfit" | The `outfit_ready` alert and the tab cover it |
| A dock button of its own; a push link that opens the Wardrobe tab | `console.html` has no lines to spare (D1); the link needs R7's launch-word module |
| A launch word `?do=wardrobe` and an Android shortcut | R7's launch words and the native shortcut list; later |
| DINOv2 fingerprints, fabric labels (RFID or washable tags) | R8 or the owner's purchase; QR labels and taps cover INV-07 |
| Auto-swap on by default | He decides after the pilot |
| AI stylist | R17, paid |

## Data model (prefix `jarvis_`; every collection named in the guide's cards before code uses it)

| Collection | Part | Holds | Sealed | Kept |
|---|---|---|---|---|
| `wardrobe/{uid}` | A | the index: pieces, pairs, sets, places, labels, custom types, settings (calendar choice and its sealed id, fields, lead, AI tagging, private display), the month's tagging ₹; ≤ 900 KB sealed | `wardrobe` | until deleted |
| `wardrobe_log/{uid}_{piece}_{page}` | A | that piece's events, 200 a page, append-only | `wardrobe` | until the piece is purged |
| `wardrobe_photo/{uid}_{photo}` | A | one cleaned ≤ 512-px JPEG of a non-private piece | `wardrobe_photos` | until the piece is purged, made private, or he deletes it |
| `wardrobe_fp/{uid}_{shard}` | A | fingerprints (1,280 bytes each) with piece, view and model, 200 a shard | `wardrobe_photos` | as its photo |
| `wardrobe_restore/{uid}` | A | a checked restore's token and counts, never its contents | `wardrobe` | 1 hour |
| `wardrobe_laundry/{uid}` | B | open loads (≤ 50), outside batches (≤ 20); closed ones 90 days | `wardrobe` | 90 days after closing |
| `wardrobe_review/{uid}` | B | open review entries (≤ 100): pending deposits, holds, conflicts, stale checks | `wardrobe` | until resolved, then 30 days |
| `wardrobe_plans/{uid}` | C | plans (≤ 60: 14 days back to 30 ahead), reservations, shared bases, his rule words and preferences | `wardrobe` | 90 days after the event |
| `wardrobe_cal/{uid}` | C | the last calendar read: event fingerprints, times, the dress code found (never a title) | `wardrobe` | overwritten |
| `wardrobe_outlook/{uid}` | C | today's and tomorrow's weather summary for his R11 place | `wardrobe` | overwritten |
| `wardrobe_told/{uid}_{key}` | C and B (each key starts with its part's name) | once-only claims (a hash) | no | 30 days |

Keyring purposes 22 → **24** (`wardrobe`, `wardrobe_photos`). Never stored: a calendar title,
description or attendee, a frame, a picture or fingerprint of a private piece, a picture with a
detected person, the query fingerprint of a scan, raw OCR text, a QR code that is not his, anything
about another person, a phone number or address of a laundry shop. Sizes (estimates): an event ≈ 250
bytes sealed; 150 pieces × ≈ 1.3 photos × ≈ 47 KB sealed ≈ 9 MB; logs ≈ 4 MB a year; ≈ 15–20 MB in the
first year.

## The HTTP contract (I0's `wardrobe/http.py`)

I0 writes the Pydantic request and reply models of every route (method, path, body, reply, error
words) before the parts start, and `tests/r13_fake_server.py` serves them from `tests/r13_fakes.py` for
D's browser tests. Each part's route tests assert those models exactly; a change is a seam change with
a line in the part's INTEGRATION file. Every route is the owner's (signed in), rate-limited (30 changes
and 60 reads a minute per owner), and answers plain words.

| Route | Part | What |
|---|---|---|
| `GET /v1/wardrobe` · `GET /v1/wardrobe/pieces/{id}` | A | the view (pieces, counts, pairs, sets, places, labels, settings, `rev`) · one piece and its history summary |
| `POST /v1/wardrobe/scan` | A | one or more events from the phone or a tap (`transact`; the `rev` seen) |
| `POST /v1/wardrobe/photos` · `DELETE …/photos/{id}` · `GET …/photos/{id}` | A | a saved crop (the door) · delete · the sealed thumbnail for his console |
| `GET /v1/wardrobe/fingerprints` · `POST …/fingerprints` | A | his saved fingerprints of one model · "Remember how it looks" |
| `POST /v1/wardrobe/tag` · `GET …/tag/estimate` | A | D7's AI tag (the door) · its ₹ |
| `GET /v1/wardrobe/labels.svg` · `POST …/labels` | A | the sheet · assign a label to a piece |
| `GET /v1/wardrobe/backup` · `POST …/restore/check` · `POST …/restore` | A | D17 |
| `GET /v1/wardrobe/pilot` | A | the pilot counts (e2e 8), counts only |
| `POST /v1/wardrobe/tools/{tool}` | A, B, C | the panel's changes through `gateway.execute` (D1) |
| `GET /v1/laundry` · `GET /v1/laundry/review` | B | the laundry list, loads, batches · the review queue |
| `GET /v1/outfits` · `GET /v1/outfits/calendars` · `PUT /v1/outfits/settings` | C | plans and suggestions · his calendars (governed read) · calendar, fields, lead, auto-swap |
| `GET /v1/r13` | I0 | each part's ready word |

## Tools (18; every call through the gateway)

| Tool | Risk | Row | Part | Card | No-AI |
|---|---|---|---|---|---|
| `wardrobe_find` | R1 | wardrobe | A | — | yes |
| `wardrobe_count` | R1 | wardrobe | A | — | yes |
| `wardrobe_add` | R2 | wardrobe | A | tainted / spoken rules | — |
| `wardrobe_edit` (type, attributes, lock, verify a care field, private, place, label, pair, set) | R2 | wardrobe | A | as above; a card's words from `preview` | yes (a move) |
| `wardrobe_places` | R2 | wardrobe | A | as above | — |
| `wardrobe_merge` | R2 | wardrobe | A | always (`ask_when`), never Approve all | — |
| `wardrobe_retire` (archive / restore) | R2 | wardrobe | A | always, never Approve all | — |
| `wardrobe_remove` | R2, undoable | wardrobe | A | the 11th delete / tainted | — |
| `laundry_status` (the list, or one piece's history) | R1 | laundry | B | — | yes |
| `laundry_move` (basket, lifted, load, washing, drying, prep, ready + place) | R2, `spoken_ok` | laundry | B | tainted rounds | yes |
| `laundry_review` (list, resolve) | R2 | laundry | B | as above | — |
| `laundry_correct` (LND-05) | R2 | laundry | B | as above | — |
| `laundry_send_out` (send with `due`, receive per piece) | R2 | laundry | B | as above | — |
| `outfit_suggest` | R1 | outfits | C | — | yes |
| `outfit_plans` | R1 | outfits | C | — | — |
| `outfit_plan` (save, lock a slot, change one, reserve, transfer, release, declare a shared base) | R2 | outfits | C | as above | — |
| `outfit_prefs` (dress code for an event, rules, fit and colour preferences) | R2 | outfits | C | as above | — |
| `wear_log` (start, done; one wear) | R2, `spoken_ok` | outfits | C | tainted rounds | yes |

Every result lists at most 20 pieces, fences his words, follows D10's view, shows fixed Activity words
(`Tool.activity_words`) and follows D18's trust rule. Write tools take piece ids; only `laundry_move`
and `wear_log` also take a `query` (D10).

## Per part: failures, security, cost

| Part | Failure modes and handling | Security and privacy | ₹ a month |
|---|---|---|---|
| A · Catalog and ledger | No token key → the wardrobe is off (never in clear) and says so; an index that can't be read or opened is never overwritten; the byte guard and the piece cap refuse in words; a photo that isn't a clean JPEG of the right size refused; a restore whose seal, schema or token fails writes nothing; a cut restore runs again | sealed index, logs, photos and fingerprints; photo bytes cleaned, never decoded on the server; the tag call only for a saved non-private piece, to a seeing, non-training brain, under the counter; the backup opens only with this JARVIS's key | ₹0 (AI tagging only if on: ≈ ₹0.01–0.3 a photo, cap ₹30) |
| B · Laundry | an ambiguous name → a review entry and holds, never a guess; a step on a piece not in that load refused; a batch with no due date never alerts; a hold always has its entry (D4.4; the sweep repairs) | a shop's label only (no number, no address); never a call, an order or a message | ₹0 |
| C · Styling | no calendar or not "Allow" → manual plans only, said in Settings; no weather → the assumption shown; no complete look → the gap and a next action; a cancelled event → a draft, no alert; a rules file that fails its check → the part is "setup failed" and the others run | titles never stored, sent or logged; only the chosen calendar and fields; alerts in fixed words | ₹0 (one Calendar read an hour, two Open-Meteo calls a day) |
| D · Phone and panel | a model file that fails to load or its self-check → "not installed", taps and scans still work; a slow phone → the live look slows itself; no camera → "Choose a photo"; unsent scans → "keep this page open" | two named pixel panels and their static rules; person and face check before anything is kept or sent; crops only; the door counts every picture; private pieces count-only outside the tab | ₹0 (≈ 13 MB of model files to the phone once) |

## Cost (₹ a month; no new paid service, secret or Scheduler job)

| Item | ₹ |
|---|---|
| Firestore storage (≈ 15–20 MB in the first year, inside the free 1 GiB) | 0 |
| Firestore reads and writes (`outfit_clock` ≈ 600–900 reads a day per owner across 288 runs, plus panels and scans: ≈ 1,000–1,500 reads and ≈ 100–200 writes a day, inside the free 50,000 / 20,000) | 0 |
| Google Calendar reads (≤ 24 a day) and Open-Meteo (≈ 2 calls a day) | 0 |
| Cloud Run egress (fingerprints ≈ 0.3 MB a scan session at 150 pieces, thumbnails ≈ 35 KB each) | measured in the pilot; expected inside the free allowance |
| R14's daily backups, when he has switched them on (≈ ₹3.8 per 100 MB a month) | ≈ 0.6–0.8 |
| Optional AI tagging (off by default; Haiku 5.5 ≈ ₹0.01, Sonnet 5.5 ≈ ₹0.26 a photo; at ₹95.24 a dollar) | 0 unless used; at most 30 |
| Printing a QR sheet (his paper) and, later, washable labels (his choice) | outside JARVIS |

## The I0 seam list (branch `r13-i0`; the integrator owns these files)

1. **Version** `13.0.0` (`__init__.py`; the four pins of fact 1).
2. **Alert kinds** +4 (D19): `alerts.py` `R13_ALERT_KINDS`, `notify/ports.py` `DEFAULT_URGENCY`,
   `notify/policy.py` `DAYTIME_RING_KINDS` (+3), `notify/held.py` (+4 words, as R14 gave its info
   kinds), `console-alerts.js` `KINDS` (+4 rows), `webpush/service.py` `TARGETS` (+4 → `helpers`),
   `buildbook/plain.py` `ALERT_WORDS` (+4); the pins 52 → **56** in the six tests of fact 13, the exact
   `DAYTIME_RING_KINDS` (`test_r51_seams.py:45`) and `TARGETS` (`test_r7_a_push.py:43`).
3. **Keyring** +2 → **24** (`keyring.py`; `test_r7_seams.py:294`, `test_r11_seams.py:166`,
   `test_r14_seams.py:258` (the last purpose becomes `wardrobe_photos`) and `:259`, the set in
   `test_r3_seams.py:850`).
4. **Permissions** +3 rows → **52** (D18; the six pins of fact 9), save cap 51 → **54**
   (`permissions/models.py:133`; its pin `test_r3_seams.py:951–953`: 54 pass, 55 fail);
   `tests/test_permissions_policy.py` `EXPECTED` / `RISK_OF` / `TOOL_OF` for the 18 tools; the nouns
   (wardrobe, piece, laundry, outfit, plan, label) join `TOOL_NOUNS` (`tests/test_r11_1_b_guard.py`).
5. **Undo**: kind `wardrobe_item` in `undo/models.py` (`Kind`, `KINDS`, `KIND_WORDS`, `IN_PLACE_KINDS`,
   `PASSKEY_PURGE_KINDS`), `console-deleted.js:25–26` ("Wardrobe piece"), the registration through
   R13's wiring into `api/personal.py` `register_undo`.
6. **Telegram**: `PERSONAL_PATTERNS` += `wardrobe_*`, `laundry_*`, `outfit_*`, `wear_*`; the refusal
   names the wardrobe; `test_telegram_tool_guard.py` `linked_gateway` gains `r13=`.
7. **Guardrails**: `NO_BULK_TOOLS` += `wardrobe_merge`, `wardrobe_retire` (`core/guardrails.py:69`).
8. **Settings** (`config.py`, ≈ 14 lines, stays < 800): `wardrobe_enabled` (on), `wardrobe_max_pieces`
   400 (50–500), `wardrobe_index_max_kb` 900 (fixed upper bound 950), `wardrobe_stale_days` 14 (3–90),
   `wardrobe_plan_evening` "20:00", `wardrobe_change_window_h` 36 (6–72),
   `wardrobe_calendar_refresh_min` 60 (15–360), `wardrobe_photo_side` 512 (256–512),
   `wardrobe_photo_max_kb` 200 (50–400), `wardrobe_photos_per_piece` 3 (1–3),
   `wardrobe_ai_tag_month_inr` 30 (0–200; 0 = never), `wardrobe_review_keep_days` 30,
   `wardrobe_backup_max_mb` 25 (5–30), `wardrobe_wear_close` "04:00". His own choices (calendar,
   fields, AI tagging on/off, auto-swap, private display) live in his sealed index.
9. **The contract** `wardrobe/ports.py`: `WardrobePart` (tools, clock jobs, daily jobs, privacy data,
   observers, services, ready word), `WardrobeContext` (settings, docs, keyring, audit, **`now()` (UTC)**,
   `zone(uid)`, a late `state(name)`, the notifier, the governed reads (`BackgroundReads`), R11's
   `OutsideStore` (late), the store port), `PARTS` (`catalog`, `laundry`, `styling`, `phone`),
   `TOOL_FAMILIES`, `ROUTE_PREFIX`, `COLLECTIONS` (the data model), `JOB_OWNER` (`wardrobe_sweep` A
   daily, `laundry_daily` B daily, `outfit_clock` C 5-minute), `SERVICE_OWNER` (`store` A, `review_writer`
   B, `refresh` C, `phrases` D), `KIND_OWNER`, and the Protocols `WardrobeStore` (`view`, `transact(uid,
   fn)` with `fn(view, tx) -> Commit(events, extra)`, `correct`), `Commit`, `ReviewNeeded`,
   `ChangeObserver`, `PhotoVault`, `WardrobeData` (count, export, delete). Plus `wardrobe/model.py`
   (D2), `wardrobe/states.py` (D3), `wardrobe/redact.py` (D10), `wardrobe/http.py` (the HTTP contract),
   the stub parts `wardrobe/{catalog,laundry,styling,phone}/part.py` ("not built yet"), and
   `tests/test_r13_fold_conformance.py` (D4.4) run against `tests/r13_fakes.py`'s store now and A's
   store from A on.
10. **Wiring**: `api/r13_wiring.py` (`wire_r13` after R14's parts and before the gateway, the contract
    check, `r13_tools`, `r13_tick_jobs`, `r13_clock_jobs`, `r13_privacy_sources`, `BODY_CAPS`,
    `install_r13_routes` with `GET /v1/r13`, `install_r13_phrases` (first), the observers and B's review
    writer joined to A's store, the bin's `wardrobe_item` restorer and purger); `api/tick_wiring.py` (+
    R13's daily and clock jobs); `home/watchdog.py:82` `ADVISORY_JOBS` += `outfit_clock`; `api/app.py`
    **+5 lines** (the import, `await r13.wire_r13(…)`, `r13=` to `build_gateway`, the routes,
    `**r13.BODY_CAPS`) → **732 ≤ 735**; `tools/setup.py` (`r13=`); `api/personal.py` (the
    `r13_privacy_sources` slot before home's); `offline/mode.py` (`add_phrases(routers, *, first: bool =
    False)`); `offline/phrases_r14.py` (`WITHOUT_AI` +1).
11. **The vision contract**: `vision/results.py` adds `WARDROBE_TASKS = ("embed", "colour", "person",
    "face")` and their schemas (embed: `{v: base64 ≤ 1,708, dims: 1280, model}`; colour: `{name, second?,
    share}` from the 18 names; person / face: `{found, count ≤ 20, boxes}`); the `Result` model accepts
    both lists; **`TASKS` stays the five** (the kept-results enum and its pin): a wardrobe result is
    never a kept vision result. `vision/assets.py` gains `WARDROBE_RELEASE`, `WARDROBE_FILES` and
    `installed()` over both (D8). The `PANELS` allow-list and its static test (D9).
12. **Console** (each file stays ≤ 800): `console-helpers.js` (+ the `wardrobe` tab and its import, +2
    lines), `console-camera-panel.js` (a fourth sub-tab whose pane a module mounts through
    `window.JarvisCameraModes.register('wardrobe', {mount, stop})`, ≤ 15 lines), `console-r7.js` (+
    `console-wardrobe-scan.js` and `console-wardrobe.css`), `console-r7-send.js` (+ `wardrobe(blob,
    meta)` and `tag(blob, meta)` through `prepared()`'s rules, ≤ 30 lines), `api/console.py`
    `APP_ASSETS` (+ the new files, stubs at I0), `tests/test_r51_console_assets_linked.py`
    `NOT_IN_PAGE` (+ the four files loaded by other code); `console.html` **unchanged (782)**; the dock
    stays 22; `helpers/kinds.py` `TABS` unchanged.
13. **Skill register**: the two groups, words, `no_ai`, `planned` (D18); `test_r14_skill_coverage.py`
    passes with the stubs.
14. **Guide and book**: C69–C71 PLANNED (every collection), the L5 row, edition line, change log;
    `scripts/arch_coverage.json`; build book `layers.py` (`wardrobe` → L5).
15. **Evals and fakes**: `evals/r13/run.py` (R14's shape) with **a staged gate**: until I1 an unbuilt part
    reports `not_built_yet` and passes (the R7 and R11 runners' rule before their I1s), so `make
    eval-mock` stays green on every branch; I1 flips `STUBS_PASS = False` (R14's rule, `evals/r14/run.py:28–33`),
    and `tests/test_r13_seams.py` pins the flip from I1 on. Stubs `catalog`, `laundry`, `styling`,
    `phone`, `e2e`, `needles`, and I0's built `contract`; gated in `evals/run_all_mock.py` as `("r13
    (gated)", […, "evals/r13/run.py", "--mock"], True)` after R14's line; `tests/r13_fakes.py` (the pilot
    set as fixtures, an in-memory `WardrobeStore` that passes the conformance test, IST clocks);
    `tests/r13_fake_server.py`; `tests/test_r13_seams.py`, `tests/test_r13_wiring.py`.
16. `docs/plans/r13-integration/BRIEF-COMMON.md` (R14's rules plus: every test takes a clock; a sentence
    with a day is asserted whole from that clock; no real clock under `wardrobe/`) and `I0-NOTES.md`.

## Part split (four builders; worktrees; branches `r13-a` … `r13-d` from `r13-i0`; disjoint files)

Each part plugs in through `build(ctx: WardrobeContext) -> WardrobePart` in its `part.py`;
`api/r13_wiring.py` leaves out a part that breaks the contract. B and C build against I0's in-memory
store (which passes the same conformance test as A's); I1 swaps in A's. D builds against
`tests/r13_fake_server.py`.

- **A · Catalog and the ledger** (INV-01–17, OPS-03, OPS-06). `wardrobe/catalog/{part,store,fold,
  service,search,counts,places,labels,photos,fingerprints,tagging,backup,restore,merge,undo,data,pilot,
  tools,jobs}.py` (`tagging.py` calls `BrainEyes`), `api/wardrobe.py`, `tests/test_r13_a_*.py`,
  `tests/r13_fakes_a.py`, `evals/r13/catalog.py`, INTEGRATION-A.md. `security-reviewer` required
  (photos, the backup seal and restore, the tag call).
- **B · Laundry** (LND-01–08, LND-10–15, OPS-02). `wardrobe/laundry/{part,flows,review,writer,holds,
  loads,providers,blind,history,store,texts,tools,jobs}.py` (`writer.py` adds review entries and load
  changes inside A's commit), `api/laundry.py`, `tests/test_r13_b_*.py`, `tests/r13_fakes_b.py`,
  `evals/r13/laundry.py`, INTEGRATION-B.md.
- **C · Styling** (STY-01–17, LND-16, OPS-04). `wardrobe/styling/{part,rules.json,rules,engine,plans,
  reserve,refresh,calendar,outlook,wear,prefs,texts,tools,jobs}.py`, `api/outfits.py`,
  `tests/test_r13_c_*.py`, `tests/r13_fakes_c.py`, `evals/r13/styling.py`, INTEGRATION-C.md. No R11
  file (D14).
- **D · Phone and panel** (OPS-01, the UI of all parts, the Privacy rows, Telegram tests and the No-AI
  sentences). `wardrobe/phone/{part,privacy}.py`, `offline/phrases_r13.py`, `console-helpers-wardrobe.js`,
  `console-wardrobe-pieces.js`, `console-wardrobe-scan.js`, `console-wardrobe.css` (≤ 200), the Part B
  section of `console-vision.js` (the four tasks and the shared ORT settings, before `sealRegistry()`;
  the I0 core's hash unchanged), `tests/test_r7_b_console.py` and `tests/test_r7_b_dom.py` (the
  nine-task pins and `BASE13`, with a line in INTEGRATION-D), `static/vendor/vision/r13-1/**`,
  `scripts/wardrobe_assets.py`, `buildbook/gen/libs.py` (the licences), `tests/test_r13_d_*.py`,
  `tests/browser/test_r13_d_*.py`, `tests/fixtures/r13/**`, `evals/r13/phone.py`, INTEGRATION-D.md.
  `security-reviewer` required (the door, the scan module, the redaction views).
- **All parts**: test first; functions ≤ 50 lines, modules ≤ 400, files ≤ 800; only the planned
  collections, job names, kinds, routes (`wardrobe/http.py`) and tool names; alerts only through the
  notifier with fixed templates; never a wiring file (only I0 and I1 touch them).

## Tests and evals (mock; each control must make its suite fail)

**Every acceptance check of the 54 is a named test** (paraphrased from the workbook; the test file is the
part's):

| ID | Test (what must hold) |
|---|---|
| INV-01 | a belt put in "Drawer 2" is found there by `wardrobe_find("belt")` |
| INV-02 | scanning a shirt rack and the accessory tray gives the catalog plus a separate list of unresolved scans; places without a baseline scan are listed |
| INV-03 | a belt and a watch in one photo become two records; a piece hidden under the belt is a later scan, never a guess |
| INV-04 | two shirts, a vest, underpants, socks, shoes, a belt and a watch are each found under their category; a type change keeps the id; a change into a private-by-default type asks |
| INV-05 | a new kurta gets one id; scanning it again (candidate offered, his tap) leaves the owned count unchanged |
| INV-06 | one patterned shirt keeps its id across front, back and folded fingerprints (fixture vectors; the real model in D's Node test) |
| INV-07 | two identical black vests get two ids; only the copy whose label was read enters laundry; a QR that is not his label is ignored |
| INV-08 | 20 frames of one shirt make one piece and one registration event |
| INV-09 | "blue striped shirt" finds the right piece once its colour and pattern are verified; a suggestion never overwrites a locked attribute |
| INV-10 | an unclear wash symbol stays unverified; the typed instruction is kept as verified; raw OCR text is never stored and an unverified field never reaches the model |
| INV-11 | two shoes count as two pieces and one wearable pair only while both are ready |
| INV-12 | a kurta and its bottoms are two pieces and one set; the set is unavailable when the bottoms go to laundry, and says whether the kurta can go alone |
| INV-13 | a watch moved from the tray to the travel bag (also by "I put my watch in the travel bag" with the AI off) shows the bag; an unobserved move shows "last known" |
| INV-14 | one missing sock leaves the owned sock count unchanged and reduces complete pairs by one; laundry stays in owned totals; scope covered is shown |
| INV-15 | "where is my black belt" returns its drawer and its state; two black belts are told apart by place or label; no match → Things' answer |
| INV-16 | merging two records of one watch (a card) leaves one active id with a continuous history; confirmed separate copies stay two |
| INV-17 | an archived belt (a card) drops out of active counts; restoring it reuses the id and asks for its condition |
| LND-01 | the navy shirt stays owned but leaves ready pieces and the next suggestions when its deposit is logged |
| LND-02 | a "To laundry" scan of a clean shirt that he cancels leaves it Ready; a `camera` event without a release goes to review |
| LND-03 | a jacket hiding a shirt: one verified deposit plus a pending deposit with no piece id |
| LND-04 | when either of two near-identical shirts could be dirty, both are withheld until he says which; "no deposit" clears to the last verified state |
| LND-05 | correcting an old basket event never overwrites a later clean return |
| LND-06 | a shirt taken from the hamper to the sorting table stays unavailable |
| LND-07 | a mixed load moves its five confirmed pieces to Washing; the rest stay In laundry; the load and the states change in one commit |
| LND-08 | three of five moved to drying change only those three |
| LND-10 | a damp shirt and one marked Needs pressing stay unavailable until their returns pass |
| LND-11 | the navy shirt returns with its original id and the same owned count, and reappears in suggestions |
| LND-12 | four of six returned restore four ids; two stay unavailable after the basket is empty |
| LND-13 | the clean left sock stays in inventory; the pair stays out until a ready matching half is recorded |
| LND-14 | two of three back from dry-cleaning: only those two can become ready; the batch is flagged short and, past its `due`, overdue |
| LND-15 | "where is my white shirt" shows Drying and its latest verified movement |
| LND-16 | a shirt due back tomorrow (`expected_back`) shows as an outstanding action while a ready shirt is offered for the meeting |
| OPS-02 | after a reported blind period, the pieces touched are verified before they appear in a ready plan |
| OPS-03 | an old basket event delivered after a confirmed clean return can't make the shirt dirty; a repeated event is applied once; a tap and a scan of one deposit make one change and no entry; 50 seeded permutations of one event set fold to the same state and marks; a phone 3 hours fast and a scan sent 20 minutes late fold in true order |
| OPS-06 | restoring a test backup keeps ids and pair links and duplicates nothing; the check writes nothing; a restore cut after chunk 2 and run again duplicates nothing; a 3 MB backup restores through the real app and its middleware; 31 MB is refused in words |
| OPS-01 | a frame with a person or a face keeps and sends nothing (no photo, fingerprint or tag) while a QR read still makes its event; a clean frame then a frame with a face saves nothing from the second; a saved photo holds only the box, and a 600-px photo is refused; Stop ends the camera before the next frame, and hiding the tab stops it |
| OPS-04 | switching the calendar off stops automatic plans from it; a laundry alert never names a private piece; only the chosen calendar id and fields are requested; a calendar id not in his list is refused |
| STY-01 | "what should I wear tomorrow" at 23:30 and 00:30 IST resolves to the next local day and shows the occasion |
| STY-02 | an important meeting on the chosen calendar makes a plan for the right date; an event missing from a later read covering it becomes a draft with no `outfit_ready`; an edited one refreshes |
| STY-03 | changing "Catch-up" to business formal gives a business-formal outfit; the calendar is not changed |
| STY-04 | a ready light-blue shirt, charcoal trousers and matching shoes, belt and watch make the meeting look |
| STY-05 | a Diwali plan uses his festive pieces and checks every part of the set |
| STY-06 | a delicate favourite he excluded stays out of the Holi options |
| STY-07 | a rainy outdoor plan offers his ready rain-ok shoes and outer layer and says the weather assumption; no place → "Weather unknown" |
| STY-08 | "no tight collars" filters the pieces tagged tight at the neck; the constraint that leaves no match is named |
| STY-09 | the meeting look lists shoes, belt and watch, and the private basics only in his view |
| STY-10 | a dirty belt or a pair missing a shoe never appears in a recommended or ready outfit |
| STY-11 | each look explains why and shows its actual piece ids |
| STY-12 | changing the shoes keeps the shirt, trousers and watch when still eligible |
| STY-13 | a meeting and an evening function get two plans with the pieces to change and the reuse said; after "I'm wearing it" the declared shared base stays eligible for the evening |
| STY-14 | reserved shoes appear for their event and make a conflict for a second plan at the same time |
| STY-15 | a white shirt dropped in the basket leaves tomorrow's active outfit and a ready alternative is shown; wearing the planned outfit sends nothing and marks nothing |
| STY-16 | "no ready formal shoes" is said when the only pair is out, with the eligible pieces apart |
| STY-17 | saving a plan changes no wear count; `wear_started` then `wear_done` count one wear; the sweep closes a forgotten wear at 04:00 local |

**The workbook's end-to-end tests** (`evals/r13/e2e.py` through the wired app on fakes, and
`tests/test_r13_i1_e2e.py`): **1** one shirt's whole life (register, suggest, wear start and done, deposit,
clean return: In use, then excluded, then eligible on its id; owned count constant); **2** two identical
vests (one label hidden → review; the label read → exactly that vest is dirty; the other available);
**3** unobserved movement in its phone form (a reported blind period over a planned garment → held; a
rescan resolves); **4** an incomplete pair and load (a pair into laundry; one piece back; the load marked
done by his tap, the phone form of the washer's "finished": only the dry returned piece is eligible
alone, the pair stays out, the other load pieces stay unavailable); **5** a meeting outfit update (approve
a formal outfit for tomorrow; one piece into laundry; the plan offers a substitute or is incomplete; the
checklist names the same ids; the avatar half is R13.1); **7** private items and photos (a look with
private layers: alerts, Telegram, Web Push, cards, the bin and the model's view show only approved
details; deleting all wardrobe photos leaves the catalog usable; the avatar half is R13.1); **8** pilot
measurements, from the events and the plan log (A's `GET /v1/wardrobe/pilot`, counts only):
- item-ID match rate = scans where his tap chose candidate 1 ÷ scans with a candidate;
- wrong status changes = corrections of state events;
- unavailable pieces suggested = suggested pieces not eligible at suggestion time;
- corrections per use = corrections ÷ events.

**Pass line (owner question 14's default): unavailable pieces suggested = 0, and wrong status changes ≤ 1
per 50 events**; the match rate is reported, not gated. Control: a recorded log with one planted bad
suggestion fails.

**Browser (Playwright, Chromium's fake camera).** `--use-fake-ui-for-media-stream
--use-fake-device-for-media-stream --use-file-for-fake-video-capture=tests/fixtures/r13/<clip>.y4m` (clips
the test draws: a striped shirt on a plain surface, two identical vests with one QR label, a belt and a
watch apart), the page clock pinned. Flows against `tests/r13_fake_server.py` while D builds, against
the wired app at I1: add a piece (chip, colour, "new"), rescan ("seen before" → same id), to laundry, back
clean, a QR label read, wearing it and done, the person / face refusal (the test hook forces a detection;
it can only refuse), the crop's size, the door's counter, "Checking…", unsent scans, the wake word and a
wardrobe task in one page, the Wardrobe tab's sections at 360 × 800 and 1280 × 800, and the existing tabs'
screenshots against R14's. D's Node test runs the real models on the vendored runtime with the
manifest's self-check references, and one drawn shirt's fingerprint under rotation and folding (INV-06's
real half). Whether a drawn face fires UltraFace is checked first; if none does, the face task's
decoding is tested on recorded model outputs and the real face check moves to the pilot (INTEGRATION-D
says so).

**Static tests (I0 and D)**: the `PANELS` allow-list; the scan module's rules (D9); no real clock under
`wardrobe/`; the CSS rule (D1); `console.html` byte-identical; the I0 core's hash; the door is the only
caller of `/v1/wardrobe/photos` and `/tag`.

**Needles** (`evals/r13/needles.py`, I1): one simulated week of the four parts on the fakes; needle
classes: a private piece's label and colour, his free-text labels, a calendar title, a laundry shop's
label, a planted phone number, raw OCR text, a foreign QR payload, photo bytes (raw and base64), a
fingerprint, the backup's plaintext; each searched raw, lower-cased, URL-encoded, hex and base64 in every
R13 document write (beyond its sealed blob), every log record, the audit detail, alerts, Telegram text,
Web Push payloads, the `approvals`, `deleted_items`, `activity` and session-turn stores, and every tool
result for the model; a positive control per sink; the one allowed place is D10's (a card's stored
arguments from a `query`). **Control**: `redact.py`'s model view swapped for the panel view → exactly the
private-label cases in tool results fail.

| Suite | Cases (examples) | Control that must fail it |
|---|---|---|
| `contract` (I0, built) | every part builds through the real wiring and owns only its tools, jobs, services and routes | the contract check off: a stray tool is accepted |
| `catalog` (A) | INV-01–17, OPS-03, OPS-06 | candidates off (every scan is new): INV-05 fails; the dedup off: INV-08 and OPS-03 fail |
| `laundry` (B) | LND-01–15, OPS-02 | holds off: LND-03, LND-04 and OPS-02 fail |
| `styling` (C) | STY-01–17, LND-16, OPS-04 | the availability check off: STY-10, STY-15, STY-16 fail; the wear rule off: STY-13 and STY-15's "sends nothing" fail |
| `phone` (D) | D20's sentences with zero provider calls and R14's phrases unchanged; D10's views; OPS-01's refusals | the person check off: OPS-01 fails |
| `e2e` (I1) | the seven workbook tests, 8 with its pass line | the fold in arrival order: tests 1 and 3 fail; a planted bad suggestion: 8 fails |
| `needles` (I1) | above | above |

## Size guards

`api/app.py` ≤ 735 (727 + 5 = 732), `tools/gateway.py` 760 unchanged (no edit), `core/brain.py` ≤ 741 (713,
no edit), `console.html` ≤ 782 (782, no edit), every `console*.js` ≤ 800 (the biggest edits:
`console-camera-panel.js` 468 → ≤ 483, `console-alerts.js` 462 → 466, `console-helpers.js` 236 → 238,
`console-r7-send.js` 100 → ≤ 130; the new wardrobe files ≤ 600 each), new CSS ≤ 300 in all
(`console-wardrobe.css` ≤ 200), `config.py` < 800 (≈ 743), every new Python module ≤ 400. I0's
`test_r13_seams.py` pins each.

## Risks and known limits

- **"Seen before?" on near-identical pieces**: ImageNet features tell colours and patterns apart, not two
  copies of one vest. Mitigation: candidates only, his tap decides, QR labels for copies, both held when
  unsure, centred scores. The pilot measures the match rate.
- **The person and face checks are detectors, not a guarantee**: SSD misses some partial bodies and
  UltraFace some angled faces; a printed face on a T-shirt is refused (he saves it without a photo).
  Either detection refuses everything kept or sent from that frame; photos are cropped, sealed and his
  alone; the summary and C63 say it can miss.
- **Phone speed and memory**: three ONNX sessions, tesseract and zxing on one page; loaded on first use,
  released on `pagehide`; ≈ 0.9–1.7 s for a save on a phone (estimate); the self-check catches a model
  that runs wrongly.
- **Device clocks**: corrected by `sent` (D4.1); a scan not sent within 24 hours, or left unsent when the
  page closes, is lost (said on screen).
- **The index's size**: the byte guard refuses before Firestore's 1 MiB; a later release shards it.
- **Calendar titles are other people's words**: read in memory for keywords only, never stored, sent or
  logged; shown fenced in his panel.
- **A card from a spoken or No-AI `query`** keeps his words in the approvals store (D10), like Things.
- **Alert noise**: four kinds, once-only claims, a 2-hour gap for changes, wearing never alerts.
- **Repository size**: ≈ 13.2 MB of model files (+ 8.8 MB if the fp32 fallback is needed); R7 added ≈ 23 MB.
- **Training data terms** (ImageNet, WIDER FACE, COCO) bind the data, not the zoo's licensed weights (D8).
- **Pins churn**: 6 alert, 4 keyring, 7 permission (with the cap's) and 4 version pins move at I0; the
  persona's 21 at I1.
- **2 CPUs here**: targeted tests only while building; whole suites queue (the side-by-side Build Book
  work shares the machine).
- **Date bombs**: `ctx.now()`, the static test, the page clock and the clock sweep before the PR.

## Needs the owner (safe defaults; none blocks the build)

1. **Where the Wardrobe lives**: a tab in Helpers and a tab in Camera (default); a dock button of its own
   would cost console lines (later).
2. **Private by default**: underpants, briefs, boxers, vests, undershirts, thermals (default); socks not
   private. Change any piece in its settings.
3. **Outfits from a calendar**: none until you pick one; then title on, location off, description and
   guests never (default).
4. **The evening reminder**: 20:00 the evening before an event on that calendar (default), or off.
5. **Auto-swap** when a planned piece goes to the laundry: off; JARVIS suggests and you tap (default).
6. **Rewear**: trousers, jeans, outerwear, belts, shoes and the watch are worn again; shirts, T-shirts,
   vests, underwear and socks go to the laundry after a wear; a wear you started and didn't close is
   closed at 04:00 the next morning by that rule (default).
7. **Holi**: only pieces you mark "okay to stain" (default).
8. **Photos**: one front photo a piece (back and detail optional), 512 px, kept until the piece is removed
   or made private (default); never for private pieces.
9. **QR labels**: print a sheet of 24 (default); washable fabric labels are a purchase for later.
10. **AI tagging**: off (default); when on, only for saved pieces that aren't private, at most ₹30 a month.
11. **"Needs a quick check"** after 14 days without a scan of a planned piece (default).
12. **The wardrobe backup file**: sealed to this JARVIS, up to 25 MB, photos left out unless you tick them
    (default).
13. **The tracker**: the 80 use cases as their own rows, replacing rows 169–174 (the proposal's default),
    or "keep the 6 rows".
14. **The pilot**: 20–30 pieces including a watch, a belt, shoes, two near-identical vests and a few
    socks; it passes when no unavailable piece is ever suggested and at most 1 status change in 50 is
    wrong (default).

## Exit check (before the PR)

1. **The pilot** on his phone: 20–30 pieces as above; the e2e 8 counts, the pass line and the bands D7
   ends up using are written into `docs/plans/r13-integration/I1-NOTES.md`.
2. **The workbook's end-to-end tests** 1–5, 7 and 8 pass (`evals/r13/e2e.py`; the runner's gate flipped
   at I1, every built part's control failing it).
3. **The full browser suite** once, on the joined branch (≈ 75 minutes; queued, never beside another whole
   suite).
4. **Screenshots looked at**: the Wardrobe tab and Camera → Wardrobe at phone and laptop sizes, and the
   unchanged existing tabs against R14's.
5. **The clock sweep**: the whole unit suite once with the clock moved forward (`time-machine` in a
   ten-line plugin outside the repo) to two days after the PR's date, 09:00 IST, and the R13 files also at
   20 Dec 2026, 1 Jan 2027 00:30 IST, 1 Mar 2027 and 29 Feb 2028; no date bomb.
6. `ruff check`, `ruff format --check`, `mypy src` (the baseline only), `evals/run_all_mock.py` ALL PASS,
   `scripts/check_doc_versions.py`, `scripts/arch_coverage.py`, the coverage floor (95),
   `python -m jarvis.buildbook.gen --check`, the PR title check.

## What can't be verified from this workspace

The models on his phone's browser (speed, memory, a quantized operator: the self-check reports it);
UltraFace on a real face and SSD on a real partial body (the pilot); his Google calendars and Google's
`fields` behaviour on `events.list` and `calendarList.list` (read from Google's reference, not called
here); Open-Meteo's tomorrow values for his place; the real match rates; Firestore's real sizes; Cloud
Run's egress for `asia-south1`; Telegram and Web Push delivery.

## Plan review 1 — how each finding was handled

| ID | Change | Where in the plan |
|---|---|---|
| H1 | `wear_started` / `wear_done`; In use eligible for a declared shared plan the same day; wearing for its own plan or a hand-off is no change and sends no `outfit_changed`; D20 two rows; the sweep closes a forgotten wear; tests for STY-13, STY-15, STY-17, e2e 1 | D3, D12, D19, D20, settings (`wardrobe_wear_close`), tests |
| H2 | Tagging only for a saved non-private piece (the server refuses from the record), after the check on the same bitmap, the month-to-date ₹ counter in the sealed index, `BrainEyes.look()` reused; tests | D7, D9, Per part, tests |
| H3 | Restore body cap from `r13_wiring` (`app.py` +1 → 732), 25 MB (5–30), streamed download, `read_capped`, check-then-confirm with a token, chunks of ≤ 50 pieces, idempotent, the attribute rule, purged pieces only if ticked; tests | D17, fact 19, seams 8 and 10, Size guards, data model (`wardrobe_restore`), tests |
| H4 | `transact(uid, fn)` with `fn(view, tx) -> Commit(events, extra)`; a hold and its entry in one commit; `due` and `expected_back`; the sweep repairs; one conformance test for the fake and A's store | D2, D4.4, D11, seam 9, Part split |
| H5 | `wardrobe/http.py` and `tests/r13_fake_server.py` at I0; route tests assert the models | "The HTTP contract", seams 9 and 15, Part split |
| H6 | `PANELS` allow-list and its static test; the camera panel's rules for the scan module; C63's new words; R7 INTEGRATION-B line | D9, fact 4, seam 11, static tests |
| M1 | One clock rule: `at` + (`server_now` − `sent`), 24 hours, unsent scans in memory and said; Risks fixed | D4.1, Risks, OPS-03 test |
| M2 | A pure, order-independent fold; marks computed, never written; 50 permutations; a stated day is 12:00 local | D4.1, D4.3, OPS-03 test |
| M3 | `duplicate` events; a conflict holds nothing by itself; `rev_seen` and "already done" | D4.2, D4.3, OPS-03 test |
| M4 | The bin's fixed title; cards' words from `preview` through `redact.py`; write tools take ids (the `query` exception named); private later deletes photos; needles sinks added | D9, D10, D16, needles |
| M5 | Parsed label fields only, unverified never to the model; QR only `jw1:` + 8 of his codes; trust rule for the 18 tools | D7, D18, INV-07 and INV-10 tests |
| M6 | R13's routers also take the PUT form, refuse possessives and Things-typical words; Things answers when the wardrobe has none (two gateway calls); R14's phrase tests still pass | D6, D20, D21, INV-13 and INV-15 tests |
| M7 | `vision/assets.py` learns `r13-1` at I0; D owns the folder and test edits; one ORT `env` with the wake word's values, tested together; `console-wakeword.js` untouched | D8, seam 11, browser tests |
| M8 | `embed` is always uint8 with its model name; other models' fingerprints never compared, recomputed from photos; load-time self-checks; the cut method stated (extract_model refuses here) and committed; the fp32 cut's sum | models section, D7, D8 |
| M9 | The 900 KB byte guard, short keys, a 600 maximal-piece test; the cap 400 by default | D2, seam 8 |
| M10 | `WardrobeContext.now()`, a static test on the real clock, the page clock | D15, seam 9, static tests |
| M11 | A staged gate (stubs pass until I1, the flip pinned); e2e 8's formulas, pass line and control; INV-05's control is "candidates off" | seam 15, tests, owner question 14 |
| M12 | Every calendar read through `BackgroundReads`; cancelled events by absence; calendar ids only from his list | D13, STY-02 and OPS-04 tests |
| M13 | The check gates what is kept or sent, not id-only events; one bitmap; the server's 512 px from SOF; "Choose a photo" checked | D9, OPS-01 test |
| M14 | The summary carries the detector's limits and "the same look"; C63 and the privacy row change in the saving commit, pinned | Summary 6 and 9, D9 |
| M15 | SSD: MIT (zoo) + Apache-2.0 (TensorFlow weights), both texts; UltraFace's MIT from Linzaer at a pinned commit | models section, D8 |
| L1 | The cap pin `test_r3_seams.py:951–953`; `NOT_IN_PAGE`; `helpers/kinds.py` `TABS` stays five (console-only tab); `planned` emptied at I1; one `add_phrases` signature | seams 4, 10, 12, 13; D1; D18 |
| L2 | Reads ≈ 1,000–1,500 a day; egress measured in the pilot | Cost |
| L3 | **Not taken**: a tab hint needs R7's launch-word module; the push lands on Helpers' last tab and the alert names the tab | D1, D22 |
| L4 | No R11 document changes (rollback-safe): C keeps tomorrow in `wardrobe_outlook`, reading R11's place late; Helpers off → "Weather unknown" | D14, data model, Part C |
| L5 | `labels.svg`: numbers and codes only, its headers, the alphabet | D2, D7 |
| L6 | Panel buttons through `gateway.execute`; `record_change` for settings | D1, D16, HTTP contract |
| L7 | "Checking…"; "the first time you save a photo (about 13 MB)" | D9, Summary 8 |
| L8 | A restored bin entry lands in "Missing or in review"; a merge's undo only drops the link | D16 |
| L9 | A key change makes older backup files unreadable; the button says so | D17 |
| L10 | Fingerprints centred by his mean; raw and centred scores recorded in the pilot | D7 |

## Sources (read 15 Nov 2026)

| # | Source |
|---|---|
| S1 | The owner's wardrobe workbook: sheets "Use Cases" (80), "Wardrobe Rules" (checkpoints, item status, categories and counting), "Build and Test" (build order, end-to-end tests 1–8) |
| S2 | The approved proposal "What goes in this build: wardrobe (R13) and the Build Book rebuild" v1.1 (15 Nov 2026), section 2 |
| S3 | ONNX Model Zoo, commit `c5cae0f1942c8d7727372c7b1f6b485aa39e4421`: MobileNet, UltraFace and SSD-MobileNetV1 model pages and their Git LFS pointers — https://github.com/onnx/models |
| S4 | UltraFace upstream `LICENSE` (MIT) at `dffdddda9794a50607cba8f318507a28c1c27cab` — https://github.com/Linzaer/Ultra-Light-Fast-Generic-Face-Detector-1MB ; TensorFlow models `LICENSE` (Apache-2.0 for `/research`) at `19f287775ae950e22a9b5fb82727e72cff2e3664` — https://github.com/tensorflow/models |
| S5 | onnxruntime-web 1.30.0 as vendored (`static/vendor/ort/MANIFEST.txt`) |
| S6 | Open-Meteo forecast API terms as recorded in R11 (`docs/plans/r11-free-helpers.md`, "External sources") |
| S7 | Google Calendar API v3 `calendarList.list` and `events.list` (`fields`, `singleEvents`, `showDeleted`) — https://developers.google.com/workspace/calendar/api/v3/reference |
| S8 | Cloud Run quotas and limits (request and response sizes) — https://docs.cloud.google.com/run/quotas |
| S9 | Plan review 1 — `docs/plans/r13-integration/PLAN-REVIEW-1.md` |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 16:42 IST | R13 | First edition, from the code at `9a8392b`: the owner's summary with ₹, the 54 use cases mapped to four parts and all 80 IDs placed (R13, R13.1, Later, Declined), code facts with file:line, the three model files downloaded, hash-checked and run on the vendored runtime, D0–D22, the data model, 18 tools, the I0 seam list, the part split with OPS-03 to A and LND-16 to C, a test per acceptance check, the end-to-end, browser and needles suites with controls, size guards, risks, owner questions, the exit check | 🛠 Mark XXI |
| v13.0.2 | 15 Nov 2026, 17:28 IST | R13 | Plan review 1 written in (H1–H6, M1–M15, L1–L10 but L3, which is declined with its reason); Status Ready. The wear lifecycle and the hand-off between events (H1); AI tagging gated by the piece record, the same bitmap's check, a named ₹ counter and `BrainEyes` (H2); the restore's body cap, 25 MB, streaming, check-then-confirm and chunked idempotent writes, `app.py` 732 (H3); the `transact` contract with holds and their entries in one commit and one conformance test (H4); the HTTP contract and a fake server at I0 (H5); R7's pixel guard widened in the open with a `PANELS` list and C63's new words (H6); one clock rule, a pure fold, duplicates, the private-data sinks, parsed labels and QR codes, the trust rule, Things and wardrobe routing, `vision/assets.py`, uint8 fingerprints with self-checks and the fp32 cut's sum, the byte guard and a 400 cap, `ctx.now()`, the staged eval gate and e2e 8's pass line, calendar reads and cancelled events, the check gating only what is kept or sent, the summary's limits, SSD's Apache-2.0 upstream (M1–M15); tomorrow's weather in C's own document, no R11 file edited (L4); a "Plan review 1" table | 🛠 Mark XXI |
| v13.0.3 | 16 Nov 2026, 23:30 IST | R13 | I1: the owner's decision that a declined calendar event still gets its outfit plan (D13); `wardrobe_max_pieces` 50 to 500 (D1's list: maximal pieces fit only to 500); the Wardrobe Privacy section has five rows (Outfit plans on its own, so a key change costs plans only); persona p13.0 as built | 🛠 Mark XXI |
