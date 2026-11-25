---
page: pg_module_console
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
sources:
  "src/jarvis/api/app.py": "51eaf37fbe6a89cf"
  "src/jarvis/api/auth.py": "02a9e121c2585fd8"
  "src/jarvis/api/body.py": "94feeb1db871c289"
  "src/jarvis/api/console.py": "03b9b870e751911f"
  "src/jarvis/api/feature_wiring.py": "473760847cb35d03"
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/api/identity.py": "4b025a7710b59c4b"
  "src/jarvis/api/personal.py": "7a9aa32e08b7d084"
  "src/jarvis/api/r11_wiring.py": "4cfa5b25282b147c"
  "src/jarvis/api/r4_wiring.py": "379192618b74836f"
  "src/jarvis/api/r6_wiring.py": "a7a1861afa933ec1"
  "src/jarvis/api/ratelimit.py": "cb57d8dab93e8640"
  "src/jarvis/api/routes.py": "4086daa780722d3f"
  "src/jarvis/api/selfcheck_wiring.py": "fb7336391ffa3727"
  "src/jarvis/api/startup_log.py": "4ba9e18096e253e1"
  "src/jarvis/api/static/console-3d-scenes.js": "80d2691e8bb110de"
  "src/jarvis/api/static/console-3d.js": "b590fd5947ccb313"
  "src/jarvis/api/static/console-deck.js": "cfb441c3101b8045"
  "src/jarvis/api/static/console-dock.js": "0798faf0a39ad778"
  "src/jarvis/api/static/console-fx.js": "bb9dd7f373411a5f"
  "src/jarvis/api/static/console-helpers.js": "38c9179fa5cd2d23"
  "src/jarvis/api/static/console-text.js": "be5a5239bbffae37"
  "src/jarvis/api/static/console.css": "6a8f96e9bcd21971"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
  "src/jarvis/api/static/console.js": "ac49b62db99514f8"
  "src/jarvis/cli.py": "fe0bb250afc25bfa"
  "src/jarvis/storage/approvals.py": "0091801c464bb3d8"
  "src/jarvis/storage/audit.py": "d268e84d6aa87ab5"
  "src/jarvis/storage/docs.py": "561064f51e6e084f"
  "src/jarvis/storage/firestore_docs.py": "7077a22c0b20173d"
  "src/jarvis/storage/sessions.py": "c9a8ec12966d54db"
---
## In plain words
The console is the web page you use JARVIS from, on a laptop or a phone: the chat, a dock of panels such as Brief, Approvals, Activity, Memory, Vault, Home and Vitals, the brain picker, and the Night and Day looks. Behind it sits JARVIS's server, which lets in only the Google accounts you listed as owners, limits how fast anyone may call it, and keeps conversations, approvals and the audit trail in Google's Firestore database. Engineers have a terminal client too, for talking to the brain without the page.

## Example (made up)
Asha opens JARVIS on her phone at the bus stop and signs in with Google. Her address is on the owner list, so the console opens on the chat, with Chat, Brief, Approvals and a More button in the dock. She asks for today's plan and closes the browser. At 9:30 at her desk she opens the laptop and the same conversation is waiting, because it lives on the server, not on the phone. That evening her cousin tries the same link with his own Google account and sees "This JARVIS belongs to someone else."

## How it works
`console` in `src/jarvis/api/console.py` serves one page, `src/jarvis/api/static/console.html`, under a strict content security policy: scripts come only from JARVIS itself, and every library and font is served by JARVIS, never fetched from another site. `src/jarvis/api/static/console.js` runs the chat, the brain picker, approvals and conversations, and what the server sends reaches the page as plain text, never as code. A reply whose model has no known price says "price unknown", never ₹0, as does the deck's conversation cost (`src/jarvis/api/static/console-deck.js`). `src/jarvis/api/static/console-deck.js` draws the panels, and `src/jarvis/api/static/console-dock.js` fits the dock to the screen: buttons that don't fit move behind More, in their order. `src/jarvis/api/static/console-fx.js` gives the Night and Day looks, and `src/jarvis/api/static/console-3d.js` adds three.js scenes where the browser draws them. `create_app` builds the server in named steps: the core, each release's wiring such as `wire_features`, `wire_personal`, `wire_home` and `wire_r11`, then the middleware, error mapping and routes. `login` sends you to Google, and `callback` accepts only a verified address on `owner_emails`, then sets a signed session cookie that lasts {{fact:settings.session_cookie_max_age_s}} seconds (`src/jarvis/api/auth.py`). `require_auth` lets in that cookie or the terminal's bearer token, and a browser's writes must carry a JARVIS header that another website is unable to add (`CSRFRejected`). `current_user` works out who you are from the sign-in, and a user id sent by a client is never read (`src/jarvis/api/identity.py`). `RateLimiter` allows each client {{fact:settings.rate_limit_per_minute}} requests a minute, and `BodySizeLimit` refuses an oversized request before reading it. `chat` and `chat_stream` pass your message to the brain, and `approve`, `decline` and `approve_all` decide waiting cards (`src/jarvis/api/routes.py`). Every store speaks one small port, `Docs`; `FirestoreDocs` is the only file that talks to Firestore, and `MemoryDocs` is its twin for tests. `DocSessionStore` keeps conversations, `DocApprovalStore` the waiting cards and `DocAuditLog` the audit chain, all under the `firestore_prefix` name prefix. `main` in `src/jarvis/cli.py` gives the terminal its chat and serve commands, its chat line says "price unknown" the same way (`reply_meta`), and `log_up` writes one "jarvis up" line when the server is ready.

## What it costs
Nothing: the console is served by JARVIS itself, and the server and its database are set up to run inside Cloud Run's and Firestore's free tiers (`src/jarvis/storage/firestore_docs.py`).

## When it fails
A wrong or missing sign-in gets status 401, a Google account that isn't an owner gets status 403, and more requests than the limit get status 429 with a short wait (`src/jarvis/api/auth.py`, `RateLimiter`). A panel whose data doesn't arrive shows a plain message, and the rest keeps working. A browser that lacks WebGL2 simply skips the 3D scenes (`src/jarvis/api/static/console-3d.js`). A Firestore query whose index is still being built falls back to sorting inside JARVIS (`IndexNotReady`), and a write that clashes with another is retried up to {{fact:src/jarvis/storage/firestore_docs.py:TX_ATTEMPTS}} times.
