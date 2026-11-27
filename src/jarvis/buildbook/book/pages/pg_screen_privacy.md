---
page: pg_screen_privacy
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/privacy.py": "26b8bb3f25b86ee7"
  "src/jarvis/api/static/console-privacy.js": "7184a1fe77763ae0"
  "src/jarvis/api/static/console.html": "d26e202e4e9aa526"
---
## In plain words
Privacy is the place that shows what JARVIS keeps about you and your family, kind by kind, your phone calls among them (`src/jarvis/calls/privacy.py`). There is a card for each kind of data: what it is, how many there are, how long it is kept, where it is stored, and whether JARVIS encrypts it. Each card has an Export button to download a copy and, where it makes sense, a Delete button. "Download everything" saves all of it in one file. You stay in charge of your own data (`src/jarvis/api/static/console-privacy.js`).

## Example (made up)
One evening you decide to clear out the list of what JARVIS did this week. You open Privacy; the top line says "JARVIS keeps 14 kinds of data about you and your family." You scroll to the Activity card, which shows 230 rows, kept for 7 days. You press Export first and keep the file. Then you press "Delete...", read what will go, and use your passkey. The card now reads "Deleted 230 rows from Activity." and shows none left.

## How it works
When the panel opens, it asks `GET /v1/privacy` for every kind of data it covers, and draws one card per kind (`src/jarvis/api/static/console-privacy.js`). Phone calls have four cards of their own, under Phone calls: your calls with their transcripts, summaries and recordings, deleted only with your passkey and exported with each number masked and without the audio; the calls settings; the call desk's link; and the language check's results (`src/jarvis/calls/privacy.py`). Each card shows the label, the count, what it is, how long it is kept, where it lives, and an "Encrypted by JARVIS" badge when that is so (`src/jarvis/api/privacy.py:get_privacy`). Export on a simple card downloads it from `POST /v1/privacy/{category_id}/export`; for private content it first needs your passkey or a Google sign-in from the last few minutes (`src/jarvis/api/privacy.py:export_category_with_proof`). "Download everything" uses `POST /v1/privacy/export-all` and leaves out vault files, which Vault exports on its own (`src/jarvis/api/privacy.py:export_all`). "Delete..." opens a box that says what will go (`src/jarvis/api/static/console-privacy.js`). A delete that can't be brought back needs your passkey, or the word DELETE plus a fresh Google sign-in (`src/jarvis/api/static/console-privacy.js`). The delete goes to `POST /v1/privacy/{category_id}/delete` together with the version of the card you saw, so a card that changed meanwhile is refused with "This changed - check again." (`src/jarvis/api/privacy.py:delete_category`). Export and delete work only in the console in your browser, never from a script with a token (`src/jarvis/api/privacy.py:_browser_only`).

## What it costs
Looking, exporting and deleting cost nothing: they read and write JARVIS's own records with no AI (`src/jarvis/api/privacy.py`).

## When it fails
If a card's data is out of reach just then, it says "Couldn't check right now." and the other cards still show. If the data changed since you opened the panel, the delete is refused with "This changed - check again." If part of a delete fails, the card says how many are still there and suggests trying again in a moment. If your sign-in is too old, a "Sign in with Google again" button appears. Changes are limited to {{fact:src/jarvis/api/privacy.py:CHANGE_PER_MINUTE}} a minute.
