Version v6.3.1 · 23 Nov 2026, 18:10 IST · Release R6.3 · Status: Draft · Owner: 🛠 Mark XXIV

# R6.3 — Part B: the writer (INTEGRATION-B)

Builder B's record for I1 (`BRIEF-COMMON.md`, `BRIEF-B.md`; the plan `docs/plans/r6-3-book-content.md`
v6.3.3: D1's use, D4–D8, D10–D13, the data model, the HTTP contract, the `writer` suite). Branch
`r6-3-b` from `origin/r6-3-i0` @ `d25dbcc`.

## 1. Plan (written before the code)

What B builds, in this order, each test written and run red first:

1. **Units** (`tests/test_r63_b_units.py`): `fill.py` (placeholders → values), `checks.py` (the six
   checks, the exemptions of check (2), the precision case), `consent.py` (the terms id, the grants
   that need his typed YES), `estimate.py` (low / mid / high, the hold, "about ₹"), `packs.py` (what
   a pack reads and never reads, the 96,000-byte cap, the scrub, the fence), `prompts.py`.
2. **Money** (`tests/test_r63_b_caps.py`): `caps.py`, R13.1's pattern: one transaction a hold,
   refused with nothing written past the run's cap, the month cap or the 80 % gate, `busy`,
   settle / release / keep-at-hold, `close_later`, `settle_old`, his IST month and the hour after it.
3. **Sealing** (`tests/test_r63_b_vault.py`): `vault.py` (the pages index beside R6's, attach or
   replace in one transaction, R6's Privacy hold, the storage limit), `carry.py` (changed pages,
   the free carry), `sweep.py`; R6's index still opens with 47ee8fc's `BookIndex`.
4. **The run** (`tests/test_r63_b_rows.py`, the named tests of B's rows): `run.py` (the step:
   lease, holds, the call through `jarvis.llm.write`, the refusals before the checks, one redraft,
   drafts, the seal at the end), `store.py`, `pages.py`, `part.py` (the service), `job.py` (the free
   work on every run, brain calls only inside an approved run), `privacy.py`.
5. **Routes** (`tests/test_r63_b_routes.py`): `api/book_writer.py`, `api/book_pages.py` over the
   real app (console only, primary owner only, guest 403, `no-store`, limits, refusals).
6. **Eval** `evals/r6_3/writer.py` with every control of the plan's `writer` row and each row's own.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 18:10 IST | R6.3 | First edition: the plan, before the code | 🛠 Mark XXIV |
