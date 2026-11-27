---
page: pg_card_c41
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/storage/__init__.py": "2dedb3cc1fb619bd"
  "src/jarvis/storage/approvals.py": "093f10af05d87010"
  "src/jarvis/storage/audit.py": "d268e84d6aa87ab5"
  "src/jarvis/storage/docs.py": "561064f51e6e084f"
  "src/jarvis/storage/firestore_admin.py": "342edf56ae911283"
  "src/jarvis/storage/firestore_docs.py": "7077a22c0b20173d"
  "src/jarvis/storage/firestore_walk.py": "82b45e93c972759f"
  "src/jarvis/storage/sessions.py": "c9a8ec12966d54db"
---
## In plain words
The document store is where JARVIS keeps what must survive a restart: your conversations, the actions waiting for your approval, and the tamper-checked log of everything it did. In the live system that is Google's Firestore database; on a developer's machine it is a copy held in memory. Every part writes through one small, shared doorway, so where the data lives is decided in a single place (`src/jarvis/storage/__init__.py:build_storage`).

## Example (made up)
At 21:05 you ask JARVIS to send Neha the guest list. Before anything goes out, the request is saved as an approval waiting for you. Nobody uses JARVIS for a few minutes, so the server shuts down to save money. At 21:09 you open Approvals, a fresh server starts, and the request is still there. On a slow connection you tap Approve twice; the message goes out once, and the activity log gains one new line, linked to the line before it.

## How it works
`build_storage` reads `session_backend`: with Firestore it opens `FirestoreDocs` on `firestore_project` and `firestore_database`; otherwise conversations stay in memory or a local Redis, and approvals and the log stay in the running process. `doc_storage` puts conversations, approvals, the activity log and Google sign-in tokens on one port, every collection name starting with `firestore_prefix` (`src/jarvis/storage/__init__.py`). Google tokens are kept in the database only when `token_key` gives an encryption key; without one they stay in memory (`_memory_tokens`). The port `Docs` offers only get, query, write and transaction, and `src/jarvis/storage/firestore_docs.py` is the one file that talks to Firestore. `MemoryDocs` behaves the same way in memory, so tests check the real rules (`src/jarvis/storage/docs.py`). Large writes go out in order, in chunks no bigger than Firestore allows in one commit (`chunks`). `DocSessionStore` keeps each conversation as a header plus one record per turn, writes only new turns with the header last, and keeps up to {{fact:src/jarvis/storage/sessions.py:CACHE_SESSIONS}} conversations in memory so a repeat read costs one look-up. A save first checks that nobody else changed the conversation since it was read, trying up to {{fact:src/jarvis/storage/sessions.py:CAS_ATTEMPTS}} times (`src/jarvis/storage/sessions.py`). `DocApprovalStore` reads and removes an approval in one transaction, so it runs once however often it is tapped. `DocAuditLog` adds each log line and moves the chain's head in one transaction, so the chain never forks. `src/jarvis/storage/firestore_admin.py` and `src/jarvis/storage/firestore_walk.py` serve only the backup restore drill, locked to its throw-away copy.

## What it costs
Nothing while JARVIS stays inside Firestore's free daily allowance, which this store is built to respect: a conversation already in memory costs one read, and nothing is removed by an expiry rule because those deletes are billed (`src/jarvis/storage/sessions.py`). The size of that allowance is set by Google and is Unverified here. In development everything stays in memory, with no bill (`build_storage`).

## When it fails
When Firestore still lacks the index a list of conversations needs, `IndexNotReady` is raised and the list is sorted in the app from up to {{fact:src/jarvis/storage/sessions.py:LIST_FALLBACK_SCAN}} conversations meanwhile (`src/jarvis/storage/sessions.py`). If another window changed or deleted the same conversation, the save writes nothing and you see a plain line saying so (`DocSessionStore`). A record that can't be read, or a sealed card that doesn't open, is logged and skipped (`src/jarvis/storage/approvals.py:DocApprovalStore`). A busy transaction is retried up to {{fact:src/jarvis/storage/firestore_docs.py:TX_ATTEMPTS}} times (`FirestoreDocs`). The health check reuses its last answer for {{fact:src/jarvis/storage/sessions.py:PING_TTL_S}} seconds, so it never hammers the database (`src/jarvis/storage/sessions.py`).
