Version v6.2.1 · 15 Nov 2026, 20:31 IST · Release R6.2 · Status: Current · Owner: 🛠 Mark XXI (fresh-context security review 1)

# R6.2 Part 1 — fresh-context security review 1

Reviewed: branch `r6-2` @ `d237b8c`, `git diff 9a8392b..d237b8c` (29 files), against
`INTEGRATION-A.md`, Phase A findings 4.3–4.5 and G11 (`origin/r6-2-plan`), and the owner's
non-negotiables 1–8 and Phase B. Read-only; nothing in the worktree was changed.

**Verdict: APPROVE WITH FIXES.** 0 CRITICAL · 1 HIGH · 0 MEDIUM · 4 LOW.
G11 is closed correctly: `BookService.open` has one caller, and that path now refuses every
non-Google mode before anything else. The Cloud Run guard can't be bypassed by casing, an empty
value or an alias, and it can't stop the live service. The hear route, its caps and D1 are sound.
The one HIGH is new in this diff: in a **guest** show, the guest's tap on "Switch the microphone
on" lifts the owner's persistent "Mic off" lock. Fix H1 before merge.

---

## Findings

### HIGH

**H1. A guest can switch the owner's "Mic off" back on from the Book (guest isolation, R5 D11, "Only my tap").**

- Evidence:
  - `src/jarvis/api/static/console-book-talk.js:118-121`: `micState()` shows `#shMicOn` whenever the lock is set, for any audience.
  - `:124-127`: `micOn(e)` calls `A.unlock('button')` for any audience.
  - `:131`: `refused()` moves the focus to `#shMicOn`.
  - The talk panel is never told the audience: `console-book-show.js:204` and `:252` call `T.open({lines, phase})` only.
  - The builder's own test proves it. `tests/browser/test_r62_book_mic.py:283-300` runs `_questions(...)`, whose audience defaults to `"guest"` (`:83`, and `test_book_show._show` seeds `audience` and the script answer with it). The test then asserts that the tap leaves `localStorage['jarvis_mic_off_v1']` as `None`.
  - Before this diff the Book had no unlock path at all.
- Scenario:
  1. The owner has "Mic off" set (Ctrl+Shift+Space, the off button, or the Voice panel) and "Hey Jarvis" switched on.
  2. He opens a guest show and hands the browser over. The guest taps the mic, sees "Switch the microphone on" and taps it.
  3. A real, trusted tap passes both checks, and the lock is removed from this browser's localStorage, which the console shares.
  4. Later the owner Resumes with his passkey. On the next console load, `console-voice-wake.js:151-154` `boot()` sees no lock and starts "Hey Jarvis" by itself.
  - The owner's hard privacy switch was changed by someone else while his back was turned. That is exactly what the guest lock and SEC-4 exist to prevent ("the guest can't use it for anything ... while the owner's back is turned"). It weakens guest isolation, which non-negotiable 1 forbids, and breaks Phase B 4 ("Only my tap turns it back on").
  - The `isTrusted` / user-activation checks are correct, but they can't tell the owner's tap from a guest's on the same device. Only the audience can.
- Fix (client only; the audience comes from the server's own script answer, `normalScript`'s `who`):
  ```js
  // console-book-show.js:204 and :252 — tell the panel whose show it is
  T.open({ lines: S.script.lines, phase: ..., audience: S.script.audience });

  // console-book-talk.js
  // in open(opts):
  S.owner = !!(opts && opts.audience === 'owner');
  // HEAR:
  offGuest: 'The microphone is switched off on this device. Type your question.',
  // micState():
  $('shMicOn').hidden = !(off && S.owner);
  hearLine(!S.canRec ? micWords('unsupported') : off ? (S.owner ? HEAR.off : HEAR.offGuest) : '');
  // micOn(e): a guest's tap never lifts the owner's lock
  if (A && A.locked() && !(S.owner && e && e.isTrusted && A.unlock('button'))) return;
  // refused(): focus #shMicOn for the owner only, else keep it in the box
  if (code === 'mic_off' || (A && A.locked())) { micState(); $(S.owner ? 'shMicOn' : 'shQ').focus(); return; }
  ```
- Tests, written first:
  - Move `test_mic_off_is_shown_and_only_a_real_tap_switches_it_on` to `audience="owner"`.
  - Add `test_mic_off_in_a_guest_show_offers_no_way_back`. With a guest show and `LOCKED`, it asserts: `#shMicOn` is hidden; the line says "switched off on this device"; the mic tap opens nothing (`__gum == []`) and the focus stays on `#shQ`; after a script un-hides `#shMicOn`, a real Playwright `click()` still leaves `JarvisAudio.locked()` true and the key present; and the typed box still sends.
  - Extend `test_r62_book_mic_static.py`: `micOn` refers to `S.owner` before `A.unlock`.

### LOW

**L1. A guest is still told about the owner's spending state.**

- Evidence: `src/jarvis/buildbook/hear.py:99-106`.
  - `budget_reached` says "...free listening minutes are used up and the monthly spending limit is reached...".
  - `budget_unreadable` says "JARVIS can't check this month's spending right now...".
  - Both are given to a guest by `api/book_show.py` `_voice_failure` (`_said(..., owner=False)`).
- Context: this is a clear improvement. Before the diff a guest got `BudgetReached`'s own text, with the owner's limit and spend in rupees and "Raise it in Vitals" (`billing/service.py` `BudgetReached.__init__`). But `INTEGRATION-A` 8.1 says "a guest is never told about costs", and this still tells a guest the owner's billing state.
- Fix:
  - Add `_GUEST: Final = {"budget_reached": "JARVIS can't listen right now. Type your question.", "budget_unreadable": <same>}` to `hear.py`.
  - `words()` returns `_GUEST.get(reason, base)` when `owner` is false.
  - Extend `test_every_reason_has_plain_words_and_a_guest_gets_no_admin_text` so a guest's words never contain "spending", "limit", "charged" or "minutes".

**L2. `book_gate.console_only` keeps the token-mode-dev shortcut, the second G11 gate for the reader.**

- Evidence: `src/jarvis/api/book_gate.py:56-63`. It passes on `s.auth_mode is AuthMode.TOKEN and s.env == "dev"`, and its docstring still advertises "(or token-mode dev)". It gates the reader's ● routes and the code download (`api/book.py:158, 178, 202, 222`).
- Today it is unreachable for content: every one of those routes needs a live OWNER book session or its ticket, and the only maker of sessions is `open_flow` → `_granted` → `BookService.open` (no other caller in `src/`), which now refuses token mode.
- Failure scenario: any future path that makes a session without `open_flow` (an eval helper wired into the app, a sessions store shared with a Google-mode run) would meet a gate that waves token-mode dev through. G11 would then rest on one check instead of two.
- Fix: `if session_email(request, s) is not None: return`, and the docstring becomes "a signed-in browser (R6.2 G11)". The token-mode-dev rows of `tests/test_r6_contract.py` for `/sections`, `/releases/{rid}/sections`, `/ticket` and `/download` then expect `(403, "console_only")`.
- See also the answer to the open question below.

**L3. `JARVIS_ENV` is a free-form string, so the Cloud Run guard's dev check matches `"dev"` only.**

- Evidence: `src/jarvis/config.py:61` (`env: str`) and `:676` (`if self.env == "dev"`).
- Probed: `K_SERVICE=jarvis` with `JARVIS_ENV=Dev` or `" dev"` passes the dev check.
- Not exploitable today, for two reasons:
  - It then trips the token-mode check (the default auth mode), and with Google mode set the value counts as **non-dev everywhere**. All 13 dev shortcuts compare exactly `== "dev"`: `config.py:651, 747`, `api/auth.py:130`, `api/book_gate.py:59`, `api/vault.py:140, 194`, `api/phone.py:216`, `api/deleted.py:215`, `api/faces.py:242`, `integrations/google.py:564, 571` and `series/part.py:105`. So an odd value needs the API token and gets Secure cookies.
  - It fails closed.
- Failure scenario: a later edit that normalises in one place only (`s.env.lower() == "dev"`) would open the gap on Cloud Run.
- Fix (hardening, optional this part): a `field_validator("env")` that strips, lowercases and refuses anything but `dev | staging | prod` at start-up, plus a test for `"Dev"`, `" prod"` and `"production"`.

**L4. Real place names in new test fixtures, in a public repo whose tests ship in the Book's source zip.**

- Evidence: `tests/test_r62_book_hear.py:64, 81, 89, 240-246` (three real place names as the owner's "Words to recognise" and turn hints; the names are left out of this committed copy). `buildbook/gen/snapshot.py` packs `tests/` and `evals/` into `source.zip`.
- Not a secret and not an address, and the repo already carries the same names in 109 lines on `main` (also under `src/`). This diff adds no new kind of exposure.
- Fix (optional): use fictional names in new fixtures (e.g. "Riverton", "Northvale"), in the spirit of rule 2. A repo-wide sweep belongs with Part 2's G8 scrubber work, not here.

---

## Focus 1 — G11: the Book never opens without the passkey

| Path | Result | Evidence |
|---|---|---|
| Owner open, token mode (dev and prod) | 403 `google_needed`, audited `book_open refused` (how `google_needed`, audience `unknown`), no session | `book_show_access.py:194-196` runs first in `_opening`; `tests/test_r62_book_open.py:29-42` |
| Guest open, token mode | the same (the old 409 `guest_needs_google` branch is gone) | `open_flow:214-222` |
| A stale Google cookie on a server restarted in token mode | refused: the auth-mode check runs before `console()` | `_opening` order |
| Google mode | unchanged: console → 5/min → book → passkeys in force → fresh sign-in (300 s) → `check_purpose(uid,"book_open",audience,proof)` → audit → open. `AuthMode` has two members, so "not GOOGLE then refuse; always `_prove_open`" equals the old branch | `:160-187`, `:219` |
| Other session makers | none: `BookService.open` has one caller (`_granted`) | grep of `src/` |
| Resume | unchanged: Google mode + `cookie_owner` + a `book_resume` passkey; never a sign-in fallback | `:267-292` |
| Emergency unlock | unchanged: lifts the lock and closes sessions; never opens one or reads content | `buildbook/unlock.py` |
| Reader, show, code download | need a live owner (●) or show session token; none can exist in token mode | `book_gate.owner_session`, `book_show._session`; see L2 |
| Static exposure of `book.json` / `source.zip` | none: `_book/` isn't under `api/static`, which is served by explicit routes | `api/console.py`, `app_shell.py` |
| Clickjacking of the open or the unlock | blocked: `frame-ancestors 'none'` + `X-Frame-Options: DENY` | `api/console.py:220, 242` |

### The Cloud Run refusal (`config._refuse_dev_on_cloud_run`), probed with `/tmp/venv-b`

| Input (with `K_SERVICE` set unless shown) | Result |
|---|---|
| `JARVIS_ENV=dev` / unset (default `dev`) | refused (dev) |
| `JARVIS_ENV=Dev` or `" dev"` | refused (token mode, the default); see L3 for Google mode |
| `JARVIS_AUTH_MODE=TOKEN`, `Google`, `" google"` | `ValidationError`: start-up fails (the enum is case-exact) |
| `JARVIS_AUTH_MODE` unset (default token), `ENV=prod` | refused (token) |
| `ENV=prod`, `AUTH=google` | passes |
| `K_SERVICE=""` | treated as unset (Cloud Run never sets it empty) |
| `K_SERVICE="  "` | refused (fails closed) |
| `K_SERVICE=jarvis` + `CLOUD_RUN_SERVICE=""` | `K_SERVICE` wins (`AliasChoices` order): refused |
| lower-case `k_service` | read (names are case-insensitive): refused |
| `K_SERVICE` over 120 characters | `ValidationError` (fails closed) |

- Callers: `create_app` (`api/app.py:707-708`, whenever no provider or brains are injected) and `jarvis chat` (`cli.py:38`). The image runs `jarvis serve`, which goes to `uvicorn.run("jarvis.api.app:create_app", factory=True)` with no arguments, so it always runs on Cloud Run. `.env` is in `.dockerignore`, and env vars outrank a `.env` anyway.
- **It can't stop the live service.**
  - `deploy/cloudrun.sh:520` sets `JARVIS_ENV=prod,JARVIS_AUTH_MODE=google` on both the full (`--set-env-vars`) and the quick (`--update-env-vars`) path.
  - CI's `gcloud run deploy --image ... --no-traffic --tag candidate` keeps the service's settings and switches traffic only after `/health` is ok.
  - A revision that refuses to start never takes traffic; the previous one keeps serving.
- The message names settings, never a value (`test_r62_cloud_run_guard.py`).
- Out of scope, noted: the guard is Cloud Run-only. On another host (e.g. `docker-compose.yml` publishes `8000:8000` on all interfaces) dev mode keeps its other shortcuts. The Book itself is shut there too, since G11 is enforced in code, not by the guard.

### The builder's open question (INTEGRATION-A 8.3): should `GET /v1/book` and the Book settings refuse in token-mode dev?

**No, not for G11.** A correction first: those three routes never called `console_only`. `status`, `get_settings` and `put_settings` (`api/book.py:134-150, 276-299`) are gated by `require_auth` + `current_user` only, as in every mode; a bearer-token holder is the owner.
- They carry no book content. Status is metadata: release, sealed list, sizes, lock state, last close, talk on/off, `passkey_ready`, `fresh_left_s`.
- They can't open a session, and the panel needs status to explain why the Book stays shut.
- In token-mode dev with no API token they are as open as every other `/v1` route (`api/auth.py:129-131`). That is the general dev posture, not a Book gap, and it is now off Cloud Run by the guard.
- Do close the one real Book-side remnant: L2.

## Focus 2 — Opening security unchanged

No diff in `book_show_auth.py`, `book_lock.py`, `book_show_wiring.py` (limits: open 5, hear 10 a minute), `buildbook/sessions.py`, `closing.py`, `telling.py`, `lock.py` or `unlock.py`. No diff in the session and idle settings either (`config.py` gains only `cloud_run_service` and the guard).
- Passkey + fresh sign-in: unchanged (`_prove_open`).
- Guest lock and the consumed sign-in: unchanged (`make_show_only`).
- 45-minute cap, 10-minute idle, deletion at close (`_finish` also drops `_heard`): unchanged.
- Audit: the new refusal is content-free (uid, `unknown`, `google_needed`).
- Guest isolation server-side: intact (focus 4). Client-side: see **H1**.

## Focus 3 — "Mic off"

- A script `click()` or a synthetic `MouseEvent`: refused. `e.isTrusted` is false, and `A.unlock` also needs `navigator.userActivation.isActive` (`console-voice-capture.js:121-126`). Tested (`test_r62_book_mic.py:293-297`).
- A synthetic `StorageEvent`: ignored (`console-voice-capture.js:145-148`, `!e.isTrusted` → return).
- A real storage event from another tab: it only follows an unlock made by a real gesture in that tab, which is R5 D11's "other tabs follow". On a storage unlock the console does not restart "Hey Jarvis" until a gesture there (`console-voice-mic.js:555`, SM1). The Book only repaints and never opens the mic.
- The Book page itself: `micOn` is the only `unlock(` caller on `book.html`'s scripts. `mic()` refuses while locked before `R.start()`, and `JarvisAudio.open()` rejects `mic_off` anyway. A lock set elsewhere stops a recording with `stopRec(true)`, so nothing is sent.
- Not met: **whose** real tap. A guest's real tap unlocks (H1).

## Focus 4 — `/v1/book/show/hear`

| Check | Result |
|---|---|
| Body cap | `read_capped` 600 KiB before parsing (`book_show.py:258-260`); over it is 413 `too_large` "Keep a spoken question under 15 seconds." |
| Duration cap | `parse_wav(blob).seconds > 15` → 413 `too_long`; `wav.py` also refuses over its own maximum |
| Content type | `audio/wav` family only (`WAV_TYPES`), checked before the body is read → 422 `bad_audio` |
| Rate limit and budget | `limited("hear", uid)` (10 a minute) before the session is resolved; `allow_hearing` (30 a session) before the body; both unchanged |
| 402 / 503 | `BudgetUnavailable` → 503 `budget_unreadable` (G12, checked before its parent `BudgetError`); `BudgetReached` → 402 `budget_reached`; `VoiceUnavailable.reason` (a 4-value `Literal`) → 503 in the Book's words; unknown → `upstream_error` words |
| `rules.apply`, no AI | `hear.understood` calls `jarvis.understand.rules.apply` only. Its imports are `context`, `near` (difflib) and `words`: no model, network or store. `UnderstandService` is not imported |
| D1 | For a guest, `owner_phrases=False`. `_owner_words` runs only `if owner` (the conditional expression is lazy), and `VoiceService.transcribe` gives `turn = public_hints` without reading settings. The `VoiceRejected` retry uses `hints_for(())`, the base list only. Tested: `settings_reads == []` for a guest (`test_r62_book_hear.py:80-89, 237-246`) |
| Vocabulary | Fixed public names, plus the release's stack (`language`, `vendored`, `3d` roles) and service labels, cleaned by `clean_phrase`, at most 60. It comes from the book a guest session was allowed to open (D3) |
| Nothing stored | The route only returns. The billing meter records usage, as before. `BookWords` caches the public word list only |
| Transcripts never logged | `transcribe` logs seconds, billed time, `chars` and cost only. `hear.py` and `_owner_words` log `type(exc).__name__` only. The rules modules don't log |

## Focus 5 — Error text

- Guests never see Cloud Shell, setting names, keys, hostnames or project ids on the hear or speak paths:
  - The `_OWNER_TAIL` "Vitals" pointers are owner-only.
  - Narration failures say "Use the browser's voice."
  - `BadAudio`'s messages are fixed sentences (`voice/wav.py`).
  - Covered by `test_every_reason_has_plain_words_and_a_guest_gets_no_admin_text`.
- `GOOGLE_NEEDED` names `JARVIS_AUTH_MODE=google`, but only on `POST /v1/book/open` (`OWNER_ONLY`), which a show-only guest browser can't call.
- The new `WORDS.blocked` text gives browser and OS steps only.
- Remaining: spending wording for a guest (L1).

## Focus 6 — Front end

- `console-book-talk.js`, `console-book-voice.js`, `console-voice-capture.js` and `console-voice-mic.js` add no `innerHTML`, `insertAdjacentHTML`, `outerHTML`, `eval` or `new Function`.
- Every new string reaches the DOM through `textContent` (`hearLine`, `mk`, `sys`). Server text goes through `txt()`, which strips control and bidi characters and caps the length (300 for `detail`, 500 for `text`/`heard`).
- `book.html` adds two elements with existing classes: no inline style and no `on*` handler.
- `book.css` adds one property.
- CSP stays `script-src 'self' 'wasm-unsafe-eval'` with `frame-ancestors 'none'`, unchanged. The browser tests assert no CSP violation (`_clean`).

## Focus 7 — Data

- A pattern scan of every added line found no secrets, keys, tokens, e-mails, phone numbers, IP addresses, Cloud Run hostnames, service accounts or project ids.
- Test identities come from `book_app_fakes`.
- Place names: L4.

## Tests run (targeted, `flock /tmp/heavy.lock`, `/tmp/venv-b`, `PYTHONPATH=$PWD/src`)

- `tests/test_r62_cloud_run_guard.py`, `test_r62_book_open.py`, `test_r62_book_hear.py`, `test_r62_book_mic_static.py` and `test_book_guest_voice.py`: **66 passed** (9 s).
- A throwaway probe of `Settings` + `_refuse_dev_on_cloud_run` under 14 environment variants (the table above). Not added to the repo.
- Browser tests were not re-run. H1 is shown by reading the existing `test_r62_book_mic.py:283-300`, which runs a guest show.

## Verdict

**APPROVE WITH FIXES.** Fix **H1** (guest audience: no "Switch the microphone on", no unlock), test first, before merge. L1 and L2 are small and worth doing in this PR. L3 and L4 are optional hardening.
