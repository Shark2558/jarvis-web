---
page: pg_card_c37
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-connectors.js": "ff3bd4922c9d1c14"
  "src/jarvis/integrations/github.py": "adc322d129055173"
  "src/jarvis/integrations/github_meta.py": "78572f23b049436e"
  "src/jarvis/photos/INTEGRATION.md": "ea59de3696230c74"
  "src/jarvis/photos/__init__.py": "25df181b59b19e3f"
  "src/jarvis/photos/api.py": "8ac985d0fd795e2a"
  "src/jarvis/photos/edge.py": "bc17b5aa05e7b2e2"
  "src/jarvis/photos/errors.py": "a53300f8e8ce239a"
  "src/jarvis/photos/imaging.py": "70fde17b9e9dcadf"
  "src/jarvis/photos/import_store.py": "200f43edb69fbab9"
  "src/jarvis/photos/imports.py": "3c2aa9d39d0ed746"
  "src/jarvis/photos/models.py": "900205b066c3fd09"
  "src/jarvis/photos/picker.py": "6dc3c8c5e7df6b3c"
  "src/jarvis/photos/service.py": "d88c9a761feb5db7"
  "src/jarvis/photos/tools.py": "a3dd34dcc8b04a5c"
---
## In plain words
Two connectors live in the Connectors panel. Google Photos: you choose photos in Google's own picker, and JARVIS passes them, one by one and stripped of location and camera details, to your home laptop, which finds the faces; the cloud keeps only ids and counts, never a picture or a face. GitHub: paste a token once and JARVIS reads your own account, repositories and recent activity, read-only.

## Example (made up)
On a rainy Sunday you press Import in Connectors and pick 600 family photos in Google's picker. JARVIS works through them in the background, a few dozen at a time, while you cook. Your laptop sleeps for an hour; the import pauses and carries on when it wakes. By evening the panel reads 600 photos, 41 faces found, and Faces offers three unnamed groups to name, each only with that person's consent.

## How it works
`PhotosService` opens a picker session for up to `photos_max_picked` photos ({{fact:settings.photos_max_picked}}), and `Importer` then runs the import in steps that save after every photo, so a restart or a sleeping laptop loses nothing (`src/jarvis/photos/imports.py`).
Each step asks the laptop first, keeps only the picked item ids, and reads at least `photos_import_batch` photos ({{fact:settings.photos_import_batch}}) when time allows, at most {{fact:src/jarvis/photos/imports.py:STEP_MAX_PHOTOS}}.
`PickerClient` downloads each photo, and `sanitise_jpeg` keeps only what a decoder needs, dropping location and camera data, and refuses a picture wider or taller than {{fact:src/jarvis/photos/imaging.py:MAX_IMAGE_SIDE}} pixels (`src/jarvis/photos/imaging.py`).
`BridgeHomeEdge` sends the picture to your laptop over the signed home link and accepts only ids and counts back; one extra field and the whole answer is refused (`src/jarvis/photos/edge.py`).
The progress lives in `photo_imports` as counts and ids only (`ImportStore`), and a photo Google won't hand over is retried, counted as unreadable only after {{fact:src/jarvis/photos/imports.py:MAX_STUCK_STEPS}} stuck steps.
Naming a face group runs the faces registry's consent check first, and a child is only ever "a child from your family" (`src/jarvis/photos/tools.py`).
`GithubClient` calls only GitHub's own address, read-only, with a deadline and a size cap; the token is sealed with the keyring in `connectors_github` and never shown again (`src/jarvis/integrations/github.py`).
`MetaBook` reads the token's expiry and hourly limit from GitHub's reply headers for the Vitals board, and a token with no stored limits is checked at most every {{fact:src/jarvis/integrations/github.py:FACTS_EVERY_S}} seconds (`src/jarvis/integrations/github_meta.py`).
`src/jarvis/api/static/console-connectors.js` holds the panel: paste or remove the token, start a pick, and see the import's line.

## What it costs
Nothing in rupees: the picker and GitHub's read calls carry no charge in JARVIS, and the faces run on your own laptop (`src/jarvis/photos/edge.py`). The cloud keeps ids, counts and the sealed token only (`photo_imports`, `connectors_github`).

## When it fails
Laptop asleep or offline: the import pauses and says why, then resumes (`EdgeOffline`). A laptop kit too old for photos says so (`EdgeNotReady`). Google not answering pauses the step and the next one tries again; a pick Google has ended says "pick again to continue", keeping what was done (`src/jarvis/photos/imports.py`). Without the Photos grant the import points you to it (`PhotosNotGranted`). A token GitHub refuses shows as needing reconnecting, in JARVIS's words, never GitHub's (`GithubNeedsReconnect`).
