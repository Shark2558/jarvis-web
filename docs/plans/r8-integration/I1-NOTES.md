Version v8.0.1 · 28 Nov 2026, 09:20 IST · Release R8 · Status: Current · Owner: 🛠 Mark XXVI

# R8 — the I1 join (branch `r8-i1`)

The six R8 builders joined into one release on `r8-i1`, from `r8-i0` @ `c4d10ac`, against the plan `docs/plans/r8-vision.md` v8.0.4 (D1–D13 final) and the seams `I0-SEAMS.md` (now v8.0.3 with the join's contract lines). The builders' notes for the join were done item by item; this page says what was joined, every mismatch fixed, what is still open, the owner's steps after deploy and the Book's list.

## What was joined

| Branch | Head | Builder | What it brought |
|---|---|---|---|
| `r8-a` | `bd6a5524` | A | pose v2 with tracks, hands, the seven-segment `digits` reader, the setup test, SUMS8, the fetch-and-hash workflow, `evals/r8/engine.py` |
| `r8-b` | `bedde53e` | B | camera spots and switches, camera health, the no-cloud check (`homebridge/camcheck.py`), the Cameras pane, `evals/r8/cameras.py` |
| `r8-c` | `58b493ff` | C | posture and activity on the home camera, the day strip, screen time through ActivityWatch, the posture nudge, the Desk pane and view renderer, `evals/r8/desk.py` |
| `r8-d` | `092af360` | D | the five webcam coaches, the seated and BP-posture home rules, the AHA table, the water log, `evals/r8/coaches.py` |
| `r8-i` | `2cbca238` | I | your bar, your way (D13): the bar's editor |
| `r8-j` | `a42ee6f3` | J | the home camera's vision on the laptop (`homevision`, the runtime, engines, who is who), HomeLive in the cloud, `evals/r8/home.py` |

Merges: six, in that order, each a `--no-ff` merge commit. **No textual conflict**; `deploy/home/bridge.env.example` merged by itself with both sets of keys (J's `HOMEVISION_*` after `MQTT_PASSWORD`, C's `AW_URL` at the end).

## The wiring (`src/jarvis/api/r8_wiring.py`)

`join_r8(app, s, docs)` runs after R18 and before the gateway (one line in `api/app.py`, whose docstring is two lines shorter so its 741-line guard holds):

- **B's camera setup** (`app.state.camera_setup`, `build_camera_setup`): its home lines from the kit's heartbeat (the cameras Frigate says are online, at the laptop's last-seen time), its home cameras from Home's camera settings, its arm reader for "cameras off" (never changed), and every saved change pushed to the laptop. Privacy's `camera_setup` row.
- **The coaches** (`wire_r8`): the sealed stores, the tracking target (a change is pushed to the laptop), the Faces lookup for "track <name>" (one enrolled, consented person by that name, never a guess).
- **C's screen time and day strip**: `BridgeScreenTime` (`app.state.coach_screen`) and `DayService` (`app.state.coach_day`); `GET /v1/coach/day` mounted; `CoachDayBrief` in the brief's Helpers section (`api/r11_wiring.helpers_brief`).
- **J's HomeLive** on `coach.home`, its reader B's switches and the target (the durable truth); on Home's webhook (`HomeWebhook.join`, new) the coach reports' handler (`CoachReports`: HomeLive first, then C's posture nudge, which never fails the event) and the coach part of the state. The desk coaches (posture, activity, seated, bp-posture) run on every home camera set for the desk that may look now; none after "cameras off" or in a "never" room; the alarm is never in it.
- **Vitals**: `LateCameras` and `LateScreen` in `OwnSources` (Vitals is wired at R4, before R8).
- **The tool**: `coach_results` (R1) through `build_gateway(r8=...)`, with the names he knows people by (you, his guests' labels, his enrolled people's names).
- **The sweep**: `coach_sweep` on the morning tick (only with the token key; unsealed, nothing is kept).
- **REGISTRY** (`jarvis.coach.home`): `posture`, `activity` (C, `create`), `seated`, `bp-posture` (D, `make`); the kit carries all four (checked by building the kit and importing them from it alone).
- **`BRIDGE_VERSION` 0.3.0**: a 0.2.0 kit is told to update. The kit's allow-list for `jarvis.coach.home*` was J's (done on `r8-j`).
- **`api/vision.py`** passes `served8`: `hands` and the full pose model are answered, and `pose_model` says which.
- **`evals/r8/run.py`**: the five parts (engine, cameras, desk, coaches, home), gated in `make eval-mock`.
- I0's stub tests in `tests/test_r8_seams.py`: the category table is D's (AHA 2025) and the three bridge plugins are built.

## Mismatches fixed at the join

| Between | The mismatch | Fixed |
|---|---|---|
| C ↔ B | the camera stopped when the tab was hidden, even with the Desk pane's small window open | `JarvisCamera.keepWhile(win)`: while that window is open and visible a hidden tab keeps the camera on; closing it, or both hidden (the screen locked), stops it; the Desk pane's words say so |
| C ↔ J | J's runtime asked for a `rate` hook, C's posture has `wanted_rate` | the runtime reads `wanted_rate` (one name; J's fake follows) |
| C ↔ J | J ended a body's session 10 s after it left view: posture lost his calibration and activity's "away" minutes showed as "off" | an all-day coach keeps a **known** body's state while it is out of view (`AWAY_KEEP_S`, an hour): no view meanwhile (a tally's view says "Not in view."), the same state when he is back under a new track; a guest's and the session coaches' states end after `LOST_S` as before. J's two tests follow |
| C, J, F ↔ A | angles skew on a portrait phone (x and y are scaled separately) | **every Result carries `aspect`** (the frame's width / height: in the browser from the task's decoded frame, else the camera's canvas; on the laptop from the stream); `console-coach-geom.js` `angle` / `dist` take it; posture, seated and bp-posture scale x by it (`jarvis.coach.home.aspect_of`); `Result.aspect` on the server (optional) |
| F (R8.1) ↔ A | tai-chi and dance compare against a recorded routine | `live(taskIds, {setup})` puts `setup` on every Result as `r.setup` (frozen once; up to 2,000 rows) |
| B ↔ A | "run() must not start or stop the camera" | it doesn't: a test holds the setup test and the task bodies to it |
| B ↔ C | camera health posted twice | the Desk pane posts none (the camera's door does, every 5 minutes): a test holds it |
| B ↔ I0 | the Camera panel's six tabs wrapped 4 + 2; "This device" had two Switch off / Allow | the tabs are 3 × 2 in `console-camera.css` (C's override removed); the panel gives its modes `deviceSwitch(on)` and the Cameras pane hides the panel's own row while this device is in its list (its Allow also ends the device's own lock, inside the tap) |
| A ↔ B, E | "B and E call `choose(model)`" | the Cameras pane's setup test tries the full model and keeps what held (`jarvis_pose_model_v1`); mounting puts it back with `choose` (E is R8.1) |
| A ↔ D9 | `cocoObjects` ready, not wired | `objects` runs on R13's vendored SSD-MobileNet v1 (its file and self-check) while EfficientDet is not installed, COCO ids mapped by `cocoObjects` |
| I0 ↔ D6 | "track me / everyone / <name>" were words only | R5's local router takes them (`coach.track` in the Desk pane); a name is one or two words, never a first word like "my" or "parcel" (`NOT_NAMES`, the same in `jarvis.coach.target`) |
| I0 ↔ R5.1 | `nudge_posture` (I0's kind) missing from R5.1's pinned daytime set | added there |
| C's test | the posture log check read the record's random thread and time digits (flaky) | it reads the message and its extras |
| R7's harness | a keyless server's 404 for `/v1/camera/spots` counted as a console error | it is by design (the door reads no switches): filtered with the others |

## The safety items (must)

- **Above 180/120** the reading's view gives the American Heart Association's own steps first (`jarvis.coach.bp.SEVERE_STEPS`, its source named: wait 5 minutes and measure again; if it is still that high, contact your doctor right away; chest pain, shortness of breath, back pain, numbness or weakness, a change in vision or difficulty speaking: call emergency services, 112 in India). `POST /v1/coach/bp/readings` answers with that view; the pane's twin (`console-coach-bp.js` `steps`, `shown`) says the same words. No diagnosis, no medicine, no dose: the not-medical scan passes them. Tests: `tests/test_r8_i1_safety.py`.
- **The `digits` reader** meets D's acceptance test, now run (never skipped) on 300 of D's screens: 297 right, none wrong, 3 refused (seeds 5 and 123: 298 and 299 of 300). A screen it can't be sure of is refused in words (`CANT_READ`: "I can't read that screen. Please type the numbers, or hold it up and retake.").
- **Posture nudges only to him**: `on_report` nudges for `who` "me" only; a guest's or an enrolled person's slouch is kept as a tally (D6) and nudges nobody. Tests: `tests/test_r8_c_posture.py`, and through the joined handler `tests/test_r8_i1_wiring.py`.

## Model pins

`gh workflow run vision-models.yml --ref r8-i1` was **refused** (HTTP 404: GitHub dispatches only workflows on the default branch, and `vision-models.yml` is on the R8 branches only). The pins are **left as they are**: the `r7-1` and `r8-1` manifests, `engines.POSE_MODELS` and `deploy/home/models/MODELS.txt` stay unpinned and agree (the models say "not installed"; the laptop loads nothing unpinned). After the workflow reaches `main` (or a pull request touching the vendored files runs it), the Workshop reads the two fetches' hashes, pins them in both manifests, `POSE_MODELS` and `MODELS.txt`, and runs `python scripts/vision_assets.py sums`. EfficientDet-Lite0's licence is still unread (A: its card page timed out), so D9's fallback serves `objects`.

## Checks (once, on the joined tree)

Every new and touched test file, unit and browser (the R8 browser files with `JARVIS_BROWSER_TESTS=1`, and R7's and R13's camera suites after the 404 filter), `ruff` and `ruff format` on every changed file, `mypy` on the touched modules, `PYTHONPATH=src python scripts/check_doc_versions.py` (all documents pass) and `python evals/r8/run.py --mock` (41 of 41, every part's control fails it). Counts: the 25 new and touched unit test files, **727 passed**; the three R8 browser files, **28 passed**; R7's and R13's camera browser suites also pass with the 404 filter (run beside the dock and desk files: 22 and 21 passed); `ruff check src tests evals` clean. Open:

- `tests/test_arch_coverage.py::test_the_real_guide_passes` fails (45 items: R8's console modules and `jarvis.coach` named by no card, the API host `storage.googleapis.com`): the Book step's.
- `mypy` reports one error in `src/jarvis/memory/redis_store.py:67`, the same on `r8-i0` (the installed redis stubs), not R8's.

## Known limits

- **The BP reading card**: no pane yet draws the camera's reading → confirm → result card (D's module has the rule, the engine the reader, the server the view with the steps). The safety words are in the server's answer and the pane's twin; the card is the review's to place (the Desk pane).
- `DELETE /v1/coach/people/{who}` still answers 501; a person's or every guest's results go through Privacy's `coach_people` and `coach_guests` rows (passkey).
- "me" on the home camera is a body that came into view alone and is nobody else; preferring his enrolled face needs Faces to know which person is him (no such mark yet). With his face enrolled he is named by his `fp_` id, and his posture nudges then need that id treated as him: the review's call.
- The four desk coaches run whenever a home camera is set for the desk (the Desk pane's words); there is no per-coach switch. Seated and BP-posture sessions start by themselves when he sits.
- Workbook wording (asked 28 Nov): row 184 "a family member leaves no record" is superseded by D6; row 217 "every camera light off" can't hold for the home camera while the alarm is armed (D11).
- B's Faces local page has no login form yet: the no-cloud check uses the login in `HOMEVISION_RTSP_URL`.
- If the camera can't serve a second stream beside Frigate's, the coaches say the stream is down.

## The owner's steps after deploy

1. **Camera permissions**: the first Start tap on the laptop (and on the phone) asks the browser for the camera: allow it for JARVIS's address. Chrome's small window on top needs nothing more.
2. **Update the home kit** (0.3.0): Home says the kit is out of date; download it and run its setup again.
3. **The Imou on 3 Dec**: set it up once in its own app, place it side-on to the desk, then on the home laptop `powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -HomeCamera` (its sub-stream address and login stay in `bridge.env`). In Camera → Cameras → **Check a camera**, type its address: the first stage checks ONVIF, its profiles, both streams and H.264; then block its internet in the router and restart it, **tick "I blocked its internet and restarted it"**, and check again (five rounds). Then **Add as a home camera** and set it for the **Desk**.
4. **Enrol his face once** in the Faces panel (his own consent) so "track me" follows him on the home camera by face, not only as the body alone in view.
5. **Optional: ActivityWatch** on the laptop (free; its data stays there) for screen time, with the R8 go-live card's one setting (`AW_URL`) so the bridge can reach it.
6. **The posture nudge** is off until he switches it on in Helpers → Nudges.

## For the Book step

`PYTHONPATH=src python -m jarvis.buildbook.gen pages --check` on this tree: 169 pages (93 ok, 75 stale, 1 failing) and 27 narrations (26 ok, 1 failing). To refresh: **76 pages and 1 narration**.

- Narration: `story_planned` (a typed number on line 43).
- Failing and stale: `pg_chapter_planned` (a typed number; its flow's refs: `docs/plans/r8-vision.md` new, `r5-2-voice.md` gone).
- Stale: `pg_card_c01`, `c02`, `c04`, `c05`, `c28`, `c38`, `c39`, `c40`, `c45`, `c46`, `c47`, `c49`, `c51`, `c55`, `c56`, `c57`, `c59`, `c60`, `c61`, `c62`, `c63`, `c67`, `c68`, `c72`, `c74`, `c80`; `pg_chapter_answers`, `costs`, `data`, `example`, `setup`, `technology`, `what`; `pg_module_alerts`, `android`, `approvals`, `brain`, `calls`, `console`, `delivery`, `helpers`, `home`, `vitals`, `voice`, `wardrobe`; `pg_screen_camera`; `pg_service_anthropic`, `bhashini`, `cloud_run`, `cloud_scheduler`, `firestore`, `frankfurter`, `frigate`, `gemini`, `gmail`, `google_calendar`, `google_cloud_speech_to_text`, `google_cloud_text_to_speech`, `google_drive`, `google_maps_platform`, `google_photos_picker`, `google_sign_in`, `google_tasks`, `home_assistant`, `microsoft_azure_speech`, `mosquitto`, `ollama`, `openai_compatible`, `redis`, `sarvam`, `tailscale`, `tavily`, `telegram`, `web_push`, `youtube_data_api`.
- New cards to write (C84 onwards, plan 7.3): the coaches (`src/jarvis/coach`), the camera setup, the Desk pane, the home vision plugin, and I's bar editor (C84–C89 set, I's note), so `test_arch_coverage` passes.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v8.0.1 | 28 Nov 2026, 09:20 IST | R8 | First edition: the six merges, the wiring, every mismatch fixed, the safety items, the model pins (refused, left), the checks, the known limits, the owner's steps and the Book's list | 🛠 Mark XXVI |
