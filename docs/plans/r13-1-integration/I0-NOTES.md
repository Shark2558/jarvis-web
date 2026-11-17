Version v13.1.1 · 17 Nov 2026, 19:10 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — I0 notes (the joins for "Try-on")

The R13.1 I0 integrator wrote these notes in the Workshop (🛠 Mark XXIII) while building I0 on `r13-1-i0`.
The plan is `docs/plans/r13-1-try-on.md` (v13.1.3, Status Ready, with plan review 1, the owner's two
answers and his scope of 17 Nov 2026). The builders' briefs are `BRIEF-COMMON.md` and `BRIEF-A.md` …
`BRIEF-D.md`, in this folder.

## 1. The base, and the owner's answers

- **Base:** `origin/main` @ `3f265cb` (R13 live as `v13.0.0`), with `r13-1-plan` fast-forwarded in.
  The clone is shallow, so the merge first said "refusing to merge unrelated histories". `git fetch
  --deepen=3` of the plan branch fixed it.
- **The owner's answers** (≈ 14:25 IST): the model is Gemini 3.1 Flash Image, processed in the United
  States (question 12). A See it on me picture is kept 30 days unless he presses Keep (question 3; the
  default had been 7). These change `tryon_keep_days` 30 (1–30), `model.PICTURE_KEEP_DAYS` and the
  Privacy row's words.
- **The owner's scope** (≈ 15:33–15:45 IST), in his words: "the see it on me is for purchasing new
  garments, But I need the 3D model to be created and within Jarvis so that whenever I ask what to
  wear, jarvis should open up the card, decide and show me on the 3D model". The plan has it as two
  decisions:
  - **D21, row 388:** the try-on card opens by itself under the answer to "what should I wear?".
  - **D22:** "See it on me" pictures him in a garment he is thinking of buying. It is paired with up to
    two of his own pieces and is never added to his wardrobe.

## 2. Stale lines and decisions taken at I0

- **Settings.** `config.py` sits at its 790-line guard. To make room:
  - `tryon_model` is a `str` with the pattern `^gemini-[a-z0-9.-]+$`, not a `Literal`. The port
    refuses a (model, location) pair it has no price for.
  - `tryon_cache` (off) is I0's addition. The deploy turns it on when Google refuses to switch its
    24-hour cache off, so that the consent words say so.
  - `_HHMM, _DAY` share one line.
- **Prices.** `global` has no price for Flash Image, so the port refuses it. Nano Banana's text price
  is an upper bound.
- **Splits for the 400-line guard:**
  - `wardrobe/tryon/http.py` became `http_figure.py` (the base and A's models) and `http_seeme.py`
    (C's), both re-exported from `http.py`.
  - The lazy provider moved from `api/r13_wiring.py` to `api/tryon_wiring.py`.
- **Morph weights.** The server computes the figure's seven morph weights (`model.morph_weights`,
  `BodyView.weights`).
  - Each of the six measurements: (v − sample) / (top − sample).
  - A waist below 82 uses `waist_down` alone: (82 − v) / 20.
- **The engine contract.** It pins the failure hooks (`GL_FAIL`: `no-webgl2`, `lost`, `asset`,
  `timeout`).
- **R7's eval reads comments.** `vision:only_the_door_asks` fails on a camera API's name even inside
  a comment, and once failed on a comment in I0's engine stub. BRIEF-B warns Part B.
- **Privacy rows and ids:**
  - The Privacy rows' order is A's three, then C's three (`kept.ROW_IDS`).
  - `PRIVACY_OWNER` names each row's part.
  - A saved comparison's id is `tc_` + 8 hex.
- **`_VisionFiles`.** Its folder argument is optional, because R7's own tests build it bare (fixed in
  `60a3e3e`).
- **The fake server does NOT enforce console-only.** The wired app at I1 tests that rule.
- **No R13 pin moved for `see_it`.** R13's tests don't pin the absence of extra result keys. The
  persona stays p13.0 (no new tool).
- **The eight tick-job pins** for `seeme_daily` are left to Part C (BRIEF-COMMON section 4).
- **Row 388 (D21):**
  - **The card.** `TryOnCard` is in `AnyCard`. At most one comes with a reply (the first look asked),
    and it counts toward the Maps / YouTube cap.
  - **Where it shows:** never on Telegram (`card_lines` ignores the kind), never in the AI's result.
    No-AI mode gets it too, because it answers with the same tool.
  - **The console.** The hook is `console-media.js`'s `cards()`. `console.js` already passes it every
    reply's cards, typed or spoken. `console.html`, `app.py`, `gateway.py` and `brain.py` are untouched.
- **The garment (D22):**
  - **Plan rows.** They keep **Show in 3D** only: `seeOn` is gone and `jarvis:tryon-open` carries
    `{plan}`.
  - **`PictureIn`** lost `plan` and takes `{garment, pieces (0–2), …}`.
  - **The fake consent template** is now `c2`.
  - **Faces.** A face in a garment photo is refused on the device, not by the server (there is no
    server code for it). This is I0's default, owner question 13 in the plan.
  - **The share tray.** It is R7 Part A's file, but I0 edited it as a seam (+3 lines): a shared picture
    gets "See it on me (a garment to buy)", and that press sends nothing.
  - **The fake server.** Its See it on me half moved to `tests/r131_fake_seeme.py`. The fake look route
    takes `?pieces=`.
- **Not test-first:** the share-tray seam's test was written beside the code, not red first.
- **A flake, not R13.1's.** `test_voice_api.py::test_the_view_is_limited_to_60_a_minute_per_owner`
  (a token-bucket timing test) failed once on 3.11 under load. It passed alone and on a re-run, and
  did not recur in the final runs.

## 3. What I0 built (the plan's seams 1–17)

The version is 13.1.0, and the keyring has 26 purposes (`tryon`, `tryon_photos`). Each seam is pinned
by `tests/test_r131_*.py`.

- **Settings and money:** ten settings; `billing/spend.py` (`with_tax`, `ensure_spend_allowed`); the
  usage label "Try-on".
- **The contract:** the two new parts in `wardrobe/ports.py`, and R13.1's types in `wardrobe/tryon/`:
  - `model.py`, `http*.py` (27 routes);
  - `ports.py`, `kept.py` (the stand-ins);
  - stub parts.
- **The provider port:** `llm/tryon.py`, and the scripted fake `tests/r131_fake_tryon.py`.
- **The wiring:** `api/r13_wiring.py` and `api/tryon_wiring.py`; the mannequin's manifest-checked
  route; empty owner-only routers.
- **The R13 fix (D20):** `actions.unready`. `lock` takes `pieces` and applies them in one change.
  Also `run_panel_tool` / `panel_reply` and `see_it`.
- **Row 388's server half (D21):** `TryOnCard`, `styling/tryon_card.py`.
- **The console:**
  - the CSP, the door's `person`, `garment`, `picture`, `garmentPhoto` and `myPhoto`, `shrink({maxKb,
    jpeg})`, `JarvisPrivacy.remove`;
  - the section's hook, the card hook, the share tray's button;
  - D's and B's stubs (`console-tryon*.js`, `console-tryon-card.js`, `console-tryon.css`).
- **The engine contract:** `tests/fixtures/r13_1/engine_contract.mjs`, with the stage page.
- **Deploy:** the Agent Platform API, the prompt-only role, the cache switch and the budget alert.
- **Guide and book:** the guide v13.1.2 (C72, C73); `arch_coverage.json`; the book's licence rows.
- **Evals and fakes:**
  - the staged runner (`STUBS_PASS = True`);
  - the built `contract` part, with row 388's case and its control;
  - the fakes and the fake server.

## 4. Sizes after I0

| File | Lines | Limit or note |
|---|---|---|
| `config.py` | 790 | the limit |
| `wardrobe/ports.py` | 394 | |
| `api/r13_wiring.py` | 384 | |
| `api/console.py` | 468 | |
| `styling/actions.py` | 214 | |
| `tryon/model.py` | 386 | |
| `tryon/http_seeme.py` | 225 | |
| `tools/reply_cards.py` | 335 | |
| `console-helpers-wardrobe.js` | 301 | |
| `console-r7-send.js` | 162 | ≤ 165 |
| `console-r111-files.js` | 331 | |
| `console-privacy.js` | 267 | |
| `console-media.js` | 411 | |
| `console-r7.js` | 93 | |
| `console-r7-share.js` | 292 | |
| `app.py` | 732 | not edited |
| `brain.py` | 713 | not edited |
| `gateway.py` | 760 | not edited |
| `console.html` | 782 | byte-identical |

## 5. For I1

1. Flip `STUBS_PASS` to False in `evals/r13_1/run.py`, and flip its pin with it.
2. Move D's and B's browser tests from the fake server to the wired app. Test console-only on every
   console route there, the garment routes included.
3. Run row 388's named test end to end: a typed and a spoken "what should I wear?" through the mock
   brain, the card under the reply, and `stats()` showing the card's pieces.
4. Check that one stage at a time holds between the section and a card.
5. In the guide, take C72 and C73 from PLANNED to built, and change C63's pixel sentence ("Three panels
   see pixels …").
6. Part C moves the eight tick pins. Check they are named in INTEGRATION-C.
7. Builders' notes:
   - Part B reads preview v2 from the main checkout's `.project-notes/scratch-in/mannequin-preview-v2/`
     (git-excluded, so it is not in a worktree) and anny from `/tmp/anny-src/anny`.
   - BRIEF-COMMON's `Claude-Session` trailer is a placeholder for the link the Workshop gives each
     builder.
8. Make one live picture only after his YES, and compare it with his Google bill. Owner question 13
   (a face in a garment photo) keeps its default unless he answers.

## 6. The checks (one at a time, behind `/tmp/jarvis-heavy.lock`), at `67077a3`

The whole unit suite was run in three parts (`--ignore` lists), each in the foreground.

| Check | Result |
|---|---|
| Python 3.12 | 5,520 + 6,307 + 6,189 = **18,016 passed**, 140 skipped, 0 failed |
| Python 3.11 | 5,521 + 6,307 + 6,189 = **18,017 passed**, 139 skipped, 0 failed |
| `ruff check` and `ruff format --check` | clean on the 63 Python files changed since `3f265cb` |
| `mypy src` | the baseline error only (`memory/redis_store.py:67`) |
| `evals/run_all_mock.py` | **ALL MOCK EVALS: PASS**; the phase0 smoke fails as usual |

The mock evals in detail:

| Suite | Passed | Its negative control |
|---|---|---|
| r13_1 | 23/23 | failed the suite, as it must (with row 388's case) |
| r13 | 110/110 | |
| r7 | 68/68 | |
| r14 | 108/108 | |

More checks:
- `scripts/check_doc_versions.py`: 30 documents OK.
- `scripts/arch_coverage.py`: OK (66 packages, 103 console modules, 114 collections).
- `python -m jarvis.buildbook.gen --check`: two builds are byte-identical.

Browser tests (Playwright venv, `JARVIS_BROWSER_TESTS=1`), run on the files the changes touch:

| Area | Files | Result |
|---|---|---|
| the share tray, R7's joins and Helpers → Wardrobe | 4 | 56 passed |
| media, the R11.1 plan cards and look | 3 | 71 passed |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 19:10 IST | R13.1 | First edition, at the end of I0: the base and the owner's answers and scope, the stale lines and I0's decisions, what I0 built (seams 1–17), sizes, the list for I1, the checks with their numbers | 🛠 Mark XXIII |
