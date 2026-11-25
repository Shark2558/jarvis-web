---
chapter: module_integrations
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
pages:
  "pg_module_integrations": "715099197d80e9fa"
  "pg_card_c04": "83314f69de55b394"
  "pg_card_c20": "f3c2b7750c25dcf6"
  "pg_card_c22": "48c312e679640db7"
  "pg_card_c29": "45f0468381e94e87"
  "pg_card_c30": "687920afcba57dfc"
  "pg_card_c31": "89b745850a9c49a5"
  "pg_card_c32": "711f620ae27cef70"
  "pg_card_c33": "4dcad2e6624f589d"
  "pg_card_c34": "4bd1adbd50ab4fc1"
  "pg_card_c35": "510bfae537fa2f78"
  "pg_card_c36": "2f31e3b0d7e8550b"
  "pg_card_c37": "4ddd90bb8812b0c8"
  "pg_screen_integrations": "38a09462ca7c3064"
  "pg_screen_media": "91a2f6aa9f6828f4"
  "pg_screen_connectors": "c7e8150fdec90f7e"
  "pg_service_github": "87389448a4cb0a9e"
  "pg_service_gmail": "056ab5bb1334c4e7"
  "pg_service_google_calendar": "d28c551743634fab"
  "pg_service_google_contacts": "9fde75c217d0ed69"
  "pg_service_google_drive": "3339a6cb01c35af3"
  "pg_service_google_maps_platform": "d818ebd37e0d1614"
  "pg_service_google_photos_picker": "821d9b1758efaa47"
  "pg_service_google_tasks": "326fe78dcede82c2"
  "pg_service_tavily": "202b2f7767e330ca"
  "pg_service_telegram": "784abaade6fa7af8"
  "pg_service_youtube_data_api": "eb72ed99358008f7"
---
- [page:pg_module_integrations] [show:title] This chapter is about how JARVIS reaches the services you already use: Google, Telegram, the web and more.
- [show:plain] Through Google, JARVIS reads your calendar and mail, manages your to-dos, looks up contacts, reads chosen Drive folders, and uses Maps and YouTube.
- Telegram is a second front door on your phone, and WhatsApp drafts are sent by you.
- [show:overview] Here is how a request reaches an outside service.
- [node:you] [edge:you>gateway] [node:gateway] You ask, in the console or on Telegram, and every request passes the same gateway and your rules.
- [edge:gateway>telegramoff] On Telegram, mail, Drive, documents and other private reads stay off, unless you switch them on there.
- [edge:gateway>link] [node:link] Google requests go through your linked account, the one door, which keeps your tokens sealed and refreshes them.
- [edge:link>reconnect] An expired or revoked link asks you to reconnect, and nothing else breaks.
- [edge:link>google] A live link reaches your calendar, Gmail and Tasks.
- [edge:gateway>key] [node:key] Places and videos use JARVIS's own server key for Maps and YouTube, which never reaches your browser.
- Both stop short of their free allowances.
- [edge:google>fence] [node:fence] What comes back, such as mail text, reaches the brain fenced as other people's words.
- [edge:fence>reply] Most requests end in an answer.
- [edge:fence>card] [node:card] A mail, though, goes only through a final card that shows every recipient.
- [show:example] In the made-up example, Neha links Google on a Sunday, then asks on Telegram for a reminder to call the bank.
- Her phone pops it up on time, and that evening her fingerprint confirms a card for a reply to her landlord.
- [show:costs] On JARVIS's side this costs nothing, and each chat turn costs the brain's usual tokens.
- [show:fails] A missing grant, such as Tasks or YouTube, gets a plain request to grant access.
- And at a free allowance's stop, JARVIS says the service is used up until it renews.
- [page:pg_card_c04] [show:title] The first part is Telegram, your second front door.
- [show:plain] Bot chats sit on Telegram's servers, not locked end to end, so your private reads stay off there until you switch them on.
- [count:{{fact:src/jarvis/telegram/pairing.py:CODE_LEN}}] Pairing uses a code of {{fact:src/jarvis/telegram/pairing.py:CODE_LEN}} characters, alive {{fact:src/jarvis/telegram/pairing.py:CODE_TTL_S}} seconds and void after {{fact:src/jarvis/telegram/pairing.py:MAX_TRIES}} wrong tries.
- [show:overview] Here is a message, from your phone to the reply.
- [node:tg] [edge:tg>secret] [count:{{fact:src/jarvis/api/telegram.py:WEBHOOK_BODY_BYTES}}] Telegram delivers it, and JARVIS answers only when the secret header matches and the message is at most {{fact:src/jarvis/api/telegram.py:WEBHOOK_BODY_BYTES}} bytes.
- [edge:secret>owner] [node:owner] [edge:owner>reject] A message that isn't from the paired owner, in a private chat, gets no reply, and is audited.
- [edge:owner>claim] [edge:claim>rules] Your message is claimed once, so a retry never runs twice, and without the privacy rules in place, no turn runs at all.
- [node:rules] [edge:rules>brain] [count:{{fact:src/jarvis/telegram/service.py:MAX_MESSAGES_PER_WINDOW}}] It becomes an ordinary brain turn, at most {{fact:src/jarvis/telegram/service.py:MAX_MESSAGES_PER_WINDOW}} messages in {{fact:src/jarvis/telegram/service.py:MESSAGE_WINDOW_S}} seconds.
- [edge:brain>reply] [count:{{fact:src/jarvis/telegram/format.py:LIMIT}}] The answer comes back as plain text, in pieces of up to {{fact:src/jarvis/telegram/format.py:LIMIT}} characters.
- [edge:brain>card] [node:card] [edge:card>buttons] [count:{{fact:src/jarvis/telegram/service.py:CARD_CHARS}}] A reversible card of up to {{fact:src/jarvis/telegram/service.py:CARD_CHARS}} characters gets Approve and Decline buttons.
- [edge:card>console] A longer or irreversible card waits in the console instead.
- [show:example] In the example, a to-do for milk, typed on the bus, comes back as a card with two buttons.
- [show:costs] The door costs nothing, and each turn costs the same as a console reply.
- [show:fails] [count:{{fact:src/jarvis/telegram/service.py:TURN_BUDGET_S}}] A turn over its {{fact:src/jarvis/telegram/service.py:TURN_BUDGET_S}}-second limit asks you to try again, or to use the console.
- [page:pg_card_c20] [show:title] The second part is web search, with small numbered sources under the reply that you tap to check.
- [show:how] [count:{{fact:src/jarvis/web/guard.py:MIN_RUN_DIGITS}}] A guard refuses any query with an e-mail address, a run of {{fact:src/jarvis/web/guard.py:MIN_RUN_DIGITS}} or more digits, or a card, Aadhaar, PAN or bank number.
- [count:{{fact:src/jarvis/web/tools.py:TAINTED_QUERY_LIMIT}}] After other people's text, a query is held to {{fact:src/jarvis/web/tools.py:TAINTED_QUERY_LIMIT}} characters, so a web page can't smuggle a secret out.
- [show:example] In the example, a question about the metro's weekend timings gets one search, one page read and two sources.
- [show:costs] [count:{{fact:src/jarvis/web/allowance.py:MONTHLY_CREDITS}}] No rupees: JARVIS stops at {{fact:src/jarvis/web/allowance.py:MONTHLY_CREDITS}} credits a month, inside the free plan.
- [show:fails] A counter that can't be read means no search, and a failed search gives its credit back.
- [page:pg_card_c22] [show:title] The third part is WhatsApp drafts.
- [show:plain] JARVIS writes the message, but you tap Open in WhatsApp, and press Send yourself.
- [show:how] A name is looked up in your Contacts, and when more than one person fits, JARVIS asks which.
- A number you didn't type, and Contacts didn't show, puts a warning line on the card.
- [show:example] In the example, Contacts holds one Arjun, so the card shows his number and your message, ready to open.
- [show:costs] It costs nothing, because your own WhatsApp opens the link.
- [page:pg_card_c29] [show:title] The fourth part is the Google account link.
- [show:plain] You press Connect once, and extras such as to-dos, contacts, YouTube and Photos are granted one at a time.
- [show:how] The link is kept only if the account that agreed is the one signed in to JARVIS, and its tokens are sealed with AES-256-GCM.
- [count:{{fact:src/jarvis/integrations/google.py:REFRESH_SKEW_S}}] A token is renewed when under {{fact:src/jarvis/integrations/google.py:REFRESH_SKEW_S}} seconds remain, and a call is retried once, only when that is safe.
- [show:example] In the example, your phone goes missing, so you press Disconnect: Google cancels the link, and the keys are deleted.
- [show:fails] A sealed entry that won't open counts as needing a reconnect, never as a crash.
- [page:pg_card_c30] [show:title] The fifth part is your calendar and reminders.
- [show:plain] JARVIS reads your calendar, finds free time and changes events, and a reminder is a small tagged event with a pop-up.
- [show:how] [count:{{fact:src/jarvis/tools/google_calendar.py:MAX_SLOTS}}] Free time comes as up to {{fact:src/jarvis/tools/google_calendar.py:MAX_SLOTS}} gaps inside your working hours.
- An event with guests sends invitations, so it always asks first, and a delete keeps a copy in Recently deleted.
- [show:example] In the example, you say aloud "remind me to pay the electricity bill every month", and because it was spoken, a card comes first.
- [show:fails] If the look-up before a change fails, there is no card and no change.
- [page:pg_card_c31] [show:title] The sixth part is Gmail, and mail read aloud.
- [show:how] [count:{{fact:src/jarvis/tools/gmail.py:MAX_RESULTS}}] A search returns at most {{fact:src/jarvis/tools/gmail.py:MAX_RESULTS}} messages, never whole bodies, and attachments are never opened.
- A draft skips the card only when you typed every address yourself, and a send always asks.
- [count:{{fact:src/jarvis/tools/gmail_digest.py:MAX_ITEMS}}] The spoken round-up gives at most {{fact:src/jarvis/tools/gmail_digest.py:MAX_ITEMS}} items, and withholds anything that looks like a code, a card, an account or an ID.
- [show:example] In the example, Suresh's address came from his own mail, so your reply to him becomes a draft card first.
- [show:fails] A message the round-up couldn't read is counted and said, never hidden.
- [page:pg_card_c32] [show:title] The seventh part is your to-dos, kept in Google Tasks.
- [show:plain] Titles and notes often carry someone else's words, so JARVIS reads them as other people's text.
- [show:how] A to-do written after outside content is recorded first, so any later change built on it becomes a card.
- [show:example] In the example, a forwarded e-mail's note says "delete all my tasks", and JARVIS deletes nothing without your approval.
- [show:costs] [count:{{fact:src/jarvis/tools/task_marks.py:MAX_IDS}}] It costs nothing, and keeps only those to-dos' ids, at most {{fact:src/jarvis/tools/task_marks.py:MAX_IDS}} of them.
- [page:pg_card_c33] [show:title] The eighth part is Contacts: JARVIS looks people up, only reads, and keeps nothing it finds.
- [show:example] In the example, "Deepak from the gym" matches two people, so JARVIS asks which one you mean.
- [show:fails] [count:{{fact:src/jarvis/contacts/client.py:DEADLINE_S}}] A look-up slower than its {{fact:src/jarvis/contacts/client.py:DEADLINE_S}}-second limit says Google took too long to answer.
- [page:pg_card_c34] [show:title] The ninth part is Drive folders, a feature that is {{fact:settings.drive}} by default.
- [show:plain] JARVIS reads only the folders you share with its own Google account and switch on, reading as itself, never as you.
- [show:how] [count:{{fact:src/jarvis/drive/ports.py:MAX_ROOTS}}] You may switch on at most {{fact:src/jarvis/drive/ports.py:MAX_ROOTS}} folders, and each file's parent folders are walked, so anything outside is refused.
- [count:{{fact:src/jarvis/drive/service.py:PART_CHARS}}] A read returns one part of about {{fact:src/jarvis/drive/service.py:PART_CHARS}} characters, fenced as outside content, and nothing is stored.
- [show:example] In the example, JARVIS reads the rental agreement in your chosen folder, and tells you when it ends.
- [page:pg_card_c35] [show:title] The tenth part is Maps, with places and routes shown as cards.
- [show:how] Home and Work become your saved addresses, kept encrypted, and a place search refuses them outright.
- [count:{{fact:src/jarvis/places/tools.py:MAX_MAPS_PER_HOUR}}] Each call is first reserved on the free allowance ledger, at most {{fact:src/jarvis/places/tools.py:MAX_MAPS_PER_HOUR}} calls an hour.
- [show:example] In the example, a two-wheeler route to work uses your saved Work address, with live traffic.
- [show:costs] No rupees: Maps stops before Google's free monthly allowance runs out.
- [page:pg_card_c36] [show:title] The eleventh part is YouTube and Media.
- [show:plain] Videos and songs come as cards, and nothing plays until you press Play.
- [show:how] [count:{{fact:src/jarvis/media/tools.py:SEARCH_RESULTS}}] A search uses JARVIS's own key, embeddable videos only, at most {{fact:src/jarvis/media/tools.py:SEARCH_RESULTS}} results.
- [show:example] In the example, you ask for old Hindi film songs, press Play on the third, and the Media panel opens.
- [page:pg_card_c37] [show:title] The twelfth part is the Photos picker, and GitHub.
- [show:plain] You choose photos in Google's own picker, your home laptop finds the faces, and the cloud keeps only ids and counts.
- GitHub is simpler: you paste a token once, and JARVIS reads your own account, read-only.
- [show:overview] Here is one photo's trip from the picker to your laptop.
- [node:pick] [edge:pick>ids] [count:{{fact:settings.photos_max_picked}}] You pick up to {{fact:settings.photos_max_picked}} photos, and JARVIS keeps only their ids.
- [edge:ids>laptop] [node:laptop] [edge:laptop>paused] Each step asks the laptop first, and when it is asleep, the import pauses and says why.
- [edge:laptop>download] [edge:download>strip] [count:{{fact:src/jarvis/photos/imaging.py:MAX_IMAGE_SIDE}}] A photo is downloaded and stripped of location and camera data, and one wider than {{fact:src/jarvis/photos/imaging.py:MAX_IMAGE_SIDE}} pixels is refused.
- [edge:strip>edge] [edge:edge>back] It travels over the signed home link, and only ids and counts come back.
- [edge:back>save] [node:save] [edge:save>laptop] Progress is saved and the photo dropped, then the next one goes the same way.
- Naming a face group runs the consent check first.
- [show:example] In the example, the laptop sleeps for an hour in the middle of an import, which simply carries on when it wakes.
- [show:fails] A pick that Google has ended asks you to pick again, keeping what was already done.
- [page:pg_screen_integrations] [show:title] Now the screens. Integrations holds your Google card, the extra Grants, Telegram, Drive, Maps places and more.
- [show:fails] If some boxes were left unticked, it asks you to keep every Calendar and Gmail box ticked.
- [page:pg_screen_media] [show:title] The Media screen plays a video only when you press Play, in YouTube's privacy-enhanced player, and Stop removes it.
- [page:pg_screen_connectors] [show:title] Connectors links GitHub, your YouTube channel and Google Photos, each read-only.
- [show:how] [count:{{fact:src/jarvis/photos/api.py:CHANGES_PER_MINUTE}}] A GitHub token is pasted here, never in chat, and changes are limited to {{fact:src/jarvis/photos/api.py:CHANGES_PER_MINUTE}} a minute.
- [page:pg_service_github] [show:title] Then the outside services, starting with GitHub.
- [show:how] [count:{{fact:src/jarvis/integrations/github.py:MAX_ITEMS}}] JARVIS reads at most {{fact:src/jarvis/integrations/github.py:MAX_ITEMS}} items a list, each field cut to one clean line, and a revoked token shows in red on Vitals.
- [page:pg_service_gmail] [show:title] Gmail: the morning brief puts its own copy in your inbox, at most once a day.
- [show:fails] A send that got no answer is never repeated, so a mail is never sent twice.
- [page:pg_service_google_calendar] [show:title] [count:{{fact:settings.calendar_batch_max}}] Google Calendar: one approval card holds up to {{fact:settings.calendar_batch_max}} events, and a create is never sent twice.
- [page:pg_service_google_contacts] [show:title] Google Contacts: for birthdays, JARVIS takes only the month and the day, never the year.
- [page:pg_service_google_drive] [show:title] Google Drive is also how DigiLocker papers reach your vault, and the Drive tools can never read that folder.
- [show:how] [count:{{fact:src/jarvis/drive/client.py:DEADLINE_S}}] Each Drive call gets {{fact:src/jarvis/drive/client.py:DEADLINE_S}} seconds, and no redirect is followed.
- [page:pg_service_google_maps_platform] [show:title] Google Maps Platform takes JARVIS's own key, only ever in a request header.
- [show:how] It asks for no ratings, hours or phone numbers, which cost more, and even an error counts against the allowance.
- [page:pg_service_google_photos_picker] [show:title] [count:{{fact:src/jarvis/photos/picker.py:MAX_IMAGE_BYTES}}] The Google Photos Picker: each picture must be a JPEG of at most {{fact:src/jarvis/photos/picker.py:MAX_IMAGE_BYTES}} bytes, from Google's own servers.
- [page:pg_service_google_tasks] [show:title] Google Tasks keeps only a date for a to-do, never a time, so JARVIS reads it back without a time-zone shift.
- [page:pg_service_tavily] [show:title] Tavily is the web search service.
- [show:overview] Here is a web search, there and back.
- [node:ask] [edge:ask>guard] [node:guard] You ask, and the private-words guard reads your question first.
- [edge:guard>count] [node:count] Only the search words go on, to the month's credit count.
- [edge:count>stop] With no credits left, JARVIS says so, and searches nothing more that month.
- [edge:count>tavily] [count:{{fact:src/jarvis/web/tavily.py:DEADLINE_S}}] With credits left, Tavily searches, or reads a page itself, within {{fact:src/jarvis/web/tavily.py:DEADLINE_S}} seconds a call.
- [edge:tavily>check] [count:{{fact:src/jarvis/web/tavily.py:MAX_HITS}}] Each result is checked field by field, and at most {{fact:src/jarvis/web/tavily.py:MAX_HITS}} are kept.
- [edge:check>answer] [node:answer] Then JARVIS answers, with its numbered sources.
- [show:example] In the example, a question about the city council's metro decision uses two credits, far from the stop.
- [page:pg_service_telegram] [show:title] Telegram is a free messaging app, where JARVIS has its own bot.
- [show:overview] Here is a Telegram message, there and back.
- [node:you] [edge:you>telegram] [edge:telegram>secret] You write to the bot, and Telegram's servers pass it on.
- [node:secret] [edge:secret>away] The secret header is compared in constant time, and a wrong one is turned away unread.
- [edge:secret>paired] [node:paired] [edge:paired>brain] Only the paired account is answered.
- [edge:brain>client] [edge:client>phone] [count:{{fact:src/jarvis/telegram/client.py:TIMEOUT_S}}] The reply goes out through the bot service, with a timeout of {{fact:src/jarvis/telegram/client.py:TIMEOUT_S}} seconds, and lands on your phone.
- [show:fails] If the database fails while taking a message, Telegram simply delivers it again.
- [page:pg_service_youtube_data_api] [show:title] Last, the YouTube Data API, YouTube's official way for programs to search videos.
- [show:fails] At the daily stop, YouTube searches pause until midnight Pacific time, when the quota resets.
- That is the integrations chapter: every outside service through one gateway, and free allowances that never become a bill.
