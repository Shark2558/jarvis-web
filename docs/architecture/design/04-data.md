Version v6.6.1 · 28 Nov 2026 · Release R5.2 · Status: Current · Owner: 🛠 Mark XXV

# 04 · Data architecture

**In plain words.** Everything JARVIS keeps is in one Firestore database in your own Google Cloud
project, in Mumbai. Google encrypts all of it. On top of that, JARVIS locks ("seals") your most
private records with its own keys, so even someone reading the database sees only scrambled
bytes. Some things never reach the cloud at all: camera pictures and face pictures stay on your
laptop, and the "Hey Jarvis" listening and the phone camera's frames stay in your browser. You can
export or delete each kind of data from the Privacy panel; Google's daily backup copies (after
your one-time backup step) are gone within 7 days of a delete.

**Phone calls (R18, built, not yet deployed).** The number of the person JARVIS calls is always
sealed. Each call's recording, its transcript and its English summary are sealed the same way as
your vault's files and kept 30 days, unless you press Keep. If the person on the line asks not to
be recorded, JARVIS deletes what it had recorded of that call and keeps only notes for the
summary. Calls have four rows in the Privacy panel, under "Phone calls" (section 4).

**Your voice (R5.2, built, not yet deployed).** The recordings of your 20-minute voice session
stay on your laptop, locked with a key only the laptop's speech kit holds; the cloud never keeps
any audio. The cloud keeps your **voice profile**: how well each listening engine understood you,
which one was chosen, and the corrections it learned (words only, never numbers). Your **voice
print**, which lets a device tell your voice from others, is made and kept only in that device's
browser, locked, and is never sent anywhere. The wake-word files trained from your voice are kept
on the laptop, locked with their own key. Three new rows in the Privacy panel let you see and
delete each of these (section 8).

## 1. Where data lives

| Place | What is there | Who can read it | Evidence |
|---|---|---|---|
| Firestore `(default)`, asia-south1 | Everything JARVIS keeps (section 2) | `jarvis-run`; the project's owner in the Cloud console | `deploy/cloudrun.sh` step 4 |
| Secret Manager, same project | API keys, the session secret, the API token, the root token key | `jarvis-run`, one grant per secret | `deploy/cloudrun.sh` step 5 |
| Cloud Logging, same project | JSON logs with a trace id; the audit chain's `(seq, hash)` anchor; never a secret, a message's text or audio | the project's owner | `src/jarvis/logging.py`, `src/jarvis/storage/audit.py` |
| Firestore backups (after the owner's step) | A daily copy of the whole database, kept 7 days | Google, the project's owner, the drill | `deploy/backup_setup.sh` |
| The owner's laptop | Camera recordings and events, the face library, face attempts, the face groups' SQLite file, Home Assistant's own data; from R18 the call desk's folder (its id and link seed, the microphone roles it changed, a log without sound, words, numbers or keys); from R5.2 the speech kit's folder (its key, the voice session's recordings and what the laptop engines heard, encrypted; the pinned model files; the wake word's trained files, sealed) and, in the call desk's folder, a copy of the kit's key | the owner; only the bridge's signed door and the kit's keyed gate are reachable from outside (the call desk opens its own socket out, nothing reaches it) | `deploy/home/docker-compose.yml` (volumes); the guide's C77 and C79; `src/jarvis/localspeech/kitconfig.py` |
| JARVIS's memory, one instance (R18) | A call in progress, the dial grants, the live socket's tickets, the phone's command outbox and its signing key; from R5.2 the kit's last health and which engine heard and spoke last | the running server only; gone at a restart (so no old approval can dial) | `src/jarvis/calls/approvals.py:GrantBook`, `src/jarvis/api/calls_routes.py:LiveTickets`, `src/jarvis/phone/calls.py:PhoneCalls`, `src/jarvis/voice/laptop.py:LaptopVoice` |
| The owner's browser | Wake-word detection, camera frames, the share tray (Cache Storage `jarvis-share-v1`, each item at most 24 hours), the camera-off switch, small conveniences (open conversation, look, sound devices); from R5.2 the voice print (IndexedDB `jarvis-voiceprint`, encrypted), its on/off switch, and the owned wake-word files in the tab's memory only | the owner | C06, C62, C63, C82, C83 in the guide |
| The phone | The phone's P-256 key in secure hardware; the SOS numbers sealed for the offline SMS screen; from R18, in the app's private preferences (never backed up), the cloud's public command key, the call machine's one line (a caller's number only while the phone rings) and the commands acted on, until they expire | the owner | C62, C65, C78 |
| The owner's Google account | Calendar, Gmail, Tasks, Contacts, Drive, Photos, as always | Google and the owner; JARVIS through his link | C29 |

## 2. Firestore collections

**How many.** `scripts/arch_inventory.py` finds **136** collection names in the code (re-run on
R5.2's code, 27 Nov 2026; 126 before R18, whose 8 are `calls`, `call_settings`, `call_lang_check`,
`call_check_sentences`, `call_lines`, `call_line_audio`, `call_desk` and `call_desk_codes`; R5.2
added 2, `voice_profile` and `voice_session`).
A wider search found **5 more** that its patterns miss: `wardrobe_outlook`, `wardrobe_plans` and
`wardrobe_cal`, named through a helper (`src/jarvis/wardrobe/styling/part.py:_sealed`, lines 50,
53 and 54; also `src/jarvis/wardrobe/kept.py:PLANS_SINGLES`), and `bills_told` and
`birthdays_told`, named in a tuple assignment (`src/jarvis/helpers/today/part.py`, line 36; also
`src/jarvis/helpers/kinds.py`). So the code names **141** top-level collections, and the table
below lists all 141 (the 131 checked name by name against the inventory on 27 Nov 2026, R18's 8
and R5.2's 2 read from the inventory's own list). The coverage
check passes all the same, because the guide happens to name all five. Teaching the inventory both
idioms is not a docs-only change: the Build Book's fact pack uses the same patterns
(`src/jarvis/buildbook/gen/facts_code.py:COLLECTION`) and `tests/test_r63_a_facts_real.py` holds
the two counts equal, so both must change together (chapter 12, section 4; follow-up F2).
Every name carries the prefix `jarvis_` (`src/jarvis/config.py` `firestore_prefix`).

**Sub-collections.** Thirteen more names live under a parent document, listed for the restore
drill in `src/jarvis/backup/walk_checks.py:KNOWN_SUBCOLLECTIONS` (pinned against the code by a
test): `turns` (under `sessions`), `vault_chunks` (under `vault`), `chunks` and `pictures` (under
`attachments`), `book_chunks` (under `book`), `items` (under `deleted_items`) and `days` (under
`activity_days`, and from R18 under `calls` too); R18 added `cards`, `records`, `numbers`,
`months`, `sealed` and `sealed_chunks` (all under `calls`; the review found the drill's count
came out short without them). The Activity log's own days are `activity/{uid}/d{YYYYMMDD}`.

"Sealed" names the keyring purpose that encrypts the content (section 3); "token key" means the
root key directly (these predate the keyring). "Kept" is how long JARVIS keeps it; JARVIS's own
morning sweeps delete what expires, because Firestore TTL policies are billed and not used.

| Area | Collections | What they hold | Sealed | Kept |
|---|---|---|---|---|
| Conversations | `sessions` (turns under each), `meta` | Conversations; the audit head; a health ping | No | Until deleted |
| Approvals and audit | `approvals`, `audit` | Waiting cards (10-minute expiry); the hash-chained audit (tool, risk, outcome, arguments' hash, short detail; never the arguments) | No; from R18's review a waiting call card's number to call and a booking's number to give: `calls` (`src/jarvis/calls/pending.py:CallNumberSeal`) | Until decided; audit always (append-only) |
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
| Voice and brain | `voice_settings`, `settings`, `local_brain` | Voice choices and words to recognise (from R5.2 also the new words the voice session found); the No-AI switch; the laptop brain's address and key | `local_brain`: token key | Until changed |
| Your voice (R5.2) | `voice_profile`, `voice_session` | The profile: each listening engine's word error and command accuracy on his voice, the chosen engine, the corrections and their switch, the session's state, the number of clips recorded and the Google seconds the comparison used. The session in progress: its prompts (his own words among them), which are recorded, what the browser and Google heard for the held-out lines (at most 400 characters each) and the comparison's ₹ answer (his YES, the ₹ shown). Never audio, never a voice print | No | The profile until the Privacy delete or a new session; the session until "Delete my recordings" (`src/jarvis/voice/profile_store.py:DocProfileStore`, `src/jarvis/voice/session_store.py:DocSessionStore`) |
| Telegram | `telegram`, `telegram_users`, `telegram_pairing`, `telegram_pairing_tries`, `telegram_updates`, `telegram_alerts` | Pairing, reverse look-up, codes, update claims, alert counters | No | Updates 48 h, counters 3 days, codes 10 minutes |
| Alerts | `notify`, `notify_held`, `notify_rate`, `webpush` | Alert settings and VIPs; held alerts; storm counters; browser subscriptions | `notify` (VIPs), `webpush` | Held until quiet hours end; counters 3 days |
| Home | `home`, `home_link`, `home_claims`, `home_devices`, `home_arm`, `home_cameras`, `home_feed` | The home link, a pending code, event claims, devices, alarm state, camera settings, the home feed | `home`, `home_feed` (not the arm state) | Claims 48 h; feed 7 days |
| Faces and photos | `faces`, `face_groups`, `photo_imports` | Consented people; the laptop's unnamed group ids and counts; an import's progress (never a picture) | `faces` | Until removed |
| Self-health | `health_last`, `vitals_providers`, `vitals_status`, `vitals_index`, `selfwatch`, `selfwatch_errors`, `selfwatch_told` | The last systems check; what Vitals tracks (never a key's value); streaks, clocks, deploys; error counts by logger name | No | Errors 14 days; claims 30 days |
| Backups | `backup_canary`, `backup_status`, `backup_drill`, `backup_drills` | The canary (a sealed nonce); backup status; the drill's state and monthly results | `backup_canary`: `backup_probe` | Canary 30 days; results 13 months |
| Helpers (R11) | `helpers_nudge`, `helpers_gate`, `helpers_clock`, `bills`, `bills_told`, `birthdays_told`, `chores`, `maintenance`, `house_told`, `outside`, `nudges`, `wellbeing`, `kitchen`, `spend`, `spend_scan` | Nudge caps and send log; bills (never a card number); reminder claims (hashes only); chores and upkeep; the owner's place and warnings; wellbeing log; pantry and recipes; grocery spend | `bills`, `alerts_place` (`outside`), `wellbeing`, `kitchen`, `spend` | Claims 30–400 days; spend 13 months |
| Followed plans | `series`, `series_told` | Plans with calendar event ids and session states; check-in claims | No | Claims 60 days |
| Phone, watch, SOS, vision (R7) | `phone_link`, `phone_devices`, `watch_days`, `watch_state`, `sos`, `sos_join`, `sos_log`, `vision_results` | A link code's hash; linked phones' public keys; steps, heart rate, sleep; emergency contacts; SOS log without coordinates; kept camera results (never a frame) | `watch` (days), `sos` (contacts), `vision` | Code 10 minutes; watch and SOS log 400 days; vision 90 days |
| Wardrobe (R13) | `wardrobe`, `wardrobe_log`, `wardrobe_photo`, `wardrobe_fp`, `wardrobe_restore`, `wardrobe_laundry`, `wardrobe_review`, `wardrobe_told`, `wardrobe_plans`, `wardrobe_cal`, `wardrobe_outlook` | The sealed index; each piece's append-only events; cleaned 512-px photos; fingerprints; laundry loads; review entries; outfit plans; the last calendar read (never a title); the weather outlook | `wardrobe`, `wardrobe_photos` | Closed loads 90 days; plans 90 days after their day (`src/jarvis/wardrobe/styling/plans.py:KEEP_DAYS`, `StylingDoc.pruned`), at most 250 (`MAX_PLANS`), of which at most 100 made by the calendar (`MAX_CAL_PLANS`) and 20 of those from today on (`MAX_CAL_AHEAD`); a new plan's day is 14 days back to 30 ahead (`BACK_DAYS`, `AHEAD_DAYS`). The owner decided this on 27 Nov 2026, as R13 planned; the code has matched since R18's review (commit `2041978`; chapter 12, section 4) |
| Try-on (R13.1) | `tryon`, `tryon_person`, `tryon_consent`, `tryon_picture`, `tryon_garment`, `tryon_spend` | Measurements and figure; the owner's one photo; his YES; Google's pictures; garment photos; the month's try-on ₹ | `tryon`, `tryon_photos` | Pictures 30 days unless kept; spend 13 months |
| Build Book (R6) | `book` (and chunks), `book_lease`, `book_lock`, `book_sessions`, `book_settings`, `book_tickets`, `book_notices`, `book_closed` | Sealed releases' books, the sealer's lease, the guest lock, sessions, tickets, content-free notices | `book_index`, `book_session`; tickets hashed | Books until removed (60 MB cap); sessions 45 minutes |
| Old Book writer trial (R6.3, no longer written) | `book_writer`, `book_write_lease`, `book_write_spend`, `book_drafts`, `book_trial`, `book_pages` | The removed runtime writer's records | `book_index` for the pages index | Until the owner deletes them (Privacy row "Book writer (old trial)") |
| Calls (R18) | `calls` (under each owner: `cards`, `records`, `sealed`, `sealed_chunks`, `days`, `months`, `numbers`), `call_settings`, `call_lang_check`, `call_check_sentences`, `call_lines`, `call_line_audio`, `call_desk`, `call_desk_codes` | Call cards; one record a call (state, languages, times, ₹ by part, references to its sealed parts, a booking's event id); the call's audio, transcript and summary; the day's counters (IST) and the month's calls ₹; numbers called before, by a keyed reference; the owner's call settings; the language check's latest result per language and option (no audio, no transcript) and its 10 translated sentences; the pre-made lines' cache (nothing writes it in v18.0.0); the linked call desk; a pending link code | The other person's number: `calls` (cipher) plus a 128-bit HMAC reference (`calls` MAC domain); the audio, transcript and summary: a per-file key wrapped by `vault`, 512 KiB chunks; the desk's seed: `calls`; the link code as a SHA-256. A card's other fields (purpose, what JARVIS may say and agree to, the contact's name, a booking's name and number to give), the record's other fields, the settings and the check's results: not sealed | Records and their sealed parts 30 days unless kept (the `calls_retention` morning job; a setting of 1–30); a link code works 10 minutes and is removed when used or the desk is unlinked; cards and numbers called before until the Privacy delete (nothing else removes a card); the counters always (they hold no number); the rest until changed or deleted |

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
| Per-purpose keys | HKDF-SHA256 (salt `jarvis-keyring-v1`, info `jarvis/<purpose>/v1`): 27 cipher purposes (`PURPOSES`; R18 added `calls`) and 1 secret purpose (`webpush_vapid`, raw output for the Web Push signing key); MACs use their own HKDF domain (`jarvis/mac/<purpose>/v1`) | `src/jarvis/keyring.py:Keyring` |
| Fail closed | An unknown purpose, a wrong key, a wrong AAD or a tampered blob raises `VaultError`; nothing logs a key, blob or plaintext; with no token key the vault, notes and things are off, never stored in clear | `src/jarvis/keyring.py` docstring, `Keyring.from_settings` |
| Key id for later rotation | Stored envelopes carry `KEY_ID = "tk1"` | `src/jarvis/keyring.py:KEY_ID` |

The 27 cipher purposes: `vault`, `vault_index`, `notes`, `belongings`, `tickets`, `home`,
`home_feed`, `faces`, `webpush`, `notify`, `connectors`, `book_index`, `book_session`, `bills`,
`spend`, `wellbeing`, `alerts_place`, `kitchen`, `watch`, `sos`, `vision`, `backup_probe`,
`wardrobe`, `wardrobe_photos`, `tryon`, `tryon_photos`, `calls` (R18: the other person's number,
its keyed reference, the call desk's seed and, since the review, a waiting call card's numbers in
`approvals`). The phone's call commands are signed with a P-256
key made at each start and kept in memory, so R18 added no secret purpose
(`docs/plans/r18-integration/I1-NOTES.md`, decision 7).

**A call's records** (`src/jarvis/calls/records.py:SealedBlobs`) use the vault's envelope
encryption: a random data key per part, AES-256-GCM in 512 KiB chunks, the key wrapped by the
`vault` key, every AAD naming the owner, the call and the kind, so a chunk moved to another call
fails to open. A delete removes the header (and with it the wrapped key) first. The audio is
8 kHz mono WAV (`src/jarvis/calls/join.py:RECORD_RATE`), about 0.96 MB a minute, capped at 16 MiB
(about 17 minutes; `src/jarvis/calls/records.py:MAX_AUDIO_BYTES`).

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
attachment text, briefs, the audit, approvals (apart from a waiting call card's numbers, below),
permissions and the cost counters. Anyone who can open the Cloud project can read them (the
guide, section 10). From R18 also: a call card's purpose, its lines, the contact's name and a
booking's name and number to give; a call record's times, languages and ₹; the call settings (the
owner's first name among them); the language check's results. Chapter 12, section 6 lists them
(G12). From R5.2 also the voice profile (his corrections are words he says) and, while a session
is kept, what the browser and Google heard for its held-out lines.

**A waiting call card in `approvals`** (R18). The gateway keeps a waiting `calls_place` card's
arguments, which are what runs on approval, in `approvals` until it is decided or tidied after its
10 minutes. This edition first found the other person's full number in clear there; the combined
review now seals it (`docs/plans/r18-integration/REVIEW.md`, item 12). The store takes a seal
(`src/jarvis/storage/approvals.py:DocApprovalStore.use_seal`, an `ArgumentSeal`): sealed on the
way in, opened on the way out, and a card that does not open is unreadable, never a guess.
`src/jarvis/calls/pending.py:CallNumberSeal` seals the number to call and a booking's number to
give under the `calls` key, bound to the approval id and the field, so a sealed number moved to
another card or field does not open; `src/jarvis/api/r18_wiring.py:finish_r18` puts it on the
gateway's store (`seal_pending_calls`). The card's other arguments (purpose, lines, the contact's
name, a booking's name) stay in clear for those 10 minutes; the console shows the numbers masked
(chapter 05, section 8). Test: `tests/test_r18_review_approval_seal.py`.

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
- **Calls (R18).** A call's record, audio, transcript and summary are kept 30 days unless the
  owner presses Keep; the `calls_retention` job on the morning tick deletes the rest, also when he
  lowers the setting (`src/jarvis/calls/retention.py:CallRetentionJob`). He can delete one call in
  Calls. **On objection** (the other person asks not to be recorded) JARVIS stops the recording,
  deletes the audio and the transcript kept so far and keeps only the summary's notes
  (`src/jarvis/calls/records.py:RecordKeeper.objected`). The opening line says the call is
  recorded (`src/jarvis/calls/models.py:OPENING_LINE`).
- **The calls' Privacy rows (R18 review),** in a "Phone calls" section
  (`src/jarvis/calls/privacy.py:calls_privacy_sources`): *calls* (records with their sealed parts,
  cards, numbers called before; export gives each call's time, length, languages, ₹, summary and
  transcript, the number masked and no audio; delete needs the passkey, and the day and month
  counters stay because they keep the limits and hold no number), *call settings* (delete puts the
  defaults back), *the call desk link* (delete is Unlink, with any unused code) and *the language
  check's results* (delete: no Indian language is offered until the check runs again).

## 5. Privacy rows and who sees what

What each outside service sees is in the guide's section 6.5 and Figure 14
(`../diagrams/14-privacy-map.png`); the brains' share is enforced by `src/jarvis/llm/brains.py`
and `src/jarvis/core/brain.py` (chapter 01, P1). In short: Anthropic sees the conversation window,
matching memory facts and the turn's tool results; a training brain (Gemini free) sees the
conversation only, never tools, memory, files or pictures; Tavily sees search words (a guard
refuses private ones) and the pages read; Google speech hears audio of a listening turn and the
text to speak; Telegram stores bot chats, which are not end-to-end encrypted.

**On a call (R18)** other people's data leaves JARVIS too: the speech option chosen for the
call's language (Google, Azure's free tier, Bhashini or, only with the owner's YES, Sarvam) hears
the other person's speech while they talk and the text JARVIS speaks; the in-call brain, never one
that may train on prompts, sees the call's transcript window and the card
(`src/jarvis/calls/brain.py:pick_call_brain`); a free Gemini tier is never used for calls. The
language check sends published test clips (FLEURS from Hugging Face), not anyone's call. The
reasoning under India's data law is in chapter 05, section 8.

## 6. Backups and the restore test

| Step | As built | Evidence |
|---|---|---|
| Set-up | Owner-run, with a cost line and a typed YES: daily backups kept 7 days, delete protection on, the drill's three grants | `deploy/backup_setup.sh` |
| Daily check | JARVIS reads Google's backup list and writes a canary (a sealed nonce under `backup_probe`, its hash, the key's fingerprint); "no newer backup" past 36 hours tells the owner | `src/jarvis/backup/canary.py`, `src/jarvis/config.py` `backup_max_age_h` |
| Monthly drill | On day 1 (`backup_drill_day`) the newest copy is restored into the throw-away database `jarvis-drill`, checked (the canary opens with today's key) and deleted; never started above ₹100 estimated (`backup_drill_max_inr`); the owner may start 2 more a month by a console-only card | `src/jarvis/backup/drill.py`, `drill_start.py`, `src/jarvis/core/guardrails.py:CONSOLE_ONLY_TOOLS` |
| Guard rails | JARVIS refuses to start with `JARVIS_FIRESTORE_DATABASE` set to `jarvis-drill`; the drill's delete grant is conditioned to that one database | `src/jarvis/config.py` (`DRILL_DB` check), `deploy/backup_setup.sh` |
| What the copies don't hold | The laptop's pictures and face library, Secret Manager (Google keeps its versions), the owner's Google account data | the guide, section 8 |
| Calls (R18) | The copies hold the calls' collections like any other, sealed parts still sealed; the drill counts the six call sub-collections, without which its count came out short once a call was kept | `src/jarvis/backup/walk_checks.py:KNOWN_SUBCOLLECTIONS` |
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
| A call's sound while the other person is silent (R18) | the laptop | The call desk's voice detector sends sound only while they speak | `src/jarvis/calldesk/vad.py` |
| The call desk's link seed (R18) | the laptop and the cloud (sealed) | Shown once at linking; the cloud keeps it sealed with `calls` and never shows it again | `src/jarvis/calls/hub.py:DeskStore` |

## 8. Your voice (R5.2)

Built in R5.2 (`v5.2.0`), not yet deployed. Plan: `docs/plans/r5-2-voice.md`, sections 3.3–3.5
and D4. The rule is the plan's: no audio, recording or voice print is ever kept in the cloud.

| Data | Where | Protection | Kept | Evidence |
|---|---|---|---|---|
| The voice session's recordings (WAV clips) and what the laptop engines heard | the speech kit's folder on the laptop only; each clip passes through the cloud in memory on its way there and is not kept | AES-256-GCM, a fresh 96-bit nonce per file, the session and prompt bound in as associated data (a file moved to another name doesn't open), under a 32-byte key in `clips.secret` that only the owner's account can read and the cloud never has | at most 400 clips a session and 12 sessions; until "Delete my recordings", which also replaces the key | `src/jarvis/localspeech/clips.py` (`MAX_CLIPS_PER_SESSION`, `MAX_SESSIONS`) |
| The wake word's trained files (stage 1's verifier, stage 2's model) | the kit's folder, under `wakeword/` | sealed with AES-256-GCM under their own key, `wakeword.secret`, so the recordings' delete can leave them | until he deletes them (their Privacy row); deleting them deletes the recordings too | `src/jarvis/localspeech/wakejoin.py`, `src/jarvis/localspeech/wakeword/store.py` |
| The same files in the console | the browser tab's memory, after each SHA-256 matches the one the kit announced | never stored by the browser; no audio, score or feature leaves the tab | until the tab closes | `src/jarvis/api/static/console-wakeword-own.js` |
| The voice print | the browser of each device where he enrolled, never uploaded | AES-GCM with a key the browser makes and cannot export, both in this origin's IndexedDB (`jarvis-voiceprint`); the page shows no score and no number of the print | until he forgets it or clears the site's data | `src/jarvis/api/static/console-voiceprint.js` |
| The voice profile and the session in progress | Firestore, `voice_profile` and `voice_session` (section 2) | Google's encryption; not sealed by JARVIS (section 3) | as in section 2 | `src/jarvis/voice/profile_store.py`, `src/jarvis/voice/session_store.py` |
| The kit's key | the kit's folder (`key`), the secret `jarvis-local-speech-key`, and, for the call desk, `local-speech.key` in the desk's folder or its environment | readable by the owner's account only on the laptop; Secret Manager in the cloud; never in the kit zip or the repository | until he makes a new one | `deploy/local-speech/start-kit.ps1`, `src/jarvis/calldesk/config.py:speech_key` |

**The Privacy panel's voice rows** (`src/jarvis/voice/session_privacy.py`, after R13's rows and
R18's "Phone calls"; wired by `src/jarvis/api/r52_wiring.py:r52_privacy_sources`):

- *Your voice profile* (`voice_profile`): look and export give the ranking, the chosen engine and
  the corrections; delete puts listening back to the usual order.
- *Voice session recordings* (`voice_recordings`): the clips on the laptop and the comparison's
  transcripts here; export gives the profile's fields and the transcripts, never audio; delete is
  "Delete my recordings".
- *Wake-word files from your voice* (`voice_wakeword_files`): the trained files on the laptop;
  deleting them deletes the recordings too.

A laptop that can't be reached makes a row say "Couldn't check right now", and a delete fails
rather than claim something is gone that isn't. With no kit set up at all (its address or key
taken off the server), "Delete my recordings" still deletes the comparison's transcripts here (the
`voice_session` document) and clears the profile's session, the owner's decision of 28 Nov 2026
(R5.2 review, row 18): the laptop's recordings are out of reach, so none is claimed gone (0
deleted), the profile keeps their count and the dashboard reports them as left, and the answer
says they stay until the kit is set up again
(`src/jarvis/voice/session.py:VoiceSessions.delete_recordings`, `475b208`;
`tests/test_r52_review_delete_here.py`). Export and delete ask for the passkey like every
row (section 4). The voice print is not a row: it never leaves the browser, and Voice → Speaker
check forgets it on that device after a confirm.

**What crosses to Google.** Only the session's comparison: Google, with his words, hears the 80
held-out lines once, inside the free minutes or after his typed YES (chapter 06, section 7), and
keeps nothing for JARVIS. The browser's own listening is used for the comparison only if he
chooses it, and the screen says that in Chrome that audio goes to the browser's maker.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 15:40 IST | R6.4 | First edition: where data lives; the 131 collections by area (126 from the coverage inventory plus 5 its patterns miss) with what is sealed and kept; keys and sealing (26 cipher purposes), the vault; what is not sealed; retention, deletion and privacy rows; backups and the drill; what never leaves a device | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): the five collections the inventory misses named with their lines; why fixing the inventory needs an app-code change too; the seven sub-collections added; outfit plans are kept 14 days after their day, not 90 | 🛠 Mark XXV |
| v6.4.3 | 27 Nov 2026 | R6.4 | Outfit plans: the owner's decision (90 days after their day) recorded; the code change is pending | 🛠 Mark XXV |
| v6.5.0 | 27 Nov 2026, 19:50 IST | R18 | R18 "Calls from your laptop": the calls' data in plain words; where it lives (the desk's folder, the server's memory, the phone app); 134 + 5 = 139 collections with the Calls row (what is sealed, what is not, how long each is kept); 13 sub-collections; the `calls` key (27 cipher purposes) and how a call's records are sealed (8 kHz WAV, 16 MiB cap); what is not sealed, a waiting call card's number in `approvals` among it; 30-day retention, deletion on objection and the four Privacy rows; who hears a call; backups and the drill; two more things that stay on the laptop | 🛠 Mark XXV |
| v6.5.1 | 27 Nov 2026, 21:25 IST | R18 | The R18 review's later fixes: a waiting call card's numbers are sealed in `approvals` (`src/jarvis/calls/pending.py:CallNumberSeal`), in the collections table, the `calls` purpose and a new paragraph, its other arguments still in clear; the Wardrobe row as built: plans kept 90 days after their day, at most 250, the calendar's cap 20 ahead and 100 kept | 🛠 Mark XXV |
| v6.6.0 | 27 Nov 2026, 22:06 IST | R5.2 | R5.2 "Your voice": the voice data in plain words; where it lives (the kit's folder on the laptop, the server's memory, the browser's voice print and wake-word files); 136 + 5 = 141 collections with the "Your voice" row (`voice_profile`, `voice_session`, not sealed, never audio); the voice profile and session transcripts added to what is not sealed; new section 8: the recordings on the laptop only (AES-256-GCM, `clips.secret`, 400 clips and 12 sessions), the wake word's sealed files, the voice print in the browser only, the kit's key, the three Privacy voice rows, and what reaches Google | 🛠 Mark XXV |
| v6.6.1 | 28 Nov 2026 | R5.2 | The owner's decision of 28 Nov 2026 (R5.2 review, row 18): with no kit set up, "Delete my recordings" deletes the comparison's transcripts here and claims none of the laptop's recordings gone | 🛠 Mark XXV |
