---
page: pg_service_firestore
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/app.py": "a739af3f1d029daa"
  "src/jarvis/api/book_show_wiring.py": "41f136cc471cf3a2"
  "src/jarvis/api/feature_wiring.py": "473760847cb35d03"
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/api/permissions.py": "42dc725d201a9c43"
  "src/jarvis/api/personal.py": "4613f76e7db113c9"
  "src/jarvis/api/r11_wiring.py": "4cfa5b25282b147c"
  "src/jarvis/api/r13_wiring.py": "4228b2005530a17c"
  "src/jarvis/api/r18_wiring.py": "75477497af6c33aa"
  "src/jarvis/api/r4_wiring.py": "379192618b74836f"
  "src/jarvis/api/r52_wiring.py": "db7440401d1030dd"
  "src/jarvis/api/r6_wiring.py": "933facfd96a82b79"
  "src/jarvis/api/selfcheck_wiring.py": "1acfee7d6ea08779"
  "src/jarvis/api/telegram.py": "4787df327efb86d5"
  "src/jarvis/api/tryon_wiring.py": "47536713ac1021b3"
  "src/jarvis/backup/part.py": "acc12e13dbcb26b4"
  "src/jarvis/billing/service.py": "f8cd9507563514e1"
  "src/jarvis/buildbook/unlock.py": "a8cc9e601703c920"
  "src/jarvis/config.py": "965b3658da16361e"
  "src/jarvis/drive/service.py": "dc7c305c68c1aca4"
  "src/jarvis/fixes/ports.py": "19c609bda735565b"
  "src/jarvis/kb/service.py": "352c0e4f7d8c5c66"
  "src/jarvis/media/service.py": "b536d789f9f47be8"
  "src/jarvis/mobile/ports.py": "1715d5e8251ff5b8"
  "src/jarvis/offline/service.py": "d8859988abef45c7"
  "src/jarvis/selfwatch/jobs.py": "a1b5cdedafe3b4b3"
  "src/jarvis/skills/part.py": "f67e6ee91d243b74"
  "src/jarvis/storage/__init__.py": "2dedb3cc1fb619bd"
  "src/jarvis/storage/firestore_admin.py": "342edf56ae911283"
  "src/jarvis/tools/r1_tools.py": "4d7f8f07d7292b33"
  "src/jarvis/vault/build.py": "1b4cc21bdbaa3c14"
  "src/jarvis/voice/service.py": "61380b913e4265cf"
  "src/jarvis/voice/session_api.py": "adb4e002a290f925"
  "src/jarvis/wardrobe/catalog/part.py": "107e069a8eb76134"
  "src/jarvis/wardrobe/laundry/part.py": "15450b1dd178a058"
  "src/jarvis/wardrobe/seeme/pair.py": "faf86b938c31c4b5"
  "src/jarvis/wardrobe/seeme/part.py": "414e788c2a14b47d"
  "src/jarvis/wardrobe/seeme/privacy.py": "43c7dfc7a3518849"
  "src/jarvis/wardrobe/styling/part.py": "2384375983e34cc4"
  "src/jarvis/wardrobe/tryon/erase.py": "9d8a836c1b6f5087"
  "src/jarvis/wardrobe/tryon/looks.py": "e1ab3815f08449b6"
  "src/jarvis/wardrobe/tryon/part.py": "f13bb75c65417960"
  "src/jarvis/web/service.py": "15e1408e1103720f"
---
## In plain words
Firestore is Google's database in the cloud, and it is where JARVIS keeps everything that must outlast a restart: your conversations, the approval cards waiting for you, the audit trail, memories, the vault, settings, the Build Book's sealed copies and much more. JARVIS locks private content such as your vault files with its own keys before it goes there, so the database never holds them in clear (`src/jarvis/vault/build.py`). Once you have run the one-time backup setup, Google keeps a copy of the whole database every day, and JARVIS proves each month that a copy really restores.

## Example (made up)
On a Tuesday Maya tells JARVIS to remember that her car insurance renews in March. That fact and the conversation go into Firestore under JARVIS's own name prefix. Overnight a new version of JARVIS starts, and in the morning both are still there. On the 1st of the month JARVIS restores last night's copy into a throw-away database, checks it over two mornings, deletes it, and the Vitals backup line says the drill passed.

## How it works
`build_storage` picks Firestore when `session_backend` says so, in the project and database that `firestore_project` and `firestore_database` name, and keeps conversations, approval cards and the audit trail there (`src/jarvis/storage/__init__.py`). Every other part uses the same document store, handed round by `app_docs`, so the brief, billing, memory and voice settings live in the one database (`src/jarvis/api/app.py`). Billing's month records hold the rupees spent and the replies with no known price (`src/jarvis/billing/service.py`). Every collection's name starts with `firestore_prefix`, {{fact:settings.firestore_prefix}} by default, so JARVIS's records never mix with anything else there (`src/jarvis/config.py`). Each part's wiring builds its stores there, such as the helpers' in `src/jarvis/api/r11_wiring.py`, the wardrobe's in `src/jarvis/api/r13_wiring.py`, the Build Book's sealed copies and sessions in `src/jarvis/api/r6_wiring.py`, and your voice profile and voice session, never audio, in `src/jarvis/api/r52_wiring.py`. Phone calls keep their cards, settings and records there too, with numbers and each call's recording, transcript and summary sealed by JARVIS's own key; without that key calls are not built at all (`src/jarvis/api/r18_wiring.py:wire_r18`). The vault is built only with JARVIS's encryption key; without it the vault stays off rather than store anything in clear (`src/jarvis/vault/build.py`). The systems check reads one document to prove the database answers (`src/jarvis/api/selfcheck_wiring.py`). Backups are Firestore's own daily copies after your one-time setup, and the monthly drill restores the newest copy into a throw-away database to check it (`src/jarvis/backup/part.py`). `FirestoreAdmin` is the only way to those copies: each call has a deadline of at most {{fact:src/jarvis/storage/firestore_admin.py:CALL_S}} seconds, and a call aimed at any database but the throw-away one is refused before it is sent (`src/jarvis/storage/firestore_admin.py`). `Settings` refuses to start JARVIS on the throw-away database, so the live one is never the copy a drill deletes (`src/jarvis/config.py`). If you lose your passkey during a guest show, the emergency unlock works straight on Firestore with the server's own Google Cloud access, not a browser (`src/jarvis/buildbook/unlock.py`). What the Book's earlier writer trial stored, `book_pages` among it, stays until you delete it in Privacy (`src/jarvis/api/r6_wiring.py`).

## What it costs
₹0 while JARVIS stays inside Firestore's free daily allowance of reads, writes and storage; the size of that allowance is Google's and is Unverified here. Once backups are set up, Google bills the daily copies and each drill's restore, and a drill is refused when its restore would cost more than ₹{{fact:settings.backup_drill_max_inr}} (`backup_drill_max_inr`).

## When it fails
If Firestore is down, a request that needs it fails with an error, and the systems check shows the database as not answering (`src/jarvis/api/selfcheck_wiring.py`). The self-health watch then keeps its notes in memory, so the outage is still told once (`src/jarvis/selfwatch/jobs.py`). A backup call to Google that hangs is cut off at its deadline, and the drill carries on at the next morning tick (`bounded`). Before the backup setup nothing is asked of Google, and Vitals says "not set up" (`src/jarvis/backup/part.py`).
