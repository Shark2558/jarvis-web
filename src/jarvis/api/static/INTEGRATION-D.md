# R6 builder D: the Book panel and the 3D show. Notes for the integrator (I1)

Branch `r6-d` (from `r6-i0`). Plan: `docs/plans/r6-build-book.md` D8–D10 and D13–D16. D did not edit any wiring file.
The 13 assets are already in `APP_ASSETS` (I0), and `/book/show` already serves `book.html` with the console CSP.

## Files (all ASCII, no `innerHTML`/`eval`, text set with `textContent` only)
| File | Lines | What |
|---|---|---|
| `console-book.js` | 352 | Book panel: status, Open (passkey + fresh sign-in, `?reauth=done` resume), owner session (reader, older releases, code download, beat, End), settings host |
| `console-book-reader.js` | 230 | The 8 sections as lazy disclosures; Book settings form |
| `console-book.css` | 63 | Panel layout only (existing components) |
| `book.html` | 114 | Show markup: top bar, stage (canvas, labels, 2D host), captions, controls, questions, start and end cards, two dialogs |
| `book.css` | 181 | Show layout: desktop and phone, Night and Day, motion levels |
| `console-book-show.js` | 353 | Transport (`window.JarvisBook`, minimal `window.JarvisConsole.api` for JarvisPasskey), script checks, timeline, keys, captions, 60 s beat, close and wipe |
| `console-book-voice.js` | 231 | Cloud voice (Web Audio, one beat prefetched), browser voice, captions-only timing, `level()`, spoken-question recorder |
| `console-book-talk.js` | 200 | Questions, hand-back, lock screen, Resume |
| `console-book-2d.js` | 185 | 2D show (< 900 px, no WebGL2, governor retire); the 2D Core built node by node |
| `console-book-3d.js` | 299 | ES module: WebGL2 probe, three r187, palette kit, labels, governor tiers, teardown |
| `console-book-scenes.js` | 138 | Scenes 1, 2, 12, 13 (`createCore` from `console-3d-scenes.js`, unchanged) |
| `console-book-scenes-flow.js` | 158 | Scenes 3, 5, 6, 8 |
| `console-book-scenes-data.js` | 181 | Scenes 4, 7, 9, 10, 11 |

Tests: `tests/test_book_static.py` (45), `tests/browser/test_book_panel.py` (9), `test_book_show.py` (13),
`test_book_lock_ui.py` (12, which includes D's visual gate on `#p-book` and `/book/show`), and `tests/browser/book_mocks.py`
(the Contract as `page.route` stubs).

## Contract D codes against (B and C: please match it, or tell I1 what differs)
- `GET /v1/book`: the Contract fields. Sealing in progress (D7) is `reason: "sealing"` or `sealing: true`. The panel then
  says "Sealing this release…" and asks again every 8 s, up to 6 times. The sealed rows are `{id, label, sealed_at, mb}`.
  `last_closed` is `{at, minutes, questions}`.
- `POST /v1/book/open {audience, proof?}`: the proof comes from `JarvisPasskey.prove('book_open', audience)` (I0: bound
  to the audience). When `open.passkey_ready` is false, the panel sends no proof. In Google mode it expects
  `403 passkey_setup_needed` back; it never falls back to the sign-in alone. When `open.fresh_left_s <= 5`, the panel goes
  to Google first, so no passkey is spent before the sign-in. A `403 reauth_required` after the passkey does the same.
- `GET /v1/book/sections` and `GET /v1/book/releases/{rid}/sections` (●): either `{release?, sections: {8 keys}}` or the
  8 keys at the top level. Each is shaped as in `buildbook/sections.py`.
- `POST /v1/book/releases/{rid}/ticket` (●) returns `{ticket: [A-Za-z0-9_-]{8,128}, expires_in_s}`. The file then comes
  from `GET /v1/book/download/{ticket}`, fetched with `JarvisChat.raw` and no ● header. Its
  `Content-Disposition: attachment; filename="<[A-Za-z0-9._-]{1,80}>"` names the saved file.
- `GET|PUT /v1/book/settings`: keys **`creator_name`** (≤ 40), **`show_voice`** (`cloud`|`browser`), **`talk_through`**
  (bool) and **`allow_training_brain`** (bool; the panel asks before turning it on). A PUT sends a partial patch and
  expects the full settings back. **B: please use these names.**
- `GET /v1/book/show/script` (●): **`{release: {id, label, committed_at}, audience, scenes: [Scene 1–11],
  lines: {ask, anything_else, hand_back, ai_off: {id, text}}, closing: [{id, text}] (or {guest: [...], owner: [...]}),
  costs: {month_inr?, limit_inr?}, talk: {on, why}, voice: "cloud"|"browser", until}`**. Each line id is a `lines.LINES`
  key. The ask line is scene 12 (the `ai_off` line instead when `talk.on` is false). The closing lines are scene 13, in
  order. **C: please answer this shape.** It holds rendered text only: D never types a line into JS (a static test pins
  that).
- `POST /v1/book/show/speak {line_id}` (●): `line_id` is a beat id `sNNbNN`, a `LINES` key, **or a reply id
  `r_<12 hex>`**: the guarded reply is spoken by its id, and its text never goes back to the server. The answer is audio
  that Web Audio can decode (mp3, wav or ogg). A 402, a 503 or a decode error switches the show to the browser voice
  for the rest of the show.
- `POST /v1/book/show/hear` (●): the body is the raw WAV (`Content-Type: audio/wav`, 16 kHz PCM16 mono, ≤ 15 s), and the
  answer is `{text}`.
- `POST /v1/book/show/ask {text}` (●) returns `TalkReply`. `POST /v1/book/show/beat` (●) is sent every 60 s by the show,
  and also by the panel while an owner session is open there. `POST /v1/book/close` (●, no body) returns
  `{closed, wiped, notified}`.
- `POST /v1/book/resume {proof}` returns `{resumed}`. The proof is `JarvisPasskey.prove('book_resume', lockId)`.
- **Needed, not in I0's 15 routes:** the show must learn the **lock id** without a book token (another console tab, or
  the presenting tab after the close). D calls **`GET /v1/book/show/lock` (cookie only, no ●) → `{on, id: "bl_…",
  line?}`**. It passes under the lock through the `/v1/book/show/*` rule; `line` is the rendered `hand_back`, optional.
  If that route answers 404, D falls back to two calls. `GET /auth/me` answering 423 means locked. `POST
  /v1/book/resume {}` (no proof) answering `403 {error, detail, lock_id}` gives the id. **I1: provide one of the two.**
  The route is preferred; it needs `tests/test_r6_contract.py` to count 16 routes.
- A ● route answering **401** means the session has ended. The show handles it (it says so, forgets the token and clears
  the page). The panel goes through `console.js api()`, and that shows the console's sign-in gate on any 401. An owner
  whose reading session expires in the panel would therefore see the gate. The panel's beats keep a session from going
  idle, and the panel forgets the token at `until`, so this only happens in a race. The panel also accepts **410**: if
  C answers a gone session with 410 on ● routes, the gate never shows.

## Facts each scene reads (A: `book.show` scene facts; all optional, nothing is invented if missing)
`Fact {label, value, n, group, flag}`. A beat lights the facts its `focus` names: their label, value or group
(case-insensitive), or their 1-based place. A flow scene with no focus lights one step per beat.
- 1 book: the first 6 facts become tiles showing `value` (or `n`) and `label`.
- 2 layers: up to 9 plates (L1…L8, X), each `value` · `label` · `n`. `n` is the module count, drawn as ticks (≤ 60).
- 3, 5, 6 and 8 are flows of ≤ 12 steps, in order, each `label` (`value` shows on the phone). An optional `group`
  hint adds an accent: `gateway`/`guard` gets a shield, `audit` gets chain links, and `passkey` is where scene 5's
  approval card goes.
- 4 memory: facts with `group: "purpose"` are the keyring's purposes. The rest label the vault, and the vault lights when
  the focus names one of them.
- 7 home: `group` is `home` (inside the boundary), `edge` (the laptop) or anything else (outside). Only the edge links out.
- 9 stack: `group` is the role (one orbit per role, up to 6), `value` the licence, and `flag` is `copyleft` or
  `non_commercial` (amber, with the word).
- 10 costs: `n` is rupees (bars on a log scale; 0 or `flag: "free"` gives a flat bar) and `value` is the price in words.
  For the owner, `costs.month_inr` / `limit_inr` from the script add two bars.
- 11 later: `label` (≤ 40 characters shown) and the word "later".

## What I1 wires or decides
1. **The lock-id route above** (or the 403 `lock_id`) and the script shape (C). The settings key names (B).
2. `console-permissions.js` `afterReauth()` also opens Approvals on `?reauth=done`. The Book panel opens on top with the
   focus, so both work. Optional: skip Approvals when `sessionStorage['jarvis_book_pending']` is set. That is not D's
   file. D reads the original query from the navigation entry, because Permissions may already have replaced the
   address.
3. The shared gate (`tests/browser/test_ui_audit.py`) audits `#p-book` against the unwired server, where it shows the
   `book_off` sentence. D's own gate, `test_book_lock_ui.py`, audits the panel with data (status and reader open) and
   `/book/show` (start, a scene, questions, hand-back) at 1440×900 and 390×844, Night and Day, with the same
   `DOM_CHECKS_JS`. To measure the panel with data in the shared gate as well: in `ui_checks.install_mocks`, route
   `**/v1/book` to `book_mocks.status()` and add `READY["book"] = "#p-book .bk-release"`.
4. **`tests/browser/test_r6_seams.py` (I0):** `test_the_deck_boots_with_the_book_stubs_and_opens_the_book_panel` asserts
   that the console logs no errors. With D's real panel, `GET /v1/book` reaches the I0 stub, which answers
   `503 book_off`, and the browser logs that 503. B's route should answer `200 {available: false, reason}` when the book
   is off (the Contract's own fields; the panel shows `reason`). Alternatively, I1 adds `/v1/book` to the by-design
   list of `test_console.Console`. Either way the test is green again. The show page asks for the lock only in Google
   mode (it reads `/console/config`), so I0's other show seams stay green on a token-mode test server.
5. Nothing else: no new asset, no CSP change, no new setting. Spoken questions reuse `voice-capture-worklet.js`.
   Pause also holds the 3D still (WCAG 2.2.2), and the questions scene keeps the Core moving.

## Decided differently from the plan (and why)
- `book.html`'s `<main>` class is now `sh-main`, not `show`. `.show` is the console's "visible" class for `.gate`, so the
  name made the start and end cards lay out wrongly. The `#show` id is kept. `book.html` also links `console-deck.css`,
  for the existing `.wordmark`, `.k` and `.mbar`.
- Script order on `book.html`: show (the transport) comes first, then voice, 2D, talk and the 3D module. Boot waits for
  `DOMContentLoaded`.
- A jump while paused never starts playing by itself, so the closing never runs, and the session never ends, without
  Play. Jumping to Questions while paused opens the questions directly. `Q` opens the questions at any time, pausing the
  show; outside scene 12 the panel's button reads "Back to the show".
- Reduced motion (Calm/Off/`prefers-reduced-motion`) on a desktop keeps the 3D: there is no animation loop, one still
  per beat, camera cuts and no particles (D15). The 2D cards are for < 900 px, no WebGL2, a lost context or a governor
  retire.
- `engineOn` (the 3D engine's closure, 106 lines) is a factory of small functions, each ≤ 50 lines, in the same
  pattern as `console-3d.js` `createEngine`.
