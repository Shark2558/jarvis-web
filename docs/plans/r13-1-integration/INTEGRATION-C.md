Version v13.1.0 · 17 Nov 2026, 20:10 IST · Release R13.1 · Status: Draft · Owner: 🛠 Mark XXIII

# R13.1 — Part C: See it on me (integration notes)

Builder C (Opus), branch `r13-1-c` from `r13-1-i0` @ `eb8b7e4`. Brief: `BRIEF-C.md` v13.1.2, the
common brief v13.1.2, the plan v13.1.3 (D10–D15, D18, D19, D22).

## 1. The plan (written before code)

What C builds, in this order, each step test first (the test run red, then the code):

1. **Fakes.** `tests/r131_fake_gemini.py`: Google's GenerateContent answers through
   `httpx.MockTransport` (an image with `usageMetadata`, a text part carrying an instruction, a
   blocked prompt, a finish without an image, 400, 403, 404, 429, 500, 503, a cut body, a timeout).
   `tests/r131_fakes_c.py`: the seeme world (R13's styling part on the seeded pilot, I0's photo
   vault with a front crop on the trousers, a yielding store so a read-then-write race is real).
2. **The adapter** `llm/tryon_gemini.py` (`test_r131_c_gemini.py`): the body (his photo, the new
   garment's photo, his crops; one fixed text part; `responseModalities`, `maxOutputTokens`), the
   endpoint per location, the bearer token, the answer (the first image part, text discarded
   unread, usage), every error billed or not, nothing logged but class names and statuses.
3. **Money and the cap** (`estimate.py`, `cap.py`; `test_r131_c_cap.py`): the ₹ figures (typical
   ≈ ₹8.9, hold ₹11.22, settle ₹8.52 at ₹95.24 and 18 % GST), the atomic reserve (busy, cap,
   unreadable), settle, release (retryable), the 34th fits and the 35th not, 10 at once.
4. **His photo, the garment's photo, consent** (`vault.py`, `garments.py`, `consent.py`;
   `test_r131_c_photos.py`, `test_r131_c_consent.py`): JPEG only, the SOF side, the size, cleaned,
   sealed; ≤ 20 garments; YES exactly; the hash bound to provider, model, location, never the ₹.
5. **The pairing** (`pair.py`; `test_r131_c_pair.py`): R13's engine around a transient piece; at
   most two sendable pieces of his, never private, never in the garment's slot.
6. **The press and pictures** (`make.py`, `pictures.py`; `test_r131_c_press.py`): the gates in
   order, ONE make, settle / release / keep, `done`, pictures as Google returned them, Keep.
7. **The join, Privacy rows, the daily job** (`part.py`, `privacy.py`, `jobs.py`;
   `test_r131_c_part.py`, `test_r131_c_jobs.py`): `erase` (OPS-05's half), the three rows,
   `seeme_daily` at 23:30 and 00:30 IST and across 28 May 2027.
8. **The routes** `api/seeme.py` (`test_r131_c_api.py`): every `seeme` row of `http.ROUTES`, the
   console-only rule, the rate limits, `Refusal`; AVT-12's named test; OPS-05's half.
9. **The eval** `evals/r13_1/seeme.py` through the port, on the adapter and on I0's one-garment fake,
   with its five controls and AVT-12's own; `BUILT = True` once each control fails it.
10. **The eight tick pins** moved; reviews; the checks; this file.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.0 | 17 Nov 2026, 20:10 IST | R13.1 | First edition: Part C's plan, before code | 🛠 Mark XXIII |
