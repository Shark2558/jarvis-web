# R6 builder B — sealing, retention, download: what I1 must wire

Plan: `docs/plans/r6-build-book.md` (D3, D4, D5, D6, D7, D9 owner capabilities, D14 "what stays",
D16 settings + privacy). Branch `r6-b` from `r6-i0`. No wiring file was edited.

## Files

| File | What |
|---|---|
| `buildbook/seal.py` | `DocsBookVault` = `ports.BookVault` on the Docs port (D6) |
| `buildbook/seal_chunks.py` | `BookChunks`: the chunk documents by path (+ the one listing, for an unreadable index) |
| `buildbook/seal_index.py` | D6 AADs, `BookCrypto` (the R2 vault envelope with the book's AADs), `BookIndex`, `Part`, `checked_files` |
| `buildbook/seal_state.py` | `SealState`: the sealer's `{prefix}book_lease/{uid}` (lease, told, failed, held); `SealHeld` |
| `buildbook/seal_notices.py` | `SealNotices`: `book_sealed` / `book_seal_failed` claimed-then-sent once, the `book_seal` audit |
| `buildbook/seal_words.py` | the notice words and D3's `holds_owner_email` |
| `buildbook/sealer.py` | `BookSealer` (`ensure`, `ensure_bounded`, `hold`, `report_tampered`), `BookSealJob` (re-exports `holds_owner_email`, `Audit`) |
| `buildbook/owner.py` | `BookSettingsStore` (D16), `BookTickets` (D9 download tickets, `UnlockStore` on its own collection) |
| `buildbook/privacy.py` | `BookSealedSource` (`book_sealed`), `BookSessionsSource` (`book_sessions`), `BookSettingsSource` (`book_settings`) |
| `api/book.py` | the 7 B routes of the Contract (I0's stubs filled; paths/methods unchanged) |
| `api/book_gate.py` | what every route passes: `BookRefused`, required parts, console only, limits, the ● session |
| `api/book_status.py` | `GET /v1/book`'s body |
| `evals/r6_book/seal.py` | eval part `seal`, `BUILT = True`, control = retention 4 |
| tests | `test_book_{seal,sealer,seal_races,owner,api,privacy}.py`, `test_book_seal_firestore.py`, fakes `tests/book_seal_fakes.py` |

## Storage (Firestore, by path; one plain listing; no composite index)

    {prefix}book/{uid}                          {rev, kid, blob}   blob = BookIndex sealed under book_index
    {prefix}book/{uid}/book_chunks/{fid}_{nn}   {blob, n, of, at}  512 KiB chunks (~700 KB a document)
    {prefix}book_lease/{uid}                    {holder, until, told[], failed[], held}
    {prefix}book_tickets/{uid}                  {grants: [], tickets: [{mac, item, fid, session, until}]}
    {prefix}book_settings/{uid}                 {creator_name, show_voice, talk_on, allow_training_brain, updated_at}

The only query lists `{prefix}book/{uid}/book_chunks` (no `where`, no order, 200 a page), and only
when Privacy deletes an index that won't open.

## `wire_r6` (after wire_r4; book OFF = every attribute None)

```python
from jarvis.api.identity import primary_user_id
from jarvis.buildbook.owner import BookSettingsStore, BookTickets
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.sealer import BookSealer
from jarvis.keyring import Keyring

# None -> the book is OFF (D6): leave B's state None
ring = Keyring.from_settings(s)
p, mb = s.firestore_prefix, s.book_max_total_mb
st.book_vault = DocsBookVault(docs, ring, prefix=p, limit_mb=mb)
# book_source = A's release.py BookSource; audit = the gateway's chain wire_r6 gets
st.book_sealer = BookSealer(
    st.book_source,
    st.book_vault,
    docs,
    notifier=_notifier(app),
    audit=audit,
    owner_emails=s.owner_emails,
    honorific=s.user_honorific,
    limit_mb=mb,
    prefix=p,
)
st.book_tickets = BookTickets(docs, ring, prefix=p)
st.book_settings = BookSettingsStore(docs, prefix=p)
```

- **Add `"book_tickets"` and `"book_settings"` to `R6_STATE`** (my routes read both per request;
  `wire_r6` must set them, None when off).
- **Never seal at start-up (D7)**: do not call `ensure` in `wire_r6` or the lifespan. Building the
  sealer does no I/O (pinned by `test_building_the_sealer_touches_nothing`).
- `_notifier(app)` must exist when `wire_r6` runs (it is `app.state.notify` or the direct sink);
  the sealer sends `Signal(source="system", kind="book_sealed" | "book_seal_failed")`.

## Tick jobs (`r6_tick_jobs`)

`BookSealJob(st.book_sealer, primary_user_id(s))` (name `book_seal`, budget 45 s; it ignores the
owners the tick passes and seals for the primary owner only). Add it to `_tick_jobs` AND to R5.1's
5-minute watchdog (`app.state.home_watchdog.extend(job)`). Recommend adding `book_seal` to
`home/watchdog.py` `ADVISORY_JOBS` (a seal failure is already told to the owner once by
`book_seal_failed`; it must not 503 the watchdog and make Scheduler retry).

## Privacy sources (`privacy_sources`)

```python
BookSealedSource(st.book_vault, st.book_sealer, limit_mb=s.book_max_total_mb)
BookSessionsSource(st.book_sessions, end=<C's BookService privacy close>, session_minutes=s.book_session_minutes)
BookSettingsSource(st.book_settings)  # added by the review fixes (see Fixes, security 7)
```

`end(uid) -> int` must run D14's close with reason `privacy` (audit `book_close`, wipe, notice) and
return 1/0. Without `end`, the source closes through `BookSessions.close(..., reason="privacy")`.
Sealed delete = passkey class (the dashboard's `privacy_delete`); it first `hold`s the current
release so the sealer doesn't re-seal it (the next release seals as usual), then crypto-shreds all.

## What my routes need from C (read live from `app.state`)

- `book_sessions.resolve(uid, token, now=)` -> `SessionView` / `SessionGone`; `.live(uid, now=)`
  (the download checks that the ticket's session is still the live owner one).
- `book_service.resolve(uid, token, now=)` is used INSTEAD of `book_sessions.resolve` whenever
  `app.state.book_service` has one (C's `BookService.resolve` finishes an expired/idle session:
  audit `book_close` + `book_session_closed`, D14). See Fixes, security 3.
- Optional: `book_lock.get(uid)` (unreadable -> status reports `lock.on = true`),
  `book_talk.state(uid)` -> `TalkState`, `book_service.last_closed(uid)` -> JSON-ready dict or None
  (D14's `{last_closed_at, notified}`; a pydantic model is dumped). Missing ones get defaults.
- C's talk/service should read Book settings with `app.state.book_settings.get_or_default(uid)`
  (never raises; safe defaults: no training brain): `creator_name` -> `lines.credit_by`,
  `talk_on`, `allow_training_brain`, `show_voice`.

## Contract notes for D (and the lock allow-list)

- `GET /v1/book` adds two fields to the Contract: `sealing` (true -> show "Sealing this
  release..." and ask again) and `sealed_ok` (false -> the sealed index failed its check or can't
  be read; `sealed` is then empty). `session` has no `session_id`. `open.fresh_left_s` is null
  for a non-browser caller. `GET /v1/book/settings` adds `creator_max: 40`.
- Errors: `book_off` 503 (part not wired), `session_gone` 401, `owner_only` 403, `console_only` 403
  (bearer), `not_found` 404, `no_book` 404, `tampered` 503 (+ one `book_seal_failed` per release),
  `unavailable` 503, `gone` 410 (ticket used/expired/foreign), `rate_limited` 429 (10 tickets / 10
  downloads / 30 settings changes a minute), `input_rejected` 422 (never echoes the input).
- Download is a plain `GET /v1/book/download/{ticket}` (cookie, no `X-Jarvis-Book`): `application/
  zip`, `attachment; filename="JARVIS-source-<id>.zip"`, `no-store`, `nosniff`; audited
  (`book_download`, `{release}`) BEFORE any byte is sent.
- None of B's routes belongs in the D10 lock allow-list: `/v1/book`, `/sections`, `/releases/*`,
  `/download/*`, `/settings` must answer 423 under a guest lock.
- `install_book` registers an exception handler for `api.book.BookRefused` only.

## Tests and evals I1 runs/updates

- `tests/test_r6_contract.py` (I0's) passes only while B's state is None (every route `book_off`);
  once wired, update its first test to expect the real answers for B's 7 routes.
- `evals/r6_book/seal.py` imports `book_seal_fakes` from `tests/` (run.py puts it on the path).
- `test_book_seal_firestore.py` runs on MemoryDocs and, with `FIRESTORE_EMULATOR_HOST`, on the
  emulator (no emulator in this sandbox: those 4 skipped).

## Binding decisions relied on, and where I decided

- D6 AADs word for word; R2 envelope reused (`Keyring.wrap/new_dek`, `TokenCipher`,
  `vault.crypto.CHUNK_BYTES/chunk_count`); `book_index` purpose for the index; <= 6 chunks a
  commit, index last; prune index first then chunks; failed reads fail closed.
- **Index blob = `{v, releases, pending, orphans}`** (D6 says "the release list"): the pending and
  orphan chunk sets are R2's design so a seal cut off mid-way and a failed chunk delete are swept by
  the next run; they are inside the sealed blob (nothing in clear but `rev` and `kid`).
- D7: the lease doc also holds `told` and `failed` (lists, each claimed in a transaction before
  the notice and given back if it can't go, so two runs tell once, across restarts and rollbacks),
  `held` (Privacy hold, also read by the vault's seal transactions).
- D3 runtime check: whole-word, NFKC, case-folded, JSON escapes undone; local parts shorter than 3
  characters are not checked (common words).
- Over the cap: the oldest releases are pruned one at a time before sealing so the new one fits
  (the newest always stays; if even that can't fit, nothing is pruned and the owner is told once).
- Retention is `KEEP` (3); `BookSealer(keep=)` exists only for the eval's control.
- Audit tool names: `book_seal` (agent `book`: release, label, removed ids, MB), `book_download`
  (agent `owner`), `book_settings` (field names only, never the creator's name).

## Fixes (review: `review-B-security.md`, `review-B-python.md`)

Each fix has a test written first and seen failing (new file `tests/test_book_seal_races.py`;
additions in `test_book_api.py`, `test_book_owner.py`, `test_book_privacy.py`,
`test_book_seal_firestore.py`).

| Finding | What changed |
|---|---|
| sec 1 / py 5 (MEDIUM/LOW) Privacy delete vs a seal in flight | The sealer re-reads `held` under the lease before it reads or encrypts anything; and BOTH index transactions of `DocsBookVault.seal` (pending, commit) read `{prefix}book_lease/{uid}` and raise `SealHeld` when `held` is that release, so every interleaving of hold + `delete_all` with a seal ends with nothing sealed and no notice (no "I'll try again" either). Chosen over "Privacy takes the lease": a request would otherwise wait up to 120 s. |
| py 5b (LOW) the empty index removed outside a transaction | `_drop_index` deletes it in a transaction only while it is still empty: a seal that lands meanwhile keeps its entry. |
| sec 2 / py 9 (MEDIUM/LOW) an index that won't open can't be deleted | `BookSealedSource.describe` shows it (count unknown, delete = passkey, "can't be read ... Delete removes them all"); `delete_all` on `VaultTampered` deletes every chunk found by listing `book_chunks`, then the index while it still won't open. An outage is never taken for tampering. Sealing resumes afterwards. |
| py 1 (MEDIUM) `told` held one id | `told` is a list (newest 8), claimed by membership: a rollback or traffic split never tells again. |
| py 2 / sec 6 (MEDIUM/LOW) `book_seal_failed` read-then-send | `failed` is claimed in a transaction before the notice goes and given back when it can't go (as `told`); cap 8 -> 32 (a handful of keys a release), so an old failure is never told again. Not "reset per current release": that would re-tell on every rollback alternation. |
| py 3 (MEDIUM) one prune to make room | `_room` keeps the newest releases that fit beside the new one, dropping the oldest one at a time (the newest always stays); when even that can't fit, nothing is pruned and `book_seal_failed` goes once (`<rid>:limit`, "doesn't fit in the build book's N MB storage limit ... Raise the limit (book_max_total_mb)"). |
| py 4 (LOW) extract at 360 | seal.py -> `seal_chunks.py` (chunk I/O), `seal_index.py` (`checked_files`, `seal_file`); sealer.py -> `seal_notices.py` (telling + audit), `seal_words.py` (words, D3 check); api/book.py -> `api/book_gate.py`. |
| py 6 (LOW) malformed settings JSON | `PUT /v1/book/settings` parses the body itself (<= 4 KB): any JSON/encoding/validation error is 422 `input_rejected`, no-store, never echoed. |
| py 7 (LOW) a crash or outage only logged | `ensure` (BookError) and `ensure_bounded` (anything) tell `book_seal_failed` once for the current release, best effort. |
| py 8 (LOW) silent fail-closed parts | `GET /v1/book` logs "book lock unreadable" / "book passkey state unreadable" with the class name. |
| py 10 (LOW) test quality | bad tickets assert `410 gone`; the eval's `tampered_chunk` says the route is covered by `test_book_api.py`. |
| sec 4 (LOW) ticket outlives its session | A ticket row holds the asking session's id; it lives `min(60 s, session.until, session.idle_until)` (none if already over: 401); the download needs that session to still be `book_sessions.live`'s owner session (else 410). `BookTickets.issue(..., session=)` is now required; `BookTickets.clear(uid)` drops them all. |
| sec 5 (LOW) bare 500s | `owner_session` maps anything but `SessionGone` to 503 `unavailable`; `GET /v1/book` and `sections` do the same for a broken source (no-store, `{error, detail}`). |
| sec 7 (LOW) the creator name not in Privacy | New row `BookSettingsSource` (`book_settings`, "Settings and safety"): export = the Book settings; delete = simple, clears the creator name only (the talk-through's choices stay). Additive to D16's two rows; I1 registers it, or folds it into the existing settings row if preferred. |

### Cross-part seam left to I1 / C (security 3, MEDIUM)

Not fixed in C's code (not B's). B's side is ready: `api/book_gate.owner_session` resolves through
`app.state.book_service.resolve` whenever the service has one, so C's `BookService.resolve`
(which catches `SessionEnded`, writes `book_close` and sends `book_session_closed`) runs for B's
● routes too; pinned by `test_the_routes_resolve_through_the_book_service_when_it_is_wired`.
**I1 must**: set `app.state.book_service` to C's `BookService` in `wire_r6` (it already reads its
`last_closed`), and have C's close call `app.state.book_tickets.clear(uid)` (defence in depth: the
download already refuses a ticket whose session is no longer live).

### Still for I1

- Add `book_seal` to `home/watchdog.py` `ADVISORY_JOBS` (now firmer: a release over the storage
  limit fails every run until the owner raises the limit; he is told once).
- Register `BookSettingsSource` (above).
