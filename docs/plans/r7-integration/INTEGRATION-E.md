Version v7.0.1 · 13 Nov 2026, 20:05 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVII

# R7 — Part E, the Android app: what was built, what CI proved, what I1 needs

Part E of `docs/plans/r7-mobile.md` (v7.0.4): deliverables 1, 3, 4, 5 and 6 on the phone; D1, D9, D10,
D22–D24. Branch `r7-e` from `r7-i0` @ `9d96320`. Built in the Workshop (🛠 Mark XVII). This workspace
cannot reach Google's Maven, Gradle's services or Maven Central, so GitHub Actions
(`.github/workflows/android.yml`) is the compiler and the test runner; the owner builds the app he installs
in Android Studio on his laptop (`OWNER-STEPS.md`).

## 1. What was built

| Deliverable | State | Where |
|---|---|---|
| `core`: the door's signing string and header, the one JSON form, the payloads (link, hello, health, inbox, sos), the X9.62 key from Keystore's SPKI | built, CI-proved against the shared vectors byte for byte | `android/core/.../Door.kt`, `Json.kt`, `Payloads.kt` |
| `core`: the SOS machine (idle → holding → countdown → sending → sent / cancelled / failed) | built; a cancel at every 50 ms of the hold or the countdown sends nothing | `SosMachine.kt` |
| `core`: the Health Connect day builder (aggregate only; one writer per night, watch before phone before others) | built; three steps writers give one count; two writers keep NoiseFit's; the phone alone is kept and named "phone" | `DayBuilder.kt` |
| `core`: launch words, notification channel by tag, inbox "seen" list and file rules, the SOS text | built | `Rules.kt`, `SosText.kt` |
| The icon's launcher (Trusted Web Activity, always `/?source=app`, opens only once linked, no WebView fallback) and the share entry | built, compiles, lint clean | `app/.../shell/IconLauncherActivity.kt`, `LaunchGate.kt` |
| The second, unexported launcher for the Talk tile and the Talk and Camera shortcuts (one allowed word) | built | `shell/ScreenLauncherActivity.kt`, `res/xml/shortcuts.xml` |
| The notification service and its three channels (Urgent, Alerts, Nudges by tag) | built | `shell/JarvisDelegationService.kt`, `NotifyChannels.kt` |
| The Talk and SOS tiles (`startActivityAndCollapse(PendingIntent)` from Android 14) | built | `shell/Tiles.kt`, `TalkTileService.kt`, `SosTileService.kt` |
| The set-up screen: link code, phone key (Android Keystore, P-256), signed client, notifications, Health Connect, location (precise and approximate together), one folder, tiles; screenshots blocked | built | `link/*.kt`, `res/layout/activity_setup.xml` |
| The Health Connect reader, its 6-hourly job and the privacy page with both entries | built | `health/*.kt` |
| The SOS screen: 10-second countdown, the door's SOS, the SMS app filled in, dial buttons, "I'm safe"; edge to edge inside the system bars; from the lock screen | built | `sos/*.kt`, `res/layout/activity_sos.xml` |
| The DigiLocker folder (one picked folder, hourly, three files a run, each once) | built | `inbox/*.kt` |
| `scripts/apk_check.py` (standard library only; decodes the binary manifest itself) | built, CI-proved on the real APK and against Gradle's merged manifest | `scripts/apk_check.py` |
| `android.yml` (resolve, JVM tests, `personal` build, merged manifest, apk_check, lint, artifact "not for installing", the controls job) | built, green | `.github/workflows/android.yml` |
| Python static tests of the manifest, the Gradle files, the Kotlin sources, the workflow and apk_check | built: 117 tests | `tests/test_r7_e_*.py` |
| `OWNER-STEPS.md` | written | this folder |

## 2. What CI proved (no secret, placeholder host `jarvis.invalid`, a throwaway debug key)

| Run | Commit | Result | What it proved |
|---|---|---|---|
| `43439904145` | `dcd5026` | failed (2 steps) | Every pinned library exists and resolves on Google's Maven and Maven Central; `core`'s JVM tests: **68 passed**; all four controls made them fail; the `personal` build **compiles and assembles** on AGP 9.5.1, Gradle 9.6.0, JDK 17, compile/target SDK 36; lint 0 errors. Failed: `resolveDependencies` (an AndroidTest classpath resolves the app itself) and `apk_check.py` (only library hosts: the reviewed list was built from this report; every reachable part and permission already matched, and the decoder agreed with the merged manifest) |
| `43441109044` | `5da50e0` | failed (1 step) | `apk_check.py` **passed** on the real APK (`--merged` agreed); lint 0 errors, 35 warnings (cleared in the next round); `resolveDependencies` still failed (a unit-test classpath resolves the app itself) |
| `43442154933` | `8afd9e5` | **green, all three jobs** | `resolveDependencies` (`:app` 6 classpaths, `:core` 2) with no Gradle deprecation warning; `core` 68/68; `assemblePersonal`; `apk_check.py` passed; lint "No issues found."; the artifact `jarvis-android-ci-not-for-installing` kept 7 days; `controls`: `dedupe_off`, `cancel_ignored`, `json_form`, `launch_words_open` each made `core`'s tests FAIL; `wrapper-pin` green |

The newest stable versions CI's information step printed (13 Nov 2026): android-browser-helper 2.7.4,
androidx.browser 1.10.0, androidx.core 1.19.1, androidx.work 2.12.0, Health Connect client 1.1.0. Pinned:
2.7.4, 1.10.0, **1.17.0**, **2.10.5**, 1.1.0 (see Deviations 4).

The reachable parts in the built app, as CI's report lists them: the icon's launcher, the notification
service, the two tiles (`BIND_QUICK_SETTINGS_TILE`), the rationale activity and the alias behind
`START_VIEW_PERMISSION_USAGE`, WorkManager's job service (`BIND_JOB_SERVICE`) and diagnostics receiver
(`DUMP`), profileinstaller's receiver (`DUMP`) and Health Connect's own client service. The library's
`ShortcutTrampolineActivity` and `ColdShortcutActivity` are removed. Permissions: the nine the app declares
plus WorkManager's network state, wake lock and boot, and AndroidX core's own signature permission;
`FOREGROUND_SERVICE` is removed.

## 3. Checks run here

| Check | Result |
|---|---|
| `pytest tests/test_r7_e_*.py` | 117 passed (apk_check 33, sources 25, manifest 17, gradle 12, workflow 6) |
| Guard tests (`test_r7_seams.py`, `test_r7_telegram_hook.py`, `test_r11_1_seams.py`, `test_arch_coverage.py`, `test_telegram_tool_guard.py`) with Part E's | 346 passed |
| `ruff check` / `ruff format --check` on `src tests evals scripts` | clean (1,538 files) |
| `mypy src` | 9 errors in 3 files: the 9 pre-existing ones (Part E changes no file in `src`) |
| `evals/r7/run.py --mock --part contract` | 10/10; its control fails it. Part E has no eval part of its own (the runner has none); its proofs are CI's |
| `scripts/check_doc_versions.py`, `scripts/arch_coverage.py` | pass |
| `python -m jarvis.buildbook.gen --check` (with every Part E file committed: Kotlin, fonts, licences) | the book is "R7", two builds byte-identical, its secret scan passes |
| Browser tests | none: Part E has no web screen |

## 4. The contract as the app uses it (for Parts A, C and D)

- **Link** (`POST /phone/link`, unsigned): the contract's body in its key order, `model` `"phone"`,
  `app_version` from `version.properties` (`7.0.0`), the fingerprint as 64 lowercase hex, the public key as
  the 65-byte X9.62 point in lowercase hex. The app reads `{"device_id": "ph_<12 hex>"}` from a 2xx answer; a
  4xx is "that code was not accepted", anything else "try again".
- **Hello** (`/phone/v1/hello`): sent at linking, whenever the set-up screen opens, and before every
  6-hourly watch read. The app reads only `{"sos": {"label": "<owner's name as family sees it>",
  "contacts": [{"label": "…", "phone": "…"}]}}` from its answer (at most five; numbers kept as `+` and
  digits; stored sealed on the phone for the offline SMS screen).
- **Health** (`/phone/v1/health`): `writer` is the writing app's package name, as the contract says:
  `com.noisefit` is the watch, `android` the phone; anything else is "other". Steps with a count but no
  origin carry `"unknown"`. Days are the phone's own time zone; a night belongs to the day it ends on;
  overlapping sessions are one night and keep one writer.
- **SOS** (`/phone/v1/sos`): `kind` `real` (tile, shortcut), `test` (set-up's Test SOS), `safe` ("I'm safe",
  after a confirm). The app reads `{"reached": <int>}` from a 2xx answer for "Sent to N people".
- **Inbox** (`/phone/v1/inbox`): `Content-Type: application/octet-stream`; the type is sniffed from the
  file's bytes; the name has no folder and no control character (at most 120 characters).
- **Launch words**: the icon opens `/?source=app`; the tile and the Talk and Camera shortcuts open
  `/?source=app&do=talk` and `…&do=look`. The SOS tile and shortcut open the NATIVE SOS screen (no `do=sos`
  from the app). The share entry posts to `https://<host>/app/share/in` (multipart; `title`, `text`, `url`,
  `files` of JPEG, PNG, WebP, PDF).
- **Notification tags**: the kind is read from the tag, or from after the last `#` of Chrome's own tag form
  (a leading `1` dropped); an unreadable tag goes to Alerts.

## 5. Needs I1

1. Part C: `/.well-known/assetlinks.json` must give `sha256_cert_fingerprints` as Digital Asset Links
   writes them (upper-case hex pairs joined by `:`); the app sends the same 32 bytes at linking as 64
   lower-case hex without colons (phone-contract.md section 1). Without that conversion Chrome never
   vouches for the app and a browser bar shows.
2. Part C: the hello answer's SOS part in the shape of section 4 (`sos.label`, `sos.contacts[].label`,
   `sos.contacts[].phone`); without it the SMS screen has no numbers ("No numbers are saved…").
3. Part C: link codes must be 8 characters of `A–Z` and `0–9` (the app upper-cases and drops spaces and
   hyphens); link answers `{"device_id": …}` with 200 or 201; `model` arrives as `"phone"`.
4. Part D: the SOS answer may carry `{"reached": n}`; without it the screen says "Sent on Telegram.".
5. Part D: the brief's "from your watch / from your phone" maps `com.noisefit` to the watch and `android` to
   the phone. A phone maker's own health app (another package name) arrives as itself and the app ranks it
   "other"; I1 decides whether the server treats every non-watch writer as the phone.
6. Part A: alerts land in Urgent and Nudges only if Chrome passes the web notification's `tag` (the kind) in
   the delegated notification's platform tag; if it does not, everything goes to Alerts (not verified live).
7. I1: the Workshop copies `android/` to `C:\Jarvis\android` and writes `jarvis.host=<address>` (host name
   only, no `https://`) into `android/local.properties`; `core`'s JVM tests read
   `../tests/fixtures/r7/phone_vectors.json`, which the laptop never needs (the app's build does not run
   them).
8. I1: `android/version.properties` stays `versionCode=1`, `versionName=7.0.0` for the first install; the
   release bump is I1's.
9. I1: the `security-reviewer` pass on the manifest, the exported parts and the signed client (the plan's
   review for Part E).

## 6. Deviations from the plan, with reasons

1. **`core`'s JVM tests use a small runner of their own** (`:core:jvmTests`, a `main` that runs every case
   and fails on any FAIL), not JUnit: D24 keeps `core` to the Kotlin standard library, and the repository
   takes only Apache-2.0 or MIT libraries (JUnit is EPL). The workflow runs `:core:jvmTests` instead of
   `:core:test testDebugUnitTest`; Gradle's `test` task in `core` is switched off.
2. **The app module has no JVM unit tests.** The "fake client with three writers" is `core`'s
   `HealthSource` fake; the real reader's "aggregate only" is held by a Python static test of
   `HealthReader.kt` (its control sums raw step records) and by `HealthSource` having no raw-record method at
   all. The "dedupe off" control is both a CI mutation (both sleep writers kept) and that Python control.
3. **The optional local Kotlin compile (D24) was not done**: running the compiler downloaded from JetBrains'
   GitHub release was refused in this workspace. CI compiled everything.
4. **androidx.core 1.17.0 and work-runtime 2.10.5, not the newest** (1.19.1, 2.12.0): 1.17.0 is
   android-browser-helper 2.7.4's own pin and builds on compile SDK 36; newer minors were not checked for a
   higher compile SDK. Lint's `GradleDependency`, `OldTargetApi` and `UseKtx` checks are disabled with that
   reason written beside them; CI prints the newest versions on every run.
5. **Without Health Connect's background switch, the watch is read while the set-up screen is open**, not
   when the console opens: the console is Chrome's window, so Health Connect counts JARVIS as being in the
   background then. The set-up screen says so ("Without the background switch…").
6. **The Talk and Camera shortcuts reload an open console**: Android adds `CLEAR_TASK` to a static
   shortcut's intent. The library's trampoline that avoids this is removed because it opens any JARVIS
   address another app sends it (D8). The tile does not reload.
7. **The library's `ManageDataLauncherActivity` is declared (not exported)**: the library's launch code
   switches it on and off, which needs it in the manifest. It is not `manageSpaceActivity`, so "Clear
   storage" in Android's settings still clears the app.
8. **The fonts are TTF copies of the console's own WOFF2 files** (`assets/fonts/`, their OFL licences
   beside them), because Android does not read WOFF2.
9. **Test SOS offers no SMS button**, so a test can never reach the family as a text message.
10. **No Gradle dependency-verification file**, exact versions only: a file recorded on CI's Linux runner
    would refuse the Windows-only `aapt2` artifact Android Studio downloads on the laptop.
11. **`resolveDependencies` resolves each project's variant classpaths** but not the app's own unit-test and
    AndroidTest classpaths (they resolve the app itself); every library is on the variant classpaths anyway.

## 7. Not verified live (no Android device here)

- That Chrome on the phone opens the app full screen after linking (needs Part C's asset links, Needs I1
  item 1) and that Google sign-in and a passkey work inside it. *Check:* acceptance 1.
- That Chrome passes the web tag to the delegated notification (Needs I1 item 6). *Check:* a burglar test
  lands under Urgent.
- That Health Connect opens the app's permission screens and its privacy page for an app installed by hand,
  and that App priority removes duplicates for heart rate as it does for steps. *Check:* steps A3, C10.
- That `startActivityAndCollapse(PendingIntent)` opens the SOS screen over the lock screen on OxygenOS, and
  the dialler and SMS app after the unlock prompt. *Check:* lock the phone, pull the shade, tap SOS.
- That the SMS app accepts several numbers joined by `;` and fills in the message. *Check:* acceptance 9.
- That the phone's clock is within 120 seconds of the server's (the door refuses older signatures).
- The menu words in Android Studio Rabbit 2 and OxygenOS that OWNER-STEPS.md marks "not checked", and that
  Studio's own Java 25 runs Gradle 9.6 (else step C3).
- The app's speed and battery use, the fonts on the phone's screen, and the screens' look at the phone's
  size (no visual gate exists for native screens).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 13 Nov 2026, 20:05 IST | R7 | First edition: what Part E built, the three CI rounds and what each proved (runs 43439904145, 43441109044, 43442154933), the checks run here, the contract as the app uses it, nine items for I1, eleven deviations with their reasons, and what only the phone can show | 🛠 Mark XVII |
