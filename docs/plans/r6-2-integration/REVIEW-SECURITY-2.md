# R6.2 security review 2 (branch r6-2 @ 3f73fd2, delta 9a48161..3f73fd2)

Read-only. Tests run under flock with a Python 3.11 venv: test_r62_book_listening, test_r62_cloud_run_guard, test_r62_book_hear, test_book_lock = 146 passed. Browser suites not run.

## Predecessor findings
| ID | Status | Evidence |
|---|---|---|
| H1 guest lifts owner's Mic off | FIXED | console-book-talk.js:69 sets S.owner from the server's script audience; :132 hides #shMicOn for a guest; :139 unlock only if S.owner and isTrusted; :144 guest focus stays in #shQ; show.js passes audience through |
| L1 guest told about spending | FIXED | buildbook/hear.py _GUEST maps budget_reached and budget_unreadable to a neutral line; words() returns it for a guest. free_used is neutral too |
| L2 console_only token-dev shortcut | FIXED | book_gate.py:56-63 now passes only on a signed-in browser |
| L3 free-form JARVIS_ENV | FIXED | config.py:100-108 strips, lower-cases, accepts dev/staging/prod (see deploy check below) |
| L4 place names in fixtures | NOT FIXED, not new | tests/test_book_guest_voice.py:29-34 still has them; the delta adds none. Defer to the G8 sweep |

## New findings
No CRITICAL, HIGH or MEDIUM.

| Sev | Where | Scenario | Fix | Test |
|---|---|---|---|---|
| LOW-1 | api/book_show.py:196-211 (show_speak) | Owner sets Show voice to Cloud (confirmed). A guest's narration then calls voice.speak(uid, ...) with no free-only limit, so a guest session can spend the owner's money past the free allowance, unlike a guest's cloud listening (free_only). The owner did confirm Cloud, and the settings text says "a guest show uses your choice", so it is not a bypass. It is still inconsistent with the "a guest is never priced" rule. Guest is told nothing about cost. | Give VoiceService.speak a free_only flag and pass free_only=(view.audience != "owner") with FreeAllowanceUsed -> the existing "Use the browser's voice." 503. Or state in the settings text that a guest's tour is charged to the owner. | A guest speak with Cloud voice and an exhausted allowance returns 503 and never calls the TTS engine. |
| LOW-2 | buildbook/show_script.py:104-105 | GET /show/script gives a guest voice and listening. A guest can infer whether the owner chose Cloud (not any rupee value; costs month_inr/limit_inr stay owner-only). The show needs the mode to work. | Accept, or send a guest only a boolean "record" instead of the setting names. | Guest script contains no costs fields (exists) and, if tightened, no "cloud" literal. |
| LOW-3 | api/book_show_hear.py:104 | Setting is read once per request. A /hear in flight while the owner switches Cloud to Browser can still finish: at most one paid call per request, still rate-limited (10/min) and capped by the 30-question session budget. The reverse (stale cloud) cannot happen: legacy docs without voice_rule 2 read as browser (owner.py _voice). | Accept. | None needed. |

## Attacks tried and held (checked and fine)
- Paid STT while Listening is Browser: /hear checks `svc.show.listening(uid) != "cloud"` first and returns 409 before the voice object, the body read and allow_hearing. No other route calls voice.transcribe in the Book. Unreadable settings give {} so the answer is browser, i.e. closed. A stale pre-R6.2 "cloud" reads as browser.
- Paid TTS while Show voice is Browser: show_speak returns 503 browser before voice.speak (unchanged and correct); the client default is also browser.
- confirm_cost: BookSettingsPatch makes it StrictBool; apply() raises CostNotConfirmed (422 confirm_needed) for show_voice or listening == "cloud" unless it is exactly True. It is never stored (popped), nothing is written on refusal, and a later unrelated patch cannot turn the voices to Cloud. The check is server-side inside the transaction, so a missing UI dialog cannot skip it. PUT /settings needs current_user; under Google sign-in the guest lock does not allow it (not in book_lock.ALLOWED), so a guest cannot read or change settings or costs.
- Audit: _changed() writes field names plus cost_confirmed true only; no values, no text.
- /heard: same SHOW dependency (marker or sign-in), same per-owner 10/min limit (LIMITS["heard"] is wired), same live-session check, same 30-question session budget via _no_more, body capped (4000 chars JSON, 500 chars after whitespace collapse -> 422). The text goes only to hear.understood (free rules, no model, no network), is returned and never stored or logged. A guest gets the public words only (_owner_words runs for owner sessions only). No model or injection path: it is data into a pure string function.
- Lock allow-list: /show/heard added to book_lock.ALLOWED, same as the siblings; nothing else added.
- Guest cloud listening: free_only runs Billing.ensure_free under the per-user stt lock with a whole 15 s step required, so a guest can never be priced. FreeAllowanceUsed is caught before BudgetError. Counter unreadable -> BudgetUnavailable -> neutral words.
- Error text: guest answers 409, free_used and budget are neutral; owner Vitals pointers are owner-only.
- Front end: no innerHTML/insertAdjacent/eval in the new JS (grep of the delta). Server and recogniser text goes through textContent and txt(). The Listening settings hint says "Chrome may send your audio to Google ... unless it listens on the device", which is truthful.
- JARVIS_ENV deploy check: values in the repo are dev (.env.example, scripts/ui_snapshots.py, browser conftests) or prod (deploy/cloudrun.sh:520, render.yaml). Dockerfile, docker-compose.yml, Makefile and .github workflows do not set it, so it defaults to dev; field_validator mode="before" does not run on defaults. CI's no-traffic candidate keeps the service's settings. An unset or differently-cased "PROD" is fine. Only a value outside dev/staging/prod (for example "production" or an empty string set by hand) fails at start-up. On Cloud Run that new revision gets no traffic and the old one keeps serving, which is safe and intended. Note for docs/go-live: say "prod", not "production".
- console_only: the dev shortcut is gone; the reader's routes need a signed-in browser plus a live owner session.
- Public repo: no secrets, keys, emails, phone numbers or hostnames in the added lines; the delta adds no place names.

## Verdict
Ship. LOW-1 is worth a follow-up (or a one-line owner-facing note) but does not block R6.2.
