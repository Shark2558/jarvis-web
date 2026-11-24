---
page: pg_card_c29
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/integrations.py": "849076061558773f"
  "src/jarvis/api/static/console-integrations.js": "2c3f17926e3d8d44"
  "src/jarvis/integrations/__init__.py": "4165bc38e588e1b8"
  "src/jarvis/integrations/github.py": "adc322d129055173"
  "src/jarvis/integrations/github_meta.py": "78572f23b049436e"
  "src/jarvis/integrations/google.py": "5e687c47689b959b"
  "src/jarvis/integrations/google_errors.py": "f87c7d6fe66b7db5"
  "src/jarvis/integrations/google_key.py": "5bb317b3fa34a038"
  "src/jarvis/integrations/vault.py": "b766226c56672432"
  "src/jarvis/integrations/youtube.py": "c96d11458be8fab1"
---
## In plain words
To read your calendar and mail, JARVIS needs Google's permission. This part is the link: you press Connect once, agree on Google's own page, and JARVIS keeps the keys Google hands back locked in its vault. Extras (to-dos, contacts, YouTube, Photos) are granted one at a time, and Disconnect cancels the link at Google and forgets the keys. JARVIS's own Google key for Maps and YouTube search stays on the server and never reaches your browser.

## Example (made up)
On a Saturday you open Integrations and press Connect Google. Google's page lists calendar and mail; you agree with the same account you sign in with, and the panel reads "Connected". A week later you press Grant next to Contacts and agree to just that. In March your phone goes missing and you press Disconnect: Google is told to cancel the link, the stored keys are deleted, and the Google tools answer "Google is not connected" until you connect again.

## How it works
`GET /connect/google` sends you to Google's consent page with your sign-in account as the hint, asking for calendar and mail plus the single extra you pressed Grant for (`connect_scopes`).
`connect_callback` keeps the link only if the account that agreed is the one signed in to JARVIS and every required permission was given; a grant from another account is cancelled at Google (`src/jarvis/api/integrations.py`).
`GoogleConnector` stores the tokens through `DocTokenStore`, encrypted with AES-256-GCM under the deployment's `token_key`, sealed to your account so a copied entry fails to open (`src/jarvis/integrations/vault.py`).
Every call of the calendar, mail and to-do tools goes through this one door, which renews the access token when under {{fact:src/jarvis/integrations/google.py:REFRESH_SKEW_S}} seconds remain, waits at most {{fact:src/jarvis/integrations/google.py:HTTP_TIMEOUT_S}} seconds, and retries once only when a retry is safe (`GoogleConnector`).
`held_grants` reads which extras you hold, and `can_use_tasks`, `can_use_contacts` and `can_use_youtube` decide whether those tools are offered.
Google's own error text never leaves the module: `src/jarvis/integrations/google_errors.py` tells a used-up daily or monthly quota (`used_up`) from a short "busy" (`rate_limited`), and the tools see short plain messages.
JARVIS's own key, `google_api_key`, is used only by `GoogleKeyClient`, travels in a header to Google's hosts alone, and never reaches the browser (`src/jarvis/integrations/google_key.py`).
`POST /v1/integrations/google/disconnect` asks Google to cancel the link and always forgets the tokens.
The panel, `src/jarvis/api/static/console-integrations.js`, shows the link, the extras and any reconnect hint from `GET /v1/integrations`.
The same folder holds the GitHub link (`src/jarvis/integrations/github.py`) and the reader of your own YouTube playlists (`YouTubeOwn`), each described on its own card.

## What it costs
Nothing: the link makes no paid call and no AI call (`GoogleConnector`). What each tool uses of Google's free allowances is counted on the free allowance ledger (C44).

## When it fails
An expired or cancelled link: the tools answer "Google needs reconnecting (panel → Integrations)." and nothing else breaks (`GoogleConnector`). A vault entry that won't decrypt, say after the key changed, counts as needing a reconnect, never a crash (`VaultError`). A missing permission or refresh token stops the connect with a plain reason (`GoogleScopesMissing`). With no token key outside development, the Google tools stay off rather than keep tokens unsafely (`google_tools_configured`). A Google service switched off in the cloud project gets its own plain message (`service_off_message`).
