---
page: pg_card_c74
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/calls_console.py": "e1bd4e9bed808d8b"
  "src/jarvis/api/calls_handlers_cards.py": "e6f2959669230273"
  "src/jarvis/api/calls_routes.py": "f6479aa1fe74bfbc"
  "src/jarvis/api/console_calls_assets.py": "d55916e88be20e3e"
  "src/jarvis/api/r18_wiring.py": "0c839cfbaf2e266b"
  "src/jarvis/api/static/console-calls-api.js": "30e91b868cba4573"
  "src/jarvis/api/static/console-calls-card.js": "0a7f743bb3cc8942"
  "src/jarvis/api/static/console-calls-form.js": "7279e89d506cadd2"
  "src/jarvis/api/static/console-calls-list.js": "c0cf7507ca91abcf"
  "src/jarvis/api/static/console-calls-settings.js": "21c585d669c3e753"
  "src/jarvis/api/static/console-calls-shapes.js": "3a6c02eba641a52f"
  "src/jarvis/api/static/console-calls-vitals.js": "ea21f11891908c71"
  "src/jarvis/api/static/console-calls.css": "8fc50ded39f7f054"
  "src/jarvis/api/static/console-calls.js": "5820e269aee5d868"
  "src/jarvis/api/static/console-r7.js": "0613adea76dca0a6"
  "src/jarvis/calls/__init__.py": "afbf055224f4680d"
  "src/jarvis/calls/answering.py": "5989d95eb22c5baf"
  "src/jarvis/calls/approvals.py": "ef3d31ed553e2584"
  "src/jarvis/calls/booking.py": "9e2602ed6c47018e"
  "src/jarvis/calls/brain.py": "f741c4f2234f0b37"
  "src/jarvis/calls/captions.py": "8a531f5a22e1a8b7"
  "src/jarvis/calls/cards.py": "24bb652d78fd44dd"
  "src/jarvis/calls/chat_card.py": "90c25c6c55d5f989"
  "src/jarvis/calls/engine.py": "5cf42570e813ff4b"
  "src/jarvis/calls/engine_ports.py": "366a3fcfbd2253a0"
  "src/jarvis/calls/engine_turns.py": "e3dd50d216e63efb"
  "src/jarvis/calls/engine_voice.py": "cac890f0a4d3bff9"
  "src/jarvis/calls/guard.py": "d300d7c800d4f2c2"
  "src/jarvis/calls/hub.py": "eecd1fae04642ee0"
  "src/jarvis/calls/join.py": "813b02128da9a631"
  "src/jarvis/calls/join_speech.py": "86d3f9a9a39c3909"
  "src/jarvis/calls/langcheck/__init__.py": "b191fe7a0f1b9545"
  "src/jarvis/calls/langcheck/api.py": "f1a5ed89b54bae04"
  "src/jarvis/calls/langcheck/fleurs.py": "46d38040fe11afaa"
  "src/jarvis/calls/langcheck/runner.py": "7708514f57b166ad"
  "src/jarvis/calls/langcheck/scoring.py": "cdff02d85ee9af8d"
  "src/jarvis/calls/langcheck/select.py": "17f8aff69333bcc1"
  "src/jarvis/calls/langcheck/sentences.py": "da6c3c76ebdcd1b4"
  "src/jarvis/calls/limits.py": "beffd3bad55ba80e"
  "src/jarvis/calls/live.py": "b4590b77f80ee087"
  "src/jarvis/calls/models.py": "54a3ab11f7ebea32"
  "src/jarvis/calls/ports.py": "75f7a00bbb601ef6"
  "src/jarvis/calls/prices.py": "09530bc93cd5d9f2"
  "src/jarvis/calls/protocol.py": "3bc2ebd613b92b89"
  "src/jarvis/calls/records.py": "dce6c1a8764c7e0a"
  "src/jarvis/calls/retention.py": "00dcaf2f11571e23"
  "src/jarvis/calls/settings.py": "355877f98d5d6331"
  "src/jarvis/calls/speech/__init__.py": "7cd8cca15eae7567"
  "src/jarvis/calls/speech/audio.py": "0282570850200ed1"
  "src/jarvis/calls/speech/azure.py": "cd27af97dbaf8e28"
  "src/jarvis/calls/speech/bhashini.py": "32a72dec885b81c5"
  "src/jarvis/calls/speech/build.py": "f03b52cba95aad09"
  "src/jarvis/calls/speech/catalogue.py": "09ee31b83a942427"
  "src/jarvis/calls/speech/detect.py": "d25e44790afcfe3e"
  "src/jarvis/calls/speech/errors.py": "da58392f33e803b9"
  "src/jarvis/calls/speech/google.py": "114d5796ec1d46c7"
  "src/jarvis/calls/speech/lines.py": "3599a5f0c2bc41ed"
  "src/jarvis/calls/speech/meter.py": "ee673080feff66fe"
  "src/jarvis/calls/speech/phoneline.py": "79408543a2713deb"
  "src/jarvis/calls/speech/rest.py": "59a2324a4c347664"
  "src/jarvis/calls/speech/sarvam.py": "bc73208ec89e647f"
  "src/jarvis/calls/speech/translate.py": "07a528c755b8b23c"
  "src/jarvis/calls/store.py": "ae0f757b833b4717"
  "src/jarvis/calls/summary.py": "ad280e3f27d4930f"
  "src/jarvis/calls/templates.py": "a10ae6b609b50fff"
  "src/jarvis/calls/tools.py": "ad6671bff6baf019"
  "src/jarvis/config_calls.py": "1de18cfb18b268b6"
  "src/jarvis/tools/reply_cards.py": "97b29df16f9aceb2"
  "tests/test_r18_i1_join.py": "e442748f476b5356"
---
## In plain words
You tell JARVIS who to call and why, in the chat or in Calls, New call, and it writes a call card: the number, the purpose, what JARVIS may say and agree to, the languages, the longest the call may last and its rupee estimate (`src/jarvis/calls/cards.py`). Nothing is dialled until you press Call on that card, every time: a call speaks for you and can't be undone, so there is no standing permission and no "don't ask again", and a number JARVIS has never called also needs your passkey (`src/jarvis/calls/approvals.py`). Fixed limits keep your number clear of spam flags, money caps keep the cost small, and each call's audio, transcript and English summary are sealed in your vault for {{fact:settings.calls_retention_days}} days unless you keep it (`src/jarvis/calls/records.py`).

## Example (made up)
Sanjay types "call the laundry and book a pickup for tomorrow between 10 and 12". JARVIS shows a card: the number ending 4417, the pickup, "may agree: a pickup tomorrow 10:00 to 12:00; no payment", English and Malayalam, 6 minutes at most, about ₹1. He presses Call; the number is new, so his passkey is asked first. The pickup is agreed for 11:00, the summary arrives with an Undo for the calendar entry, and the call waits in Calls with its audio and transcript. He presses Keep on it.

## How it works
`CardBuilder` checks the number as an Indian number, refusing emergency, helpline, premium-rate, international and other short numbers, or takes a saved contact's when exactly one matches; it allows English plus up to {{fact:src/jarvis/calls/models.py:MAX_INDIAN_LANGUAGES_PER_CARD}} Indian languages that passed the language check, and a length never above your setting. `Estimator` prices the speech on the cheapest passing option, the fast-tier brain at about {{fact:src/jarvis/calls/cards.py:TURNS_PER_MINUTE}} turns a minute and the summary; an unknown price makes the estimate unknown, never ₹0. Call runs the gateway's irreversible call card (`src/jarvis/calls/tools.py`), the same press in the Calls panel, under a chat reply (`CallReplyCard`) or on your phone; with "Require passkey for irreversible actions" on, a second press signs it with your passkey (`POST /v1/calls/cards/{card_id}/approve`). A number never called before is refused while that requirement is off, with words saying how to switch it on (`CallsService`). Your approval issues a dial grant, one use and {{fact:src/jarvis/calls/models.py:APPROVAL_TTL_S}} seconds, bound to the number and the card's content, which the engine spends just before the dial (`GrantBook`). `Limits` checks at approval and again at the dial, in one transaction: {{fact:src/jarvis/calls/models.py:CALLS_PER_DAY}} calls a day, {{fact:src/jarvis/calls/models.py:CALLS_PER_NUMBER_PER_DAY}} to one number, {{fact:src/jarvis/calls/models.py:NEW_NUMBERS_PER_DAY}} new numbers, {{fact:src/jarvis/calls/models.py:NO_ANSWER_REDIALS_PER_DAY}} redial of a number that didn't answer, none in the night's quiet hours (`in_quiet_hours`), and the money caps. `RecordKeeper` seals the audio as WAV at {{fact:src/jarvis/calls/join.py:RECORD_RATE}} samples a second, the transcript and the summary, each under its own key; an objection to recording deletes the audio and transcript so far. A booking's slot must fit one of your windows and goes on your Google Calendar through the gateway, with Undo (`BookingCalendar`). `CallRetentionJob` deletes calls past their days unless you pressed Keep. Answering missed calls is off until you switch it on, always its own card (`calls_tools`); then JARVIS answers after {{fact:src/jarvis/calls/models.py:ANSWER_AFTER_RINGS}} rings, for the callers your rule allows, never a withheld number, and only takes a message (`AnsweringPolicy`). Calls opens from the dock where its tab fits without pushing another tab into More, from Vitals' calls line, from a call card in the chat and from its own link (`src/jarvis/api/static/console-calls.js`).

## What it costs
The skill itself costs ₹0, a few Firestore reads and writes a call. A call's own rupees are its speech and its brain, held by default to ₹{{fact:settings.calls_call_cap_inr}} a call and ₹{{fact:settings.calls_month_cap_inr}} a month for calls, and a call lasts {{fact:settings.calls_max_minutes}} minutes at most (`src/jarvis/config_calls.py`). In Calls, Settings you can raise these up to ₹{{fact:src/jarvis/calls/models.py:CALL_CAP_CEILING_INR}} a call, ₹{{fact:src/jarvis/calls/models.py:MONTH_CAP_CEILING_INR}} a month and {{fact:src/jarvis/calls/models.py:CALL_MAX_MINUTES_CEILING}} minutes, and a raise waits for your confirmation (`PUT /v1/calls/settings`). Every rupee also counts against your overall monthly limit (`Limits`).

## When it fails
With calls switched off the routes answer with status 503; without JARVIS's encryption key or a private brain nothing is wired and they answer with status 501 (`src/jarvis/api/r18_wiring.py`). A number or card that can't be placed says why in plain words, and nothing is issued (`CardBuilder`). A card changed after its approval no longer matches its grant, and after a restart no grant is live (`GrantBook`). A day's count, the month or your overall limit that can't be read refuses the call (`Limits`). A sealed part that doesn't open is reported unreadable, never shown empty (`RecordKeeper`). The Privacy panel has no calls row: a call is deleted in Calls or by the retention job, and there is no export (`CallRetentionJob`).
