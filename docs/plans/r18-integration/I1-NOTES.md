Version v18.0.0 · 27 Nov 2026, 15:30 IST · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# R18 "Calls from your laptop": the I1 join

Branch `r18-i1`, from `r18-i0` (2c62f9a). The builders' own notes: `docs/plans/r18-calls/I0-SEAMS.md`, `INTEGRATION-D.md`, `E-NOTES.md`; the Workshop's collected notes and its one decision (English before the first language check) are in section 2.

## 1. What was joined

| Branch | Head | Builder | Merged |
|---|---|---|---|
| `r18-a1` | bc67de7 | cards, approvals, limits, records, retention, booking, templates, answering, `api/calls_handlers_cards.py` | clean |
| `r18-a2` | bc3bec8 | engine (+ `engine_ports/turns/voice`), hub, brain, guard, summary, captions, live, `api/calls_ws.py` | clean |
| `r18-b` | a42d186 | `calls/speech/**`, `calls/langcheck/**`, `evals/calls_language/**`, NumPy | clean |
| `r18-c` | bf57ec7 | `calldesk/**`, `deploy/calldesk/**`, `api/calldesk_kit.py` | clean |
| `r18-d` | a94ce4b | `android/**`, `phone/calls.py`, `phone/calls_wire.py` | clean |
| `r18-e` | 1c6b70e | the console's Calls panel, Vitals' calls line, browser tests | clean: 11cb158 (14:41, with E-NOTES.md), then 1c6b70e (15:11: Calls last in the dock) |

No two builders touched the same file; every builder's tests are kept (one fake changed: A2's `FakeGate.before_dial` takes the call id, see 3.1).

## 2. Wiring (what is where)

The join is three new modules; the parts' own files changed only where a seam did not meet (section 3).

- **`src/jarvis/api/r18_wiring.py`**: `wire_r18` (after R13, before the gateway) builds the store (`DocCallStore`, numbers sealed with the keyring's `calls` purpose), A1's builder / limits / `CallsService` / `RecordKeeper`, A2's `CallHub` with one set of engine parts **per call** (B's speech with its own meter, D's `OwnerPhoneLink`, the hub's `DeskProxy`), `calls_sockets`, `calls_desk_door`, C's kit (`install_calldesk_kit`: only with an https `public_base_url`), D's late ports, the language-check job. `r18_tools` gives `calls_place` (R3) and `calls_answer_mode` to `build_gateway(r18=...)`. `finish_r18` (from `tick_wiring.finish_wiring`, after the gateway) sets `app.state.calls_api`, the booking calendar and the phone's card decisions. `r18_tick_jobs` adds `calls_retention`. Nothing is wired when calls are off, without `JARVIS_TOKEN_KEY` (numbers and records are sealed) or without a private brain (A2's `NoPrivateBrain`): the routes then answer 501 (`calls_off`: 503). `app.py`: +4 lines (import, wire, `r18=`, the closer).
- **`src/jarvis/calls/join.py`**: the adapters. `EngineStarter` (A1 `CallStarter` → `hub.start_outgoing`, reading the language table first), `GrantGate` (A2 `DialGate` → `CallsService.take_for_dial`), `PhoneApprovals` (D `ApprovalCheck` → `GrantBook.live_until`), `BookingSlots` (A2 `SlotCheck` → A1's rule), `VaultRecords` (A2 `RecordsSink` → `RecordKeeper` + `BookingCalendar`), `HubAnswering` (A2 → A1 `AnsweringPolicy`), `AnsweringRules` (D `AnsweringView`), `PhoneCardDesk` (D `CardDesk` → his press), `HubPhoneSink` (D `PhoneEventSink` → `hub.phone_event`), `PushNotice` (A2 `OwnerNotice` → Web Push), `NoPhone`, `status_view`.
- **`src/jarvis/calls/join_speech.py`**: `CallTally` / `CallSpend` (metering, below), `SpeechChoices` / `CallSpeech` (A2 `SpeechKit` on the language table), `LanguageCheckJob` (the check in the background).
- **`src/jarvis/api/calls_console.py`**: `ConsoleCardsApi`, A1's `CardsApi` with E's names beside A1's (3.6).

Decisions:

1. **Metering in exactly one place.** B's adapters already meter every hearing and voice through `jarvis.billing` (Google's shared free allowance gated and charged; Azure F0 held and never billed; Sarvam and Bhashini in ₹). A2's `BillingSpend.speech` would have counted every Google second a second time (and under other keys for Azure). So `CallSpend.speech` records nothing: it hands the engine what B's `SpeechMeter` reported for this call (`CallTally`, the meter's `on_cost`), so the call's ₹ cap sees the same rupees billing holds. A use B could not price (Bhashini: `None`) is counted for the call at Google's paid rate, never ₹0. Model calls (brain, captions, summary, line translations) keep A2's `BillingSpend.model`, their only meter; the calls month (`calls/{uid}/months`) is the engine's `add_spend` at the call's end, once.
2. **The dial's approval, end to end.** A1's press runs the gateway's `calls_place` card (R3: a card every time, the passkey when in force, a never-called number only with the passkey in force); `CallsService.place` issues a one-use 10-minute grant and starts the engine; just before `call.dial` the engine's gate spends the grant **for that call id** (`take_for_dial`), so D's phone side (`live_until`, which spends nothing) queues the dial only for that call, number and owner, at most 2 minutes after the gate. A dial the phone could not place (`refused`, `no_permission`, `expired`, `no_phone`) ends the call at once (`HubPhoneSink`); `needs_tap` keeps it (he taps the notification). A1's `confirm_dial` stays unused (D's check is `live_until`).
3. **Records.** `VaultRecords` holds the call's mixed audio in memory, resampled to **8 kHz** (the phone line is narrowband; ≈ 0.96 MB a minute, capped at A1's 16 MiB ≈ 17 minutes) and seals it at the end as `audio/wav`, then the transcript (English lines keep no translation) and the summary; a booking is added to the calendar through the gateway with Undo. `finish` never raises: a part that fails is logged and the others are kept (the engine would otherwise save the record without its references). An objection drops what was held and keeps nothing more; the summary's notes stay (A1's rule).
4. **Speech per call.** `SpeechChoices.refresh` reads the latest result per language and option (`langcheck.select.choose`) and the call's languages before the call (the starter) and before a ringing call JARVIS may answer (the phone sink, his default languages). `CallSpeech` serves the chosen option; English before its first check and the "unsupported language" line's Hindi half fall back to the first cloud option that is set up (Google, then Azure); a language with none gets a stand-in that raises `SpeechUnavailable` (a failed line for the engine). `detector()` is None for a one-language call and for Google (it detects inside `transcribe` with alternative languages: one request, not two); B's try-each detector otherwise.
5. **English before its first check** (the Workshop's decision): `cards.offered` adds `PROVISIONAL_ENGLISH` (Google, `versions.check = "not yet checked"`) when English has no result at all; once it has one the check decides; every Indian language still needs a pass. The language table shows English `offered`, `checked: false`.
6. **The language check** (`POST /v1/calls/languages/check`): the estimate answers at once; a run goes to one background task (409 `check_running` while one runs; 409 `check_refused` above the ₹ he accepted, before anything starts); progress (`check {running, total, done, skipped, error}`) is read from the results it writes and shown in `GET /v1/calls/languages`. **New route** `POST /v1/calls/languages/score` (B's `handle_score`: his 1–5 scores of a language's samples) — B built the handler, I0 had no route.
7. **The phone (D).** The door's fifth route `calls` (`DoorRoute`, `DOOR_OWNER`, `DOOR_CAPS` 16 KB, the signed path in `mobile/contract.py`); the phone part builds one `PhoneCalls` and offers it as `phone_calls` (a `SERVICE_OWNER` entry). Its command key is `CommandSigner.ephemeral()` (made at each start): the door's every answer carries the key with the commands and the outbox is in memory too, so no `calls_phone` keyring secret (and no `SECRET_PURPOSES` pin change) was needed. A card that waits for his tap is also sent to the phone (Approve / Decline); Approve is his press (a never-called number, or his passkey in force, opens the console).
8. **The desk (C ↔ A2).** A2's link answers `{desk_id: "h_" + 8 hex, seed (base64url, unpadded), ws_path}`; C reads exactly that (its `_seed` takes base64url) and signs the upgrade of `/v1/calls/desk/ws` with `jarvis.home.signing` as A2 checks it; C sends hello then state and answers `prepare` with `mic`, as A2 waits for. No change was needed.
9. **Notices** go to his devices by Web Push, kind `call_notice` (the summary, "JARVIS asks: …", "tap Phone"). It is not an `AlertKind` (no alert policy, no Telegram): a tap opens the console (an unknown kind's target).
10. **The Book's `planned`** list is empty; the image carries `deploy/calldesk` (Dockerfile `COPY`, `.dockerignore` `!deploy/calldesk`); `evals/run_all_mock.py` runs `calls_language`; `test_r3_seams` pins the `calls` keyring purpose.
11. **NumPy.** `numpy>=2.0,<3` in the cloud dependencies is installable on Python 3.11 (pip resolves 2.4.6 there; checked) and the image locks 2.5.4 with hashes (Python 3.12). Nothing was weakened: `test_r3_seams` now says NumPy is in the cloud image on purpose and still keeps `aiomqtt`, `paho-mqtt`, `opencv` out of it and the bridge extra's pins as they were.

## 3. Mismatches found and fixed

1. **A2's `DialGate` had no call id**, but A1's grant must be taken for one call (D's check names it): `before_dial(uid, card, approval_id, call_id)`; the engine passes its call id (A2's fake follows).
2. **D wants a look at a dial that spends nothing; A1 had only `confirm_dial` (spends once).** `GrantBook.live_until` added (A1's file).
3. **A2's `SlotCheck` takes a booking; A1's rule took a card.** `booking.booking_slot` split out of `accept_slot` (same rule).
4. **A2's `RecordsSink` streams lines and PCM; A1 seals whole parts and reads the record back from the store, which the engine writes only at the end.** `VaultRecords` (2.3) writes the record first, then the parts.
5. **A2's `AnsweringPolicy` (number, rings, settings → bool) vs A1's (the ringing event → decision)**; **D's `AnsweringView` and `CardDesk` had no implementation**: adapters in `join.py`.
6. **The console (E) and A1's views used different names** (`ConsoleCardsApi`, A1's views kept whole): the card body (`contact_name` → `contact`, `limits.max_minutes` → `max_minutes`, `from_card` → that card's number), the card (`number_last4`, `passkey_required`, `ready {ok, problems}`, `refused`), records (`number_last4`; one record's `summary` text with A1's whole summary as `summary_parts`, `transcript` as a list, `booking_event`), settings (`azure_status`), the language table (`results` with English's stand-in, `check`), the status's ready cards (A1's templates by `id`, `title`), `PUT /v1/calls/settings?confirm=1` (→ A1's `confirm_raise`; route change), the check's `{confirm, estimate_inr}` (→ B's `estimate_only`, `accept_inr`; answers `estimate_inr`, `languages`).
7. **Call with passkey could never pass**: E made the passkey for the card id before any approval existed; A1's guard checks a proof made for the approval's id. E's `place()` now asks A1's first press for the approval id, then proves for it and presses again (a fresh approval each press, so a stale one never blocks him); E's stub and test follow; the 17 Calls browser tests pass.
8. **B's language-check handler had no route for scores** (route added, 2.6), and its body forbade the console's fields (2.6).
9. **The skill register's coverage** failed (`calls_*` matched nothing): the fullest test registry (`tests/test_telegram_tool_guard.linked_gateway`) carries R18's tools; the Telegram guards pass with them.
10. **Pins moved by R18 I1**: `app.py` 734 → 738 (`test_r63_seams`, `test_r13_seams`, `test_r7_seams`, `test_r14_seams`, `test_r131_seams`), the door's routes (`test_r7_seams`), the I0 route table (`test_r18_i0_routes`).
11. **The console had no way to the call desk**: no kit download and no link code (A2's `POST /v1/calls/desk/code`, C's `-Link`). Calls → Settings has a "Call desk on your laptop" section (the home kit's way: a plain download link, shown only when `kit/info` answers; "Link the call desk" shows the code once), in the console's own classes and tokens; E's stub and settings test follow.

## 4. Known limits

1. **The brain check per language (plan 5.3 step 4) is not built**: B leaves `brain_ok` None (never a failure) and the speed bar uses the fast tier's 0.6 s estimate (labelled in `versions`). A 10-turn mock call per language with the safety cases is more than a join step; it is the first R18.x follow-up.
2. **Laptop speech mode cannot be chosen**: no laptop `Hearing`/`Voice` adapter reaches the desk from the cloud, so the check never passes a laptop option and every call is cloud mode (`SpeechMode.CLOUD`).
3. **The pre-made lines' audio is not cached**: A2's `FixedLines` caches each line's text; its voice is made per call (inside Google's free 1 M characters a month). B's `LinesCache` is not used by the engine.
4. **Recordings are 8 kHz WAV, not Opus** (≈ 0.96 MB a minute, not the plan's ≈ 0.1 MB): no encoder without a new dependency. A recording stops at ≈ 17 minutes (A1's 16 MiB cap); the cap of a call is 6 minutes by default (30 at most).
5. **Detection on Azure tries each language** (up to 4 hearings an utterance of F0's free seconds) for a call with more than one language; Google detects in one request.
6. **The console's ready cards are A1's templates by title only**: the form fills the rest; A1's `{template, fields}` path stays for the chat and the tool.
7. **Records list** has no `purpose` (a record keeps the card id only); the booking's Undo shows no title or time (`booking_event` carries `undone` only).
8. **The live view in token auth**: a browser cannot send `Authorization` on a WebSocket (E-NOTES): the live view needs the cookie session (Google sign-in), as production uses.
9. **Untested here** (no device, no network): real Phone Link / WASAPI / COM / Bluetooth and the PowerShell scripts (C), the Android build (CI compiles it, D), FLEURS clips from Hugging Face (B), Bhashini (runs only with `accept_unknown`), the doorbell through real Web Push.
10. **For the combined review**: the Approvals panel's generic card prints a pending `calls_place`'s arguments (the full number) — E-NOTES; whether Telegram may approve a call card (I0-SEAMS); the phone's Approve path runs his press (`PhoneCardDesk`) only when no passkey is asked.
11. **`test_arch_coverage::test_the_real_guide_passes` fails until the guide has R18's cards** (section 6): `src/jarvis/calls`, `src/jarvis/calldesk`, `src/jarvis/config_calls.py`, the 11 `console-calls*.js` modules, the collections `calls`, `call_settings`, `call_lang_check`, `call_desk`, `call_desk_codes`, `call_lines`, `call_line_audio`, `call_check_sentences`, and the API host `api.sarvam.ai` (`arch_coverage.json` `api_hosts`).

## 5. What still needs the owner's hands

1. **The call desk** on the laptop: VB-CABLE (free) installed; the kit from Calls → Settings → "Download the call desk" (needs `JARVIS_PUBLIC_BASE_URL` https on the server), `install-calldesk.ps1`, then `install-calldesk.ps1 -Link` with the code from Calls → Settings → "Link the call desk" (once, 10 minutes); no Bluetooth headset on the laptop during calls; Phone Link with calls set up (deploy/calldesk/README.txt).
2. **The new phone app** (About 18.0.0, code 2): install from the laptop as for R7; Allow calls; notifications on; battery Unrestricted (INTEGRATION-D.md section 4).
3. **The language check**: Calls → Languages → Run (the estimate first: inside the free allowances it is ₹0; checking all 13 languages needs more than Google's free hour of hearing, and the estimate shows the ≈ ₹2.29 past it before anything runs); then **score voices**: listen to 3 samples of each passing language over a real call (or ask a native speaker) and enter the 1–5 scores (`POST /v1/calls/languages/score`).
4. **Calls settings**: his first name (JARVIS says whose assistant it is), the caps if not ₹200 / ₹20 / 6 minutes; answering missed calls stays off until he switches it on.
5. The live checks of plan 10 step 6: one English call to a friend, one call with a language switch, optionally one missed call answered.

## 6. The Build Book after the join

`PYTHONPATH=src python -m jarvis.buildbook.gen pages --list` on `r18-i1`: **154 pages: 68 ok, 84 stale, 1 failing, 1 missing**; on the tree before R18's code (92b1a82): 153 ok. So every item below is R18's. `pages --check`: the same 86 pages, 176 problems; `pages --narration-check`: 26 narrations ok, 0 problems (no narration exists for R18 yet).

**Missing (1):** `pg_screen_calls` (the Calls screen).

**Failing (1):** `pg_chapter_planned` (`docs/plans/r18-calls.md` is new to it; `docs/plans/r6-4-book-look.md` left its refs; its flow nodes name the old ref).

**Stale (84)**, by kind:

- chapters (7): `pg_chapter_what`, `pg_chapter_example`, `pg_chapter_data`, `pg_chapter_answers`, `pg_chapter_setup`, `pg_chapter_technology`, `pg_chapter_costs`
- modules (10): `pg_module_console`, `pg_module_brain`, `pg_module_home`, `pg_module_vitals`, `pg_module_approvals`, `pg_module_android`, `pg_module_helpers`, `pg_module_delivery`, `pg_module_book`, `pg_module_wardrobe`
- cards (19): `pg_card_c01`, `pg_card_c02` (the calls routes, sockets, kit, console and wiring files are new to it), `pg_card_c11`, `pg_card_c28`, `pg_card_c39`, `pg_card_c49`, `pg_card_c51`, `pg_card_c55`, `pg_card_c57`, `pg_card_c58`, `pg_card_c59`, `pg_card_c62`, `pg_card_c63`, `pg_card_c64`, `pg_card_c65`, `pg_card_c67`, `pg_card_c68`, `pg_card_c72`, `pg_card_c73`
- screens (22: `console.html` changed): `pg_screen_chat`, `pg_screen_brief`, `pg_screen_approvals`, `pg_screen_activity`, `pg_screen_history`, `pg_screen_memory`, `pg_screen_vault`, `pg_screen_things`, `pg_screen_notes`, `pg_screen_privacy`, `pg_screen_home`, `pg_screen_faces`, `pg_screen_voice`, `pg_screen_integrations`, `pg_screen_media`, `pg_screen_vitals`, `pg_screen_connectors`, `pg_screen_people`, `pg_screen_book`, `pg_screen_construct`, `pg_screen_helpers`, `pg_screen_camera`
- services (26: `config.py` changed): `pg_service_anthropic`, `pg_service_cloud_run`, `pg_service_cloud_scheduler`, `pg_service_firestore`, `pg_service_frankfurter`, `pg_service_frigate`, `pg_service_gemini`, `pg_service_gmail`, `pg_service_google_calendar`, `pg_service_google_cloud_speech_to_text`, `pg_service_google_cloud_text_to_speech`, `pg_service_google_drive`, `pg_service_google_maps_platform`, `pg_service_google_photos_picker`, `pg_service_google_sign_in`, `pg_service_google_tasks`, `pg_service_home_assistant`, `pg_service_mosquitto`, `pg_service_ollama`, `pg_service_openai_compatible`, `pg_service_redis`, `pg_service_tailscale`, `pg_service_tavily`, `pg_service_telegram`, `pg_service_web_push`, `pg_service_youtube_data_api`

**Not in the Book's catalogue yet (the Book refresh adds them; the generator lists only catalogued pages):**

- the guide's cards for R18 (next free ids **C74–C78** proposed): the Calls skill (cards, approvals, limits, records, retention, booking, templates, answering: `calls/{cards,approvals,limits,records,retention,booking,templates,answering}.py`, `api/calls_handlers_cards.py`, `api/calls_console.py`); the call engine and hub (`calls/{engine*,hub,brain,guard,summary,captions,live}.py`, `api/calls_ws.py`); call speech and the language check (`calls/speech/**`, `calls/langcheck/**`); the call desk (`calldesk/**`, `deploy/calldesk/**`, `api/calldesk_kit.py`); phone calls (`phone/calls*.py`, the app's `calls/*`) — with the I0 seams (`calls/{models,protocol,ports,store,settings,prices,tools}.py`, `config_calls.py`, `api/calls_routes.py`) and the join (`api/r18_wiring.py`, `calls/join*.py`) placed among them;
- a module for them in `buildbook/gen/modules.py` (e.g. `calls`, "Phone calls") → its page **`pg_module_calls`**, cards' pages **`pg_card_c74`…`pg_card_c78`**, and its narration **`module_calls.md`**;
- new services if the guide lists them: Microsoft Azure Speech, Sarvam, Bhashini, Hugging Face (FLEURS) → `pg_service_*`.

## 7. Checks run at I1

- Touched and new tests, once, behind `flock /tmp/jarvis-heavy.lock` (every `test_calls_*`, `test_calldesk_*`, `test_r18_*`, the calls eval, every seam pin, the wiring tests of R2–R14, the phone door's, the Telegram guards, the skill register, the console assets, the deploy tests): **3,421 passed, 6 failed**. Five were pins the join moved (A1's offered test, I0's tools test, R2's tick names, R7 C's door routes, R11's dock order after E's 1c6b70e): fixed and rerun (90 + 1,016 passed). The sixth, `test_arch_coverage::test_the_real_guide_passes`, waits for the guide's R18 cards (4.11).
- `tests/test_r18_i1_join.py` (26): the wired app and its 501 without the token key, the door route, the image, the eval, the dial chain (A1's press → the gate → D's queue, one use, this call only, 2 minutes), the slot rule, records sealed (8 kHz WAV, transcript, summary; an objection; a failing part), answering, the phone's card decisions and results, metering once, the speech choice and detection, English "not yet checked", the background check and its progress, the console's names, `?confirm=1`.
- Browser (Playwright, `JARVIS_BROWSER_TESTS=1`): `tests/browser/test_r18_e_calls.py` and `test_r18_e_look.py`, **25 passed** on the joined branch (NumPy for the test server's Python 3.13 from a separate `--target` directory, nothing installed in a venv).
- `ruff check` clean on every file R18 touched (`tests/test_r63_seams.py:114` and three unformatted files are older than R18); `mypy --strict` on `jarvis.calls`, `jarvis.calldesk`, `jarvis.phone`, `jarvis.mobile`, `config_calls`, `api/app.py`, `api/tick_wiring.py` and the R18 API files: clean but for `memory/redis_store.py:67`, which fails the same on `r18-i0` (this venv's Redis stubs).
- The Book: `pages --list` / `--check` / `--narration-check` as in section 6 (unchanged after E's last commit).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v18.0.0 | 27 Nov 2026, 15:30 IST | R18 | First edition: the join, its wiring decisions, the mismatches fixed, the known limits, the owner's steps, the Book's list | 🛠 Mark XXV |
