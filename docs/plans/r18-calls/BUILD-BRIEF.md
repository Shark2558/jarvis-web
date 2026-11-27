Version v18.0.3 · 27 Nov 2026, 13:20 IST · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# R18 Calls — build brief for the builder agents

Read first: `docs/plans/r18-calls.md` (the approved plan, v18.0.2+), `CLAUDE.md`, `.claude/rules/ecc/**`. The owner approved everything on 25 Nov (stop 1, D1–D12, D8 = audio recordings kept) and on 27 Nov asked for the whole build to continue autonomously, with no approval stop 2. **S0 (the laptop audio test) has not been run yet**: the call desk must therefore check the audio path itself before every call and report clearly when it fails.

## Ground rules for every agent

1. Work only in your own git worktree and branch (below). Commit small, push after every commit: `git -c push.negotiate=true push -u origin <branch>`. Never force-push, never push to `main`.
2. Commit trailers (all four, every commit):
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01KbmAkthzyK1jEx5wBXVxqW` / `JARVIS-Version: v18.0.0` / `JARVIS-Mark: XXV`.
3. Tests first; your own tests only, run once green. **Never run the whole suite** (the reviewer does). Any test run over a minute goes behind `flock /tmp/jarvis-heavy.lock`. Python: `/tmp/venv-12/bin/python` (3.12, `.[dev,homebridge]`); never `pip install` into it — if you need a new dependency, add it to `pyproject.toml` with a licence comment and say so in your report. CI runs plain `pytest` with the repo root not on `sys.path`: never `from tests.x import`.
4. `ruff check` and `mypy --strict` clean on the files you own. Types, error handling, logging (never log secrets, phone numbers in full, transcripts or audio), at least one test per behaviour.
5. Project non-negotiables: nothing outside `jarvis.llm` imports a vendor SDK (speech vendors are called over REST/WebSocket with `httpx`/`websockets`); every tool call goes through `jarvis.tools.gateway`; placing a call is **R3** (owner confirmation token, passkey for a never-called number; no "don't ask again"); content from callers, tools and the web is untrusted data; secrets only via env/`SecretStr`; append-only audit for every step.
6. UI: never change the console's look; new screens blend with the existing theme and tokens (ui-ux-pro-max guidance). Costs only in ₹.
7. The repository is public: no personal data, phone numbers, the owner's city or employer in code, tests, fixtures or docs. Use `+91 90000 00001`-style fake numbers in tests.
8. Your final report to the Workshop: **at most 150 words** — branch, head commit, what is done, what is not, any decision you took, any new dependency.

## Branches

`r18-i0` is the base (plan, S0 kit, this brief). The I0 agent pushes the seams to `r18-i0`; builders branch from `r18-i0` after I0 is pushed (B and D may start earlier from `r18-i0` as it is now and merge `r18-i0` again when I0 lands). Builders: `r18-a1`, `r18-a2`, `r18-b`, `r18-c`, `r18-d`, `r18-e`. The I1 join is `r18-i1`.

## Decisions fixed for the build

| Topic | Decision |
|---|---|
| Release | R18 "Calls from your laptop", `v18.0.0`; About line reads v18.0.0 |
| Rows | 387, 395, 104 (answering missed calls, **off by default**), 195–197 (laundry call template, each call after his tap), 396 (listen live, take over, tell JARVIS, hang up). 198 stays Pending |
| Route | His own SIM through Windows Phone Link (Bluetooth hands-free). The JARVIS phone app places, answers and ends calls; the call's audio reaches the laptop through Phone Link |
| Hearing | The call desk records the laptop's default speaker by WASAPI **loopback**; it sends audio to the cloud **only while the other person speaks** (voice detector) |
| Speaking | During a JARVIS call only, the call desk makes VB-CABLE's `CABLE Output` the default **and** default-communications microphone and plays JARVIS's voice into `CABLE Input`; it restores the owner's microphone afterwards, on crash (watchdog) and at next start |
| Bluetooth headset on the laptop | Phone Link refuses calls then: the desk checks before every call and the card says so |
| Speech modes | **cloud** (Google within its free allowance — already in `jarvis.voice`; Azure free tier F0 if the owner adds a key; Bhashini optional; Sarvam paid, off unless the owner turns it on with its ₹) and **laptop** (local models on the desk; text only to the cloud). The language check picks per language |
| Brain | `jarvis.llm` **fast** tier for the conversation, structured output (`say`, `action`); a language marked "needs balanced" uses balanced only if the owner allowed it. Gemini free tier is never used for calls |
| Opening line | In the call's first language: "Hello, this is JARVIS, an AI assistant calling on behalf of <first name>. This call is recorded." Pre-made per language and cached |
| Records | Audio (Opus or 16 kHz mono compressed), transcript (original + English), English summary, ₹ — encrypted in the vault, kept 30 days (setting), deleted on request; recording stops and is deleted for that call if the other person objects |
| Booking | Card fields: acceptable days/times, name and number to give, reason, "no payment". Accept only inside the limits, repeat back to confirm; after the call add a Google Calendar event through the existing calendar tool, with Undo |
| Phone menus | Key tones played into the call as sound (DTMF); spoken menus answered in words |
| Live controls | Listen live (both sides' audio + English captions) in the console and on the phone (the console page in the phone's browser is enough), Captions only, Take over (handover line, then the desk restores the owner's mic; on the phone, the app tries to route audio to the earpiece, else tells him to tap "Phone"), Tell JARVIS (silent instruction), Hang up |
| Caps | ₹200 a month for calls, ₹20 a call, 6 minutes a call (owner settings); the card shows the estimate; at a cap JARVIS says goodbye and ends |
| Limits | 10 calls a day, 2 a day per number, 3 new numbers a day, no calls 21:00–08:00 IST, no emergency (100, 101, 102, 108, 112, 1091, 1098, 181 and similar short codes), premium (1900…) or international numbers; at most one redial a day to a number that did not answer |
| Answering missed calls | Off by default; when on: after N rings (setting, default 5) and a caller policy (all / saved contacts only / everyone except saved contacts); JARVIS takes a message only, never agrees to anything |
| Cloud Run | `--max-instances 1` already: one in-memory call hub is enough. **Raise `--timeout` from 300 s to 1800 s** in `deploy/cloudrun.sh` so a call's WebSockets are not cut |

## Contracts (the I0 agent turns these into code in `src/jarvis/calls/protocol.py`, `models.py`, `ports.py`)

**Audio format everywhere:** 16 kHz, mono, signed 16-bit little-endian PCM, 20 ms frames (640 bytes), sent as binary WebSocket messages prefixed with one byte: `0x01` = the other person (desk → cloud), `0x02` = JARVIS's voice (cloud → desk), `0x03` = mixed live audio (cloud → listener).

**Desk ↔ cloud** — WebSocket `GET /api/calls/desk/ws`, authenticated like the home bridge (its signed device credentials; reuse `jarvis.homebridge` signing), one connection per desk. JSON messages `{"type": ..., ...}`:
- desk → cloud: `hello {desk_version, speech_modes: ["cloud","laptop"], local_languages: [...]}`; `state {ready: bool, problems: [str], bt_headset: bool, cable: bool, phone_link: bool}`; `vad {call_id, speaking: bool}`; `heard_text {call_id, lang, text, confidence}` (laptop speech mode only); `played {call_id, utterance_id}`; `dtmf_done {call_id, digit}`; `mic {call_id, owner_mic: bool}`; `error {call_id?, code, message}`.
- cloud → desk: `prepare {call_id, mode, languages}` (switch mic to the cable, start listening); `say_text {call_id, utterance_id, lang, text}` (laptop speech mode); `dtmf {call_id, digit}`; `stop_speaking {call_id}`; `takeover {call_id}` (restore the owner's mic, keep the loopback recording); `release {call_id}` (restore everything); `ping`.

**Phone ↔ cloud** — the R7 phone door and its existing cloud → phone channel (the D agent finds it in `jarvis.phone` / `jarvis/api/r7_wiring.py`). Commands to the phone: `call.dial {call_id, number, approval_id}`, `call.answer {call_id}`, `call.end {call_id}`, `call.route {call_id, to: "phone"|"bluetooth"}`. Events from the phone: `call.state {call_id?, state: "ringing"|"dialing"|"active"|"ended", number_e164 (incoming only, for the answering policy), rings, at}`. The phone app acts on a command only if it carries a valid cloud signature and, for `dial`, a live approval id.

**Console ↔ cloud** — REST under `/api/calls/…` (cards: create/estimate/approve/cancel; records: list/get/delete/keep; settings; language table; run the language check) and a live WebSocket `GET /api/calls/{call_id}/live` (owner session auth): server → client `caption {who, lang, text, english}`, `state {...}`, binary `0x03` audio when listening; client → server `listen {audio: bool}`, `takeover`, `tell {text}`, `hangup`.

**Ports (Protocols)** in `jarvis/calls/ports.py`:
```python
class Hearing(Protocol):
    name: str
    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Heard: ...  # Heard(lang, text, confidence, seconds)
class Voice(Protocol):
    name: str
    async def speak(self, text: str, lang: str) -> bytes: ...  # PCM16 16 kHz mono
class LanguageDetector(Protocol):
    async def detect(self, pcm16k: bytes, candidates: Sequence[str]) -> tuple[str, float]: ...
class CallStore(Protocol): ...   # cards, records, counters, settings, language results (Firestore + in-memory fake)
class DeskLink(Protocol): ...    # send(msg) / is_ready() / state()
class PhoneLink(Protocol): ...   # send(command) / last_state()
```
Language codes are BCP-47 (`en-IN`, `hi-IN`, `ml-IN`, `ta-IN`, `te-IN`, `kn-IN`, `bn-IN`, `mr-IN`, `gu-IN`, `pa-IN`, `or-IN`, `as-IN`, `ur-IN`, plus the other scheduled languages' codes).

## Who owns what (no two agents edit the same file; the I1 join wires the rest)

| Agent | Branch | Owns |
|---|---|---|
| I0 | `r18-i0` | `src/jarvis/calls/{__init__,models,protocol,ports,store,settings}.py`, the router skeleton `src/jarvis/api/calls_routes.py` (501 stubs), config keys in `config.py`, gateway tool registration for `calls.place` (R3) and `calls.answer_mode` in the registry, price entries (Azure, Sarvam) in the existing price tables, the version bump to `v18.0.0`, `deploy/cloudrun.sh --timeout 1800`, `docs/plans/r18-calls/I0-SEAMS.md` |
| A1 | `r18-a1` | `src/jarvis/calls/{cards,approvals,limits,records,retention,booking,templates,answering}.py` + their routes in `calls_routes.py` handlers module `src/jarvis/api/calls_handlers_cards.py`: card building and ₹ estimate, approval tokens bound to number + card hash (10 min, one use), passkey for never-called numbers, limits and caps, records in the vault (audio, transcripts, summary), the 30-day retention job, the calendar add with Undo, the laundry template (rows 195–197), the answering policy (row 104) |
| A2 | `r18-a2` | `src/jarvis/calls/{engine,hub,brain,guard,summary,captions,live}.py` + `src/jarvis/api/calls_ws.py`: the call state machine, the in-memory hub joining desk, phone and live listeners, the in-call brain prompt and structured output, the reply guard (no OTP/card/bank/Aadhaar/PAN digit strings unless on the card, stays within the card), language switching, takeover / tell / hang-up, the English summary, live captions, metering every ₹ |
| B | `r18-b` | `src/jarvis/calls/speech/**` (adapters: Google via `jarvis.voice`, Azure F0 over REST, Bhashini over REST, Sarvam over REST — off unless enabled; language detection; phone-line simulation 8 kHz + μ-law; pre-made lines cache) and `src/jarvis/calls/langcheck/**` + `evals/calls_language/**` (the language check of plan 5.3: test clips from FLEURS (CC BY 4.0) fetched at run time, scoring, the table) |
| C | `r18-c` | `src/jarvis/calldesk/**` (the Windows program: audio loopback + cable, default-mic switch and restore (Core Audio `IPolicyConfig` via `comtypes`, with a tested fallback), watchdog, voice detector, WebSocket client, DTMF, Bluetooth-headset check, laptop speech mode hooks) and `deploy/calldesk/**` (installer `.ps1`, hash-pinned Windows requirements, README); the kit zip served by JARVIS like the home kit |
| D | `r18-d` | `android/**` (permissions CALL_PHONE, ANSWER_PHONE_CALLS, READ_PHONE_STATE, READ_CALL_LOG only if needed; command handling; call-state events; the approval notification; Take over route attempt; app version bump) and the cloud side of the phone commands/events in `src/jarvis/phone/calls.py` |
| E | `r18-e` | the console Calls panel and call cards (`src/jarvis/web/**` or wherever the console lives: new files only, plus the smallest registration edits), Vitals' calls cost line, browser tests, screenshots in `build/r18-shots/` |

## After the builders

I1 join (`r18-i1`): merge all, wire the routes and the hub, fix integration, run the touched tests once. Then the Book: new pages for the calls modules and the call desk, the strict `pages --check` and `--narration-check` passing. Then one combined security + code review that fixes its findings and runs the one final check pass. Then the PR `v18.0.0 · R18 Calls from your laptop · Mark XXV`.
