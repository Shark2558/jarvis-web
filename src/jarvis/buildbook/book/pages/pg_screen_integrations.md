---
page: pg_screen_integrations
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/integrations.py": "849076061558773f"
  "src/jarvis/api/static/console-integrations.js": "2c3f17926e3d8d44"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
---
## In plain words
Integrations is where you link JARVIS to your accounts and your home. Its first card is your Google account: once linked, JARVIS reads your calendar, finds free time, and searches, drafts and sends mail, with anything that sends or deletes still waiting for your approval. Extra Grants add your to-do list, contacts, YouTube playlists and the photos you pick, each only when you press its Grant. Further down sit WhatsApp drafts, Telegram, your home laptop, alerts, Drive, Maps places and the systems check (`src/jarvis/api/static/console.html`).

## Example (made up)
On your first evening with JARVIS you open Integrations and press Connect Google. Google's own page asks which account; you choose the one you sign in to JARVIS with and keep every box ticked. Back in the console, the card says "Connected as" your address, with "Calendar: read & edit · Gmail: read, draft, send". A week later you want JARVIS to see your to-do list, so you press Grant on "To-do list — permission needed", agree on Google's page, and the card's permission line now also reads "To-do list: read & edit".

## How it works
When the panel opens, it asks `GET /v1/integrations` whether Google is linked, with which address, which permissions it holds and which Grants this server offers (`src/jarvis/api/static/console-integrations.js`). Connect Google sends your browser to `GET /connect/google`, which opens Google's consent page for the account you are signed in with (`src/jarvis/api/integrations.py:connect`). Google sends you back to `GET /connect/google/callback`, and the link is kept only if the account that agreed is the one signed in to JARVIS and every Calendar and Gmail permission was granted (`src/jarvis/api/integrations.py:connect_callback`). A Grant button runs the same consent for one more permission, such as the to-do list (`src/jarvis/api/integrations.py:connect`). Disconnect asks first, then `POST /v1/integrations/google/disconnect` cancels the link at Google and forgets it (`src/jarvis/api/integrations.py:disconnect`). The card shows "Needs reconnecting" when Google stops accepting the saved link, and Calendar and Gmail tools pause until you reconnect (`src/jarvis/api/static/console-integrations.js`). The Maps Home and Work places and the systems check card sit in the same panel (`src/jarvis/api/static/console.html`).

## What it costs
Linking Google costs nothing: JARVIS uses Google's own sign-in and its free Calendar and Gmail access (`src/jarvis/api/integrations.py`). The replies that use these tools are priced like any other reply, in rupees under each reply (`src/jarvis/api/static/console-integrations.js`).

## When it fails
If Google was linked with a different account, the panel says so and asks you to connect again with the account you sign in with. If some boxes were left unticked, it says "Some permissions were left unticked" and asks you to keep every Calendar and Gmail box ticked. If Google stops accepting the link, the card says "Needs reconnecting" and offers Reconnect. On a server without Google sign-in, the panel says linking is not available in this setup.
