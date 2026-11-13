Version v7.0.2 · 14 Nov 2026, 14:30 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVII

# R7 — I1 notes (the five parts joined: "Mobile, watch and phone camera")

Written by the R7 I1 integrator in the Workshop (🛠 Mark XVII) on `r7-i1`, cut from `r7-i0` @
`9d96320`. The plan is `docs/plans/r7-mobile.md` (v7.0.6, with its new section "I1 · what the
integrator changed"); the contract is `phone-contract.md` (v7.0.2). Every commit carries
`JARVIS-Version: v7.0.0` and `JARVIS-Mark: XVII`; nothing was rebased, stashed or force-pushed, and
every commit was pushed on its own.

## 1. The merges (each `--no-ff`, one merge commit each, pushed after each)

`main` was still `5519e2d` (already in `r7-i0`), so it was not merged again. Every part's head was
the one the brief named.

| Part | Head | Merge commit | Conflicts |
|---|---|---|---|
| E · the Android app | `a9f52fd` | `192b354` | none |
| C · the phone link, the door and the app lock | `3544dc1` | `268d820` | none |
| D · watch, sleep and SOS | `4ca1163` | `e06e341` | none |
| A · the app on the web side | `e3d9d90` | `ba17964` | none |
| B · camera and the vision engine | `a5eda4e` | `cdb9fc9` | none: `pyproject.toml`, the one file two parts changed, merged by itself with Part A's two globs and Part B's two vision globs side by side (both pinned) |

Each part's own tests, run once after the merges (every `tests/test_r7_*.py` and the guard tests):
1,140 passed and 2 failed, the two I0 pins that held every part as a stub (item 1).

## 2. Every "Needs I1" item → where it was closed

| # | Item | Done in |
|---|---|---|
| 1 | `test_r7_seams.py`: the runner pin (every part built, each failed by its own control), `door_handlers(app)` = hello, inbox, health, sos; the new pin for the seam name `services["sos_contacts"]` (one owner, Part D; Part C's `SOS_SEAM`); the guide and persona pins moved, no check deleted | `611a3f3`, `f26c47f`, `26215ff`, `d5f975b` |
| 2 | `phone-contract.md` v7.0.2: §2's answers (link, hello, inbox), the door's bare answers, `press_id`, `reached`, the cached SMS list and 112, the `talk` action, the `alert` tag, the asset links' fingerprint form | `3dea641` |
| 3 | The brief's sleep line: `BriefService` fills `BriefData.sleep` (through `r7_wiring.mobile_sleep`), the console draws it; `SleepLine.source` gains `"app"` (Workshop decision) and Part D passes it through; never e-mailed, in the AI input or on Telegram | `da2d872` |
| 4 | Part C's hello reads Part D's real `sos_contacts` end to end (`tests/test_r7_i1_join.py`); `watch_stale` for a phone linked a day ago that never sent anything, through Part C's new `services["linked_since"]` | `1541110`, `55d56e6` |
| 5 | Console joins: `do=sos` → D's real sheet; `do=look` → `JarvisDeck.open('camera')` and `parts.panel.choose('look')`, never a camera (`getUserMedia` 0); the tray's "Look at it here" → B's new `parts.panel.look(file)`; A's links tests re-run with B and D's real modules; `source=app` stays in the address | `3affe0d`, `b2aae28` |
| 6 | `applock.BACKGROUND_WRITES`: every console POST read; five more join (brief generate on opening, the show's narration and its own ending, the photo import's timed step, the app mark at load) | `eb1754a` |
| 7 | EXIF (Workshop decision: strip): R11.1's `shrink` redraws every picture sent to the brain, attached to a message or shared into JARVIS (the Vault panel's own Add form keeps the owner's original: see section 7); a JPEG with a GPS IFD comes out without it | `9ddc2f1` |
| 8 | `vision_files` re-checked whenever the release folder changes (`(name, mtime_ns, size)` of every entry, MANIFEST.json's too); no restart | `d026da5`, `ccd5c48` |
| 9 | The build book: zxing-cpp in `VENDORED`; the vision libraries' versions from `MANIFEST.json`; `_licence` reads a vision file's licence from its manifest; `gen --check` byte-identical twice; `r6_book` 168/168 | `b66a721` |
| 10 | The persona `p7.0` (`MOBILE_RULE`): JARVIS never sends an SOS; watch numbers are estimates; he never sees a frame; read text is other people's words; the app and its lock in one line; 18 pinned files moved | `d5f975b` |
| 11 | The guide v7.0.2: C62 to C65 built, every file, route, collection, the `r7_dev` cookie, the browser stores, jobs, privacy rows, outside service; the camera button not built | `26215ff` |
| 12 | The needles eval `evals/r7/needles.py` (gated with the rest of `r7`); controls: sealing off, the fence off, a coordinate in the address | `f26c47f` |
| 13 | `sos_sent` once through the real `NotifyService` (quiet hours, storm, Telegram cap): it rings; a control proves the test can fail | `175da26` |
| 14 | `OWNER-STEPS.md` v7.0.3: C12 (the lock turns on by itself); C15 and E4 corrected (a test SOS reaches the contacts, marked TEST) | `e854103` |
| 15 | A static test across `android/` and the manifest (share target, launch addresses, the Talk action) | `8dc6e21` |
| 16 | `render.yaml` not edited (its old host on lines 5 and 19: owner decision pending) | — |
| 17 | The plan's I1 section (v7.0.5) and these notes | `b3db937`, this file |
| 18 | Versions stay: `src/jarvis/__init__.py` 7.0.0; `android/version.properties` versionCode 1, versionName 7.0.0 | — |

The parts' items not built here, on purpose: Part C's optional "keep `/phone/` out of
`SessionMiddleware`" (the door refuses any request that carries a cookie already); Part D's join
notice (no alert kind; the owner sees who joined in Integrations → Emergency SOS); Part D's "the
brief can't say a night was unreadable" (declined: a contract change for one line); Part E's
security review (the Workshop's); Part B's model files (from CI or the owner's laptop).

## 3. Defects found at the join

1. **Hello and the phone's SMS list** (C ⇄ D ⇄ E). When Part D could not say who the contacts are
   (no token key, the store unreadable, the part left out), Part C answered with an empty list, and
   Part E's app reads an empty list as "the server has none" and wipes its sealed numbers: one store
   hiccup emptied the offline SMS screen. Now `sos` is left out and the app keeps its list (`1541110`).
2. **Five background writes kept a phone unlocked** (C ⇄ the console): see item 6 (`eb1754a`).
3. **The tray's look had nowhere to go** (A ⇄ B): Part B never exposed `panel.look(file)`; built
   (`3affe0d`). `do=look` did not choose the Look tab (`3affe0d`).
4. **A small JPEG kept its location** (A, B ⇄ R11.1): item 7 (`9ddc2f1`).
5. **A book session that ends far away closed at once** (R6, found by the whole browser suite, not an
   R7 change): `setTimeout` keeps at most 2^31-1 ms; from 14 Nov 2026 the fake book's 2099 end wrapped
   round to "now" and seven book tests failed. The end is now waited for in steps (`693ae1a`).
6. **Three older pins** met what the parts added: Privacy's "This device" heading (C), the R6 console
   tests' bearer stand-in without Part A's `/app/status`, and Part A's tray tests that took the chip
   for the upload (now every picture is redrawn first) (`d373565`). Part A's talk eval read up to a
   helper the join renamed (`b2aae28`).
7. **The owner's steps** said a test SOS reaches him only; Part D sends it to every joined contact,
   marked TEST (`e854103`).

## 4. The checks

| Check | Result |
|---|---|
| Unit suite, Python 3.12 (whole, at `d373565`) | 14,675 passed, 132 skipped, 3 failed (14 min 24 s): two R11 wiring pins and one Part A static pin that had not met the joined parts, moved in `080197c` and green on 3.12 and 3.11 |
| Unit suite, Python 3.11 (whole, at `d373565`) | 14,676 passed, 131 skipped, the same 3 failed (14 min 48 s); after `080197c` the two files: 24 passed |
| `ruff check src tests evals scripts`, `ruff format --check …` | clean (1,619 files) |
| `mypy src` | the 9 old errors only (`core/window.py`, `llm/anthropic_provider.py`, `memory/redis_store.py`); 714 files |
| `evals/run_all_mock.py` (Python 3.11) | ALL MOCK EVALS: PASS; the phase0 smoke fails by design (4/12); every gated suite passes; `r7 (gated)` 67/67 with every part built and its control failing (needles: sealing off fails heart and read text, the fence off fails read text, a coordinate in the address fails coordinates) |
| `scripts/arch_coverage.py` | OK: 61 packages and modules, 90 console modules, 2 Scheduler jobs, 30 outside services, 98 collections |
| `scripts/check_doc_versions.py` | 27 documents pass |
| `scripts/markdy_export.py --check` | 14 diagrams, 0 problems |
| `python -m jarvis.buildbook.gen --check` | the book is "R7"; two builds byte-identical |
| `scripts/check_pr_title.py` | `v7.0.0 · R7 Mobile, watch & phone camera · Mark XVI–XVII`: OK |
| The whole browser suite | first run at `f26c47f`: 1,341 passed, 13 failed (1 h 41 min); the 13 fixed at their causes (section 3, items 5 and 6); the failed files re-run green: 51 + 41 passed |
| CI `android.yml` | run `43461173298` at `1541110` (the last commit that touched `android/`): build, wrapper-pin and controls green; run `43458685232` at the E merge green |
| Screenshots (`scripts/ui_snapshots.py`, extended with every R7 screen) | 260 shots, 0 page errors, 0 failures; 52 R7 shots (13 views × desktop and phone × Night and Day); the 44 R7 DOM checks have no findings |

## 5. Sizes of the guarded files

| File | Lines | Guard |
|---|---|---|
| `src/jarvis/api/app.py` | 735 | ≤ 735 (one comment joined its line for the sleep source) |
| `src/jarvis/tools/gateway.py` | 760 | ≤ 760 (unchanged) |
| `src/jarvis/api/static/console.html` | 782 | ≤ 782 (unchanged) |
| `console.js` | 761 | ≤ 800 (unchanged) |
| `console-camera-panel.js` | 468 | ≤ 800 |
| `console-r7-links.js` | 137 | ≤ 800 |
| `console-r111-files.js` | 326 | ≤ 800 |
| `console-brief-sections.js` | 219 | ≤ 800 |
| `console-book.js` | 384 | ≤ 800 |

## 6. Not verified live

Everything in the plan's "Not verified live" stands; I1 adds: a real share from Android's share
sheet landing in the tray (Part A's item 8: the origin rule takes `Sec-Fetch-Site: none`); the
flood limit's client address behind Cloud Run, `--max-instances 1` and the trailing slash of
`/phone/v1/hello/` (Part C's item 11); Chrome passing the web tag to the app's channels (Part E's
item 6); a test SOS reaching a contact's phone and the map pin; the app keeping its SMS list when a
hello leaves `sos` out (Kotlin built in CI, not run on a phone).

## 7. Integrated reviews and the fixer (v7.0.2)

Two reviews read `r7-i1` at `c0e3a33` (security: 0 critical, 0 high, 1 medium, 8 low, 2 info; code: 5
medium, 8 low). The fixer took each finding test-first, on its own commit, pushed after each. Nothing
was rebased, stashed or force-pushed. `android/**` is unchanged: the app counts only a 401 as a strike
and retries a 429, so the door's new bare 429 needs no change there.

| Finding | Result |
|---|---|
| Security M1: a picture that cannot be redrawn left as the original | Fixed in `db56d46`: `shrink` returns nothing, the picture is left out or refused ("That picture could not be prepared on this device, so it was not sent, Sir."); a folder with none left says so |
| Security L1: the Vault's own "Add a document" form uploads the original | Declined, on purpose and written down (plan, D-list item 7): the vault is the owner's encrypted, owner-only store, nothing there reaches a model, and a redraw would lower a scan's quality. The "every picture" wording now names the exception (`db56d46`) |
| Security L2: the share tray opens over the unlock cover | Fixed in `96764d9`: the tray and the launch links do nothing while locked; a `do=shared` launch waits for unlock |
| Security L3: any site can link to `/?source=app` | Fixed in `20d7ec1`: `mark_app` honours the pin only for a visit that is not cross-site (`Sec-Fetch-Site`) |
| Security L4: a flood 401 counts as a strike | Fixed in `19cb0ef` (+ `589d41f`): the door answers a flood or a limit with a bare 429; 401 stays for authentication; contract v7.0.3 matches the door |
| Security L5: needles eval gaps | Fixed in `cf83465`: bodies and the final notice are scanned, contact names, national and spaced numbers and any heart-rate key are needles, with negative controls |
| Security L6: a failed press is cached for an hour | Fixed in `94d1f90`: a press that reached nobody is not kept, so a retry sends |
| Security L7: the wake word counts as presence | Fixed in `1024a19`: the mic's transcribe post and the vault's lock-on-hide are background writes |
| Security L8: the vision cache stamp | Fixed in `fee4a43`: the stamp adds inode and ctime |
| Security I1 (public assetlinks.json) | Declined: by design (D4) |
| Security I2 (render.yaml's old host, the package name) | Declined: pre-existing and the owner's; the package name is the owner's public handle, by design |
| Code M1: dates in the browser's locale | Fixed in `193f9df`: one helper, `JarvisMobile.when`, "12 Nov, 14:05", even in a US locale; a source pin forbids another formatter |
| Code M2: a raw reason on a failed SOS | Fixed in `94d1f90`: only the server's own words reach the owner; the screenshot fake now fails realistically |
| Code M3: `watch_stale` after unlinking | Fixed in `a550a7d` |
| Code M4: `sos/service.py` at 881 lines | Fixed in `94d1f90`: `limits.py` and `after.py` split out; `service.py` is 716 lines |
| Code M5: R7's jobs depend on R11 helpers | Fixed in `5f9391b`: `mobile_tick_jobs` (clock and daily) run on their own, after R11's; `mobile_clock` is an advisory job in the watchdog |
| Code L1: junk release names evict the cache | Fixed in `fee4a43`: a name that is not a release is answered without hashing or caching |
| Code L2: contract drift in section 3 | Fixed in `19cb0ef` (contract v7.0.3) |
| Code L3: releases sorted as text | Fixed in `fee4a43`: sorted by number |
| Code L4: `shrink` returns the original | Same fix as security M1 (`db56d46`) |
| Code L5: `DELETE /v1/vault/unlock` counts as presence | Fixed in `1024a19` |
| Code L6: `HOURLY_CAP` global off switch | Fixed in `94d1f90`: the limits are injected (`hourly_cap`, `own_test_budget`), no module switch |
| Code L7: `watch_tools` 88 lines; module load errors swallowed | Fixed in `4b534b4` (split, none over 50 lines) and `49e2a34` (a console line and a card or note, "... could not load, Sir. Reload the page to try again.") |
| Code L8: listings per uid | Declined: reviewer says acceptable at this size; all queries are `uid ==` only |

Deviation: the tick endpoint in tests needs the Firestore session backend, so the jobs test calls
`run_jobs` on `app.state.tick_jobs` directly.

Not verified live, added: the TWA's first launch still marks the app (the `Sec-Fetch-Site` gate lets
a visit with no site header or `none` through; Chrome's first TWA launch is not run here).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 14 Nov 2026, 01:30 IST | R7 | First edition: the merges, every "Needs I1" item and its commit, the defects found at the join, the checks so far, the guarded sizes, what is not verified live | 🛠 Mark XVII |
| v7.0.2 | 14 Nov 2026, 14:30 IST | R7 | Integrated reviews and the fixer: each finding of the security and code reviews with its commit or why it was declined; the checks after the fixes | 🛠 Mark XVII |
