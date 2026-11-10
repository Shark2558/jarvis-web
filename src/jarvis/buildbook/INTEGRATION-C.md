# R6 builder C: access, sessions, guest isolation, talk-through, wipe: integration notes for I1

Branch `r6-c` (from `r6-i0`). Plan: `docs/plans/r6-build-book.md` D1, D8-D14, D17's guest prompt.
I didn't edit any wiring file. Everything below is for I1 to wire.

## What C ships

| File | What |
|---|---|
| `buildbook/sessions.py` | `DocBookSessions` (ports.BookSessions) + `reserve`/`release`/`put_turn`, `SessionEnded(SessionGone)` |
| `buildbook/closing.py` | `ClosingStore` (mixed into `DocBookSessions`): close once, the notice outbox `{prefix}book_notices/{bk}` |
| `buildbook/telling.py` | `Telling`: the content-free audit lines, the `book_session_closed` words, `{prefix}book_closed/{uid}` |
| `buildbook/unlock.py` | the emergency unlock CLI (`python -m jarvis.buildbook.unlock`), see the runbook below |
| `buildbook/lock.py` | `DocShowLock` (ports.ShowLock) + `refresh(uid)` (an uncached read) |
| `buildbook/guard.py`, `guard_words.py` | `pre_guard`, `post_guard`, `cap`, `normalise`, `book_hosts` (D12) |
| `buildbook/prompt.py` | `GUEST_SYSTEM`, `GUEST_PROMPT_VERSION = "bg1"`, fences, canary (D11, D17) |
| `buildbook/digest.py` | deterministic chunk choice within 10,000 characters (D11) |
| `buildbook/talk.py` | `BookTalk(brains, billing, mode, book, sessions, *, prefs, owner_emails)` (ports.BookTalker) |
| `buildbook/service.py`, `show_script.py` | `BookService` (open/close/wipe/sweep/resume/emergency_unlock/script), `BookSweepJob` |
| `api/book_show.py` | the 8 contract routes (open, script, speak, hear, ask, beat, close, resume) |
| `api/book_show_access.py` | the open and resume proofs (D8, D10) |
| `api/book_lock.py` | `ShowLockMiddleware` (pure ASGI), `install_show_lock_middleware`, `ALLOWED` |
| `api/book_show_wiring.py` | `wire_book_c(...)` and `book_sweep_job(app)`: C's state in one call |
| `evals/r6_book/{access,guest,wipe,lock}.py` + `cases_{guest,lock,access}.jsonl` | BUILT, each with a negative control |

## Wiring steps

1. **`api/r6_wiring.py::wire_r6`**, after A's source and B's vault, sealer and settings:
   ```python
   from jarvis.api.book_show_wiring import wire_book_c
   wire_book_c(app, s, docs, audit, source=<A's BookSource or None>,
               keyring=Keyring.from_settings(s), prefs=<B's Book settings reader>)
   ```
   This sets `book_sessions`, `book_lock`, `book_talk`, `book_service` and `book_show_limits`
   (all None without a keyring or a source, so every route answers 503 `book_off`). It reads
   `app.state.brains`, `billing` and `brain_mode` (they exist by then) and the notifier via
   `r4_wiring._notifier(app)`. `audit` is the gateway's chain that `wire_r6` receives.
   **`prefs`** is any object with `async get(uid) -> Mapping`, using the keys `creator_name`
   (str), `show_voice` ("cloud" | "browser"), `talk_on` (bool, default True) and
   `allow_training_brain` (bool, default False). Wrap B's settings store to fit. If it can't be
   read, C uses the defaults, and a training brain is never allowed.
2. **`install_show_lock(app, s)`**: call `install_show_lock_middleware(app, s)` (from
   `api/book_lock.py`). Update `tests/test_r6_wiring_seams.py::test_the_i0_show_lock_adds_nothing_yet`.
3. **`r6_tick_jobs(app)`**: add `book_sweep_job(app)` when it isn't None (name `book_sweep`,
   budget 30 s), and add it to R5.1's 5-minute watchdog list. It reports `failed` > 0 while a
   delete is still pending.
4. **B's `GET /v1/book`**:
   - `session`: `book_sessions.live(uid, now=)`
   - `lock.on`: `book_lock.get(uid)` (`LockUnreadable` means 503)
   - `talk`: `book_service.talk_state(uid)`
   - `last_closed`: `book_service.last_closed(uid)` (doc `{prefix}book_closed/{uid}` =
     `{last_closed_at, notified}`)
   - `open.fresh_left_s`: `fresh_sign_in_left`
   - `open.passkey_ready`: `permissions.passkey_required(uid)`
5. **B's ● routes** (sections, older sections, ticket): resolve the token with
   `book_service.resolve(uid, token, now=)` (B's code calls `book_sessions.resolve` directly:
   that still works, an expired or idle session it closes is told by the sweep once the notice
   claim expires, ≤ 2 min + the next sweep). Refuse when `view.audience != "owner"` (403
   `owner_only`). The `access` eval's three B rows (`guest-sections`, `guest-older-sections`,
   `guest-ticket`) send a guest token with the lock NOT engaged, so B's audience check is what
   answers; while `api/book.py` is the I0 stub they pass marked `rerun_at_integration`. **After
   the merge, wire B's `book_source`, `book_vault` and `book_tickets` into
   `tests/book_app_fakes.book_app` and re-run `evals/r6_book/run.py --mock --part access`**: with
   B's real routes a `book_off` answer FAILS those rows.
6. **Privacy (D16)**: `book_sessions_source` delete calls `book_service.wipe(uid, now=)` (it ends
   EVERY session of the owner, expired and idle ones included, and returns how many).
7. **`tests/test_r6_contract.py`** pins every route to 503 `book_off` while unwired. Once wired,
   C's routes give 403 `console_only` / 401 `session_gone` to that test's bearer caller.
   Re-scope that test to the unwired app.
8. Add `r6_book (gated)` to `evals/run_all_mock.py`. C's four parts take about 7 s.

## Contract details for D (the shapes D's stubs should match)

- **open**: `{token, session_id, until, idle_until, audience}`.
- **script**: `{release, audience, scenes, closing, costs, talk, voice, session}`.
  - `scenes` holds all 13. 1-11 come from `book.show`. Scene 12 has one beat, `ask`. Scene 13's
    beats are `credit, sealed_<aud>, thanks_<aud>`.
  - `closing` = `{lines:[{id,text}], hand_back: {id:"hand_back",text} | null}` (null for the owner).
  - `costs` is `book.costs`, plus `month_inr` and `limit_inr` for the owner only.
  - `talk` = `{on, why}`; `voice` is "cloud" | "browser"; `session` = `{until, idle_until,
    questions_left}`.
- **speak** `{line_id}` takes a beat id or a `lines.LINES` key and returns audio/mpeg. A 503
  `voice_unavailable` carries a `reason`: `browser` (Book settings), `budget` (this session has
  used its cloud speech) or `not_configured`/upstream. On any of these, use the browser voice.
- **hear** returns 503 reason `budget` after 30 recordings in a session. A guest's recording is
  transcribed WITHOUT the owner's phrase hints (`VoiceService.transcribe(..., owner_phrases=False)`,
  a new keyword with default True; the route passes it).
- **ask**: 422 `too_long` over 500 characters; 429 over 6 a minute.
- **close**: `{reason: "closing" | "end"}`.
- Every expired, idle, closed or unknown token gets 401 `session_gone`, also when the session
  closes while a question is with the brain (`ask`). A book that can't be read, or (for a guest)
  names the owner's address, is 404 `no_book` on `script`, `speak` and `ask`.
- **Resume** (D10: the passkey ONLY):
  1. `POST /v1/book/resume {}` returns 403 `passkey_required` with `lock_id`. The 423 body also
     carries `lock_id`, but only for the owner whose lock it is.
  2. Prove with `JarvisPasskey.prove('book_resume', lock_id)`.
  3. `POST /v1/book/resume {proof}` returns `{resumed: true}`.
  4. When no passkey is in force any more, the answer is 403 `emergency_unlock_needed` (no
     `lock_id`, no sign-in hop): show its `detail`; only the emergency unlock (runbook) helps.

## The lock allow-list (final) and the sign-in routes under the lock

While ANY owner's guest lock is on, an owner's cookie session gets exactly these (exact method and
path; HEAD = GET), everything else 423 `show_locked` (`GET /` 302 `/book/show`):

| Method | Path |
|---|---|
| GET | `/book/show`, `/static/...` (fixed shape, no `..`), `/health`, `/console/config` |
| GET | `/auth/login`, `/auth/callback` |
| POST | `/auth/logout` |
| GET | `/v1/book/show/script` |
| POST | `/v1/book/show/speak`, `/v1/book/show/hear`, `/v1/book/show/ask`, `/v1/book/show/beat` |
| POST | `/v1/book/close`, `/v1/book/resume`, `/v1/passkeys/challenge` |

- **Every passkey register / reset / cancel / remove route is locked** (`/v1/passkeys/reset` is
  OFF the list now), and so are `/auth/me`, `/v1/permissions` (read and change) and
  `/v1/book/open`.
- **`/auth/login` and `/auth/callback`** stay reachable (a signed-out device must be able to sign
  in to reach Resume). A sign-in made under the lock, however "fresh" (`?reauth=1`; Google asks
  nothing more with a live session and sends no `auth_time` unless asked), gives a session the
  middleware holds like any other. Nothing it unlocks is reachable, and no R6 path uses a sign-in
  alone: open needs the passkey AND the fresh sign-in, resume needs the passkey only, the
  emergency unlock needs the server's credentials. The callback clears the session (and the
  `book_guest` flag); harmless, as that flag only matters in the first 3 s after the open.
- **`/auth/logout`** clears this browser's session; the lock is per owner on the server.
- **Websockets** of an owner's session are closed (4423 locked, 4503 unreadable) while a lock is
  on. An HTTP or websocket scope with no `session` in Google mode means the middleware sits
  outside `SessionMiddleware`: 503 `show_lock_unwired` (logged), never "pass".
- The app-wide "no `auth_time` counts as now" in `api/auth.py` (R3) is unchanged: the
  orchestrator raises it with the owner.

## Decided differently from the plan, and why

1. (Withdrawn in the fixes: resume is passkey-only again, the reset is off the allow-list; a
   lost passkey is recovered with the emergency unlock.)
2. (Withdrawn, as 1.)
3. **The lock holds every owner's sessions.** With several `owner_emails`, a lock on any owner
   holds all of them, so switching Google accounts in the same browser isn't a way out. Only the
   owner whose lock it is can lift it.
4. **A per-question canary** instead of per-session. It is strictly stronger.
5. **Stricter-only hardening added:**
   - The `book_guest` flag in the presenting browser's signed session makes the middleware
     re-read the lock uncached, closing the ≤ 3 s cross-instance window right after an open.
   - Each session gets a speech budget of 24,000 characters (about 4× the show) and 30
     recordings, so a guest can't run up the owner's TTS/STT bill.
6. **Refused questions:** a refused question counts toward the 20 and is stored as "", so it
   never reaches a model.
7. **`ai_off` line cases:** No-AI, a reached monthly limit, a failed call and "no private brain"
   all answer `ai_off`, and none of them cost a question. The owner's talk-through uses the same
   guest prompt.
8. **Extra modules** (`guard_words.py`, `show_script.py`, `book_show_access.py`,
   `book_show_wiring.py`) keep every module ≤ 400 lines.
9. **Exactly-once notices** use a content-free outbox `{prefix}book_notices/{bk}` written in the
   same transaction that marks the session closing (see Fixes). From the store's
   `close()`/`open()`, `ClosedSession.notified=True` means "not yours to tell".

## Open / low

- **Per-instance limits that remain:** the speech budget (24,000 characters) and the hearing
  budget (30 recordings) per session live in each instance's memory, so N instances allow N×.
  The monthly billing limit is still the backstop. The question limit is store-backed now.
- A lock document that isn't a lock reads as unreadable (503) until it is fixed by hand.
- The lock store reads one owner at a time (N owners means N cached reads per 3 s per instance).

## Tests and evals (3.11 and 3.12)

- **Tests:** `test_book_{sessions,lock,guard,talk,show_api,wipe,boundaries}.py`,
  `test_book_{close_once,guest_book,guest_voice,unlock}.py`, `test_evals_r6_book.py`.
- **Fakes:** `book_show_fakes.py`, `book_app_fakes.py`, `book_rig_fakes.py`.
- **Evals (C's parts):** `access` 14, `guest` 67, `wipe` 13, `lock` 57.

## Fixes (R6 review, security + python; tests first, each seen failing)

| Finding | Fix |
|---|---|
| SEC HIGH: a guest's one-click "fresh" sign-in could start a passkey reset and later lift the lock | Resume is the `book_resume` passkey ONLY (no sign-in fallback; no passkey in force -> 403 `emergency_unlock_needed`, audited). `POST /v1/passkeys/reset` is off the allow-list; every passkey register/reset/cancel route is 423. The lock eval: a guest's fresh re-sign-in lifts nothing; with no passkey left no sign-in lifts it. |
| (orchestrator) a passkey lost during a lock | `python -m jarvis.buildbook.unlock` (runbook below): server credentials only, audit first, lift, end every session with its notice, a notice even when none was open, asks before acting. |
| SEC MEDIUM: a guest saw a book naming the owner | `guard.book_names_owner` (A's `owner_mentioned` ∪ B's `holds_owner_email`: the address anywhere, the local part ≥ 3 as a whole word, raw and JSON-unescaped, NFKC) at the guest open (404 `no_book`, audited) and again on every guest `script`/`speak`/`ask`; unreadable = refused. Cached per release id. `wire_book_c` passes `s.owner_emails`. |
| SEC LOW guards | "the person who built/made you", creator/maker/builder, a few French (propriétaire, créateur, courriel, téléphone, où habite), Hindi, Tamil and Malayalam phrasings; post-guard reads spelled addresses ("x dot y at gmail dot com", "at the rate", "[at]") and a spelled owner local part. Table-driven in `guard_words.py`. |
| SEC/PY LOW websocket, unwired | Websockets closed 4423/4503 under a lock; no `session` in Google mode -> 503. |
| SEC LOW phrase hints | `owner_phrases=False` for a guest's recording (`voice/service.py`: one keyword, default True). |
| PY HIGH 1 | `wipe`, `resume` and `open` end EVERY session of the owner (open, expired, idle, closing); a session already over says "ended by itself". |
| PY HIGH 2, MEDIUM 3 | `closing.py`: the close transaction marks the session `closing`, drops its turns AND writes `{prefix}book_notices/{bk}` (content-free) claiming the telling. Only the claimer audits and tells, then marks it told. A claim not told within 2 min is re-claimed by the sweep (from the session or the record): a crash after the mark, after the delete, or a `SessionEnded` raised to B is told exactly once. The sweep closes and tells one session at a time; a failure is counted (`failed`) and retried. A delete that finally succeeds adds one audit line ("deleted at HH:MM (its first delete had failed)") and no notice. |
| PY MEDIUM 4 | `ask`: `SessionGone` -> 401 `session_gone`; `speak`/`ask`/`script`: `BookUnavailable` -> 404 `no_book`. |
| PY MEDIUM 5 | The lane RESERVES the question in a transaction before the model call (refused at the limit), gives it back on ai_off, stores the turn without counting again: 6 parallel asks at 1 left make 1 call. |
| PY MEDIUM 6 | The worst-case brain echoes the question and every book excerpt it sees on every answer; dumps its whole context verbatim or reworded on request; calls a tool whenever offered one or told to. Controls, EACH failing the part on its own: post-guard off (4 cases), gateway specs given (17), pre-guard off (45), canary off (exactly `canary-reworded`). |
| PY MEDIUM 7 | Access eval B rows: lock not engaged, must be 403 `owner_only`, marked `rerun_at_integration` while B is the stub (step 5). |
| PY LOW 9, 10, 11, 12 | Every `/open` refusal audited (console_only, 429, bad body, no_book); every ended session returned/told; wipe eval checks no session keeps sealed turns; the 51-line test split; `json_body` is generic. |
| SEC 1 "request `auth_time` as essential" | Not done here (orchestrator: `api/auth.py` stays as R3 designed it; raised with the owner). |

## Runbook: the emergency unlock (a passkey lost during a guest show)

Use it only when Resume says "No passkey of yours is in force any more", or the passkey is lost
and the console is locked. It needs your Google Cloud access (the project's owner): a guest at
your laptop can't run it. In **Google Cloud Shell** (shell.cloud.google.com, signed in as you,
your JARVIS project selected), paste:

```bash
cd ~/jarvis-web && git pull --ff-only
python3 -m venv ~/.jarvis-unlock && ~/.jarvis-unlock/bin/pip install -q -e .
export JARVIS_SESSION_BACKEND=firestore
export JARVIS_FIRESTORE_PROJECT="$(gcloud config get-value project)"
export JARVIS_OWNER_EMAILS="you@gmail.com"
export JARVIS_TOKEN_KEY="$(gcloud secrets versions access latest --secret=jarvis-token-key)"
export JARVIS_TELEGRAM_BOT_TOKEN="$(gcloud secrets versions access latest --secret=jarvis-telegram-bot-token)"
export JARVIS_TELEGRAM_WEBHOOK_SECRET="$(gcloud secrets versions access latest --secret=jarvis-telegram-webhook-secret)"
~/.jarvis-unlock/bin/python -m jarvis.buildbook.unlock --owner you@gmail.com --reason "lost my passkey during a guest show"
```

- Put your own address in the two places it says `you@gmail.com`. Leave out the two Telegram
  lines if you never set up Telegram (you then get no message, only the audit line).
- It shows what is locked and asks "Type yes to go on". Type `yes`. It then writes the audit line
  first, lifts the lock, ends every build book session (each with its "session has closed"
  message) and prints what it did. Exit code 0 = done, 1 = not done, 2 = refused.
- If it says it can't find credentials, run `gcloud auth application-default login` once and
  run the last line again.
- Afterwards, sign in to the console and set up a new passkey (Approvals -> Permissions).
