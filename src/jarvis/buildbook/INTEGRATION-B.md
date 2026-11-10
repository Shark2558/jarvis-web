# R6 builder B — sealing, retention, download: what I1 must wire

Plan: `docs/plans/r6-build-book.md` (D3, D4, D5, D6, D7, D9 owner capabilities, D14 "what stays",
D16 settings + privacy). Branch `r6-b` from `r6-i0`. No wiring file was edited.

## Files

| File | What |
|---|---|
| `buildbook/seal.py` | `DocsBookVault` = `ports.BookVault` on the Docs port (D6) |
| `buildbook/seal_index.py` | D6 AADs, `BookCrypto` (the R2 vault envelope with the book's AADs), `BookIndex`, `Part` |
| `buildbook/seal_state.py` | `SealState`: the sealer's `{prefix}book_lease/{uid}` (lease, told, failed, held) |
| `buildbook/sealer.py` | `BookSealer` (`ensure`, `ensure_bounded`, `hold`, `report_tampered`), `BookSealJob`, `holds_owner_email` |
| `buildbook/owner.py` | `BookSettingsStore` (D16), `BookTickets` (D9 download tickets, `UnlockStore` on its own collection) |
| `buildbook/privacy.py` | `BookSealedSource` (`book_sealed`), `BookSessionsSource` (`book_sessions`) |
| `api/book.py` | the 7 B routes of the Contract (I0's stubs filled; paths/methods unchanged) |
| `api/book_status.py` | `GET /v1/book`'s body |
| `evals/r6_book/seal.py` | eval part `seal`, `BUILT = True`, control = retention 4 |
| tests | `test_book_{seal,sealer,owner,api,privacy}.py`, `test_book_seal_firestore.py`, fakes `tests/book_seal_fakes.py` |

## Storage (Firestore, all by path; no query, no composite index)

    {prefix}book/{uid}                          {rev, kid, blob}   blob = BookIndex sealed under book_index
    {prefix}book/{uid}/book_chunks/{fid}_{nn}   {blob, n, of, at}  512 KiB chunks (~700 KB a document)
    {prefix}book_lease/{uid}                    {holder, until, told, failed[], held}
    {prefix}book_tickets/{uid}                  {grants: [], tickets: [{mac, item, fid, until}]}
    {prefix}book_settings/{uid}                 {creator_name, show_voice, talk_on, allow_training_brain, updated_at}

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
```

`end(uid) -> int` must run D14's close with reason `privacy` (audit `book_close`, wipe, notice) and
return 1/0. Without `end`, the source closes through `BookSessions.close(..., reason="privacy")`.
Sealed delete = passkey class (the dashboard's `privacy_delete`); it first `hold`s the current
release so the sealer doesn't re-seal it (the next release seals as usual), then crypto-shreds all.

## What my routes need from C (read live from `app.state`)

- `book_sessions.resolve(uid, token, now=)` -> `SessionView` / `SessionGone`; `.live(uid, now=)`.
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
- D7: the lease doc also holds `told` (claimed in a transaction before the notice, so two runs tell
  once), `failed` (one notice per release and cause, across restarts), `held` (Privacy hold).
- D3 runtime check: whole-word, NFKC, case-folded, JSON escapes undone; local parts shorter than 3
  characters are not checked (common words).
- Over the cap: the oldest release is pruned before sealing so the new one fits (then prune to 3).
- Retention is `KEEP` (3); `BookSealer(keep=)` exists only for the eval's control.
- Audit tool names: `book_seal` (agent `book`: release, label, removed ids, MB), `book_download`
  (agent `owner`), `book_settings` (field names only, never the creator's name).
