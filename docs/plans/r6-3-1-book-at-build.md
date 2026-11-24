Version v6.3.2 · 24 Nov 2026, 05:55 IST · Release R6.3.1 · Status: Ready · Owner: 🛠 Mark XXIV

# Release R6.3.1 — The Build Book written at build time (`v6.3.2`)

**Why:** the owner's instruction of 24 Nov 2026, 03:12 IST, after both brains failed his Writer
trial with "the API server was busy": *"design and develop the entire build book during development
and remove the trial from the screen as well. It should be a completely backend process without my
intervention and also use Claude subscription which can create the entire book without API usage or
cost. Markdy is not mandatory for this book. Use the theme specific flowcharts aesthetics."*

**Phase:** 7 (quality, docs) on the Build Book (cross-cutting; the Learning skill). **Type:** ₹0 —
JARVIS makes no AI call for the Book at all after this release. **Version:** `v6.3.2` (`v6.3.1` is
R6.3's hotfix 1; workshop rules §6.1). **Base:** `main` @ `598ee82`. **Branches:** `r6-3-1-i0` →
parts `r6-3-1-e`, `r6-3-1-f`, `r6-3-1-w1` … `r6-3-1-w6` → `r6-3-1-i1` → PR
`v6.3.2 · R6.3.1 The Build Book written at build time · Mark XXIV`. Trailers `JARVIS-Version: v6.3.2`,
`JARVIS-Mark: XXIV`. Workbook: new row **391** (this ask), rows 379–380 stay Done.

## Summary for the owner (plain words)

1. **The Workshop writes the whole book** — all 153 pages — while it builds JARVIS, with Claude on
   your subscription. JARVIS itself never calls an AI for the Book: **₹0, nothing to approve.**
2. **Gone from the screen:** the Writer trial, the writer pick and its ₹ caps, "The full write" and
   "The update". The Book panel keeps the tour and the **Full book** reader.
3. **Every release keeps it current by itself:** when a release changes code a page describes, the
   Workshop rewrites that page in the same pull request. GitHub refuses to merge a release whose
   pages are out of date or fail a check.
4. **The same checks as before, now before merge:** every file, function and setting a page names
   must exist; every number comes from the code; no personal data, no private words, no invented
   features.
5. **Flowcharts in the console's own look** (no Markdy): each chapter and each module page shows a
   flowchart drawn in the console's colours, Night and Day, readable on the phone.
6. **Public:** the pages live in the public repository (they describe only JARVIS's own public code;
   the checks block anything personal). Your sealed copy per release stays in your vault.
7. **Your old trial data** (the writer pick, caps and trial pages from 24 Nov) is not deleted by
   itself: Privacy keeps a row for it with **Delete**.
8. **Not in this release:** the Book's new look and the full book narrated in chapters (R6.4,
   mockups first); pictures of each module are replaced by the module flowcharts.

## Decisions (safe defaults, taken for the owner; each reversible)

- **D1 Authored pages.** One file per indexed page, `src/jarvis/buildbook/book/pages/<page_id>.md`,
  in the existing five-section wire format (`writer/model.DRAFT_SECTIONS`, `## <heading>` blocks,
  `{{fact:<key>}}` placeholders, `Planned:` lines), with a YAML front matter. "Where in the code" is
  still generated from the index, never written.
- **D2 Front matter.**
  ```yaml
  ---
  page: pg_module_wardrobe          # must equal the file name and an indexed page
  written_by: Workshop · Mark XXIV
  written_on: 2026-11-24
  sources:                          # every ref of the page: path -> first 16 hex of SHA-256
    src/jarvis/wardrobe/ledger.py: 3f1c0a9b2d4e5f60
  ---
  ```
  `sources` is written only by the stamp tool (D5), never by hand.
- **D3 Flowcharts.** `src/jarvis/buildbook/book/flows/<page_id>.json`, required for the 8 chapters and
  18 modules, optional elsewhere. Spec (pydantic, `extra="forbid"`): `title` (≤ 60), `dir`
  (`"down"` | `"right"`), `nodes` (2–14: `id` slug, `label` ≤ 28 chars, `kind` one of `step`,
  `store`, `service`, `guard`, `person`, `rank` 0–9, `col` 0–5, optional `ref` = a path the page may
  cite), `edges` (1–24: `from`, `to`, optional `label` ≤ 20, optional `style` `"main"` | `"side"`).
  Explicit `rank`/`col` → a deterministic layout with no layout library. Labels pass the scrubber and
  the private-word guard; refs must be in the page's refs.
- **D4 Build.** The generator (`python -m jarvis.buildbook.gen`) compiles the authored pages into the
  release's pages file (`writer/pages.encode_file`, gzipped canonical JSON, ≤ 2 MiB) plus a flows
  file, beside `book.json`/`facts.json` in `_book/`. Each page is parsed, filled from the release's
  fact pack and checked (`writer/checks.check`); a page that fails, or is missing, is served as the
  generator's plain text (`pages.generator_page`) — the deploy never breaks on a page.
- **D5 Tools for the writer** (`python -m jarvis.buildbook.gen pages …`):
  `--list` (id, kind, title, status: `missing` | `stale` | `failing` | `ok`), `--pack <id>` (what a
  page may cite and the facts with their keys and values: `writer/packs`), `--check [ids…]` (parse,
  the six checks, the flow spec, staleness; one line per problem; exit 1 on any), `--stamp <ids…>`
  (writes `sources` from the current tracked files after the writer re-read them). The fact pack is
  cached per tree in `build/book-cache/` so a check takes seconds; page and flow files under
  `src/jarvis/buildbook/book/` are excluded from the index, the refs and the "uncommitted changes"
  rule.
- **D6 Staleness.** A page is **stale** when its `sources` differ from its refs' current hashes (a
  ref changed, appeared or went). CI's `docs-check` job runs `pages --check` on every pull request
  and on `main`: missing, stale or failing pages fail the job. The Workshop's release loop gains one
  step: rewrite the stale pages before the PR (rules §7 note).
- **D7 Serving.** `GET /v1/book/pages` and `/{id}` (same gates as R6.3: primary owner, owner book
  session, console only, `no-store`, 60 a minute) read the kept release's sealed pages file; no
  per-owner Firestore pages any more. The sealer seals the pages and flows files with each release
  (60 MiB cap unchanged; pages ≈ 0.5 MiB).
- **D8 Removed (runtime writer):** `writer/caps.py`, `consent.py`, `estimate.py`, `job.py`, `run.py`,
  `sweep.py`, `part.py`, `prompts.py`, `store.py`, `vault.py`, the writer routes in `writer/http.py`,
  `api/book_writer.py` and `api/book_writer_wiring.py` (the pages routes move to a small module of
  their own), the 5-minute clock hook, `console-book-writer.js` and its Book-settings sections, the
  writer's eval suites; `jarvis.llm.write` if nothing else uses it. **Kept:** `writer/model.py`
  (trimmed: no ₹ or brain fields), `checks.py`, `fill.py`, `pages.py`, `packs.py`, `carry.tree_of`
  (hashing), `privacy.py`. `PageMeta` becomes `{written_by, written_on, release, version}`.
- **D9 Old data.** The Privacy row of the old writer data (pick, caps, consent, trial pages, sweep
  state) stays, with count, export and **Delete** (passkey), labelled "Book writer (old trial)". No
  automatic deletion.
- **D10 Look.** The reader and the flowcharts use only the console's existing tokens
  (`--accent`, `--accent-2`, `--amber`, `--ok`, `--bad`, `--ink*`, `--line*`, `--card`, `--well*`,
  `--glow`, `--r-*`, `--font`, `--mono`); node kinds map to existing accents; Night and Day; ≤ 400
  lines per JS file; CSP `script-src 'self'`; an accessible text list of the steps under each chart
  (`role="img"` + `aria-describedby`). Design per the owner's ui-ux-pro-max rule; the PR carries the
  screenshots (desktop + phone, Night + Day) for his look check.

## Who builds what

| Part | Branch | Owner | What |
|---|---|---|---|
| I0 | `r6-3-1-i0` | Mark XXIV | This plan; `book/pages/`, `book/flows/`; the page and flow file models and loaders; `pages --list/--pack/--check/--stamp` with the facts cache; the authoring guide `src/jarvis/buildbook/book/AUTHORING.md`; tests |
| E | `r6-3-1-e` | builder | D4 compile in the generator, D7 serving and sealing, D8 removals, D9 Privacy row, CI `docs-check` step, version `6.3.2`, evals updated, tests |
| F | `r6-3-1-f` | builder | D10: `console-book-flow.js` (SVG renderer from the flows file), the reader shows the chart above "How it works"; browser tests and screenshots |
| W1–W6 | `r6-3-1-w1` … `w6` | writers | The 153 pages and 26+ flows, every page passing `pages --check`, stamped |

Writers' split (by the index order): **W1** the 8 chapters + 18 modules (all with flows) · **W2**
cards 1–25 · **W3** cards 26–50 · **W4** cards 51–73 · **W5** the 23 screens · **W6** the 31 services.
Each writer reads the code behind every page (not only the pack), follows `AUTHORING.md`, runs
`pages --check` on its pages until clean, stamps them, commits small and pushes after each batch.

## Writing rules (AUTHORING.md, from R6.3's writer rules)

The reader is the owner, not a programmer. Five sections in order: **In plain words** (what it is and
why it matters), **Example (made up)** (one worked example with made-up people and numbers; the only
place a typed number may appear), **How it works** (every sentence cites a backticked reference the
page may cite), **What it costs** and **When it fails** (from the facts and the code only). Every other
number is a `{{fact:<key>}}`; an Unverified fact says "Unverified" in its sentence; never a feature
the code doesn't show; planned work only after a `Planned:` line; no HTML, links, e-mails or real
names; British spelling, short sentences, "JARVIS" for the assistant, "you" for the owner. Caps:
900 / 900 / 2,400 / 900 / 900 characters once filled.

## Tests and checks (the 23 Nov working rules)

- I0, E, F: own tests first (red → green), run once. Writers: `pages --check` only.
- I1: join; `pages --check` all clean; the touched test files once.
- One combined security + code review (fresh context) that fixes its findings and runs the ONE final
  check pass: unit 3.12 whole suite with coverage (≥ 80 %, today ≈ 95.6 %), ruff, mypy baseline, mock
  evals, docs checks, `pages --check`, the Book's browser files, screenshots looked at.
- GitHub CI runs Python 3.11 and the whole browser suite.

## Risks

- **Subscription usage limits:** writing 153 pages is a long run; a limit pauses the writers and they
  resume from their pushed heads. **Server restarts:** writers commit and push after every few pages.
- **Quality:** a check-passing page can still read poorly; the review samples 20 pages against the code.
- **Public text:** the checks (scrubber, owner-id match, private-word hashes) run on every PR; the
  words file never enters the repository.
- **Merge friction:** every PR that changes a cited file must refresh its pages; the `--list` status
  and a clear CI message keep that quick.
- **Rollback below v6.3.2 (review of I1, M-4):** a release sealed by v6.3.2 or later holds four
  files (book, source, pages, flows). Code before v6.3.2 reads exactly two in R6's vault index, so
  after a rollback to v6.3.1 the whole index fails its check: the Book opens no kept release and the
  sealer sends one "your sealed build books failed their integrity check" notice. Nothing is
  rewritten or deleted by itself (an index that won't open is never overwritten), and rolling
  forward again opens every release as before. After such a rollback, don't press Privacy →
  Delete on the sealed build books (it deletes an index it can't open), and don't take that
  notice for tampering.

## Owner's steps after merge

Ctrl+F5; About reads v6.3.2; Book → Full book shows written pages with flowcharts; the Writer trial
is gone; optionally Privacy → "Book writer (old trial)" → Delete. Nothing to pay, nothing to approve.
A rollback to v6.3.1 or earlier, once v6.3.2 has sealed a release, makes the Book read the vault as
failing its check until you roll forward again (see Risks): nothing is lost.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 24 Nov 2026, 04:00 IST | R6.3.1 | First edition: the owner's instruction of 03:12 IST; decisions D1–D10; builders I0, E, F, W1–W6; writing rules; checks; risks | 🛠 Mark XXIV |
| v6.3.2 | 24 Nov 2026, 05:55 IST | R6.3.1 | Review of I1: the rollback note (a four-file sealed release is unreadable below v6.3.2; nothing lost, roll forward) in Risks and in the owner's steps | 🛠 Mark XXIV |
