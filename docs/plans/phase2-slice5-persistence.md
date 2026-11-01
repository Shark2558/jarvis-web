# Phase 2 · Slice 5 — Persistence: conversations, approvals and the audit chain survive scale-to-zero

Status: DONE · 2026-11-01 · 165 tests (+27 on the Firestore emulator in CI) · ECC loop · two fresh-context reviews: 2 HIGH + 5 MEDIUM found and fixed (see end)

## Problem
Cloud Run scales JARVIS to zero when idle. Sessions, pending approvals and the hash-chained
audit live in process memory, so every cold start wipes them. The console also forgets the
open conversation on reload, so even a persistent store would be invisible to the owner.

## Decision: Firestore (Native mode, Standard edition) in the owner's own JARVIS project
Free options checked 2026-11-01:

| Option | Free allowance (verified) | Owner effort | Privacy | Fit |
|---|---|---|---|---|
| **Firestore, same GCP project, asia-south1** | 1 GiB stored, 50k reads/day, 20k writes/day, 20k deletes/day, 10 GiB egress/month; one free DB per project (firebase.google.com/docs/firestore/pricing, docs.cloud.google.com/firestore/quotas) | none: the deploy script enables it; auth is the Cloud Run service account, **no new secret** | data stays in his project, Mumbai region; no new third party | document store |
| Neon Postgres free | 1 GB/project, 100 CU-h/month, suspends after 5 min idle, no card (neon.com/pricing, updated 2026-10-31) | new account, region choice, paste a connection string (a new secret) | new processor (Neon/Databricks); region list unverified for India | matches the architecture's Postgres |
| Cloud SQL | no free tier | — | — | — |

Firestore wins on the two things the owner cares about most: zero payment and zero new
accounts/keys, and it is the more private choice. **Deviation from the architecture's
"Postgres" is deliberate and contained**: every store is behind an interface
(`SessionStore`, `ApprovalStore`, `AuditTrail`); a Postgres implementation drops in later
(Phase 3 long-term memory is the natural point to revisit, e.g. pgvector).

Things Firestore does NOT give free, so we do not use them: TTL policies (TTL deletes are
billed), PITR, backups. Conversations are kept until the owner deletes them.

## Design
### Ports (all async)
* `SessionStore` (exists) — add `FirestoreSessionStore`.
* `ApprovalStore` (new, `core/approvals.py`): `put`, `consume(id, matches)` (atomic: read,
  check, delete — a wrong token never consumes another action), `cancel(id)`, `list()`.
  `ConfirmationGate` becomes async and delegates storage to it. In-memory + Firestore impls.
* `AuditTrail` (new protocol, `tools/audit.py`): `append`, `recent(limit)`, `verify(limit)`.
  `AuditLog` = in-memory impl (name kept); `FirestoreAuditLog` appends in a transaction
  (read head → write entry seq+1 → move head), so the chain never forks.
  `verify(limit)` checks the last `limit` entries + their predecessor link + head; full-chain
  verification stays available (`verify(None)`) but the console uses the window, so reads stay
  O(window) instead of O(history).

### Narrow document port (`storage/docs.py`)
Repositories talk to a 5-method `Docs` port (`get`, `query`, `write`, `transaction`,
`close`). `FirestoreDocs` is the only code that imports `google.cloud.firestore`;
`MemoryDocs` is a faithful in-process implementation used by unit tests. Same contract tests
run against both; the Firestore run happens in CI against the official emulator (the dev
sandbox cannot download it).

### Data model (prefix `jarvis_`, all payloads stored as pydantic JSON strings)
```
jarvis_sessions/{sid}                 user_id, updated_at, turn_count, rev, title, json(session minus turns)
jarvis_sessions/{sid}/turns/{000001}  json(turn)              ← one doc per turn: no 1 MiB ceiling per conversation
jarvis_approvals/{id}                 scope, expires_at, json(PendingAction)
jarvis_audit/{seq:012d}               seq, json(AuditEntry)
jarvis_meta/audit_head                seq, hash
```
* Turns are append-only. `save()` writes the header + only new/changed turns (digest memo);
  turns first, header last, so a reader never sees a header pointing at missing turns.
* `get()` reads the header; if `rev` matches the in-process cache it returns the cached copy
  (1 read), else reads `turn_count` turns.
* Listing: `where user_id == X order by updated_at desc` (composite index created by the deploy
  script); if the index is still building, fall back to `where user_id` + sort in app.

### Cost budget (single owner, generous)
One chat message ≈ 1–3 reads + 3–6 writes; one tool approval ≈ +3 writes. 200 messages/day
≈ 600 reads / 1,200 writes — about 1–6% of the daily free quota. `/health` ping is cached 60 s.

### Console
* Remember the open conversation (localStorage) and redraw it after a reload or cold start.
* Inspector gains **Conversations**: recent list (title, time, turns), open one, delete one
  (two-step confirm — deleting is irreversible).
* `PendingApproval` carries `session_id`, so an approval from another conversation can still
  be approved after a reload.

### Deploy (`deploy/cloudrun.sh`)
Enable `firestore.googleapis.com`; create `(default)` DB in asia-south1 if missing (location
is permanent); create the composite index (idempotent, async); grant the service account
`roles/datastore.user`; set `JARVIS_SESSION_BACKEND=firestore`. Max instances stays 1 for now
(the rev cache is coherent across instances, but rate limiting is per process).

### CI
* New `firestore` job: setup-gcloud + `cloud-firestore-emulator`, run the contract tests with
  `FIRESTORE_EMULATOR_HOST`.
* `eval-gate` skips cleanly when `JARVIS_ANTHROPIC_API_KEY` is not set (it has failed on every
  push since the owner chose the free brain).

## Risks
* Emulator-only verification of the real adapter → mitigated by CI job + owner smoke test.
* Free quota resets at midnight Pacific; exceeding it bills tiny amounts (budget alert exists).
* Firestore data is readable by anyone with Owner/Editor on the project — only the owner.

## Tests (write first)
1. Gate: async contract (existing cases ported) + concurrent double-approve executes once.
2. Audit: append/verify across a "restart" (new object over same docs); tamper detection;
   window verify.
3. Sessions: round-trip, append-only diff writes, rev cache, list order + fallback, delete,
   >500-turn chunking, header-last ordering.
4. API: approval survives app restart; transcript survives restart; `session_id` on approvals.
5. Contract suite parametrized over MemoryDocs / FirestoreDocs(emulator).

## Fresh-context review (security + correctness, independent) — outcome
| Sev | Finding | Fix |
|---|---|---|
| HIGH | Two approves racing (or approve vs decline): the loser re-stored the action as a NEW pending approval → approving that card sent twice; loser also overwrote the transcript's "executed" record | `ConfirmationInvalid`: a spent/expired/mismatched token never stores anything; gateway outcome `CONFIRMATION_INVALID` → 404 before the session is touched; per-conversation async lock serialises chat / approve / decline / delete |
| HIGH | Audit append failing AFTER a tool ran raised → no record of a sent message, retry possible | `_audit_after_run`: post-execution audit failures are logged loudly, the result is still returned and recorded |
| MED | Deleting the audit head made `tail`/`verify_all` report verified; next append overwrote entry 1 | missing head + existing entries = not verified; entries written create-only (`DocTx.create` → `DocExists`) |
| MED | Whole-chain rewrite by anyone with datastore.user is undetectable in-database | each append also logs `(audit_seq, audit_hash)` to Cloud Logging as an external anchor |
| MED | datastore.user + secretAccessor on the default compute SA, which is also the build identity | dedicated runtime SA `jarvis-run`; build SA loses secretAccessor (after a successful deploy) and never gets Firestore |
| MED | save() after delete resurrected a conversation; concurrent saves lost turns | per-conversation lock (in-process); cross-process rev precondition deferred — **do not raise max-instances before adding it** |
| MED | `get()` cached turn digests positionally across a gap → later save skipped a needed write | cache only when turn ids are exactly 000001..count |
| LOW | `tail` head/window race showed "Log tampered" | ignore entries newer than the head read (+4 row slack) |
| LOW | delete left waiting approvals behind; header-first delete not retryable | `Brain.forget` cancels the conversation's approvals; turns deleted first, header last |
| LOW | `SAFE_ID` `$` accepted a trailing newline | `fullmatch` / `\Z` |
| LOW | rejected first message left an empty conversation | validate input before creating the session |
| LOW | console: approve during a reply; cleared saved conversation on any error | busy guard; clear only on 404 |
| LOW | `limit<=0` → Firestore 500; gRPC channel not closed | clamp ≥1; close transport |

Accepted / deferred: `user_id` is still a request parameter, not derived from the signed-in email (safe with one owner email; fix before adding a second owner). Approve executes the stored arguments; a client-side hash of the displayed arguments is a later hardening.
