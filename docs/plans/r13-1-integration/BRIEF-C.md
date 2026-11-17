Version v13.1.1 · 17 Nov 2026, 16:05 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — Part C brief: See it on me (Opus)

Read `BRIEF-COMMON.md` first. Branch `r13-1-c` from `origin/r13-1-i0`. `security-reviewer` is
REQUIRED (consent, money, his photo, the adapter, the deploy's role: read `deploy/cloudrun.sh`'s
R13.1 block, I0's, and say in INTEGRATION-C whether it holds).

You build the one paid path: the Gemini adapter behind I0's port, his photo, his typed YES, the ₹
estimate, the atomic monthly cap, the press, the pictures, their 30 days, your Privacy rows, the
daily job and C's half of OPS-05. Plan sections: D10–D15, D18, D19, "Google's image models",
"Data model" (C's four collections), "The HTTP contract" (the `seeme` rows), "Per part" C, the
`seeme` suite, "What can't be verified".

## 1. Your files (only these)

`src/jarvis/llm/tryon_gemini.py`, `src/jarvis/wardrobe/seeme/{part,vault,consent,cap,estimate,
make,pictures,privacy,jobs,texts}.py` (`part.py` replaces I0's stub), `src/jarvis/api/seeme.py`
(I0's empty router: fill it), `tests/test_r131_c_*.py`, `tests/r131_fake_gemini.py`,
`evals/r13_1/seeme.py` (I0's stub: replace it), `docs/plans/r13-1-integration/INTEGRATION-C.md`.
Every module ≤ 400 lines, functions ≤ 50. The eight tick-job pins of earlier wiring tests (BRIEF-COMMON
section 4) are the one exception you move, named in INTEGRATION-C.

## 2. Your contracts

- **The join** (`part.py`): `build(ctx) -> WardrobePart("seeme", daily_jobs=(<seeme_daily>,),
  privacy=(…three rows…), services={"seeme": <a SeeMeErase and your service>}, ready=…)`. No tool,
  no `data`; only `tryon_photo`, `tryon_pictures`, `tryon_spend` (`ports.PRIVACY_OWNER`).
- **The adapter** `llm/tryon_gemini.py`: `build(s, *, tokens, project) -> TryOnProvider` (I0's
  `llm.tryon.build_tryon` imports it by that name: `ADAPTERS["gemini"]`). Plain REST with httpx to
  the Agent Platform's GenerateContent at the `us` multi-region (`https://aiplatform.us.rep.
  googleapis.com/v1/projects/{p}/locations/us/publishers/google/models/{model}:generateContent`;
  `eu` likewise; `global` is not priced in `TRYON_PRICES` for this model, so it stays off), a bearer
  token from `tokens.headers()` (`voice.adc.AdcTokens`; `invalidate()` on a 401), the project from
  `await project()`. NEVER `gemini_provider.py`'s Developer-API key (it may train on content). The
  body holds only what Google's own image sample holds: one `user` turn with `inlineData` parts (his
  photo, then each garment's crop) and one fixed English text part ("Show the person in the first
  image wearing the clothes in the other images: a navy shirt (image 2), charcoal trousers (image
  3). Keep the person's face, body shape, pose and background as they are. One full-length picture,
  no text."), and `generationConfig` with `responseModalities: ["IMAGE"]` and `maxOutputTokens:
  8192` (CHECK both names on Google's GenerateContent reference first, M5; no safety, person or size
  setting). The answer: the first `inlineData` image part (JPEG or PNG by its magic bytes, ≤ 16 MB,
  `model.ANSWER_MAX_BYTES`), **every text part discarded unread** (never logged, shown or kept);
  `usageMetadata` → `TryOnUsage`; a `promptFeedback.blockReason` or a finish without an image →
  `blocked` (billed). Any non-200 → `TryOnNotBilled`; a timeout after sending or a cut 200 →
  `TryOnMaybeBilled`. Redirects never followed; the token, bodies and bytes never logged (class
  names and statuses only). No SDK. `describe()` from `llm.tryon`'s `MODEL_WORDS`, `LOCATION_WORDS`,
  `RETIRES_ON` (`max_garments` 3); `estimate(n)` = `(typical_usd, worst_usd)`. Tested with
  `httpx.MockTransport` only (`tests/r131_fake_gemini.py`: an image with `usageMetadata`, an answer
  whose text part carries an instruction, a blocked prompt, a finish without an image, 400, 403,
  404, 429, 500, 503, a cut body, a timeout).
- **His photo (D12)** `tryon_person/{uid}`: JPEG only, the side ≤ 1,568 px from its SOF marker
  (R13's `catalog.photos.frame_size`), ≤ `tryon_photo_max_kb` (700) KB, cleaned by
  `photos.imaging.sanitise_jpeg` (EXIF and GPS dropped; never decoded), sealed `tryon_photos`
  (`model.aad_person(uid)`), a plain `owner` field; a new photo replaces the old in one write; read
  back by his signed-in console only (`console_only`'s rule; `http.PICTURE_HEADERS`). Never in the
  Vault panel, the R13 backup file, an export or the AI.
- **Consent (D11)** `tryon_consent/{uid}` (sealed `tryon`, `model.aad_consent(uid)`): his typed
  `YES` (exactly, letters only, trimmed; "yes", "Yes", "YES!" refused, nothing changed), when, and a
  SHA-256 over a FIXED template: its version, provider, model, location and location words. NEVER
  the day's ₹ or the cap (a moved rate 95.24 → 96.10 keeps consent current; a model or location
  change asks again). The fixed lines go to the console in `ConsentView.words` with the template's
  `version` (what is sent, to whom, what Google keeps: no training without permission, may log for
  abuse checks, caching off, or "up to 24 hours" when `s.tryon_cache` is true; every picture's ₹
  first under his cap; Content Credentials; the model's end date; how to withdraw). Only from a
  signed-in browser; withdraw = delete his photo (the consent goes with it).
- **The estimate (D13.2)** `GET /v1/seeme/estimate`: `llm.tryon.typical_usd` / `worst_usd` × the
  day's rate (`billing.fx`, ₹95.24 when unknown) and `billing.spend.with_tax(…, s.tryon_tax_pct)`,
  rounded UP to 10 paise for the words: typical ≈ ₹8.9, hold ≈ ₹11.2 (top + trousers + jacket); the
  pieces sent and not sent (a private piece, no `front` crop, a slot that isn't a garment
  (`model.GARMENTS`), unticked) with reasons; the cap left; his limit's room. The look comes from
  A's `ports.looks_service(ctx).look(uid, plan)`, fresh; the crops from R13's catalog through
  `ports.photo_vault(ctx).get(uid, photo)`.
- **The cap (D15)** `tryon_spend/{uid}_{YYYY-MM}` (his IST month, `UsageMeter.month_of`; numbers
  only, a plain `owner`): `{spent_inr, held_inr, holds {request_id: {inr, at}}, done {request_id:
  outcome} (≤ 50), pictures, blocked, updated_at}`. `reserve(uid, request_id, hold_inr)` reads and
  writes in ONE transaction: refused with nothing written while a hold under 10 minutes old exists
  (`busy`) or when `spent + held + hold > cap` ("This month's try-on limit of ₹300 is used: ₹291.6
  spent. It resets on 1 Dec, or raise it in Try-on settings."); a counter that isn't a finite
  number ≥ 0 refuses (never "₹0 spent"); `settle` moves the hold into spend; `release` gives it back
  (never below 0, `released` set before the first await, a failed release retryable: R6.2's `Hold`,
  `billing/meter.py:330–372`). The cap is `tryon_month_cap_inr` (his own setting 0–2,000; 0 = off;
  raising it needs `confirm_cost: true`). Every ₹ shown and the cap include GST.
- **The press (D13.4)** `POST /v1/seeme/pictures`, gates in this order, each refusing before any
  spend: console-only; 6 presses a minute (`r13_status.limited(..., per=model.PRESSES_A_MINUTE)`);
  pictures on (`tryon_pictures`) and before `tryon_model_retires`; not No-AI mode
  (`offline.mode.BrainMode`); consent current; his photo kept; every piece sendable (from the
  record, never the console's word); `confirm_cost`; the fresh typical ≤ `inr_shown` + ₹0.01 (else
  409 `price_changed`); `billing.spend.ensure_spend_allowed` (his overall limit, fail closed); the
  cap's atomic reserve of the hold (`busy` inside it). Then ONE `make` (a 120 s deadline,
  `model.CALL_DEADLINE_S`); settle from `usageMetadata` (`llm.tryon.cost_usd`) into the cap and his
  usage month under the label `tryon` (`Billing.record`); no usage → settled at the hold; released
  in full on `TryOnNotBilled`; kept at the hold on `TryOnMaybeBilled` and a blocked 200. A repeated
  `request_id` answers the same outcome (`done`). Errors per `http.ROUTES`: 402 `cap_reached` /
  `budget_reached`, 409 `consent_needed` / `price_changed` / `busy`, 422 `private_piece` /
  `no_photo` / `not_a_garment`, 502 `blocked` (with the ₹ note), 503 `not_configured` / `retired` /
  `no_ai` / `provider_unavailable`.
- **Pictures (D10, D14)** `tryon_picture/{uid}_{id}` (`tp_` ids, sealed `tryon_photos`,
  `model.aad_picture`, a plain `owner`): kept AS GOOGLE RETURNED IT (structure checked, never
  decoded or re-encoded, so its Content Credentials stay), if ≤ 700 KB (else shown once, not kept,
  said); served with its detected type and `http.PICTURE_HEADERS`; **30 days** (`tryon_keep_days`,
  `model.PICTURE_KEEP_DAYS`: the owner's answer of 17 Nov 2026 to question 3) unless Keep (≤ 24 kept); a piece later made private or purged takes its pictures with it. `PictureView`'s
  `sent` is what was SENT (never the plan's list), `not_sent` the rest; `label` `model.GENERATED`,
  `credentials` `model.CREDENTIALS`.
- **`seeme_daily`** (the morning tick, budget-bounded like R13's jobs): pictures past their time
  and of pieces now private or gone; holds older than an hour settled at their hold; from 30 days
  before the model's end date the panel's notice. Nothing else runs on a clock.
- **Privacy rows** (words from `kept.SPECS`): `tryon_photo` (export says when and how big, never the
  bytes; passkey), `tryon_pictures` (export lists them, never the bytes; passkey), `tryon_spend`
  (numbers per month; not deletable). **`erase(uid)`** (your `SeeMeErase`): pictures, then his
  photo, then his YES; never the spend.
- **Settings** `PUT /v1/seeme/settings` `{on, cap_inr, keep_days, confirm_cost}` (console only).

## 3. Your row (his acceptance check, word for word) and its named test

| Row · ID | His acceptance check | Your test (what must hold) |
|---|---|---|
| 363 · AVT-12 | A still preview is labelled as 2D and the checklist still identifies the exact clothes used in the plan. | **`test_avt12_the_picture_is_labelled_a_generated_2d_preview_and_lists_the_exact_pieces`**: a made picture shows "Generated 2D style preview — not a photo" and the list of the exact piece ids sent (top, bottom, jacket: the ones in the request) with their words; pieces not sent are listed as not in the picture; the 3D view stays (D proves the card) |
| 350 · OPS-05 (your half) | Deleting an avatar removes it from the viewer and disables dependent previews while retaining the item catalog. | `test_ops05_seeme_*`: `erase` removes his pictures, photo and YES in that order; "See it on me" asks for a photo again; the spend stays (A owns the named test) |

## 4. Your eval (`evals/r13_1/seeme.py`, through the PORT) and its controls

Run every case on your adapter (recorded answers through `httpx.MockTransport`) AND on I0's
`ScriptedTryOn(max_garments=1)` (`tests/r131_fake_tryon.py`, which chains inside itself): zero
provider calls without a current YES; "yes", "Yes", "YES!" refused; a moved rate (95.24 → 96.10)
keeps consent, a model or location change asks again; the cap: with each picture settled at ₹8.52
and a hold of ₹11.22, the 34th fits and the 35th is refused; 10 presses at once → exactly one
reserves, nine `busy`; released on every non-200 and on "never sent", kept on a timeout after
sending, a cut 200 and a blocked 200; settled from `usageMetadata`, at the hold without it; a text
part in the answer is read nowhere (logs, store, reply); a private piece and a piece without a front
crop refused before any call; No-AI, bearer token, past the end date, `price_changed`, idempotent
`request_id`. **Controls that must turn it red:** the atomic reserve replaced by read-then-write (the
10-at-once case lets two through); the consent check off ("zero calls without YES" fails); the
private check moved to the console only (a private piece reaches the fake provider); the ₹ hashed
into the consent (the moved-rate case asks again). **The row's own control (M8):** AVT-12 the piece
list taken from the plan, not from what was sent.

## 5. Limits

No real Google call anywhere (the live picture is the pilot's, after his YES, at I1). Dollars stay
inside `llm/` and the estimate's arithmetic: every owner-facing string is ₹ (a static test refuses
a `$` figure in R13.1's Python texts). Fixed clocks (the 30 days and 28 May 2027 tested at 23:30 and
00:30 IST). INTEGRATION-C: the deploy's role and cache step reviewed, the names you checked on
Google's reference (M5), the eight tick pins you moved, "Needs I1", what you could not verify.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 16:05 IST | R13.1 | First edition, written at I0: Part C's files, contracts (the join, the Gemini adapter on I0's port, his photo, consent bound to provider, model and location, the estimate, the atomic cap, the press's gates in order, pictures as Google returned them, `seeme_daily`, the Privacy rows and `erase`, settings), its row with his acceptance check and the named test, the `seeme` eval through the port with its controls, limits | 🛠 Mark XXIII |
