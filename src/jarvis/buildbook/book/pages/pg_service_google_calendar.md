---
page: pg_service_google_calendar
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/config.py": "8c3c0b7f0890ff99"
  "src/jarvis/integrations/google.py": "5e687c47689b959b"
---
## In plain words
Google Calendar is where your appointments live. Once you link your Google account in Integrations, JARVIS reads your calendars, adds and moves events, sets reminders as events with pop-up alerts, and deletes events with an undo. The morning brief lists your day from it, family calendars you register show beside yours, followed plans check in after each session, and the wardrobe plans outfits for your events. What goes to Google is what each request needs: the event you create or change, or the dates you ask about. JARVIS reads your calendar through your own link, and an event with guests sends invitations, so it always asks you first.

## Example (made up)
At 18:30 you say: "Put a parent-teacher meeting on Thursday at 4 pm for an hour, and remind me an hour before." JARVIS shows one approval card with the event and its alert. You approve; the event appears in your Google Calendar a second later, with a reply card offering Undo. On Thursday morning the brief lists it at 16:00.

## How it works
`GoogleConnector` is the one door for every Calendar call: it adds your access token, waits at most {{fact:src/jarvis/integrations/google.py:HTTP_TIMEOUT_S}} seconds and turns every error into JARVIS's own short words, never Google's (`src/jarvis/integrations/google.py`). Linking asks for permission to read your calendars and to change events; if you untick either, `GoogleScopesMissing` refuses the link and nothing is stored. The access token is renewed when less than {{fact:src/jarvis/integrations/google.py:REFRESH_SKEW_S}} seconds of it remain, with the refresh token kept sealed under the server's token key (`GoogleConnector`). Only reads are tried again after a busy or failing Google; a create or a change is never sent twice, because Google may already have acted (`GoogleConnector`). A call that got no answer is marked as maybe done (`GoogleUncertain`), and a delete is then checked by reading the event again. A used-up quota or a short-term limit gets neutral words (`_raise_quota`). One approval card holds up to `calendar_batch_max` ({{fact:settings.calendar_batch_max}}) events, created a few at a time, with each event's result shown. The calendar tools exist only with `google_tools_enabled` on, Google sign-in in use and the server's token key present (`google_tools_configured`). The wardrobe re-reads the one calendar you pick every `wardrobe_calendar_refresh_min` ({{fact:settings.wardrobe_calendar_refresh_min}} minutes).

## What it costs
Nothing in rupees: Google charges nothing for Calendar calls. Google's daily request quotas apply. Unverified: the exact quota numbers for your project.

## When it fails
Not linked: JARVIS says Google is not connected and points to Integrations. A link Google stopped accepting asks you to reconnect in Integrations (`GoogleNotConnected`). A Google error becomes one short message, such as "Google is rate limiting requests right now; try again shortly." (`_friendly`). A delete whose undo copy fails to save first does not delete. An event with guests always waits for your approval.
