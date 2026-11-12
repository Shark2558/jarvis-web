Version v11.1.3 · 12 Nov 2026, 17:23 IST · Release R11.1 · Status: Current · Owner: 🛠 Mark XV

# Release R11.1 — Your observations, fixed (`v11.1.0`)

**Phase:** fixes across Phase 1 (voice), Phase 2 (tools, files), Phase 4 (follow-ups) and Phase 5 (home
kit). **Type:** free: no new paid service, no new secret, no new Cloud Scheduler job; any AI use is metered
in ₹ against the monthly limit. **Branches:** I0 `r11-1-i0` (from `origin/r11-i1` @ `cc7576a`, R11) →
parts `r11-1-a` … `r11-1-d` → integration `r11-1-i1` → one PR `v11.1.0 · R11.1 Your observations, fixed ·
Mark XV`. Every commit carries `JARVIS-Version: v11.1.0` and `JARVIS-Mark: XV`. Read on `r11-i1` @ `cc7576a`.

## Goal (plain words)

On 12 Nov 2026 you tried JARVIS for real work and it let you down twelve times. This release fixes each one.
JARVIS stops answering "I have nothing to add, Sir." and either does the job or says plainly what stopped
it. A study plan of 60 sessions goes into your calendar from ONE approval, with one Undo, and JARVIS asks
after each session whether it happened and moves the rest when you skip one. It shows what it heard and what
it understood. It reads Excel, PowerPoint, pictures, zip files and folders. Google Photos works, up to 2,000
photos at a time, and your home laptop groups faces from a photo folder so you name each person once. The
People panel shows profile cards that actually open. Vitals says which part is broken. The brief counts all
your unread mail.

One request is declined and stays declined: JARVIS does not identify a person from a picture, and the check
that limits people research to public figures and work contacts stays exactly as it is (D17).

## What you reported, and the root cause found in the code

Every row was checked against the code on `cc7576a`. "Correction" marks where the first reading of the cause
was wrong or incomplete.

| # | What you saw | Root cause (file:line on `cc7576a`) | Part |
|---|---|---|---|
| O1 | "I have nothing to add, Sir." again and again when asked to put a 60-session plan (a CSV) in the calendar; 8–18 s a reply; sometimes "1 tool call" | `core/brain.py:371` `reply = completion.text.strip() or "I have nothing to add, Sir."` never looks at `Completion.stop_reason` (`llm/base.py:159`; the providers fill it: `anthropic_provider.py:232`). `config.py:118` `max_output_tokens = 1024` is used for every call (`brain.py:473`, `:759`): sixty tool calls do not fit in 1,024 tokens, so the answer is cut off with no words. The filler is stored as a normal assistant turn (`brain.py:372–385`), so the next turn's window contains it and the model repeats it. **Also found:** after 6 tool rounds the last call is made with no tools (`brain.py:535–538`) and an empty answer there becomes the same filler; the streaming path (`brain.py:776`) stores an empty reply with no words at all. | A |
| O2 | Only 1 of 60 events was created | `tools/google_calendar.py:556–575` `calendar_create_event` makes one event a call. **Correction — three limits stack, not two:** `config.py:183` `tool_max_rounds = 6`; `tools/budget.py:33` `MAX_NEW_CARDS = 5` (at most 5 new approval cards a message; the 6th is refused with "Too many approvals"); and a round that has read an attached file is "tainted", so every write in it becomes its own card (the gateway's rule; the flag is set at `brain.py:549`), spoken or typed. Sixty events can never get through. | A |
| O3 | The microphone mishears ("D csb file", "Tu D calender") | **Correction:** the language is already `en-IN` everywhere: `config.py:360` (`voice_language`), the cloud engine (`voice/google_cloud.py:233`, `voice/service.py:470`) and the browser engine (`console-voice-loop-browser.js:26` `rec.lang = V.language()`, default `'en-IN'` at `console-voice.js:140`, `:615`). What is missing: (a) hints are only the fixed base list plus the words you typed into "Words to recognise" (`voice/service.py:232`, `:277`; `console-voice-phrases.js`), never the names of the files you just attached or the nouns of the conversation; (b) one alternative only (`maxAlternatives: 1`, `google_cloud.py:236`; `loop-browser.js:26`); (c) the recognised text goes to the Brain raw (`ChatRequest.message`), with no correction step and nothing on screen showing what was heard. | B |
| O4 | Excel cannot be attached | `console.html:168` `accept=".pdf,.docx,.txt,.md,.markdown,.csv"`, `console-attach.js:13–14` (`MAX_FILES = 3`, `EXTENSIONS`), `documents/limits.py:12–19` (`Kind`, `EXTENSIONS`), `:29–30` (10 MB, 3 files). **Also found:** `jarvis.llm` had no picture input at all (`llm/base.py:71` `ContentBlock = TextBlock | ToolCall | ToolResultBlock`), and billing has no estimate before a reply (`billing/service.py` only admits and records; `llm/pricing.py:65` `estimate_usage` is used after the fact). | B |
| O5 | Google Photos: "That Google service is not switched on for your JARVIS project yet." | `deploy/cloudrun.sh:82–98` enables Calendar, Gmail, Tasks, speech, Drive and People, never `photospicker.googleapis.com`; the message is the generic `integrations/google.py:216` `SERVICE_OFF_MSG`, raised at `:425`, and names no service. | C |
| O6 | Only 20 photos at a time | `photos/picker.py:48` `MAX_PICKED = 20` (sent as `maxItemCount`, `:144`); `photos/service.py` `collect` takes them in the request itself, inside one time budget. Google's Picker allows 2,000 (its reference: "Values above 2000 will be coerced to 2000", read 12 Nov 2026). | C |
| O7 | Photos → faces is a dead end | `deploy/home/README.txt:93` "Kit to-do for R4 Photos (not built yet…)". The cloud allows `POST /bridge/v1/faces/photos` and `/faces/enrol` (`home/ports.py:82–83`, `photos/edge.py:29–30`) but the bridge serves only `GET /bridge/v1/faces/summary` (`homebridge/faces.py:355`): 404, so "laptop not reachable". The bridge's faces plugin drives Frigate's face library by id (`homebridge/faces.py:1–20`); nothing on the laptop can look at a still photo or group unknown faces. | C |
| O8 | "Open all profiles" does nothing | `console-people.js:106` `window.open(p.url, '_blank', 'noopener,noreferrer')`: with `noopener` the call returns `null` by specification, so `opened` is always 0 and the panel always says "Your browser blocked some tabs"; and a browser allows one new tab per click anyway. | D |
| O9 | "Remove the public-figure check and tell me who is in a picture" | Declined (D17). The check is `people/gate.py`; it is not touched. There is no picture research of any kind today. | D |
| O10 | Vitals: "Home laptop link reports a problem" while the laptop is on | `home/heartbeat.py:69` sets `degraded` when `parts.frigate is False or parts.mqtt is False`; `vitals/own.py:361–363` then says only "reports a problem". The parts that failed are stored but never named. | D |
| O11 | GitHub token: "Unknown — hasn't been used yet" | `vitals/own.py:339–340`. **Correction:** connecting already reads `/user` and stores what GitHub's headers said (`integrations/github.py:241–247`). The row is unknown when there is no stored record: a token connected before R5.1 added the record, or a record that could not be saved, after a restart emptied the in-memory copy (`github.py:255–261`). Nothing ever fetches it again until some tool happens to read GitHub. | D |
| O12 | The brief says there is no unread mail | `brief/collect.py:54` `INBOX_QUERY = "is:unread in:inbox category:primary newer_than:1d"` and `tools/gmail_digest.py:37` `QUERY = "is:unread in:inbox category:primary newer_than:3d"`: only the Primary tab, only the last day (or three). Mail that Gmail files under Updates, Promotions, Social or Forums, and anything older, is invisible. | A |

## The fixes: skill, layer, phase, part

| # | Fix | Core skill | Layers | Phase | Part | Brain? |
|---|---|---|---|---|---|---|
| O1 | A reply is never a filler; cut-off and empty answers are handled | (core loop) | L4 | 0 | A | the reply itself |
| O2 | One card for many events; one Undo | Task & Productivity | L5, L6 gateway card | 2 | A | no extra call |
| O2b | A series followed up: "did it happen?", re-planning a skipped session | Task & Productivity | L5, L3 helpers clock, L8 | 4 | A | no |
| O12 | The whole inbox, counted and grouped | Communication | L6 Gmail, L5 brief | 2/4 | A | no |
| O3 | "Heard / understood as", per-turn hints | Communication | L2 input processing | 1 | B | fast tier, only when unsure |
| O4 | Excel, PowerPoint, pictures, zip, folders; ₹ estimate first | Research & Intel | L2, L6 documents | 2 | B | the reply itself |
| O5 | Photos service switched on by the deploy script; the message names it | (infrastructure) | L6 | 2 | C | no |
| O6 | 2,000 photos, in the background, resumable | Automation Engine | L6, L3 | 2 | C | no |
| O7 | The laptop reads photos; a watched folder; name a face group once | Security Advisor (home) | L6 home bridge | 5 | C | no |
| O8 | Profile cards, one tab a click | Research & Intel | L1 console | 2 | D | no |
| O9 | Research a picture of a thing, place, label or logo; never a person | Research & Intel | L4 vision input, L5 | 2 | D | the reply itself |
| O10, O11 | Vitals rows that name the fault and read the token by themselves | Security Advisor | L5 Vitals | 2 | D | no |

## Decisions (binding)

**D0 · Never change the look** (R5.1 D1 stands). Every new piece of screen reuses the existing tokens and
components (`.btn`, `.btn.lift`, `.btn.primary`, `.k`, `.kv`, `.rhead`, `.integ`, `.bnote`, `.bfine`, the
approval card, the attach chip, the People panel's rows). No new colours, fonts, radii or shadows; text
through `textContent` only; 44 px targets; Night and Day at 1440×900 and 390×844; contrast ≥ 4.5:1. Each
part's stylesheet (`console-r111-<part>.css`, ≤ 150 lines) only places things. `tests/browser/test_ui_audit.py`
keeps passing, and each part adds its own browser test with `tests/browser/ui_checks.py`.

**D1 · A working turn may write a longer answer (O1).** `work_output_tokens` (default 8,192; 1,024–64,000)
is the output cap for any model call of a turn that has tools on or carries attachments; a plain chat
reply, a voice reply's narration and a training brain keep `max_output_tokens` (1,024).
`core.finish.output_cap(s, working=...)` is the one place that decides. Cost: the cap is a ceiling, not a
spend: you pay for what is written (see Cost).

**D2 · An empty or cut-off answer is handled, never papered over (O1).** After the tool loop,
`core.finish` decides from `(text, stop_reason, tool_calls, rounds)`:
1. words → the reply, as today;
2. no words and `stop_reason` is `max_tokens`/`length` (`finish.cut_short`) → one retry of that call
   (`empty_reply_retries`, default 1) with the higher cap and a short fixed instruction ("Answer in words
   now. If the work needs many tool calls, use the batch tool or say what remains."), admitted and metered
   like any call;
3. still nothing → a fixed, honest line chosen from what happened, never from the model:
   cut off → "My answer was cut off before I could finish, Sir. Ask me for a smaller piece, or raise the
   answer length in Settings."; cards waiting → "I've prepared N approval(s) for you, Sir."; tools ran →
   "I did N step(s) but the AI gave me no words to report them. Activity shows what ran."; otherwise →
   "The AI returned an empty answer, Sir. Please ask again; if it repeats, switch brain in the top bar."
The round-limit summary call and the streaming path use the same function.

**D3 · A filler is never history.** The fixed lines of D2.3 are returned to you but stored with
`Turn.tool_derived`-style marking **and left out of the model's window** (`core/window.py`), so no later
turn can imitate them. Stored turns that are exactly the old filler string are dropped from the window too
(your existing conversations recover without a migration). The persona gains no "nothing to add" wording.

**D4 · One card for many events (O2).** New tool `calendar_create_events` (`tools/calendar_batch.py`):
`{events: [{summary, start, end, description?, location?, reminders_minutes?}] (1–100,
`calendar_batch_max`), title_prefix?, series?: {name}}`. No attendees: an event with guests stays the
single-event tool and its R3 card. It is R2 with `ask_when` always, so it is **always one approval card**,
typed or spoken, tainted round or not, and costs one of the message's five cards. The card's summary says
how many, the first and last date and the prefix; the console lists every event (title, date, start–end) in
a scrolling list built from the card's own arguments (`console-r111-plan.js`), and "Approve" is the existing
button. Telegram shows the count and the range and says "open JARVIS to see the list". Nothing is created
before the approval; confirm-before-commit is unchanged. The tool's description tells the model: "more than
three events → this tool, never many single calls".

**D5 · A batch runs once, reports each item and has one Undo.** Approved, the events are created five at a
time, each stamped with a private marker (`extendedProperties.private.jarvisBatch = <batch id>:<n>`); a
retry first lists by that marker, so nothing is created twice. The result is per item (`created`, or the
plain reason), and the reply says "58 created, 2 failed" with a "Retry the 2" button (the same card path).
`calendar_undo_events {batch}` (R2) deletes the batch's events that you have not changed since, through the
existing undo-able delete (each goes to Recently deleted, 30 days); the reply carries one "Undo all" button
(a reply card, `tools/reply_cards.py` kind `batch`). Events created from an attached file's words are
marked as outside-written exactly as single events are today (`mark_outside`); the series record (D6) is
JARVIS's own trusted list.

**D6 · A series is followed up, and no session is ever dropped (O2b).** With `series` given, the batch is
remembered in `series/{uid}` (≤ 10 series, ≤ 200 sessions each: event id, title ≤ 80, start, end, state
`planned | done | skipped | moved`). Titles are "<prefix> - <topic>" ("CCA - <topic>") when you give a
prefix. A job on the helpers' 5-minute clock (`series_checkin`) asks once per session, 15 minutes after it
ends: "Session 7 of 60 in your CCA plan was at 19:00. Did it happen, Sir? Say 'session done' or 'session
skipped'." (a fixed template: number, plan name, time; alert kind `series_checkin`: rings by day, **held**
in quiet hours, never dropped). You answer by voice, in chat, on Telegram or with the two buttons on the
card; No-AI phrases work (`BrainMode.add_phrases`). "Done" marks it. "Skipped" builds a re-plan: the skipped
session and every later one move to the next free slot of the plan's own rhythm (the same weekdays and time,
skipping any slot where your calendar is busy), so the plan ends later and **the number of sessions is the
same before and after** (checked in code; a re-plan that would lose one is refused). The re-plan is ONE
approval card listing every "old date → new date"; nothing moves until you approve. Unanswered sessions are
asked again in the morning brief's Helpers lines ("2 study sessions have no check-in"), never nagged.

**D7 · Permissions for A.** `calendar_create_events` and `calendar_undo_events` fall under "Add and change
your events" (`calendar_*`); `series_*` under a new row "Calendar plans — Follow a study plan or other
series of sessions" (R2, default Allow; moving sessions is still a card); `gmail_inbox_summary` under
"Search and read email". 44 → 46 rows with D17's.

**D8 · "Heard / understood as" (O3).** A spoken message goes through one step before the Brain,
`POST /v1/input/understand {heard, alternatives?, files?, session_id?}` → `{understood, changed, sure,
question?}`:
1. **Fixed rules first, free:** known mishearings of common words in Indian English speech-to-text
   ("csb/csv/c s v file", "D" → "the", "tu/too" → "to", "calender" → "calendar", "jarvis" variants), then
   fuzzy matching of each heard word run against the hint list (below) with a conservative threshold; a
   change is made only when exactly one candidate fits.
2. **Only when the rules are unsure** (a low recogniser confidence, or a word run that matches nothing and
   sits where a noun is expected) **and the AI is on:** one fast-tier call with the heard text, the
   alternatives and the hint list, fenced as data, answering strict JSON; admitted and metered (about ₹0.01).
   In No-AI mode, or past the monthly limit, this step is skipped.
3. Still unsure → one short question ("Did you mean the file study-plan.csv, Sir?") instead of acting.
The chat shows the row as "Heard: … / Understood as: …" whenever something changed (`Turn.heard`,
`ChatRequest.heard`: display only, never sent to a model, never learned from). The Brain receives the
understood text, still on `channel: voice`, so every spoken-turn safeguard (cards for writes) is unchanged.
`voice_understand` (default on) switches the step off.

**D9 · Per-turn hints.** The hint list for a spoken turn = the names of the files waiting on the composer
and attached in this conversation (stems and extensions: "study plan", "CSV"), the last few distinctive
nouns of the conversation (deterministic: capitalised or repeated words, no model), then your own "Words to
recognise"; at most `voice_hint_words` (40) on top of the base list, inside Google's phrase limits. They go
to the cloud engine as speech contexts and to the browser engine where it supports biasing; both engines are
asked for three alternatives. The recognition language stays the `voice_language` setting (already
`en-IN`). File names are your own data and go only to your own Google speech project, as the phrase list
does today; nothing is logged.

**D10 · Pictures are a message block that only a seeing, private brain receives (O4, O9).**
`jarvis.llm.base.ImageBlock` (JPEG or PNG, ≤ 4 MB) is a *message* block, not a stored one: a picture is never
written into a conversation. `BrainSpec.sees_pictures` is true only for a provider that reads pictures
(`vision = True`: Claude today) that does not train on content; every other brain gets one fixed line
("a picture was attached; this brain was not shown it") through `without_pictures`. The browser shrinks a
picture before upload (longest side ≤ 1,568 px, JPEG, which also removes camera and location data); the
server checks the JPEG's structure again with the existing `photos.imaging.sanitise_jpeg`, refuses anything
over `attach_picture_max_kb` (900), and keeps it with the attached documents (deleted with them). At most 4
pictures go with a turn, only with the turn they were attached to.

**D11 · More kinds of files, the same isolation (O4).** `.xlsx`/`.xlsm` (openpyxl, read-only, values not
formulas: each sheet as rows of text, capped), `.xls` (xlrd), `.pptx` (slide text and notes from the XML
with the lxml already in the image), `.png`/`.jpg`/`.jpeg` (D10), `.zip` (members read one by one, at most
`attach_zip_max_files`, never a nested archive, never a path outside, total uncompressed size capped, each
member then treated as its own kind) and a folder (`webkitdirectory`: the browser sends its supported files,
at most `attach_folder_max_files`). All parsing stays in the killable child process
(`documents/isolation.py`) with its CPU, memory and time caps; a file that breaks a cap is refused in plain
words, never half-read. Limits: `attach_max_files` 10 a message (was 3), 10 MB a file, `attach_total_mb` 40
together. The `accept` list and the tooltip are set by `console-attach.js` from its own list, so the page
itself does not change.

**D12 · The stronger tier and a rupee estimate, before the paid reply.** When the files of a message are
large or complex (more than 40,000 characters in all, a workbook with more than 3 sheets or 2,000 rows, more
than 2 pictures), the console asks `POST /v1/input/estimate` first and shows, above Send, "About ₹N on
<tier>; ₹M on the stronger tier" with the tier it suggests; you choose, then send. The estimate is
characters ÷ 4 for input plus the output cap's typical use, at `llm/pricing.py` prices and the day's rate,
always shown with "about". Below ₹5 nothing is shown. A skill still asks for a tier, never a model.

**D13 · Google Photos is switched on by the deploy script and says so (O5).** `deploy/cloudrun.sh` enables
`photospicker.googleapis.com` in its optional block (a failure warns, like Drive's); the Photos path
raises "Google Photos Picker is not switched on for your JARVIS project yet: re-run deploy/cloudrun.sh."
instead of the generic sentence.

**D14 · 2,000 photos, in the background (O6).** `photos_max_picked` (2,000) replaces the constant. An
import is a job: `photo_imports/{uid}` holds the session id, counts and the item ids still to do; the
helpers' clock takes `photos_import_batch` (10) at a time (download, strip metadata as today, send to the
laptop, drop), so a restart or a sleeping laptop resumes where it stopped; the panel shows "312 of 2,000
read · 41 faces found · paused: laptop not reachable". Google's download links expire: an import that
outlives them asks Google for the list again, and one that outlives the Picker session says "pick again to
continue" and keeps what was done. Per-photo EXIF stripping is unchanged.

**D15 · The laptop looks at photos; a watched folder; name a group once (O7).** On the home bridge:
- `POST /bridge/v1/faces/photos` and `POST /bridge/v1/faces/enrol` as the R4 contract says, and
  `GET /bridge/v1/faces/groups` (unnamed groups: id, count, first and last seen; ids only).
- A face engine inside the bridge for still pictures: OpenCV's YuNet detector and SFace recogniser
  (`opencv-python-headless`, models bundled in the kit; hash-locked; licences to be read by Part C before
  bundling, see "Not verified"). Embeddings and crops stay in the bridge's data folder; decoder safety as
  the README lists (JPEG only, ≤ 2048 px, pixel cap).
- A **watched folder** (a folder on the laptop mounted read-only into the bridge, `PHOTOS_DIR` in
  `bridge.env`; off until you set it): new pictures are scanned a few a minute; a face that matches a named
  person is counted; unknown faces are grouped (≥ 3 pictures make a group worth naming).
- **Naming a group** happens in the console's Faces panel ("Unnamed groups: Group 4 · 23 photos") and runs
  the existing `FacesService.add` consent check **once per person** (a guardian's yes for a child); only
  then is the bridge told `enrol`. The bridge then copies that group's best face crops into Frigate's face
  library under the person's id, so the camera recognises them too, with no further step. Later photos and
  sightings of that person need nothing more.
- To see **who** a group is, you open the bridge's own page on the laptop, which shows the crops; the cloud
  console shows ids and counts only. Photos, crops and embeddings never leave the laptop.
- Alert kind `faces_to_name` (feed only): "3 new groups of faces to name".
Not possible and not built: reading your whole Google Photos library, or Google's own face groups (Google's
API gives an app only what you pick).

**D16 · Profile cards (O8).** The People panel lists each profile as a card (platform, title, the summary
line already in the dossier; no page is framed: most sites refuse it) with its own "Open in browser" link
(`<a target="_blank" rel="noopener noreferrer">`, one tab per click, never blocked) and an "Open next"
button that opens the next unopened profile and marks it. "Open all" is removed.

**D17 · Research a picture, never a person (O9; declined part).** The R4 check in `people/gate.py` stays
exactly as it is and no face-to-identity search is built. Built instead: `picture_research` (R1; new row
"Pictures — Research a picture you attach") for a picture attached to the turn: the Brain's vision input
describes it, reads any text, label or logo, and may use web search for the product, place or landmark. If
the picture shows a person, JARVIS describes only what is visible (clothing, setting, objects), says once
"I don't identify people from pictures, Sir", and never searches with a description of the person. Enforced
three ways: a persona rule (`core/prompts.py`, new persona version), a deterministic guard on the tool (a
first vision call answers strict JSON `{has_person, subjects}`; with `has_person` no web search runs for a
person-shaped query and the reply template is fixed), and an eval with a negative control. A named public
figure typed by you still goes through the People panel and its gate, unchanged.

**D18 · Vitals names the fault (O10).** The home row reads the stored parts: "Camera watcher (Frigate) is
not answering" / "The camera's messenger (MQTT) is not connected, so burglar alerts can't arrive", each with
its fix steps (`start-home.ps1`, the container to restart) on the row and in the systems check's spoken
line. Fixed words from a map keyed by the part; never a device name.

**D19 · The GitHub token is read when its facts are missing (O11).** When a connected token has no stored
record, the Vitals refresh makes one `GET /rate_limit` (GitHub does not count it against the limit), at most
once every 6 hours per owner, stores the headers' facts, and shows "Checking…" rather than "hasn't been
used". A refused token shows as refused.

**D20 · The whole inbox (O12).** Unread count from the INBOX label's `messagesUnread` (one call, exact).
The brief and `gmail_inbox_summary` read at most `mail_summary_max_reads` (30) unread messages of the last 7
days across every inbox category and group them by Gmail's own category labels: People (Primary), Bills and
orders (Updates with a fixed sender-class check), Updates, Promotions (count only). One-time codes and bank
messages are withheld exactly as today (`gmail_digest.withheld`, `mask_for_speech`); the background read for
the brief goes through `tools/background.py` and obeys the "Search and read email" row.

**D21 · Orchestrator's additions (Mark XV, 12 Nov 2026, binding on the part named).**
- **A · Undo of a batch is not a new way round the card.** When the *model* asks for `calendar_undo_events`
  it is a card like any other write (it removes up to 100 events). Only your own press of "Undo all" on the
  reply card runs it without a second card, through the gateway, in exactly the way today's reply-card and
  Activity "Undo" presses do (`tools/reply_cards.py`, `undo/`): follow that path, add no new bypass.
- **B · "Understood as" never rewrites the things that matter most.** Neither the fixed rules nor the fast
  tier may change a number, an amount, a date, a time, a person's name, a phone number or an e-mail address.
  If the only possible correction touches one of those, the step asks its one question instead (D8.3).
- **C · Unnamed face groups do not live for ever.** On the laptop an unnamed group (its crops and
  embeddings), and any unknown face seen in fewer than 3 pictures, is forgotten after
  `FACE_GROUPS_KEEP_DAYS` (a `bridge.env` setting, default 90) unless you name it; the pictures in your
  folder are never touched, so a later scan can group them again. Each group has "Forget this group". The
  Privacy panel gets a "Face groups" row (count; delete all) through the part's `privacy` source, and a
  delete is only reported done when the laptop has confirmed it (if the laptop is off it stays pending and
  is retried, as R3's face delete does). The R3 rule for strangers at the camera (72 hours) is unchanged.
- **D · A name can come from words in the picture, never from a face.** If a picture carries a name as
  visible text (a caption, a name board, a jersey, a book cover), JARVIS may say "The caption names X" and
  offer to look X up; that look-up is the existing people research with its unchanged check
  (`people/gate.py`), so a public figure passes and a private person is refused exactly as when you type the
  name. No name, guess or "looks like" is ever produced from a face, for anyone, public or private, you and
  your family included. The eval covers both: a captioned picture of a made-up public figure (offer made,
  the gate decides) and an uncaptioned face (no name, no person search).
- **D, as built after the integrated reviews (I1, v11.1.4 of the I1 notes).** The main brain's own
  outward words on a picture turn (`web_search`, `youtube_search`, `maps_search` and `maps_route`,
  `research_person`'s context) pass `picture.turnguard` in one of two modes. **Strict** whenever the
  picture MAY show a person (the look said so; nobody researched this message's picture; it carried
  two; it could not be read; anything failed): a query may carry only words he typed in that
  message, words the picture shows (its read text and vetted things) and free words (small, search
  and generic thing words, never part of a name), in any script, inside a link or joined with `_`,
  and in every query of the turn on its own; else one fixed sentence says he can type the name or
  ask without the picture. **Light** only when picture research of that message's only picture saw
  nobody (its report carries the message's key): the name shapes above, with a mark-aware tokeniser,
  a link's parts tested on their own, and no "one word is a topic" escape beside a person word.
  The rise in over-caution on person pictures is accepted (30 of 35 ordinary queries wait for his
  words there; 5 of 35 on a picture known to show nobody, as before).

## Needs the owner (safe defaults until answered; none blocks the build)

| # | Question | Default built |
|---|---|---|
| 1 | Longer answers cost more when used. Keep the working cap at 8,192 tokens (at most about ₹8 an answer on the balanced tier), or lower? | 8,192 |
| 2 | When you skip a session, move *every* later session one slot (the plan ends later), or put only the skipped one at the end? | Move every later one |
| 3 | May the "did it happen?" question reach Telegram and your phone, or the console only? | Everywhere your alerts go; held at night |
| 4 | "Understood as" uses the fast AI tier only when the fixed rules are unsure (about ₹0.01). Allow, or fixed rules only? | Allow |
| 5 | Old `.xls` files need one more small open-source library (xlrd, BSD). Add it, or ask you to save as `.xlsx`? | Add it |
| 6 | The estimate appears above ₹5 a reply. A different threshold? | ₹5 |
| 7 | Which folder on the laptop is the watched photo folder? | Off until you set `PHOTOS_DIR` |
| 8 | To see who a face group is, you look at the laptop's own page. Allow a small face crop to pass through the cloud to your console instead (shown, never stored)? | No: ids and counts only |
| 9 | Children in the photo folder: group them (naming still needs the guardian's yes), or never group faces that look like children? | Group; naming needs the guardian's yes |
| 10 | Unnamed face groups are forgotten on the laptop after 90 days unless you name them. A different period? | 90 days |

## Part split (four builders; worktrees; branches `r11-1-a` … `r11-1-d` from `r11-1-i0`; disjoint files)

A file appears under one part only. Everything not listed is I0's or I1's (see the brief).

| Part | Owns |
|---|---|
| **A · Brain and calendar** (O1, O2, O2b, O12) | `core/brain.py`, `core/finish.py`, `core/window.py`, `core/rounds.py`; new `tools/calendar_batch.py`; `tools/google_calendar.py`, `tools/calendar_cards.py`, `tools/reply_cards.py`; `src/jarvis/series/`; `api/fix_plan.py`; `brief/collect.py`, `brief/render.py`, `tools/gmail_digest.py`; console `console-r111-plan.js`/`.css`, `console-approvals.js`, `console-approve-all.js`, `console-media.js`, `console-brief-sections.js`; `evals/r11_1/plan.py`; tests `tests/test_r11_1_a_*.py`, `tests/r11_1_fakes_a.py`, and the existing tests of the files above |
| **B · Voice and files** (O3, O4) | `src/jarvis/understand/`; `voice/*`, `api/voice.py`; `documents/*` (incl. `pictures.py`), `api/documents.py`; `api/fix_files.py`; console `console-r111-files.js`/`.css`, `console-attach.js`/`.css`, `console.js`, every `console-voice*.js`; `evals/r11_1/files.py`; tests `tests/test_r11_1_b_*.py`, `tests/r11_1_fakes_b.py`, `tests/fixtures/r11_1/b_*`, existing `test_documents_*`, `test_voice_*` |
| **C · Photos, faces and the home kit** (O5, O6, O7) | `photos/*`, `faces/*`, `src/jarvis/facegroups/`; `homebridge/*`, `home/ports.py`, `home/client.py`; `integrations/google.py` (the message only), `integrations/google_errors.py`; `deploy/cloudrun.sh`, `deploy/home/*`; `api/fix_photos.py`, `api/faces.py`; console `console-r111-photos.js`/`.css`, `console-faces.js`, `console-connectors.js`; `evals/r11_1/photos.py`; tests `tests/test_r11_1_c_*.py`, `tests/r11_1_fakes_c.py`, existing `test_photos_*`, `test_homebridge_*`, `test_deploy_*` |
| **D · People, pictures and Vitals** (O8, O9, O10, O11) | `src/jarvis/picture/`; `core/prompts.py`, `core/persona.py`; `people/*` **except `people/gate.py`, which nobody edits**; `vitals/*`, `home/heartbeat.py`, `home/store.py`; `integrations/github.py`, `github_meta.py`; `api/fix_look.py`; console `console-r111-look.js`/`.css`, `console-people.js`/`.css`, `console-vitals.js`, `console-systems*.js`; `evals/r11_1/look.py`; tests `tests/test_r11_1_d_*.py`, `tests/r11_1_fakes_d.py`, existing `test_people_*` (never weakening `test_people_gate_eval.py`), `test_vitals_*`, `test_r51b_*` |

Cross-part needs, settled by I0 so nobody waits: D's picture research gets its pictures from
`documents.pictures.turn_pictures` (B fills it; D tests against a fake); A's persona wishes go to D's
`core/prompts.py` through `INTEGRATION-A.md` for I1; D reads the heartbeat's `frigate`/`mqtt` parts, which C
may add to but not rename.

## The I0 seams (branch `r11-1-i0`; tests green: `tests/test_r11_1_seams.py`)

1. `jarvis.__version__` = `11.1.0` (as R11's I0 did; `tests/test_about.py`).
2. `config.py`: `work_output_tokens`, `empty_reply_retries`, `calendar_batch_max`, `series_enabled`,
   `voice_understand`, `voice_hint_words`, `attach_max_files`, `attach_folder_max_files`,
   `attach_zip_max_files`, `attach_total_mb`, `attach_picture_max_kb`, `photos_max_picked`,
   `photos_import_batch`, `picture_research_enabled`, `mail_summary_max_reads` (ranges pinned).
3. Alert kinds `series_checkin` (important, a daytime ring, held at night) and `faces_to_name` (info):
   `alerts.py`, `notify/ports.py`, `notify/policy.py`, `notify/held.py`, `console-alerts.js`,
   `buildbook/plain.py`; pinned counts 36 → 38.
4. Permission rows `plans` (`series_*`, R2) and `pictures` (`picture_*`, R1) before Maps; pinned 44 → 46
   (`RISK_OF`, `TOOL_OF`, the permissions eval's samples).
5. No new keyring purpose: nothing new is sealed (a series holds calendar titles you already keep in
   Google; imports and face groups hold ids). The pinned set is unchanged.
6. `jarvis.llm`: `ImageBlock`, `MessageBlock`, `PICTURE_TYPES`, `without_pictures`; Claude's provider sends
   a picture as base64 and declares `vision = True`; `BrainSpec.sees_pictures`. Gemini and the
   OpenAI-compatible provider ignore a picture block (they are never given one).
7. `core/finish.py` (`reply_text`, `cut_short`, `output_cap`, `log_turn`, `FILLER`): the Brain calls it;
   behaviour unchanged until Part A. `brain.py` 779 → 765 lines.
8. `documents/pictures.py`: `with_pictures` (called by the Brain on both paths) and `turn_pictures`.
9. `ChatRequest.heard` and `Turn.heard` (voice turns only; display only).
10. `jarvis.fixes.ports` (`FixPart`, `FixContext`, `PARTS`, `TOOL_FAMILIES`, `ROUTE_PREFIX`,
    `COLLECTIONS`), `api/r11_1_wiring.py` (parts built before the R11 helpers so their jobs ride the
    helpers' clock; a part that breaks its contract is left out), stub parts `series`, `understand`,
    `facegroups`, `picture`, stub routes `api/fix_{plan,files,photos,look}.py`; slots in `api/app.py`
    (721 → 725), `tools/setup.py` (`r111=`), `api/r11_wiring.py`, `api/personal.py`.
11. Console: `console.html` 798 → 795 lines (the four confirm dialogs' two empty lines joined, nothing
    removed; one new line loads `console-r111.js`, which loads the four part modules and stylesheets
    itself, as the Helpers panel does); `APP_ASSETS`.
12. Guide: card C61 (PLANNED), edition v11.1.1. Evals: `evals/r11_1/run.py` with four stub parts.
13. `docs/plans/r11-1-integration/BRIEF-COMMON.md`.

## What I1 wires (after the four parts are merged)

- New Python dependencies, hash-locked: `openpyxl`, `xlrd` (cloud image: `pyproject.toml`,
  `requirements.lock`, `requirements.licences.json`); `opencv-python-headless`, `numpy` and the two model
  files (home bridge only: `deploy/home/bridge-requirements.txt`, checksums in the kit).
- The persona line(s) Part A asks for, into Part D's `core/prompts.py`; one persona version for the release.
- `evals/r11_1/run.py` into `evals/run_all_mock.py`; the guide's card C61 as built, C05/C07/C13/C21/C37/C39/
  C55 lines; the build log, release plan and go-live guide; `README`.
- Any setting, alert kind, permission row or `console.html` line a part asked for in its `INTEGRATION-*.md`.
- The whole suite on 3.11 and 3.12, ruff, mypy, the browser suite and the visual gate; the integrated
  reviews (code, python, security for A, B, C; silent-failure for A).

## Tests and evals per part (mock; each control must make its suite fail)

| Part | Must prove | Negative control |
|---|---|---|
| A | (O1) a 60-row CSV plus "add these to my calendar" ends in ONE approval card or a real answer, on the mock brain scripted to answer empty, cut off (`max_tokens`) and with 60 single calls; the filler string never appears in a reply or in a stored turn; a retry happens at most once and is metered; a window never contains a filler turn. (O2) 60 events → one card listing 60, one approval, 60 creates, a failed create reported by item, a retry creates nothing twice, one Undo removes 60 and leaves a changed event alone; an event with a guest is refused by the batch. (O2b) "skipped" on session 7 of 60 moves 54 sessions, the count stays 60, busy slots are avoided, nothing moves before approval; the check-in is sent once, held at night, and works in No-AI mode. (O12) unread in Updates and Promotions is counted; the count equals the label's; a one-time code is withheld; "Never" on the mail row means no read. | the old `or FILLER` line restored; the batch split into single calls; the re-plan dropping the last session; the Primary-only query |
| B | (O3) a fixture set of real mishearings ("D csb file", "Tu D calender", …) is corrected by the rules with no model call; an unsure case makes exactly one fast-tier call with the AI on and none in No-AI mode; an unresolvable case asks one question; `heard` is stored and never reaches a model's window. (O4) each new kind is read inside its caps; a zip bomb, a nested zip, a path-escaping member, a 300-sheet workbook and an oversized picture are refused in plain words and the child process is killed on time; a picture reaches only a seeing, non-training brain and is never stored in a turn; the estimate appears above ₹5 and never below. | the rules table emptied; the zip caps removed; `sees_pictures` forced true for the training brain |
| C | (O5) the script enables the Photos service (shellcheck; `test_deploy_*`). (O6) 2,000 picked items import in steps of 10, resume after a restart and after "laptop off", strip metadata each, and stop cleanly when the session expires. (O7) the bridge's three routes answer ids only; an unknown face seen in 3 pictures becomes a group; naming a group runs the consent check once and a child needs a guardian's yes; without a yes nothing is enrolled; afterwards a new photo of that person is recognised with no further step; no picture, crop or embedding ever appears in a cloud request, log or document (a needle test). | consent check skipped; a crop added to the reply; the import done in one request |
| D | (O8) every profile has its own link; "Open next" opens exactly one; no `window.open` with `noopener` is counted. (O9) a picture of a product, a landmark, a label and a logo is researched with sources; a picture of a person is described without any name and with the fixed sentence, and no web search runs for the person; a typed name still meets the unchanged gate (`test_people_gate_eval.py` untouched and green). (O10) each failing part gives its own row text and fix steps. (O11) a connected token with no record triggers exactly one `/rate_limit` read in 6 hours and then shows its limits. | the person guard removed (the eval must then catch a name); the fault map emptied |

## Acceptance checks

1. The owner's own case, replayed on the mock and then live: the 60-session CSV, by voice with the same
   mishearings → "Heard / Understood as" → one card listing 60 "CCA - …" events → Approve → 60 in the
   calendar → Undo removes them.
2. No reply anywhere is "I have nothing to add, Sir."; a forced empty answer gives the plain sentence.
3. A skipped session re-plans with the same number of sessions.
4. An `.xlsx`, a `.pptx`, a photo, a zip and a folder attach and are read; a costly one shows its estimate.
5. Google Photos opens after re-running the deploy script; 200 picked photos import in the background.
6. With the laptop on: a watched folder produces groups; naming one makes the next photo recognised.
7. People: each profile opens from its own card. A picture of a landmark is researched; a picture of a
   person is not identified.
8. Vitals names the failing part; the GitHub row shows limits without any other GitHub use.
9. The brief's unread count matches Gmail's.
10. Works, or says honestly why not, in No-AI mode; the visual gate passes; `make eval-mock` passes.

## Cost (₹; no new paid service, secret or Scheduler job)

At the prices in `llm/pricing.py` (balanced tier: ₹0.19 per 1,000 input tokens, ₹0.95 per 1,000 output
tokens; fast tier: ₹0.01 and ₹0.05) and the fallback rate of ₹95.24 a dollar:

| What | Cost | When |
|---|---|---|
| A longer working answer | at most about ₹7.8 (8,192 output tokens, balanced); a 60-event batch is about ₹2.6 of output | only for what is actually written |
| The one retry of an empty answer | about ₹2.3 at most (the same window read again) | only when an answer came back empty |
| "Understood as" | ₹0 by the fixed rules; about ₹0.01 when the fast tier is asked | per spoken turn, only when unsure; ₹0 in No-AI mode |
| A picture | about ₹0.3 (about 1,500 input tokens, balanced) | per attached picture, per reply that includes it |
| A large file on the stronger tier | shown before you send (D12) | your choice each time |
| Calendar batch, series, inbox summary, Photos import, face groups, profile cards, Vitals rows | ₹0 | plain code, free Google quotas, your own laptop |
| Speech-to-Text | unchanged (three alternatives and hints cost nothing extra) | — |

Everything above counts against your monthly limit and is refused, in plain words, once the limit is reached.

## Risks

- **A longer cap invites longer bills.** The cap applies only to working turns; the estimate (D12) and the
  monthly limit bound it; owner decision 1.
- **A batch card is a big write on one tap.** The card lists every event; it is never approvable as part of
  "Approve all" silently (its own card); Undo exists; events with guests are excluded.
- **A file's words steer the batch** (prompt injection in a CSV). The round is tainted, so the batch is a
  card whatever your permission says, the list is on the card, and the events are marked outside-written.
- **"Understood as" changes your words.** It only changes with one clear candidate, always shows both
  lines, and asks when unsure; a write on a spoken turn is still a card.
- **Zip and Office files are hostile-input surfaces.** Same child process, caps and kill as PDF today; no
  nested archives; macros never run (values only).
- **Faces.** Grouping happens only on your laptop; the consent check stays the single door to a name;
  children need the guardian's yes; the engine's accuracy on your family's faces is unknown until tried
  (thresholds are settings on the laptop).
- **Picture research sliding into identifying people.** Three guards (D17) and an eval whose control must
  fail.
- **Bridge image size** grows by OpenCV (roughly 60–100 MB); CPU use while a folder is first scanned
  (rate-limited to a few pictures a minute).

## Not verified live (the sandbox reaches no Google, GitHub or home kit)

- Whether Claude's API returns a partly written `tool_use` block when it stops at `max_tokens`, and how the
  SDK presents it (D2 treats any `max_tokens` stop as cut off, whatever came back).
- Google Calendar's private extended-property search for the batch marker, and its per-minute write quota at
  five creates at a time.
- The Photos Picker's download-link and session lifetimes (the 2,000 limit itself was read in Google's
  reference on 12 Nov 2026), and whether enabling `photospicker.googleapis.com` needs anything beyond the
  API switch (for example a consent-screen scope review).
- Gmail's `labels.get` `messagesUnread` under the existing read-only scope, and the category labels' ids.
- The browser engine's support for three alternatives and for phrase biasing in your Chrome.
- OpenCV's YuNet and SFace model licences (expected MIT and Apache-2.0; Part C reads both files before
  bundling; if either is not permissive, the fallback is Frigate's own recognise endpoint for named people
  only, with no grouping), their accuracy and speed on the laptop, and Frigate's face-library endpoints
  (already unverified in R3).
- GitHub's `GET /rate_limit` not counting against the limit for fine-grained tokens.
- Folder upload (`webkitdirectory`) on your phone's browser.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.1.1 | 12 Nov 2026, 06:17 IST | R11.1 | First edition, with the I0 seams built: the twelve observations and their root causes checked against the code (corrections for O2, O3, O11), D0–D20, owner decisions with safe defaults, the A–D split with each part's files, the I0 seams, what I1 wires, tests and evals, acceptance, cost in ₹, risks and what is not verified live | 🛠 Mark XV |
| v11.1.2 | 12 Nov 2026, 06:35 IST | R11.1 | D21, the orchestrator's additions after reading the plan: the batch Undo adds no bypass (A); "Understood as" never rewrites numbers, dates, times, names or addresses (B); unnamed face groups expire after 90 days, can be forgotten and appear in Privacy (C); a name may come from words in a picture and then meets the unchanged people check, never from a face (D); owner question 10 | 🛠 Mark XV |
| v11.1.3 | 12 Nov 2026, 17:23 IST | R11.1 | D21-D as built after the integrated reviews: the turn guard's strict mode (a picture that may show a person: only his words, the picture's and free words go out) and light mode (a picture researched and seen without a person); YouTube, Maps and people research's context behind it | 🛠 Mark XV |
