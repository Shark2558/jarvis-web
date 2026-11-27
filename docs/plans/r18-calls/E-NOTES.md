Version v18.0.0 · 27 Nov 2026 · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# R18 E — the console's Calls screens: what I1 and A1/A2 need

Branch `r18-e`. The console only reads and sends what is listed here; every field is checked in `console-calls-shapes.js` (a missing or wrong-typed field shows "—" or nothing, never a guess).

## Registration edits (outside the new files)

| File | Edit |
|---|---|
| `console.html` | one line for `#p-calls` (after Camera), one dock tab (last, after Camera: every older tab shows where it did); the R2 comment joined to keep 782 lines |
| `console-deck.js` | `calls` at the end of `ORDER` (a test pins the middle) and in `defaults()` |
| `console-dock.js` | `DESCRIBE.calls` (More sheet) |
| `console-r7-links.js` | `calls` in `PANELS` (`?open=calls`) |
| `console-r7.js` | loads `console-calls.js`; `noLoad` also says so in `#callsBody` |
| `console.js` | `JarvisCalls.cards(row, r.cards)` beside the other card renderers |
| `api/console.py` | `**CALLS_ASSETS` (the 13 new files, listed in the new `api/console_calls_assets.py`; console.py keeps its 473-line guard) |
| tests | dock count 22 → 23 (`test_console_assets`, `test_arch_coverage`, `test_r7_seams`), `console.html` SHA pins (R6.3, R13, R13.1 seams), `NOT_IN_PAGE` entries; guide C01 lists Calls |

## What the console sends and reads (A1's `CallsApi` views)

| Route | Console sends | Console reads |
|---|---|---|
| `GET /v1/calls/status` | — | `desk {connected, ready, problems[], bt_headset}`, `phone {linked}`, `month {used_inr, cap_inr}`, `today {calls, max}`, `active {call_id, state}`, **`templates[]`** (the ready cards: `id, title, contact_name, number_last4, purpose, may_say, may_agree, languages, booking, limits`) |
| `POST /v1/calls/cards` | `number` (E.164, optional), `contact_name`, `purpose`, `may_say[]`, `may_agree[]`, `languages` (first = opening), `limits {max_minutes}`, `template?`, `booking {windows[{day,start,end}], give_name, give_number?, reason, no_payment, duration_minutes, add_to_calendar}?`, **`from_card?`** (Edit: reuse that card's number) | `{card}` or the card: `id, status, number_last4 \| number_masked \| number_e164` (only the last 4 digits are ever shown), `contact_name, purpose, may_say, may_agree, languages, booking (give_number_last4), limits {max_minutes, max_inr}, estimate_inr, new_number, passkey_required?, approval_id?, ready {ok, problems[]}, call_id?, call_state?, refused?` |
| `POST /v1/calls/cards/{id}/approve` | `{passkey?}`: a proof from `JarvisPasskey.approve(approval_id or card id)` (purpose `approve`) | `{card, call_id}`; a 4xx with `error: "passkey_required"` makes the card ask for the passkey |
| `POST /v1/calls/cards/{id}/cancel` | `{}` | `{card}` |
| `GET /v1/calls/records?limit=50` | — | `{records: [...]}`: `id, direction, state, end_reason, started_at, seconds, cost_inr, contact_name, number_last4, purpose, languages_used` |
| `GET /v1/calls/records/{id}` | — | the above + `summary, transcript [{who, lang, text, english}], has_audio, recorded, objected, keep, delete_after, booking_event {title, when, undone}` |
| `PUT …/keep`, `POST …/booking/undo`, `DELETE`, `GET …/audio` | `{keep}`, `{}` | audio bytes any Web Audio decodes (WAV or Ogg/WebM Opus) |
| `GET`/`PUT /v1/calls/settings` | changed `CallSettings` fields only; **`?confirm=1`** when he confirmed a raise, answering on, Sarvam / balanced on, or fewer days kept | `CallSettings` fields + `azure_status` (`ready` or anything else) |
| `GET /v1/calls/languages` | — | `{results: [LanguageResult...], check {running}}` (one row per language and option; the console picks the passed one, free first) |
| `POST /v1/calls/languages/check` | `{confirm: false}` then `{confirm: true, estimate_inr}` | `{estimate_inr, languages}` (count) |
| WS `/v1/calls/{id}/live` | `listen {audio}` (first message; `false` until he presses Listen live), `takeover`, `tell {text ≤ 500}`, `hangup` | `caption`, `state` (`LiveState`), binary `0x03` PCM; close codes 4400/4401/4404/4501 are shown in words, not retried |

Chat: a reply's `ChatResponse.cards` item `{kind: "call_card", ...card fields}` is drawn under the reply (Call, Edit, Cancel).

## Open points

- **Templates route**: there is none in I0; the console reads `templates` from `GET /v1/calls/status`.
- **Edit**: no card update route; Edit makes a new card (`from_card` when the number is not retyped) and cancels the old one.
- **Token auth and the live socket**: a browser cannot send `Authorization` on a WebSocket, so in `JARVIS_AUTH_MODE=token` the live view needs another way in (cookie mode works). Tests stub the socket.
- The Approvals panel's existing card prints `a.arguments` as JSON: for `calls_place` that would show the full number unless the gateway redacts it.
- `test_arch_coverage::test_the_real_guide_passes` wants the new console modules in a guide card's "Where in the code" (the Book refresh).
