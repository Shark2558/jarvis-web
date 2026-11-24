Version v6.3.1 · 24 Nov 2026, 07:30 IST · Release R6.3.1 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3.1 combined review of I1 (fresh context, 24 Nov 2026)

Reviewed: `r6-3-1-i1` @ `6ee2d64` against `main` @ `598ee82`, with `git diff origin/main...HEAD`
(333 files: the code, 153 authored pages and 46 flowcharts), the plan
`docs/plans/r6-3-1-book-at-build.md` (D1 to D10) and `src/jarvis/buildbook/book/AUTHORING.md`. One
reviewer for 🛠 Mark XXIV, security first, then code and Python, by the rules in `.claude/rules/ecc/`.
By the owner's rule this is the only review round: the reviewer fixed what it found, each fix with
its failing test first, on `r6-3-1-review`, then ran the one final check pass.

**Verdict at I1's head: BLOCK** (H-1: the whole unit suite was red, so CI's test job fails).
**After the fixes: APPROVE.** CRITICAL 0 · HIGH 1 · MEDIUM 4 (all fixed) · LOW 12 (five fixed,
seven noted) · one pre-existing MEDIUM outside this release (P-1, reported with a proposed fix, not
changed: the owner's rule is to explain first and fix on his OK).

## What holds

- **The pages routes' gates are R6.3's, unchanged and tested** (`api/book_pages.py`,
  `tests/test_r631_e_serve.py`): signed in (`require_auth`), the primary owner only (another owner
  e-mail is 403 `not_primary`), an OWNER book session's `X-Jarvis-Book` (a guest's is 403
  `owner_only`, no token 401 `session_gone`), `console_only` after the session (a bearer script
  with an owner's book token is 403 `console_only`, R6.3 review L-1 kept), `Cache-Control: no-store`
  (`book_json`), 60 a minute per owner. The order of the gates is the one R6.3 shipped. The
  `release` query and the page id are checked against `RELEASE_ID` and `PAGE_ID` before use. A
  guest can never read the full book: every route needs an owner session, and the show lock
  answers a guest's console as before.
- **Serving** (`writer/serve.py`): R6's vault index is read on every call, so a Privacy delete is
  never outlived; the two files are opened once per release and cached by (owner, release,
  pages SHA-256, flows SHA-256), at most four; a release sealed before v6.3.2 is 404 `no_pages`;
  a vault that can't be read, a file that fails its check or names another release is 503
  `unavailable`, logged by type only. The sealed bytes are AES-256-GCM chunks checked against the
  index's size and SHA-256 (`seal.DocsBookVault.read`), the pages file is at most 2 MiB gzipped
  and 32 MiB once open (a gzip bomb stops at the cap before parsing), the flows file 1 MiB, and
  every flow is validated again as a `FlowSpec` (extra fields refused) before it is served.
- **Sealing** (`sealer.py`, `seal_index.py`): a release seals its pages and flows only when
  release.json names their SHA-256, each under its cap and matching; the owner-address check reads
  the book, the opened pages file and the flows file; a pages file that won't open is never sealed
  unread.
- **Authored files** (`book/files.py`, `book/authored.py`): YAML through `yaml.SafeLoader` and
  `yaml.safe_load` only, anchors and aliases refused before loading (no alias bomb), 256 KiB a page
  and 64 KiB a flowchart, UTF-8 only, no NUL, a duplicate JSON key refused; the file name must be a
  page id and equal `page:`; `sources` keys are only compared, never opened (staleness hashes the
  INDEX's refs through `Repo`, which never follows a link). `--stamp` takes only indexed page ids
  and writes only `book/pages/<id>.md` (a temporary file beside it, then a rename). Errors name the
  file and the rule, never its content.
- **The flowchart renderer** (`console-book-flow.js`, `console-book-flow-layout.js`): every node,
  edge and label re-checked in `normalFlow` (ids against a slug pattern, kinds by `Object.hasOwn`,
  ranks and columns as bounded integers, invisible characters stripped, lengths capped); the DOM is
  built with `createElementNS`, `createElement`, `setAttribute` and `textContent` only (no
  `innerHTML` anywhere in the three Book modules); the module is imported once with a relative
  `import('./console-book-flow.js')`, same origin, under `script-src 'self'`; a chart that fails
  leaves its page as it was. The browser suite's hostile-flow case passes (text stays text).
- **Privacy, "Book writer (old trial)"** (`writer/privacy.py`, `privacy/ports.py`): every query
  is `where owner == uid` or under that owner's own document path; delete is `passkey` (the
  Privacy service's rule) and removes only that owner's old writer records, the chunks first, in
  groups of 200; export is counts, his pick and his YES records, never page text; the row leaves
  the list only when a check finds it empty (a failing check still shows it). Another owner's
  records stay (tested).
- **The runtime writer is gone**: no route under `/v1/book/writer` (404, tested), no
  `book_write` job on the tick, the clock or the watchdog, no `llm/write.py`, no
  `AnthropicProvider.no_retry`, no `console-book-writer.js` or its CSS, nothing in the console
  calling a writer route; the routes table names the two pages routes only.
- **No personal data in the public pages**: the scrubber over all 153 pages and 46 flowcharts
  finds nothing; a search for the owner's name, employer, home city, phone numbers, e-mail
  shapes, web addresses and long digit runs finds one made-up tracking number in an example
  (`pg_card_c27`). The private words file was never opened.

## Findings

| ID | Severity | Where | What, and why it matters | Fix |
|---|---|---|---|---|
| H-1 | HIGH | `tests/test_markdy_export.py:666`, `static/console-book-flow.js:2`, `book/pages/pg_chapter_technology.md`; `tests/r63_fakes_a.py:219,243` | The whole unit suite was red at I1's head, so CI's `test` job (3.11 and 3.12) fails and the release can't merge; I1 ran only the touched test files. (a) `test_nothing_the_app_ships_mentions_markdy`: the flowchart module's header said "no Markdy", and the Technology chapter names the dev tool's lock file as data (its sources and its words). (b) `test_row380_every_tour_key_is_known`: I1 made `release.new` read the plan with this exact version and took the R6.3.1 row out of the guide's roadmap, but the pins of this checkout's own values still named R6.3's title and the old roadmap. | `3722211`: the comment says "no diagram tool"; the guard takes out that one path in the written pages' folder too (as R6.3 review M-6 did for the generator's folder), nothing else. `6e84726`: the pins name "The Build Book written at build time", then "R6.4, the Book's new look" and "Calls" (the facts the real build makes) |
| M-1 | MEDIUM | `book/files.py:_read`, `book/authored.py:judge` | A page or flowchart file that is a symbolic link was followed when read by its page id: `all_pages` refuses links, but its error is dropped for an indexed id and `judge` (the check and the generator's compile) opened the link's target. A committed link could feed any file on the build machine into the check, the compile and the sealed full book. | `6184838`: `_read` refuses a link (`is a link`), whichever way the file is read; test `test_m1_…` |
| M-2 | MEDIUM | `book/files.py:_yaml`, `load_flow`; `gen/compile_pages.py` | A front matter or a flowchart nested past Python's recursion limit raised `RecursionError` (not `AuthoredError`): `pages --check` crashed, and in the deploy's best-effort build ONE such page made the whole build fail, so the release went live with no Book at all (no tour, no seal), against D4 ("a page never breaks the build"). | `6184838`: both map `RecursionError` to one plain `AuthoredError`; the compile treats a page whose check raises anything as the generator's text (`_served`; `pages --check` still stops on it); tests `test_m2_…` |
| M-3 | MEDIUM | `gen/repo.py`, `gen/snapshot.py` | The sealed code snapshot (`source.zip`, the owner's code download) left out the whole `src/jarvis/buildbook/book/` folder, because the snapshot zips `Repo.files`, which leaves the folder out for the index: the download lacked `jarvis.buildbook.book.*` (imported at run time by `writer/pages.py`), the guide and the pages, so it was not the release's code and would not run. | `6184838`: `Repo.book_files` lists the folder's tracked files for the snapshot only (never the index, the refs, the facts or the cache key); the real build's `source.zip` now holds its 207 files; test `test_m3_…` |
| M-4 | MEDIUM | `model.py:SealedRelease`, `docs/plans/r6-3-1-book-at-build.md` | No rollback note. A release v6.3.2 seals has four files; v6.3.1's model takes exactly two (probed against `main`'s `model.py`: a four-file release is a ValidationError, a two-file one reads), so after a rollback the WHOLE vault index fails its check: no kept release opens and the sealer sends "your sealed build books failed their integrity check". Nothing is overwritten; Privacy → Delete would delete the unreadable index. | `8c25373`: the plan's Risks and the owner's steps say so (nothing lost, roll forward, don't press Delete, it isn't tampering). A code fix would need a separate index (R6.3's design) and is not cheap |
| L-1 | LOW | `writer/pages.py:unzipped`, `decode_flows` | A bad deflate block raised `zlib.error`, deep JSON `RecursionError`: neither a `ValueError`, so serving would be a bare 500 and the seal run would crash instead of refusing. Reachable only through a broken build (the bytes are AEAD- and SHA-256-checked). | `6184838`: both are `ValueError` (503 `unavailable`, seal refused); tests `test_l1_…` |
| L-2 | LOW | `docs/architecture/JARVIS-Architecture.md` C57 | "R6.3 (built and joined at its I1, not yet deployed)" while the guide's opening says v6.3.0 is live. | `8c25373`: "R6.3 (v6.3.0, live)"; guide v6.3.5 |
| L-3 | LOW | `book/flows/pg_module_vault.json`, `pg_module_home.json` | The vault chart chained "You confirm the expiry" before opening a file (the code has no such order); the home chart's "Disarm: passkey first" left out the fresh Google sign-in the page and `api/camera.py` allow. | `8c25373`: the expiry is a side path off "Sealed in the vault", which leads to the unlock; "Disarm: passkey or sign-in" |
| L-4 | LOW | `book/pages/pg_card_c68.md` (When it fails) | "a brain that trains on content still gets none" is true (`core/brain.py`, `llm/brains.py:tools_allowed`) but cited to `skills/offer.py`, which only narrows tools. | Noted, not changed: true, and the right files aren't in the page's may-cite list |
| L-5 | LOW | `writer/model.py:CheckCode` | R6.3's writer-only codes `incomplete`, `empty`, `tier`, `model` were left in the type; nothing produces them. | `6184838`: taken out |
| L-6 | LOW | `writer/serve.py:BookPages._open` | After a Privacy delete the decrypted files of up to four releases stay in memory until evicted. Never served (the index is read first) and the pages are the public text. | Noted |
| L-7 | LOW | `api/r6_wiring.py:210` | The pages limit moved from R6.3's 60-in-any-minute window on the Book's clock to R6's token bucket (`RateLimiter(60)`: a burst of 60, then one a second). Still 60 a minute; tests that set the Book's clock can't move it. | Noted |
| L-8 | LOW | `gen/repo.py:from_git` | The "uncommitted changes" rule leaves out the whole Book folder, its Python modules too, so a local `--out` build is not refused for an edited `book/authored.py` (and, with M-3, such a file goes into that local snapshot). The deploy builds a clean checkout. | Noted |
| L-9 | LOW | `.github/workflows/ci.yml` docs-check | "GitHub refuses to merge a release whose pages are out of date" holds only if `docs-check` is a required check in the branch protection, which the repository can't show; no job waits for it. | Noted for the owner: make `docs-check` required |
| L-10 | LOW | `api/r6_wiring.py:wire_book` | 52 lines (the soft limit is 50). | Noted |
| L-11 | LOW | the guide's change log | I1's row says "24 Nov 2026, 06:30 IST", after its own commit (05:26 IST) and after this review. | Noted (history is not rewritten) |
| L-12 | LOW | `book/flows/pg_module_home.json` | Seen in the screenshots of the REAL compiled chart: the "laptop silent" pill of the bridge-to-watchdog side path lay across the main path, reading as if the main path carried it. | `1eb5e3b`: that side path has no label (the node says "No heartbeat: told once"); shot again, clean |
| P-1 | MEDIUM (pre-existing) | `src/jarvis/config.py:40-45` (`_is_private_host`), since `f285902` | See "The `*.ts.net` question" below. | Proposed, not changed |

## The `*.ts.net` question (P-1, pre-existing)

**Verdict: real, MEDIUM, not CRITICAL; reported, not changed.** `_check_base_url` lets
`openai_compat_base_url` use `http://` when `_is_private_host(host)` is true, and that is true for
ANY name ending in `.ts.net`. Plain HTTP to a Tailscale name is safe only from a machine on the
same tailnet (MagicDNS answers a 100.x address and WireGuard encrypts the hop). JARVIS runs on
Cloud Run, which is not on the tailnet: there a `*.ts.net` name resolves through public DNS, and
only a Tailscale Funnel name resolves at all, to Tailscale's public relays, which take TLS only
(ports 443, 8443, 10000, routed by SNI). With `http://<machine>.<tailnet>.ts.net:443/v1` (or 8443,
10000) the TCP connection opens and httpx sends the request line and its headers, the
`Authorization: Bearer <openai_compat_api_key>` among them, in clear text across the public
Internet before the relay drops the non-TLS bytes. On port 80 the result depends on what
Tailscale's relays listen on: Unverified. It needs the owner to type an `http://` Tailscale
address with a key, so it is unlikely, but it is exactly the leak the validator exists to stop
("a bearer key must never travel in cleartext to a remote server"); the laptop's own offline
brain already refuses anything but `https://<machine>.<tailnet>.ts.net` (`offline/config.py`).

**Proposed fix (on the owner's OK):** take `.ts.net` out of `_is_private_host`, so a Tailscale
name needs `https://` (Serve and Funnel give it a certificate), or keep `http://*.ts.net` only
when no `openai_compat_api_key` is set (nothing to leak); a test each way; then refresh the three
pages that describe the rule (`pg_service_tailscale`, `pg_service_openai_compatible`,
`pg_card_c49`) in the same pull request, as CI will ask.

## The content sample (20 pages, 5 flowcharts)

Twenty pages drawn at random (seed 631), at least two of each kind; two or three claims of each
checked against the code. **No untrue sentence found**; one loose citation (L-4).

| Page | Claims checked against the code |
|---|---|
| `pg_chapter_setup` | dev settings refuse to start on Cloud Run (`config._refuse_dev_on_cloud_run`); a missing Claude key or bearer token stops start-up (`Settings` validator); an unknown `--brain` exits with the configured list (`cli._resolve_brain`) |
| `pg_chapter_data` | Firestore in the Mumbai region (`deploy/cloudrun.sh`, `asia-south1`); a changed category is 409 at delete (`api/privacy.py`); the drill deletes its copy on failure (`backup/drill.py`) |
| `pg_chapter_example` | a spoken turn always asks first, whatever the rule (`tools/gateway.py`); no copy kept, nothing deleted (`calendar_undo.delete_kept`); the monthly limit checked before a paid call (`core/brain.py:_admit`) |
| `pg_module_people` | `_prove` asks for the passkey or a fresh sign-in and the delete is console only (`api/faces.py`); JPEG or PNG only and the 0.9 threshold (`homebridge/faces.py`); the exact Frigate words |
| `pg_module_vault` | archive refusals from the directory alone (`documents/archive.py`); the unlock by passkey or fresh sign-in, audited first (`api/vault.py`); "Open it again." (`api/vault.py:370`) |
| `pg_module_home` | the disarm through `audited_disarm`, console only (`api/camera.py`); the one "couldn't arm" alert (`camera/alarm.py`) |
| `pg_module_integrations` | a stranger gets no reply and is audited (`telegram/service._stranger`, `_reject`); the webhook answers only with its secret header (`api/telegram.py`, `SECRET_HEADER`) |
| `pg_card_c04` | the busy, limit and too-slow lines word for word (`telegram/service.py:73-75`); the pairing code rules |
| `pg_card_c07` | hidden sheets are named, never read (`documents/sheets.py`); a picture only to a brain that sees and never trains (`llm/brains.sees_pictures`) |
| `pg_card_c08` | consent renewal after a year (`faces/consent.renewal_due`); a greeting never lowers an alert (`faces/greeting.py`) |
| `pg_card_c12` | a restored event never carries guests (`calendar_undo.restore_body`); Remove now needs the passkey for the final kinds (`api/deleted.py`) |
| `pg_card_c34` | Sheets read as their first sheet only (`drive/service.py`); the extracted text kept in memory only, for `TEXT_CACHE_S` (600 s) |
| `pg_card_c68` | the cache point on the last message (`anthropic_provider._mark`); the catalogue failure offers every tool (`skills/part.py`); L-4 |
| `pg_screen_connectors` | the three card lines word for word (`console-connectors.js`) |
| `pg_screen_brief` | "Today's brief didn't finish.", "Brief limit reached for today.", "Couldn't check today's brief.", "Connect Google to see your calendar here." (`console-brief.js`) |
| `pg_screen_memory` | the private-data refusal and "Memory is full" (`console-memory.js`); FORGET keeps the switches (`api/memory.py:23`) |
| `pg_service_google_cloud_text_to_speech` | nothing retried, one deadline (`voice/google_cloud.py`); "Google rejected that voice or text." (`:95`); the en-GB voices (`voice/catalogue.py`) |
| `pg_service_google_tasks` | the Grant words (`tools/tasks_api.py:52`); bounded reads (facts) |
| `pg_service_google_agent_platform` | no redirects (`llm/tryon_gemini.py:308`); a blocked picture is billed, a refusal before sending never is |
| `pg_service_anthropic` | strong to balanced to fast, an unreachable cloud or "no credit" to the laptop, a 4xx never (`llm/router.py`); the day's rate with the setting as fallback (`billing/service.py`) |

Flowcharts read against their pages: `pg_chapter_example`, `pg_chapter_setup`, `pg_module_people`
(logic matches), `pg_module_vault` and `pg_module_home` (fixed, L-3), then drawn from the REAL
compiled files in the screenshots below.

## The final check pass

Run once on the review branch, heavy runs one at a time behind `flock /tmp/jarvis-heavy.lock`.

| Check | Result |
|---|---|
| Unit, Python 3.12, whole suite with coverage | The first run (`-x`) stopped at H-1 (a). After its fix the whole suite ran again in the background and was stopped at 73 % (0 failures) when the session's environment restarted; it was then run in ten chunks in the foreground with `--cov-append`: **19,214 passed, 1 failed, 51 skipped**. The one failure was H-1 (b), fixed in `6e84726`; its file then ran again: 9 passed. **Coverage 95.65 %** (floor 95, target 80; ≈ 95.6 % before). |
| `ruff check src tests evals` | All checks passed |
| `ruff format --check` (the files this review touched) | 9 files already formatted |
| mypy | The touched modules: no issues (8 files). `mypy src`: 1 error, the known baseline `memory/redis_store.py:67` |
| Mock evals (`evals/run_all_mock.py`, venv-b) | **ALL MOCK EVALS: PASS**; R6.3's suite 27/27 with its control failing it, R6's book 168/168, every other suite passing with its negative control |
| `scripts/check_doc_versions.py` | All 32 documents have their version line and change log |
| `scripts/arch_coverage.py` | OK: 66 packages and modules, 109 console modules, 2 Scheduler jobs, 31 outside services, 126 Firestore collections |
| `pages --check` (strict, every page) | **153 ok, 0 stale, 0 failing, 0 missing; 0 problems**, exit 0 (again at the head this file is committed on) |
| The real compile (`gen --out /tmp/r631-book` @ `1eb5e3b`) | book.json 302,889 B · facts.json 1,011,129 B · **pages.json.gz 200,153 B (153 written, 0 the generator's)** · **flows.json 70,227 B** · source.zip 10,666,950 B (98 files left out; 207 of the Book folder now in it, M-3) · release.json 666 B, naming both new SHA-256s |
| The Book's browser files (venv-c): `test_r631_f_flow.py`, `test_r63_c_pages.py`, `test_r63_c_look.py`, `test_book_panel.py` | **42 passed** (168 s) |
| Screenshots, looked at | `/tmp/r631-review-shots/`: the Full book reader on the REAL compiled module pages `pg_module_vault` and `pg_module_home` (served from this build's `pages.json.gz` and `flows.json`), desktop 1280 and phone 390, Night and Day, the panel and the whole figure (16 pictures); F's test pictures in `fakes/` (13). In the console's own tokens, nothing clipped or foreign; one overlap found and fixed (L-12) |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 24 Nov 2026, 07:30 IST | R6.3.1 | First edition: the combined security, code and Python review of I1 @ `6ee2d64` (BLOCK on H-1), the fixes (H-1, M-1 to M-4, L-1, L-2, L-3, L-5, L-12) with their commits, the `*.ts.net` verdict (P-1, not changed), the content sample, the final check pass and the verdict after the fixes | 🛠 Mark XXIV |
