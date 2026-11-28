Version v8.0.4 · 28 Nov 2026, 05:35 IST · Release R8 · Status: Current · Owner: 🛠 Mark XXVI

# R8 and R8.1 — Vision core, your desk camera and your workout spot: the plan

**Releases:** R8 "Vision core & your desk camera" (`v8.0.0`, 14 rows) and R8.1 "Fitness coach at your workout spot" (`v8.1.0`, 20 rows). One plan, two pull requests: R8 first, R8.1 after R8 is merged.

**Order and approval:** the owner's order (17 Nov, reaffirmed 27 Nov) is calls → R5.2 → **R8 → R8.1** → R9; R18 and R5.2 are merged (PRs #44, #45). His rule "each vision release starts only after he confirms its cameras" is met: on 14 Nov he confirmed the external camera on the Windows laptop (the desk camera) and one phone on a tripod (the workout spot). **His answers of 28 Nov 2026, 04:24 and 04:33 IST (section 3) add the home camera he has ordered**, an **Imou Ranger S2** (3 MP, RTSP and ONVIF per its listing; delivery 3 Dec 2026), and everything is built for any RTSP/ONVIF camera: posture and every desk use case that needs the whole body look through it, with the vision running on the home laptop (D3). The laptop's webcam stays for the face-and-hands use cases. The approval stop is passed: the four mockups are approved (D2). His 04:33 ask adds **part I, "your bar, your way"** (D13): every item of the console's bar can be moved, removed to More and put back, and the bar itself hidden. Nothing is bought by JARVIS, and nothing costs money.

**Layers:** 1 (Camera panel panes, the phone's workout view), 2 (the vision engine: a new `hands` task, `digits`, the live driver; and on the home laptop, the home camera's pose runtime), 3 (the use-case registry, sessions, the tracking target), 5 (the coaches, posture and activity), 6 (the home bridge: the home vision plugin, ActivityWatch and the no-cloud camera check), 7 (kept tallies, sealed), 8 (spoken counts and tips, nudges). Cross-cutting: privacy, security, CI (the model fetch job), evals. **Skill:** Health & Wellbeing (ADR-20's 11th skill); row 184 and row 377 are Security Advisor. **Phase:** 5 (home + camera) with Phase 4's nudges and Phase 6's phone surface.

**Sources read for this plan (28 Nov 2026):** `/home/claude/notes/r8-scope.md` (the scope note, checked against the repository: section 12 lists what it got wrong); the Architecture Design Document, chapters 02–05, 08 (ADR-16, 19, 20, 26, 29, 35), 09, 10, 11 (R8 section and the 27 Nov hardware note) and 12 (kept privately); `docs/plans/r5-2-voice.md` and `docs/plans/r18-calls.md` (format); `docs/plans/r7-mobile.md` appendix A (the vision use cases and the tasks each needs); `docs/plans/r7-integration/INTEGRATION-B.md` (sections 3, 5 and **7a "For R8 (the live driver)"**); the code in `src/jarvis/api/static/console-vision.js`, `console-vision-r13.js`, `console-camera.js`, `console-camera-panel.js`, `console-r7-links.js`, `src/jarvis/vision/*`, `src/jarvis/camera/*`, `src/jarvis/homebridge/*`, `src/jarvis/home/ports.py`, `src/jarvis/helpers/nudges/*`, `src/jarvis/keyring.py`, `src/jarvis/vitals/own.py`, `scripts/vision_assets.py`, `src/jarvis/api/static/vendor/vision/*/MANIFEST.json`.

---

## 1. What you get (in plain words)

**At your desk (R8).** Two cameras become a quiet desk coach. The home camera you ordered watches the whole of you at the desk (the laptop's webcam sees only your face), and its pictures are looked at on the home laptop only; the laptop's webcam stays for the short face-and-hands sessions, inside a small window that stays on top of your other work. Each runs only when you switch it on.
- **Posture (home camera):** after a 10-second "sit up straight" calibration, JARVIS notices when you slouch or lean towards the screen for more than a minute and gives one gentle nudge (at most a few an hour). It checks about once a second, so the laptop stays cool.
- **Your day:** a strip showing when you were at your desk, away, on your phone or eating, and (if you install the free ActivityWatch app) how long you spent in each program. It appears in Camera → Desk and as one line in your morning brief.
- **Short sessions at the desk:** on the webcam, a hand-reaction game, a breathing pacer, a water counter that notices sips and logs glasses (with Undo), a hand-and-finger exercise game and a reach-and-grasp exercise with scores; on the home camera, a seated exercise coach that adapts to you and a checklist that helps you sit correctly for a blood-pressure reading. Hold the monitor up to the webcam and JARVIS reads its numbers for you to confirm (D7).
- **Camera setup:** each camera has a name, a spot and a room. You can switch off one camera, a whole room, or every camera at once ("Jarvis, cameras off"). Vitals shows whether each camera is working. A "Check a camera" button tells you whether a home camera you buy works with JARVIS and your laptop **with no cloud service**.

**At your workout spot (R8.1).** The phone on the tripod becomes a personal trainer, full screen, with big numbers you can read from 2–3 metres and JARVIS's voice calling counts and tips: rep and tempo counting, a warm-up checklist, form tips for common exercises (fixed rules, no AI), yoga and mobility holds, plank timing and alignment, a space-clear check before you start, single-leg balance, shadowboxing punches, an agility timer between marks you set, Pilates and tai-chi sequences, jump height and landing, dancing in sync with a routine you record, handstand holds (only with a wall or a spotter), kettlebell swings, assisted stretching with a partner (only your data is kept), a six-minute walk lap counter, a sit-to-stand test, and your eating pace and meal length at the table.

**Privacy.** By default JARVIS tracks everyone in view and **saves everyone's results** (his words: "Keep everything and save the results"). Say "Jarvis, track me" and it follows only you; "Jarvis, track Shruti" and it follows only Shruti, once her face is enrolled with her consent in Faces ("I don't know Shruti yet: enrol her face first" otherwise); "Jarvis, track everyone" goes back to all. A person JARVIS knows (you, and people enrolled with consent) has their results saved under their name; someone it doesn't know is saved as "Guest 1", "Guest 2" … for that session, and you can rename or merge a guest later. Every person and every guest has their own Privacy rows to view, export and delete; everything is sealed with JARVIS's keys. Nothing is recorded: no video, no photos, no clips, no body points: only counts, times and scores. None of this is medical advice: JARVIS never states a diagnosis or a medicine, and every session says "Stop if anything hurts".

**What it costs.** ₹0 a month. Everything runs on your laptop and phone, with no AI call and no new account or key.

**What you do (after each release is merged).** Allow the camera in Chrome on the laptop and on the phone, run a 2-minute setup test on each, and (optional) install ActivityWatch. When you buy a home camera, run "Check a camera" (section 10).

---

## 2. The rows and their acceptance tests

Each row's acceptance test is below. **The workbook's own "success check" wording is not in this repository** (the workbook is kept outside it: chapter 09); the checks below are written from each row's feature, the R7 appendix and the ADD. I0 copies the workbook's exact success-check text for each row into `docs/plans/r8-integration/ROWS.md` (new); where the workbook's figure is stricter, it wins. CI proves each test on synthetic Result sequences (section 8); the owner's 10-rep check on his own devices is the live proof.

### 2.1 R8 `v8.0.0` — vision core and the desk camera (14 rows)

| Row | Feature | Use case id (spot) | Tasks | Acceptance test |
|---|---|---|---|---|
| 216 | Vision engine on the device: browser, phone and home laptop | — (engine) | `pose`, `hands`, `objects`, `digits` | All are "installed" in `GET /v1/vision` once the models are pinned (D8); each loads only JARVIS-served, hash-checked files; the setup test reports frames a second and the share of one CPU core on the laptop browser and the phone. **The home-laptop leg is in R8 (D3, ADR-49):** the home vision plugin reads the home camera's RTSP sub-stream, runs pose on the laptop (full model if it keeps ≥ 15 frames a second, else lite: D4) and sends only views and tallies; a CI test proves no frame, point or box leaves it |
| 217 | Camera setup: each camera and spot, per-camera and per-room off switches, camera health | — (setup) | — | A camera or room switched off stops its looking on the same device within 2 s and on every other device within 60 s; Vitals shows each camera's last-seen time and frame rate; a switched-on camera unseen for 24 h is amber |
| 184 | Indoor-camera privacy controls | — (setup) | — | The "Camera on" chip shows exactly while a track is live (R7 test extended to the new panes); a room marked "never" can't be chosen for any coach; the R7 "no picture leaves" suite passes on every new module; Privacy lists every kept tally with export and delete |
| 377 | A home camera that works with JARVIS and the laptop with no cloud service | — (bridge probe) | — | Against a fake camera in CI: the check passes only when RTSP main and sub streams and ONVIF Profile S answer, H.264, **and** they still answer after the camera's internet is blocked and it is restarted; it fails in plain words naming the missing piece. Real proof after the purchase (owner step 7) |
| 181 | Posture checks from the camera | `posture` (desk, **home camera**) | `pose` at 1 fps (2 fps while a slouch is suspected), on the home laptop | On synthetic sequences: ≥ 90 % of 60-s slouch or forward-head spans give a nudge; ≤ 1 false nudge per synthetic hour of good posture; at most 3 nudges an hour; the desk coach's share of one laptop core ≤ 10 % |
| 182 | Activity timeline (desk, away, phone, eating) | `activity` (desk, **home camera**) | `pose`, `objects` (cell_phone, cup, bowl) at 1 fps, on the home laptop | A synthetic 8-hour day is labelled correctly for ≥ 90 % of its minutes; only kind, start and end are kept |
| 183 | Screen time via ActivityWatch | — (bridge adapter) | none | Against a fake ActivityWatch API: per-program minutes and active time exact; window titles never leave the laptop; with no ActivityWatch Vitals says "off until ActivityWatch is installed" |
| 224 | Gesture-controlled fitness reaction game | `reaction-game` (desk) | `hands` at 15 fps | On synthetic hand tracks: ≥ 95 % of target touches counted; reaction time within ±100 ms |
| 227 | Adaptive seated fitness movement coach | `seated` (desk, **home camera**) | `pose` (whole body), on the home laptop | Reps within ±1 per set of 10 for each seated move; the next set adapts (fewer reps after an unfinished set, more after two easy ones) |
| 238 | Visual breath-pacing companion | `breath` (desk) | `pose` (shoulders) | The pacer's timing is exact to 0.1 s at each rhythm offered; the breath-rate estimate is within ±1 breath a minute on synthetic shoulder motion between 6 and 20 a minute; it says it is not a medical measure |
| 248 | Water-intake logger at the desk | `water` (desk) | `hands`, `objects` (cup, bottle, wine_glass) | ≥ 90 % of synthetic drinking events counted, ≤ 1 false sip an hour; a glass is added to the existing water log (`log_water`) with Undo |
| 262 | Home blood-pressure measurement posture coach | `bp-posture` (desk, **home camera**); the reading on the webcam | `pose`, `objects` (dining_table, chair) on the home laptop; `digits` on the webcam | Each checklist item (back supported, feet flat, legs uncrossed, arm at heart level, 5 minutes' rest, still and quiet) judged right on ≥ 90 % of synthetic poses; **the monitor's seven-segment display read right** (systolic, diastolic, pulse) on ≥ 95 % of synthetic displays and never stored before he confirms or corrects it; a confirmed reading is sealed and shown with its trend and the published category **with its source named**, and "talk to your doctor" where that category says so; no diagnosis and no medicine ever (the not-medical test) (D7) |
| 268 | Hand and finger rehabilitation exercise game | `hand-rehab` (desk) | `hands` | Counts within ±1 per 10 for open-close, finger taps and thumb-to-finger; range of motion within ±10° on synthetic hands; "Stop if it hurts" shown before and during |
| 276 | Occupational-therapy reach-and-grasp task scoring | `reach-grasp` (desk) | `hands`, `objects` (cup) | Reach time within ±150 ms; the same sequence always gives the same score; scores are practice scores, never a clinical rating |

Row 125 ("Posture and movement nudges") is already Done (R11's stand-up nudge, `src/jarvis/helpers/nudges/standup.py`); its camera half is row 181.

### 2.2 R8.1 `v8.1.0` — the fitness coach at the workout spot (20 rows)

All on the tripod phone (Chrome or the R7 app), full screen, screen kept awake. Equipment is the owner's own.

| Row | Feature | Use case id | Tasks | Acceptance test |
|---|---|---|---|---|
| 132 | Workout rep counting (= HF-03 rep and tempo) | `reps` | `pose` | Reps within ±1 per set of 10 for squat, push-up, lunge, curl, shoulder press, jumping jack; tempo (down, up) within ±0.3 s |
| 218 | Dynamic warm-up exercise checklist (HF-38) | `warm-up` | `pose` | ≥ 95 % of synthetic warm-up moves ticked; a wrong move never ticks an item |
| 219 | Resistance-band tracker and anchor visibility prompt (HF-24) | `band` | `pose` | Reps ±1 per 10; when the anchor area he marks at setup (one tap on the screen) or the holding hand leaves the frame, a prompt within 1 s |
| 220 | AI personal trainer and form corrector (HF-01; fixed rules, no AI call) | `form` | `pose` | Each form rule (depth, knees caving, back angle, elbow flare, hip sag) fires on ≥ 90 % of synthetic faulty reps and ≤ 5 % of clean reps; at most one tip per rep |
| 221 | Smart yoga and mobility coach (HF-04) | `yoga` | `pose` | Each pose in its list recognised on ≥ 90 % of synthetic holds; hold time ±1 s |
| 222 | Plank hold duration and alignment coach (HF-16; side view) | `plank` | `pose` | Hold time ±1 s; hip sag and pike flagged on ≥ 90 % of synthetic spans, ≤ 5 % false |
| 223 | Home workout space clearance checker (HF-22) | `space-check` | `objects`, `pose` | On fixture object lists: "clear / not clear, move the chair" correct in 100 %; the check runs once before a session and keeps nothing |
| 226 | Single-leg balance and stability coach (HF-07) | `balance` | `pose` | Hold time ±1 s; the sway score rises with every step of injected sway |
| 228 | Shadowboxing punch and combination tracker (HF-08) | `boxing` | `pose` | Punch counts ±1 per 20; punch type (jab, cross, hook, uppercut) right on ≥ 85 % at 30 fps sequences, and at 15 fps counts only with types marked "about" |
| 230 | Agility drill and cone-crossing timer (HF-13) | `agility` | `pose` | With marks he taps on the screen at setup, split times within ±0.2 s on synthetic runs |
| 231 | Pilates movement-sequence adherence (HF-34) | `pilates` | `pose` | Steps recognised on ≥ 90 %; every out-of-order step in the fixtures is reported |
| 232 | Tai-chi form sequence and flow (HF-35) | `tai-chi` | `pose` | Steps ≥ 90 % against his recorded reference; the smoothness score is lower for every sequence with injected jerks |
| 235 | Jump height and landing mechanics (HF-06) | `jump` | `pose` | Height from flight time within ±5 cm at 30 fps and ±10 cm at 15 fps (shown as "about"); stiff or knees-in landings flagged on ≥ 90 % |
| 236 | Dance choreography sync (HF-09) | `dance` | `pose` | The sync score drops by ≥ 20 points for a 0.5 s offset; his reference routine is kept as joint angles only |
| 237 | Handstand hold drift and safe exit (HF-113) | `handstand` | `pose` | Will not start until he confirms a wall or a spotter (a test); hold time ±1 s; a drift warning and "come down" cue when the hips pass the set limit. Upside-down tracking is "to be tried" (risk 4) |
| 239 | Kettlebell swing path and hip hinge (HF-99) | `kettlebell` | `pose` | Hinge versus squat right on ≥ 90 %; swings ±1 per 20; the wrist path is shown as the bell's path |
| 240 | Assisted stretching partner monitor (HF-70) | `partner-stretch` | `pose` (two bodies, one kept) | Starts only after the partner-consent line is confirmed; a test proves no point, count or result of the partner ever leaves the pose task and nothing about the partner is kept; his stretch ranges and holds ±10° and ±1 s |
| 263 | Remote six-minute walk test lap and turn counter | `walk-test` | `pose` | With the course length he types: laps exact and turns counted on synthetic walks; distance = laps × length; labelled "practice, not a clinical test" |
| 269 | Sit-to-stand functional test assistant | `sit-to-stand` | `pose` | 30-second count exact and 5-times time within ±0.3 s on synthetic sequences; "practice, not a clinical test" |
| 247 | Eating pace and meal duration tracker (DN-03, phone at the table) | `meal` | `pose`, `hands` | Bites within ±10 % and meal length within ±1 minute; another person in view pauses the count (he angles the phone at himself) |

Declined on 14 Nov and not built: rows 225, 229, 233, 234.

**Row placement (recorded at the release paperwork):** 132 moves from the workbook's R8 to R8.1; 182 and 183 (R13), 247 and 248 (R9), 262, 263, 268, 269 and 276 (R10) are built here because they use the same two cameras (approved build lists of 14 Nov). Their workbook release changes when the Workshop regenerates chapter 10.

---

## 3. Decisions (safe defaults: each applies unless the owner answers otherwise)

The owner answered on 28 Nov 2026, 04:24 IST. Each row says what holds now.

| # | Question | Decision |
|---|---|---|
| D1 | Cameras for R8 and R8.1 | **Approved:** workout = the tripod phone; the laptop's external webcam for the face-and-hands desk use cases; the home camera he ordered for the whole-body ones (D3) |
| D2 | Mockups | **Approved** (the four in section 9); the screens follow them |
| D3 | Row 216's home-laptop leg | **Changed by the owner** ("The laptop camera shall not be able to capture the entire body posture and only my face would be visible. Rather it should be from the camera which I have ordered."): **in R8.** The ordered home camera (any RTSP/ONVIF IP camera; arriving about 3 Dec) serves rows 181, 182, 227 and 262's posture checklist. A home vision plugin on the home laptop (the home kit's bridge, R3) reads its RTSP sub-stream, runs pose there and runs those use cases' fixed rules there; **no frame, body point or box ever leaves the laptop**, only views and tallies, through the bridge's signed channel. Frigate stays the alarm's engine and is never switched by a coach. Rows 224, 238, 248, 268, 276 and 262's reading stay on the webcam (face and hands are enough). ADR-49 |
| D4 | Pose model size | **Follows D3:** on the home laptop, the full model if the laptop keeps ≥ 15 frames a second with it, else lite; lite stays the browser default; on the workout phone, full if its setup test keeps ≥ 15 a second, else lite. Live rate stays at R7's cap of 15 a second; rows 228 and 235 may ask for 30 only if the setup test shows the phone keeps 30 (a contract line at R8.1's join) |
| D5 | Screen time (183) | **Approved:** built and **off** until he installs ActivityWatch (free) and the home kit is linked; numbered steps in section 10 |
| D6 | People in view | **Changed by the owner** ("Please track all and not only me. When I say jarvis to track me, it should only track me. If I say track Shruti, it should identify and track that person and by default it should track all."; **final, 04:33 IST: "Keep everything and save the results."**): a **tracking target**, `all` (the default) \| `me` \| one named person, set by voice ("track me", "track <name>", "track everyone") or on screen. A named person is identified only through the consent-based face enrolment (R3's Faces, on the home laptop); a name with no enrolment answers "I don't know <name> yet: enrol their face first". **Results are saved for everyone:** a known person's under their name, an unknown person's as "Guest 1", "Guest 2" … per session (`coach_people`), which he can rename or merge later; sealed; every person and every guest has Privacy rows to view, export and delete; never clips, pictures or video (ADR-48) |
| D7 | Blood-pressure coach (262) | **Changed by the owner** ("Reading needs to be identified by the camera automatically and used and confirm."): the webcam reads the monitor's seven-segment display on the device (the `digits` task: systolic, diastolic, pulse), shows the reading, and he confirms or corrects it; only a confirmed reading is stored, sealed, and used: a trend and the standard published category **with its source named**, and "talk to your doctor" where that category says so. Never a diagnosis, never a medicine or a dose (the automated not-medical test stays) |
| D8 | Model fetch | **Approved** (04:33 IST, after the plainer explanation): a CI job on the R8 pull request fetches and hashes the models twice (pose lite and full, hand, the object model once its licence is read); no step for him (ADR-50). The home laptop's pose model comes from the same pinned files |
| D9 | The object model (223, 248, 262, 276, 182) | **Approved** (04:33 IST): EfficientDet-Lite0 only after its licence is read and recorded as permissive; otherwise `objects` runs on SSD-MobileNet v1, **already vendored and licensed** in `vendor/vision/r13-1/` (MIT model zoo, Apache-2.0 weights; COCO labels) |
| D10 | The webcam coach while you work | **Default stands:** the webcam's sessions run in a small always-on-top window (Chrome's Document Picture-in-Picture) so they keep looking while you use other programs; closing that window stops the camera; R7's "stops when the page is hidden" rule stays for everything else (ADR-52). The home camera's coaches need no window: they run on the home laptop |
| D11 | "Cameras off" | **Default stands:** stops every camera's looking at once (this device, his other devices, the home camera's coaches); it **never disarms the burglar alarm** and never switches off Frigate (R3 D8): the reply says the alarm camera is still armed and offers the Disarm card |
| D12 | Where results show and how long they're kept | **Default stands:** the day strip in Camera → Desk ("Your day") plus one line in the brief's Helpers section; Vitals shows camera health only. Tallies are kept only for coaches he switched on, for every person and guest (D6), 90 days (settable 7–365), exportable and deletable |
| D13 | Your bar, your way (part I, his 04:33 ask: "make every icon editable … drag and drop each item and place it as per my requirement. Also, the items I remove should be in the More. I should also have the option to hide the bar as well.") | An **Edit the bar** mode on the console, opened from a **right-click on the bar** ("Edit the bar"), a **long-press** on touch, a **keyboard shortcut** and a line in the console's settings (About), never from a new always-visible button: drag and drop each item to any place; every move also works by keyboard (arrow keys on a picked item); an item removed from the bar goes to More and can be put back from there; a **Hide the bar** switch, with a slim handle and a shortcut to show it again. **More keeps today's behaviour:** it appears only when items overflow or when he has removed items (the mockup's always-visible More would push Camera into More at 1920 px, which R18's rule forbids). On the phone, editing is a list in the More sheet (as mocked). **Nothing can be lost:** Chat and More can't be removed, and "Reset to default" puts the shipped bar back. The layout is saved **per device** (localStorage), versioned, so a tab a later release adds appears at the end instead of being lost. Until he edits it, the default bar at 1920 px stays byte-identical (R18's 1920 rule; `tests/browser/test_dock_fit.py`). A mockup of the edit mode is on `r8-mockups` |

---

## 4. Architecture

### 4.1 Where it fits

```
 L1  Camera panel: Look · Results · Cameras (setup) · Wardrobe · Desk (new) · Workout (new)   phone: full-screen workout
      │ pixel panes only (tests/test_r13_seams.py PANELS)          deep links ?do=desk|workout|cameras (open, never act)
 L2  console-vision.js engine ── tasks: text code objects pose quality hands digits(new) │ embed colour person face (R13)
      │  live(tasks, {uses, rate, target}) = the driver (R7 INTEGRATION-B 7a)     frames never leave the task
      │  home laptop: homevision plugin ── RTSP sub-stream → pose → the home use cases' rules → views, tallies
 L3  use-case registry: JarvisVision.use(...) modules console-coach-<id>.js → Results in, {view, tally} out
 L5  Health & Wellbeing: jarvis.coach (registry, tallies, posture nudge, day strip, screen time)
 L6  home bridge plugins: homevision (216 home leg, D3), activitywatch (183), camcheck (377)   Frigate unchanged (ADR-16)
 L7  coach_results, coach_routines (sealed `coach`), camera_spots, camera_health (sealed `vision`)
 L8  browser voice for counts and tips (₹0); nudge_posture; brief line
```

### 4.2 The engine: the `hands` task and the result-contract change (I0, then builder A)

- **`hands` (new task, v1):** MediaPipe Hand Landmarker (Apache-2.0) through the MediaPipe Tasks Vision 1.2.3 runtime already vendored in `r7-1`; VIDEO mode, up to 2 hands, rate 15. Data: `{hands: [{side: "left"|"right", score, points: 21 × {x, y, z}}]}` (at most 2 hands; numbers in ranges; nothing else).
- **`pose` v2 (D6 as changed):** `bodies`: up to 4 bodies in view, each `{track, who, points: 33}`: `track` a number that follows one body from frame to frame (continuity of the torso centre), `who` `""` (unknown), `"me"` or an enrolled person's `fp_` id. On the home camera `who` comes from R3's consented face library on the laptop; on a device camera (browser, phone) there is no face matching, so `who` is `"me"` only while exactly one body is in view of his own signed-in device, else `""`. The driver gives each use case one body at a time (its state is kept per body) and, for a target of `me` or one person, only that body: a use case is always written for one body.
- **`digits` (new task, v1, D7):** the numbers on a seven-segment display (a blood-pressure monitor's): `{lines: [{value: 0..999, score}]}`, at most 4 lines, read on a tap from one frame; the method (segment arithmetic or a pinned permissive model) is builder D's choice, with its licence recorded.
- **Contract files:** `src/jarvis/vision/results.py` gains `hands` and `digits` in `TASKS`, `HandsData`, `Hand`, `HAND_POINTS = 21`, `DigitsData`, and `PoseData.bodies` (`Body`); `console-vision.js`'s `CHECKS` match them. Per that file's rule, the change has a line in `docs/plans/r7-integration/INTEGRATION-B.md` (section 3), and the port core's byte pin in `tests/test_r7_b_console.py::test_the_port_core_is_the_agreed_one_byte_for_byte` moves with it.
- **Where the code goes:** the task bodies live in a sibling module `src/jarvis/api/static/console-vision-r8.js` (new; the R13 split pattern), statically imported by `console-vision.js` and registered **before** `sealRegistry()`. A use case still can't register a task.
- **Model files:** `src/jarvis/api/static/vendor/vision/r7-1/` already lists `pose_landmarker_lite.task` and `efficientdet_lite0.tflite` as "not installed" and `scripts/vision_assets.py fetch --models [--object-licence …]` already pins them there. R8 adds release **`r8-1`** (`src/jarvis/api/static/vendor/vision/r8-1/MANIFEST.json`, new) for the two new files, `hand_landmarker.task` and `pose_landmarker_full.task` (both Apache-2.0; URLs on MediaPipe's model pages, confirmed by builder A), with `--release r8-1` added to the script and `R8_RELEASE`, `R8_FILES` to `src/jarvis/vision/assets.py`. If D9's fallback applies, `objects` loads SSD-MobileNet v1 from `r13-1` through the onnxruntime-web runtime R13 already uses (its `person` self-check reused), mapping COCO ids to `OBJECT_LABELS`.

### 4.3 The live driver and the use-case registry on `JarvisVision.use`

R7 left the driver to R8 on purpose (`INTEGRATION-B.md`, section 7a): a use case may not touch the camera, `run` or `stream`. I0 adds to the port core, with contract lines:

| API | Who calls it | What it does |
|---|---|---|
| `JarvisVision.live(taskIds, {uses, rate, target, onError}) → {end(), tracks()}` | the Desk and Workout panes (pixel panes) | Pulls frames from `JarvisCamera` on a tap-started look, calls `stream(..., {onError})` at `min(rate, task rate)`, and tells **only the use cases named in `uses`**, one body at a time; `target` `{kind: all \| me \| person, person}` (D6) picks the bodies |
| `JarvisVision.use({id, tasks, onResult, summary})` | each `console-coach-<id>.js` | As in R7 (ids `^[a-z][a-z-]{1,20}$`). Change: a Result reaches a use case only during a `live()` that names it; `run()` from the Look tab tells no use case |
| `JarvisVision.tally(id, track?) → {view, tally, who}` | the panes | Calls the use case's `summary(state)` for one body's state (the first, or `track`); returns frozen plain data: `view` (fixed widget kinds below), `tally` (the use case's kept-result shape, or null) and `who` |
| `JarvisVision.reset(id)` | the panes | Clears that use case's state at a session's start and end |

**View widgets (fixed list, rendered by the panes, never by a use case):** `big` (a number and its word), `line`, `tip` (one form tip from the use case's own list), `timer`, `pacer` (phase and seconds), `targets` (dots for the reaction game and reach targets), `checklist`, `bar` (a 0–100 score), `paused` (why). A use case module therefore holds no DOM, no network and no storage, and stays inside the fail-closed guard (`tests/r7_jsguard.py`, `tests/r7_fakes_b.py:use_case_modules`), which already runs on every module that calls `JarvisVision.use(`.

**The server's registry:** `src/jarvis/coach/usecases.py` (new) lists all 34 rows' use cases: id, row, release, spot (`desk`, `workout`, `table`), tasks, rate, whether it is health data, and its `Tally` model (Pydantic, `extra="forbid"`): counts (ints in ranges), seconds, scores 0–100, labels from the use case's own fixed lists, start and end times. `GET /v1/coach/usecases` gives the panes their lists. **A tally that doesn't fit its model is dropped, never repaired.**

### 4.4 Kept results: counts, times and scores only, never pixels or points

- **What is kept:** a use case's tally at the end of a session (and every 15 minutes for the all-day desk coaches), **for everyone** (D6 final): `who` is `me`, an enrolled `fp_` id, or a guest (`gst_<12 hex>`, "Guest N" of that session, renamed or merged later in `coach_people`). Never a frame, a picture, a body point, a hand point or a box. Only for coaches he switched on (D12). A blood-pressure reading is kept only once he confirms it (D7).
- **Where:** `{prefix}coach_results/{uid}_{yyyymmdd}`: `uid, day, v, kid, n, updated_at, blob`, blob = AES-GCM(JSON {day, items}) under a **new keyring purpose `coach`** (`src/jarvis/keyring.py:PURPOSES`), AAD `coach_results/{uid}/v1`. Same rules as `src/jarvis/vision/store.py`: at most 200 items a day, a day under Firestore's 1 MiB, the day inside the blob must match the document, no keyring → off (never in clear), a day that won't open never blocks the others, the daily sweep deletes days past `coach_keep_days` (90).
- **His references:** `{prefix}coach_routines/{uid}_{id}` (sealed `coach`): the dance and tai-chi reference routines he records, as joint angles over time (no points, no pictures), and his posture calibration (a few angles).
- **Health data (ADR-51):** posture, blood-pressure posture (and a typed reading), hand rehab, reach-and-grasp, six-minute walk, sit-to-stand, eating pace and every workout tally are health data: sealed under `coach`, in Privacy's new **"Health and fitness"** section with a count, export (JSON of tallies) and delete with the passkey (it can't be brought back), and never sent to the brain unless he asks: the brain's one tool `coach_results` (R1, read-only, filed under Health & Wellbeing in `src/jarvis/skills/catalogue.json`) returns tallies, private on Telegram (`coach_*` in the private patterns).
- **Writes:** about 30–200 a day, well inside Firestore's free tier.

### 4.5 Cameras, spots, rooms and off switches (row 217, 184; builder B)

- **Registry:** `{prefix}camera_spots/{uid}`, sealed under `vision`: each camera `{id, kind: device|home, label (his words), spot, room, on}`, each room `{id, label, never: bool}`; the desk camera and the workout phone are device cameras (registered from the device that has them), R3's home cameras appear from the bridge's camera list. `PUT /v1/camera/spots`, `GET /v1/camera/spots`.
- **Off switches:** per camera, per room ("never" rooms can't be picked for a coach), and all. A device reads the switches when its camera starts and every 60 s while live; a switch it reads as off stops the look at once. For home cameras the switches ride the existing state push to the bridge (Frigate detection for that camera off), which never touches the alarm's arm state.
- **"Cameras off" for every camera (D11):** today's phrases (`src/jarvis/voice/commands.py`, `R7_PHRASES["camera.off"]`, mirrored in `console-camera.js`) still lock this device at once (works with the AI off); R8 also sets "all off" on the server so the other devices stop within 60 s. No voice command switches a camera on; only a tap.
- **Camera health in Vitals:** each live device posts `{camera, fps, ms, last_seen}` every 5 minutes (`POST /v1/camera/health`, `{prefix}camera_health/{uid}`); `src/jarvis/vitals/own.py` gains one item per registered camera ("Desk camera: seen 3 min ago, 1 frame a second"): ok, amber when a switched-on camera is unseen for 24 h, "off" when switched off. Home cameras use the bridge heartbeat's existing "cameras producing frames".

### 4.5a The home camera's vision on the home laptop (D3, D4, row 216's home leg; builder J)

- **Where it runs:** a new home-bridge plugin `src/jarvis/homebridge/homevision.py` in the home kit on the laptop (R3's containers under WSL; installed, keyed and reached the way the kit already is: the bridge's HMAC link both ways through Tailscale Funnel, no new key or port). It reads the home camera's **RTSP sub-stream** (the address and the camera's password stay in `bridge.env` on the laptop, like Frigate's), decodes about 1 frame a second (2 while a slouch is suspected, up to 15 during a seated session), runs MediaPipe's pose landmarker there (Python, Apache-2.0; the pinned `r7-1`/`r8-1` model files, SHA-256 checked; full if the laptop keeps ≥ 15 frames a second, else lite: D4) and identifies enrolled people through R3's face library already on the laptop (D6).
- **What runs there:** the home camera's use cases (`posture`, `activity`, `seated`, `bp-posture`) as fixed Python rules on the same Result shapes (`jarvis.coach.home`: one `HomeUseCase` per id with `on_result(result, state)` and `summary(state) → {view, tally}`, the browser's contract in Python; kit-safe: standard library and Pydantic only).
- **What leaves the laptop:** only `CoachReport`s through the bridge's signed event channel: `{camera, use, track, who, view, tally, at}` (views and tallies only; never a frame, a point or a box: a CI test proves it). The cloud keeps the newest view in memory for the panes (`GET /v1/coach/live`) and keeps a tally only for a known person.
- **What goes to the laptop:** the coach part of the bridge's state push (`CoachState`: which use cases are on for which camera, the tracking target, "cameras off"); it never touches the alarm's arm state or Frigate.
- **Source kinds:** every camera is `browser`, `phone` or `home` (the Result's `device`); each use case names the source it runs on (`jarvis.coach.usecases`), and a home-camera use case can't be started on a device camera.
- **The camera:** the owner's **Imou Ranger S2** (3 MP pan-and-tilt, RTSP and ONVIF per its listing; delivery 3 Dec 2026). Nothing in the code names the model: the sub-stream's address is what the no-cloud check (row 377) finds and he confirms, so any RTSP/ONVIF camera works the same way.

### 4.5b Your bar, your way (D13, part I; builder I)

- **The layout:** `{v, order: [tab ids], more: [tab ids], hidden: bool}` in this device's localStorage (`jarvis_dock_layout_v1`), read and written only by `src/jarvis/api/static/console-dock-layout.js` (I0, pure: `parse`, `apply(defaults, saved)`, `move`, `toMore`, `fromMore`, `reset`). `apply` drops ids the console no longer has, appends tabs a later release adds at the end of the bar, never lets `chat` or `more` leave the bar, and returns the defaults for anything it can't read: no item is ever lost.
- **The editor:** builder I's `console-dock-edit.js` and `console-dock-edit.css` (new) and the dock's own `console-dock.js`: Edit the bar (right-click on the bar, long-press, a shortcut, the settings line; no new button), drag and drop, keyboard moves, Remove (to More), Put back, Reset to default, Hide the bar and its handle and shortcut; on the phone a list in the More sheet. More shows only when tabs overflow or one was removed. With no saved layout the bar is exactly today's.

### 4.6 The no-cloud camera check (row 377; builder B)

- **Before buying:** Camera → Cameras → "Check a camera before you buy" shows the 27 Nov hardware note as a checklist (RTSP main and sub streams, ONVIF Profile S, H.264, mains power, memory card; one-time app setup is fine). A probe can't test a camera that isn't on the network yet.
- **After buying:** a new bridge plugin `src/jarvis/homebridge/camcheck.py` serves `POST /bridge/v1/camera-check` (added to `src/jarvis/home/ports.py:BRIDGE_ROUTES`). It takes a private-range IP only (RFC 1918; anything else refused), then checks RTSP `DESCRIBE` on both streams, ONVIF `GetDeviceInformation` and `GetProfiles`, and the codec; standard library and httpx only (the bridge kit's rule). The camera's user name and password are typed on the bridge's local page (`src/jarvis/homebridge/local_page.py`), stay on the laptop and are never sent to the cloud; the cloud sees only pass/fail and the missing piece.
- **The "no cloud" half:** he blocks the camera's internet at the router and restarts it; the check runs again and passes only if everything still answers. WS-Discovery is not relied on (multicast may not cross WSL's network), so he types the IP.

### 4.7 Posture, the day strip and screen time (rows 181–183; builder C)

- **Posture:** `console-coach-posture.js`: neck and torso angles against his 10-second calibration; a slouch held 60 s → the pane posts a `posture` tally; `src/jarvis/helpers/nudges/posture.py` (new, kind `nudge_posture` in `src/jarvis/helpers/kinds.py`, cap 3 an hour, 8 a day, inside his nudge window, off until he switches it on) sends one fixed sentence ("Sit back and lift your head, Sir."). No count or angle in any message or log line.
- **The day strip:** `console-coach-activity.js` labels each minute desk, away, phone or eating; the cloud joins the minutes into segments (`src/jarvis/coach/day.py`, new) with screen time; Camera → Desk → "Your day" draws it; `src/jarvis/coach/brief.py` (new) adds one line to the brief's Helpers section.
- **Screen time (ADR-53):** ActivityWatch (MPL-2.0) is installed by the owner, not shipped. A bridge plugin `src/jarvis/homebridge/activitywatch.py` (new) reads its local REST API (the window and "away" buckets) and serves `GET /bridge/v1/screentime`: per-program minutes and active time for a day; **window titles never leave the laptop**. Its address is `AW_URL` in `deploy/home/bridge.env.example` (default `http://host.docker.internal:5600`; the containers reach Windows as `172.29.80.1`, `deploy/home/docker-compose.yml`). Built, off until installed (D5).

### 4.8 CPU and battery budget

| Where | Coach | Rate | Budget (measured by the setup test and every session's `ms`) |
|---|---|---|---|
| Laptop (i7-10750H, 16 GB, browser) | posture, day strip | 1 fps (2 while a slouch is suspected) | ≤ 10 % of one core averaged (frame time × rate ≤ 0.1) |
| Laptop | games, seated coach, breath, rehab, reach | up to 15 fps, only during a session | session only; stops when the pane closes |
| Laptop | water | 2 fps | ≤ 15 % of one core |
| Phone (tripod) | workout coaches | 15 fps (D4) | the session's own; the screen kept awake (Screen Wake Lock), a warning at 20 % battery |

This answers ADD chapter 12's "R8 measures camera load": the setup test's figures are stored as camera health and shown in Vitals.

### 4.9 No new dock tab (ADR-35); ways in

The 1920 px dock is full. R8 and R8.1 add **no tab**: Desk and Workout are panes of the existing Camera panel (beside Look, Results, Cameras and Wardrobe), camera setup is the Cameras pane, camera health is in Vitals, kept tallies are in Privacy. Deep links in `src/jarvis/api/static/console-r7-links.js` gain `?do=desk`, `?do=workout` and `?do=cameras`: each opens its pane and **never starts the camera** (R7 D8). The R7 app's shortcut list can point at `?do=workout`. `tests/browser/test_dock_fit.py` must still pass to the pixel.

### 4.10 The desk window (D10, ADR-52)

`console-camera.js` stops the camera when the page is hidden. At the desk he works in other programs, so the Desk pane offers "Keep a small window on top": a Document Picture-in-Picture window (Chrome on the laptop) that holds the live video, the "Camera on" chip with Stop and the posture status. The camera stays on only while that window is open and visible; closing it, the Stop chip, "cameras off" or 10 minutes with no frame used stops it. The look's timer runs on the small window's own clock so a hidden console tab can't throttle it (to be proved in a browser test over 2 hours of fake camera; risk 1).

### 4.11 The no-cloud model fetch in CI (D8, ADR-50)

This sandbox can't reach `storage.googleapis.com` (HTTP 403, checked again 28 Nov 2026). New workflow `.github/workflows/vision-models.yml` (`workflow_dispatch` and pull requests touching `src/jarvis/api/static/vendor/vision/**`; `permissions: contents: read`): runs `python scripts/vision_assets.py fetch --models` (and `--release r8-1`) twice from fresh downloads, fails if any SHA-256 differs between the runs, writes each file's name, size and SHA-256 to the job summary, and uploads the files as a 7-day artifact. The Workshop reads the hashes, downloads the artifact with `gh run download`, runs `python scripts/vision_assets.py check`, and commits the files and the pinned manifests on the R8 branch. If the artifact host is refused here, the fallback is the same workflow with a job that commits only files whose two hashes agree to the `r8-*` branch (never `main`), recorded in ADR-50. Either way the pins are "read twice", not vendor-published (Google publishes no hash: trust on first use, as R7's section 5 says).

### 4.12 The object model's licence (D9)

`efficientdet_lite0.tflite`'s licence is "to be read" (`r7-1/MANIFEST.json`); R7 found that its page links no model card. Builder A reads MediaPipe's object-detector model card and records the licence's name and address in the manifest and `docs/plans/r8-integration/I1-NOTES.md`. Only a permissive name passes `--object-licence` (Apache-2.0, MIT, BSD-2-Clause, BSD-3-Clause; ADR-29). Otherwise D9's fallback (SSD-MobileNet v1 from `r13-1`) serves `objects`, with a test that the same `OBJECT_LABELS` come out.

---

## 5. ADRs to add and the ADD chapters each release updates

**New ADRs in the Architecture Design Document, chapter 08 (kept privately), from the next free number (ADR-46 is the last):**

| ADR | Decision | Status when the PR merges |
|---|---|---|
| ADR-47 | The engine owns the live driver and the use-case registry; a use case gets Results only for a live look that names it and returns `{view, tally}`; kept tallies are counts, times and scores only (extends ADR-19) | Accepted (R8) |
| ADR-48 | A tracking target: everyone in view by default, "me", or one named person identified only through consent-based face enrolment; everyone's results are saved (a known person's under their name, an unknown person's as a session's "Guest N", renamable and mergeable), sealed, with Privacy rows, export and delete per person; never clips, pictures or video (the owner's D6) | Accepted (R8; R8.1 applies it to 240 and 247) |
| ADR-49 | Vision also runs on the home laptop: the home camera's RTSP sub-stream is looked at there by a bridge plugin (pose, the home use cases' rules, face identification from R3's library) and only views and tallies leave it; Frigate stays the alarm's engine; a home camera is accepted only if it passes the no-cloud check (RTSP + ONVIF on the home network, still working with its internet blocked) | Accepted (the owner's D3; amends ADR-19 and ADR-16) |
| ADR-50 | Model files come from a CI fetch whose SHA-256s are read twice, because the vendor's storage is unreachable here; the object model ships only with its licence read, else the vendored SSD-MobileNet v1 serves `objects` | Accepted (extends ADR-29 and ADR-42's context) |
| ADR-51 | Health results are sealed under their own key (`coach`), exportable and deletable; never a diagnosis, a medicine or a dose (an automated test); a blood-pressure reading is read by the camera, stored only once he confirms it, and shown with its trend and the published category with its source named (the owner's D7) | Accepted |
| ADR-52 | The desk coach may keep the desk camera on in a small always-on-top window while the console tab is hidden; R7's "stops when hidden" rule stays everywhere else | Accepted (amends R7 D11) |
| ADR-53 | Screen time comes from ActivityWatch, installed by the owner and read through the home bridge; JARVIS ships none of it (MPL-2.0 is outside ADR-29's "shipped" scope); window titles never leave the laptop | Accepted |
| ADR-54 | "Cameras off" stops every camera's looking on every device and every coach; it never disarms the burglar alarm (R3 D8) | Accepted (widens R7 D11) |

R8.1 adds no ADR unless its join raises the 15-a-second cap for rows 228 and 235 (then ADR-55, written then).

**Chapters updated by R8 (`r8-add` branch, in the R8 PR):** 02 (the bridge's two new plugins and routes; ActivityWatch on the laptop; the `vision-models` workflow in 2.10); 03 (L2: `hands`, `pose` v2, the live driver; L5: coaches, posture, day strip; L6: the plugins; new components C84 Coach use cases and kept tallies, C85 Live driver and hands, C86 Camera setup, spots and health, C87 No-cloud camera check, C88 Screen time, C89 Desk coach and posture nudges; the Book writer confirms the numbers); 04 (collections `coach_results`, `coach_routines`, `camera_spots`, `camera_health`; purpose `coach`; retention; Privacy's "Health and fitness" rows; section 7 "what never leaves the device" gains points, boxes and window titles); 05 (the probe's private-range rule and local credentials; the model pins; health data); 06 (the CPU and write budgets of 4.8, measured); 07 (the `evals/r8` suites and the not-medical test); 08 (ADR-47 to ADR-54; ADR-19, ADR-16 and ADR-29 updated); 09 (counts); 10 (regenerated from the new workbook; reviewed pointers for the rows that become Done); 11 (R8 built; what R8.1 and R9 inherit); 12 (conflicts C16 "desk camera while the tab is hidden" and C17 "health data", the gaps found, the risks of section 11); 13 (verification of the new chapters).

**Chapters updated by R8.1 (in the R8.1 PR):** 03 (L5's workout coaches; component C90 Workout coach), 04 (`coach_routines` in use), 07 (`evals/r8_1`), 09, 10, 11, 12.

---

## 6. Privacy and safety

1. **A tracking target** (D6, ADR-48). Everyone in view by default; "track me" or "track <name>" narrows it to one person; "track everyone" widens it again. A named person is identified only through R3's consent-based face enrolment, on the home laptop; there is no face matching in the browser or on the phone. Everyone's results are saved, per person: a known person under their name, anyone else as a session's "Guest N" (rename or merge later).
2. **Children.** A child is identified only if a parent or guardian enrolled them with consent in Faces (R3's rule); an unknown child is saved like any guest, as counts, times and scores only, and can be deleted in Privacy. No use case has a child mode.
3. **No clips, no pictures.** Frames are looked at on the device and thrown away (ADR-19). Clip review is off and not built. The only things that leave a device are tallies (counts, times, scores, fixed labels), camera health figures and the panes' requests; the R7 "no picture leaves" eval runs on every new module.
4. **Health results** are sealed under `coach`, listed in Privacy ("Health and fitness") with export and delete (passkey), kept 90 days by default (D12), never in a log line, never sent to Telegram in clear, never sent to the brain unless he asks through the `coach_results` tool.
5. **Not medical advice.** Rows 262, 263, 268, 269, 276 (and every coach) carry "Practice only, not medical advice". **An automated test** (`tests/test_r8_not_medical.py`, new, I0) scans every coach's words (`src/jarvis/coach/words.py`, every `console-coach-*.js` string list) and every `view` produced in the evals for diagnosis or dose language (a list: "you have", "diagnos", "hypertension", "normal range", "mg", "dose", "take your", "prescri", "treat", and others) and fails on any hit; a negative control plants one.
6. **Stop on pain.** Every session starts with "Stop if anything hurts" and shows a big Stop; "Jarvis, stop looking" or "Jarvis, cameras off" (R7's local camera-off phrases, which work with the AI off) stops a session at once.
7. **Handstand (237):** won't start until he confirms "a wall behind me" or "a spotter with me"; a safe-exit cue when the hips drift; a test proves it can't start without the confirmation.
8. **The partner in 240** must agree before the session (a line he confirms on the partner's behalf); with the target `me` the partner is never told to a use case and nothing about them is saved; with `all` the partner is saved as a guest (or under their name if enrolled with their own consent) and can be deleted.
9. **Camera door:** the camera starts only from a tap; "Camera on" chip while live; no voice command turns a camera on; "cameras off" never disarms the alarm (D11).
10. **The no-cloud check** touches only a private-range address; the camera's password stays on the laptop.

---

## 7. Build: one plan, two pull requests

Branches from `main` (R5.2 and R18 merged). Every branch is pushed as soon as it has a commit. File ownership: after I0, **no two builders own the same file**; a seam file I0 owns changes only with a contract line in `docs/plans/r8-integration/I0-SEAMS.md`.

### 7.1 I0 seams (`r8-i0`; covers R8 and R8.1)

| # | Seam | File(s) | Owner after I0 |
|---|---|---|---|
| S1 | Result contract: `hands`, `HandsData`, `PoseData.others`; the line in R7's INTEGRATION-B | `src/jarvis/vision/results.py`, `docs/plans/r7-integration/INTEGRATION-B.md` | I0 (frozen) |
| S2 | Port core: `live`, `tally`, `reset`, results only to named uses, `stream` honours `opts.rate`; imports and registers the R8 tasks before the seal; the byte pin | `src/jarvis/api/static/console-vision.js`, `tests/test_r7_b_console.py` | I0 (frozen) |
| S3 | The R8 task module (stub: `hands` and `pose` v2 say "not installed") | `src/jarvis/api/static/console-vision-r8.js` (new) | A |
| S4 | Assets: release `r8-1`, `R8_FILES`; its manifest; the script's `--release` | `src/jarvis/vision/assets.py`, `src/jarvis/api/static/vendor/vision/r8-1/MANIFEST.json` (new), `scripts/vision_assets.py` | A |
| S5 | The model fetch-and-hash workflow | `.github/workflows/vision-models.yml` (new) | A |
| S6 | Use-case registry and every tally model (34 rows), view widget kinds | `src/jarvis/coach/usecases.py` (new), `src/jarvis/coach/__init__.py` (new) | I0 (frozen) |
| S7 | Sealed stores: `coach_results`, `coach_routines`; keyring purpose `coach` | `src/jarvis/coach/store.py` (new), `src/jarvis/keyring.py` | I0 |
| S8 | Privacy rows "Health and fitness" | `src/jarvis/coach/privacy.py` (new) | I0 |
| S9 | Routes: `GET /v1/coach/usecases`, `POST/GET /v1/coach/results`, `DELETE /v1/coach/results/{id}`, `GET /v1/coach/export`, `PUT/GET /v1/coach/routines` | `src/jarvis/api/coach.py` (new) | I0 |
| S10 | The brain's tool `coach_results` (R1) and its register entry | `src/jarvis/coach/tools.py` (new), `src/jarvis/skills/catalogue.json` | I0 |
| S11 | Ports the builders implement: `CameraSpots`, `CameraHealth`, `WaterLog`, `ScreenTime`, `PostureNudge` | `src/jarvis/coach/ports.py` (new) | I0 |
| S12 | Camera spots model and store (skeleton) and its routes (skeleton) | `src/jarvis/camera/spots.py` (new), `src/jarvis/api/camera_spots.py` (new) | B |
| S13 | Vitals: one item per camera (ids, words, the reader protocol) | `src/jarvis/vitals/own.py`, `src/jarvis/vitals/words.py` | I0 (B implements the reader in `src/jarvis/camera/health.py`) |
| S14 | Bridge routes `GET /bridge/v1/screentime`, `POST /bridge/v1/camera-check`; both plugins in the registry as stubs | `src/jarvis/home/ports.py`, `src/jarvis/homebridge/registry.py`, `src/jarvis/homebridge/activitywatch.py` (new stub), `src/jarvis/homebridge/camcheck.py` (new stub) | I0 / C / B |
| S15 | Nudge kind `nudge_posture` and its caps | `src/jarvis/helpers/kinds.py` | I0 (C writes `src/jarvis/helpers/nudges/posture.py`) |
| S16 | Camera panel panes `desk`, `workout` and the `cameras` mode hook (`JarvisCameraModes` allow-list widened) | `src/jarvis/api/static/console-camera-panel.js` | I0 (frozen) |
| S17 | Deep links `do=desk`, `do=workout`, `do=cameras` | `src/jarvis/api/static/console-r7-links.js` | I0 |
| S18 | Every new console file listed in `APP_ASSETS` up front | `src/jarvis/api/console.py` | I0 |
| S19 | Pixel panes widened (`console-coach-desk.js`, `console-coach-workout.js`); the guard runs on every `console-coach-*.js` | `tests/test_r13_seams.py`, `tests/r7_fakes_b.py` | I0 |
| S20 | Shared geometry: joint angle, distance, smoothing, rep state machine, hold timer, sway, sequence matcher (pure) | `src/jarvis/api/static/console-coach-geom.js` (new) | I0 (frozen; additions by contract line) |
| S21 | The not-medical test and its word list | `tests/test_r8_not_medical.py` (new), `src/jarvis/coach/words.py` (new) | I0 |
| S22 | Wiring skeleton, settings (`coach_enabled`, `coach_keep_days`), version `8.0.0`, seams notes, the rows' success checks | `src/jarvis/api/r8_wiring.py` (new), `src/jarvis/config.py`, `src/jarvis/__init__.py`, `docs/plans/r8-integration/I0-SEAMS.md` (new), `docs/plans/r8-integration/ROWS.md` (new) | I0, then I1 |
| S23 | Test fakes and the synthetic sequence maker (Node) | `tests/fixtures/r8/poses.mjs` (new), `tests/fixtures/r8/hands.mjs` (new), `tests/r8_fakes.py` (new) | I0 (builders add their own fixture files beside them) |
| S24 | The home vision seam (D3): source kinds, the `CoachReport` event and `CoachState` push, the plugin stub, the home use-case contract in Python, the cloud's live views | `src/jarvis/coach/sources.py` (new), `src/jarvis/home/ports.py`, `src/jarvis/homebridge/homevision.py` (new stub), `src/jarvis/coach/home/__init__.py` (new) | I0 / J |
| S25 | The tracking target (D6): its model, store, route, voice phrases and the "I don't know <name> yet" reply | `src/jarvis/coach/target.py` (new), `src/jarvis/voice/commands.py` | I0 |
| S26 | The blood-pressure reading (D7): the `digits` task shell, the reading model, the confirm step, the categories table's shape (filled from a named published source by D) | `src/jarvis/coach/bp.py` (new) | I0 / D |
| S27 | People and guests (D6 final): who a result is for (`me`, an enrolled `fp_` id, or a session's "Guest N"), rename and merge, Privacy rows per person | `src/jarvis/coach/people.py` (new) | I0 |
| S28 | The bar's layout model (D13): order, the More set, hidden, versioned; the defaults unchanged | `src/jarvis/api/static/console-dock-layout.js` (new) | I0 (frozen; I builds the editor on it) |

### 7.2 R8 builders (parallel, after I0 is pushed)

| Builder | Branch | Rows | Owns (files) | Tests |
|---|---|---|---|---|
| **A** engine and models | `r8-a` | 216 | `src/jarvis/api/static/console-vision-r8.js`; `src/jarvis/vision/assets.py`; `scripts/vision_assets.py`; `src/jarvis/api/static/vendor/vision/r8-1/**`; the pinned model files and manifests in `vendor/vision/r7-1/` (models only); `.github/workflows/vision-models.yml`; `src/jarvis/api/static/console-vision-check.js` (new: the setup test, frames a second and core share) | `tests/test_r8_a_engine.py`, `tests/test_r8_a_assets.py`, `tests/fixtures/r8/engine.mjs`, `evals/r8/engine.py` |
| **B** camera setup, privacy, no-cloud check | `r8-b` | 217, 184, 377 | `src/jarvis/camera/spots.py`; `src/jarvis/camera/health.py` (new); `src/jarvis/api/camera_spots.py`; `src/jarvis/homebridge/camcheck.py`; `src/jarvis/api/static/console-camera-setup.js` and `.css` (new, the Cameras pane via the mode hook); `src/jarvis/api/static/console-camera.js` (reads the switches, sets "all off"); `src/jarvis/voice/commands.py` (the "cameras off" reply words only) | `tests/test_r8_b_spots.py`, `tests/test_r8_b_health.py`, `tests/test_r8_b_camcheck.py` (a fake RTSP and ONVIF server, standard library), `tests/browser/test_r8_camera_setup.py`, `evals/r8/cameras.py` |
| **C** posture, day strip, screen time, the desk pane | `r8-c` | 181, 182, 183 | `src/jarvis/api/static/console-coach-desk.js` (new: the Desk pane, the small window, `live()`, posting tallies and health); `src/jarvis/api/static/console-coach-view.js` and `console-coach.css` (new: the widget renderer both panes use); `console-coach-posture.js`, `console-coach-activity.js` (new); `src/jarvis/helpers/nudges/posture.py` (new); `src/jarvis/coach/day.py`, `src/jarvis/coach/brief.py`, `src/jarvis/coach/screentime.py` (new); `src/jarvis/homebridge/activitywatch.py`; `deploy/home/bridge.env.example` (`AW_URL`) | `tests/test_r8_c_posture.py`, `tests/test_r8_c_day.py`, `tests/test_r8_c_activitywatch.py` (a fake ActivityWatch API), `tests/browser/test_r8_desk_pane.py` (incl. the 2-hour small-window run on a fake camera), `evals/r8/desk.py` |
| **D** desk coaches | `r8-d` | 224, 227, 238, 248, 262, 268, 276 (227 and 262's checklist as home rules in `src/jarvis/coach/home/seated.py`, `bp_posture.py`; 262's reading on the webcam, `src/jarvis/coach/bp.py`'s categories filled from a named source) | `console-coach-reaction.js`, `console-coach-seated.js`, `console-coach-breath.js`, `console-coach-water.js`, `console-coach-bp.js`, `console-coach-handrehab.js`, `console-coach-reach.js` (new, in `src/jarvis/api/static/`); `src/jarvis/coach/water.py` (new: the `WaterLog` port over `src/jarvis/helpers/nudges/hydrate.py:log_water`, with Undo) | `tests/test_r8_d_coaches.py` (Node runs each module on synthetic sequences), `tests/fixtures/r8/desk_sequences.mjs`, `evals/r8/coaches.py` |

| **I** your bar, your way (D13) | `r8-i` | — (his 28 Nov ask) | `src/jarvis/api/static/console-dock.js`, `console-dock-edit.js` and `console-dock-edit.css` (new) only | `tests/test_r8_i_dock.py` (Node: the editor on the layout model), `tests/browser/test_r8_dock_edit.py` (drag, keyboard, long-press, hide and show, reset; 1920 px unchanged until edited) |
| **J** home vision (D3) | `r8-j` | 216 (home leg) | `src/jarvis/homebridge/homevision.py`; `src/jarvis/coach/home/runtime.py` (new: RTSP decode, pose, identification, the report loop); `deploy/home/` (the plugin's image deps and `bridge.env.example` keys); the laptop's pose model pin | `tests/test_r8_j_homevision.py` (a fake RTSP source of synthetic frames; no frame, point or box in any report), `evals/r8/home.py` |

C writes posture and activity as home rules (`src/jarvis/coach/home/posture.py`, `activity.py`) instead of console modules. Screens (B's Cameras pane, C's Desk pane and renderer) follow the approved mockups (section 9); every builder starts at once.

### 7.3 R8's join, Book, ADD, review and pull request

1. **I1 join** (`r8-i1`): merges A–D, completes `src/jarvis/api/r8_wiring.py` (the coach part, privacy rows, the tool, the two bridge plugins, the Vitals reader, the nudge), runs `make test`, `make lint`, `make type`, `make eval-mock`, the browser suite; writes `docs/plans/r8-integration/I1-NOTES.md` (the pinned hashes, the object model's licence, deviations).
2. **Model pins:** the Workshop runs the `vision-models` workflow on the R8 branch and commits the files and manifests (4.11).
3. **Book writers** (`r8-book`): guide cards C84–C89 in `docs/architecture/JARVIS-Architecture.md`; the `coach` package in `src/jarvis/buildbook/gen/modules.py` and `layers.py`; `scripts/arch_coverage.json`; then `PYTHONPATH=src python -m jarvis.buildbook.gen pages --list`, write or refresh every page and narration it names in the same PR, until `pages --check` and `pages --narration-check` pass; `python -m jarvis.buildbook.gen --check`.
4. **ADD update** (`r8-add`): the chapters in section 5; `PYTHONPATH=$PWD/src python scripts/check_doc_versions.py` passes.
5. **One combined security + code review** (`r8-review`, fresh context: code-reviewer, python-reviewer, security-reviewer): fixes its findings and runs the one final check pass; `docs/plans/r8-integration/REVIEW.md`.
6. **PR** `v8.0.0 · R8 Vision core & your desk camera · Mark XXVI`. The owner merges; the Workshop follows main's CI to a green deploy.

### 7.4 R8.1 builders (parallel; may start once R8's I0 is pushed; PR after R8 merges)

| Builder | Branch | Rows | Owns (files, all new in `src/jarvis/api/static/` unless named) | Tests |
|---|---|---|---|---|
| **E** strength and form, the workout pane | `r8-1-e` | 132, 218, 219, 220, 222, 223 | `console-coach-workout.js` (the full-screen phone pane: picker, Stop, wake lock, browser voice for counts and tips, the safety lines); `console-coach-reps.js`, `console-coach-warmup.js`, `console-coach-band.js`, `console-coach-form.js`, `console-coach-plank.js`, `console-coach-space.js` | `tests/test_r81_e_coaches.py`, `tests/fixtures/r8/strength_sequences.mjs`, `tests/browser/test_r81_workout_pane.py` (390 × 844), `evals/r8_1/strength.py` |
| **F** flow and balance | `r8-1-f` | 221, 226, 231, 232, 236 | `console-coach-yoga.js`, `console-coach-balance.js`, `console-coach-pilates.js`, `console-coach-taichi.js`, `console-coach-dance.js` (reference routines through `PUT /v1/coach/routines`, angles only) | `tests/test_r81_f_coaches.py`, `tests/fixtures/r8/flow_sequences.mjs`, `evals/r8_1/flow.py` |
| **G** dynamic | `r8-1-g` | 228, 230, 235, 237, 239 | `console-coach-boxing.js`, `console-coach-agility.js`, `console-coach-jump.js`, `console-coach-handstand.js`, `console-coach-kettlebell.js` | `tests/test_r81_g_coaches.py` (incl. "handstand can't start without a wall or spotter"), `tests/fixtures/r8/dynamic_sequences.mjs`, `evals/r8_1/dynamic.py` |
| **H** partner, tests and meals | `r8-1-h` | 240, 263, 269, 247 | `console-coach-partner.js`, `console-coach-walk.js`, `console-coach-sitstand.js`, `console-coach-meal.js` | `tests/test_r81_h_coaches.py` (incl. "no partner data leaves the task"), `tests/fixtures/r8/tests_sequences.mjs`, `evals/r8_1/care.py` |

Then the same steps as 7.3: I1 join (`r8-1-i1`, from R8's final branch if R8 isn't merged yet, naming R8 as a prerequisite), Book writers (C90 and the workout pages), the ADD's R8.1 chapters, one combined review (`r8-1-review`), PR `v8.1.0 · R8.1 Fitness coach at your workout spot · Mark XXVI`.

---

## 8. Evals

- **CI uses synthetic data and public data only.** `tests/fixtures/r8/poses.mjs` and `hands.mjs` animate a 33-point body and 21-point hands (joint angles over time, with noise, missed frames, low visibility, a second body walking in, a child-sized body, camera tilt); each builder's sequence file scripts its exercises, faults and edge cases. Any public dataset must be CC BY 4.0 or more permissive, with its licence in the suite's docstring; none is needed for the thresholds below.
- **Per-row thresholds:** the acceptance tests in section 2 are the pass bars. Each suite (`evals/r8/*.py`, `evals/r8_1/*.py`, run by `evals/run_all_mock.py`) has at least one negative control that must fail (a coach that counts half reps; a tally with a body point in it; a pause rule removed; a view with "your blood pressure is normal").
- **Cross-cutting suites:** no picture or point leaves (R7's suite on every new module); tallies outside their models dropped; health tallies sealed and opening only under `coach`; the not-medical scan; "cameras off" stops every device and never disarms; the probe refuses public addresses; the small window's 2-hour run; the dock unchanged at 1920 px (Night and Day); the visual gate `tests/browser/test_ui_audit.py` on the new panes.
- **His own test sets stay on his devices.** The owner's check (owner step 5): 10 reps of each exercise he uses, counted by him and by the coach; the console compares them on the device, shows the score, keeps the score as a tally if he chooses, and throws away the sequence. No owner sequence, point or picture is ever uploaded or committed.

---

## 9. Screens needing mockups and the approval stop

Mockups are made in parallel on branch `r8-mockups` (`docs/plans/r8-mockups/`, the owner's ui-ux-pro-max rule, the console's look unchanged, Night and Day):

1. **Camera setup** (217, 184, 377): cameras, spots and rooms, the off switches, camera health, "Check a camera" (before and after you buy). Camera → Cameras.
2. **Desk coach** (181, 224, 227, 238, 248, 262, 268, 276): posture status, the small window, the breath pacer, water count, the games and rehab sessions. Camera → Desk.
3. **Workout session on the phone** (R8.1's 20 rows): full screen at 390 × 844: picker, rep and tempo counter, form tip, timer, big Stop, the safety lines.
4. **Your day and screen time** (182, 183): the day strip. The mockups brief places it in Vitals; this plan places it in **Camera → Desk → "Your day"** (D12: Vitals is "Keys, allowances & bills"), so the mockup is reused there unchanged. Privacy rows use the existing pattern (no mockup).

**Approval stop:** the four mockups go to the owner with this plan. Under his 27 Nov instruction the build continues meanwhile; the screen code (B's Cameras pane, C's Desk pane and renderer, E's workout pane) is written after the mockups are pushed and follows them unless he objects. A, D, F, G, H and every server part start at once.

---

## 10. Owner steps after deploy (plain, numbered)

**After R8 is merged and deployed:**
1. **Laptop:** open JARVIS in Chrome → Camera → Cameras → Add this camera. Type a name ("Desk camera") and a room ("Study"). Tap **Allow**. When Chrome asks to use the camera, choose your external camera and click **Allow**.
2. **Setup test on the laptop (2 minutes):** in the same place tap **Run the setup test**, sit as you normally do, and wait for "Done". It shows how fast the camera works; nothing is recorded.
3. **Desk coach:** Camera → Desk → **Posture** → sit up straight for the 10-second calibration → tap **Keep a small window on top**. To stop, close the small window or say "Jarvis, cameras off".
4. **Optional, screen time:** (a) download ActivityWatch (free) from its official site and install it on the laptop; (b) follow the one setting in the R8 go-live card (`docs/plans/r8-integration/OWNER-STEPS.md`, written at the I1 join) so the home kit can read it; (c) Vitals → "Screen time" turns from "off" to OK. Skip this and everything else still works.

**After R8.1 is merged and deployed:**
5. **Phone on the tripod:** open JARVIS (the app or Chrome) → Camera → Cameras → Add this camera ("Workout phone", room) → **Allow** → when the phone asks, **Allow** the camera → **Run the setup test** standing where you exercise (2 minutes). Then Camera → Workout, pick an exercise, and do 10 reps while counting yourself: the screen shows whether JARVIS agreed. The reps stay on the phone.

**When the home camera arrives (about 3 Dec):**
4a. Set it up once in its own app, put it where it sees you at the desk (side-on, the whole of you), note its address; then Camera → Cameras → **Check a camera** (step 7) and **Use for the desk**. Posture and the seated and blood-pressure coaches then look through it, on the home laptop.

**Any other home camera you buy:**
6. Before buying: Camera → Cameras → **Check a camera before you buy**, and match the box against the list.
7. After buying: set it up once in its own app and note its address on your network; block its internet in your router; restart it; then Camera → Cameras → **Check a camera**, type its address, user name and password (they stay on your laptop), tap **Check**. "Passed" means it works with JARVIS and your laptop with no cloud service.

---

## 11. Risks, cost and known limits

1. **Chrome may throttle a hidden console tab, slowing the desk window's look.** The look's timer runs on the small window's own clock; a 2-hour browser test proves 1 frame a second; if it fails, the desk coach runs only while the console is visible and says so.
2. **The phone may not keep 15 frames a second with up to four bodies tracked (D6: everyone).** The setup test measures it; the lite model, and "track me" (one body) as the fallback.
3. **Fast moves (228, 235) need more than 15 frames a second.** Counts stay right; punch types and jump height are marked "about" at 15; 30 only if the phone keeps it (D4).
4. **Upside-down poses (237) are not what the pose model is trained on.** "To be tried": if tracking fails in his check, 237 ships as a hold timer with the wall-or-spotter rule only.
5. **One camera can't see depth; side views matter (plank, kettlebell).** Each coach's setup line says which way to face; low visibility pauses the count rather than guessing.
6. **Two bodies crossing can swap who is followed.** A body's track follows its torso centre; where two overlap, the counts of both tracks are marked "about" for that span, and a guest saved by mistake can be merged or deleted later (D6).
7. **ActivityWatch listens on Windows' 127.0.0.1; the bridge's container may not reach it.** Unverified; the go-live card's setting and the bridge's self-test prove it at his step 4; screen time stays off until it works.
8. **The home kit has shown amber (from the scope note, not verified here).** Rows 183 and 377 need it linked; both say so in plain words; nothing else in R8 needs the kit.
9. **Model pins are trust on first use (no vendor hash).** Two CI runs must agree; the console checks every file's SHA-256 against the manifest before use.
10. **The object model's licence may not be permissive.** D9's fallback (SSD-MobileNet v1, already pinned and licensed).
11. **Battery and heat on a 30-minute phone session.** A warning at 20 % battery; the session can pause; the camera stops when the screen locks.
12. **The workbook's success-check wording is not in the repository.** I0 copies it into `ROWS.md`; a stricter figure there wins.
13. **Not medical grade.** Every health row says "practice, not medical advice"; the automated scan; a reading is categorised only by a published table with its source named, never diagnosed.
14. **The home camera arrives about 3 Dec and its model is not confirmed.** Built for any RTSP/ONVIF camera; CI uses a fake RTSP source; rows 181, 182, 227 and 262's checklist are proved on the real camera after it arrives (owner step 4a).
15. **The home laptop may not keep pose at 15 frames a second beside Frigate.** D4: lite when full is too slow; posture needs 1 a second; the seated session says when the laptop is too slow.
16. **Identifying people (D6) relies on R3's face library, which works only on the home camera.** On device cameras `who` is "me" only while one body is in view of his own device; "track <name>" there says it needs the home camera.

**Cost:** ₹0 a month. All looking is on the device; coaches use fixed rules, no AI call; counts and tips use the browser's own voice (no cloud minutes); the `coach_results` tool runs only when he asks the brain (an ordinary brain turn, inside his ₹3,000 limit); Firestore writes stay inside the free tier; the CI job runs on GitHub's free minutes; no new account, key or secret. Equipment for rows 219, 230 and 239 is his own. Built on the Claude subscription.

---

## 12. What checking the scope note found

1. **Vendor paths:** the manifests are `src/jarvis/api/static/vendor/vision/r7-1/MANIFEST.json` and `…/r13-1/MANIFEST.json`, not `vendor/vision/…`.
2. **The R7 models already have a home:** `r7-1/MANIFEST.json` lists `pose_landmarker_lite.task` and `efficientdet_lite0.tflite`, and `scripts/vision_assets.py fetch --models [--object-licence …]` already pins them into `r7-1`; the new `r8-1` release is needed only for the hand model and the full pose model.
3. **An object model is already vendored:** `r13-1` ships SSD-MobileNet v1 (COCO labels, MIT and Apache-2.0, self-checked), used today only for `person`; it is D9's fallback for `objects`.
4. **R13's four tasks are registered in `console-vision.js`**, not in `console-vision-r13.js` (that file holds only their arithmetic); and there are three pixel panels in `tests/test_r13_seams.py:PANELS` (Camera, Wardrobe scan, Try-on photo), not two.
5. **`use()` alone can't drive a coach:** R7 deliberately built no live driver (`INTEGRATION-B.md` 7a); today every registered use case receives every Result of its task, `summary` is never called, and a use case can't post or store anything (`fetch` and storage are banned names). Section 4.3 adds `live`, `tally` and `reset`.
6. **The camera stops when the page is hidden** (`console-camera.js`), so all-day desk posture needs the small window (D10, ADR-52); the scope note didn't cover this.
7. **"Cameras off" today locks this device's camera** (laptop or phone), not only the phone's.
8. **The no-cloud check can't run "before purchase":** a probe needs the camera on the network; before buying, the check is the hardware checklist (4.6).
9. **Vitals is "Keys, allowances & bills"**, so the day strip goes in Camera → Desk (D12).
10. **Version on `main` is `5.2.0`** (`src/jarvis/__init__.py`); I0 sets `8.0.0`. The next free ADR is 47 and the next component C84.

---

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v8.0.4 | 28 Nov 2026, 05:35 IST | R8 | I0: section 11's risks as a numbered list (the Build Book reads a plan's risks from a list); D13's edit mode opens from a right-click on the bar, a long-press, a shortcut and a settings line, and More keeps today's behaviour (the coordinator's correction to the mockup) | 🛠 Mark XXVI |
| v8.0.3 | 28 Nov 2026, 04:40 IST | R8 | The owner's further answers of 28 Nov 04:33 IST: the camera is an **Imou Ranger S2** (RTSP and ONVIF, delivery 3 Dec; built for any RTSP/ONVIF camera); D8 and D9 approved; **D6 final** ("Keep everything and save the results": everyone's results saved, unknown people as "Guest N" per session, rename and merge, Privacy rows per person and guest); **D13 new**, part I "your bar, your way" (move, remove to More, put back, hide the bar; saved per device, versioned; Chat and More can't be removed; the 1920 bar unchanged until edited; builder I); seams S27, S28 | 🛠 Mark XXVI |
| v8.0.2 | 28 Nov 2026, 04:35 IST | R8 | The owner's answers of 28 Nov 04:24 IST: D1, D2 (mockups), D5, D10–D12 approved; **D3 changed** (the ordered home camera for posture and the whole-body desk rows, vision on the home laptop: section 4.5a, ADR-49, builder J); D4 follows it; **D6 changed** (a tracking target, everyone by default, kept only for known people: ADR-48); **D7 changed** (the camera reads the monitor, he confirms, category with its source: ADR-51); D8 and D9 defaults kept; seams S24–S26; links to the Architecture Design Document replaced by plain words (it is kept privately) | 🛠 Mark XXVI |
| v8.0.1 | 28 Nov 2026, 03:50 IST | R8 | First edition: rows (R8's 14, R8.1's 20) with acceptance tests; decisions D1–D12 with safe defaults; the `hands` task and `pose` v2 contract change, the live driver and use-case registry, kept tallies sealed under `coach`, cameras, spots, rooms, health and "cameras off", the no-cloud check, posture, the day strip and screen time, CPU budget, no new dock tab, the desk window, the CI model fetch and the object model's licence; ADR-47 to ADR-54 proposed; privacy and safety; I0 seams S1–S23, builders A–D and E–H with their files and tests; evals; four mockups and the approval stop; owner steps; ₹0 cost, risks; corrections to the scope note | 🛠 Mark XXVI |
