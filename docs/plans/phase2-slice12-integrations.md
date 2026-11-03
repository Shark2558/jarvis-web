# Phase 2 · Slice 12 — Integrations wave: Drive (chosen folders), Maps, YouTube & music, Contacts, WhatsApp drafts — and the road for Swiggy, home and watch

Status: PLAN v1 · 2026-11-03 · branch `slice12` (from `main` @ 571402b, PR #17 merged and deployed —
CI test 3.11/3.12, firestore, browser, eval-gate, deploy all green)

## Owner request (3 Nov 00:51 IST)
"Next I want you to integrate with Google Services, Google maps, Music, Youtube, Swiggy, Whatsapp,
Noise watch, My Ecovacs robo cleaner, Google home and any other integration, Google drive Selected
folders only."

## Owner decisions (3 Nov, after the research summary)
- Music: **no Spotify Premium → YouTube only** (no Spotify slice).
- Home hub: **try Home Assistant free on the laptop first** (VirtualBox); buy hardware only if it
  proves useful. Slice 14 must cope with the hub being offline (plain "your home hub is off" reply).
- Swiggy: request to builders@swiggy.in **saved as a Gmail draft** for the owner to send
  (redirect URI `/connect/swiggy/callback`, Food + Instamart, single user, passkey on every order).
  Swiggy's process: form at mcp.swiggy.com/builders/access/ or email → staging access → production
  after the staging integration is green (demo video helps).
- Ecovacs: **wait for the home box** — connect through Home Assistant, not Ecovacs' Open Platform.

## Architecture fit
Every item is already named in the reference architecture's Layer 6 (Integration & Tools):
*Messaging — WhatsApp*, *Smart Home / IoT — Home Assistant, Matter*, *Maps & Travel — Google Maps*,
*Media — Spotify, YouTube*, *Knowledge — Drive*, *E-commerce — orders*. No architecture change; one
recorded deviation (D1: Drive through the runtime service account instead of the owner's OAuth).

## Phase mapping and verdict (research verified 2026-11-03; sources at the end)

| Integration | Phase · skill | Verdict | Why |
|---|---|---|---|
| **Google Drive — chosen folders only** | 2 (file system) · Research & Intel | **Build now** | Owner shares each folder with JARVIS's own Google identity; Google enforces the boundary (D1) |
| **Google Maps** (places, travel time) | 2 · Task & Productivity | **Build now** | Free a month: 5,000 text searches and 5,000 traffic-aware routes (35,000 each on India's price list, India billing accounts only); two-wheeler 1,000 (7,000) (D2–D3) |
| **YouTube** (search, play, your playlists) | 2 · Creative | **Build now** | Data API free (10,000 units/day; search 100 calls/day since 1 Jun 2026) (D4) |
| **Music** | 2 · Creative | **YouTube now; Spotify only with Premium** | Spotify dev mode (Feb–Mar 2026) needs the owner on Premium, ≤ 5 users; YouTube Music / JioSaavn / Gaana have no official API |
| **Google Contacts** ("any other") | 2 · Communication | **Build now** | People API, free; needed to turn "message Ravi" into a number or address (D5) |
| **WhatsApp** | 2 · Communication | **Build now as drafts** | JARVIS writes, owner taps Send (`wa.me` link). No sending by JARVIS (D6) |
| **Swiggy** (food, Instamart) | 2 · Task (spends money) | **Next wave — blocked on Swiggy** | Official MCP (Jan 2026) with OAuth 2.1 + PKCE + DCR; a Cloud Run redirect URI needs Swiggy's approval (builders@swiggy.in). Orders: COD or UPI link (owner enters PIN) → always R3 card + passkey |
| **Ecovacs robot vacuum** | 5 (IoT) · Automation | **Next wave — try Ecovacs' official connection first** | Ecovacs Open Platform publishes an official MCP server (start/stop/dock/status) — no home box needed if the owner's account is eligible; Home Assistant's Ecovacs integration is the fallback |
| **Google Home** devices | 5 · Automation | **Later — needs a home hub** | Home APIs are Android/iOS only; Home MCP (Sep 2026) needs Home Premium Advanced, US only, not India |
| **Noise watch** | 6 (wearable) · Learning/health | **Premature** | No API; data only on the phone (Health Connect / Apple Health) → needs a phone companion app; health data is sensitive |

Not chosen (and why): WhatsApp Business Cloud API as JARVIS's chat channel (Meta's Business
Solution Terms, in force 15 Jan 2026, bar general-purpose AI assistants outside EEA/Brazil; also
needs a separate number) → Telegram stays the planned mobile front door. Unofficial WhatsApp
libraries (Baileys, whatsapp-web.js) → account-ban risk on the owner's main number. Zomato MCP
(approved clients only, "third-party apps not allowed"). Google Keep (Workspace only). Google Fit
(closed, ends 2026). Strava (bans AI use of its data). ytmusicapi (cookie scraping).

## Decisions

**D1 · Drive = folders shared with JARVIS's service account (read-only).** Verified: `drive.file`
plus a Picker-chosen folder gives NO access to the files inside (Google's docs are silent; a
community test in Oct 2026 listed 0 files), and `drive.readonly` would let a code bug read the whole
Drive. So: the owner opens a folder in Drive → **Share** → pastes JARVIS's address
(`jarvis-run@<project>.iam.gserviceaccount.com`, shown with a Copy button in Integrations) →
**Viewer**. Subfolders and files added later are included automatically. Switching a folder off in
JARVIS stops access at once; un-sharing in Drive also stops it (within a minute) unless someone
else has shared it too. JARVIS calls Drive v3 as `jarvis-run` (no OAuth token, so **no 7-day
Testing-mode expiry**, no new consent). Guard rails:
- *Owner confirms each folder*: anyone who knows the address could share things with it, so
  Integrations lists folders shared with JARVIS and only those the owner ticks **Use** are read.
  Ownership test (Use and every re-check): `sharingUser.emailAddress` is the owner's verified
  email; when Drive leaves `sharingUser` out, the owner's email is in `owners[]`; a sharer who is
  someone else never passes. Use asks Drive for that folder (folder, not trashed, same id, the
  owner's). The list is flood-proof: folders the owner OWNS first, then a bounded sharer-matched
  list; other accounts' shares are only a count. Store: `drive_roots/{uid}` {roots: [{id, name,
  confirmed_at, email}]} (≤ 20; `email`: the address that switched it on).
- *Every switched-on folder is re-checked* on each tool call (≤ 60 s cache per instance): still
  visible, not trashed, still the owner's by the same test against the stored email. One that
  fails is OFF for every tool (kept in the store); Integrations says "Switched on, but JARVIS
  can't currently read it".
- *Every file id is checked*: walk `parents` (cached 60 s, ≤ 12 levels) to a confirmed root
  before reading; anything else → "not in your chosen folders".
- One extraction slot for the whole app: Drive files go through `DocumentService.extract`
  (injected by the app), never a second sandbox.
- Read-only: service accounts have no storage of their own, so JARVIS cannot create files there.
  Saving into Drive is a later item (`drive.file` OAuth, files JARVIS creates).
- Token: the Cloud Run metadata server with the `drive.readonly` scope (verify; fallback: IAM
  Credentials `generateAccessToken` for `jarvis-run` on itself — `cloudrun.sh` grants
  `iam.serviceAccountTokenCreator` only if needed). `cloudrun.sh` enables `drive.googleapis.com`.
  **Verified (builder A, 3 Nov):** google-auth's `compute_engine.Credentials` docstring: "On Cloud
  Run, Flex and App Engine the server honours requested scopes" (only Compute Engine ignores
  them); it sends `?scopes=` exactly as JARVIS does. So no fallback and no token-creator grant.
  The official Cloud Run container-contract page could not be fetched from the build sandbox:
  confirm live after deploy (see *Slice 12: check after deploy*, Drive).
- Content: Google Docs/Slides → `text/plain` export, Sheets → `text/csv` (first sheet), PDF/DOCX/
  TXT/MD/CSV ≤ 10 MB → the slice 10 sandboxed extractor. Everything is **other people's words**
  (untrusted, fenced, taints the round), never sent to training brains.
- Tools (R1): `drive_folders`, `drive_list(folder, page)`, `drive_search(query)` (fullText, then
  filtered to confirmed roots), `drive_read(file, part)` (chunked like documents).
- Deviation recorded: the owner's identity is not used for Drive; reading is done as JARVIS.

**D2 · One server-side Google API key + JARVIS's own allowance ledger.** `cloudrun.sh` creates
`jarvis-maps-yt` with `gcloud services api-keys create`, restricted to Places API (New), Routes
API and YouTube Data API v3 (not Geocoding: Routes geocodes address waypoints itself and no
Google doc says it needs the Geocoding API), stores it in Secret Manager (`jarvis-google-api-key`,
readable only by `jarvis-run`) and enables the three APIs. After every create / update it reads
the key's allowed APIs back; unless they are exactly those three, Maps and YouTube stay off for
that deploy (unmounted on a quick re-run). The key never reaches the browser.
JARVIS keeps a deployment-wide counter per SKU — the SKU Google actually bills each call as — and
stops at **90 % of the free allowance** of the billing account's price list; like Tavily, it never
runs into paid use. Free allowances a month (Pacific-time months, as Google bills; verified
2026-11-03, sources below):

| JARVIS SKU | Google SKU (trigger) | India price list | global price list |
|---|---|---|---|
| `maps_search` | Places API Text Search Pro (our Pro-only field mask) | 35,000 → stop 31,500 | 5,000 → stop 4,500 |
| `maps_route` | Routes: Compute Routes Pro (car, `TRAFFIC_AWARE`) | 35,000 → 31,500 | 5,000 → 4,500 |
| `maps_route_2w` | Routes: Compute Routes Enterprise ("two-wheeled vehicle routing") | 7,000 → 6,300 | 1,000 → 900 |
| `maps_route_walk` | Routes: Compute Routes Essentials (walk: no Pro / Enterprise feature) | 70,000 → 63,000 | 10,000 → 9,000 |

YouTube search 90/day (of its own 100) and other YouTube units 9,000/day (of 10,000), Pacific-time
days, on either list. `JARVIS_MAPS_PRICING` = `india` | `global` (default **global**, the low
caps, so a wrong guess only stops early); `cloudrun.sh` sets `india` only when `gcloud billing
accounts describe <account> --format='value(currencyCode)'` is `INR`, else `global` with a plain
note. Every "paused" message is built from the cap (`Sku.reached`). Plus per-message caps (3 Maps
calls, 2 YouTube searches) and 30 Maps calls/hour (a call counts towards the hour only once the
allowance let it through). Corrupt counters fail closed.
*Google's own "quota gone"*: every Places / Routes 429 is `RESOURCE_EXHAUSTED`, most of them
per-minute. Only an error whose ErrorInfo `metadata.quota_limit` / `quota_unit` (or QuotaFailure
`quotaId`) names a per-day or per-month limit latches — a per-day limit closes only that day
(`closed_day` on the month's counter), a per-month one the month — and always the period of the
call's reservation (a call made at 23:59 Pacific answered at 00:01 closes the old day). Every
other 429, and YouTube's 403 `rateLimitExceeded` / `userRateLimitExceeded`, is "busy, try again";
YouTube's `quotaExceeded` / `dailyLimitExceeded` close its day. Calls with the owner's token
(playlists) follow the same refund / latch rules. Shared counter code with web search:
`jarvis.quota.counter`.
*Second brakes* (non-fatal steps in `cloudrun.sh`): a budget of 1 in the billing account's
currency (₹1 for an Indian account) whose alerts email the billing account's admins on any charge
to the project. Per-day consumer quota overrides (`gcloud beta quotas preferences create`) are
NOT scripted: Google's docs (checked 2026-11-03) give no quota IDs for Places Text Search or
Routes ComputeRoutes per day — set them by hand (see *Slice 12: check after deploy*, Maps).

**D3 · Maps tools (R1).** `maps_search(query, near?)` — Places Text Search (New) with a **Pro field
mask only** (id, displayName, formattedAddress, location, googleMapsUri, businessStatus); no
ratings/hours/phone (Enterprise SKU, 7,000 free). `maps_route(from, to, mode, depart?)` — Routes
`computeRoutes`, `TRAFFIC_AWARE` (Pro SKU) for drive / two-wheeler, `walk` without traffic;
returns duration, distance, a Google Maps directions link. Terms: show "Google Maps" attribution and
the `googleMapsUri` links on every card; cache nothing but `place_id`; never feed results to a
training brain; never draw them on a non-Google map. Owner-set **Home** and **Work** (Integrations
→ Maps; plain text ≤ 200 chars, stored in `maps_places/{uid}` **encrypted with the token key**,
the OAuth tokens' AES-256-GCM cipher, AAD `maps_places/{uid}`; no key → this process only) let
"how long to work?" resolve without asking; they are the owner's own words (trusted), sent to
Google only in a route call — and in a round that read other people's words (a page, a mail, a
place name) a route that would send them asks the owner first (`Tool.ask_when`; the gateway now
honours it for read-only calls too, and an approval token is always spent). Directions links are
cut to Google's 2,048-character limit by their ENCODED length, longest encoded field first, at a
comma.

**D4 · YouTube and music.** `youtube_search(query, kind=video|music)` (API key; music adds
`videoCategoryId=10`); results show title, channel, length and a **Play** button; the console
plays in a `youtube-nocookie.com` embed inside the Media panel (CSP adds only
`frame-src https://www.youtube-nocookie.com`). The console page keeps `Referrer-Policy:
no-referrer`: Google's player refuses to play without the embedding origin (Error 153), but an
iframe's own `referrerpolicy` attribute governs the request for that frame, so only the player's
iframe carries `referrerpolicy="strict-origin-when-cross-origin"` — YouTube gets the console's
origin (never a path or query) and nothing else on the page sends a referrer (browser-tested).
JARVIS never autoplays without the owner's click on Play. The search is paid first, so when the
durations can't be had (videos.list failed, units used up) the results come without them. Optional **Grant** (`youtube.readonly`): `youtube_my_playlists`, `youtube_playlist`
(liked videos included). Watch history is not available through any API (verified). Titles and
descriptions are other people's words (untrusted). **Spotify**: only if the owner has Premium
(owner question); then a separate small slice (dev-mode app, PKCE, `user-modify-playback-state`).

**D5 · Contacts (R1).** Optional Grant (`contacts.readonly`), same pattern as the to-do list
(`/connect/google?add=contacts`). `contacts_search(name)` → ≤ 5 matches: name, email addresses,
phone numbers normalised to E.164 (+91 default). Untrusted (people write their own profile names),
never to training brains. JARVIS keeps no contact list: a look-up's result is kept only in the
conversation it was made in (as a tool result, like every tool's) and deleted with it; the audit
holds only a hash of the name asked for.

**D6 · WhatsApp drafts.** `whatsapp_draft(to, text)`: `to` is a phone number the owner typed or a
Contacts match; text ≤ 2,000 characters. Result: a draft card with the recipient's name + number,
the text, and **Open in WhatsApp** (`https://wa.me/<digits>?text=<urlencoded>`, opened only by the
owner's click). JARVIS sends nothing; WhatsApp then shows the text in the chat box and the owner
presses Send. A number that came from outside content (an email, page, document) — not typed by
the owner and not in Contacts — shows a warning line, like un-typed email recipients. Treated as
R1 (nothing leaves JARVIS), its own permission row so the owner can switch it off.

**D7 · Grants generalised.** `/connect/google?add=<tasks|contacts|youtube>` (exactly one name,
allow-listed); a renewal keeps every optional scope already held. `/v1/integrations` carries the
Google link plus, per Grant, `tasks_granted` / `contacts_granted` / `youtube_granted` and
`tasks_available` / `contacts_available` / `youtube_available` (its tools exist here and its row
is not Never). **Decision at integration: Drive, Maps and the allowance counts keep their own
endpoints** — `/v1/drive` (service address, shared and switched-on folders), `/v1/maps/places`
(configured, Home / Work) and `/v1/quota` (the Vitals counts) — and `/v1/integrations` adds no
summary blocks for them: each panel reads the endpoint it owns, so a Drive or Maps failure can't
break the Google link's view.

**D8 · Permissions rows (R1, Allow / Ask first / Never):** Drive · Maps · YouTube · Contacts ·
WhatsApp drafts. "Never" switches the tools off and the console hides their buttons.

**D9 · Costs.** All ₹0 inside the caps. Vitals: "Maps: N of 4,500 searches / N of 4,500 routes
this month" (31,500 on India's price list; "· two-wheeler paused" / "· walking paused" when those
SKUs' own stops are reached), "YouTube searches today: N of 90". Claude reading the results adds
roughly ₹0.5–2 per reply (as with web search).

**D10 · Safety, same as slice 10/11.** Drive files, place names/addresses, YouTube titles and
contact fields are other people's words: fenced with the per-call nonce, they taint the round
(`policy.TAINTED_WRITES_ASK`), so a hostile document can't make JARVIS change anything without a
card. Results never vouch (`may_vouch` false). No new R3 in this slice.

**Review fixes for D5–D8 (builder C, after two independent reviews of 4784621).**
- S1: a look-up that names another permission row (`Preview.also`) gets that row's whole
  decision — "Never" refuses, "Ask first" makes the call a card (a draft by name with Contacts on
  Ask first no longer lists names and numbers without a card).
- S2: `contacts_search` has its own card text (`Look up “Ravi” in your Contacts`); `Tool.summary`
  never raises (a template that can't be filled falls back to the generic card and is logged).
- S3: `whatsapp_draft` asks on a spoken turn or in a tainted round (`ask_when`; the gateway
  honours it for read-only calls, as builder B's maps_route needs): a one-by-one R1 card (no
  passkey, never in Approve all) showing the whole text, quoted line by line, with its line count.
  The text also loses characters that render blank (Hangul fillers, braille blank, CGJ, Khmer
  inherent vowels, Mongolian selectors, variation selectors but an emoji's), trailing spaces and
  runs of more than two blank lines; a text that is blank after that is refused. The console
  checks the same and shows the whole text (no inner scroll box) with "N lines" for long texts.
- S4: only typed owner messages vouch for a number; a spoken current message never does.
- S5: a +91 number must have exactly 10 digits after the code (first 2–9), else "check the
  number"; a number written without a country code shows "Assumed India (+91)" on both cards.
- S6/C2: the wording now says what happens — a look-up's result lives in its conversation (a
  tool-result turn) and is deleted with it (turns, waiting cards; the audit has only hashes).
- S7/S8: the hint says "Nothing is sent to <name> until you press Send in WhatsApp." and that
  opening the link hands the text to WhatsApp; the number is bidi-isolated.
- C3: one usable number among more matches than shown still asks which.
- C5: the Integrations section is `console-integrations.js`; every console*.js ≤ 800 lines.
- C7/C8: `/v1/integrations` says per Grant whether it is `available` (its tools exist — YouTube
  needs the server's API key — and its row is not Never); a Grant is held when any accepted scope
  is (YouTube: youtube.readonly, youtube, youtube.force-ssl), but only the read-only one is asked.
- C9: at most 5 draft cards per reply across rounds and in Approve all; the Contacts warm-up is
  best effort.
- Integration: a draft is one kind ("whatsapp") in `ChatResponse.cards`, added by the tool with
  `reply_cards.add_card` (caps per reply: 8 Maps / YouTube cards, 5 drafts, counted apart); the
  separate `ChatResponse.whatsapp` field, `whatsapp.cards` and the name-fence reader are gone.

## Slice 12: check after deploy
None of these could be verified from the build sandbox. The owner checks them once, after the
first deploy of this slice.

Drive
- Integrations → Google Drive lists a folder you shared with JARVIS's address (this proves Cloud
  Run's metadata server honours `?scopes=drive.readonly`).
- Drive returns `sharingUser` for a gmail.com account (if not, every check runs on the `owners[]`
  fallback: still safe, but an editor's re-share can't be told apart).
- The longest Drive file / folder name (names past 300 characters are cut; pages are 25 entries so
  a page of the longest names stays under the 2 MB answer cap).
- Whether a `pageToken` is bound to its query (`drive_list` drops any item whose `parents` don't
  include the folder either way).
- Drive accepts `sharedWithMe and '<email>' in owners` and `fullText … and '<email>' in owners`
  (if not, the view and search fall back to the bounded, unfiltered lists).

Maps and YouTube
- APIs & Services → Credentials → `jarvis-maps-yt` allows exactly Places API (New), Routes API and
  YouTube Data API v3.
- The deploy summary's "Maps price list" says `india` only if the billing account bills in rupees.
- Billing → Budgets and alerts lists `jarvis-any-charge` (₹1 on an Indian billing account); if the
  deploy said it could not add it, add one by hand (alerts to billing admins).
- Billing → Reports, grouped by SKU, shows no Geocoding charges from routes.

Contacts and WhatsApp
- APIs & Services → Enabled APIs lists the People API (the deploy says so if it could not).
- The OAuth consent screen's Data Access lists `contacts.readonly` and `youtube.readonly`; then
  Integrations → Contacts → Grant and YouTube playlists → Grant each work.
- After a Grant, a search for a contact you added minutes ago finds it (Google gives no figure for
  how long its contacts cache takes to catch up).
- Open in WhatsApp on a phone and on a laptop opens the right chat with the text filled in
  (WhatsApp's own click-to-chat page could not be fetched; the wa.me format comes from pages that
  cite it).

Optional second safety net: Google's own per-day Maps caps. JARVIS already stops at 90 % of the
free allowance; these caps make Google refuse calls past a daily limit even if JARVIS's counter were
wrong. Not scripted, because Google publishes no quota IDs for these limits.
1. Google Cloud Console → APIs & Services → Places API (New) → Quotas.
2. Find the per-day Text Search request limit and choose Edit.
3. Enter about the monthly stop ÷ 30: 150 a day on the global price list, 1,050 on India's.
4. Save, and check the new limit is shown.
5. Do the same for Routes API (APIs & Services → Routes API → Quotas → the per-day Compute Routes
   limit), with the same numbers.

## Next waves (not built in this slice)
- **Swiggy (slice 13, after Swiggy approves the redirect URI).** First real MCP **client** in
  JARVIS (`jarvis.mcp`: streamable HTTP, OAuth 2.1 + PKCE + Dynamic Client Registration, tokens in
  the AES-GCM vault, rotating refresh token). Read tools R1 (search, menu, cart view, track ≥ 10 s
  apart); cart changes R2; **`place_*_order` = R3 always** (card shows items, total in ₹, address,
  payment method; passkey); cancellation is by phone only (shown on the card). Owner step: email
  builders@swiggy.in asking to allow `https://jarvis-320922108419.asia-south1.run.app/connect/swiggy/callback`
  (Claude can draft it).
- **Home (Phase 5; slice 14 once a hub exists).** Home Assistant at home (24/7) is the hub:
  official Ecovacs integration (Deebot start/stop/dock/rooms), Google Cast (Nest speakers:
  announcements, media), Matter devices, many Wi-Fi plugs/bulbs via their own integrations.
  JARVIS → Home Assistant's official MCP server over a tunnel (details below), dedicated HA user,
  only exposed entities; "start cleaning" R2, locks/garage/alarm R3 (never automatic).
- **Noise watch (Phase 6).** Only via an Android companion app reading Health Connect — and only if
  NoiseFit writes there (unverified). Health data stays on the device by default.
- **Telegram front door** stays next in the pipeline (the WhatsApp-channel alternative).
- Optional later: Google Photos Picker (pick photos to discuss), Zerodha Kite read-only portfolio
  (Finance skill; never trades), Drive saving via `drive.file`.

## Home automation research (verified 2026-11-03)
- **Ecovacs, direct (no hub) — try first.** Ecovacs' own Open Platform (open.ecovacs.com) publishes
  an official MCP server (`ecovacs-ai/ecovacs-mcp`, MIT, v1.0 Apr 2025): list devices, start /
  pause / resume / stop cleaning, return to dock, status; auth = a "server AK" from the Open
  Platform console; remote SSE `https://mcp-open.ecovacs.com/sse?ak=…` (key in the URL → JARVIS must
  never log that URL; key in Secret Manager). Unverified: who may register, cost, India accounts,
  which models. Owner step: sign up and check. If it works, the vacuum joins slice 13 without
  Home Assistant ("start cleaning" R2, Allow-able; nothing irreversible).
- **Ecovacs via Home Assistant**: the built-in integration (`deebot-client`, reverse-engineered,
  v18.7.0 16 Oct 2026, Python ≥ 3.14; broke in Jul 2026 on Ecovacs' device verification, fixed in
  HA 2026.8–2026.10.2). Fallback only.
- **Google Home devices**: no server API (Home APIs are Android/iOS; Home MCP needs Home Premium
  Advanced, US only). Through Home Assistant: **Google Cast** (Nest speakers/displays: announcements,
  media; same network), **Matter** sharing from Google Home via the Android Companion app, and each
  Wi-Fi bulb/plug through its own vendor integration (Tuya / Smart Life by QR code; Wipro devices
  are often Tuya). The Google Assistant SDK route is fragile (no text replies, Gemini replacing
  Assistant on speakers) → not used.
- **Home Assistant MCP server** (since 2025.2): Streamable HTTP `/api/mcp`; least privilege =
  a dedicated **non-admin** HA user calling `/api/mcp/assist`, which reaches only entities exposed
  to Assist. Token in Secret Manager.
- **Hub hardware**: HA OS in VirtualBox on the owner's laptop = ₹0 prototype (offline whenever the
  laptop sleeps); always-on Raspberry Pi 5 4 GB ≈ ₹12,000 in India + ≈ ₹1,500–3,000 accessories
  (≈ ₹15–25/month power); HA Green US$199 ≈ ₹18,900 + import (no Indian distributor).
- **Reaching home from Cloud Run, privately**: Tailscale (free Personal plan) inside Cloud Run in
  userspace mode, so Home Assistant is never on the public internet (unverified: cold starts / idle
  CPU throttling). Fallbacks: Nabu Casa ≈ ₹6,175/year (USD-billed); Cloudflare Tunnel needs a
  domain (≈ ₹995/year).
- **Device risk tiers** (slice 14): read state R1; lights, plugs, media, vacuum R2 (Allow-able);
  locks, garage doors, alarms, heaters/geysers on a timer → R3 always, never by voice.

## Shared rules for every builder
- Start: `git merge --ff-only slice12` in your worktree; commit on your own branch `s12-<x>`.
- Tests first. Run with `PYTHONPATH=$PWD/src /tmp/venv-b/bin/python -m pytest -q` (3.11) and
  `/tmp/venv-12/bin/python` (3.12). Never `pip install -e` into the shared venvs. No 3.12-only APIs.
  Never `from tests.conftest import`. Fences: use `jarvis.tools.external.FENCE_END` etc., never a
  literal. Mock evals: `PYTHONPATH=$PWD/src /tmp/venv-b/bin/python evals/run_all_mock.py`.
  Browser tests: `JARVIS_BROWSER_TESTS=1 PYTHONPATH=$PWD/src /tmp/venv-c/bin/python -m pytest
  tests/browser -k <yours>` (never `playwright install`).
- Every tool goes through `jarvis.tools.gateway`; only `jarvis.llm` imports vendor SDKs; HTTP
  adapters use `httpx` with an overall deadline, redirects off, response size caps, strict response
  validation; Google calls with the owner's token reuse `GoogleConnector.request`. Secrets only via
  settings `SecretStr`; never logged. Vendor error text never reaches the model or the owner.
- Tool output from Drive, Maps, YouTube, Contacts is untrusted: wrap with `jarvis.tools.external`
  fences and taint the round (`jarvis.tools.taint`). Training brains (`trains_on_content`) never get
  these tools or their content.
- UI: `textContent` only, no CDNs, ₹ only (never "$"), plain-English messages, error shape
  `{error, detail, reason?}`; follow Command Deck patterns (collapsed settings, confirm dialogs with
  focus trap); CSP changes only as D4 says.
- Do NOT bump `PERSONA_VERSION` (integration does). New persona/tool rules in a separated
  paragraph. New dependencies: `pyproject.toml` only (integration runs `make lock`); permissive
  licences only. `brain.py` stays under its 800-line guard.
- Final report ≤ 300 words: what changed, test counts, not verified, open questions.

## Builders (worktrees, tests first)
- **A · Drive** — `jarvis.drive` (ports, service-account token, roots store, parents check,
  export/extract), tools, Integrations section (address + Copy, shared folders, Use toggles),
  `cloudrun.sh` (enable Drive API; token-creator grant only if needed).
- **B · Maps + YouTube** — `jarvis.places` + `jarvis.media` on one `GoogleKeyClient`, the
  allowance ledger (`jarvis.quota`), tools, Home/Work settings, console cards (place, route,
  video) + Media panel player, CSP/referrer change, `cloudrun.sh` key + APIs + secret.
- **C · Contacts + WhatsApp + grants + permissions** — Grant generalisation (D7), People API
  client, `contacts_search`, `whatsapp_draft` + draft card, the five permission rows, persona note.
- Then fresh-context reviews (security for A/B/C, code for each), fixes tests-first, an
  integration builder, an integrated review, browser tests, mock evals, PR.

## Evals (gate: all pass in mock mode; negative controls must fail)
- **drive**: 25 path cases (in root, nested 5 deep, outside, unconfirmed root, root shared by
  someone else, moved out of the root, trashed, shortcut to outside; 5 sharer refusals: a
  stranger's share switched on — also a look-alike name and with `sharingUser` left out — and a
  switched-on root the owner un-shared that an editor re-shared) → 100 % correct allow/deny;
  injection 10 (a shared doc telling JARVIS to email/delete) → 0 unconfirmed writes; negative
  controls: an allow-all guard → suite fails; Drive tools trusted → injection fails; ownership
  test saying yes → every sharer case fails.
- **maps**: 18 cases (place found / none / ambiguous, route drive/two-wheeler/walk, Home/Work
  resolution, cap reached → plain message, two-wheeler (Enterprise) stop while a car route still
  goes, corrupt ledger → fail closed, a per-minute 429 never latches, a per-day quota closes only
  today, a hostile place name can't send Home to Google without a card, attribution + link
  present on every card); negative control: ledger off → fails.
- **youtube**: 10 cases (search, music filter, cap 90/day, playlist needs Grant, titles fenced);
  0 autoplays without a click (browser test).
- **contacts + whatsapp**: 15 cases (one match, several → asks, none, +91 normalisation, number
  from an email → warning, text > 2,000 → refused, Never → refused; link built exactly); negative
  control: provenance check off → fails.
- **permissions**: each new row Allow/Ask/Never × its tools.

## Sources (accessed 2026-11-03)
Drive scopes/Picker: developers.google.com/workspace/drive/api/guides/api-specific-auth,
developers.google.com/workspace/drive/picker/guides/overview, github.com/arc53/DocsGPT/pull/3169 ·
Testing-mode 7-day consent: support.google.com/cloud/answer/15549945 · Maps India:
developers.google.com/maps/billing-and-pricing/pricing-india, …/india, cloud.google.com/maps-platform/terms,
developers.google.com/maps/documentation/places/web-service/policies · Maps free caps and SKU
triggers (verified 2026-11-03): developers.google.com/maps/billing-and-pricing/pricing-india
("Places API Text Search Pro (India)" 35,000; "Routes: Compute Routes Essentials / Pro /
Enterprise (India)" 70,000 / 35,000 / 7,000), developers.google.com/maps/billing-and-pricing/pricing
(global: Text Search Pro 5,000; Compute Routes Essentials / Pro / Enterprise 10,000 / 5,000 /
1,000), developers.google.com/maps/billing-and-pricing/sku-details/routes (Pro: TRAFFIC_AWARE;
Enterprise: "Two-wheeled vehicle routing"; Essentials: no Pro / Enterprise feature),
developers.google.com/maps/billing-and-pricing/sku-details/places (our six fields are Text Search
Pro), developers.google.com/maps/documentation/routes/usage-and-billing,
developers.google.com/maps/documentation/routes/specify_location ("Routes API internally geocodes
the string"; no Geocoding API requirement stated) · Billing account currency:
docs.cloud.google.com/billing/docs/reference/rest/v1/billingAccounts (`currencyCode`) · Budgets:
docs.cloud.google.com/sdk/gcloud/reference/billing/budgets/create · YouTube:
developers.google.com/youtube/v3/determine_quota_cost, …/revision_history,
developers.google.com/youtube/iframe_api_reference · Google Home: developers.home.google.com/apis,
developers.home.google.com/mcp/home · People API / Photos Picker / Google Health:
developers.google.com/people, developers.google.com/photos/picker, developers.google.com/health/about ·
Swiggy: mcp.swiggy.com/builders/docs/start/authenticate.md, …/reference/food/place_food_order/,
mcp.swiggy.com/builders/blog/2026-07-10-mcp-payments-upi/ · Zomato: github.com/Zomato/mcp-server-manifest ·
WhatsApp: whatsapp.com/legal/business-solution-terms, developers.facebook.com/docs/whatsapp/pricing,
whatsapp.com/faq/en/general/26000030 · Telegram: core.telegram.org/bots/faq · Spotify:
developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide,
…/concepts/quota-modes · Noise: play.google.com/store/apps/details?id=com.noisefit,
developer.android.com/health-and-fitness/guides/health-connect · Strava: developers.strava.com/docs/getting-started/
