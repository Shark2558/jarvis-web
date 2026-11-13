Version v7.0.1 · 13 Nov 2026, 16:50 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVI

# R7 — I0 notes (the joins for "Mobile, watch and phone camera")

Written by the R7 I0 integrator in the Workshop (🛠 Mark XVI) while building I0 on `r7-i0`. The
plan is `docs/plans/r7-mobile.md` (v7.0.4, Status Ready); the builders' brief is
`BRIEF-COMMON.md` and the server ⇄ app contract `phone-contract.md`, both in this folder.

## 1. The base

- `origin/r7-i0` @ `9ca8379` (the plan v7.0.3 and review 1, cut from `r11-1-i1` @ `bbe056d`) took
  `origin/main` @ `5519e2d` (R11.1 live, v11.1.1: R11.1's integrated fixer and hotfix 1) by a merge
  commit, `60958b3` ("merge main (R11.1 live, 5519e2d) into r7-i0 for I0"). No conflict; nothing
  rebased or force-pushed. Gate G0 is met.
- The full unit suite on that merge (Python 3.12) before any I0 change: 13,589 passed, 119 skipped.

## 2. Stale lines in the plan (v7.0.3), read line by line against `5519e2d`

37 stale lines or passages; every one is corrected in v7.0.4 (its change log row lists them).

1. Line 1: Status Draft and owner Mark XV → v7.0.4, Ready, 🛠 Mark XVI.
2. L7–11: the base (`r11-1-i1` @ `bbe056d`, G0 pending), the trailer `JARVIS-Mark: XV` and the PR
   title's "Mark XV" → `main` @ `5519e2d`, Mark XVI.
3. L28–32 (limit 3), L219 (fit table), L501–503 (three writers), L524–528 ("Which apps write"),
   L1029–1030 (owner step A1), L1105–1109 (question 3), L1159 (answers row 3), L1173 (research
   "So:"), L1192–1196 (risk), L1264 (not verified live): written before the owner's check of
   13 Nov 2026, 15:19 IST. NoiseFit DOES write steps and calories; no sleep entry yet because the
   watch was not worn overnight; sleep and heart rate stay "to be seen" (Needs you first). The
   "only through Google Fit" research is superseded.
4. L57–65 Gate G0 ("not yet merged into `main`"): met.
5. L67–69 and the heading L71: the file:line facts were from `bbe056d`; re-read on `5519e2d`.
6. L75: `api/app.py:557–568` → `:558–569` (R11.1 I1 grew `app.py` by one line above it).
7. L113: `documents/pictures.py:49` → `:50`.
8. L120 and L977: `console-r111-files.js:183`, `:309` → `:184`, `:310`.
9. L133–135 (line budgets): `api/app.py` is 732, not 731; `console.js` 753 and `core/brain.py` 704
   were not named; I0's results added (`console.html` 782, `console.js` 761, `app.py` 735).
10. L140–145 (this workspace): measured again; developer.android.com is also unreachable, the
    Gradle tag on raw.githubusercontent.com is reachable, github.com's release pages answer 403.
11. L629 (D21) and L931 (seam 14): the boot 423 reader is `console.js:745`, not `:740`.
12. L691–704 (D23 pins): "every pin *unverified*", "I0 confirms on the Studio-to-plugin table" and
    "a Kotlin version that runs on JDK 25" → the pins confirmed on Google's pages on 13 Nov 2026
    (Rabbit 2 → AGP 7.1–9.5; AGP 9.5.1, Gradle 9.6.0 minimum and default, SDK Build Tools 36.0.0,
    JDK 17 minimum and default, API 37 at most; Kotlin 2.4.10 for `core`; JDK 25 not stated, so CI
    on JDK 17 and Studio's Gradle JDK 17 or 21 as the fallback).
13. L746 (D26): "checked on `bbe056d`" → re-checked on `5519e2d` (the same four facts hold:
    `photos/edge.py:173–180`, `home/kit.py:198–207`, `buildbook/seal_index.py:130–136`, the two
    scripts check format only).
14. L862 (seam 1): `tests/test_r11_1_seams.py:73` also pins the version; the plan named only
    `tests/test_about.py:24` (both pinned 11.1.1).
15. L900 (seam 8): "it is 731 now" → 732.
16. L950 (seam 17): the guide's L1874 (the glossary's vision libraries) also names ML Kit; missing.
17. L959 (seam 20): `api/r11_1_wiring.py:100–138` → `:100–148` (R11.1 I1 added the phrase and
    brief readers).
18. L971 (seam 23): `brief/service.py:688–694` → `:691–697`.
19. L1102–1103 (question 2), L1158 (answers row 2), L1204–1205 (risk "Studio older than the
    plugin"), L1280–1282 (not verified live: the toolchain): the Studio question is answered by
    Google's table; what is left is JDK 25 and the wrapper checksum.
20. L1417 and S36 (sources): S36 was "not reachable, confirmed at I0"; now read (13 Nov 2026, by
    the Workshop), and S50 (the Studio-to-AGP table) is added.
21. Appendix A: the 24 hand-held rows were a review's count; now settled (the owner's head start).
22. A plan fact that is NOT stale but was checked: the counts (38 alert kinds, 46 permission rows,
    18 key purposes, 21 dock tabs, `PERSONA_VERSION` "p11.1" in 17 test files), every other
    file:line in the plan (173 references read with a script that maps `bbe056d` to `5519e2d`),
    the five 423 readers and the `data-sheet-open` pins.

## 3. What I0 built (seams 1–27)

Tests first: `tests/test_r7_seams.py` (94 cases with the hook file) and
`tests/test_r7_telegram_hook.py` were written before the code and failed (no module) before it.

1. `__version__` 7.0.0; `test_about.py:24` and `test_r11_1_seams.py:73` moved.
2. The build book names the release from the repository's own `src/jarvis/__init__.py`
   (`fallback.label_from_version`: 7.0.0 → R7, 11.1.x → R11.1, 11.0.x → R11), used by both
   `plans.release_label` and `fallback._label`; without that file, the highest plan as before.
   `plan_paths` lists this release's plan first, then the rest newest first. The real repository
   now reads "R7" with `r7-mobile.md` first; the determinism and real-plans pins moved.
3. Layers: `mobile` and `phone` L1, `vision` L2, `watch` and `sos` L5. The snapshot's binaries
   gained `.jar .ttf .task .tflite .gz .webp`; `android/**/build/` is never read ("build output").
4. The sixteen settings of D25 with pinned ranges (`config.py`).
5. Alert kinds 38 → 43 (`sos_sent`, `phone_linked` urgent; `sos_contact_left` important and a
   daytime ring; `phone_unlinked`, `watch_stale` info), in `alerts.py` (`R7_ALERT_KINDS`),
   `notify/ports.py`, `notify/policy.py`, `notify/held.py`, `console-alerts.js` and
   `buildbook/plain.py`; `sos_sent` and `phone_linked` joined `NO_SWITCH`; `sos_sent` joined
   `NO_CAP_KINDS`. Every pinned count moved (R3, R6, R11, R11.1 seams; R5.1's daytime set).
6. Permission rows 46 → 49. **Placed right after Camera (the end of R3's block) and before Vitals**:
   `vision` ("Camera results", R1, `vision_*`), `watch` ("Watch and sleep", R2: `watch_*` and
   `sleep_*` at R1 and R2), `sos` ("Emergency SOS", R1, only `sos_status`). R11.1's pin between
   Kitchen and Maps and "Maps and YouTube last" both hold. `RISK_OF`, `TOOL_OF`, `EXPECTED` and the
   counts moved.
7. Key purposes 18 → 21: `watch`, `sos`, `vision` (and their words in the book).
8. `jarvis.mobile.ports` (`MobilePart`, `MobileContext`, `PARTS` = shell, vision, phone, body;
   `TOOL_FAMILIES`, `ROUTE_PREFIX`, `STATUS_ROUTE`, `COLLECTIONS`, `PhoneRequest`, `PhoneReply`,
   `PhoneHandler`, the door's routes, owners and caps, `LAUNCH_WORDS`, `PACKAGE`, D21's
   never-locked list), `jarvis.vision.results` (the Result schemas), the port core of
   `console-vision.js`, `api/r7_wiring.py` (a part that breaks its contract is left out), the
   stub parts (`api/app_shell.py`, `vision/part.py`, `phone/part.py`, `watch/part.py`) and status
   routes (`/app/status`, `/v1/vision`, `/v1/phone`, `/v1/watch`, `/v1/sos`). Slots in `api/app.py`
   (one import, `wire_r7`, `install_r7_routes`, `r7=` for the gateway, the app lock's slot before
   R6's show lock, `**r7.BODY_CAPS`), `tools/setup.py` (`r7: Sequence[Tool] = ()`),
   `api/personal.py` (the parts' privacy rows) and `api/r11_wiring.py` (the parts' clock and daily
   jobs, phrases and brief lines ride the helpers', after R11.1's). `app.py` stays at 735: four
   comment lines were joined to make room.
9. The door's fake (`tests/r7_fakes.py`: `FakeDoor`, `sign_request`, `phone_key`,
   `load_vectors`), `phone-contract.md` and `tests/fixtures/r7/phone_vectors.json` (nine cases:
   one per route, `sos_no_location`, and `changed_body`, `other_key`, `changed_path`,
   `stale_time_shape`; the private keys were made in memory and never written down).
   `jarvis.mobile.contract` writes the signing string, the header and the one JSON form (integers
   only: coordinates are micro-degrees) and refuses a query string or any other path.
10. Console: `console-dock.js` builds the More sheet's 20 entries from the dock (same order, words
    and markup; the descriptions moved into its `DESCRIBE`), so `console.html` freed 19 lines and
    gained six: the manifest link, the Camera dock tab (the 22nd, last), its panel section (three
    lines, Helpers' frame) and the loader `console-r7.js` (795 → 782, pin moved to ≤ 782). The
    deck knows the panel (`ORDER`, a default place). Every `data-sheet-open` pin now reads the built
    sheet; the dock count and "the last tab" pins moved (Helpers is second-to-last); `PANELS` in
    `ui_checks.py` gained `camera`; C01 lists the Camera tab.
11. CSP: exactly `manifest-src 'self'` added (the four exact pins moved). `GET /` answers 302 to
    the same address without `do` and `open` when `Sec-Fetch-Site: cross-site` (every other word,
    `reauth` too, stays). The vision route `/static/vendor/vision/<release>/<name>` serves only what
    that release's `MANIFEST.json` lists with a matching SHA-256 (a year-long cache), and every
    JavaScript file from it carries the console's CSP header (worker scripts).
12. Helpers: a fifth sub-tab "Watch" (`helpers.kinds.TABS`; not an R11 part) and the stub
    `console-helpers-watch.js` loaded by `console-helpers.js`.
13. Voice: `voice/commands.py` gained `R7_PHRASES` (twenty `camera.off` phrasings, five `sos.open`),
    all speech hints; nothing turns a camera on. `test_r5_seams.py` lets `console-camera.js` be the
    second place `getUserMedia(` may appear and checks the R7 phrases are hints.
    `JarvisVoiceLoop` is unchanged (a test checks it offers no way to start a turn).
14. All five 423 readers read the `error` code (`lockedBy` in `console.js`: `device_locked` →
    `jarvis:device-locked` and `data-locked="device"`, anything else → R6's show;
    `console-book-talk.js` ignores `device_locked`). The app lock's slot (`AppLockSlot`, pure
    ASGI): a pass-through until Part C's `services["app_lock"]`; then 423 `device_locked` outside
    D21's list, 503 `lock_unreadable` when the check fails, 4423/4503 for a websocket.
15. `telegram/service.py`: the one hook (`self.sos`, bound by `wire_r7` from Part D's
    `services["sos_hook"]`). A `/start sos-…` goes to the hook and never to `finish_pairing`; a
    known contact's `/stop` reaches the hook before the turn-away. Tests: a wrong SOS word leaves
    the pairing counter unchanged; a pairing code never joins SOS; a contact's `/stop` reaches the
    hook; anyone else is still turned away and audited.
16. `.github/workflows/android.yml` (first version), `.gitignore` (all eleven entries),
    `android/.gitattributes`, and the Android project's first files: `settings.gradle.kts`,
    `build.gradle.kts` (the two plugins declared once, `resolveDependencies`), `gradle.properties`,
    `gradle/libs.versions.toml` (AGP 9.5.1, Kotlin 2.4.10, once), `version.properties`
    (versionCode 1), the wrapper scripts and jar from Gradle's tag `v9.6.0` and
    `gradle-wrapper.properties` (Gradle 9.6.0, with the `distributionSha256Sum` CI read: section 4).
17. The guide (v7.0.1): cards C62–C65, PLANNED, with what I0 built; the Mobile departure (a Trusted
    Web Activity, instead of Capacitor); L196 unchanged (it is right); the phases table, the
    decisions log (the R6.1 row reworded, an R7 row), the roadmap (R7, and R8 without ML Kit), the
    glossary (Capacitor, Health Connect, the vision libraries, SOS, and a new "Trusted Web Activity"),
    four technology rows, the R7 collections and key purposes. `arch_coverage.py` and
    `check_doc_versions.py` pass.
18. `evals/r7/run.py` with the stubs `shell`, `vision`, `phone`, `body`, `needles` and I0's own built
    part `contract` (the shared vectors; its control flips a byte of every body and fails it).
    Gated in `evals/run_all_mock.py` from I0.
19. The persona and `PERSONA_VERSION` "p11.1" are untouched (a test holds it until I1).
20. `MobilePart` carries every `FixPart` field (a test compares them).
21. `watch_*`, `sleep_*` and `vision_*` joined `PRIVATE_PATTERNS`; `test_telegram_tool_guard.py`
    builds the R7 parts through the real wiring into its linked gateway and checks every
    `watch_`/`sleep_`/`vision_` tool of the BUILT registry (and the planned names) is denied on
    Telegram by default; `sos_status` stays answerable.
22. The new tool-name words (`sleep`, `last`, `night`, `week`, `watch`, `today`, `sos`, `vision`,
    `results`) are nouns in `tests/test_r11_1_b_guard.py`'s `TOOL_NOUNS`, with an R7 tool list
    (`note` and `status` were already known).
23. The brief's sleep line, pinned: `brief.models.SleepLine {minutes 0–1440, start, end (HH:MM),
    source: watch | phone | typed}`, `BriefData.sleep = None`; `render_text` (the e-mailed copy)
    does not read it (a test).
24. `buildbook/gen/libs.py` `VENDORED`: the six vision licence files Part B adds under
    `static/vendor/vision/` (MediaPipe Tasks Vision, its models, tesseract.js, its core, the
    English data, zxing-wasm).
25. `console-r7-send.js` (`canAsk`, `ask`, `attach`, `vault`, `sentToday`, `line`; the counter
    per day in this browser) over `JarvisAttach.add(files)` (exposed in `console-attach.js`) and
    R11.1's `shrink` (which now also redraws a `.webp`, always as a JPEG) and its cost line (inside
    `JarvisChat.send`). `/v1/brains` answers `sees_pictures`; the console's brain detail has `sees`.
26. `BRIEF-COMMON.md`, with "ask nothing before sign-in" and the per-part
    `test_before_sign_in_the_block_asks_the_server_nothing`.
27. Passkey purposes `phone_link` (target `pl_<12 hex>`) and `device_unlock` (target
    `ss_<24 base64url>`) in `Purpose`, `TARGETED_PURPOSES`, the exact targets and the page's
    allow-list.

Not done, on purpose: no part builder was started, no pull request opened. Nothing in the plan's
I0 list was left out; where a seam needs a download this workspace cannot reach, section 4 says
what CI or the owner's Studio proves.

## 4. What only CI or the owner's Android Studio can prove

Refused from this workspace (13 Nov 2026): Google's Maven, Gradle's distributions and plugin
portal, Maven Central, developer.android.com and storage.googleapis.com. So:

- **`distributionSha256Sum`** for `gradle-9.6.0-bin.zip`: CI's first run on `r7-i0` (run
  `43414082880`, commit `6d0c34b`) read the official sum from `services.gradle.org`
  (`bbaeb2fe…2a529a01`), failed `wrapper-pin` by design, and I0 pinned that value; the job checks it
  on every run.
- **The wrapper jar**: taken from Gradle's tag `v9.6.0` (SHA-256 `497c8c2a…a9c7`; it is the jar of
  9.6.0-rc-3, which that tag's own wrapper uses). CI's `gradle/actions/wrapper-validation` checks it
  against Gradle's known sums.
- **AGP 9.5.1 and Kotlin 2.4.10 exist and resolve: proven** by that same run's `build` job (green in
  52 s): the wrapper jar validated, Gradle 9.6.0 downloaded and ran on Temurin JDK 17.0.21, and the
  root project's plugin block resolved both pins ("BUILD SUCCESSFUL"). Still for CI: every library
  once Part E's modules use them (android-browser-helper 2.7.4, AndroidX, Health Connect 1.1.x).
- **JDK 25**: Google's pages do not state it is supported. CI runs on JDK 17. The owner's first
  Studio sync (step C3) is the proof; the fallback is Studio's Gradle JDK 17 or 21.
- **The Android build itself**, lint, the JVM tests, `apk_check.py` and the merged manifest's
  allow-list: CI, once Part E's modules exist (those steps are skipped until then).
- **MediaPipe's two model files**, their sums and the object model's licence: from CI or the
  owner's laptop (Part B), before `pose` and `objects` can say anything but "not installed".
- **The menu words** for "Build APK(s)" in Rabbit 2 (owner step C5) and OxygenOS's battery setting
  (step C14): not checked here.

The first push of I0 ran `android.yml` (it touches `android/**`): `build` passed and `wrapper-pin`
failed by design, printing the sum; the next push carries the pin.

## 5. For the owner

Nothing blocks the parts. Defaults that stand: the package `io.github.shark2558.jarvis`, the
version `v7.0.0` ("R7"), the shell (a Trusted Web Activity). Open, with safe defaults: a NoiseFit
sleep or heart-rate entry after a night with the watch on, and App priority with NoiseFit first
(steps A1, A2); the emergency contacts (question 4); and, after the first CI run, nothing for him
unless the first Studio sync stops on the Java version (step C3 says what to set).

## 6. Sizes after I0

| File | Lines | Guard |
|---|---|---|
| `src/jarvis/api/static/console.html` | 782 | ≤ 782 (was ≤ 795), < 800 |
| `src/jarvis/api/static/console.js` | 761 | ≤ 800 |
| `src/jarvis/api/app.py` | 735 | ≤ 735 |
| `src/jarvis/tools/gateway.py` | 760 | ≤ 760 (unchanged) |
| `src/jarvis/core/brain.py` | 704 | ≤ 770 (unchanged) |
| `src/jarvis/api/static/console-dock.js` | 283 | ≤ 800 |
| new stylesheets (four stubs) | 2 each | ≤ 150 (≤ 300 for any new CSS) |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 13 Nov 2026, 16:50 IST | R7 | First edition: the base and the merge, the 37 stale lines found in the plan v7.0.3 and their fixes, what I0 built for each of the 27 seams (and where it placed what the plan left open), what only CI or the owner's Studio can prove, the owner's open points, the sizes after I0 | 🛠 Mark XVI |
