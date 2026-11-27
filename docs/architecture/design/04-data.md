Version v6.4.2 · 27 Nov 2026 · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV

# 04 · Data architecture

**In plain words.** Everything JARVIS keeps is in one Firestore database in your own Google Cloud
project, in Mumbai. Google encrypts all of it. On top of that, JARVIS locks ("seals") your most
private records with its own keys, so even someone reading the database sees only scrambled
bytes. Some things never reach the cloud at all: camera pictures and face pictures stay on your
laptop, and the "Hey Jarvis" listening and the phone camera's frames stay in your browser. You can
export or delete each kind of data from the Privacy panel; Google's daily backup copies (after
your one-time backup step) are gone within 7 days of a delete.

## 1. Where data lives

| Place | What is there | Who can read it | Evidence |
|---|---|---|---|
| Firestore `(default)`, asia-south1 | Everything JARVIS keeps (section 2) | `jarvis-run`; the project's owner in the Cloud console | `deploy/cloudrun.sh` step 4 |
| Secret Manager, same project | API keys, the session secret, the API token, the root token key | `jarvis-run`, one grant per secret | `deploy/cloudrun.sh` step 5 |
| Cloud Logging, same project | JSON logs with a trace id; the audit chain's `(seq, hash)` anchor; never a secret, a message's text or audio | the project's owner | `src/jarvis/logging.py`, `src/jarvis/storage/audit.py` |
| Firestore backups (after the owner's step) | A daily copy of the whole database, kept 7 days | Google, the project's owner, the drill | `deploy/backup_setup.sh` |
| The owner's laptop | Camera recordings and events, the face library, face attempts, the face groups' SQLite file, Home Assistant's own data | the owner; only the bridge's signed door is reachable from outside | `deploy/home/docker-compose.yml` (volumes) |
| The owner's browser | Wake-word detection, camera frames, the share tray (Cache Storage `jarvis-share-v1`, each item at most 24 hours), the camera-off switch, small conveniences (open conversation, look, sound devices) | the owner | C06, C62, C63 in the guide |
| The phone | The phone's P-256 key in secure hardware; the SOS numbers sealed for the offline SMS screen | the owner | C62, C65 |
| The owner's Google account | Calendar, Gmail, Tasks, Contacts, Drive, Photos, as always | Google and the owner; JARVIS through his link | C29 |

## 2. Firestore collections

**How many.** `scripts/arch_inventory.py` finds **126** collection names in the code (27 Nov 2026).
A wider search found **5 more** that its patterns miss: `wardrobe_outlook`, `wardrobe_plans` and
`wardrobe_cal`, named through a helper (`src/jarvis/wardrobe/styling/part.py:_sealed`, lines 50,
53 and 54; also `src/jarvis/wardrobe/kept.py:PLANS_SINGLES`), and `bills_told` and
`birthdays_told`, named in a tuple assignment (`src/jarvis/helpers/today/part.py`, line 36; also
`src/jarvis/helpers/kinds.py`). So the code names **131** top-level collections, and the table
below lists all 131 (checked name by name against the inventory on 27 Nov 2026). The coverage
check passes all the same, because the guide happens to name all five. Teaching the inventory both
idioms is not a docs-only change: the Build Book's fact pack uses the same patterns
(`src/jarvis/buildbook/gen/facts_code.py:COLLECTION`) and `tests/test_r63_a_facts_real.py` holds
the two counts equal, so both must change together (chapter 12, section 4; follow-up F2).
Every name carries the prefix `jarvis_` (`src/jarvis/config.py` `firestore_prefix`).

**Sub-collections.** Seven more names live under a parent document, listed for the restore drill
in `src/jarvis/backup/walk_checks.py:KNOWN_SUBCOLLECTIONS` (pinned against the code by a test):
`turns` (under `sessions`), `vault_chunks` (under `vault`), `chunks` and `pictures` (under
`attachments`), `book_chunks` (under `book`), `items` (under `deleted_items`) and `days` (under
`activity_days`); the Activity log's own days are `activity/{uid}/d{YYYYMMDD}`.

"Sealed" names the keyring purpose that encrypts the content (section 3); "token key" means the
root key directly (these predate the keyring). "Kept" is how long JARVIS keeps it; JARVIS's own
morning sweeps delete what expires, because Firestore TTL policies are billed and not used.

| Area | Collections | What they hold | Sealed | Kept |
|---|---|---|---|---|
| Conversations | `sessions` (turns under each), `meta` | Conversations; the audit head; a health ping | No | Until deleted |
| Approvals and audit | `approvals`, `audit` | Waiting cards (10-minute expiry); the hash-chained audit (tool, risk, outcome, arguments' hash, short detail; never the arguments) | No | Until decided; audit always (append-only) |
| Long-term memory | `memory`, `memory_shards` | Profile blocks and facts about the owner | No | Until deleted |
| Notes | `kb`, `kb_shards`, `kb_fetch` | Notes, memo transcripts, saved links | `notes` | Until deleted |
| Things | `belongings`, `belongings_history` | Where things are kept | `belongings` | Until deleted |
| Vault | `vault` (and chunks), `vault_unlocks`, `vault_alerts`, `vault_inbox` | Vault index and files; unlock windows and tickets; reminders sent; the DigiLocker folder | `vault_index`, per-file keys wrapped by `vault`; tickets as HMAC (`tickets`) | Until removed (30 days in the bin); tickets 60 s |
| Google link and tools | `tokens`, `connectors_github`, `drive_roots`, `maps_places`, `photos`, `outside_tasks`, `groceries`, `family_calendars`, `deleted_items` | OAuth tokens; the owner's GitHub token; chosen Drive folders; Home and Work; a Photos picker session (ids); ids of to-dos from outside content; the groceries list id; family calendars; undo copies | `tokens` and `maps_places`: token key; `connectors_github`: `connectors` | Until changed; undo copies 30 days |
| Attachments | `attachments` | Text chunks of attached files; cleaned pictures (at most 900 KB each) | No | With the conversation; unsent uploads 1 day |
| Brief | `briefs`, `brief_settings` | Morning briefs and their settings | No | Briefs 7 days |
| Activity | `activity`, `activity_days` | What JARVIS did, in plain words | No | 7 days |
| People research | `people_last` | The last research | No | Replaced by the next |
| Permissions and passkeys | `permissions`, `passkeys`, `webauthn_challenges` | Allow / Ask first / Never choices; passkey public keys; one-time challenges | No (public keys only) | Until changed; challenges 2 minutes |
| Costs and allowances | `usage`, `allowance`, `budget`, `fx`, `api_quota`, `web_usage`, `web_vendor_usage`, `token_ledger` | ₹ per month; voice allowance used; the limit; the day's rate; Maps and YouTube counters; web searches; tokens by part (counts only) | No | Months kept; the ledger 90 days |
| Voice and brain | `voice_settings`, `settings`, `local_brain` | Voice choices and words to recognise; the No-AI switch; the laptop brain's address and key | `local_brain`: token key | Until changed |
| Telegram | `telegram`, `telegram_users`, `telegram_pairing`, `telegram_pairing_tries`, `telegram_updates`, `telegram_alerts` | Pairing, reverse look-up, codes, update claims, alert counters | No | Updates 48 h, counters 3 days, codes 10 minutes |
| Alerts | `notify`, `notify_held`, `notify_rate`, `webpush` | Alert settings and VIPs; held alerts; storm counters; browser subscriptions | `notify` (VIPs), `webpush` | Held until quiet hours end; counters 3 days |
| Home | `home`, `home_link`, `home_claims`, `home_devices`, `home_arm`, `home_cameras`, `home_feed` | The home link, a pending code, event claims, devices, alarm state, camera settings, the home feed | `home`, `home_feed` (not the arm state) | Claims 48 h; feed 7 days |
| Faces and photos | `faces`, `face_groups`, `photo_imports` | Consented people; the laptop's unnamed group ids and counts; an import's progress (never a picture) | `faces` | Until removed |
| Self-health | `health_last`, `vitals_providers`, `vitals_status`, `vitals_index`, `selfwatch`, `selfwatch_errors`, `selfwatch_told` | The last systems check; what Vitals tracks (never a key's value); streaks, clocks, deploys; error counts by logger name | No | Errors 14 days; claims 30 days |
| Backups | `backup_canary`, `backup_status`, `backup_drill`, `backup_drills` | The canary (a sealed nonce); backup status; the drill's state and monthly results | `backup_canary`: `backup_probe` | Canary 30 days; results 13 months |
| Helpers (R11) | `helpers_nudge`, `helpers_gate`, `helpers_clock`, `bills`, `bills_told`, `birthdays_told`, `chores`, `maintenance`, `house_told`, `outside`, `nudges`, `wellbeing`, `kitchen`, `spend`, `spend_scan` | Nudge caps and send log; bills (never a card number); reminder claims (hashes only); chores and upkeep; the owner's place and warnings; wellbeing log; pantry and recipes; grocery spend | `bills`, `alerts_place` (`outside`), `wellbeing`, `kitchen`, `spend` | Claims 30–400 days; spend 13 months |
| Followed plans | `series`, `series_told` | Plans with calendar event ids and session states; check-in claims | No | Claims 60 days |
| Phone, watch, SOS, vision (R7) | `phone_link`, `phone_devices`, `watch_days`, `watch_state`, `sos`, `sos_join`, `sos_log`, `vision_results` | A link code's hash; linked phones' public keys; steps, heart rate, sleep; emergency contacts; SOS log without coordinates; kept camera results (never a frame) | `watch` (days), `sos` (contacts), `vision` | Code 10 minutes; watch and SOS log 400 days; vision 90 days |
| Wardrobe (R13) | `wardrobe`, `wardrobe_log`, `wardrobe_photo`, `wardrobe_fp`, `wardrobe_restore`, `wardrobe_laundry`, `wardrobe_review`, `wardrobe_told`, `wardrobe_plans`, `wardrobe_cal`, `wardrobe_outlook` | The sealed index; each piece's append-only events; cleaned 512-px photos; fingerprints; laundry loads; review entries; outfit plans; the last calendar read (never a title); the weather outlook | `wardrobe`, `wardrobe_photos` | Closed loads 90 days; plans 90 days after the event |
| Try-on (R13.1) | `tryon`, `tryon_person`, `tryon_consent`, `tryon_picture`, `tryon_garment`, `tryon_spend` | Measurements and figure; the owner's one photo; his YES; Google's pictures; garment photos; the month's try-on ₹ | `tryon`, `tryon_photos` | Pictures 30 days unless kept; spend 13 months |
| Build Book (R6) | `book` (and chunks), `book_lease`, `book_lock`, `book_sessions`, `book_settings`, `book_tickets`, `book_notices`, `book_closed` | Sealed releases' books, the sealer's lease, the guest lock, sessions, tickets, content-free notices | `book_index`, `book_session`; tickets hashed | Books until removed (60 MB cap); sessions 45 minutes |
| Old Book writer trial (R6.3, no longer written) | `book_writer`, `book_write_lease`, `book_write_spend`, `book_drafts`, `book_trial`, `book_pages` | The removed runtime writer's records | `book_index` for the pages index | Until the owner deletes them (Privacy row "Book writer (old trial)") |

The guide's section 6.2 has the same rows in plain words with each collection's card.

**Redis** is used only for local Docker runs (`docker-compose.yml`): `jarvis:session:{id}` with a
24-hour idle expiry and a per-user index (`src/jarvis/memory/redis_store.py`).

## 3. Encryption, keys and sealing

| Layer of protection | As built | Evidence |
|---|---|---|
| In transit | HTTPS everywhere; the bridge's calls also HMAC-signed both ways with a nonce; Web Push encrypted to each browser (RFC 8291) | `src/jarvis/home/signing.py`, `src/jarvis/webpush/` |
| At rest, by Google | Firestore and Secret Manager encrypt everything | Google's platform |
| At rest, by JARVIS | AES-256-GCM with a random nonce and a string AAD (`TokenCipher`) | `src/jarvis/integrations/vault.py:TokenCipher` |
| The root key | `jarvis-token-key`: 32 random bytes, made once by the deploy, never rotated so far | `deploy/cloudrun.sh` (`rand_key`) |
| Per-purpose keys | HKDF-SHA256 (salt `jarvis-keyring-v1`, info `jarvis/<purpose>/v1`): 26 cipher purposes (`PURPOSES`) and 1 secret purpose (`webpush_vapid`, raw output for the Web Push signing key); MACs use their own HKDF domain (`jarvis/mac/<purpose>/v1`) | `src/jarvis/keyring.py:Keyring` |
| Fail closed | An unknown purpose, a wrong key, a wrong AAD or a tampered blob raises `VaultError`; nothing logs a key, blob or plaintext; with no token key the vault, notes and things are off, never stored in clear | `src/jarvis/keyring.py` docstring, `Keyring.from_settings` |
| Key id for later rotation | Stored envelopes carry `KEY_ID = "tk1"` | `src/jarvis/keyring.py:KEY_ID` |

The 26 cipher purposes: `vault`, `vault_index`, `notes`, `belongings`, `tickets`, `home`,
`home_feed`, `faces`, `webpush`, `notify`, `connectors`, `book_index`, `book_session`, `bills`,
`spend`, `wellbeing`, `alerts_place`, `kitchen`, `watch`, `sos`, `vision`, `backup_probe`,
`wardrobe`, `wardrobe_photos`, `tryon`, `tryon_photos`.

**The vault in detail** (`src/jarvis/vault/crypto.py`, `src/jarvis/vault/unlock.py`). A file is
cut into 512 KiB chunks; each chunk is sealed with the file's own random data key under an AAD
that names owner, item, file, position and count, so a moved, reordered or shortened chunk fails
to open. The data key is wrapped by the keyring's `vault` key; the index is one blob under
`vault_index`. Opening needs the owner's passkey (or a fresh Google sign-in before any passkey
exists: `src/jarvis/permissions/service.py:PermissionsService.check_purpose`), which opens an
unlock window; downloads use tickets of 32 random bytes shown once, stored only as an HMAC, bound
to one item and file, valid 60 seconds and removed when taken (at most 3 live grants and 5 live
tickets).

**Not sealed by JARVIS** (Google's encryption only): conversations, long-term memory facts,
attachment text, briefs, the audit, approvals, permissions and the cost counters. Anyone who can
open the Cloud project can read them (the guide, section 10).

## 4. Retention and deletion

- **Expiry** is done by JARVIS's own jobs on the morning tick (04:00–11:30 IST) and, for some,
  the 5-minute clock (`src/jarvis/ticks.py`, `src/jarvis/api/tick_wiring.py`). No Firestore TTL
  policy is used (`deploy/cloudrun.sh` step 4 comment).
- **Recently deleted.** The owner's own undo-able deletes (events, to-dos, notes, things,
  documents) keep a copy in `deleted_items` for 30 days (`src/jarvis/undo/`).
- **The Privacy panel** lists every category ("privacy rows") from every part, each able to
  export and delete where allowed (`src/jarvis/privacy/service.py:PrivacyService`,
  `src/jarvis/privacy/ports.py:PrivacySource`, `PrivacyRegistry`). An export or delete asks for
  the passkey, or a fresh sign-in before one exists (`check_purpose`). A row that is a record of
  the owner's own cap (try-on spend) or a once-only claim (self-health) is shown but not
  deletable, and says so.
- **Backups.** After a delete, the live data is gone at once (or after the 30-day bin) and the
  backup copies within 7 days; the Privacy panel's "Backups (Google's copies)" row says so.

## 5. Privacy rows and who sees what

What each outside service sees is in the guide's section 6.5 and Figure 14
(`../diagrams/14-privacy-map.png`); the brains' share is enforced by `src/jarvis/llm/brains.py`
and `src/jarvis/core/brain.py` (chapter 01, P1). In short: Anthropic sees the conversation window,
matching memory facts and the turn's tool results; a training brain (Gemini free) sees the
conversation only, never tools, memory, files or pictures; Tavily sees search words (a guard
refuses private ones) and the pages read; Google speech hears audio of a listening turn and the
text to speak; Telegram stores bot chats, which are not end-to-end encrypted.

## 6. Backups and the restore test

| Step | As built | Evidence |
|---|---|---|
| Set-up | Owner-run, with a cost line and a typed YES: daily backups kept 7 days, delete protection on, the drill's three grants | `deploy/backup_setup.sh` |
| Daily check | JARVIS reads Google's backup list and writes a canary (a sealed nonce under `backup_probe`, its hash, the key's fingerprint); "no newer backup" past 36 hours tells the owner | `src/jarvis/backup/canary.py`, `src/jarvis/config.py` `backup_max_age_h` |
| Monthly drill | On day 1 (`backup_drill_day`) the newest copy is restored into the throw-away database `jarvis-drill`, checked (the canary opens with today's key) and deleted; never started above ₹100 estimated (`backup_drill_max_inr`); the owner may start 2 more a month by a console-only card | `src/jarvis/backup/drill.py`, `drill_start.py`, `src/jarvis/core/guardrails.py:CONSOLE_ONLY_TOOLS` |
| Guard rails | JARVIS refuses to start with `JARVIS_FIRESTORE_DATABASE` set to `jarvis-drill`; the drill's delete grant is conditioned to that one database | `src/jarvis/config.py` (`DRILL_DB` check), `deploy/backup_setup.sh` |
| What the copies don't hold | The laptop's pictures and face library, Secret Manager (Google keeps its versions), the owner's Google account data | the guide, section 8 |
| What it proves | Recovery from a bad write or delete; not from losing the project or the key, which share one project | the guide, section 8 ("Restoring for real") |

## 7. What never leaves the device

| Data | Stays on | Why it can't leave | Evidence |
|---|---|---|---|
| Room audio before "Hey Jarvis" | the browser | The wake word runs on the device (openWakeWord on onnxruntime-web); nothing is sent until it is heard | C06; `src/jarvis/api/static/console-wakeword.js` |
| Camera frames in the console | the browser | The vision engine runs in the page; only results are kept; a picture leaves only when the owner presses Ask, Add to vault or Attach, through one door that redraws it (no camera or location data) | C63; `console-vision.js`, `console-r7-send.js` |
| Home camera recordings, the face library, face attempts (72 hours for unknown people, 7 days for enrolled people) and the face groups' embeddings and crops | the laptop | Matching runs in Frigate and the bridge; the cloud keeps names, consent and ids only | C08, C39, C61; `deploy/home/docker-compose.yml` |
| The phone's signing key | the phone's secure hardware | Generated there; only its public key is sent | C62 |
| Audio of a listening turn | not stored anywhere by JARVIS | Sent to Google's Speech-to-Text and discarded | C05 |
| A burglar-alert photo | memory only | Sent to Telegram once if the owner opted in; never stored, logged or audited | `src/jarvis/alerts.py` docstring |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 15:40 IST | R6.4 | First edition: where data lives; the 131 collections by area (126 from the coverage inventory plus 5 its patterns miss) with what is sealed and kept; keys and sealing (26 cipher purposes), the vault; what is not sealed; retention, deletion and privacy rows; backups and the drill; what never leaves a device | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): the five collections the inventory misses named with their lines; why fixing the inventory needs an app-code change too; the seven sub-collections added | 🛠 Mark XXV |
