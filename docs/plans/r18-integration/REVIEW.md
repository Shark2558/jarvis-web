Version v18.0.0 · 27 Nov 2026, 19:40 IST · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# R18 "Calls from your laptop": the combined security and code review

Branch `r18-review`, from `r18-book` (795091c). One reviewer with a fresh context read the whole
release (`git diff origin/main...HEAD`: `src/jarvis/calls/**`, `calldesk/**`, `phone/calls*`,
`api/calls_*`, `api/r18_wiring.py`, `config_calls.py`, the console's `console-calls*.js`,
`deploy/calldesk/**`, the Android calls code, the Book), handled every item of the Workshop's
notes, fixed every CRITICAL and HIGH and the MEDIUMs that were cheap, each with a test written red
first, and ran the one final check pass (section 3).

## 1. Findings

No CRITICAL was found. Counts: **3 HIGH** (3 fixed), **12 MEDIUM** (12 fixed), **10 LOW** (7 fixed, 3
left), and one owner decision carried out (section 2). Rows 12, 23 and 24 are the ADD writer's
three items (the Workshop's message during the review).

| # | Severity | Where | What | Fix | Test |
|---|---|---|---|---|---|
| 1 | HIGH | `calls/cards.py:206` (`offered`) | The speech option was ranked by its price past the free allowance, so with Sarvam on, paid Sarvam (≈ ₹0.70 a call minute) beat Google (≈ ₹1.57 past free) while Google's free allowance still covered the call: the owner's "free first" rule broken, on the card's estimate, the language table and the call itself | `Estimator.free_options(minutes)` names the options a call costs ₹0 on now (can't bill, or the allowance covers it); `offered(results, settings, free)` ranks those first, then the known price, then the option order; used by `CardBuilder`, the language table and `SpeechChoices.refresh` (for the card's own length, passed by `EngineStarter`) | `test_calls_cards.py::test_review_*` (3), `test_calls_handlers_cards.py::test_review_the_language_table_offers_free_first`, `test_r18_i1_join.py::test_review_the_call_speaks_free_first_*`, `::test_review_the_starter_reads_the_table_for_the_card_s_length` |
| 2 | HIGH | `backup/walk_checks.py:31` | `KNOWN_SUBCOLLECTIONS` lacked the calls' `cards`, `records`, `numbers`, `months`, `sealed`, `sealed_chunks`: once a call was kept, the monthly restore drill's document count came out short and the drill failed closed (the notes' `test_r14_a_verify`) | the six added | `test_r14_a_verify.py::test_the_known_sub_collections_are_pinned_against_the_stores` (red on the base, green) |
| 3 | HIGH | Privacy panel (`api/personal.py`) | No Privacy row for calls: a call could be deleted only in Calls or by the 30-day job and never exported; the settings, the desk link and the check's results were not listed at all | `calls/privacy.py`, four rows in a "Phone calls" section: `calls` (records, sealed parts, cards, numbers called before; export with the number masked and no audio; delete with the passkey; the limits' counters stay), `call_settings` (delete = the defaults), `call_desk` (delete = Unlink, an unused code too), `call_lang_check`; wired by `r18_privacy_sources` | `test_r18_review_privacy.py` (7, one through the wired app) |
| 4 | MEDIUM | `core/models.py:154` (`PendingApproval`) | The Approvals panel prints a card's arguments as JSON: a waiting `calls_place` showed the whole number (and a booking's `give_number`) | `shown_arguments`: what a card shows carries the numbers as `+91 …0001`; the gate keeps the whole arguments, which are what runs | `test_r18_review_approvals_mask.py` (7); browser `test_r18_review_look.py` (the Approvals card) |
| 5 | MEDIUM | `core/guardrails.py:74`, `telegram/service.py` | Telegram refused a call card only through the R3 rule, which the eval's negative control switches off: a forged or old Approve button then placed a call | `calls_place` in `CONSOLE_ONLY_TOOLS` (and `NO_BULK_TOOLS`): never buttons, a forged button refused, whatever the R3 switch | `test_r18_review_telegram_calls.py` (5; red with the R3 rule off) |
| 6 | MEDIUM | `api/calls_routes.py:149` | A part raising anything but `CallsRefused` (a store down, a seal that doesn't open) gave Starlette's bare 500 | logged by class name, answered 503 `unavailable` in plain words, never the error's text (the kit's build too) | `test_r18_review_routes.py::test_review_a_failing_part_answers_503_*` (23 routes) |
| 7 | MEDIUM | `calls/join_speech.py:322` (`score`) | The runner's `ValueError` ("Score at least one sample") became a 500 | 422 with its words; a store that can't be read 503 | `test_r18_review_routes.py::test_review_a_bad_voice_score_is_422_not_500` |
| 8 | MEDIUM | `console-calls-settings.js` | The daily limits, the caps' ranges and Sarvam's prices were typed in the console (drift from `calls/models.py` and the price settings) | `settings_view` carries `limits`, `ceilings`, `prices`; the console reads them and says plainly when one is unknown | `test_calls_handlers_cards.py::test_review_the_settings_carry_*`; browser `test_r18_review_calls.py` (3) |
| 9 | MEDIUM | `console-calls-langs.js` | No way to enter the language check's 1–5 voice scores (`POST /v1/calls/languages/score` existed): the owner's step was blocked | "Score the voice" on a checked row: up to three samples, 1–5 each, in the console's own `.seg` | browser `test_r18_review_calls.py::test_review_a_checked_voice_is_scored_*` |
| 10 | MEDIUM | `console-calls-settings.js`, `calls/hub.py:263` | No Unlink for the call desk in the console; `unlink` left an unused link code alive | Unlink (after his yes) calls `DELETE /v1/calls/desk`; `DeskDoorService.unlink` also spends the code | browser `test_r18_review_calls.py::test_review_unlink_*`; `test_r18_review_privacy.py::test_review_the_desk_row_*` |
| 11 | MEDIUM | `buildbook/gen/facts_routes.py:264` | The Book's route reader skipped a dict's `**spread`, so the calls' `/static/` routes were missing from the fact pack (the notes' `test_m9`) | `dict_pairs` follows a spread of another constant dict, each entry read where it is written | `test_r63_a_facts_units.py::test_r18_review_*`, `test_r63_a_facts_real.py::test_m9_*` (red, green) |
| 12 | MEDIUM | `storage/approvals.py:31` (the ADD writer's item 1) | A waiting `calls_place` card's arguments (the number, a booking's `give_number`) sat in plain text in the `approvals` collection for up to 10 minutes, while every other R18 number is sealed | `DocApprovalStore.use_seal` (an `ArgumentSeal`: sealed in, opened out, a card that doesn't open is unreadable); `calls/pending.py` `CallNumberSeal` seals each number under the keyring's `calls` purpose, bound to the approval id and field; `finish_r18` puts it on the gateway's store. The masked display stays | `test_r18_review_approval_seal.py` (10, through the gateway's propose-and-approve) |
| 13 | LOW | `api/calls_routes.py:437` | `?ticket=` was taken whenever the bearer or cookie didn't let him in, not only when none came | the ticket only when the socket brought no other credential (and a refused try spends no ticket) | `test_r18_review_routes.py::test_review_a_live_ticket_*` |
| 14 | LOW | `calls/join.py:319` (`PhoneCardDesk`) | Checked: the phone's Approve can't skip the passkey (a new number, the rule in force, or the rule unreadable all answer `passkey_needed`). A press the approval guard refused answered `unavailable` | a guard refusal answers `passkey_needed` (the phone opens the console) | `test_r18_i1_join.py::test_review_the_phone_s_approve_never_skips_his_passkey` |
| 15 | LOW | `console-calls-langs.js:11` | The Languages intro said the check "holds a mock call" (not built, I1-NOTES 4.1) | the words say what it does, and that he scores each voice | browser `test_r18_review_calls.py` |
| 16 | LOW | `console-calls-langs.js` | The console never sends `accept_unknown`, so Bhashini can't be checked from it, and nothing said so | the estimate says plainly "Left out: Bhashini … never counts an unknown price as ₹0" (an opt-in would still leave every card's estimate unknown, which the limits refuse) | browser `test_r18_review_calls.py::test_review_the_estimate_says_bhashini_*` |
| 17 | LOW | `deploy/calldesk/README.txt:47,87` | "Calls -> Call desk" does not exist | Calls -> Settings -> "Call desk on your laptop" -> "Link the call desk" / Unlink | `test_calldesk_kit.py::test_review_readme_*` |
| 18 | LOW | `calls/live.py`, `calls/langcheck/api.py`, `console-calls-live.js`, `console-calls-vitals.js`, `calls/records.py`, `calls/speech/catalogue.py`, `phone/calls.py` | Docstrings: `/api/calls`, Opus/16 kHz (it keeps 8 kHz WAV), Bhashini "₹0 at low volume" (unknown), the phone's keyring key (ephemeral) | the words follow the code | — |
| 19 | LOW | `calls/speech/lines.py` | `call_lines` / `call_line_audio`: nothing in the joined app writes them | **Left**: B's tested cache is the R18.x follow-up that makes the lines' audio once (I1-NOTES 4.3); the module now says it is not wired, as the guide already does | — |
| 20 | LOW | `calls/engine.py` `__init__` (69 lines), `calls/speech/build.py` `build_speech` (58), `api/r18_wiring.py` `_build` (60) | Over the 50-line guide | **Left**: straight-line constructors and wiring with no branching worth splitting; no file is over 800 lines | — |
| 21 | LOW | `calls/hub.py:154` (`take_code`, `spend_code`) | Two link requests racing with the same right code could both link (take, then spend) | **Left**: both hold his code; the later link wins and the earlier desk's socket is dropped at once (`drop_desk`) | — |
| 22 | LOW | the Book | Pages that said Privacy has no calls row, "cheapest" without free first, the phone's Approve, the Calls screens | 52 page stamps and 9 narration stamps after reading each diff, the words fixed where they were wrong | `pages --check`, `--narration-check` |
| 23 | MEDIUM | `deploy/cloudrun.sh` (the ADD writer's item 2) | No deploy step for the optional speech keys (Azure F0, Sarvam, Bhashini) | `speech_keys`: each mounted from Secret Manager only when its secret exists, both deploy paths, in the grant loop (a failed grant leaves that key out, never fatal), a quick re-run unmounts one whose secret is gone; no question and no value in the repository. The calls README's "On the server" says how to store a key and the three plain settings (Azure region, Sarvam's server switch, Bhashini's user id). The go-live guide (a project document, out of this repository) needs the same lines | `test_r18_review_deploy_speech.py` (7, bash run with `gcloud` stubbed) |
| 24 | MEDIUM | `evals/calls_language` (the ADD writer's item 3) | The calls eval tested B's option order, not the app's free-first choice | suite `free_first`: allowance left → Google before cheaper Sarvam; used → the cheapest paid option he allows; Sarvam off → never; Azure's free tier before paid; an unknown price last. Control: list-price ranking (before fix 1) must fail it, and does | `run.py --mock`: 6/6, control fails; `test_evals_calls_language.py` |
| 25 | MEDIUM | `evals/r6_3/{facts,tour,narration}.py` | The mock evals failed `r6_3` on R18's Book (pins of 73 cards, 179 settings, 46 scrubbed paths, 31 services, 11 other modules, 26 narrated chapters) | pins moved to R18's 78, 197, 62, 35, 12, 27, each commented | `run_all_mock.py`: r6_3 30/30 |

Checked and sound (no finding): every call starts with his press; `calls_place` is R3 with a card
every time and no "don't ask again"; the grant is one use, 10 minutes, spent once for that call id
(`GrantBook.take`, `live_until` spends nothing, `give_back` on a refused dial); a never-called
number needs the passkey and is refused while the rule is off; the chat's call card and the
gateway's card are used once either way; caps (₹200 a month, ₹20 and 6 minutes a call), the day's
limits (10, 2 per number, 3 new, one redial) and quiet hours 21:00–08:00 IST checked at the press
and again in the counting transaction at the dial; emergency, premium, short and international
numbers refused (`check_number`, and the phone's own `DIAL_NUMBER`); speech metered once
(`CallTally`); the desk's socket signed (`jarvis.home.signing`, nonce, ±60 s) before `accept`; the
link code one use, 10 minutes, hashed, 20 wrong tries a window; the door route signed and capped;
the speech hosts pinned (Sarvam's fixed URLs, Azure's region pattern, Bhashini's callback host,
FLEURS on Hugging Face with every redirect checked, no redirects followed by the shared client);
the other person's words fenced as untrusted data, the in-call brain with no tools, the reply
guard on every line and key; no number, transcript, audio, seed or key in a log; numbers and
records sealed; 30-day retention; an objection drops what was recorded; secrets only as
`SecretStr`, none in the repository; the desk's seed in his own profile folder.

## 2. The owner's decision carried out (the Workshop's message, 27 Nov 2026)

| What | Where | Change | Test |
|---|---|---|---|
| Outfit plans kept **90 days after their day** (R13's plan, the Privacy row), not 14 | `wardrobe/styling/plans.py` (`KEEP_DAYS`, `StylingDoc.pruned`), `wardrobe/styling/calendar.py` (`_room`) | `KEEP_DAYS = 90` (a new plan's day stays 14 back to 30 ahead, `BACK_DAYS`). `MAX_PLANS` 60 would have capped plans long before 90 days (one a day fills it in 60), so it is **raised to 250**: two a day over the 121 days a plan can be on, a full document of the largest plans about 0.68 MiB, under Firestore's 1 MiB. The calendar's cap is split so kept past plans never stop it and a flood of invites stays capped as before: `MAX_CAL_AHEAD` 20 from today on, `MAX_CAL_PLANS` 100 kept in all; his own always have room for one a day. `pg_card_c71` says it | `test_r18_review_outfit_plans.py` (7, red first) |

## 3. The final check pass

Filled in when it ran (section 3 of the change log's last row).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v18.0.0 | 27 Nov 2026, 19:40 IST | R18 | First edition: the findings, the owner's outfit-plans decision carried out, the check pass | 🛠 Mark XXV |
