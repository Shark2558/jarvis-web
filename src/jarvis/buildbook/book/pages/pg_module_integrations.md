---
page: pg_module_integrations
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/drive.py": "aab977fe9441f939"
  "src/jarvis/api/integrations.py": "849076061558773f"
  "src/jarvis/api/media.py": "aa4e42876e43952e"
  "src/jarvis/api/static/console-connectors.js": "ff3bd4922c9d1c14"
  "src/jarvis/api/static/console-drive.js": "ba574f359e1d5e2b"
  "src/jarvis/api/static/console-integrations.js": "2c3f17926e3d8d44"
  "src/jarvis/api/static/console-media.js": "9470b3411b87efe1"
  "src/jarvis/api/static/console-telegram.js": "3a2ca68ffecee7e5"
  "src/jarvis/api/static/console-web.js": "249905ef58dc235d"
  "src/jarvis/api/static/console-whatsapp.js": "47858cdee58c9c9a"
  "src/jarvis/api/telegram.py": "4787df327efb86d5"
  "src/jarvis/api/web.py": "ef6843949c281f10"
  "src/jarvis/integrations/github.py": "adc322d129055173"
  "src/jarvis/integrations/github_meta.py": "78572f23b049436e"
  "src/jarvis/integrations/google.py": "5e687c47689b959b"
  "src/jarvis/integrations/google_errors.py": "f87c7d6fe66b7db5"
  "src/jarvis/integrations/google_key.py": "5bb317b3fa34a038"
  "src/jarvis/integrations/vault.py": "b766226c56672432"
  "src/jarvis/integrations/youtube.py": "c96d11458be8fab1"
  "src/jarvis/notify/telegram_out.py": "b716c4ea72837feb"
  "src/jarvis/tools/addresses.py": "7ebd4b775eca6e2a"
  "src/jarvis/tools/calendar_alerts.py": "9a4b67b7f2509a33"
  "src/jarvis/tools/gmail.py": "b20d7099344ef32a"
  "src/jarvis/tools/gmail_digest.py": "4f0089a3d92bebcd"
  "src/jarvis/tools/gmail_mime.py": "7096ad94b71e768a"
  "src/jarvis/tools/google_calendar.py": "a296ba2d81650abd"
  "src/jarvis/tools/google_tasks.py": "40bbd471c6461dd8"
  "src/jarvis/tools/reminders.py": "71b05fbd96e5a679"
  "src/jarvis/tools/task_marks.py": "86c9e4daa64cb47e"
  "src/jarvis/tools/tasks_api.py": "e6481d1913414507"
---
## In plain words
This module is how JARVIS reaches the services you already use. Linking your Google account lets it read your calendar and mail, add events and reminders, manage your to-dos, look up contacts, read the Drive folders you chose, find places and routes on Maps, and search YouTube. Telegram is a second front door, so you chat with JARVIS and get alerts on your phone without opening the console. Web search answers with numbered sources, and WhatsApp drafts let JARVIS write a message that you send yourself. Every one of these passes the same gateway and your permission rules.

## Example (made up)
Neha links her Google account in Integrations on a Sunday. On Monday at 7:50 she asks on Telegram, "Remind me to call the bank at 11." JARVIS adds a reminder to her calendar, and at 11:00 her phone pops it up. At lunch she asks for a route to a café in her area by two-wheeler; Maps answers with 18 minutes and a card. In the evening she asks JARVIS to send a reply to her landlord; the card shows the recipient, the subject and the first lines, and her fingerprint confirms it.

## How it works
`GoogleConnector` is the one door to your Google account: it keeps the tokens sealed by `TokenCipher`, refreshes them, and turns Google's errors into short words of JARVIS's own (`src/jarvis/integrations/google.py`). `GoogleKeyClient` holds JARVIS's own server key for Maps and YouTube, sent only in a header to Google's hosts and never to your browser. `calendar_tools` read and change events; an event with guests sends invitations, so it always asks. `reminder_tools` make reminders as tagged calendar events whose pop-up is the reminder (`src/jarvis/tools/reminders.py`). `gmail_tools` search and read mail, save drafts, and send only through a final card showing every recipient; `digest_tools` give a voice-safe summary of unread mail. Mail text reaches the brain fenced as other people's words (`src/jarvis/tools/gmail.py`). `tasks_tools` manage your to-dos, and `OutsideTasks` remembers those written from outside text, so they never pass as your own words later. Drive reads only folders you shared with JARVIS's own account and switched on (`PUT /v1/drive/roots/{folder_id}`). Maps and YouTube stop short of their free allowances; your saved Home and Work go to Google only in a route call (`src/jarvis/api/media.py`). `GithubClient` reads your own GitHub account with a token you paste once. Telegram messages arrive at `POST /telegram/webhook`, where a wrong secret gets a bare refusal; mail, Drive, documents and personal data stay off there unless you switch them on (`PUT /v1/telegram/settings`). `TelegramHomeAlerts` keeps urgent alerts on a counter of their own, so ordinary ones never use it up. `web_usage` reports the month's web-search credits, and `src/jarvis/api/static/console-whatsapp.js` draws the WhatsApp card whose link opens the message for you to send.

## What it costs
Nothing on JARVIS's side: Google's tools use your own account, Maps and YouTube stop inside their free allowances, Telegram's bot service and WhatsApp's link are free, and web search stays on the search service's free plan (`src/jarvis/api/web.py`). Each chat turn that uses these tools costs the brain's usual tokens.

## When it fails
An expired or revoked Google link makes the tools ask you to reconnect, and nothing else breaks (`GoogleNotConnected`). A missing grant, such as Tasks or YouTube, gets a plain "grant access" (`YouTubeNotGranted`). Anyone but the paired owner who writes to the bot gets no reply (`webhook`). At a free allowance's stop, JARVIS says the service is used up until it renews. A token GitHub refuses shows as such on Vitals (`GithubNeedsReconnect`). A web-search counter that can't be read is said so, never shown as zero (`web_usage`).
