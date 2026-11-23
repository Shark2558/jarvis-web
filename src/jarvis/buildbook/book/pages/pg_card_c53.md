---
page: pg_card_c53
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/privacy.py": "26b8bb3f25b86ee7"
  "src/jarvis/api/static/console-privacy.js": "7184a1fe77763ae0"
  "src/jarvis/privacy/__init__.py": "50f731c22de44512"
  "src/jarvis/privacy/existing.py": "021f304566e63a19"
  "src/jarvis/privacy/export.py": "7af0681ad7ec0319"
  "src/jarvis/privacy/ports.py": "b905feed47b9fbbd"
  "src/jarvis/privacy/service.py": "216cb38b625ffa31"
  "src/jarvis/privacy/sources.py": "312d6572b6dd061e"
  "src/jarvis/privacy/sources_r1.py": "cc0a709ab284ea09"
---
## In plain words
The Privacy panel lists everything JARVIS keeps about you, one row per kind: what it is, how many, how long it is kept, where it lives and whether JARVIS encrypts it. Each row has Export and, where it makes sense, Delete. Deleting something gone for good, like conversations or memories, needs your passkey, so a stolen phone with an open console is not enough. "Download everything" gives you one file with all of it, never a secret.

## Example (made up)
On a quiet evening you open Privacy. The Conversations row reads 214, kept until you delete them; Memories reads 37. You press Export on Memories and get a small file. Then you press Delete on Conversations; JARVIS lists what goes and asks for your passkey, you touch the fingerprint reader, and the row drops to 0. Meanwhile your laptop is off, so the Face groups row says its delete finishes when the laptop is back on.

## How it works
Every feature that keeps something about you registers a `PrivacySource`, and `PrivacyRegistry` asks them all at once, each within {{fact:src/jarvis/privacy/ports.py:SOURCE_BUDGET_S}} seconds; a slow or failing one still keeps its row, marked "Couldn't check right now" (`src/jarvis/privacy/ports.py`).
Each row is a `CategoryView`: section, label, what it holds, a count, how long it is kept, where it lives, and its delete class.
The delete class decides what you must prove first (`PrivacyService`): none (explained, not deletable here), simple (a setting you can make again), confirm (a dialog listing what goes), or passkey (content that can't be brought back).
With passkeys in force, a passkey check bound to that row is needed; without them, the typed word DELETE plus a Google sign-in less than a few minutes old (`src/jarvis/privacy/service.py`).
`fingerprint` gives each row a short revision from what you were shown, so a delete is refused if the data changed since you looked, and no proof is spent (`src/jarvis/privacy/export.py`).
`scrub` runs over every export and drops anything named like a token, key, password or encrypted blob, at any depth, as a second line of defence.
`export_all` gives the single download of every exportable row except vault files, behind a passkey or a fresh sign-in (`src/jarvis/api/privacy.py`).
The sources themselves live in `src/jarvis/privacy/sources.py` and `src/jarvis/privacy/sources_r1.py`: conversations, memories, approvals, the audit, briefs, Google, Drive, places, faces, Telegram and more.
Every export and delete is audited with the row and a count, never the content (`PrivacyService`). A bearer token can look but never export or delete (`ConsoleOnly`).
`src/jarvis/api/static/console-privacy.js` draws the panel from `GET /v1/privacy` and deletes through `POST /v1/privacy/{category_id}/delete`.

## What it costs
Nothing: no rupees, no AI and no outside service; it keeps nothing of its own and reads each feature's store through that feature's own methods (`PrivacyRegistry`).

## When it fails
A row whose source fails keeps its place and says "Couldn't check right now", never disappearing (`src/jarvis/privacy/ports.py`). Data that changed since you looked is refused with "This changed - check again." and burns no proof (`PrivacyService`). A delete that partly fails says how many are still there, and one the home laptop must finish says it is pending until the laptop is back on (`src/jarvis/privacy/service.py`). Too many changes in a minute are refused for a moment (`PrivacyRateLimited`).
