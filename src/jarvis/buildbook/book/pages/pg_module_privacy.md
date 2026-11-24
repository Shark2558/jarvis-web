---
page: pg_module_privacy
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/privacy.py": "26b8bb3f25b86ee7"
  "src/jarvis/api/static/console-privacy.js": "7184a1fe77763ae0"
---
## In plain words
The privacy panel is one screen in the console that lists every kind of data JARVIS keeps about you and your family. For each kind it shows what it is, how many items there are, how long they are kept, where they live and whether JARVIS encrypts them itself. Each kind has an Export button, and a Delete button wherever removing it makes sense. Nothing JARVIS remembers is hidden from you, and whatever you want gone leaves from this one place, with your passkey asked first for anything that would be gone for good.

## Example (made up)
On a Sunday evening Nandini opens Privacy on her laptop. The top line says JARVIS keeps 9 kinds of data about her family. Under Memory she sees 42 facts, kept until she deletes them. She taps Export, her phone asks for her fingerprint, and a file called jarvis-memory-2026-11-22.json lands in her downloads. Next she decides last week's morning briefs should go. She taps Delete, the dialog says "This removes 6 briefs" and warns that they won't come back, and her phone asks for her fingerprint again. A moment later the note under the button reads "Deleted 6 from Morning briefs."

## How it works
When you open the panel, `src/jarvis/api/static/console-privacy.js` asks `GET /v1/privacy` for the list and checks every field before drawing a card, dropping anything of the wrong type. On the server `get_privacy` answers only the signed-in owner, reading each feature's own store through the privacy service that `_svc` finds on the app. Every call passes a per-owner limit in `_limit`, set up by `install_privacy`: {{fact:src/jarvis/api/privacy.py:VIEW_PER_MINUTE}} looks a minute and {{fact:src/jarvis/api/privacy.py:CHANGE_PER_MINUTE}} exports or deletes a minute. Export, delete and "Download everything" pass `_browser_only` first, so a caller holding only a bearer token is refused with `ConsoleOnly`: only the console in your own browser takes data out or removes it. `export_category` and `export_category_with_proof` share `_export_one`, which returns the data as a JSON file that `_attachment` names after the category and `_today`'s date, never cached. `export_all` gathers every exportable kind into one file and leaves vault files out (`POST /v1/privacy/export-all`). A delete sends a `DeleteRequest` holding a fingerprint of what you saw plus a passkey proof or the typed word DELETE. `delete_category` hands it to the privacy service, which refuses it when the data changed since you looked. For data that would be gone for good, the script asks for your passkey bound to that category and that fingerprint; when no passkey is set up yet it asks for the word DELETE and a fresh Google sign-in instead (`src/jarvis/api/static/console-privacy.js`).

## What it costs
Nothing: the panel makes no AI call and uses no outside service, it only reads and removes what JARVIS already keeps (`src/jarvis/api/privacy.py`).

## When it fails
A kind of data that can't be read keeps its card and says "Couldn't check right now", so the rest of the list still shows (`src/jarvis/api/static/console-privacy.js`). If the data changed after you opened the panel, the delete is refused with status 409 and the note "This changed - check again."; the list reloads and your passkey check is not used up (`delete_category`). Too many requests in a minute get status 429 and a short wait (`PrivacyRateLimited`). A delete that left items behind says how many are still there, and one your home laptop finishes later says so in the note (`src/jarvis/api/static/console-privacy.js`). A Google sign-in that is too old for a delete shows a "Sign in with Google again" button (`src/jarvis/api/static/console-privacy.js`).
