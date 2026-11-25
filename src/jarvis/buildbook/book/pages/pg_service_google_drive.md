---
page: pg_service_google_drive
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/app.py": "51eaf37fbe6a89cf"
  "src/jarvis/api/drive.py": "aab977fe9441f939"
  "src/jarvis/api/feature_wiring.py": "473760847cb35d03"
  "src/jarvis/api/integrations.py": "849076061558773f"
  "src/jarvis/api/personal.py": "7a9aa32e08b7d084"
  "src/jarvis/api/startup_log.py": "4ba9e18096e253e1"
  "src/jarvis/api/vault_inbox.py": "26546b663f03b975"
  "src/jarvis/config.py": "8c6265f13d09201d"
  "src/jarvis/drive/client.py": "766e2385d779a833"
  "src/jarvis/drive/guard.py": "89a1025585b08521"
  "src/jarvis/drive/kinds.py": "64732723fb4aeeed"
  "src/jarvis/drive/live.py": "9b9a306d821512a1"
  "src/jarvis/drive/ports.py": "7417de94901166bc"
  "src/jarvis/drive/roots.py": "81117f718c69555f"
  "src/jarvis/drive/service.py": "dc7c305c68c1aca4"
  "src/jarvis/drive/token.py": "9e3f8f673ac390aa"
  "src/jarvis/drive/tools.py": "a381ec7f15714801"
  "src/jarvis/privacy/existing.py": "021f304566e63a19"
  "src/jarvis/privacy/sources.py": "312d6572b6dd061e"
  "src/jarvis/tools/budget.py": "bb2f9659efef5175"
  "src/jarvis/tools/setup.py": "b430d38a376cac97"
  "src/jarvis/vault_inbox/service.py": "28d7d4fda9011c06"
  "src/jarvis/vault_inbox/store.py": "bfcd12486df55c2d"
---
## In plain words
Google Drive is where your files live in your Google account. JARVIS reads Drive files only in folders you choose: you share a folder with JARVIS's own Google address, read-only, then switch it on in Integrations. JARVIS reads as itself, never as you, so the rest of your Drive stays out of its reach. Drive is the way documents from DigiLocker reach your vault, too: you share them from the DigiLocker app into one Drive folder, and JARVIS moves new ones into the vault. What goes to Google is each search and each file JARVIS opens; nothing from Drive is stored, except the files you import into the vault on purpose.

## Example (made up)
You share a folder called "House papers" with JARVIS's address and switch it on. At 22:15 you ask: "What does the rental agreement say about notice?" JARVIS searches that folder, finds the agreement, reads its second part and quotes the two-month notice clause, naming the file it came from.

## How it works
Drive works only with the setting `drive` on, which the deploy sets, and uses `MetadataTokens` to get a read-only token for JARVIS's own service account, so no key exists (`src/jarvis/drive/service.py:drive_configured`). A folder is accepted only if it is yours by `owned_by`, and you may switch on at most {{fact:src/jarvis/drive/ports.py:MAX_ROOTS}} (`src/jarvis/drive/roots.py`). Before any read, `ParentsGuard` checks that the item sits inside one of those folders, walking at most {{fact:src/jarvis/drive/guard.py:MAX_DEPTH}} levels and {{fact:src/jarvis/drive/guard.py:MAX_LOOKUPS}} look-ups; anything else is refused, whatever a model or a hostile document asks for. Every tool call re-checks the switched-on folders, with a cache of {{fact:src/jarvis/drive/live.py:ROOT_CHECK_TTL_S}} seconds, and a folder that fails is off for every tool (`RootChecks`). A search returns at most {{fact:src/jarvis/drive/service.py:SEARCH_LIMIT}} hits inside your folders, and a read gives one part of about {{fact:src/jarvis/drive/service.py:PART_CHARS}} characters, fenced as outside content (`DriveService`). Files up to {{fact:src/jarvis/drive/ports.py:MAX_FILE_BYTES}} bytes are read, and extracted text stays in memory for {{fact:src/jarvis/drive/service.py:TEXT_CACHE_S}} seconds only. `DriveClient` gives each call {{fact:src/jarvis/drive/client.py:DEADLINE_S}} seconds, follows no redirect and retries a busy Drive at most {{fact:src/jarvis/drive/client.py:MAX_RETRIES}} times. The DigiLocker folder is checked by `InboxService`, at most {{fact:src/jarvis/vault_inbox/service.py:MAX_PER_RUN}} downloads a run, and the Drive tools can never read it (`src/jarvis/vault_inbox/service.py`).

## What it costs
Nothing in rupees: Google charges nothing for Drive calls. Google's daily quotas apply. Unverified: the exact quota numbers for your project.

## When it fails
A file outside your chosen folders is refused as not in your chosen folders (`NotInRoots`). A folder that is no longer yours or no longer readable shows as switched on but not readable right now (`RootChecks`). If the stored folder list can't be read, JARVIS reads nothing from Drive until it can (`RootsUnreadable`). A DigiLocker file that is skipped is listed with its reason in plain words, and nothing is imported twice (`InboxService`).
