---
page: pg_service_google_photos_picker
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/r4_wiring.py": "379192618b74836f"
  "src/jarvis/config.py": "8c6265f13d09201d"
  "src/jarvis/photos/picker.py": "6dc3c8c5e7df6b3c"
---
## In plain words
The Google Photos Picker is Google's own window for choosing photos from your Google Photos. JARVIS uses it so your home laptop learns the faces of the people you want it to recognise: you pick photos in Google's window, JARVIS reads only those, removes their hidden data such as place and camera details, passes each one to your laptop and drops it. The laptop groups the faces, and you name a group once, with the consent check. JARVIS never sees the rest of your library, and no photo or face is kept in the cloud. It is an extra permission you grant once in Integrations.

## Example (made up)
On a Sunday you press "Pick photos" in the Faces panel. Google's window opens; you choose 120 photos from a family wedding and press Done. Over the next twenty minutes JARVIS reads them in the background, a few at a time, and sends each to the laptop. That evening Faces shows three unnamed groups; you name one "Asha", tick the consent line, and the door camera names her the next time she visits.

## How it works
`PickerClient` first checks that your Google link holds the Photos permission, then asks Google for a picking session and its link, which must be on Google Photos' own site over HTTPS (`src/jarvis/photos/picker.py`). A pick may hold up to `photos_max_picked` ({{fact:settings.photos_max_picked}}) photos, Google's own maximum being {{fact:src/jarvis/photos/picker.py:PICKER_MAX}} (`PickerClient`). The list of picked items is read a page of {{fact:src/jarvis/photos/picker.py:PAGE_SIZE}} at a time, and only photos are kept (`_item`). Each picture is fetched only from Google's own picture servers, waits at most {{fact:src/jarvis/photos/picker.py:DOWNLOAD_TIMEOUT_S}} seconds, is refused past {{fact:src/jarvis/photos/picker.py:MAX_IMAGE_BYTES}} bytes and must be a JPEG (`_check_headers`). Its hidden data is stripped before it leaves `PickerClient`, and no picture link is ever kept. A busy or failing Google means "try again later" for that picture, while a picture Google won't serve is skipped (`TOO_MANY`). Background steps read at least `photos_import_batch` ({{fact:settings.photos_import_batch}}) photos when time allows and carry on after a restart or while the laptop is away. Photos runs only with `photos_enabled` on, the Google link, Faces and the home kit in place (`src/jarvis/api/r4_wiring.py:wire_photos`). "Delete all" in Faces also ends the picking session and drops its state (`FacesAndPhotosPrivacy`).

## What it costs
Nothing in rupees: Google charges nothing for the Picker. Google's daily quotas apply. Unverified: the exact quota numbers for your project.

## When it fails
Without the permission, JARVIS says it has no permission to open the photos you pick and to press Grant next to "Google Photos" in Integrations (`PhotosNotGranted`). If the Picker service is off in your Google project, JARVIS says to re-run the deploy script. With the laptop off, the import waits and says it is paused until the laptop is back. A picture that is too big or not a JPEG is skipped, and the rest go on.
