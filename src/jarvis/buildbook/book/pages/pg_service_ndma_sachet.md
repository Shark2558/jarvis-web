---
page: pg_service_ndma_sachet
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/helpers/sources.py": "4a821b855f40c328"
---
## In plain words
NDMA SACHET is the Indian government's public feed of official disaster and weather warnings: floods, cyclones, landslides, heavy rain and more, each for named districts. JARVIS's helpers read it so a warning for your own district reaches you on your phone. JARVIS is only a second channel: the official SACHET app, SMS and cell broadcast stay first. Nothing about you goes to SACHET: JARVIS reads your state's public feed like any visitor, and the matching against your district happens inside JARVIS. The warnings are public domain.

## Example (made up)
You set your district in the Helpers panel. At 02:30 a new landslide warning for your district appears in your state's feed. Within ten minutes JARVIS reads it, finds your district in it and rings your phone: "Urgent: Landslide warning for your district until 18:00 (SACHET). Open JARVIS." A warning for a district two hours away is ignored.

## How it works
Disaster warnings run only with `disaster_alerts_enabled` and `helpers_enabled` on, and only for an owner who has set a place, kept sealed in `outside`. The helpers' clock reads your state's list of warnings every `disaster_poll_minutes` ({{fact:settings.disaster_poll_minutes}} minutes), or the national list for a state without its own (`src/jarvis/helpers/sources.py`). Each read goes over HTTPS with no key, follows no redirect and must finish within {{fact:src/jarvis/helpers/sources.py:OUTSIDE_TIMEOUT_S}} seconds; the list may be at most {{fact:src/jarvis/helpers/sources.py:MAX_RSS_BYTES}} bytes and each warning at most {{fact:src/jarvis/helpers/sources.py:MAX_CAP_BYTES}} bytes (`MAX_CAP_BYTES`). JARVIS keeps only real, public warnings for your district that have not expired; a cancellation of one it told you about says the warning is lifted, and an update rings again only when it got worse (`disaster_alerts_enabled`). The text it sends is a fixed sentence built from a fixed event word, your district and the expiry, and the warning's own words are kept sealed in `outside` for the panel. A disaster warning for your district rings at any hour, with a cap on rings in one night and a morning summary for the rest (`helpers_enabled`). SACHET has its own share of each clock run, separate from the weather, so neither holds up the other (`src/jarvis/helpers/sources.py`).

## What it costs
Nothing in rupees: SACHET's feeds are public, free and need no key.

## When it fails
If SACHET doesn't answer, the panel says it can't reach SACHET since a given time, and JARVIS keeps trying on the next runs (`src/jarvis/helpers/sources.py`). A warning that is unsafe or unreadable is refused and never fetched again. A warning that keeps being refused is dropped after a while. Your official channels are unaffected either way.
