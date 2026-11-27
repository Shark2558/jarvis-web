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

## What the console sends and reads (A1's `CallsApi` views, `r18-a1` @ bc67de7)

| Route | Console sends | Console reads |
|---|---|---|
| `GET /v1/calls/status` (A2/I1: not in A1) | — | `desk {connected, ready, problems[], bt_headset}`, `phone {linked}`, `month {used_inr, cap_inr}`, `today {calls, max}`, `active {call_id, state}` |
| `POST /v1/calls/cards` | a `PlaceArgs` draft (`number?` E.164, `contact?`, `purpose`, `may_say[]`, `may_agree[]`, `languages` (first = opening), `max_minutes`, `booking?`, `template?`) or `{template, fields}` (the template's own fields); Edit adds `replaces` (and resends the card's number) | `card_view`: only `number_masked` / the last 4 digits are shown (the whole `number` is kept for Edit, never drawn), `needs_passkey`, `blocked {words}`, `estimate_inr` |
| `POST /v1/calls/cards/{id}/approve` | `{}`; after `{status: "needs_passkey", approval_id}`, his next press sends `{approval_id, passkey}` (`JarvisPasskey.approve(approval_id)`, purpose `approve`) | `{status, card_id, call_id}` → the live view opens |
| `POST /v1/calls/cards/{id}/cancel` | `{}` | `card_view` |
| `GET /v1/calls/records?limit=50`, `GET …/{id}` | — | `record_view`; the record adds `transcript {lines[{who, lang, text, english}]}` and `summary {english, agreed, next_steps, needs_owner, message}` |
| `PUT …/keep` `{keep}`, `POST …/booking/undo`, `DELETE`, `GET …/audio` | | `record_view`; Undo's `words` are shown; audio any Web Audio decodes (WAV or Ogg/WebM Opus) |
| `GET`/`PUT /v1/calls/settings` | the changed `CallSettings` fields; `confirm_raise: true` whenever he confirmed (a raise, Sarvam or the balanced tier on, answering on, fewer days) | `settings_view` with `templates [{name, title, fields}]` (the ready cards for New call) |
| `GET /v1/calls/languages` | — | `{languages: [{lang, name, offered, option, inr_per_minute, results[LanguageResult]}]}` (a flat result list works too) |
| `POST /v1/calls/languages/check` (B/I1) | `{confirm: false}` then `{confirm: true, estimate_inr}` | `{estimate_inr, languages}` (count); a row whose result has `running: true` shows "Being checked" |
| WS `/v1/calls/{id}/live` (`?device=phone` on the phone layout) | `listen {audio}` (first; `false` until he presses Listen live), `takeover`, `tell {text ≤ 500}`, `hangup` | `caption`, `state` (`LiveState`), binary `0x03` PCM; close codes 4400/4401/4404/4501 shown in words, not retried |

Chat: a reply's `ChatResponse.cards` item `{kind: "call_card", ...card_view}` is drawn under the reply (Call, Edit, Cancel). Nothing emits it yet: in the chat, `calls_place` shows the gateway's own approval card.

## Open points

- **Status**: `GET /v1/calls/status` is A2's/I1's delegate; the shape above is what the readiness line, Vitals' line and the live view need.
- **Token auth and the live socket**: a browser cannot send `Authorization` on a WebSocket, so in `JARVIS_AUTH_MODE=token` the live view needs another way in (cookie mode works). Tests stub the socket.
- The Approvals panel's existing card prints `a.arguments` as JSON: for `calls_place` that would show the full number unless the gateway redacts it.
- `test_arch_coverage::test_the_real_guide_passes` wants the new console modules in a guide card's "Where in the code" (the Book refresh).
