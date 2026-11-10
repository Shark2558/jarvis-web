# R6 builder C: access, sessions, guest isolation, talk-through, wipe: integration notes for I1

Branch `r6-c` (from `r6-i0`). Plan: `docs/plans/r6-build-book.md` D1, D8-D14, D17's guest prompt.
I didn't edit any wiring file. Everything below is for I1 to wire.

## What C ships

| File | What |
|---|---|
| `buildbook/sessions.py` | `DocBookSessions` (ports.BookSessions) + `sweep_owned`, `SessionEnded(SessionGone)` |
| `buildbook/lock.py` | `DocShowLock` (ports.ShowLock) + `refresh(uid)` (an uncached read) |
| `buildbook/guard.py`, `guard_words.py` | `pre_guard`, `post_guard`, `cap`, `normalise`, `book_hosts` (D12) |
| `buildbook/prompt.py` | `GUEST_SYSTEM`, `GUEST_PROMPT_VERSION = "bg1"`, fences, canary (D11, D17) |
| `buildbook/digest.py` | deterministic chunk choice within 10,000 characters (D11) |
| `buildbook/talk.py` | `BookTalk(brains, billing, mode, book, sessions, *, prefs, owner_emails)` (ports.BookTalker) |
| `buildbook/service.py`, `show_script.py` | `BookService` (open/close/wipe/notice/sweep/resume/script), `BookSweepJob` |
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
   `book_service.resolve(uid, token, now=)`. Going through the service means an expired or idle
   session is closed with its notice. Refuse when `view.audience != "owner"` (403). The `access`
   eval checks a guest token gets no 200 on these. It passes today against B's 503 stubs, so
   **re-run it after the merge**.
6. **Privacy (D16)**: `book_sessions_source` delete calls `book_service.wipe(uid, now=)`.
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
- **hear** returns 503 reason `budget` after 30 recordings in a session.
- **ask**: 422 `too_long` over 500 characters; 429 over 6 a minute.
- **close**: `{reason: "closing" | "end"}`.
- Every expired, idle, closed or unknown token gets 401 `session_gone`.
- **Resume**:
  1. `POST /v1/book/resume {}` returns 403 `passkey_required` with `lock_id`. The 423 body also
     carries `lock_id`, but only for the owner whose lock it is.
  2. Prove with `JarvisPasskey.prove('book_resume', lock_id)`.
  3. `POST /v1/book/resume {proof}` returns `{resumed: true}`.
  4. When no passkey is in force any more, the answer is 403 `reauth_required` with `lock_id`:
     hop to `/auth/login?reauth=1`.

## Passkey-reset routes under the lock (plan "Risks"): what I found

- **`POST /v1/passkeys/reset` is on the allow-list.** It is the only way back when the passkey is
  lost mid-show (24 h, inbox notice, cancellable with any passkey). It still needs a Google
  sign-in from the last 5 minutes *in that browser*, which the guest can't make (password +
  2-Step).
  - A guest open **consumes** the presenting browser's fresh sign-in.
  - The `lock` eval shows the guest's browsers are refused (403 `reauth`) and the owner, signing
    in again, can start it.
- **Not allowed: `reset/cancel`.** With no reset pending it returns the full PermissionsView
  (choices, passkey labels) with no proof.
- **Not allowed: `register/options` and `register`.** Their options carry the owner's e-mail.
- Since registering a new passkey isn't reachable under the lock, **resume falls back to a fresh
  Google sign-in, but only when NO passkey is in force** (that is, after the 24 h reset has
  completed). This is the same proof the reset itself needed.

## Decided differently from the plan, and why

1. **Resume's sign-in fallback** (above). Without it, a lost passkey locks every console for good.
2. **`POST /v1/passkeys/reset` added to D10's allow-list** (above).
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
9. **`ClosedSession.notified=True`** on a sweep-retried delete means "already told", so there is
   no second notice.

## Open / low

- `VoiceService.transcribe` always uses the owner's phrase hints. That leaks nothing to a guest,
  though it may bias a guest's transcript toward the owner's words. I1 could add a
  `phrases=False` option for guest sessions.
- A lock document that isn't a lock reads as unreadable (503) until it is fixed by hand.
- The lock store reads one owner at a time (N owners means N cached reads per 3 s per instance).

## Tests and evals (3.11 and 3.12)

- **Tests:** `test_book_{sessions,lock,guard,talk,show_api,wipe,boundaries}.py`,
  `test_evals_r6_book.py`.
- **Fakes:** `book_show_fakes.py`, `book_app_fakes.py`.
- **Evals (C's parts):** `access` 14, `guest` 54, `wipe` 12, `lock` 47.
