Version v13.1.0 · 17 Nov 2026, 19:40 IST · Release R13.1 · Status: Draft · Owner: 🛠 Mark XXIII

# R13.1 Part A: Try-on data (AVT-03, AVT-04, AVT-05, AVT-09, AVT-11, AVT-14, OPS-05)

Builder A's report for I1. Branch `r13-1-a`, cut from `r13-1-i0` @ `eb8b7e4`. Built against
`BRIEF-COMMON.md` v13.1.2, `BRIEF-A.md` v13.1.2, `I0-NOTES.md` v13.1.1 and the plan
`r13-1-try-on.md` v13.1.3 (D4–D7, D11's no-go list, D14, D16, D20, D21, the data model, the HTTP
contract's `tryon` rows, the `looks` suite).

## 1. Plan (written before the code)

What A builds, in this order, each test first (red, then green):

1. `wardrobe/tryon/store.py`: the sealed `tryon/{uid}` document (purpose `tryon`, AAD
   `model.aad_tryon`, plain `owner` and `updated_at`, at most 200 KB sealed); an unreadable
   document is never overwritten; no keyring or no storage is `Off`. Tests `test_r131_a_store.py`.
2. `versions.py`: a draft from what he typed (range words), "Use these measurements", "Keep the
   current", five earlier versions, `BodyView.weights` from `model.morph_weights`; typed fields
   stay typed, the rest re-estimated from the height. Tests `test_r131_a_versions.py`
   (`test_avt02_store_*`, the AVT-03 named test through the routes).
3. `options.py`: one slot's readiness from a FRESH view and his plans (Ready, `DRAFT_WORDS`,
   reserved for an event, one shoe missing, a set part without its set, the shared base); the
   ≤ 12 options of a slot. `assets.py`: his figure choice per piece (AVT-05), tidied on read.
4. `looks.py`: the look for a plan, a day (`alt` 0–2) or a reply card's pieces (row 388), each
   `LookSlot` with its template, colour, texture view, views kept and missing, readiness,
   approximate flags, options; a private slot covered only. Tests `test_r131_a_looks.py`
   (AVT-04, AVT-05, `test_avt14_looks_*`, row 388's `?pieces=`).
5. `confirm.py`: "Use this look": the fresh check before any tool call (409 in words), then ONE
   `outfit_plan` `lock` with `pieces` through `run_panel_tool`. Tests `test_r131_a_confirm.py`
   (AVT-09 with the race).
6. `saved.py`: saved comparisons (≤ 10, re-checked on every read). Tests `test_r131_a_saved.py`
   (`test_avt11_saved_*`).
7. `privacy.py`, `erase.py`: the rows `tryon_figure`, `tryon_all`, `tryon_device`; OPS-05's
   `erase_all` (C's half through its service, else by path; `tryon/{uid}` last; the catalog
   untouched). Tests `test_r131_a_privacy.py` (the OPS-05 named test through `PrivacyService`).
8. `part.py` (the join) and `api/tryon.py` (the 11 routes): owner-only, `no-store`, limited,
   every refusal a `Refusal`. Tests `test_r131_a_routes.py`, `test_r131_a_part.py`.
9. `evals/r13_1/looks.py`: the cases, the three suite controls and each row's own control; BUILT
   only once every control turns its case red.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.0 | 17 Nov 2026, 19:40 IST | R13.1 | The plan section, before any code | 🛠 Mark XXIII |
