Version v5.2.1 · 28 Nov 2026 · Release R5.2 · Status: Current · Owner: 🛠 Mark XXV

# R5.2 "Your voice": the combined security and code review

Branch `r5-2-review`, from `r5-2-book` (1db5988) with R18's final release merged (`r18-release`,
48d35d4, R18's last CI fix; merge 4f96d79, no conflicts). One reviewer with a fresh context read
R5.2's changes (`git diff origin/r18-release...HEAD`: `src/jarvis/localspeech/**`,
`voice/{laptop,calls_bridge,routing,profile*,session*,wakeword_api,service}.py`,
`api/{r52_wiring,voice_profile_routes,speaker_assets,voice}.py`, `config_voice.py`, the call desk's
hook, Vitals' line, the console's `console-voice-session*`, `console-wakeword-own.js`,
`console-voiceprint*.js` and the barge-in hook, `deploy/local-speech/**`, `deploy/cloudrun.sh`'s kit
step, the evals and the Book), and R18's code only where R5.2 touches it. Every item of the
Workshop's notes (`r52-review-notes.md`) and of BOOK-LIST section 4 is handled below; every
CRITICAL and HIGH and the cheap MEDIUMs are fixed, each with a test written red first; then the one
final check pass (section 3).

## 1. Findings

No CRITICAL was found. Counts: **1 HIGH** (1 fixed), **8 MEDIUM** (8 fixed; rows 20 and 21 came out
of the final check pass), **12 LOW** (7 fixed, 5 left, each with its reason; row 18 was then done on the owner's decision
of 28 Nov 2026, so 4 are left).

| # | Severity | Where | What | Fix | Test |
|---|---|---|---|---|---|
| 1 | HIGH | `deploy/local-brain/start-windows.ps1:83`, `start-unix.sh:91` (the Workshop's notes) | The offline brain's start scripts took Tailscale Funnel's port **8443**, the home bridge's door (`deploy/home/setup-windows.ps1`, `jarvis.home.models.BRIDGE_PORT`): on one laptop the brain's start replaced the bridge's door and its Ctrl+C closed it, so home went offline. R3's plan D3 and `jarvis.home.client` (which refuses 443 as "R1's local brain") had already given the brain 443 | One door each: the brain **443**, the bridge 8443, the kit 10000 (Funnel's only three https ports). Both brain scripts use 443 and close only it; each refuses its port while it serves something else (`Test-FunnelTaken`, or `tailscale funnel status` read for that port, 443 having no `:port`), before Caddy starts; the bridge's setup refuses a taken 8443; the brain's README says to paste the new address (no `:8443`) once | `test_r52_review_ports.py` (8, two of them run `start-unix.sh` / `start-kit.sh` against stub programs); `test_local_brain_kit.py`'s pins moved to 443 |
| 2 | MEDIUM | `localspeech/manager.py:127` (`ModelEntry._checks`) | I1's git-blob pins (the recorded deviation) required only that `/<commit>/` appear somewhere in the file's address: a moving ref passed with the commit in a query, a fragment, or a folder under `resolve/main/`; the commit is what makes a SHA-1 pin safe | `_at_commit`: the address is exactly the host's raw file at the commit (`/<owner>/<repo>/resolve/<commit>/…/<name>` on Hugging Face, `raw` on GitHub), plain segments, no port, query or fragment, ending in the pinned name; SHA-256 pins unchanged; the real `models.json` still loads | `test_r52_review_manager.py` (14) |
| 3 | MEDIUM | `deploy/cloudrun.sh` `local_speech_answer` (the Workshop's notes) | A bad kit address, a key under 32 characters or a key Secret Manager would not store hit `die` and stopped the whole deploy; I1-NOTES: an optional part never does | `ls_skip`: says why in plain words, leaves the kit off this time (voice uses Google, then the browser), the deploy goes on; the key never echoed | `test_r52_review_deploy_kit.py` (7, bash with `gcloud`'s parts stubbed) |
| 4 | MEDIUM | `api/voice_profile_routes.py:105,144` | A part raising anything but `ProfileRefused` (the profile store down, a session document that can't be read) reached Starlette as a bare 500 | `_answer` and `_file` log the class name only and answer 503 `unavailable` in plain words, never the error's text (R18 review finding 6's rule) | `test_r52_review_routes.py` (14, every route) |
| 5 | MEDIUM | `voice/profile.py:108` (`PROTECTED_WORDS`) | "Corrections never touch numbers, money or codes" listed the cardinals and "first second third" only: a learned correction could still write or rewrite "fifth", "hundreds", "dozen", "twice" or "passcode" | Ordinals, plural and counting words, and password / passcode / passkey / pincode / cvc added | `test_r52_review_corrections.py` (38) |
| 6 | MEDIUM | `localspeech/selftest.py:274` (BOOK-LIST 4.2) | With kit 1.0.0 (Whisper, no voice) the round trip was skipped, so the plan's "listening faster than real time ×3" bar was never measured | `check_listening_alone`: with a listening engine and no voice, listening is timed on 5 s of a test tone (the loading call untimed); the report says the word error needs a voice | `test_r52_review_selftest.py` (3) |
| 7 | MEDIUM | `deploy/local-speech/start-kit.sh:56` | The kit's Unix script looked for `:443` in Funnel's status, which names port 443's door with no port, so `JARVIS_SPEECH_KIT_HTTPS_PORT=443` would take the brain's door | Port 443 is read as a door with no `:port` (or `:443`), the others by their exact suffix | `test_r52_review_ports.py::test_the_kit_refuses_port_443_while_the_brain_holds_it` |
| 8 | LOW | `deploy/local-brain/start-*` (address) | The brain printed the first `ts.net` address in Funnel's status, which with the bridge or the kit on the laptop could be theirs | Its own door only (no `:port`) | `test_r52_review_ports.py::test_the_brain_leaves_the_bridges_door_alone_and_prints_its_own_address` |
| 9 | LOW | `console-voice-session.js:318`, `.css:58` | Through the console's own DOM checks (R18's `_gate`), the session pop-up's "Names and places you use" label was in the plain body font, which the console's look rule refuses | The Voice panel's own `.bl` label style | `tests/browser/test_r52_review_look.py` (red on the label, then green) |
| 10 | LOW | `calls/speech/build.py:10,72` (the Workshop's notes) | The "laptop" option was "the call desk's local models … (passed in by the hub)", and its reason in Calls → Languages "The call desk has not offered its laptop speech models"; since R5.2 it is the laptop speech kit, from `r52_wiring.calls_laptop` | The docstring and the reason name the kit ("The laptop speech kit is not set up on this server.") | `test_r52_review_words.py::test_review_the_laptop_options_reason_names_the_speech_kit` |
| 11 | LOW | `console-voice-session.js` header (the notes) | Said clips go by POST; the route is PUT `…/session/clips/{prompt_id}`; over-long comment lines | Words and wrapping | `test_r52_review_words.py::test_review_the_session_screen_says_clips_go_by_put` |
| 12 | LOW | `api/voice.py:218`, `api/voice_profile_routes.py:2,25` (the notes, BOOK-LIST 4.5) | "501 until its I1 wires it", "the router skeleton (I0)", "Not wired yet" | The words follow the wiring (501 only for a part that failed to build) | — |
| 13 | LOW | `deploy/local-speech/README.md:3` (BOOK-LIST 4.3); R5.2's docs | The README said the kit "listens and speaks" and "(later) trains" the wake word; the plan, brief, seams, I1-NOTES, the ADD's chapter 02 and the guide's C79 said "the offline brain keeps 8443" | The README: listens (no voice in kit 1.0.0), trains the personal check now; every port line corrected; versions moved with change-log rows | `check_doc_versions.py` |
| 14 | LOW | `localspeech/server.py:120` `build_app` (92 lines) | Over the 50-line guide | **Left**: a flat route table of one-line handlers plus the auth wrapper; splitting it scatters the "exactly `protocol.ROUTES`" assert. No R5.2 file is over 800 lines | — |
| 15 | LOW | `voice/profile.py` `SPOKEN_BY_HEADER` (BOOK-LIST 4.4) | Defined, never sent or read | **Left**: the "Spoken by the owner" label is not built (I1-NOTES 4.7); `test_r52_v5_never_approves.py` forbids it in every module that decides anything | — |
| 16 | LOW | `vitals/words.py` `VOICE_ENGINES`, `protocol.DEFAULT_ENGLISH_VOICE` (BOOK-LIST 4.6) | Name Kokoro and Piper, which kit 1.0.0 leaves out | **Left**: never shown while the slots are empty; right again once a permissive voice is pinned | — |
| 17 | LOW | `buildbook/gen/pages_index.py` docstring (BOOK-LIST 4.7) | Counts 153 pages (now 169) | **Left**: a comment; changing it stales every page that cites the module | — |
| 18 | LOW | `voice/session.py:567` (`delete_recordings`) | With no kit set up (address or key removed), "Delete my recordings" refuses (503 `laptop_not_set_up`), so the comparison's transcripts in Firestore can't be deleted from Privacy until the kit is back | **Left** by the review: by design nothing claims to be gone that isn't (the row says recordings are deleted only while the laptop is on); the profile row deletes on its own. A cloud-only delete was for the owner to decide. **Done, 28 Nov 2026** (the owner's decision, the safe default, 475b208): with no kit set up the delete clears the session document here and the profile's session; none of the laptop's recordings is claimed gone (0 deleted, their count kept, the dashboard shows them as left); a kit that is set up but down still refuses, nothing deleted | `test_r52_review_delete_here.py` (4, red first) |
| 19 | LOW | the Book | 26 pages and 3 narrations staled by the fixes (2 more by row 20) | Each diff read; C79, C17, C39 and the Voice screen's words fixed where they had become untrue or incomplete, the rest restamped; `module_voice` retold where its pages changed | `pages --check`, `--narration-check` |
| 20 | MEDIUM | `pyproject.toml` package data (the final suite's one failure) | `static/vendor/speaker/spk-1/MANIFEST.json` was not package data: the image (`pip install .`) would have no speaker manifest (the route then 404s, safe) and the model V5's `to_ship` list adds later would never ship | `static/vendor/speaker/*/*` beside the mannequin's | `test_r14_i1_join.py::test_every_runtime_data_file_ships_in_the_wheel` (red in the suite, green) |
| 21 | MEDIUM | `evals/r6_3/facts.py:163,184` | The mock evals failed `r6_3` on R5.2's Book: pins of R18's 78 cards and 197 settings | 83 cards (C79–C83) and 204 settings (`LocalSpeechConfig`'s 7), each commented | `run_all_mock.py`: r6_3 30/30, its control failing |

**Checked and sound (no finding).** The kit's key: at least 32 characters in the cloud's config
(`config_voice._key`), the client (`_require_key`, `bearer`), the kit (`KitConfig.require_key`: the
server never starts without one), the gate (`@nokey`: 503 for everything) and the desk
(`calldesk.config.speech_key`); compared in constant time; only in the environment (never a command
line) and never logged (`KitConfig.__repr__`, `HttpKit.__repr__`, the self-test's report, the
deploy's `read -s`). The cloud reaches the kit only by `cloud_kit`: an https `*.ts.net` name
(`kit_origin`, then R1's `check_url`: every resolved address public), every request through
`PinnedTransport` (resolved again, connected to the checked address, SNI kept), no redirects
(`follow_redirects=False`, a 3xx is `protocol`), at most `REPLY_MAX` read while streaming, no
environment proxy; the kit's words never shown (fixed `REFUSED_WORDS`). The Caddy gate passes
exactly `protocol.ROUTES` with the key (the server asserts the same table), binds 127.0.0.1, and
uvicorn binds `kitconfig.HOST` (not configurable), access log off; Funnel's port 10000 by default.
`parse_request` reads every body (strict models, `BODY_MAX`, never quoted). The recordings:
AES-256-GCM, a fresh 96-bit nonce, session and prompt bound in, a key only the kit holds; ids match
`SESSION_ID` / `PROMPT_ID`, so no path leaves the folder; "Delete my recordings" stops a running job
first, removes the folders, replaces the key when every recording goes, and (if asked) the
wake-word files, which have their own key; the cloud refuses to claim a delete the laptop didn't
make. The model manager: only pinned https files from the two hosts, size checked while streaming,
renamed into place only on a match; blob pins only for JSON/TXT ≤ 5 MB at a full commit (finding 2);
an LFS file's blob id is its pointer's, so it can only fail closed. **The speaker check never
approves anything**: on the server (`test_r52_v5_never_approves.py`: only `voice/profile.py` names
the label, nothing imports it, no decider mentions a voice print, no decision has an input for it,
and through the real app a labelled turn still leaves the irreversible card waiting and the label
is no passkey) and in the console (`test_r52_v5_console.py`: the scripts send nothing but the model
file's GET, touch no approval, passkey, unlock or Telegram screen, only the barge-in hook asks the
check; the browser test's verified voice saying "approve all" approves nothing). The voice print
stays in the browser: AES-GCM under a non-extractable key in IndexedDB, never `exportKey`. Money:
inside the free minutes every comparison call is free-only (`FreeAllowanceUsed` turns the session
to NEEDS_YES), beyond them 402 `needs_yes` with the rupees comes before any priced call, mid-session
too (`Comparison.check` before the clip is sent), and free minutes that can't be read are never
promised; the laptop is never gated or metered. The kit's replies are untrusted: bounded models,
the transcript capped, the wake-word files hash-, licence-, size- and feature-checked before the
console gets them (and again in the console). No transcript, audio, phrase, key or Tailscale name in
a log (every R5.2 log call read). Owner-only routes (`require_auth`, CSRF header for cookie writes,
the app's rate limit), `no-store`, bodies capped.

**Recorded, not fixed (the owner's or a launch's).** openWakeWord's mel-spectrogram and embedding
models are CC BY-NC-SA: personal use is fine, a launch needs an owned or permissive front end
(stage 2 included). The speaker model (WeSpeaker VoxCeleb CAM++, CC BY 4.0) is not vendored; its
threshold 0.45 is uncalibrated and its EER eval needs the real model. Only faster-whisper small and
medium are pinned (weights by SHA-256, three text files each by blob id at the commit); Kokoro,
Piper and the Indian engines stay left out (the Workshop's decision), so the kit has no voice.

## 2. The Workshop's notes, item by item

| Note | Where handled |
|---|---|
| Stale comments (`api/voice.py`, `voice_profile_routes.py`, the session script's POST) | rows 11, 12 |
| BOOK-LIST section 4 | 4.1 (m9) was fixed by R18's review (its finding 11) and passes; 4.2 row 6; 4.3 row 13; 4.4 row 15; 4.5 row 12; 4.6 row 16; 4.7 row 17; 4.8 section 1, "Recorded" |
| Licence and launch | section 1, "Recorded"; the blob-pin path row 2 |
| Security focus | section 1, "Checked and sound", rows 2–5 |
| Owner decisions in force | kept: no GPL or PyTorch engine added; R18's 1920 px dock unchanged (the look gate asserts Calls stays out of the bar at 1920; `test_dock_fit`, `test_r51_dock`, `test_r18_calls_ways_in` in the browser pass); free first (row 3 of "Checked") |
| The port clash | rows 1, 7, 8, 13; the Book's C17, C39, C79 and `module_voice` |
| `cloudrun.sh` | row 3 |
| `calls/speech/build.py` | row 10 |

## 3. The final check pass

Run once, at the end. The suite ran on `r5-2-review` at 8a506f8; its one failure was fixed in f13624a (row 20) and the evals' pins in 135471b (row 21); the rest of the pass ran after them. This file is the only change after.

| Check | Result |
|---|---|
| 1. The whole suite, Python 3.12, with coverage | **21,278 passed, 1 failed, 168 skipped** (42 min). Coverage **95.3 %** (108,077 statements, 5,065 missed), at or above the project's floor of 95. The failure was R5.2's (row 20), fixed in f13624a; its file rerun with its neighbours (`test_r14_i1_join`, `test_r52_v5_console`, `test_notify_hardening`): 62 passed. The suite was not run a second time (one pass) |
| 2. `ruff check src tests evals` | All checks passed (the whole tree; R18's E501 is gone) |
| 2. `ruff format --check` | the 18 Python files the review touched: formatted |
| 2. `mypy --strict` | 113 files (`localspeech`, `voice`, `calldesk`, `vitals`, `config_voice`, the R5.2 API files, `calls/speech/build.py`): only the known baseline `memory/redis_store.py:67` |
| 3. Mock evals, Python 3.11 (`/tmp/venv-b`) | **ALL MOCK EVALS: PASS** after row 21 (the first run failed only `r6_3`'s two pins); `wakeword` passes with both controls failing it; `calls_language`, `r6_3` 30/30 and every other suite with its negative control failing as it must |
| 4. The Book and the docs | `pages --check`: 169 pages ok, 0 problems; `--narration-check`: 27 ok; `check_doc_versions.py`: all 49 documents; `adds_citations.py`: 1,165 citations, 0 missing; `arch_coverage.py`: OK (71 packages/modules, 136 console modules, 35 services, 136 collections); `tests/test_arch_coverage.py`: in the suite |
| 5. Browser, Python 3.13 + Playwright (`/tmp/venv-c`) | R5.2's files and the ones the review touched or that read its screens (`test_r52_v3_voice_session`, `test_r52_v4_wake_own`, `test_r52_v5_voiceprint`, `test_r52_review_look`, `test_voice`, `test_voice_barge`, `test_voice_fixes_barge`, `test_dock_fit`, `test_r51_dock`, `test_r18_calls_ways_in`, `test_privacy`, `test_offline`): **178 passed** (15 min) |
| 6. Screenshots | `build/r52-review-shots/` (24 PNGs, never committed: git ignores `build/`): Voice → Your voice after a scored session (ranking, corrections switch, Check again, both Train buttons, Delete), the speaker check (no model: says so, Record hidden), the session pop-up's start and a line to read, Privacy's three voice rows (5 learned items, 120 recordings), Vitals' "Laptop speech kit" line (OK, last heard by the laptop, ₹0 a minute), each at 1920 × 1080 and 2560 × 1440, Night and Day, each through the console's DOM checks. Every one looked at: one fix (row 9, the pop-up's label); at 1920 Calls has no tab in the bar and nothing moved, at 2560 it is last (R18's rule) |

## 4. Left for the owner

1. **The offline brain's address changes** (row 1): if Offline mode was set up before v5.2.0, run
   the brain's start script once and paste its new address (no `:8443`) into Integrations →
   Offline mode. The home bridge keeps its address.
2. Everything in I1-NOTES section 5 (install the kit, the session, training, the speaker model).
3. Row 18: **decided, 28 Nov 2026**: "Delete my recordings" also clears the cloud's comparison
   words when no kit is set up. The safe default is applied (475b208): any recordings on the
   laptop stay counted until the kit is back; the Workshop tells him.
4. The merge commit 4f96d79 carries no trailers (made by `git merge --no-edit`, as the setup said;
   pushed, so not rewritten).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v5.2.0 | 27 Nov 2026, 23:55 IST | R5.2 | First edition: the findings (1 HIGH, 8 MEDIUM, 12 LOW), the Workshop's notes item by item, the one final check pass, what is left for the owner | 🛠 Mark XXV |
| v5.2.1 | 28 Nov 2026 | R5.2 | Row 18 and section 4 item 3: the owner's decision of 28 Nov 2026 applied (with no kit set up, "Delete my recordings" clears the comparison's words here; the laptop's recordings stay counted), 475b208, its test | 🛠 Mark XXV |
