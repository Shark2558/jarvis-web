Version v18.0.0 · 27 Nov 2026, 13:40 IST · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# R18 Calls — the I0 seams (code against these)

Built on `r18-i0` from `BUILD-BRIEF.md` "Contracts". Import, don't copy. Names that **differ from the brief** are marked ⚠.

## Differences from the brief ⚠

| Brief | Code | Why |
|---|---|---|
| `/api/calls/…`, `/api/calls/desk/ws`, `/api/calls/{call_id}/live` | **`/v1/calls/…`**, `/v1/calls/desk/ws`, `/v1/calls/{call_id}/live` (`protocol.DESK_WS_PATH`, `LIVE_WS_PATH`) | every JARVIS route is `/v1`; the app's per-client rate limiter covers `/v1` only |
| tools `calls.place`, `calls.answer_mode` | **`calls_place`**, **`calls_answer_mode`** (`calls.tools.PLACE`, `ANSWER_MODE`) | every tool name uses `_`; Anthropic tool names may not contain `.` |
| `takeover` (cloud→desk) / `takeover` (console→cloud) | classes `DeskTakeover` / `LiveTakeover` (both `type: "takeover"`) | one name per class |
| config keys in `config.py` | in **`src/jarvis/config_calls.py`** (`CallsConfig`, a base class of `Settings`: still `settings.<key>`, `JARVIS_<KEY>`) | config.py's size guard (791) |
| `CallsSockets.live(ws, call_id)` | `live(ws, uid, call_id)` | the route checks the owner first |

## Modules (`src/jarvis/calls/`)

| Module | Names |
|---|---|
| `models.py` (pure, desk-safe) | `CallCard` (`digest()`, `first_language`), `CardLimits`, `Booking`, `TimeWindow`, `CardStatus`, `CallRecord` (`delete_after`), `CallState` (`.terminal`), `EndReason`, `Direction`, `Heard`, `LanguageResult`, `LangCheckBars`/`LANG_CHECK`, `CallSettings`, `AnswerPolicy`, `SpeechMode`, `SpeechOption`, `Speaker`; `opening_line(first_name)`, `check_languages`, `is_language`, `new_card_id` (`cc_<12hex>`), `new_call_id` (`call_<12hex>`) |
| constants | `MONTH_CAP_INR` 200, `CALL_CAP_INR` 20, `CALL_MAX_MINUTES` 6, `CALLS_PER_DAY` 10, `CALLS_PER_NUMBER_PER_DAY` 2, `NEW_NUMBERS_PER_DAY` 3, `NO_ANSWER_REDIALS_PER_DAY` 1, `QUIET_FROM` 21:00, `QUIET_UNTIL` 08:00, `QUIET_ZONE`, `EMERGENCY_NUMBERS`, `PREMIUM_PREFIXES` ("1900"), `HOME_COUNTRY_CODE` "+91", `APPROVAL_TTL_S` 600, `RETENTION_DAYS` 30, `ANSWER_AFTER_RINGS` 5, `MAX_INDIAN_LANGUAGES_PER_CARD` 3, `ENGLISH`, `LANGUAGES`, `SCHEDULED_LANGUAGES` (22), `LANGUAGE_NAMES`, `E164`, `CARD_ID`, `CALL_ID` |
| `protocol.py` (pure, desk-safe) | audio: `SAMPLE_RATE` 16000, `FRAME_BYTES` 640, `AudioKind.THEM/JARVIS/MIXED` (0x01/0x02/0x03), `pack_audio`, `unpack_audio`, `split_frames`, `MAX_FRAMES_PER_MESSAGE` 50; `parse_desk`, `parse_cloud_to_desk`, `parse_phone_command`, `parse_phone_event`, `parse_live_client`, `parse_live_server`, `dump`; `ProtocolError` (never quotes the message); close codes `WS_BAD_MESSAGE` 4400, `WS_UNAUTHORIZED` 4401, `WS_GONE` 4404, `WS_NOT_BUILT` 4501 |
| `ports.py` | `Hearing`, `Voice`, `LanguageDetector`, `SpeechUnavailable`; `CallStore`, `CallStoreUnreadable`, `NumberSealer`, `DayCounts`, `LimitCheck`; `DeskLink` (`send`, `send_audio`, `is_ready`, `state`), `PhoneLink` (`send`, `last_state`); `CallsApi`, `CallsSockets`, `DeskDoor`, `DeskKit`, `CallsRefused(status, code, words)` |
| `store.py` | `DocCallStore(docs, prefix=, sealer=, base=)`, `MemoryCallStore()` (tests), `KeyringSealer(keyring)` (prod), `MemorySealer` |
| `settings.py` | `defaults(settings)`, `read`, `apply`, `CallSettingsStore`, `CallSettingsRejected`, `owner_key` |
| `prices.py` | `speech_prices(settings, usd_inr) -> {SpeechOption: SpeechPrice}`; `SpeechPrice.inr_per_minute()`, `.inr_per_chars(n)` raise `PriceUnknown` (unknown is never ₹0) |
| `tools.py` | `calls_tools(calls: CallTools)`, `CallTools` (`place`, `preview`, `answer_mode`), `PlaceArgs`, `AnswerArgs`, `place_summary`, `answer_summary` |

## Messages (`type` → class)

- desk → cloud: `hello` Hello · `state` DeskState (also the answer to `ping`) · `vad` Vad · `heard_text` HeardText · `played` Played · `dtmf_done` DtmfDone · `mic` Mic · `error` DeskError
- cloud → desk: `prepare` Prepare · `say_text` SayText · `dtmf` Dtmf · `stop_speaking` StopSpeaking · `takeover` DeskTakeover · `release` Release · `ping` Ping
- cloud → phone: `call.dial` CallDial · `call.answer` CallAnswer · `call.end` CallEnd · `call.route` CallRoute; phone → cloud: `call.state` CallStateEvent (`at` is an aware ISO time)
- live, server → client: `caption` LiveCaption · `state` LiveState; client → server: `listen` Listen · `takeover` LiveTakeover · `tell` Tell · `hangup` Hangup

## Routes (`src/jarvis/api/calls_routes.py`, `install_calls_routes(app)`, mounted in `app.py`)

Owner-only (`require_auth` + `current_user`), `no-store`, bodies JSON objects ≤ 16 KB. 501 `not_built` until I1 sets the slot; 503 `calls_off` when `calls_enabled` is off; `CallsRefused` → `{error, detail}`.

| Path | Slot.method |
|---|---|
| `GET /v1/calls/status` | `calls_api.status(uid)` |
| `POST /v1/calls/cards`, `POST /v1/calls/cards/estimate` | `create_card(uid, body)`, `estimate(uid, body)` |
| `GET /v1/calls/cards/{card_id}`, `POST …/approve`, `POST …/cancel` | `get_card`, `approve(uid, card_id, body)`, `cancel` |
| `GET /v1/calls/records?limit=1..200`, `GET`/`DELETE /v1/calls/records/{call_id}` | `list_records(uid, limit)`, `get_record`, `delete_record` |
| `PUT …/records/{call_id}/keep` `{keep}`, `GET …/audio`, `POST …/booking/undo` | `keep_record(uid, id, keep)`, `record_audio → (bytes, media type)`, `undo_booking` |
| `GET`/`PUT /v1/calls/settings`, `GET /v1/calls/languages`, `POST /v1/calls/languages/check` | `get_settings`, `put_settings(uid, body)`, `languages`, `run_language_check(uid, body)` |
| `POST /v1/calls/desk/code`, `DELETE /v1/calls/desk` | `calls_desk_door.code(uid)`, `.unlink(uid)` |
| `POST /v1/calls/desk/link` (no session: the code is the proof) | `calls_desk_door.link(body)` |
| `GET /v1/calls/desk/kit`, `…/kit/info` | `calls_desk_kit.build()`, `.version` |
| WS `/v1/calls/desk/ws` | `calls_sockets.desk(ws)` (A2 checks the desk's signed credentials before `accept`) |
| WS `/v1/calls/{call_id}/live` | owner checked here (bearer, or his cookie from JARVIS's own `Origin`), then `calls_sockets.live(ws, uid, call_id)` |

## Store layout (Docs port; numbers sealed, keyring purpose `calls`)

`{p}calls/{uid}/cards/{card_id}` · `{p}calls/{uid}/records/{call_id}` (+ `started_ts`, `delete_ts`) · `{p}calls/{uid}/days/{YYYY-MM-DD}` (calls, new_numbers, per_number, no_answer) · `{p}calls/{uid}/months/{YYYY-MM}` (inr) · `{p}calls/{uid}/numbers/{ref}` · `{p}call_settings/{uid}` · `{p}call_lang_check/{lang}_{option}`. `count_call(uid, day, e164, check=)` runs the limits check and the count in one transaction.

## Config (`config_calls.CallsConfig`, on `Settings`)

`calls_enabled` (True) · `azure_speech_key` (SecretStr|None) · `azure_speech_region` ("centralindia") · `sarvam_api_key` (SecretStr|None) · `sarvam_enabled` (False) · `bhashini_user_id` · `bhashini_api_key` (SecretStr|None) · `calls_retention_days` 30 · `calls_month_cap_inr` 200 · `calls_call_cap_inr` 20 · `calls_max_minutes` 6 · prices: `voice_price_azure_f0_inr_per_hour` 0 and `voice_price_azure_f0_inr_per_m_chars` 0 (fixed: F0 cannot bill), `voice_azure_f0_stt_free_seconds` 18000, `voice_azure_f0_tts_free_chars` 500000, `voice_price_sarvam_inr_per_hour` 30, `voice_price_sarvam_inr_per_10k_chars` 30, `voice_price_bhashini_inr_per_minute` None (unknown).

## Gateway and register

`calls_place`: IRREVERSIBLE (a card every time; never Approve all; card text shows only the last 4 digits). `calls_answer_mode`: REVERSIBLE, switching ON always asks. `tools.setup.build_gateway(r18=calls_tools(...))`. Filed in `skills/catalogue.json` under communication/`calls`; listed in `planned` — **I1 empties `planned`** when it registers them (`test_r14_skill_coverage`).

## Left for I1 and the Book

Wire `app.state.calls_api`, `calls_sockets`, `calls_desk_door`, `calls_desk_kit` and `r18=`; empty `planned`; a Permissions row for calls (optional; R3 defaults to Ask first); whether Telegram may approve a call card (security review). Book: `buildbook/gen/layers.py` maps `calls` (L5) and `config_calls` (X) — **C must add `calldesk`** or `--check` fails; the settings scanner now follows `Settings`' `jarvis` base classes (fact pack: 197 settings), but the costs section's voice table (`gen/costs.py` `VOICE_KEYS`) does not list Azure / Sarvam yet; the guide's version line says R18, its calls cards and roadmap row are the Book refresh's; `release.new` reads the plan's title ("Calls from your laptop: the plan"). Seam tests of earlier releases were moved by one where R18 adds (key purposes 27, config.py 791 lines, app.py 734, `planned`).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v18.0.0 | 27 Nov 2026, 13:40 IST | R18 | First edition: every I0 seam, the differences from the brief, what is left for I1 | 🛠 Mark XXV |
