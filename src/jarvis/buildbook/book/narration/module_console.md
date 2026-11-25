---
chapter: module_console
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
pages:
  "pg_module_console": "df072ac9862073c3"
  "pg_card_c01": "4324712b3fcf1d31"
  "pg_card_c02": "550c8b34167298f0"
  "pg_card_c03": "773a566ba7590934"
  "pg_card_c41": "8336130889fc3e26"
  "pg_screen_construct": "199bad85a6e6ff3a"
  "pg_service_firestore": "c0fa9cd8ff2d6ced"
  "pg_service_google_sign_in": "fde5db99cea41a26"
  "pg_service_redis": "fb4824e2028bff31"
---
- [page:pg_module_console] [show:title] This chapter is about the console you use JARVIS from, and the server that stands behind it.
- [show:plain] The console is one web page, on a laptop or a phone: the chat, a dock of panels, the brain picker, and the Night and Day looks.
- Behind it sits JARVIS's server, which lets in only the Google accounts you listed as owners, and limits how fast anyone may call it.
- It keeps your conversations, approvals and audit trail in Google's Firestore database, and engineers have a terminal client too.
- [show:overview] Here is the whole path, from signing in to a reply on your screen.
- [node:you] It starts with you, opening the console in your browser.
- [edge:you>google] The console sends you to Google to sign in.
- [node:google] Google checks that it is really you, and tells JARVIS which address signed in.
- [edge:google>owner] [node:owner] That address comes back to JARVIS, which lets in only a verified address on its owner list.
- [edge:owner>refused] Any other account is turned away, with the words: This JARVIS belongs to someone else.
- [edge:owner>cookie] [node:cookie] [count:{{fact:settings.session_cookie_max_age_s}}] An owner gets a signed session cookie, which lasts {{fact:settings.session_cookie_max_age_s}} seconds.
- [edge:cookie>limits] Every request after that carries the cookie on to the server's limits.
- [node:cli] The terminal comes in by a side door, with a secret token in place of a cookie.
- [edge:cli>limits] [node:limits] [count:{{fact:settings.rate_limit_per_minute}}] Both doors meet the same limits: each client may make {{fact:settings.rate_limit_per_minute}} requests a minute, and an oversized request is refused unread.
- A browser's changes must also carry a JARVIS header, which another website is unable to add.
- [edge:limits>routes] [node:routes] What passes reaches the chat and approval routes, which hand your message to the brain and decide the waiting cards.
- [edge:routes>store] Whatever must be kept travels to Firestore: your conversations, the waiting cards and the audit chain.
- [node:store] Every store speaks through one small, shared doorway, so only one part of JARVIS ever talks to Firestore.
- [edge:routes>page] [node:page] The reply travels back to the page, where it is shown as plain text, never run as code.
- Under a reply whose model has no known price, the console says price unknown, never free, and so does the deck's conversation cost.
- [show:example] In the made-up example, Asha opens JARVIS on her phone at the bus stop, and signs in with Google.
- Her address is on the owner list, so the console opens on the chat, with Chat, Brief, Approvals and a More button in the dock.
- She asks for today's plan, and later, at her desk, the same conversation is waiting on her laptop, because it lives on the server.
- That evening her cousin tries the same link with his own Google account, and sees: This JARVIS belongs to someone else.
- [show:costs] The console costs nothing: JARVIS serves it itself, and the server and its database are set up to run inside Cloud Run's and Firestore's free tiers.
- [show:fails] A wrong or missing sign-in gets status 401, and a Google account that isn't an owner gets status 403.
- More requests than the limit get status 429, with a short wait.
- [count:{{fact:src/jarvis/storage/firestore_docs.py:TX_ATTEMPTS}}] And a database write that clashes with another is retried, up to {{fact:src/jarvis/storage/firestore_docs.py:TX_ATTEMPTS}} times.
- [page:pg_card_c01] [show:title] Now the first part: the web console itself.
- [show:plain] You install nothing: the JARVIS server sends the page, its fonts and its 3D library itself, so nothing is loaded from another website.
- [show:how] Every script and stylesheet has its own fixed address, so a request can never name a file outside that list.
- The dock is measured at every width, and buttons that don't fit fold into the More sheet, last ones first.
- Chat, Brief and Approvals never fold for lack of room, and if Approvals folds on a mid-size laptop, More carries its waiting count.
- Under each reply the console shows the model, the time and the rupees, or price unknown when JARVIS has no price for that model.
- [show:example] In the example, you open JARVIS on your phone one morning, tap More, choose Things, and ask where Rohan left the spare car key.
- That evening on your laptop the dock has room for nearly every button, you switch the look from Night to Day, and your layout and look are still there the next morning.
- [show:costs] It costs nothing in rupees, and the console keeps no data of its own on the server; your browser keeps only small conveniences, like your layout.
- [show:fails] A panel whose data can't be fetched shows a plain line, such as: Couldn't load approvals, with a Retry button.
- If the browser can't draw 3D, the flat emblems stay in place, and if measuring the dock goes wrong, every button shows again.
- [page:pg_card_c02] [show:title] The second part is JARVIS's front door: the server that the console, the phone app and the terminal all talk to.
- [show:plain] It works out who you are from your sign-in, never from what a page claims, and it answers trouble in short, plain words.
- [show:how] [count:{{fact:src/jarvis/api/auth.py:SESSION_ABSOLUTE_MAX_S}}] The cookie's time runs from your last visit, but it ends for good {{fact:src/jarvis/api/auth.py:SESSION_ABSOLUTE_MAX_S}} seconds after you signed in.
- Your address is checked against the owner list on every request, so taking an address off the list signs that browser out at once.
- Your user id is a short hash of your address, made from the sign-in, and a user id sent by a client is never read.
- [count:{{fact:src/jarvis/api/auth.py:FRESH_SIGN_IN_S}}] A sensitive step, such as opening the Build Book, asks you to sign in again, and that counts as fresh for {{fact:src/jarvis/api/auth.py:FRESH_SIGN_IN_S}} seconds.
- The full book's own page holds no data: it reads the book with your session's token, kept in that tab alone.
- [count:{{fact:src/jarvis/api/body.py:MAX_BODY_BYTES}}] A request over {{fact:src/jarvis/api/body.py:MAX_BODY_BYTES}} bytes is refused before it is read, with larger caps only for uploads.
- Errors become a short answer with an error code, and an AI vendor's own words stay in the log.
- [show:example] In the example, a script on a stranger's computer floods the server; after {{fact:settings.rate_limit_per_minute}} requests in that minute it must wait, while your chat carries on.
- [show:costs] The sign-in is Google's own, and the server runs inside Cloud Run's free allowance; the size of that allowance is Google's, and Unverified here.
- [show:fails] A request body over the cap gets status 413, and outside development, start-up stops on an unsafe setting, such as having no API token.
- [page:pg_card_c03] [show:title] The third part is the terminal client.
- [show:plain] It lets someone talk to JARVIS from a computer's command line, with no browser, and the same command starts the server.
- [show:how] It builds the same conversation store, brain list and monthly spending meter as the server, so a chat here counts against the same limit.
- Each answer ends with a line naming the model, the tokens, the cost in rupees and the time, or price unknown for a model JARVIS has no price for.
- [show:example] In the example, Arjun, who looks after the code, watches an answer arrive word by word, then starts again with Gemini as the brain, to compare the two.
- [show:costs] The client costs nothing itself; each answer is paid like any other message to the chosen brain.
- [show:fails] At the monthly limit, in No-AI mode, or on a brain error, it prints a short note in brackets and waits for the next line.
- [page:pg_card_c41] [show:title] The fourth part is the document store, where JARVIS keeps what must survive a restart.
- [show:plain] In the live system that is Firestore; on a developer's machine it is a copy held in memory, and that choice is made in one single place.
- [show:how] The shared doorway offers only get, query, write and transaction, and its in-memory twin behaves the same way, so the tests check the real rules.
- Each conversation is a header plus one record per turn, and a save writes only the new turns, with the header last.
- [count:{{fact:src/jarvis/storage/sessions.py:CACHE_SESSIONS}}] Up to {{fact:src/jarvis/storage/sessions.py:CACHE_SESSIONS}} conversations stay in memory, so a repeat read costs one look-up.
- [count:{{fact:src/jarvis/storage/sessions.py:CAS_ATTEMPTS}}] A save first checks that nobody else changed the conversation since it was read, trying up to {{fact:src/jarvis/storage/sessions.py:CAS_ATTEMPTS}} times.
- An approval is read and removed in one transaction, so it runs once, however often it is tapped.
- Each audit line is added, and the chain's head moved, in one transaction, so the chain never forks.
- [show:example] In the example, you ask JARVIS one evening to send Neha the guest list, and the request is saved as an approval waiting for you.
- The server shuts down in the quiet minutes after, yet when you open Approvals a fresh server starts, and the request is still there.
- You tap Approve twice on a slow connection; the message goes out once, and the activity log gains one line, linked to the line before it.
- [show:costs] It costs nothing inside Firestore's free daily allowance, whose size is Google's and Unverified here; no expiry rule deletes anything, because those deletes are billed.
- [show:fails] [count:{{fact:src/jarvis/storage/sessions.py:LIST_FALLBACK_SCAN}}] While Firestore still lacks an index, the list of conversations is sorted inside JARVIS, from up to {{fact:src/jarvis/storage/sessions.py:LIST_FALLBACK_SCAN}} of them.
- If another window changed the same conversation, the save writes nothing, and you see a plain line saying so.
- [page:pg_screen_construct] [show:title] Next, a screen with no work to do: Construct, the console's hologram.
- [show:plain] Wireframe shapes, nested inside each other, turn slowly above a projector base, while a glowing plane sweeps up and down through them.
- [show:fails] Your own browser draws it, with no server call, and without 3D the flat picture stays; nothing else depends on this panel.
- [page:pg_service_firestore] [show:title] Now the outside services, starting with Firestore, Google's database in the cloud.
- [show:plain] It holds what must outlast a restart: conversations, approval cards, the audit trail, memories, the vault, settings, and the Build Book's sealed copies.
- JARVIS locks private content, such as your vault files, with its own keys before it goes there, so the database never holds them in clear.
- [show:how] Once you run the one-time backup setup, Google keeps a copy every day, and each month JARVIS restores the newest one into a throw-away database to check it.
- Billing's month records live there too: the rupees spent and, kept apart, the replies whose price JARVIS doesn't know.
- [count:{{fact:src/jarvis/storage/firestore_admin.py:CALL_S}}] Each call to those copies has a deadline of {{fact:src/jarvis/storage/firestore_admin.py:CALL_S}} seconds, and one aimed at any database but the throw-away one is refused.
- [show:costs] [count:₹{{fact:settings.backup_drill_max_inr}}] It is ₹0 inside the free allowance, whose size is Unverified here, and a drill is refused when its restore would cost more than ₹{{fact:settings.backup_drill_max_inr}}.
- [show:fails] If Firestore is down, a request that needs it fails, and the systems check shows the database as not answering.
- [page:pg_service_google_sign_in] [show:title] Next, Google sign-in: how you prove to JARVIS that you are you.
- [show:plain] Google only says who you are; JARVIS decides who may enter, and at sign-in it asks Google for your e-mail address and nothing else.
- [show:how] The same Google service links your calendar, mail and to-dos through a second, separate permission screen, and proves that the clock's calls really come from Google.
- [show:fails] Without its client id, its secret, the public address or an owner, the server refuses to start in this sign-in mode.
- [page:pg_service_redis] [show:title] Last, Redis: a small, fast storage program that keeps data in memory.
- [show:plain] JARVIS uses it only on a developer's own machine with Docker; your live JARVIS keeps its conversations in Firestore, and never uses Redis.
- [show:how] [count:{{fact:settings.session_ttl_s}}] There, a conversation expires after {{fact:settings.session_ttl_s}} seconds without activity.
- That is the Console chapter: one page you install nothing for, one front door for owners only, and one doorway to everything that is kept.
