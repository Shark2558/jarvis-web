Version v6.3.1 · 23 Nov 2026, 18:45 IST · Release R6.3 · Status: Draft · Owner: 🛠 Mark XXIV

# R6.3 — Part A's integration notes: the fact pack and the generator

Part A of R6.3 (`docs/plans/r6-3-book-content.md` v6.3.3: D2, D2a, D2b, D3, D10's G3–G8), built on
`r6-3-a` from `r6-3-i0` @ `d25dbcc` by the Workshop (🛠 Mark XXIV). Briefs: `BRIEF-COMMON.md`,
`BRIEF-A.md`. A first builder was stopped by a server restart after three commits (the scrubber's
kinds and phrases, the counter, and a `wip` of the pack and the pages index); this builder checked
that `wip` against the brief, fixed it and finished the part.

## 1. The plan (written before the code)

Already on the branch: `gen/scrub.py` (G8, M8; `tests/test_r63_scrub_kinds.py` green, its `xfail`
marks removed), `gen/loc.py` (D2a, G6), and the `wip`: `gen/facts.py` with its helpers
`facts_code.py`, `facts_guide.py`, `facts_routes.py`, `facts_values.py`, `gen/pages_index.py`,
`gen/plans.py` (G4) and their tests. Order of the rest, each test written before its code:

1. Fix the `wip`: the release day in the book's own form ("23 Nov 2026", D asks for it), and the
   tour's 30 keys all or none (a fixture repository gives none, so D's "some but not all is a
   `GenError`" never stops R6's fixture builds). Tests: `test_r63_a_facts_units.py`.
2. G7, `gen/costs.py`: GitHub Actions on a public repository Unverified; Firestore's daily free
   reads, writes and deletes. Test: `test_r63_a_book.py`.
3. G3, `gen/code.py`: the book's integrations name every one of the coverage checker's 31
   services. Test: `test_r63_a_book.py`.
4. D2b and G5, `gen/inventory.py` (new): Android, the home kit's images, the bridge's pins, the dev
   tools, one SPDX spelling a licence, the run-time / build-and-maintenance split. Test:
   `test_r63_a_inventory.py`.
5. The eval `evals/r6_3/facts.py`: the plan's `facts` cases and every control of BRIEF-A §4.
6. Verify once at the end (the owner's rule of 23 Nov): A's tests and the seam tests, `--check` on
   the real repository, ruff and mypy on A's files, the eval; then this file.

(Filled in at the end: what was built, the numbers, the deviations, "Needs I1".)

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 18:45 IST | R6.3 | First edition: part A's plan, written before the rest of its code | 🛠 Mark XXIV |
