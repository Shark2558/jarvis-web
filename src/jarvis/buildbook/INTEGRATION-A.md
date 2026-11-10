# R6 builder A — Generator and release id: what the integrator (I1) wires

Branch `r6-a` (from `r6-i0`). Binding decisions relied on: D1 (no model call), D2 (sources and the
generator), D3 (scrub), D4 (CI, release id, hand deploys), D5 (snapshot), D15 "all facts come from
`book.show`" (scenes 1–11 with fixed templates; 12–13 are `lines.py`).

## What A delivers

| File | What |
|---|---|
| `buildbook/gen/__main__.py` | `python -m jarvis.buildbook.gen [--repo] [--out] [--check] [--best-effort]` |
| `gen/repo.py` | `Repo` (git-tracked files, `rev-parse HEAD`, `log -1 %cI`; shallow-clone safe; symlinks never followed), `GenError` |
| `gen/code.py`, `gen/layers.py` | AST look-ups; packages + layers (an unmapped package fails); Integrations |
| `gen/plans.py` | release label, decisions, fit rows, limitations (first sentence ≤ 200, newest first, ≤ 80) |
| `gen/libs.py` | libraries + licences (dist metadata; vendored licence files), flags, Stack |
| `gen/costs.py` | ₹ costs (price table, voice, search, maps, free tiers) at `billing.fx.DEFAULT_RATE` |
| `gen/flows.py` | the 10 flows; every step's symbol AST-checked |
| `gen/show.py`, `gen/chunks.py` | show scenes 1–11 (beats + facts), the digest (overview + ≤ 1,500-char chunks) |
| `gen/scrub.py`, `gen/redact.json` | D3 scrub + `verify`; `NoScrub` (the eval control); hashes only |
| `gen/snapshot.py`, `gen/fake_secrets.txt` | D5 zip, THIRD_PARTY.json, secret scan, 15 MB cap |
| `gen/write.py` | `build`, `check` (twice, byte-compare), `write`, `write_error` (best effort) |
| `buildbook/release.py` | `ReleaseSource` (the `BookSource` port), `default_source()`, `current()`, `owner_mentioned` |
| `buildbook/plain.py` | plain words: layers, services, alert kinds, key purposes, package fallbacks |
| `.github/workflows/ci.yml` | test job: `python -m jarvis.buildbook.gen --check`; deploy job: D4's steps (best effort) |
| `Makefile` `book`, `deploy/cloudrun.sh` (one line), `.gcloudignore` (new, see below) | hand deploys |
| `evals/r6_book/gen.py` | `BUILT = True`, 8 cases, control = scrub off |

## Wiring for I1

1. **Book source** (in `wire_r6`): `R6_STATE.book_source = jarvis.buildbook.release.default_source()`.
   B's sealer: `current()` → `None` = "This server has no build book" (no notice); a `Release`
   with `error` = the deploy's best-effort build failed → `book_seal_failed` once; an ok release →
   `read("book")`, `read("source")` (verified on every read; `BookUnavailable` on a mismatch).
   `book()` is the parsed `Book` (C's digest/talk and D's script route read `book().show` /
   `book().digest`).
2. **D3's last check before sealing** (B or I1): `release.owner_mentioned(book_bytes,
   settings.owner_emails)` → True means refuse and send `book_seal_failed` (full address
   case-insensitive, or its local part as a whole word when ≥ 3 characters).
3. **Mock evals**: `r6_book (gated)` into `evals/run_all_mock.py` (I1's). The `gen` part takes ~5 s.
4. **`--check` must stay green after the merge** (the CI test job runs it on 3.11 and 3.12):
   - every new `src/jarvis/<pkg>` (or top-level module) needs a line in `gen/layers.py`;
   - B, C and D test/eval files must not hold secret-shaped strings (private-key header, `AIza`+35,
     `sk-ant-`+20, `ghp_`+30, `github_pat_`+22, `AKIA`+16, Telegram `<digits>:<35>`). Assemble them at
     run time (see `tests/book_gen_fakes.py::fake_secret`) or add `<sha256>  <path>  # <shape>` to
     `gen/fake_secrets.txt`. `python -m jarvis.buildbook.gen --check` names path and shape, never the
     string. C's guard cases are the likely place.
   - Optionally re-point the `build_book` flow (`gen/flows.py`) at B's/C's classes once merged
     (e.g. `buildbook.sealer:BookSealer.ensure`, `buildbook.talk:BookTalk.ask`); today it names the
     I0 ports (`buildbook.ports:BookVault.seal`, `buildbook.ports:BookTalker.ask`).
5. Nothing else: no settings, routes, tick jobs, persona lines, privacy sources or console assets.

## Decided differently from the plan (and why)

- **Prices, the rate and Settings are read as ASTs, not imported** (D2 allows those imports): `import
  jarvis.llm.pricing` runs `jarvis/llm/__init__` → router → the anthropic SDK and the tool gateway
  (~1 s, half the app). AST reads import nothing and document exactly the checkout given (the fixture
  too). Values are pinned against the imports in `test_book_gen_costs.py` / `test_book_gen_code.py`.
- **`.gcloudignore` added.** Without it `gcloud run deploy --source .` builds its ignore list from
  `.gitignore`, which drops the git-ignored `_book/` — the `make book` line would do nothing. The file
  is gcloud's documented default plus `!src/jarvis/buildbook/_book/`; checked with `gcloud meta
  list-files-for-upload`: the only difference is the three book files.
- **`gen/chunks.py`** (the digest) split out of `show.py` to keep modules ≤ 400 lines.
- **Fake secrets: 14 test/eval files + the fixture (10 distinct strings), not "7"** — the shapes as
  implemented (above) also catch the `sk-ant-…`/`ghp_…` fakes. Lines carry the path and shape.
- Limitations: licence flags first, then plans newest first. Parts = packages **and** top-level
  modules (`alerts`, `cli`, `config`, `keyring`, `logging`, `ticks`); lines count `.py/.js/.mjs/.css/
  .html`, not `static/vendor/`. Every zip entry is 0644 (D5), `create_system` Unix.
- CI deploy: a failure of `pip install` (not the generator) leaves no `release.json` at all →
  `current()` is None ("no build book", no notice). `pip install .` builds in-tree, so
  `src/jarvis.egg-info` rides into the image via `COPY src` (harmless; `PYTHONPATH=src` would avoid it).

## Measured (real repo, `r6-i0` tree + A)

`--check` (two builds): 2.3–2.7 s; book.json ≈ 148 KB; source.zip ≈ 4.3 MB; 31 files left out;
identical bytes from Python 3.11 and 3.12. Scenes 1–11 ≈ 6,250 characters; 58 digest chunks.
