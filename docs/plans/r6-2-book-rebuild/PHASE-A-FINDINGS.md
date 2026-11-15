Version v6.2.1 · 15 Nov 2026, 16:46 IST · Release R6.2 · Status: Draft — for the owner's approval · Owner: 🛠 Mark XXI

# The Build Book rebuild (R6.2–R6.4) — Phase A findings and plan

Investigation only: no application code, test or setting was changed. Everything below comes from the
repository at `main` `9a8392b` (`v14.0.2`) and from scratch runs outside the repository. Nothing was checked
on the live JARVIS, so every hosting, security and diagram statement is **"From repo configuration"**.
Where a claim could not be established it says **"Unverified — what would confirm it"**. Rupee figures
use `config.usd_inr_rate` = ₹95.24 a dollar and are estimates unless they say "measured".

---

## 0. For the owner, in plain words

**The microphone.** The "Ask by voice" button hides the reason when something goes wrong. Six different
problems (microphone blocked, no microphone, microphone busy, a part failing to load, "Mic off" left on
from the console, an old browser) all show the same sentence: *"The microphone is not available. Type the
question instead."* Three other problems show nothing at all (nothing heard, a very short tap, audio that
never started). I reproduced every one of these in a test browser. The voice path itself works: with a
working microphone the words land in the box.

The most likely cause on your laptop is that "Mic off" (from the R5 voice release) is still switched on in
that browser, or that Chrome or Windows is blocking the microphone for JARVIS. The Book has no way to
switch "Mic off" back on. One check tells us which (step 1 below).

**What the AI-written book costs** (Claude Sonnet 5.5, the "balanced" tier):

| What | Estimate |
|---|---|
| First full write (about 135 pages) | about ₹700–1,400, once (most likely about ₹1,030) |
| Each normal release (the pages whose code changed) | about ₹180–650 (most likely about ₹360) |
| A hotfix | about ₹5–30 |
| The free Gemini brain instead | ₹0, slower, quality to be checked first |
| A 10–15 minute narrated tour | free for about 86–129 tours a month; after that about ₹20–30 a tour; the browser voice is always free |

The Workshop's earlier caps (₹800 first write, ₹200 a release) are too low for these numbers. I propose
₹1,500 for the first write, ₹500 a release and ₹1,000 a month. At a cap the previous text stays.

**Storage.** One release's book and code take 7.98 MB today (measured), against 4.81 MB at R6. Three
releases fit easily now (24 MB of the 60 MB cap). The pictures for every module would add about 12–22 MB
once and 2–5 MB a release. Your suggested 8 MB of new pictures a release fits only if the stored code
copies are also de-duplicated. That costs nothing extra.

**Your steps (only step 1 is needed now):**
1. On the laptop, open JARVIS in Chrome (the normal console, not the Book). Look at the microphone
   button next to the message box **before** you tap it.
   - If it says **"Microphone off: tap to switch it on"**, that was the cause. Tap it once. Then open the
     Book again and try "Ask by voice".
   - If not, tap it and read the sentence JARVIS shows (for example "The microphone is blocked…" or
     "Another app is using the microphone…"). Tell me that sentence.
2. Read the decisions in section 13 and answer YES or NO to each (safe defaults apply until you do).
3. Approve this report (approval stop 1 of 5).

---

## 1. What was done and how

| Step | How | Result |
|---|---|---|
| Read the code | `src/jarvis/buildbook/**`, `api/book*.py`, `api/r6_wiring.py`, `api/console.py`, `api/app_shell.py`, the voice code, `llm/`, `billing/`, `understand/`, `tools/`, `activity/`, CI, Docker, deploy, home kit, Android, docs | Sections 2–12 |
| Ran the generator exactly as the deploy job does | `PYTHONPATH=src python -m jarvis.buildbook.gen --out <dir> --best-effort` (`.github/workflows/ci.yml`, job `deploy`, step "Write the build book") on Python 3.12, and the PR gate `--check` on 3.11 | Byte-identical; sizes in section 3 |
| Ran it at every release since R6 | a local clone in `/tmp`, each release's own generator (merges `37c3bfd` … `9a8392b`) | Growth table, section 3 |
| Reproduced the microphone | 20 cases in headless Chromium 153 (Playwright 1.63) against the real app (mock brain, token sign-in, as `tests/browser/conftest.py`), the book routes stubbed by `tests/browser/book_mocks.FakeBook`, the real capture worklet and Chromium's fake microphone | Section 4 |
| Ran targeted tests | `tests/test_book_show_api.py::test_speaking_and_hearing`, `tests/test_book_guest_voice.py` | 3 passed |
| Measured | page counts (catalogue, screens, services), changed cards per release (`git diff` between releases), show narration, screenshot sizes as WebP, lines of code | Sections 7–9 |

Scratch files live in `/tmp/phaseA/` only (`repro_mic*.py`, `repro_layout.py`, `shots.py`); none is in the
repository.

---

## 2. How the current book is made (From repo configuration)

### 2.1 The generator: no AI, fixed templates

```
PR:      CI job "test" ── python -m jarvis.buildbook.gen --check ── builds twice, refuses if bytes differ
deploy:  CI job "deploy" (main, AUTODEPLOY=on)
           1 pip install --require-hashes -r requirements.lock         (continue-on-error)
           2 PYTHONPATH=src python -m jarvis.buildbook.gen --out src/jarvis/buildbook/_book --best-effort
             (BEFORE the Google sign-in step: no credentials exist while it runs)
           3 docker build  → _book/{book.json, source.zip, release.json} ride in as package data
           4 roll out with no traffic → /health → switch traffic
running app (Cloud Run):
           book_seal tick job (5-minute watchdog + morning tick, 45 s budget) or GET /v1/book (≤ 20 s wait)
             → seal book.json + source.zip into Firestore (3 kept, 60 MB) → one "book_sealed" notice
```
*Diagram: From repo configuration (`.github/workflows/ci.yml` jobs `test`, `deploy`; `Dockerfile`; `src/jarvis/buildbook/sealer.py`).*
Local deploys run the same through `make book` (`Makefile`, called by `deploy/cloudrun.sh:536–538`).

| Part | Where | What it does |
|---|---|---|
| Entry | `buildbook/gen/__main__.py` | `--repo`, `--out`, `--check`, `--best-effort`, `--licences`; clears an earlier build first; stdlib only, so a failed install still writes an error `release.json` (`gen/fallback.py`) |
| Runner | `gen/runner.py` `run()` | refuses a dirty checkout (`DIRTY`); one-line failure words, never file content |
| The repo view | `gen/repo.py` `Repo.from_git` | 4 git questions only (`ls-files`, `rev-parse`, `log -1`, `status`): works on a shallow clone, never walks history |
| Assembly | `gen/write.py` `assemble()`, `build()`, `check()` | the 8 sections (`sections.SECTION_IDS`: architecture, stack, libraries, integrations, workflows, limitations, costs, decisions), the show (scenes 1–11) and the talk digest; `canonical_bytes` gives the same bytes for the same commit |
| Sections | `gen/code.py` (packages, layer, files, raw lines, docstring first line; integrations), `gen/libs.py` + `gen/licences.py` (libraries and stack from `requirements.lock` + `requirements.licences.json`), `gen/flows.py` (10 fixed workflows), `gen/plans.py` (decisions, fit rows, limitations from `docs/plans`), `gen/costs.py` (prices, free allowances, `FREE_TIER`), `gen/layers.py` (`LAYER_OF`) | |
| Show | `gen/show.py` `build_show()` | scenes 1–11 from fixed templates; every number a scene draws is a `Fact`; scenes 12–13 are `buildbook/lines.py` |
| Digest | `gen/chunks.py` `build_digest()` | overview ≤ 2,000 characters + chunks ≤ 1,500 (`DIGEST_CHUNK_CHARS`) for the talk lane |
| Privacy | `gen/scrub.py` `Scrubber.clean` / `verify` + `gen/redact.json` (SHA-256 of names only) | removes URLs off the allow list, private hosts, e-mails, Indian phone numbers, 10+ digit runs, secret shapes, hashed names; `verify` walks the finished book |
| Code snapshot | `gen/snapshot.py` | git-tracked files only; vendored, binary and > 1 MB files left out but listed in `THIRD_PARTY.json`; every kept file scanned for secret shapes (known fakes in `gen/fake_secrets.txt`); cap 15 MiB (`model.SNAPSHOT_CAP_BYTES`) |
| Caps | `buildbook/model.py` | `book.json` 2 MiB, snapshot 15 MiB, `KEEP = 3`, `MAX_LIMITATIONS = 80` |

### 2.2 Sealing and the Firestore collections (prefix `jarvis_`)

`sealer.py` `BookSealer.ensure`: current release not sealed → 120 s lease → owner e-mail check
(`seal_words.owner_hit`, D3) → make room under `book_max_total_mb` (oldest first, newest always stays) →
`seal.py` `DocsBookVault.seal` → prune to 3 → audit `book_seal` (ids and MB only) → one `book_sealed`
notice. Never at start-up (a failed candidate never seals). Envelope: R2 vault crypto, AES-256-GCM,
a random key per file wrapped by the keyring, 512 KiB chunks (`seal_index.BookCrypto`,
`vault/crypto.CHUNK_BYTES`), base64 text in Firestore (`integrations/vault.TokenCipher`).

| Collection | Shape (from the docstrings) | Kept |
|---|---|---|
| `book/{uid}` | `{rev, kid, blob}`; `blob` = sealed `BookIndex {v, releases[SealedRelease], pending[Part], orphans[Part]}` (keyring purpose `book_index`) | until pruned |
| `book/{uid}/book_chunks/{fid}_{nn}` | `{blob, n, of, at}` | with the release |
| `book_lease/{uid}` | `{holder, until, told, failed, held}` (ids only) | |
| `book_lock/{uid}` | `{id, bk, since}` + `sessions_valid_after` | until Resume |
| `book_sessions/{bk}` | `{v, uid, audience, mac, created_at, last_seen, until, idle_until, questions, state, reason, blob}`; token stored only as `Keyring.mac`; `blob` = last 8 turns sealed (`book_session`) | 45 min, 10 idle |
| `book_settings/{uid}` | `creator_name, show_voice, talk_on, allow_training_brain, updated_at` | |
| `book_tickets/{uid}` | `{grants, tickets[{mac, item, fid, session, until}]}` | single use |
| `book_notices/{id}`, `book_closed/{uid}` | content-free notices; `{last_closed_at, notified}` | |

The 60 MB cap counts **plain bytes** (`SealedRelease.size`); Firestore holds about 1.34× that (base64
plus a nonce and tag per chunk).

### 2.3 The show

13 scenes (`model.SHOW_SCENES`): the build book, eight layers, one conversation turn, memory and privacy,
confirm before commit, voice, home, on its own, stack and licences, costs, not built yet, questions,
closing. Served at `/book/show` by `api/console.py` `book_show()` with the console's own headers
(`_page`). Scripts in `book.html`: `console-fx.js`, `console-permissions.js`, `console-book-show.js`
(timeline, controls, captions), `console-voice-capture.js`, `console-book-voice.js` (narration and the
recording), `console-book-2d.js`, `console-book-talk.js` (questions, closing, Resume) and the ES module
`console-book-3d.js` (three.js `three-0.187.0`, MIT) with `console-book-scenes*.js`. Narration: the cloud
voice through `POST /v1/book/show/speak`, else the browser's `speechSynthesis` (`en-GB`), else captions
(330 ms a word + 800 ms). Motion Full ≤ 30 fps; Calm, Off and `prefers-reduced-motion` run no loop
(`console-book-3d.js` header). Measured today: scenes 1–11 hold **56 beats, 6,231 characters, 1,084 words**.

### 2.4 Questions (the talk lane)

`buildbook/talk.py` `BookTalk`: Book settings on, AI on, a brain that doesn't learn from what it's told
(the deployment's default brain, else the first private one, else the default only if the owner allowed
it: `_brain()`) → reserve one of the session's questions → `guard.pre_guard` (fixed refusals, no model
call; English, Hindi, Malayalam) → `billing.ensure_allowed` → ONE `router.complete(tier=BALANCED,
system=GUEST_SYSTEM, system_dynamic=<fenced digest + canary>, last 8 turns, max_tokens=400, tools=None)`
→ `billing.record` → `guard.post_guard` (e-mail, phone, owner, secret, canary, off-list URL) → `guard.cap`
(1,200 characters). Limits: 20 questions a session (`book_talk_questions`), 500 characters, 6 a minute
(`api/book_show_wiring.LIMITS`). No-AI mode or the monthly limit: the fixed `ai_off` line, no call.

### 2.5 Opening, sessions and the guest lock

`api/book_show_access.py` `open_flow`: a signed-in browser → 5 a minute → a book exists → Google mode:
passkeys in force → a Google sign-in from the last 5 minutes (`api/auth.FRESH_SIGN_IN_S = 300`) → a
`book_open` passkey proof bound to the audience. A guest open sets the lock (`buildbook/lock.py`,
`api/book_lock.ShowLockMiddleware`, 3 s cache) and consumes the fresh sign-in; only a `book_resume`
passkey lifts it (or the emergency CLI `python -m jarvis.buildbook.unlock`). Sessions: 45 minutes
absolute, 10 idle (`config.py` `book_session_minutes`, `book_idle_minutes`), deleted at close
(`closing.py`, `telling.py`).

---

## 3. Measured size per release

Each release built with its own generator (`--best-effort --out`), plain bytes:

| Release (merge) | Version | book.json | source.zip | Total | Files left out |
|---|---|---|---|---|---|
| R6 (`37c3bfd`) | 0.0.1 in the code | 147,385 | 4,661,955 | 4.81 MB | 31 |
| R6.1 (`90e483f`) | v6.1.0 | 148,781 | 4,919,221 | 5.07 MB | 45 |
| R11 (`665fce0`) | v11.0.0 | 157,297 | 5,679,207 | 5.84 MB | 45 |
| R11.1 (`814540c`) | v11.1.0 | 162,032 | 6,485,085 | 6.65 MB | 45 |
| R11.1.1 (`5519e2d`) | v11.1.1 | 162,032 | 6,489,463 | 6.65 MB | 45 |
| R7 (`5db4f05`) | v7.0.0 | 172,919 | 7,282,216 | 7.46 MB | 73 |
| R14 (`529c06f`) | v14.0.0 | 182,037 | 7,792,477 | 7.97 MB | 73 |
| R14.0.2 (`9a8392b`, today) | v14.0.2 | **182,037** | **7,800,117** | **7.98 MB** | 73 |

- R6's figures (147 KB + 4.65 MB) are confirmed. Today is +23 % book and +67 % code.
- Growth: about **+0.63 MB per feature release** (5 feature releases, +3.17 MB); hotfixes add < 0.01 MB.
- The code zip holds 2,277 files, 22.4 MB raw: tests 2.1 MB zipped, `src/jarvis/api` 0.85 MB,
  `docs/plans` 0.79 MB, evals 0.51 MB.

**Projection (Estimate), today's format, 3 kept releases:**

| | Now | +3 feature releases | Cap / limit |
|---|---|---|---|
| One release | 7.98 MB | ≈ 9.9 MB | snapshot cap 15 MiB (code zip alone) |
| 3 kept (the cap counts plain bytes) | 23.9 MB | ≈ 29.7 MB | 60 MiB (`book_max_total_mb`), 80 % warning at 48 MB |
| At seal time (3 kept + 1 incoming) | 31.9 MB | ≈ 39.6 MB | the sealer prunes the oldest first if needed (`_room`) |
| In Firestore (×1.34) | ≈ 32 MB | ≈ 40 MB | free tier 1 GiB stored (`gen/costs.FREE_TIER`); ₹0 |

Two risks today: the 15 MiB code-zip cap is reached in about 12 feature releases at this rate (then
`GenError`, no book, deploy unaffected); and hotfixes count as releases, so the 3 kept can be three
near-identical copies (R14, R14.0.1, R14.0.2) while R7 is already gone.

---

## 4. The microphone ("Ask by voice")

### 4.1 The path, end to end (From repo configuration)

```
#shMic click ─► console-book-talk.js mic()
                 ├─ R = JarvisBookVoice.record (console-book-voice.js `rec`)
                 ├─ R.start() → JarvisAudio.open()            (console-voice-capture.js)
                 │     locked? ──► reject 'mic_off'            (localStorage jarvis_mic_off_v1)
                 │     supported()? getUserMedia + AudioWorklet
                 │     prime(): AudioContext inside the tap
                 │     getUserMedia({audio: echo/noise/gain, mono}) → reason(): blocked | no_mic | busy | failed
                 │     audioWorklet.addModule('/static/voice-capture-worklet.js') → 'failed'
                 │     worklet: low-pass + resample to 16 kHz, Int16 frames of 1,280 (80 ms)
                 │  catch (_) ──► ONE sentence: "The microphone is not available. Type the question instead."
                 ├─ frames collected ≤ 15 s (MAX_REC_S), second tap or 15 s → stop
                 ├─ JarvisWav.encode → WAV 16 kHz PCM16 (no frames → null → returns silently)
                 └─ POST /v1/book/show/hear (X-Jarvis-Book, audio/wav)
server: api/book_show.py show_hear()
   book on? → 10 a minute per owner (LIMITS["hear"]) → session (401) → voice service → audio/wav (422)
   → allow_hearing: 30 a session (service.HEARS_PER_SESSION) else 503 reason "budget" "Type your question."
   → read ≤ 600 KB (413) → parse_wav ≤ 15.0 s (413), ≥ 0.3 s (422 bad_audio)
   → voice.transcribe(owner_phrases = audience == "owner")            (voice/service.py)
        _require("stt") → 503 voice_unavailable (not_configured | api_disabled | upstream_error | timeout)
        billing.ensure_units_allowed: free 3,240 s a Pacific month (90 % of Google's 60 min), deployment-wide;
          beyond it the call is PRICED (≈ ₹2.29 a minute) and only the monthly limit stops it → 402
        GoogleSTT.recognize: languageCode en-IN (config voice_language), model latest_short (≤ 15 s),
          speechContexts = base hints + the owner's "Words to recognise" (owner only), 3 alternatives
   → {"text": "..."}   (an empty transcript is a 200 with "")
browser: the text goes into #shQ for editing; never auto-sent
```
*Diagram: From repo configuration.*

- **Speech-to-text runs in the cloud only** (Google Cloud Speech-to-Text v1, server side). Chrome's own
  free recogniser, which the console can fall back to (`console-voice.js` `inputEngine()` "Automatic"),
  is never used by the Book.
- **Headers on `/book/show`:** `Content-Security-Policy: CONSOLE_CSP` (`default-src 'none'; script-src
  'self' 'wasm-unsafe-eval'; connect-src 'self'; worker-src 'self'; …`), `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Cache-Control: no-store` (`api/console.py` `_page`). Identical to the
  console (`/` uses the same `_page`; `api/app_shell.py` `_PAGE_HEADERS` too). **No
  `Permissions-Policy` header anywhere** (searched `src/`), so the microphone is allowed for the page's
  own origin by default. The worklet loads under `script-src 'self'`; no CSP violation in any run.
- **`owner_phrases`** apply only to an owner session (D1). No per-turn hints (`turn_hints`) are passed and
  the R11.1 correction is not applied.
- **No status line.** While recording, only the button's colour changes (`book.css:74`
  `.sh-mic[aria-pressed="true"]`); there is no "Listening / Processing / Done".
- **R6's browser tests never ran the real capture path:** `tests/browser/test_book_show_hold.py`
  `GUM_STUB` replaces `navigator.mediaDevices` with an oscillator.

### 4.2 Reproduction (headless Chromium 153, `/tmp/phaseA/repro_mic*.py`)

| # | Case | How it was made | What the owner sees | Request sent |
|---|---|---|---|---|
| 1 | Permission granted | `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream` | words land in the box (≈ 1.6–1.9 s WAV) | yes |
| 2 | Permission denied (no prompt) | fake device only (headless says `NotSupportedError`) | "The microphone is not available. Type the question instead." | no |
| 2e | Blocked in Chrome | `getUserMedia` throws `NotAllowedError` | same sentence | no |
| 3 | "Mic off" set | `localStorage.jarvis_mic_off_v1 = '1'` | same sentence; nothing in the Book can switch it on | no |
| 4 | No microphone | auto-allow, no fake device → `NotFoundError` | same sentence | no |
| 4b | Busy in another app | `NotReadableError` | same sentence | no |
| 5b | Worklet fails to load | `addModule` rejects | same sentence | no |
| 6 | Unsupported browser | no `AudioWorkletNode` | **the button is not there** | — |
| 5c | Audio never starts | capture context suspended | **nothing**; button resets | no |
| 9c | Tap–tap at once | stop after 50 ms | **nothing**; button resets | no |
| 7 | Server: voice not set up | 503 `not_configured` | "Cloud voice is not set up on this server; the browser's voice is used." (misleading: nothing listens instead) | yes |
| 7b | Server: speech API off | 503 `api_disabled` | a Cloud Shell `gcloud services enable …` command (shown to guests too) | yes |
| 7c | Session's 30 spoken questions used | 503 `budget` | "Type your question." | yes |
| 8 | Monthly limit | 402 `budget_reached` | "This month's limit of ₹… is used up … Raise it in Vitals." | yes |
| 8b | Google busy | 429 `voice_busy` | "Google's speech service is busy right now…" | yes |
| 9 | Nothing heard | 200 `{"text": ""}` | **nothing**; the box stays empty | yes |
| 9b | Too short | 422 `bad_audio` | "That recording is too short to hear anything." | yes |
| — | Layout | 1280×720@1.5, 1366×768, 1536×864@1.25, 1280×800, 1920×1080 | the button is visible and on top in every one | — |

In every case the typed box stayed usable and no page error happened. A dropped connection already gets
the calm "Can't reach JARVIS. Check your connection." (existing test).

### 4.3 Root cause

1. **The defect (verified by reproduction):** `console-book-talk.js` `mic()` ends in
   `catch (_) { … sys('The microphone is not available. Type the question instead.') }`. It throws away
   the `.code` that `console-voice-capture.js` already provides (`blocked`, `no_mic`, `busy`, `failed`,
   `mic_off`, `unsupported`), and `sendRec()` says nothing for an empty transcript or a recording with
   no frames. Whatever went wrong on the laptop, the owner could not have been told what it was.
2. **The most likely trigger on a laptop Chrome where the console's own mic works (hypothesis):** the
   R5 "Mic off" lock (`jarvis_mic_off_v1`, set by "Jarvis, mic off", Ctrl+Shift+Space, the off button or
   the Voice panel; R5 D11 asked for exactly this, `docs/plans/r5-voice.md` item 5). It persists in that
   browser until a tap on the **console's** mic button (`console-voice-mic.js:429` `A.unlock('button')`).
   `book.html` loads neither `console-voice-micoff.js` nor any unlock path, so the Book fails the same way
   every time. Next most likely: Chrome's site permission set to Block, or Windows' "Let desktop apps
   access your microphone" switched off; both reach the page as `NotAllowedError`.
3. **Unverified — what confirms it:** the one live check in section 0, step 1. The console's composer
   mic uses the same capture code and names the reason (`console-voice-mic.js` `HELP`, `LOCKED_LINE`;
   the button title "Microphone off: tap to switch it on").

### 4.4 Can the console's "Heard / Understood as" (R11.1) be reused? Yes, its free part

`src/jarvis/understand/rules.py` `apply(heard, hints)` is plain code (known Indian-English mishearings
such as "D" → "the", "javis" → "JARVIS", near-matches against hints; protected words never changed).
`UnderstandService.understand` adds a fast-tier model call only when unsure and only with the AI on
(`understand/service.py`), and it reads the owner's files and conversation nouns (`hints.py`), which a
guest must never get. Plan for the Book: on the server, after `voice.transcribe`, run `rules.apply` with
the base hints plus the book's own vocabulary (component names from the digest), and the owner's "Words
to recognise" for an owner session only. Pass the same vocabulary to Google as speech hints. No model call
in the Book (₹0, guest-safe). The answer carries `heard` beside `text`, so the box can show "Heard /
Understood as" when something changed.

### 4.5 Part 1 fix design (`v6.2.0`, in the shared R5 code, not forked)

1. **Shared words.** Move the `HELP` table out of `console-voice-mic.js` into `console-voice-capture.js`
   (e.g. `JarvisAudio.words(code)`), with the same strings so the R5 tests stay green, and add Chrome and
   Android steps for "blocked". The console and the Book read the same table.
2. **Book behaviour** (`console-book-talk.js`, `console-book-voice.js`):
   - One tap starts, a second tap stops (as now); 15 s at most.
   - A status line under the box (`aria-live`): Listening… → Processing… → Done, edit and press Ask.
   - The text lands in the box; never auto-sent (as now).
   - Each failure gets its own sentence (table below); the typed box always stays usable.
   - "Mic off": the line says so and offers "Switch the microphone on"; that button calls
     `JarvisAudio.unlock('button')` inside the tap (real user activation), as in R5. Nothing else
     unlocks it.
   - Unsupported: the button stays visible but disabled, with the reason, instead of disappearing.
   - No frames after 1.5 s: "The microphone isn't sending any sound…" (detected from the first frame).
3. **Server** (`api/book_show.py` `show_hear`): `{text, heard, changed, no_speech}`; R11.1 rules as in
   4.4; plain sentences by reason for guests (no Cloud Shell command; the owner gets that in Vitals);
   `BudgetUnavailable` answered as 503, not as 402 `budget_reached`.
4. **Free listening minutes.** Today, past the free 54 minutes, listening is simply charged until the
   monthly limit. Decision 4 (section 13) asks whether the Book should stop at the free allowance and say
   "This month's free listening minutes are used up; type your question."

| Case | Sentence (draft) |
|---|---|
| Blocked | "The microphone is blocked for JARVIS. In Chrome: the icon left of the address → Site settings → Microphone → Allow, then reload. On Android: Chrome ⋮ → Settings → Site settings → Microphone → JARVIS → Allow." |
| No microphone / busy | "No microphone was found…" / "Another app is using the microphone. Close it, then tap the mic again." |
| Unsupported | "This browser can't record here. You can still type." |
| Network / speech service | "Can't reach JARVIS…" / "The speech service isn't answering right now. Type your question." |
| Nothing heard | "I didn't hear any words. Try again closer to the microphone, or type." |
| Free minutes / session's spoken questions / monthly limit | one plain line each |
| Mic off | "The microphone is switched off. [Switch it on]" |

**Tests (written first):** Playwright with the real Chromium fake microphone for "granted", and injected
`getUserMedia` / `addModule` failures and stubbed server answers for every other case above (the 20
cases of 4.2 become tests); unit tests for the hear route (empty text, each reason, the session budget,
R11.1 rules, a guest never gets the owner's words); the R5 voice browser tests (`tests/browser/test_voice*.py`)
stay green; one live check in the go-live guide.
**Effort:** about 1 builder day, plus a fresh-context review and one full browser run (≈ 75 minutes).

---

## 5. Claude: built with it, called by it, or both? Both

| | Evidence |
|---|---|
| Built with Claude | 1,029 of the 1,096 commits in the fetched history (31 Oct–15 Nov 2026) carry a `Co-Authored-By: Claude …` trailer: Opus 5.5 (904 lines), Fable 5.2 (58), Fable 5.1 (32), Sonnet 5.5 (32), Opus 4.8 (3); 1,029 carry `Claude-Session:` (`git log --format=%(trailers)`) |
| Called by the running app | `pyproject.toml` depends on `anthropic>=2.0,<3`; `requirements.lock` pins `anthropic==2.3.0`; `src/jarvis/llm/anthropic_provider.py` is the only file importing the SDK; `config.py` default `llm_backend = ANTHROPIC`, tiers `claude-haiku-5-5` / `claude-sonnet-5-5` / `claude-opus-5-5`; `deploy/cloudrun.sh:149` mounts `JARVIS_ANTHROPIC_API_KEY` from Secret Manager |
| Model-agnostic | callers ask for a tier (`llm/router.ModelTier` FAST/BALANCED/STRONG); providers: Anthropic, Gemini, OpenAI-compatible, local, mock (`llm/`) |

---

## 6. Gaps and wrong facts (with evidence)

**In the prompt's section 1:**

| # | Claim | Finding |
|---|---|---|
| P1 | `static/book.html` | It is `src/jarvis/api/static/book.html` (all console files live there) |
| P2 | The file list | Also `console-book.js` (the Book panel), `console-book.css`, `book.css`; the Book's mic uses `console-voice-capture.js` and `voice-capture-worklet.js`; API files are `book.py`, `book_gate.py`, `book_http.py`, `book_lock.py`, `book_show.py`, `book_show_access.py`, `book_show_auth.py`, `book_show_wiring.py`, `book_status.py` |
| P3 | Shipped in R6 (v6.0.0) | The code at R6's merge said `0.0.1` (`src/jarvis/__init__.py` at `37c3bfd`); "v6.0.0" was given later by R6.1's versioning (decision 3). R6's own book has no version |
| P4 | C57 in `claude/architecture.md` | `claude/` is not in the repository; the repo's catalogue is `docs/architecture/JARVIS-Architecture.md`, C01–C68, continuous. Unverified that the project doc matches |
| P5 | About 9 minutes before questions | Unverified. Measured narration: 6,231 characters; at the code's caption pace 6.7 minutes; at 150 words a minute 7.2 minutes, plus scene transitions. A stopwatch on the live show confirms |
| P6 | "Written at every release" | At every deploy (hotfixes too) and checked on every PR (`--check`) |
| P7 | Last 3 releases, 60 MB | True; the cap counts plain bytes and is a setting (20–200 MB); hotfixes use up the 3 places |
| P8 | Answered by the brain router | True, on the BALANCED tier, with the deployment's default brain, not the owner's brain pill (`talk.py` `_brain`) |

**In the current book and its card:**

| # | Gap | Evidence |
|---|---|---|
| G1 | The mic hides every reason (section 4) | `console-book-talk.js` `mic()` `catch (_)`, `sendRec()` |
| G2 | C57 says "Outside services: Anthropic (the talk-through only)" | The show also uses Google Text-to-Speech (narration) and Speech-to-Text (spoken questions); the talk uses whichever non-training brain is the default (`talk.py`) |
| G3 | Integrations list 15 services | The coverage check finds 30 (`scripts/arch_inventory.py`): missing e.g. GitHub, Tailscale, Open-Meteo, NDMA SACHET, Google Photos Picker, Contacts, Tasks, Home Assistant, Frigate, Mosquitto, Ollama, YouTube. The guide's 6.5 "What leaves your project" lists 9 |
| G4 | Limitations silently cut at 80 | 82 found; `write.py` `limits[:MAX_LIMITATIONS]` |
| G5 | Technology inventory incomplete | `gen/libs.py` covers 67 Python pins, 8 vendored JS, 3 fonts, 2 models; not the Android libraries (`android/gradle/libs.versions.toml`: AGP 9.5.1, Kotlin 2.4.10, 5 AndroidX/browser-helper libs, Apache-2.0), the home kit images (Mosquitto 2.0.20, Frigate 0.17.2, Home Assistant 2026.10.0 in `deploy/home/docker-compose.yml`), the bridge's 24 pins (`deploy/home/bridge-requirements.txt`) or dev tools (Markdy 1.5.7, ruff, mypy, pytest). Licence names are not normalised ("Apache-2.0" / "Apache 2.0"; "BSD" / "BSD License" / "BSD-3-Clause") |
| G6 | Lines of code are raw newlines | `gen/code.py` `_lines` counts every line (comments, blanks, CSS, HTML); no tests, no split. Python source measured with the standard library's `tokenize`: 107,710 code, 15,302 docstring, 2,446 comment-only, 23,028 blank lines (772 files); the book says 176,907 lines for 65 packages |
| G7 | Costs: "GitHub Actions 2,000 minutes a month" | That is the private-repository allowance; this repository is public (likely free on standard runners). Unverified — GitHub's billing page confirms. Firestore's free reads, writes and deletes a day are not listed |
| G8 | The scrubber leaves IP addresses alone and has no PAN pattern | `gen/scrub.py` docstring ("IP addresses are left alone"); the new rules need both |
| G9 | No dedup across sealed releases | each release seals its whole 7.8 MB zip (`seal.py` `seal`) |
| G10 | Diagrams carry no C-numbers | 0 C-ids in the 14 `docs/architecture/diagrams/*.markdy` sources |
| G11 | A dev shortcut opens the Book with no passkey | `api/book_show_access.py:92` (`console()`: token mode and `env == "dev"`) and `:221` (`"token-mode dev, no passkey"`); nothing refuses `JARVIS_ENV=dev` on Cloud Run (`config.py` `require_prod_invariants` checks only the API token; `K_REVISION` is read only by the self-health watch). Conflicts with rule 1 ("including for local development") and C8.2. Production is safe from repo configuration (`deploy/cloudrun.sh:520` sets `JARVIS_ENV=prod`, `JARVIS_AUTH_MODE=google`) |
| G12 | Hear maps "limit unreadable" to 402 `budget_reached` | `api/book_show.py` `_voice_failure` (every `BudgetError`); elsewhere `BudgetUnavailable` is a 503 |
| G13 | The free-minutes wording | Past the free allowance listening is charged, not refused (`billing.ensure_units_allowed`) |
| G14 | The 15 MiB code-zip cap will be reached | ≈ 12 feature releases at +0.63 MB each (section 3) |

---

## 7. The AI writer plan

### 7.1 Where it runs

The Workshop proposed "inside the post-deploy sealing step on Cloud Run with the existing Secret Manager
key". Checked against the code:

- **Sealing is a tick job, not a step after the deploy.** `BookSealJob` (`sealer.py`) runs on the existing
  tick (the 5-minute watchdog and the morning brief, the 2 Cloud Scheduler jobs) with a 45 s budget
  (`JOB_BUDGET_S`); all jobs share 150 s a tick (`ticks.TICK_TOTAL_BUDGET_S`), a job at most 60 s
  (`MAX_BUDGET_S`). Cloud Run gives CPU only during a request (`sealer.BOUNDED_S` comment); the service
  has 1 CPU, 512 MiB, 300 s timeout, at most 1 instance (`deploy/cloudrun.sh:542–543`). One Sonnet page
  takes about 20–40 s. A 135-page write cannot fit in one step.
- **The source is there.** The image has `/app/src` but not `docs/`, `tests/`, `evals/`, `android/` or
  `*.md` (`.dockerignore`). However `_book/source.zip` is package data in the image
  (`pyproject.toml` `"jarvis.buildbook" = ["_book/*"]`) and holds all 2,277 tracked text files of that
  release, docs and Android included. The writer reads that zip in memory: the exact code of the running
  release, no git needed.
- **The key is there.** `JARVIS_ANTHROPIC_API_KEY` is mounted from Secret Manager (`cloudrun.sh:149`,
  `--set-secrets` at `:533`). No new copy.
- **The text cannot go into `book.json`.** Its SHA-256 is fixed in `release.json` at CI time and
  re-checked (`release.py`), and `--check` demands byte-identical builds. AI text is a new sealed file
  kind beside `book` and `source` (`seal_index.KINDS`, `checked_files` change in Part 2).

**Recommendation:** a separate, resumable tick job `book_write`, after `book_seal`, never at start-up:
it writes 1–3 pages per tick (parallel calls inside a ≤ 50 s budget), keeps its progress and drafts sealed
in Firestore, and seals the checked AI text as the release's third file when done. No new Cloud resource,
no new key copy, nothing in GitHub. Throughput (Estimate): first write 4–12 hours (once, overnight); a
feature release 1–4 hours; the deterministic book still seals within 5 minutes as today, and the AI text
follows with its own "sealed" message. **Alternative** if the tick gets crowded (the self-health watch
would show `skipped` jobs): a Cloud Run Job from the same image with the same secret reference (minutes,
not hours; one more resource and one more permission, set up by `cloudrun.sh`). **Not recommended:** the
CI deploy job (it would need the key in GitHub; `eval-gate` already reads a `JARVIS_ANTHROPIC_API_KEY`
GitHub secret — Unverified whether one is set).

### 7.2 Model tier, router and fallback

`jarvis.llm` through the brain registry, as the talk lane does (`brains.router_for(spec.id)`), on
**BALANCED** (`config.model_balanced` = `claude-sonnet-5-5`), only a brain with `trains_on_content =
False` unless the owner allows the free one for the book. The router degrades STRONG → BALANCED → FAST on
transient errors and can hand an unreachable cloud to the laptop's fallback brain (`llm/router.py`
`_DEGRADE_TO`, `FallbackBrain`); for the writer that is wrong (quality, laptop off). Part 2 asks the
router not to fall back for this call, or records the model per page and rejects a page written below
BALANCED. Unverified whether the router already has such a switch. No-AI mode (`brain_mode = "none"`)
raises `BrainOff`: the previous text stays.

### 7.3 What it reads, and what it never reads

Reads: the release's `source.zip` (code, docs, plans, the architecture guide) and the fact pack. Never:
`.env*` (names only, from `.env.example`), key files, `gen/fake_secrets.txt`, `gen/redact.json`,
`tests/fixtures/**` and any eval fixture with recorded data, logs, sealed bundles, `.claude/**`, anything
binary or over 1 MB (already out of the zip), and nothing from Firestore, the vault, memory, mail,
contacts, photos or cameras. Each page gets a **reading pack**, not whole files: its catalogue card, the
docstrings, signatures and route tables of the files the card cites (`Where in the code`), the matching
plan sections and its slice of the fact pack, capped at 12–24k tokens. Measured: the median card cites
112 KB of files (≈ 28k tokens); all of `src/jarvis` is 8.6 MB of text.

### 7.4 The fact pack (computed by code every release; the AI quotes, never types numbers)

| Fact | How it is computed |
|---|---|
| Versions | `jarvis.__version__`, the release label (`gen/plans.release_label`), commit id and date (`gen/repo.py`) |
| Routes | an AST scan of `@router.get/post/put/delete/patch` and `add_api_route` in `src/jarvis/api/*.py` (deterministic, no app import) |
| Firestore collections | `scripts/arch_inventory.py` (106 today) |
| Modules and components | the catalogue cards C01–C68 (`JARVIS-Architecture.md` §3) and the 65 packages (`gen/code.py`) |
| Screens | console panels `id="p-*"` in `console.html` (22 today), `/book/show`, the Android activities (`android/app/**/*Activity.kt`) |
| Integrations | the 30 outside services (`arch_inventory`) |
| Lines of code | the counter of 9.2, per module, source / tests / config / generated separately |
| Limits | `Settings` field defaults and bounds (`config.py`), e.g. `book_talk_questions` 20, `book_session_minutes` 45 |
| Costs | `gen/costs.py` (prices, free allowances, ₹ rate and its date) |
| Source references | every tracked path, every top-level function and class (AST), every `Settings` field, every collection: the index the checks look up |
| Verified flags | each hosting or security fact carries `verified: false` until a live check sets it |

The AI writes `{{fact:book.talk_questions}}`-style placeholders; the assembler fills them. A page whose
code changed only in a number then needs no rewrite.

### 7.5 The checks before anything is sealed (a rejected page keeps its previous text)

1. **Source references exist:** every path, `path:symbol`, setting name and collection in a draft must be
   in the fact pack's index.
2. **Numbers match:** outside a marked fictional example block, every number must be a placeholder.
3. **Personal data and secrets:** `gen/scrub.Scrubber.verify` (URLs, private hosts, e-mails, phone
   numbers, 10+ digits, secret shapes, hashed names) + `buildbook/owner_id.in_book` (the owner's address
   and its distinctive parts) + new kinds: IP addresses, PAN, Aadhaar written in groups, hostnames and
   project-id shapes.
4. **Unverified stays Unverified:** a sentence using a fact with `verified: false` must carry the label.
5. **No invented features:** every capability claim must cite a source reference; items in the guide's
   §11 Roadmap (PLANNED) may appear only under "Planned".
6. **Negative controls (evals):** a fake path, a wrong number, an e-mail address and an invented feature
   must each be rejected; the cap and No-AI fall back to the previous text.

### 7.6 Rupee estimates (Sonnet, Opus, Haiku) and proposed caps

Page count (measured): 68 catalogue cards + 22 console screens + 30 outside services + about 15 book
chapters = **≈ 135 pages**, plus the tour script. Changed pages per release (measured from `git diff`
of the files each card cites): 7, 24, 44, 28, 36 cards in the feature releases R6.1, R11, R11.1, R7, R14;
1–3 in hotfixes. Assumptions: low / mid / high = 12k / 16k / 24k input tokens and 2.2k / 3k / 3.5k
output tokens a page, 15 / 25 / 30 % of pages redrafted after a failed check, the tour written and timed
twice (60k in, 4k out each). Prices from `src/jarvis/llm/pricing.py` (US$ per million tokens in / out:
Opus 5.5 4 / 20, Sonnet 5.5 2 / 10, Haiku 5.5 0.10 / 0.50).

| | Pages | Sonnet 5.5 | Opus 5.5 | Haiku 5.5 |
|---|---|---|---|---|
| First full write — low | 135 | ₹711 | ₹1,421 | ₹36 |
| First full write — **mid** | 135 | **₹1,027** | ₹2,054 | ₹51 |
| First full write — high | 135 | ₹1,418 | ₹2,836 | ₹71 |
| Feature release — low | 30 | ₹182 | ₹363 | ₹9 |
| Feature release — **mid** | 45 | **₹363** | ₹725 | ₹18 |
| Feature release — high | 60 | ₹647 | ₹1,294 | ₹32 |
| Hotfix (1–3 pages, tour unchanged) | 1–3 | ₹5–30 | ₹10–60 | under ₹2 |
| Free Gemini brain | any | ₹0 | — | — |

Prompt caching of the shared instructions (Sonnet cache reads at 5 %) saves roughly ₹100–150 on the first
write. **Proposed hard caps** (for approval): first write ₹1,500 (one-time), ₹500 a release, ₹1,000 a
month for the Book; the writer also stops before it would take the owner's monthly limit
(`billing/budget.py`) past 80 %. At any cap, in No-AI mode or on failure, the previous release's text
stays, labelled with its version.

**The free Gemini option:** `llm/gemini_provider.py` is chat-only (fine: the writer needs no tools);
the free tier may use prompts to improve Google's products (`config.py` comment); the writer would send
only public code, nothing personal. The code holds no numeric free quota: "RPM/RPD limits are not
published … expect 429s" (`docs/plans/phase2-slice3-gemini-free-brain.md:19`), mapped to transient
errors. A first write of ~170 calls may take several days of free quota (Unverified). The strong tier is
the same flash model (`gemini_model_strong`). Quality must pass the same checks and a side-by-side
review of 5 pages first.

---

## 8. The two versions

### 8.1 Today's 13 scenes → the short tour (target 12–13 minutes, Estimate)

| Today | Short tour scene | Target |
|---|---|---|
| 1 The build book | 1 What JARVIS is, who it's for, what's new in this release | 60 s |
| 2 Eight layers | 2 The eight layers in one picture (3D plates) | 75 s |
| 3 One conversation turn + 5 Confirm + 6 Voice | 3 The running example, start to finish (C2) | 180 s |
| 4 Memory and privacy | 4 Privacy and security in plain words | 75 s |
| 7 Home, 8 On its own | 5–10 Six module highlights (8.2) | 6 × 40 s |
| — | 11 "What else JARVIS can do" (one grouped scene, grows without adding time) | 50 s |
| 9 Stack and licences | 12 How it is built (short) | 40 s |
| 10 Costs | owner only; the guest view hides costs | (20 s) |
| 11 Not built yet | 13 What's planned next | 40 s |
| 12 Questions, 13 Closing | 14–15 Questions, closing (fixed lines, `lines.py`) | not counted / 20 s |

Total ≈ 12.7 minutes before questions. Every scene links to its full-book chapter. The timer estimates
narration time from the characters and a measured speaking pace, plus each scene's animation time; it
must be calibrated once with a stopwatch on the live show (Unverified until then; the show's caption pace
of 330 ms a word is faster than the cloud voice).

### 8.2 Proposed short-tour modules (for approval, stop 2)

Highlights: Voice; Approvals and passkeys; Memory; Vault and documents; Home bridge and cameras; the
Android app and SOS. In the running example: chat and the brain router, Calendar, the activity log.
Grouped in "What else": people research, web search, WhatsApp drafts, the morning brief and helpers,
groceries, parcels, family calendars, Telegram, Vitals, the Build Book itself.

### 8.3 The voice cost of a 10–15 minute tour

Today's show speaks about 6,480 characters (6,231 in scenes 1–11 plus the fixed lines, measured). The free
allowance is 900,000 Chirp 3: HD characters a Pacific month for the **whole deployment**, shared with the
console's own spoken replies (`config.voice_tts_free_chars`); beyond it US$30 a million characters
(`voice_price_chirp3_hd_usd_per_m`), ≈ ₹0.0029 a character. Each show is synthesised again (no cache).

| Tour | Characters (Estimate) | Tours free a month | ₹ a tour beyond the free allowance |
|---|---|---|---|
| Today's show | ≈ 6,480 (measured) | ≈ 139 | ≈ ₹18.5 |
| 10 minutes | ≈ 7,000 | ≈ 129 | ≈ ₹20 |
| 13 minutes | ≈ 9,100 | ≈ 99 | ≈ ₹26 |
| 15 minutes | ≈ 10,500 | ≈ 86 | ≈ ₹30 |

Spoken answers to questions add to this. The browser voice is always ₹0. Spoken questions: 3,240 free
seconds a month (≈ 216 questions of 15 s), then ≈ ₹0.57 per 15 s question. An option for later: keep the
tour's audio per release, so a tour is paid once per release, not per showing (needs about 3 MB a release).

### 8.4 The full book's storage per release, with dedup (Estimate)

| Part | Size | With dedup by content hash |
|---|---|---|
| Code zip | 7.8 MB, +0.6 MB a feature release | per-file store: ≈ 8 MB once + ≈ 1–2 MB of changed files a release |
| book.json + AI text (compressed) | ≈ 0.2 + ≈ 0.4–0.6 MB | stored per release |
| Module images (measured WebP, 9.4) | base ≈ 12 MB (cropped to the panel) – 22 MB (full screen) | stored once; ≈ 2–4.5 MB of changed screens a release |
| 3 kept releases, no code dedup, 8 MB image budget | ≈ 27 + 2 + 12 + 16 = **≈ 57 MB** | over the 80 % warning (48 MB) |
| 3 kept releases, code dedup, 8 MB image budget | ≈ 11 + 2 + 12 + 16 = **≈ 41 MB** | 68 % of 60 MB |

Recommendation: de-duplicate the code zip per file as well as the images (same mechanism, ₹0); image
budget 8 MB a release as the owner suggests, expected use 2–4.5 MB. If the cap ever needs raising, 100 MB
stays inside Firestore's free 1 GiB (₹0; about ₹1.4 a month per 100 MB beyond it, and ≈ ₹0.3 a month more
in backups if those are on). Warn at 80 %, never drop a sealed release without telling the owner.

---

## 9. The prompt's Phase C, D and E questions

### 9.1 C2 — the running example: "Add a dentist appointment on Friday at 5 pm"

It exists end to end, with one correction: **Activity offers Undo only for deletes**, not for a created
event.

| Step | Where |
|---|---|
| Tap and speak | `console-voice-mic.js` (composer mic, Ctrl+Space), `console-voice-capture.js` |
| Speech to text | cloud: `POST /v1/voice/transcribe` (`api/voice.py`) → `voice/service.transcribe` → `GoogleSTT` (en-IN); or the browser's recogniser under "Automatic" (`console-voice-loop-browser.js`) |
| Heard / understood as | `POST /v1/input/understand` (`api/fix_files.py`) → `understand/service.py` |
| Chat API | `POST /v1/chat/stream` (`api/routes.py`), `channel: voice` |
| Brain router and tool call | `core/brain.py` `Brain` → `llm/router.ModelRouter` (BALANCED) → `anthropic_provider`; tool `calendar_create_event` (`tools/google_calendar.py`) |
| Approval card | `tools/gateway.py`: an ALLOW for a write on a spoken turn is tightened to ASK (`taint.spoken_in_context`); an event with no guests is REVERSIBLE (R2, no passkey; guests make it R3) → card in `console-approvals.js`; `POST /v1/approvals/{id}/approve` (`api/routes.py`) |
| Google Calendar | `tools/google_calendar.py` through the Google link (`integrations/`) |
| Activity log | `activity/recorder.py` writes the row; a created event shows "Can't be undone from here — ask JARVIS to change or delete it" (`activity/words.NOTE_WRITE`) |
| Reply, on screen and spoken | the streamed reply; `POST /v1/voice/speak` (Chirp 3: HD, en-GB) or `speechSynthesis` (`console-voice-speech.js`) |

Failure branches: mic denied (`console-voice-mic.js` `HELP.blocked`); STT fails (503 → the browser's
recogniser under "Automatic", `console-voice.js:270`); No-AI mode (`offline/no_ai.py` + `offline/rules.py`
`_calendar` handles only *listing* events: adding one needs the AI); monthly limit (402 before the stream,
`api/routes.py`); a free brain that learns from prompts gets no tools at all (`core/brain._tools_on`), so the
event is not created; Calendar refuses (the tool's error result in plain words). **Proposed improvement:**
extend the example with a second line, "Cancel it", which deletes the event with an Undo in Activity
(`tools/calendar_undo.py` `CalendarRestorer`, `undo/service.py`, 30 days), so the Undo step is real.

### 9.2 C3 — the 8 diagrams from the 14 Markdy sources

| Needed | Reuse | Change |
|---|---|---|
| 1 System context | `01-context` | add guests, Tailscale, GitHub Actions, Open-Meteo, NDMA SACHET, Photos Picker, Home Assistant / Frigate / Mosquitto (30 services) |
| 2 Application architecture | `03-deployment`, `02-layers` | add the Android app, the 2 Scheduler jobs, background tick jobs, the home bridge |
| 3 Module dependencies | — (new) | generated from the cards' "Depends on" fields |
| 4 Running-example sequence | `04-chat-turn`, `05-approvals-passkeys`, `06-voice-loop` | one sequence with the return path and the failure branches |
| 5 Data flow and lifecycle | `14-privacy-map`, `07-memory` | add retention and outbound sends |
| 6 Deployment | `13-release-flow`, `03-deployment` | secrets, network boundaries, the Tailscale link, the AI writing step |
| 7 Book Q&A and microphone | `12-build-book-guest` | add the hear path of 4.1 |
| 8 Backup and restore | — (new) | as it exists: off until the owner's one-time step (9.5) |

Not used by the 8: `08-vault-digilocker`, `09-brief-ticks`, `10-home-alarm`, `11-systems-vitals` (module pages
reuse them). The C-numbers exist (C01–C68, no gaps, no repeats) but **no diagram uses them**: node ids are
names (`Jarvis`, `Data`, …). Part 2 adds the C-id to every node and a CI check that every catalogue card
appears in at least one diagram and ids match across diagrams. Tooling exists: `scripts/markdy_export.py`
(`--check`, `--lint-only`), `@markdy/cli` 1.5.7 (MIT), CI job `docs`.

### 9.3 C4 — the technology inventory source

`gen/libs.py` already reads every pin in `requirements.lock` (67 packages, hash-locked) with the licence
`requirements.licences.json` records for that exact version (`gen/licences.py`, refreshed with
`--licences`), flags copyleft and non-commercial licences, and adds the vendored three.js, onnxruntime-web,
MediaPipe, tesseract.js, zxing, the wake-word code and models and the fonts. Missing: see G5. Part 2 adds
Android (`android/gradle/libs.versions.toml`), the home kit images and bridge pins, dev tools
(`tools/markdy/package-lock.json`, the `dev` extra), one licence spelling (SPDX), and the run-time /
build-and-maintenance split.

### 9.4 C5 — the module list and the lines-of-code method

17 modules, every catalogue card in exactly one:

| Module | Cards |
|---|---|
| Console and API | C01, C02, C03, C41 |
| Chat and the brain router | C09, C13, C14, C15, C16, C17, C68 |
| Voice | C05, C06 |
| Memory and knowledge | C10, C23, C24 |
| Vault and documents | C07, C42, C43 |
| People and faces | C08, C21 |
| Home bridge and cameras | C38, C39, C40, C63 |
| Alerts and notifications | C45, C46, C47 |
| Google, Telegram and other integrations | C04, C20, C22, C29, C30, C31, C32, C33, C34, C35, C36, C37 |
| Vitals, costs and the systems check | C44, C54, C55, C56, C67 |
| The privacy panel | C53 |
| Activity log and undo | C12, C48 |
| Approvals and passkeys | C18, C28, C51, C52 |
| The Android app | C62, C64, C65 |
| Daily helpers (brief, helpers, family, groceries, parcels) | C11, C19, C25, C26, C27, C60, C61 |
| Delivery, CI and backups | C49, C50, C58, C59, C66 |
| The Build Book | C57 |

A new card joins its module by its layer and skill, or the coverage check fails until it is placed.
**LOC:** neither `cloc` nor `tokei` is installed. Proposal: a small counter in the generator, standard
library only (`tokenize` for Python; a comment-aware scanner for JS, CSS, HTML and Kotlin), counting code,
comments and blanks separately, source / tests / config / generated separately, shared code once under its
own module, re-checked once in a test against a reference count. Measured with it today (Python source):
107,710 code lines (G6). Alternative: `pygount` 3.2.0 (BSD-3-Clause, pip), but it pulls in `chardet`
(LGPL) and `gitpython`, so it is a heavier dev-only tool.

### 9.5 C6 — data, hosting, security and recovery (From repo configuration)

- **Hosting:** Google Cloud Run, region `asia-south1` (`deploy/cloudrun.sh:48`, `ci.yml` `REGION`);
  Firestore `(default)` in the same region (`cloudrun.sh:417`); 1 CPU, 512 MiB, 0–1 instances. Local: `jarvis
  serve` (token sign-in, memory or Redis sessions; `docker-compose.yml` runs the API with Redis).
  Code reaches production only through CI: no-traffic rollout, `/health`, traffic switch (`ci.yml`
  `deploy`). Unverified live — the Cloud Run service page confirms the region.
- **Encryption:** TLS to Cloud Run (Google-managed) and to the home bridge through Tailscale Funnel
  (`deploy/home/setup-windows.ps1` step 7); at rest Firestore's own encryption plus JARVIS's AES-256-GCM
  for the vault, the sealed books, book sessions and tokens (`integrations/vault.TokenCipher`,
  `keyring.py`, key `<JARVIS_TOKEN_KEY>` from Secret Manager). Sign-in: Google (owner list
  `JARVIS_OWNER_EMAILS`), passkeys (`webauthn`), Permissions (`api/permissions.py`).
- **Backups:** Firestore managed backups, daily, kept 7 days, delete protection, and a restore drill into
  a separate `jarvis-drill` database (`deploy/backup_setup.sh`, `src/jarvis/backup/`, R14 D3–D4). **Off
  until the owner runs `bash deploy/backup_setup.sh` and types YES**; the deploy only runs `--status`.
  Cost about ₹4 a month at 100 MB (`docs/plans/r14-hardening.md:7`). Whether a restore has been tested
  live: Unverified (the drill code and its tests exist).
- **Outbound transfers:** the guide's §6.5 covers 9 services; the full book must cover all 30 (G3) and the
  AI writer (it sends only public code and docs to the chosen brain). Providers' logging and retention:
  Unverified for every one.

### 9.6 C7 — "How answers are made" (what the code supports today)

> Your question, the last few questions of this session and the matching parts of this book (at most
> 10,000 characters) go to JARVIS's everyday brain — today Claude Sonnet 5.5 from Anthropic — through
> JARVIS's brain router. Nothing about you is sent: personal questions are refused by fixed rules with no
> AI call, and every answer is checked for e-mail addresses, phone numbers and secrets before you see it.
> A spoken question is turned into text by Google Cloud Speech-to-Text (Indian English) from JARVIS's own
> Google Cloud project; the recording is not kept. With No-AI mode on, or the monthly limit reached, no AI
> is asked and JARVIS says so.

Evidence: `talk.py` (BALANCED, `MAX_TOKENS` 400, last 8 turns), `prompt.CONTEXT_CHARS` = 10,000,
`guard.py`, `api/book_show.py` `show_hear`. "Claude Sonnet 5.5" holds only when the deployment's default
brain is Anthropic (`JARVIS_LLM_BACKEND`, set by `cloudrun.sh`): Unverified live; the note must name the
brain from the running settings, not from text.

### 9.7 C8 — a local setup today

- Exists: `jarvis serve` (`Makefile` `serve`), token sign-in (`JARVIS_AUTH_MODE=token`), memory or
  Redis sessions, the mock brain (`JARVIS_LLM_BACKEND=mock`, as the browser tests run it). The Firestore
  emulator is used only by CI's `firestore` job (`FIRESTORE_EMULATOR_HOST`); the Google client honours that
  variable, so a local run against it should work (Unverified — to be run in Part 2).
- The Book locally: token mode + `JARVIS_ENV=dev` opens it with no passkey (G11), and a guest show is
  refused (`guest_needs_google`). A real local Book with passkeys needs Google mode, which needs an OAuth
  client for `localhost`.
- **Missing:** a guard that refuses dev-only settings on Cloud Run. Part 2 adds one: start-up fails when
  `K_SERVICE` (Cloud Run's own variable) is set and `JARVIS_ENV=dev`, `JARVIS_AUTH_MODE=token` without an
  API token, or memory sessions. Decision 6 asks whether the passkey-less dev open stays.

### 9.8 Phase D — images

- **Seed and screenshots:** `scripts/ui_snapshots.py` exists (real app, mock brain, 1440×900 and 390×844,
  night and day, every panel, DOM checks; fixtures from `tests/browser/ui_checks.py` via `page.route`;
  `seed_conversations` types four sample chats). There is **no demo-household seed** (no fake names set,
  no SAMPLE documents, no avatars, no camera test pattern) and no fixed clock or masking: Part 2 adds them.
- **OCR for the privacy gate:** the `tesseract` binary is in this sandbox (5.3.4) but not installed in
  CI's workflow, and `pytesseract` is not a dependency. Better: the vendored **tesseract.js** (Apache-2.0,
  `static/vendor/vision/r7-1`, already in the inventory) runs in the same Chromium that takes the
  screenshots: no new dependency.
- **Measured sizes** (one console screen, WebP quality 80): desktop 1x 73 KB, 2x 167 KB; phone 1x 21 KB,
  2x 48 KB; the existing diagram SVGs average 22 KB. All under the 250 KB limit. About 7 images a module
  (overview, 2–6 steps, one error state, phone, one schematic SVG) → ≈ 120 images for 17 modules.
- **Budget:** base set ≈ 12 MB (cropped to the panel) to ≈ 22 MB (full screen); new images ≈ 2–4.5 MB a
  release; the owner's 8 MB a release fits with code dedup (8.4).
- **Native Android screens** (setup, SOS, privacy activities) can't be captured by Playwright: phone shots
  are the console at 390×844; the native screens get schematics unless an emulator step is added to
  `android.yml` (later, Estimate +0.5 day).

### 9.9 Phase E and the owner and guest views — what exists

| Exists today | Where |
|---|---|
| Guest view: the show only, no reader; costs (month and limit) for the owner only | `console-book.js` `toShow`, `show_script.py` |
| Owner reader of the sections and kept releases, single-use code download | `console-book-reader.js`, `api/book.py` |
| 3D (three.js) and 2D shows with a performance budget, reduced motion, phone fallback | `console-book-3d.js`, `console-book-2d.js`, `console-book-scenes*.js` |
| Show controls and keys, captions, chapters | `console-book-show.js`, `book.html` |
| Design tokens of the console | `console.css`, `console-deck.css`, `console-fx.js` `JarvisFX.tokens()` |

Missing: the Short tour / Full book choice, search, module index, Simple / Technical / Both, interactive
architecture, walkthrough player, print views, the guest-safe full book, axe checks.

---

## 10. Repository inspection (only what the full book must cover)

- **Dependencies:** `pyproject.toml` (17 run-time packages, `dev` and `homebridge` extras),
  `requirements.lock` (67 hash-locked pins, Python 3.12 image), `requirements.licences.json`,
  `android/gradle/libs.versions.toml`, `deploy/home/bridge-requirements.txt`, `tools/markdy/package-lock.json`.
- **Configuration:** 155 settings with prefix `JARVIS_` (`config.py`); secrets by name only:
  `JARVIS_API_TOKEN`, `JARVIS_GOOGLE_CLIENT_SECRET`, `JARVIS_SESSION_SECRET`, `JARVIS_ANTHROPIC_API_KEY`,
  `JARVIS_GEMINI_API_KEY`, `JARVIS_OPENAI_COMPAT_API_KEY`, `JARVIS_TOKEN_KEY`, `JARVIS_TAVILY_API_KEY`,
  `JARVIS_TELEGRAM_BOT_TOKEN`, `JARVIS_TELEGRAM_WEBHOOK_SECRET`, `JARVIS_GOOGLE_API_KEY`.
- **Delivery:** `Dockerfile` (python:3.12-slim, hash-locked install, non-root user, build date stamp),
  `.dockerignore`, `deploy/cloudrun.sh` (APIs, Firestore, secrets, Workload Identity Federation for CI,
  2 Scheduler jobs), `.github/workflows/ci.yml` (test on 3.11 and 3.12 with coverage floor, docs-check,
  pr-title, firestore emulator, browser, docs/diagrams, eval-gate, deploy) and `android.yml`.
- **Home bridge:** `src/jarvis/homebridge/` (34 files: HA, Frigate, MQTT, faces, camera, heartbeat) and
  `deploy/home/` (Docker Compose with Mosquitto, Frigate, Home Assistant and the bridge; WSL2 and Windows
  set-up scripts; Tailscale Funnel on port 8443).
- **Android:** `android/` (46 Kotlin files: set-up, the phone's door, SOS and its tile, Talk tile, Health
  Connect sync, folder sync, privacy screen), AGP 9.5.1, Kotlin 2.4.10.
- **Docs:** `docs/architecture/JARVIS-Architecture.md` (v14.0.3, 12 chapters, 68 cards, 14 diagrams,
  glossary), 30+ plans in `docs/plans/` (R6: `r6-build-book.md`, v6.0.1, Superseded), checked by
  `scripts/check_doc_versions.py` and `scripts/arch_coverage.py` (OK: 65 packages and modules, 90 console
  modules, 2 Scheduler jobs, 30 outside services, 106 collections).

---

## 11. Placement, effort and the approval stops

The owner approved the Book side by side with R13 (wardrobe): Part 1 built alongside R13 and merged
first; Parts 2 and 3 after R13. With the full prompt (Phase D images, 8 diagrams, a setup guide actually
run, the guest-safe full book), the effort is larger than the Workshop's first plan:

| Part | Version | Builder effort (Estimate) | Calendar (Estimate) | Waits for |
|---|---|---|---|---|
| 1 Mic fix | `v6.2.0` | ≈ 1 day + review + one full browser run | 16–17 Nov, beside R13 | stop 1 |
| 2 Content: fact pack, AI writer and checks, tour and timer, sealing format with dedup and the 80 % warning, coverage and drift checks, 8 diagrams with C-ids, inventory, LOC, demo seed and capture with the OCR gate and manifest, setup guide and the Cloud Run guard, "Continue where I left off" | `v6.3.0` | ≈ 9–10 builder-days (4 builders) + the first AI write overnight | ≈ 4 days after R13 | stops 2 and 3 |
| 3 New look: mockups, Book-only tokens, reader with search, index and toggle, interactive architecture, walkthrough and tour players, guest view and its isolation tests, print views, axe, before/after snapshots of every other screen | `v6.4.0` | ≈ 7–8 builder-days (3D on Fable 5.2) | ≈ 3 days | stop 4 |

So the voice build (R5.2) moves about **6–8 days** later, not 3–4. **The 5 approval stops, in order:**
1. after Phase A (this report); 2. after the short tour's module list and first script; 3. after the image
contact sheet; 4. after the Book mockups; 5. every PR (the owner merges). Showing the mockups early (during
R13, as the Workshop planned) is fine, but their approval stays stop 4.

---

## 12. What contradicts the Workshop's proposal (`proposal.md` §3)

| Proposal | Finding |
|---|---|
| H1 every failure looks the same | **Confirmed** (6 causes, one sentence) and worse: 3 outcomes show nothing |
| H2 "Mic off" follows into the Book | **Confirmed**; also no way to switch it on in the Book |
| H3 free 54 minutes used up → "voice unavailable" → "I didn't catch that…" | **Overturned:** past the free minutes listening is charged until the monthly limit (402); the Book shows the server's own sentence, "I didn't catch that" only when none comes |
| H4 the button hides when unsupported | **Confirmed** |
| "About 8–9 MB a release likely now" | **Measured 7.98 MB** |
| The writer inside the sealing step | Sealing is a 45 s tick job; the writer must be its own resumable tick job (or a Cloud Run Job). The key point holds: Secret Manager, no new copy. The image lacks docs, but `source.zip` in the image has them |
| ₹500–700 first write, ₹100–175 a release; caps ₹800 / ₹200 / ₹1,000 | **About ₹710–1,420 (mid ₹1,030) and ₹180–650 (mid ₹360)**: 135 pages and 7–44 changed cards a feature release, measured. Proposed caps ₹1,500 / ₹500 / ₹1,000 |
| Voice: 9,000–10,000 characters, ~100 tours, ₹25–28 | **Confirmed for a 13–14 minute tour**; 10 min ≈ 129 tours / ₹20; 15 min ≈ 86 / ₹30 |
| Storage: ~10 MB images once, 1–2 MB a release, 35–40 MB for 3 | Measured screenshots give 12–22 MB once and 2–4.5 MB a release; without code dedup 3 releases reach ≈ 57 MB with an 8 MB image budget |
| Parts 2 and 3 on 19–22 Nov; R5.2 moves 3–4 days | Full scope ≈ 7 calendar days after R13; R5.2 moves ≈ 6–8 days |
| The prompt is cut off | Resolved: the full prompt was received and is covered here |

---

## 13. Decisions for the owner (safe defaults in brackets)

1. AI writer tier: Sonnet 5.5 (balanced) [yes]; the free Gemini brain only after a 5-page trial [no].
2. Caps: ₹1,500 first write, ₹500 a release, ₹1,000 a month [yes].
3. Where it runs: a resumable tick job inside JARVIS, first write overnight [yes]; a Cloud Run Job only if
   the tick gets crowded [no].
4. Book listening stops at the free monthly minutes instead of charging [yes: stop and say so].
5. Book only: Chrome's free recogniser as a fallback for owner sessions when the cloud can't listen
   (audio then goes to the browser's maker) [no].
6. The passkey-less dev open (G11) is removed, and dev settings refuse to start on Cloud Run [yes].
7. De-duplicate the code copies as well as the images [yes]; image budget 8 MB a release [yes].
8. The running example: dentist appointment plus "Cancel it" for a real Undo [yes].
9. Short-tour modules as in 8.2 [yes, confirmed at stop 2].

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.2.1 | 15 Nov 2026, 16:46 IST | R6.2 | First edition: how the book is made, measured sizes per release, the microphone traced and reproduced (20 cases) with its root cause and the Part 1 fix design, Claude used and called, gaps and wrong facts, the AI writer plan with ₹ estimates and caps, the two versions, the full prompt's C2–C8, Phase D and E questions, placement, effort and the approval stops | 🛠 Mark XXI |
