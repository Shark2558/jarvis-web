# R7 plan review 1 (fresh context, 12 Nov 2026, 16:00 IST)

Plan reviewed: `docs/plans/r7-mobile.md` v7.0.2 (`r7-i0` @ `898f14e`), all 1,118 lines.
Checked against: the integrated R11.1 code, `r11-1-i1` @ `bbe056d`.
Reviewer: a fresh-context planner agent run by 🛠 Mark XV; read-only.
Workshop's note: the Workshop accepts every item below. The plan edits come before R7's I0. Line numbers refer to v7.0.2.

**Verdict: NOT ready for I0 as written.** It becomes ready once A1–A10 are written into the plan, the B lines are updated, and the C seams are added to the I0 list. None of these needs the owner first. The design holds: the Trusted Web Activity, the signed phone door, frames kept on the device, and SOS limited to opening a screen by voice.

What the reviewer could not check:
- **Version numbers.** Without web access, AGP 9.5.x, Gradle 9.6.0, android-browser-helper 2.7.4, the Health Connect client 1.1.x, tasks-vision 1.2.3 and the other pins are unverified; only contradictions are flagged. CI's first step must resolve every dependency.
- **The release plan's decision 9 and `requirements-rows-135-280.json`.** Neither was in the worktrees, so section D works from Appendix A.

## A. Blocking

**A1. Health Connect double-counting, and the "resting" permission (D17 L421–434, D18 L436–443, tests L721).**
- **Three writers.** Since the owner's check on 12 Nov, the phone, Google Fit and NoiseFit (write on) can all write steps. The only sleep entry so far is "OnePlus 12R". Adding up raw records counts steps two or three times, and "the longest session" (L436–437) may pick the phone's guess.
  - Fix: read steps and heart min/avg/max with Health Connect `aggregate`, which removes duplicates by the owner's App priority list.
  - Fix: for sleep, pick one writer per night, NoiseFit before the phone, in `core`'s day builder, with JVM tests.
  - Fix: L441 names the real writer ("· from your phone" or "· from your watch").
  - Tests: two writers on one night; three steps writers; the dedupe switched off as a negative control.
- **Resting heart rate.** "Resting" (L425) is a separate record type, `RestingHeartRateRecord`, behind `READ_RESTING_HEART_RATE`. Either add that permission to L422, L498, D22, step C10 (L773–775) and the prompts table (L792), or drop "resting" and keep "lowest".
- **Lines to rewrite** for the new Health Connect facts:
  - L26–29 and L190: the phone's own steps and sleep arrive now.
  - L431–433.
  - L750: the NoiseFit switch is done.
  - L805–807, question 3: answered. It becomes: check tomorrow for a NoiseFit sleep entry, and set App priority with NoiseFit first.
  - L850: ColorFit Vision 3; NoiseFit connected with write on, 12 Nov 08:25 IST; only sleep entry so far "OnePlus 12R".
  - L856–857 and L861: "the only known route is via Google Fit" is wrong. L859's end-of-2026 Fit risk matters only if NoiseFit writes through Fit.
  - L880–882: reword the risk and add the double-counting risk.
  - L943–945.
  - Sources S44 and S45 (L1106–1107): S44 is contradicted on his phone.

**A2. Health Connect's privacy screen must be exported, and D22 has no slot for it (L428–430 against L505–511).**
- Health Connect opens the app's rationale activity (`androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE`). On Android 14 and later it uses an activity-alias for `VIEW_PERMISSION_USAGE` / `HEALTH_PERMISSIONS`, guarded by `START_VIEW_PERMISSION_USAGE`. Both must be exported. Without them, either `apk_check.py` fails the build or Health Connect never asks.
- Fix: add them to the allowed list at L506–508.
- Expect more library entries than the three named, for example profileinstaller's receiver behind `DUMP` (through `androidx.activity`). Build the allow-list from CI's first merged manifest, reviewed, rather than guessing.

**A3. The Android build pins are incomplete and contradict each other (L528–531, L804, L849, L957, L541–542).**
- AGP is 9.5.0 at L528, L804 and L957, but 9.5.1 at L849. Pick one and confirm it on the Studio-to-AGP table for Rabbit 2 2026.2.2.
- No Kotlin/KGP pin and no serialization-plugin pin. AGP 9 uses built-in Kotlin and the new DSL by default: no `org.jetbrains.kotlin.android`, no `kotlinOptions {}`. Part E's brief must say so.
- Studio's Gradle JDK on the laptop is the bundled Java 25, so the Kotlin pin must support JDK 25.
- L849 is wrong that "the wrapper pins the Gradle JDK to 17". That is set by `gradle/gradle-daemon-jvm.properties` or Studio's Gradle JDK setting.
- Add `distributionSha256Sum` to the wrapper properties.
- android-browser-helper and AndroidX live on Google Maven; a GitHub tag (S11) does not prove the artifact exists. CI's first step resolves all dependencies.
- D24's optional local compile of `core` (L541–542) fails if `core` uses kotlinx-serialization, whose jar is only on Maven Central. Keep `core` free of it, or drop the claim.

**A4. The app lock (D21, L481–486) collides with R6's 423 handling (seam 14, L700–701).**
- Five places treat any 423 as "a guest show is running":
  - `console.js:78`
  - `console.js:101`
  - `console.js:699` (the `/auth/me` recheck on every visibility change)
  - `console.js:740` (boot: `/auth/me` 423 sends the page to `/book/show`)
  - `console-book-talk.js:147`

  Seam 14 names only `:78`, so a locked app would be sent to `/book/show` at boot and every time it comes back on screen.
- Fix: split by `error` code in all five places.
- List the exempt routes: `GET /`, `/static/*`, `/console/config`, `/auth/*`, `POST /v1/passkeys/challenge`, the unlock route, `/manifest.webmanifest`, `/.well-known/assetlinks.json`, `/app/share/*`, the SOS routes.
- Order: inside the show lock, both inside the session middleware.
- **Idle.** Background requests beat "idle": the R6 recheck and the Home panel's poll (`console-home-panel.js:242`). Define idle as "no request the owner made", and add a control where polling must not keep the lock away.
- **Default ON (L481, question 10 at L823–824) can lock him out.** If his only passkey is Windows Hello on the laptop, it does not exist on the phone. Default: ON once a passkey has been registered from this phone. Add an owner step to register one.
- **New passkey purposes** (`phone_link`, `device_unlock`) need `permissions/models.py:79,88`, `permissions/service.py:148` and the allow-list at `console-permissions.js:131`. No seam lists them.

**A5. An SOS contact's `/start <word>` falls into Telegram pairing (D20 L474–475, seam 15 L702).**
- `handle()` turns any non-owner away at `telegram/service.py:156–158` unless `_is_pairing_attempt` (`:178–188`) is true. `_stranger()` then sends the word to `finish_pairing` (`:313–317`).
- So a join word counts as a wrong pairing code and can start the owner's pairing cooldown. A contact's `/stop` is turned away at `:156` before any hook runs.
- Fix:
  - SOS words carry a fixed prefix and are checked before `finish_pairing`, with their own counter that never touches the pairing cooldown.
  - A `/stop` from a known contact is handled before `:156`.
  - Words are stored as `keyring.mac("sos", word)` with at least 128 random bits.
- Tests: a wrong SOS word leaves the pairing counter unchanged; a pairing code never joins SOS.

**A6. Any app on the phone can make JARVIS listen (D8 L299–305, D9 L312, risk L897–898).**
- The D3 WebAPK's intent filters cover JARVIS's address, so a link tapped in WhatsApp opens it standalone.
- The exported, subclassed `LauncherActivity` launches from an incoming intent's address by default.
- Either way Chrome reports `Sec-Fetch-Site: none` and the page reports standalone display, so `?do=talk` passes D8's checks.
- Fix: `do=talk` never starts the mic by itself. It opens JARVIS with the mic button ready; the tile plus one tap still meets acceptance 3 ("at most two taps").
- Fix: override `getLaunchingUrl()` so the exported launcher ignores incoming addresses.
- Then remove L935–937 and correct L897–898.

**A7. SOS delivery and the confirm rule (D19 L445–466, D25 L546).**
- `notify/models.py:20` `NO_SWITCH` and `notify/telegram_out.py:45` `NO_CAP_KINDS` decide what has no off switch and what is never capped. Seam 5 (L661–664) names neither file.
  - Fix: `sos_sent` and `phone_linked` join `NO_SWITCH`.
  - Fix: `sos_sent` joins `NO_CAP_KINDS`, like `home_hazard`. Otherwise a Telegram cap can drop the owner's SOS notice.
- "3 an hour" (L461) refuses a real SOS after three tests.
  - Fix: tests and "I'm safe" use their own budget.
  - Fix: a refused or failed send still opens the SMS screen and the 112 button.
  - Test: a real SOS goes out after three tests.
- Record in D19 that SOS is not a tool and never passes the gateway. The hold plus the countdown is the owner's confirmation. This is a deliberate exception to "R3 needs an owner token", because a passkey in an emergency defeats the purpose. There is no "don't ask again", the brain cannot reach it, and it is audited without coordinates.
- Coordinates travel only in a POST body, never in an address: Cloud Run logs addresses. Add that log to the needles scan (L723).

**A8. The picture privacy wording is now wrong (L94, L345, L403–407, L723).**
- R11.1 keeps an attached picture as cleaned bytes beside the file until the conversation is deleted (`documents/service.py:19–21`, `documents/pictures.py:5–11`). "Never stored" (L345) is false.
- It accepts JPEG and PNG only, at most 2,048 px (`documents/imagecheck.py:13–14`; the console shrinks to 1,568). A WebP share (L403) or a full-size photo cannot be sent as it is.
- Pictures reach only a brain with `sees_pictures`, but the console's brain detail is `{id, label, trains, tools}` (`console.js:53`). On the free brain, "Ask the AI" would cost money and see nothing.
- Fix: all three send buttons go through the existing `JarvisAttach` and `JarvisFixes.parts.files.shrink`/`cost` (`console-r111-files.js:183`, `:309`). I0 adds `JarvisAttach.add(files)`, which does not exist yet (`console-attach.js:13`, `:244`), and exposes `sees` in the brain detail.
- Reword L345.
- Scope the needles eval: its "pixel pattern" and "read text" checks fail by design on anything he chose to send.

**A9. Costs not in ₹ only.** L817–818 and L873 quote "25 US dollars" and an exchange rate. Keep only "about ₹2,381 once (an estimate)".

**A10. `.gitignore` is incomplete for a public repository (L703–704).** Add `android/.idea/` (it can hold his Windows user path), `android/.kotlin/`, `*.iml`, `*.apk`, `*.aab` and `captures/`.

## B. Stale against R11.1 (`r11-1-i1` @ `bbe056d`)

| Plan line | Says | Now |
|---|---|---|
| 7, 9, 54–60, 62 | base `r11-1-i0` @ 9250be1; G0 pending | G0 met: fork from `r11-1-i1` (I1-NOTES v11.1.3), or from `main` once R11.1 is merged |
| 66 | `api/app.py:555–562` | `:557–568` |
| 74–76 | CSP "pinned by four tests" | `test_console_assets.py:20–26`, `test_media_console.py:37–40`, `test_r3_seams.py:1059–1060` (not 1050), `test_wakeword_assets.py:191` |
| 83 | `alerts.py:21–72` | `:21–74`; R11.1 added `series_checkin` (important, rings by day) and `faces_to_name` (info) |
| 86–89 | mic `:423–437`, `:660–667`, `:631`; `api/console.py:172–183` | `:426`, `:663`, `:633–634`; wake word `:180–184` |
| 93–94 | picture seam waits for Part B | built: kept beside the file, JPEG/PNG only, ≤ 900 KB, ≤ 4 a turn, `BrainSpec.sees_pictures`; picture turn guard (`picture/turnguard.py`) refuses `research_person`/`web_search` with a face's name; new row "Pictures" (R1, `picture_research`) |
| 99–100 | `telegram/service.py:132–148`, `:298–313` | `handle()` `:144–168`; `_stranger()` `:310–325` |
| 107–108, 909 | `app.py` 725; `console.html` < 800 | `app.py` 731, pinned ≤ 735 (`test_r11_1_seams.py:243`); `console.html` 795, pinned **≤ 795** (`:244`), so every added line fails until seam 10 frees lines and updates the pin |
| 345 | "never stored" | stored with the conversation (A8) |
| 652–655 | `test_book_gen_plans.py:205–214` red; determinism `:209–213` expects "R11" | both green and expect **R11.1**; also `test_book_gen_plans.py:101–103` and `:180` |
| 663–664 | `test_r11_1_seams.py:117`; `test_r51_seams.py:43–48` | `:118`; `:45–50` (now includes `series_checkin`) |
| 665–667 | `test_r3_seams.py:896`; `test_r11_1_seams.py:137` | `:905`; `:138`, plus `:139` pins exactly `plans, pictures` between `kitchen` and `maps`, so R7's 3 rows go elsewhere |
| 668–669 | `test_r3_seams.py:838` | `:847` (keyring still 18) |
| 675–677 | `test_r11_1_seams.py:239` (≤ 730, 725); `test_r11_wiring.py:276` | `:243` (≤ 735, 731); `:283`; also `test_r6_wiring_seams.py:75` (≤ 750) |
| 682–687 | `test_r11_1_seams.py:240` (≤ 796); `test_r11_wiring.py:293`; `test_dock_fit.py:478` | `:244` (≤ 795); `:300`; `:484` (and `:346`, "helpers" last). Moving the More sheet's items also breaks the static pins on `data-sheet-open` (see note 1) |
| 706–709 | guide rows | C61 is R11.1's; C62–C65 are free. Update `JARVIS-Architecture.md` (see note 2) |
| 712 | 16 files pin `p11.0` | `PERSONA_VERSION = "p11.1"` (`core/prompts.py:51`), 17 test files; the persona may hold no `{}` (`test_voice_persona.py`); D26 names the new persona version (nothing compares it) |

Notes to the table:
1. The `data-sheet-open` pins are at `test_console_assets.py:511–513` and `:634`, `test_r11_wiring.py:303–304`, `test_media_console.py:102`, `test_r6_wiring_seams.py:213` and `test_console_integrations.py:75`. The 19 `<small>` descriptions (`console.html:710–728`) move into `console-dock.js` (240 lines).
2. In `JARVIS-Architecture.md`, update L195, L196, L1438, L1486, L1770, L1771 (R8's row names ML Kit, which D14 bans), L1806 (Capacitor), L1849 and L1918.

## C. Gaps

**Missing I0 seams.** R11.1's I1 had to add two of these late: the phrase slot and the brief contributor.
- **`jarvis.mobile.ports.MobilePart`.** Copy R11.1's part fields (`r11_1_wiring.py:100–137`): `privacy` sources, `phrases`, `brief`, `clock_jobs`, `daily_jobs`. They cover the `watch_stale` check and the 400-day and 90-day retention sweeps.
- **Telegram.** `telegram/rules.py:41`: `watch_*`, `sleep_*` (and `vision_*`) join the private patterns, with a guard test like R11.1's. The test lists tool names from the built registry, not a hand list (R11.1's integrated security review H2).
- **New tool-name words.** Classify them in `ACTION_WORDS` / `TOOL_NOUNS` (`test_r11_1_b_guard.py:68–93`, `understand/words.py:126`). Otherwise the join turns a test red.
- **The brief's sleep line.** Add it to the brief model with a pinned API shape. Decide about the emailed inbox copy (`brief/service.py:688–694`); safe default: no.
- **Licences.** `buildbook/gen/libs.py:59–70` `VENDORED`: add the vision licences, or the book silently leaves them out.
- **Seam 2.**
  - Read the label from the repo's own `src/jarvis/__init__.py` (`fallback.version_of`), not the running interpreter.
  - Fall back to the highest plan when that file is absent.
  - Reorder `plan_paths` (`plans.py:61–73`), because decisions and the ≤ 80 limitations follow that order.
  - Change both `plans.release_label` and `fallback._label` (`:66–84`).
- **CI workflow.** `.github/workflows/android.yml` belongs to Part E after I0, because E iterates on it during the blind CI rounds.
- **`BRIEF-COMMON`.** R11.1's "ask nothing before sign-in" rule applies to every new console module: one `test_before_sign_in_the_block_asks_the_server_nothing` per part. The tray keeps `do=shared` items until sign-in.

**Missing failure modes and tests.**
- **Push targets.** `console-sw.js:13`'s URL check refuses `?`, so `?open=home` falls back to `/`. At `:31`, `navigate()` fails on a window this worker does not control (all of them, given scope `/static/push/`), so a tap opens a second JARVIS window. Fix: focus the open window and send it the target over `BroadcastChannel`.
- **Native screens.**
  - Android 14 and later require the tile's `startActivityAndCollapse(PendingIntent)`.
  - Target 36 enforces edge-to-edge on the native screens; this matters for the SOS Cancel button.
  - Never use expedited work: on Android 9–11 it needs the removed foreground-service permission.
  - Add `dataExtractionRules` beside backups off.
  - Fine and coarse location must be requested together.
- **Phone door (D6).** Signed requests refuse any query string, because the signature covers only the path.
- **Vision static test (L364–366).** Too narrow. Add `XMLHttpRequest`, `sendBeacon`, `WebSocket`, `JarvisConsole.api`, `JarvisChat`, `import(`, `createImageBitmap`, `captureStream` and the storage APIs.
- **Tesseract English data.** No source is named. jsdelivr is blocked here; GitHub tessdata or npm `@tesseract.js-data/eng` are reachable.
- **Pose acceptance.** Acceptance 5 (L733) is conditional on the model files arriving.

**Owner steps.**
- Step B (L753–756) plus step C leave two JARVIS icons, and the WebAPK catches links. Remove the Chrome-installed icon after C9.
- L764's menu wording ("Build Bundle(s) / APK(s)") was renamed in recent Studio versions. Check it against Rabbit 2.
- Add: register a passkey on the phone.
- Add (optional): OxygenOS Battery → allow background activity, for the 6-hourly read.

**Overlaps that would cause merge conflicts.**
- A and B both build "Ask / Attach / Vault" and the "Pictures sent today" counter. One I0 door over `JarvisAttach` solves it.
- Privacy rows (D25) would have B, C and D all edit the privacy files. Use `PrivacySource` registration instead.
- Part D lists `telegram/service.py` (L631). D's code belongs in `jarvis.sos`, behind I0's hook.
- The notification tag format (A's `console-sw.js` `tag: kind`) is read by E's DelegationService. Write it into `phone-contract.md`.

**The split.** Keep five parts. With only four builders, merge A into E, not D into C:
- A and E share the launch words, shortcuts, the share-target JSON, the notification tags and `source=app`.
- E sits idle during the CI rounds.
- C and D are already the largest server parts.

## D. Vision rows that need only the OnePlus 12R in his hand (24)

Appendix A's "52 need no new camera" (L970) counts a phone on a stand (22 rows) and a desk camera (8 rows), and he has neither. The rows that need only the phone in his hand:
- **Photo, no extra equipment or person:** 241, 242, 245, 250, 251, 252, 255, 258, 260, 261, 175†.
- **Photo, waiting for his yes** (equipment, or a person at home): 254, 256, 265, 266, 273, 274, 275, and 264 (doubtful: it checks the framing of a camera that will be mounted by the bed).
- **Live in the hand, no yes needed:** 253.
- **Live in the hand, waiting for his yes:** 267, 270, 271, 278.

**R7 builds none of these use cases.** It builds rows 214 and 215 (photo and live camera, and share) and the engine tasks. By release:
- **R9 (kitchen):** 241, 242, 245, 250, 251, 252, 253, 254, 255, 256, 258, 175†.
- **R10 (care):** 260, 261, 264, 265, 266, 267, 270, 271, 273, 274, 275, 278.

With R7's tasks, only 242 and 253 come out "mostly" ready; 251, 258, 261 and 175† partly.

L1053–1057 needs rewriting: all six "Musts" it calls ready (218, 220, 221, 222, 223, 181†) need a stand or a desk camera. No hand-held row needs `pose` (264 aside). Keep `pose` as "not installed" until its model files arrive; its speed check belongs to R8.

**Workshop's note:** this contradicts the "19 rows" the owner agreed to (decision 9: his own phone plus a desk camera), and he has no desk camera yet. The R7 I0 Workshop tells him plainly:
- the use cases that need only his phone in his hand are these 24 rows, built in R9 and R10 on top of R7's camera engine;
- the desk-camera rows wait for the USB webcam he plans to buy.

## E. The owner's questions

**Nothing blocks I0.**
- **Package name (question 15, L833–834).** Adopt `io.github.shark2558.jarvis`; it is valid and follows GitHub's reverse-domain convention. It goes into `applicationId`, the server's single allowed package (D5), asset links, `phone-contract.md` and `apk_check.py`. It costs nothing to change before the first install; after it, a reinstall and a relink.
- **Version going down to 7.0.0: safe.** Nothing compares JARVIS's version:
  - the only comparisons are for the home kit's own `0.2.0` (`photos/edge.py:173–180`, `home/kit.py:198–207`);
  - sealed books sort by seal time (`seal_index.py:130–136`);
  - `check_pr_title.py` and `check_doc_versions.py` check format only;
  - nothing reads the `JARVIS-Version` trailer.

  The only number-based ordering is the build book's plan order (seam 2, fixed above). The guide's edition number will read lower (v11.1.2 → v7.0.x), which is cosmetic.
- **Answered:** 1 (OnePlus 12R, Android 16, Chrome), 2 (Rabbit 2), 3 (ColorFit Vision 3; tomorrow's check does not block), 9 (DigiLocker Share button).
- **Defaults stand for the rest**, with two changes:
  - Question 10: the app lock default as in A4.
  - Question 3: becomes "set App priority, NoiseFit first".
- **Add, with defaults:**
  - a passkey on the phone: yes;
  - the sleep line in the emailed brief and on Telegram: no.
