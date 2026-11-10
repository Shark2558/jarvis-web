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

## Fixes (after the security and python reviews of 8d3bf4f)

Every finding was fixed test-first (a failing test, then the fix). Ids: S = security review,
P = python review.

| Finding | Fix |
|---|---|
| S1/P1 HIGH: the deploy job's non-editable install had no `gen/redact.json`, `gen/fake_secrets.txt` | Package data `"jarvis.buildbook.gen" = ["redact.json", "fake_secrets.txt"]`; both loaded through `importlib.resources` (a missing file is still an error). Test: every non-`.py` tracked file under `gen/` matches a package-data pattern. Checked by hand: the built wheel holds both, and its generator loads them. The deploy step also runs with `PYTHONPATH=src` (the same code the PR's `--check` ran). |
| P2: best effort hid the cause | An unexpected error becomes ONE line: type, file name, code place (`unexpected FileNotFoundError (redact.json) at buildbook/gen/scrub.py:180`), never the message or a path. A git failure carries git's first stderr line with paths replaced by `<path>`. |
| P3a: a failed `pip install` left no release.json | `gen/__main__.py` and new `gen/fallback.py` import the standard library only: if the generator's packages are missing, best effort writes the error release.json from git alone (same bytes `write.release_bytes` would write; pinned by a test run in a subprocess with pydantic blocked). |
| P3b/S8b: a stale `_book/` could be served as the new release | `--out`'s `book.json`, `source.zip`, `release.json` (and their `.tmp`) are unlinked first, by name; a failure clears them too. `deploy/cloudrun.sh` runs `rm -f` on those three named files before `make book` (for a missing make/Python). |
| S2: one listed fake PEM would pass every key with its header; the path column was ignored | A private key is matched (scan and scrub) as its whole block, header to END; the allow-list is `(sha256, path)` pairs, a fake passes only in the file it is listed for. `fake_secrets.txt` gained the fixture's in-checkout path and 3 new fakes (see below). |
| S3/P5: PGP keys, Telegram tokens ending in `-`, `bot<id>:` in URLs | `PRIVATE KEY( BLOCK)?`, Telegram `(?<![0-9])…(?![A-Za-z0-9_-])`. Also added (S3's recommendation): `GOCSPX-`, `sk-` (OpenAI-compatible), `sk-or-v1-`, `gsk_`, `tvly-`. |
| S4: phone formats with separators | Mobile with/without `+91`/`0091`/`0` and any single space/hyphen/dot/dash between digits; 11-digit numbers starting with 0 (landlines); `+` numbers with 8–15 digits; 10+ digits in groups of ≥ 3 split by spaces/hyphens. Tests both ways: dates, versions, decimals, prices, IPs, ports, `1 2 3 … 10` are kept. Real book: still 0 `[removed]`; the text is unchanged. Known edge: three 4-digit numbers split only by single spaces (`8080 8098 8085`) now read as one 12-digit number. |
| S5: name bypasses | Names are matched on NFKD with accents and format characters (zero-width, soft hyphen) removed, Cyrillic/Greek look-alikes folded (the table copied from `recall/sensitive.py`), casefolded; also camel-case parts and the word without edge digits. Output text unchanged. |
| S6: URL/host gaps | URL scheme any case; `gs://`, `s3://`, `ftp://`, bare `www.`; an allowed URL with a user part, a percent-encoded e-mail or a secret in it is removed; `*.pkg.dev`, `gcr.io`, `storage.googleapis.com` with their path are hosts. |
| S7: installs ran while holding deploy credentials | The three book steps moved before `google-github-actions/auth`. `.gcloudignore` also leaves out `gha-creds-*.json`. |
| S8a/P8: a dirty tree sealed as HEAD | `Repo.dirty` (`git status --porcelain -uno`); the CLI refuses to WRITE a book (`--out` or the default) for a checkout whose tracked files differ from HEAD, staged or not; with best effort that is the error release ("commit them first"). `--check` without `--out` still builds the working tree (dev loop); CI checkouts are clean. |
| P4: licences depended on the environment | New `requirements.licences.json` (committed beside the lock) holds each locked dist's version and licence; `gen/licences.py` reads it and fails `--check` when it is out of step with the lock (names the packages and the refresh). Refresh: `pip install --require-hashes -r requirements.lock && PYTHONPATH=src python -m jarvis.buildbook.gen --licences`, which refuses if any installed version differs from the lock. Today's table: 47 rows from installed metadata, 16 from the locked wheels (hash-checked against the lock); none "not stated". Result: identical book.json from 3.11 and 3.12 venvs with different installed versions. |
| P6: AST reads fell back silently | `code.tree` returns None only for a module that isn't tracked; a tracked one that isn't UTF-8 or Python fails. `billing/fx.py`, `llm/pricing.py` (keyword `Price(...)` now read), `web/allowance.py`, `quota/ledger.py`, the voice Settings defaults and `keyring.PURPOSES` fail when present but unreadable. |
| P7: `flag_of` | SPDX parsed (AND binds tighter than OR, brackets); a mandatory copyleft part flags. MPL-2.0 (and EPL/EUPL/CDDL) flagged as copyleft like LGPL: the real book gains "certifi (MPL-2.0): copyleft …". |

Not changed: `source.zip` is still not scrubbed (D5/D9: owner-only download of his own tracked files).

**For I1 (supersedes item 4's list):** the scan now also refuses `GOCSPX-`+20, `sk-`+20 (not
`sk-ant-`), `sk-or-v1-`+20, `gsk_`+20, `tvly-`+20, PGP private-key blocks and Telegram tokens in
any position. A fake must be listed as `<sha256>  <path>  # <shape>` for EACH file holding it
(build fakes at run time where possible: `book_gen_fakes.fake_secret`). Any branch that changes
`requirements.lock` must refresh `requirements.licences.json` (the error says how). New files:
`gen/fallback.py`, `gen/runner.py`, `gen/licences.py`, `requirements.licences.json`,
`tests/test_book_gen_cli.py`.
