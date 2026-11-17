Version v13.1.3 · 17 Nov 2026, 20:45 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — Part C: See it on me (integration notes)

Builder C (Opus), branch `r13-1-c` from `r13-1-i0` @ `eb8b7e4`. Briefs: `BRIEF-C.md` v13.1.2 and
`BRIEF-COMMON.md` v13.1.2. Plan: v13.1.3 (D10–D15, D18, D19, D22).

The first builder was stopped by a server restart at about 19:09 IST, just after it pushed v13.1.1
of this file. A second builder took over. It ticked every item of BRIEF-C against the code and the
tests, fixed what §2.1 lists, and ran every check again (§3).

## 1. The plan (written before code, first edition)

Each step was test first: the test was written, then the code.

1. **Fakes.** `tests/r131_fake_gemini.py`: Google's GenerateContent answers through
   `httpx.MockTransport`. `tests/r131_fakes_c.py`: the seeme world.
2. **The adapter**, `llm/tryon_gemini.py`.
3. **Money and the cap**, `estimate.py` and `cap.py`.
4. **His photo, the garment's photo, consent**: `vault.py`, `garments.py`, `consent.py`.
5. **The pairing**, `pair.py`.
6. **The press and pictures**: `make.py`, `pictures.py`.
7. **The join, the Privacy rows, the daily job**: `part.py`, `privacy.py`, `jobs.py`.
8. **The routes**, `api/seeme.py`.
9. **The eval**, `evals/r13_1/seeme.py`.
10. **The eight tick pins**, the review, the checks, and this file.

## 2. What C built

| File | Lines | What |
|---|---|---|
| `src/jarvis/llm/tryon_gemini.py` | 305 | `GeminiTryOn` and `build(s, tokens=, project=)` (see below) |
| `wardrobe/seeme/texts.py` | 121 | every owner-facing sentence (₹ only), and `SeeMeRefused(status, code, words)` |
| `wardrobe/seeme/vault.py` | 140 | `clean_jpeg`, `Sealer`, `PersonPhoto` (`tryon_person/{uid}`) |
| `wardrobe/seeme/garments.py` | 155 | `GarmentStore` (`tryon_garment/{uid}_{tg_id}`) |
| `wardrobe/seeme/consent.py` | 152 | his typed YES; the template hash; the card's fixed lines |
| `wardrobe/seeme/estimate.py` | 143 | the ₹ figures and their words; the estimate (`http.Estimate`) |
| `wardrobe/seeme/cap.py` | 291 | `TryonCap`: the atomic reserve, settle, release, old holds; his own settings |
| `wardrobe/seeme/pair.py` | 207 | what of his may be sent (`split`); `Pairer` (R13's engine around a transient piece) |
| `wardrobe/seeme/make.py` | 339 | `Kit`, `off_reason`, `no_ai`, `Press` (the gates, the call, the settle) |
| `wardrobe/seeme/pictures.py` | 234 | `PictureStore` (`tryon_picture/{uid}_{tp_id}`), `OnceCache` |
| `wardrobe/seeme/privacy.py` | 120 | the three Privacy rows |
| `wardrobe/seeme/jobs.py` | 98 | `seeme_daily` |
| `wardrobe/seeme/part.py` | 272 | `SeeMeService` (also the `SeeMeErase`) and `build(ctx)` |
| `src/jarvis/api/seeme.py` | 394 | the 16 `seeme` rows of `http.ROUTES` |
| `evals/r13_1/seeme.py` | 387 | 13 cases × 2 providers, 6 controls; `BUILT = True` |
| `tests/test_r131_c_*.py` (9 files) | — | 163 tests |
| `tests/r131_fake_gemini.py`, `tests/r131_fakes_c.py` | — | the fakes (unique names); the eval's providers, `SlowProvider` and `grab_logs` live in `r131_fakes_c.py` |

### 2.1 What the second builder fixed (each test first, seen red)

1. **A made picture could be lost** (HIGH). The press read the list beside a picture ("not in the
   picture") outside its `try/finally`. That list costs a storage read for each piece. A failure
   there, after Google had made and billed the picture, lost the picture and left the hold
   neither settled nor released.
   - Now the list is best effort: nothing when it can't be read.
   - The picture's record is built inside the `try`, so the cap and his month always hear it.
   - Test: `test_a_made_picture_is_kept_and_settled_when_the_rest_of_the_look_cant_be_read`.
2. **A repeat answered a code outside the contract** (MEDIUM). A repeated request id whose first
   answer was "maybe billed" answered `503 maybe_billed`. That code is not in `http.SEEME_ERRORS`,
   and the first answer had been `provider_unavailable`.
   - Now a repeat answers the first status and code. That includes a hold `seeme_daily` settled.
   - Test: `test_a_repeated_maybe_billed_request_id_answers_the_same_code`.
3. **Ids by `fullmatch`** (LOW). `tg_` and `tp_` ids were checked with `re.match` against `^…$`.
   Python's `$` also matches before a trailing newline (a `%0A` in the path).
   - Now no document path is built from such an id.
   - Test: `test_an_id_with_a_trailing_newline_never_reaches_a_path`.
4. **The eval** was 463 lines, over the 400-line rule. It is now 387: its reusable fakes moved to
   C's own `tests/r131_fakes_c.py`. Three cases now hold what BRIEF-C §4 says:
   - `billed_or_not` releases on every non-200 (400, 403, 404, 429, 500, 503), not only 500;
   - `d22_the_garment_and_never_his` takes R13's `rev` before an upload, so the upload is covered;
   - the pairing check also refuses one of his pieces in the garment's own slot.

### The adapter

`llm/tryon_gemini.py` is plain REST (httpx) to GenerateContent at
`https://aiplatform.{us|eu}.rep.googleapis.com/v1/projects/{p}/locations/{loc}/publishers/google/models/{model}:generateContent`.

- **The token.** It uses a bearer token from `tokens.headers()`. On a 401 it calls `invalidate()`.
  It never uses an API key, an SDK, or the Developer API.
- **The body.** One `user` turn: his photo, then the new garment's photo, then his crops (all as
  `inlineData`). Then one text part from fixed words only (`WORDS` = `^[a-z][a-z ]{0,59}$`,
  checked before anything leaves). Then `generationConfig {responseModalities: ["IMAGE"],
  maxOutputTokens: 8192}`.
- **The answer.** It takes the first `inlineData` part that is not a "thought". That part must be a
  JPEG or PNG by its magic bytes and at most 16 MB. Text parts are never read.
  - `usageMetadata` becomes `TryOnUsage`. If there is no per-modality breakdown, every output token
    counts at the image price (the safe side).
  - A `blockReason`, or a finish without an image, is `blocked`, as a fixed word.
- **Billed or not.**
  - `TryOnNotBilled`: any non-200, no project, no token, or a connection refused.
  - `TryOnMaybeBilled`: a timeout after sending, or a cut 200.
- **Logs** hold class names and statuses only.

### The service, the routes, the join

- **`SeeMeService`.** Its methods: `save_photo`, `photo`, `delete_photo`, `give_consent`,
  `add_garment`, `garments`, `garment_photo`, `delete_garment`, `pair`, `estimate`, `press`,
  `picture`, `keep`, `delete_picture`, `overview`, `settings`, `erase`.
- **The routes** call it. Console rows check `auth.session_email` FIRST, before any body is read.
  Then come the limits: 30 changes, 60 reads, 6 presses a minute. Every refusal is `Refusal`, sent
  `no-store`. Images go out with `http.PICTURE_HEADERS`. Owner changes are audited by ids with
  `record_change`.
- **The join.** `build(ctx)` returns `WardrobePart("seeme", daily_jobs=(seeme_daily,),
  privacy=(tryon_photo, tryon_pictures, tryon_spend), services={"seeme": SeeMeService})`.
  - Without a token key: the job only, and I0's stand-ins.
  - Without storage: nothing.

### The ₹ figures the code shows

All at ₹95.24 a dollar with 18 % GST, for `gemini-3.1-flash-image` in `us`:

| Figure | ₹ |
|---|---|
| Typical (the new garment and one of his), rounded up to 10 paise | **8.9** |
| Typical at ₹96.10 a dollar | 9.0 (so `price_changed`) |
| Hold (three garments, `maxOutputTokens`), to the paise | **11.22** |
| Settle from Google's usage (3,510 tokens in, 1,120 image tokens out) | **8.52** |
| Settle without usage | 11.22 |

- **The confirm sentence:** "Make 1 picture of you in a new navy shirt, with your charcoal
  trousers? About ₹9 with GST. ₹0 of ₹300 used this month."
- **The cap's words:** "This month's try-on limit of ₹300 is used: ₹289.7 spent. It resets on
  1 Dec, or raise it in Try-on settings." The 34th picture fits and the 35th is refused.

## 3. The checks, with their numbers

All checks ran again at `2286c66`, after §2.1's fixes; the heavy ones behind
`/tmp/jarvis-heavy.lock`. (The first builder's numbers at `3b75cf4` were 160 tests and 183 with
I0's; its other results were the same as below.)

| Check | Result |
|---|---|
| `tests/test_r131_c_*.py` | **163 passed** on Python 3.11 and 3.12: gemini 44, press 27, cap 26, photos 20, consent 14, part 10, pair 9, jobs 7, api 6 |
| The same, plus I0's `test_r131_port.py`, `test_r131_fakes.py` and `test_r131_spend.py` | **186 passed** on 3.11 and on 3.12 |
| Coverage (3.12): `wardrobe/seeme`, `api/seeme.py`, `llm/tryon_gemini.py` | **94 %** (1,782 statements, 112 missed); every module ≥ 89 % |
| `test_r131_seams.py`, `test_r131_wiring.py`, `test_r13_seams.py`, `test_r13_wiring.py`, and the four files of the tick pins (§5) | **642 passed, 2 failed** on 3.11 and on 3.12. Both failures are I0's "not built yet" pins in `test_r131_wiring.py` (§6.1); the eight tick pins pass |
| `evals/r13_1/run.py --mock --part seeme` | **26/26 passed**; the control failed the part: True (12 cases red, listed below) |
| `evals/r13_1/run.py --mock` (every part) | **48/48 passed**; the negative control failed the suite: True |
| `ruff check` and `ruff format --check` on Part C's 27 files | clean |
| `mypy` on C's modules, and `mypy src` | the baseline error only (`memory/redis_store.py:67`) |
| `scripts/arch_coverage.py` | OK (66 packages, 103 console modules, 119 collections) |
| `scripts/check_doc_versions.py` | 30 documents OK |
| Function and module size (by the AST) | every function ≤ 33 lines; every module ≤ 400 (the largest `api/seeme.py`, 394; the eval 387) |

- **The eval's controls.** Each control turns its own case red on BOTH providers (12 cases red):
  - a read-then-write reserve (`ten_at_once`);
  - the consent check off (`no_call_without_yes`);
  - the private check moved to the console (`private_and_no_front_refused`);
  - the ₹ hashed into the consent (`moved_rate_keeps_consent`);
  - the garment added to the wardrobe (`d22_the_garment_and_never_his`);
  - AVT-12's own (M8): the pieces from the look (`avt12_the_exact_pieces`).

  With the controls removed, all 26 cases pass again.
- **Not run:** the whole unit suite (I1 runs it) and browser tests (Part C has none).

## 4. Deviations from the plan and the brief, and why

1. **His own settings live in `tryon_spend/{uid}_prefs`.** These are the switch, his cap and his
   keep days: `{owner, on, cap_inr, keep_days, updated_at}`, numbers and a flag. The data model
   names no collection for them.
   - They sit beside the spend so that deleting his photo, or OPS-05, never resets a cap he
     lowered. A reset would be a silent raise. An unreadable settings document fails closed.
   - `TryonCap.months` lists only `_YYYY-MM` ids, and `seeme_daily` never prunes this document.
   - I0's `tryon_spend` stand-in counts it as one more document.
2. **The hold is always the worst case for three garments** (₹11.22), whatever is sent. That is the
   plan's figure and the eval's. The typical is for 1 + his pieces.
3. **The sentence's ₹ is a whole rupee, rounded up.** "About ₹9 with GST" is shown for a typical of
   ₹8.9 (or ₹8.52). `Estimate.typical_inr` itself is to 10 paise, and `inr_shown` is checked
   against that figure.
4. **A blocked 200 is settled at the hold, even when Google sends usage** (the brief's rule). A
   timeout after sending, a cut 200, or any other error from the provider is kept at the hold too.
   All of these answer `503 provider_unavailable`, saying "It may still be charged (about ₹9)". A
   blocked 200 answers `502 blocked` with its ₹ note.
5. **Refusal codes beyond `http.SEEME_ERRORS`** (the `Refusal` model accepts them):
   - `cap_unreadable` (503): the cap or his overall limit can't be read. Fail closed.
   - `gone` (404): a picture that isn't there.
   - `invalid` (422): a body that isn't the model.
   - `unavailable` (503): storage down.
   - `rate_limited` (429): R13's limiter.
6. **The JSON bodies of the console routes are read inside the handler, after the console check.**
   This covers consent, pictures, keep and settings. A script gets 403 before it learns the shape,
   and a malformed body gets a `Refusal` (422 `invalid`) instead of FastAPI's list.
7. **The end-date notice is computed when the panel is read**, from `tryon_model_retires` and the
   clock, on his IST day. `seeme_daily` doesn't write it: there is nothing to store, and the result
   is the same.
8. **What a picture document keeps.** The picture's bytes are sealed (`tryon_photos`,
   `aad_picture`). Its other fields are plain: ids, numbers, and FIXED words (type and colour only;
   never a label, a private piece or Google's text). A second sealed blob would push a 700 KB
   picture past Firestore's 1 MiB document.
9. **"Shown once" means the server's memory.** A picture over 700 KB goes into `OnceCache`, which
   holds at most two, for 10 minutes. A restart or rollout loses it.
10. **How his front crop is found.** C reads the plain `owner`, `piece` and `view` fields of R13's
    `wardrobe_photo/{uid}_{photo}` (a read, no write), because the `PhotoVault` port only opens
    bytes. `tests/test_r131_c_api.py` proves this on R13's REAL catalog (its store, its sealed crops
    and their view records). I1 may prefer a port method (§6.4).
11. **`seeme_daily` is offered without a token key.** It forgets by path, so it rides every morning
    tick (§5).
12. **The 20-garment limit is a query, then a write.** It is not one transaction, so two uploads at
    the very same moment could keep 21. LOW.
13. **The order of photo and YES is the console's.** Consent may be given before his photo is kept.
    Deleting the photo always deletes the YES, in the same write.
14. **Audit.** The press (made or not), consent, photo, garment and settings each make one
    `record_change` line, with ids only.
15. **Not strictly test-first in places.**
    - The press, pictures, part and jobs tests were written before their code, but first run after
      it (before the code they could only fail at import).
    - The deadline test (§7) was written after its change.
    - The adapter, cap, photos, consent, pairing and routes tests were run red first.
    - The eval's controls prove the guards bite.
    - §2.1's three tests were run red first, each for its own reason.
16. **The list beside a picture is best effort** (§2.1.1). This is the rest of the look, shown as
    "not in the picture". When it can't be read, the picture is still shown and kept, with an
    empty `not_sent`. `sent` is always exact.
17. **Two edges at his month's end** (LOW, accepted). The cap's `done` and `holds` live in his IST
    month's own document.
    - A repeated request id from the old month is not found after midnight on the 1st.
    - A hold from the old month's last seconds does not make the new month's press `busy`.
    - Both need a retry or a second press within seconds of midnight on the 1st. The console
      sends a fresh request id for each confirm.

## 5. The eight tick-job pins moved (the one exception, BRIEF-COMMON section 4)

`seeme_daily` rides the morning tick after `laundry_daily` (in `PARTS` order), key or no key. All
eight pins were seen red first (7 tests), then green (64 passed).

| File | Where | What moved |
|---|---|---|
| `test_r11_wiring.py` | `names[-8:-4]` | → `names[-9:-5]` |
| `test_r11_wiring.py` | `names[-4:]` | → `names[-5:]`, with `seeme_daily` |
| `test_r2_wiring.py` | the key-off list | `seeme_daily` added |
| `test_r2_wiring.py` | `r13` | `+= ["seeme_daily"]` |
| `test_r4_wiring.py` | `R11_JOBS` | `+= ("seeme_daily",)` (its three pins) |
| `test_r51_wiring.py` | the list | `seeme_daily` added |

## 6. Needs I1 (exact diffs)

1. **`tests/test_r131_wiring.py`** (I0's file, not edited here). Two pins say the seeme stub is
   "not built yet". Part C is built, and in those key-off contexts it says
   `"off: See it on me needs JARVIS's token key, which isn't set up on this server."`.

   ```diff
   @@ def test_six_parts_build_through_the_real_modules_and_the_two_stubs_say_not_built
   -    assert parts["tryon"].ready == parts["seeme"].ready == NOT_BUILT
   +    assert parts["tryon"].ready == NOT_BUILT  # (A's own line at I1)
   +    assert parts["seeme"].ready.startswith("off: ")  # built; no token key in this context
   @@ async def test_the_app_builds_six_parts_and_v1_r13_lists_them
   -        assert body["parts"][-1] == {"part": "seeme", "ready": NOT_BUILT}
   +        assert body["parts"][-1]["part"] == "seeme" and body["parts"][-1]["ready"] != NOT_BUILT
   ```

2. **The consent's claim about the cache** (`config.py`, I0's; MEDIUM).
   - When `tryon_cache` is false (the default), the consent says Google's cache is switched off.
   - The deploy sets false only when its PATCH succeeded. Pictures switched on any other way (an
     env file, a manual service update) would make that claim without proof.
   - Proposal: fail toward disclosure. The deploy line already passes
     `JARVIS_TRYON_CACHE=${TRYON_CACHE}` explicitly, so the deploy is unchanged.

   ```diff
   -    tryon_cache: bool = Field(default=False, description="Google kept its 24-hour cache")
   +    tryon_cache: bool = Field(default=True, description="Google may keep its 24-hour cache")
   ```

3. **Vitals against the cap.** `Billing.record(uid, "tryon", usd)` adds the pre-GST ₹ (usd × the
   rate) to his month, like every brain; the cap counts GST.
   - So Vitals' "Try-on" line reads about ₹7.2 where the panel says ₹8.52.
   - I1's call: leave it (it is consistent with every other Vitals line), or say "before GST" in the
     label.
4. **Optional: a port method for a photo's view.** `PhotoVault.view_of(uid, photo) -> View | None`
   in `wardrobe/ports.py` and R13's catalog. C would then stop reading `wardrobe_photo` fields
   (§4.10). Not needed for R13.1.
5. **D's console.**
   - The extra codes of §4.5.
   - `Estimate.not_sent` and `PictureView.not_sent` hold the rest of the look around the garment:
     his unticked offers (`unticked`); shoes, belt, watch and socks (`not_a_garment`, with a
     thumbnail id); a private slot as "Base layer (covered)", with no id.
   - `Pairing.not_sent` is the same list.
   - `SeeMeView.typical_inr` is for the new garment and one of his.
6. **The wired app.**
   - C reads `app.state.billing` and `app.state.brain_mode` through `ctx.state`, late. Missing ones
     fail closed: no billing is 503 `cap_unreadable`; no brain mode is 503 `no_ai`.
   - Run AVT-12 (row 363) on the wired app, signed in, as D's browser test.
   - A's `erase_all` reaches C through `tryon.ports.seeme_service(ctx).erase(uid)`. It removes the
     pictures, the garment photos, his photo and his YES, in that order. It never removes the
     spend, and it touches no R13 document (tested).
7. **The needles suite.** C's plain fields are listed in §4.8. His photo, the pictures, the garment
   photos and the consent record are sealed.
8. **The deploy:** see §7, notes (a) and (b).
9. **One live picture after his YES** (the plan's exit check 7). Compare its `usageMetadata` and the
   ₹ settled with his Google bill.
10. **The consent's hash and Google's cache** (MEDIUM; found by the second builder). The hash covers
    exactly what BRIEF-C and D11 name: the template's version, provider, model, location and
    location words. It does not cover `tryon_cache`.
    - The problem: he may type YES under "Google's own short-term cache of requests is switched
      off". If the deploy later sets `JARVIS_TRYON_CACHE=true` (its cache PATCH failed), his
      consent stays current, but the words now say Google may keep each request for up to 24
      hours. That is a change in what Google keeps, made without a new YES.
    - Not changed here, because the brief names the hash's inputs. I1's call. Proposal (C's
      `consent.py`, plus its callers in `make.py` and `consent.py`, and the eval's `_priced_text`
      control taking `**kw`):

    ```diff
    -def template_text(desc: TryOnDescription) -> str:
    +def template_text(desc: TryOnDescription, *, cache: bool) -> str:
         fixed = {"version": VERSION, "provider": desc.provider, "model": desc.model,
    -             "location": desc.location, "location_words": desc.location_words}  # fmt: skip
    +             "location": desc.location, "location_words": desc.location_words,
    +             "cache": cache}  # fmt: skip
    -def digest(desc: TryOnDescription) -> str:
    -    return hashlib.sha256(template_text(desc).encode()).hexdigest()
    +def digest(desc: TryOnDescription, *, cache: bool) -> str:
    +    return hashlib.sha256(template_text(desc, cache=cache).encode()).hexdigest()
    ```

    `Consent.current(uid, desc)` then takes `cache=`, and `Press._on` passes
    `cache=self.kit.ctx.s.tryon_cache`. Add a test: cache off, then on, asks for his YES again.

## 7. The review

The brief requires `security-reviewer`, `code-reviewer` and `python-reviewer`. Neither builder had
an agent tool to start them in a fresh context. So the review below is C's own pass, written to
their checklists. **I1 or the Workshop should run the three agents on `r13-1-c` before the merge.**

The second builder read every C module and test again, in a context of its own, against BRIEF-C
item by item. It found §2.1's four items and §6.10, and fixed the four. Its findings, by
severity:

- **HIGH:** §2.1.1, a made picture lost (fixed).
- **MEDIUM:** §2.1.2, a repeat's code (fixed); §6.10, the consent's hash and the cache (for I1).
- **LOW:** §2.1.3, ids by `fullmatch` (fixed); §4.17, the month's end (accepted); the 20-garment
  limit, a query and then a write (§4.12, accepted).
- **Checked and holding:** R13's backup file reads only R13's own catalog store and photo vault,
  never C's collections. The 400-line eval was the only module over its limit.

### Security (consent, money, his photo, the adapter)

- **Consent.**
  - Console only.
  - Exactly `YES`; "yes", "Yes", "YES!", "ＹＥＳ" are refused and nothing is written.
  - The hash covers version, provider, model, location and its words. It never includes the ₹ or
    the cap: tested both ways, and the eval's control proves it.
  - Withdraw deletes his photo and his YES in one write.
- **Money.**
  - The gates run in order, each before any spend.
  - `confirm_cost`.
  - The fresh price, within ₹0.01 of what he was shown.
  - His overall limit, checked on the hold, fail closed.
  - The cap's reserve, in ONE transaction. 10 at once reserve exactly one.
  - A repeated request id answers its first outcome and is never charged twice.
  - Released only on "not billed".
  - Old holds are settled at their hold.
  - **Found and fixed:** a provider that ignores `timeout_s` is now cut at 125 s and kept at the
    hold (tested).
- **His photo and the garment's photo.**
  - JPEG only, ≤ 700 KB, ≤ 1,568 px, sanitised (EXIF, GPS and comments dropped; never decoded).
  - Sealed, with the owner in the AAD (a moved document won't open).
  - Read back by his console only, with `default-src 'none'`, `nosniff` and CORP.
  - Exported as when and how big only.
  - Never in a tool result, the Vault or a log.
- **Untrusted content.**
  - A garment photo's bytes are the only thing taken from it. Text drawn into its bytes shows up
    nowhere else (eval).
  - Google's text parts are never read: not in a log, the reply or a document (tests and eval).
  - The prompt is fixed words under a pattern checked before sending.
- **The adapter.**
  - No SDK, no API key, never the Developer API.
  - Redirects are never followed (tested on a 302).
  - Logs carry no token, body, byte, text part or project (tested with needles).
- **Authorisation.**
  - Every path uses the signed-in owner's uid.
  - `tg_` and `tp_` ids are checked by pattern before a path is built.
  - Every read checks the plain `owner` field.
  - CSRF comes from `require_auth` on the router.
- **Accepted, LOW.**
  - httpx reads Google's answer whole before its size is checked. It comes over TLS from Google;
    the picture is capped at 16 MB.
  - The shown-once memory holds at most two pictures (≤ 32 MB) for 10 minutes.
  - A settle from usage can pass the hold if Google bills more than 1,120 tokens an input image.
    It is recorded as billed, and the `jarvis-tryon` budget alert is the outside brake.

### The deploy's R13.1 block (`deploy/cloudrun.sh`, I0's)

**It holds.**

- The Agent Platform API is switched on, with a note when refused.
- A custom role, `jarvisTryOn`, has only `aiplatform.endpoints.predict` and is bound to
  `jarvis-run`. `roles/aiplatform.user` is the fallback, with a note.
- `JARVIS_TRYON_PICTURES=true` is set only when the API and a role worked.
- The cache PATCH gets the token on stdin only (`--config -`): never on a command line, never
  printed.
- A failed PATCH sets `JARVIS_TRYON_CACHE=true`, so the consent says "up to 24 hours" (it fails
  toward disclosure).
- The `jarvis-tryon` budget alert sits at the cap.
- Nothing is called or charged by the deploy.

Three notes:

- **(a) MEDIUM, the comment overstates.** `aiplatform.endpoints.predict` on the project lets the
  server prompt ANY Agent Platform model, including paid text models, not only the image model. So
  "the server can't start other paid models" is too strong. JARVIS's own cap and the budget alert
  are the brakes. Proposal: "can only make prompt requests (to any model); the jarvis-tryon budget
  alert watches the bill".
- **(b) LOW, an existing role is reused unchecked.** `describe || create` reuses an existing
  `jarvisTryOn` without checking its permissions. Proposal:
  `gcloud iam roles update jarvisTryOn --project "$PROJECT" --permissions=aiplatform.endpoints.predict --quiet`
  after a successful describe.
- **(c) Not verifiable here.** C couldn't check whether the project-level `cacheConfig` PATCHed on
  the global host covers requests to the `us` multi-region endpoint.

### Quality

- Functions ≤ 33 lines; modules ≤ 400; no deep nesting.
- Frozen dataclasses and pydantic models.
- Errors are handled explicitly (no bare 500s).
- I0's static tests hold: no real clock under `wardrobe/seeme` or `llm/tryon_gemini.py`, and no
  dollar figure in an owner-facing string.
- One flaky test found and fixed: two garments with the same fixed time were ordered by random ids.
  The test now moves the clock, and the sort breaks ties by id.

## 8. M5: the names checked against Google's own definitions

Google's documentation hosts (`cloud.google.com`, `docs.cloud.google.com`) are refused by this
workspace's proxy (403). So the names were checked in Google's own published API types instead:
`google-cloud-aiplatform` 2.9.0 from PyPI, read as files and never imported. The REST JSON name is
the proto field in lowerCamelCase.

- **`aiplatform_v1/types/content.py`:**
  - `GenerationConfig.response_modalities` (`Modality.IMAGE = 2`) is `responseModalities`.
  - `GenerationConfig.max_output_tokens` is `maxOutputTokens`.
  - `Part.inline_data` (`Blob.mime_type`, `data`) is `inlineData`.
  - `Part.thought` is a field of its own.
  - `Candidate.finish_reason` is `finishReason`.
- **`aiplatform_v1/types/prediction_service.py`:**
  - `PromptFeedback.block_reason` is `blockReason`.
  - `UsageMetadata` has `promptTokenCount`, `candidatesTokenCount`, `thoughtsTokenCount` and
    `candidatesTokensDetails` (`modality`, `tokenCount`).

## 9. What could not be verified here

- **The real call.** No call reached Google. A paid call needs his typed YES; it is the pilot's
  picture at I1. Still unknown:
  - the call's answer, latency and billed thinking tokens;
  - whether Google bills 1,120 tokens for a 1,568 px photo;
  - how it keeps his likeness, and how a shop photo dresses him.
- **The live docs page.** Whether the Agent Platform's live reference page matches the 2.9.0 types
  (§8).
- **The role and the cache.**
  - Whether `aiplatform.endpoints.predict` is enough for `generateContent` in his project.
  - Whether `cacheConfig` covers the `us` endpoint.
- **Money.** Google's INR price and the GST on his invoice: JARVIS's ₹ is an estimate.
- **Firestore.** The documents' real sizes there. The arithmetic says a 740 KB photo seals to about
  0.99 MB, under 1 MiB.
- **The wired app.** C's tests run on R13's real catalog and styling in a bare app, not in
  `create_app`: that is I1's (§6.6).
- **The review agents** (§7).

## 10. Fix (review C-1)

The fixer for review C-1 (`REVIEW-C-1.md` v13.1.1: 1 HIGH, 2 MEDIUM, 9 LOW) worked on `r13-1-c`
from `8bd4a2a`. Every fix was written test first: the failing test was run and seen red for the
reason the review gives, then the code was fixed, then the test passed. Each fix was then
committed and pushed. No call reached Google, and nothing outside `jarvis.llm` imports a vendor
SDK. This section supersedes §6.10, §7's accepted LOW on Google's answer being read whole, and the
parts of §2 and §4 that it names.

### 10.1 What was fixed

| Finding | Outcome | Commit |
|---|---|---|
| **1 HIGH**: his T-shirts can never be sent | **Fixed.** C sends its own fixed words (`pair.prompt_words`: the colour and the type, `_` as a space, so "grey t shirt"). `mine_words` stays for what he reads ("grey T-shirt"). Words JARVIS can't send are refused before the reserve (422 `not_a_garment`, `NO_WORDS`), never blamed on Google. The scripted fake now checks a request as the adapter does (`StrictTryOn` in `r131_fakes_c.py` runs `tryon_gemini._check`). It is the default for C's tests, the routes test and the eval's one-garment runs | `1b5760c` |
| **2 MEDIUM**: the consent is not bound to the cache or to the words he read | **Fixed**, as the review's diff, with one addition: `give` refuses a YES under any other version. The hash covers the version, provider, model, location and location words, the cache setting and every line he is shown. `ConsentView.version` is `"c2-"` plus 12 hex of the hash (15 characters; `ConsentIn` takes 20; no contract change). `current` and the press pass `cache=tryon_cache`. The record also keeps `cache` | `4164611` |
| **3 MEDIUM**: a press in flight outlives OPS-05 and his withdrawal | **Fixed**, and closed further than the review asked (§10.2) | `87a41a5` |
| 4 LOW: `done` pruned by a map's order | **Fixed.** An explicit `done_order` list; on a key-sorted store, a retry is never charged twice | `36dda56` |
| 5 LOW: a failed release or settle is never retried and skips his month | **Fixed** (§10.2), plus a double count this fix itself could have caused, found in the self-review and fixed (`fc00fda`) | `74304fe`, `fc00fda` |
| 6 LOW: two sources for the end date | **Fixed.** The gate, the notice and `ProviderView.retires_on` read the model's own date (`describe().retires_on`). Part C no longer reads `tryon_model_retires` (§10.4 b) | `a0521b8` |
| 7 LOW: the device check of a photo rests on the console | **Not done:** it is a contract change (§10.4 f) | — |
| 8 LOW: the audit can't tell made, released and maybe-billed apart | **Fixed.** The press's args gain `code` (`made` or the refusal's code) and `inr` (what it added to his spend). Keep and a picture's delete are audited by ids. The risk level stays I1's call (§10.4 g) | `634ca27` |
| 9 LOW: silent fallbacks; a provider bug charged as maybe billed | **Fixed.** `TryOnMaybeBilled` and a timeout are maybe billed (WARNING). Any other error is a provider bug, logged at ERROR with the request id and still kept at the hold. Three fallbacks are now logged (his limit's room, a garment record, a consent record that won't parse). A failing route logs its name and the press's request id | `634ca27` |
| 10 LOW: Google's answer read whole before its size check | **Fixed.** The answer is streamed and read only up to `ANSWER_BODY_MAX` (16 MB in base64 plus its JSON, about 23 MB). Past that it is `TryOnMaybeBilled("too_large")`. A refusal's body is never read | `ab86c1b` |
| 11 LOW: wrong or missing words | **Fixed.** `pair.refusal` says `SAME_SLOT` for a garment slot already taken and `NOT_HIS` for a piece not his; `NotSent.why` is unchanged. `PHOTO_KEPT`, `CONSENT_GIVEN` and `UNTICKED` are removed. `NOT_KEPT` is D's wording for a shown-once picture (§10.4 e) | `d8ef5f4` |
| 12 LOW: gaps in the money tests | **Fixed.** Every test the review lists now exists (§10.3) | (with each fix) |

### 10.2 How findings 3 and 5 were closed, and where this differs from the review

- **Finding 3: a press in flight.**
  - After the call, his photo and his YES are checked again (still current, with the cache).
  - `PictureStore.save(needs=…)` then checks his photo, his YES **and the garment's photo**, and
    writes the picture in ONE transaction.
  - `erase` and the pictures row's delete then **sweep once more** (`PictureStore.delete_all`).
  - Together these leave no ordering in which a picture survives:
    - a press that commits before the delete's batch is found by the sweep;
    - a press that commits after the delete's batch finds his photo gone and writes nothing.

    The re-check alone would have left a window between the check and the write.
  - The garment's photo is in `needs` so that a press during the **pictures row's** delete (which
    takes the garment photos, not his photo) keeps nothing either.
  - A picture too big to keep is put in page memory, then checked, and dropped when a photo went.
  - His withdrawal (`delete_photo`, and the photo row's delete) clears page memory.
  - When a photo went during the call:
    - nothing is kept;
    - he reads 422 `no_photo`: "Your photo or the garment's photo was deleted while the picture
      was being made, so it isn't kept. It may still be charged (about ₹9).";
    - `done` says `withdrawn`, so a repeat answers the same.
  - "Release the hold" is done as **closing** it at what Google made: settled from its usage,
    not given back. Google made the picture, and a 200 is billed. It also counts in `pictures`
    and in his usage month.
- **Finding 5: a failed release or settle.**
  - `TryonCap` tries a settle or a release three times, waiting 0.05 s and then 0.25 s
    (`CLOSE_WAITS_S`).
  - One that still fails is logged at ERROR with its request id and kept in `TryonCap.pending`.
    `pending` is this process's memory; nothing else is written while the store is failing.
  - His next reserve and `seeme_daily` close a kept one first, **as it was meant**: a release
    stays a release, and `settle_old` skips a hold whose close is pending. So a retry of the same
    request id is answered from `done`, and the next press is not `busy`.
  - A restart loses `pending`. The daily job then settles the hold at its hold, as it does after
    a crash (accepted in §7).
  - The press closes through `_closed`, which never raises after the cap's tries, and records his
    usage month in its own `finally`. So:
    - a made picture is shown, never "can't be reached";
    - a blocked or maybe-billed press keeps its words;
    - a not-billed one keeps "Nothing was charged".

    The review suggested MAYBE_BILLED's words for the last case. They say "Google didn't answer in
    time", which is wrong after a 429, and Google billed nothing.
  - **The choice for `settle_old`, pinned by a test:** it records nothing in his usage month. The
    press records every billed call whatever its settle did, so only a crash during the call is
    left out. Recording again would count a press whose settle failed twice.
  - **Found in the self-review:** with retries, a commit whose reply was lost would be retried,
    adding `pictures` or `blocked` a second time. These counters now move only while the hold is
    still held, as the spend already did (`fc00fda`).

### 10.3 The tests, and what was not red first

- **New files:**
  - `test_r131_c_inflight.py` (10): erase, his withdrawal, the photo row and the pictures row,
    each during a press held at a gate; a big picture in flight; withdrawal clearing page memory;
    a picture saved between erase's list and its delete.
  - `test_r131_c_money.py` (13): blips on close, kept closes, a 429 and a made picture whose
    close fails, a lost reply, and the pins below.
  - `test_r131_c_review.py` (10): the T-shirt on the adapter and on the strict fake, words
    refused before the reserve, the cache turned on after his YES, the two end-date cases, the
    refused-piece words, the provider bug and the fallback logs.
- **Added to existing files:**
  - `test_r131_c_pair.py`: every sendable type × every colour (and none) through
    `tryon_gemini._check`; every `NEW_TYPES` × colour through `short_words`; the strict fake.
  - `test_r131_c_consent.py`: rewritten for the binding. Ten changes each ask again; the same
    inputs and a moved rate don't.
  - `test_r131_c_cap.py`: the key-sorted store.
  - `test_r131_c_gemini.py`: the byte cap; a refusal's body is never read.
  - `test_r131_c_api.py`: the press, Keep and delete audits; a failing route's log.
- **Pins, green from the start** (the behaviour already held; written because the review asked
  for them):
  - the worst case recorded on a blocked and a maybe-billed press;
  - nothing recorded on a release;
  - nothing recorded by `settle_old`;
  - a maybe-billed call logged as a WARNING, never as a provider bug.
- **Not a behaviour change:** four of the review's own tests moved from `test_r131_c_press.py`
  (it had passed 400 lines) into `test_r131_c_review.py`, unchanged.

### 10.4 Needs I1 (new, or changed by this fix)

- **a. I0's fake server answers the old consent version.** `tests/r131_fake_seeme.py` pins
  `CONSENT_VERSION = "c2"`. The real version is now `"c2-"` plus 12 hex. D's console must send
  back `ConsentView.version` as it was shown, never a literal. Proposal, so that D's browser tests
  see the real shape:

  ```diff
  -CONSENT_VERSION = "c2"
  +CONSENT_VERSION = "c2-0123456789ab"  # the real one: "c2-" + 12 hex (seeme.consent.shown_version)
  ```

- **b. `tryon_model_retires` is no longer read by Part C** (finding 6). Either drop it from
  `config.py` with its two pins in `test_r131_seams.py`, or make it a per-model override. A single
  date is what caused the finding.
- **c. One rule for fixed words.** `pair.PROMPT_WORDS` is a copy of the adapter's `WORDS`,
  pinned equal by a test, because the port (`llm/tryon.py`, I0's) has no shared constant.
  - Proposal: `FIXED_WORDS = re.compile(r"^[a-z][a-z ]{0,59}$")` in `llm.tryon`, imported by both.
  - Then I0's `ScriptedTryOn.make` can run the same check, and C's `StrictTryOn` can go.
- **d. §6.10 is done** (finding 2). §6.2 still stands: `tryon_cache` should default to true. A
  later flip now asks for his YES again in any case.
- **e. For D:** a `PictureView` with `kept=False` and `until=None` means "shown once". Its words
  are `texts.NOT_KEPT` ("This picture is too large to keep: it is shown once and not kept.").
- **f. Finding 7 (not done, a contract change).** The door sends the device check's counts with
  both uploads (`?people=&faces=`). The server refuses a garment photo with `faces > 0` and his
  photo with `people != 1` (422, in fixed words), and keeps the counts as plain fields (the data
  model's "the device's check"). This touches `http.py`'s `QUERIES`, the door
  (`console-r7-send.js`) and D's photo panel, so it is I1's to schedule.
- **g. The audit's risk level.** A paid press is audited as REVERSIBLE (`record_change` is
  shared). Two edges of the new `inr`:
  - a repeat answered from `done` is audited with its first outcome's ₹;
  - a press that fails after its settle (a store error on the save) is audited `unavailable` with
    ₹0. Its spend is still in `tryon_spend`.
- **h. Data model.** `tryon_spend/{uid}_{YYYY-MM}` gains `done_order`, a list of request ids
  (finding 4). The consent record gains `cache`.
- **i. The review agents.** This fixer had no agent tool either. `code-reviewer`,
  `python-reviewer` and `security-reviewer` should look at commits `1b5760c` to `fc00fda` in a
  fresh context.

### 10.5 The checks, with their numbers (at `fc00fda`, the heavy ones behind the lock)

| Check | Result |
|---|---|
| `tests/test_r131_c_*.py` | **218 passed** on Python 3.11 and on 3.12 (was 163): gemini 46, consent 28, cap 27, press 27, photos 20, money 13, pair 12, inflight 10, part 10, review 10, api 8, jobs 7 |
| The same, plus I0's `test_r131_port.py`, `test_r131_fakes.py`, `test_r131_spend.py` | **241 passed** on 3.11 and on 3.12 |
| Coverage (3.12): `wardrobe/seeme`, `api/seeme.py`, `llm/tryon_gemini.py` | **94 %** (1,946 statements, 110 missed); every module ≥ 91 % |
| `test_r131_seams.py`, `test_r131_wiring.py`, `test_r13_seams.py`, `test_r13_wiring.py` | **578 passed, 2 failed**: I0's two "not built yet" pins (§6.1), as before |
| The four tick-pin files (§5) | **64 passed** |
| `evals/r13_1/run.py --mock --part seeme` | **26/26 passed**; the control failed the part: True (every control red on both providers) |
| `evals/r13_1/run.py --mock` (every part) | **48/48 passed**; the negative control failed the suite: True |
| `ruff check`, `ruff format --check` (C's 30 files) | clean |
| `mypy` on C's 15 modules | the baseline error only (`memory/redis_store.py:67`) |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK (119 collections); 30 documents OK |
| Sizes (by the AST) | largest module `make.py` 393 (`api/seeme.py` 380, the eval 389); longest function `Press.press` 35 lines |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.0 | 17 Nov 2026, 18:20 IST | R13.1 | First edition: Part C's plan, before code | 🛠 Mark XXIII |
| v13.1.1 | 17 Nov 2026, 19:09 IST | R13.1 | What C built, the checks with their numbers, the ₹ figures, the deviations, the eight tick pins, "Needs I1" with diffs, the review (C's own pass; the agents for I1), the deploy's block, the M5 names, what could not be verified | 🛠 Mark XXIII |
| v13.1.2 | 17 Nov 2026, 19:35 IST | R13.1 | The second builder, after the server restart: BRIEF-C ticked item by item; fixed a made picture lost when its list couldn't be read, a repeat's code outside the contract, ids by `fullmatch`, and the eval over 400 lines (with three cases closer to the brief); two LOW edges at the month's end; "Needs I1" §6.10 (the consent's hash and the cache); every check run again (163 tests; 186 with I0's on 3.11 and 3.12; 94 %; the eval 26/26 with its controls; the runner 48/48). The two earlier rows' times corrected to their commits (they had said 20:10 and 21:40) | 🛠 Mark XXIII |
| v13.1.3 | 17 Nov 2026, 20:45 IST | R13.1 | §10, Fix (review C-1): each finding test first. Fixed: the HIGH (his T-shirts sent in C's own fixed words; a strict scripted fake), both MEDIUMs (his YES bound to the cache and to every line he read, version `c2-` + 12 hex; a press in flight checked and written in one transaction, with a sweep after erase and the pictures row, and page memory cleared on withdrawal), and LOWs 4, 5, 6, 8, 9, 10, 11 and 12 (`done_order`; three tries and kept closes; the model's own end date; the press's audit; logged fallbacks and provider bugs; a streamed, capped answer; the refused-piece words). LOW 7 is left for I1 as a contract change. New Needs I1 a-i. Every check run again (218 tests, 241 with I0's, on 3.11 and 3.12; 94 %; the eval 26/26 with its controls; the runner 48/48) | 🛠 Mark XXIII (fix C-1) |
