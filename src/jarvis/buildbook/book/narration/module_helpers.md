---
chapter: module_helpers
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
pages:
  "pg_module_helpers": "436d6936e4704d27"
  "pg_card_c11": "c363f6aaf81452c8"
  "pg_card_c19": "a0a2ca2c74371c24"
  "pg_card_c25": "3b3602091ba6a386"
  "pg_card_c26": "3fbb57daabb8a34e"
  "pg_card_c27": "a359e0092bd4311d"
  "pg_card_c60": "8937509eb0e9f775"
  "pg_card_c61": "19c50f91a3140994"
  "pg_screen_brief": "fbee37aa8b7acb8d"
  "pg_screen_helpers": "e440d95ad0fb2fe5"
  "pg_service_ndma_sachet": "4a3772611c568f90"
  "pg_service_open_meteo": "7e33c0d4296e2e5f"
---
- [page:pg_module_helpers] [show:title] This chapter is about the everyday helpers that look ahead for you, nearly all of them free and plain code.
- [show:plain] The morning brief gives your day at a glance: calendar, unread mail, parcels on the way, family calendars, documents due, and what needs you.
- The Helpers panel has tabs: Today for bills, birthdays and your top priority, and Home for chores, upkeep, weather and official disaster warnings.
- Nudges holds gentle reminders, each off until you switch it on, and Kitchen gives recipe ideas that keep to your diet; groceries, family calendars and parcels round it off.
- [show:overview] Here is a helper reminder's journey, from the clock to your phone.
- [node:scheduler] It starts with Cloud Scheduler, which wakes JARVIS; only the scheduler's own signed token is accepted.
- [edge:scheduler>brief] [node:brief] When your brief is due, the morning wake-up makes it first.
- [edge:scheduler>clock] [node:clock] Then the helpers' jobs run: the frequent ones on the home watchdog's clock, and the daily ones on the morning tick.
- [edge:clock>rows] [node:rows] Before a job reads your Google data, it asks the gateway whether your permission row allows it.
- [edge:rows>paused] [node:paused] On Ask first or Never, the helper pauses, and says so in one fixed line at the top of its tab.
- [edge:rows>sources] [node:sources] Then it reads its sources: your mail, the weather, or the official SACHET warnings.
- [edge:sources>gate] [node:gate] [count:{{fact:settings.nudges_max_per_hour}}] Each message then meets your caps and switches: at most {{fact:settings.nudges_max_per_hour}} nudges an hour, and {{fact:settings.nudges_max_per_day}} a day.
- [edge:gate>nonudge] [node:nonudge] Over a cap, no nudge is sent.
- [edge:gate>policy] [node:policy] Otherwise the alert policy applies your quiet hours, and then rings.
- [edge:policy>you] [node:you] And on your phone, you tap Pay or Snooze.
- [show:how] [count:₹{{fact:settings.bill_pay_cap_inr}}] For a bill, JARVIS writes a UPI payment link for your own app to open; it never pays, and the amount is capped at ₹{{fact:settings.bill_pay_cap_inr}}.
- [show:example] In the made-up example, Lata's brief lists her meetings, a parcel out for delivery, and the electricity bill due on Friday.
- Later the Today tab reminds her of the bill; she taps Pay, approves with her fingerprint, and her UPI app opens with the amount filled in for her PIN.
- [show:costs] The helpers cost nothing: the weather and SACHET need no key, and nearly all is plain code; a recipe idea or the brief's AI summary counts against your limit.
- [show:fails] A helper part whose setup fails is left out while the rest keep running, and nudge settings that can't be read mean no nudge.
- [page:pg_card_c11] [show:title] Now the first part: the scheduler's ticks and the watchdog.
- [show:plain] JARVIS sleeps when nobody is talking to it, so two alarm clocks in Google Cloud wake it: a morning clock and a watchdog clock.
- The morning clock rings every half hour through the early morning, making your brief when it is due, then doing the daily chores.
- The watchdog clock rings every few minutes all day, noticing when your home laptop stops answering, and running the helpers' small jobs.
- [show:how] Google's signature is checked, with the issuer, the exact address and the scheduler's own account, so one clock's token never opens the other.
- [count:{{fact:src/jarvis/ticks.py:TICK_TOTAL_BUDGET_S}}] Each job gets at most {{fact:src/jarvis/ticks.py:MAX_BUDGET_S}} seconds, and all of them {{fact:src/jarvis/ticks.py:TICK_TOTAL_BUDGET_S}} seconds together, inside the scheduler's own deadline.
- [show:example] In the made-up example, the morning clock rings before Deepa's brief is due, so it runs the chores, and on its next ring the brief is made.
- [show:costs] It costs nothing: Google gives a few scheduler jobs free, and JARVIS uses only the morning clock and the watchdog.
- [show:fails] A job the tick has no time left for is reported as skipped, never silently dropped, and a caller without the valid token learns nothing.
- [page:pg_card_c19] [show:title] The second part is the morning brief.
- [show:plain] Each morning, at the time you pick, JARVIS lays out your day on one screen, and every fact is written by code, so it is the same every time.
- An optional "what matters today" summary by AI stays off until you agree to its cost, and the brief can also land in your own Gmail inbox.
- [show:how] The tick asks whether your brief is due, catching up one missed at its time, and a claim makes sure only one worker builds it.
- [count:{{fact:src/jarvis/brief/collect.py:MAX_READS}}] Fixed read-only Google calls gather the calendar, the inbox and your to-dos, reading at most {{fact:src/jarvis/brief/collect.py:MAX_READS}} messages, and withholding codes and bank messages.
- [count:{{fact:src/jarvis/brief/vault_due.py:WITHIN_DAYS}}] Documents due come from the vault: within {{fact:src/jarvis/brief/vault_due.py:WITHIN_DAYS}} days, or expired in the last {{fact:src/jarvis/brief/vault_due.py:EXPIRED_DAYS}}.
- [count:{{fact:src/jarvis/brief/summarize.py:MAX_LINES}}] The summary is one fast AI call to a brain that doesn't train on your content, with no tools, and at most {{fact:src/jarvis/brief/summarize.py:MAX_LINES}} short lines.
- [show:example] In the example, Farhan's brief finds his meetings, a free block, his mail by kind and a parcel, with two lines marked as AI under the facts.
- [show:costs] [count:{{fact:src/jarvis/brief/summarize.py:MAX_TOKENS}}] The facts cost nothing; the summary is capped at {{fact:src/jarvis/brief/summarize.py:MAX_TOKENS}} tokens of output, and checks your monthly limit first.
- [show:fails] [count:{{fact:src/jarvis/brief/schedule.py:MAX_SECTION_RETRIES}}] One failing section shows as unavailable while the rest still shows, and later ticks make the brief again, up to {{fact:src/jarvis/brief/schedule.py:MAX_SECTION_RETRIES}} times.
- [page:pg_card_c25] [show:title] The third part is groceries.
- [show:plain] Your shopping list lives as a list called Groceries in your own Google Tasks, so it is on your phone in the shop, even without JARVIS open.
- JARVIS notices when an item is already there, so adding milk twice gives one line, and it knows that curd and yogurt are the same thing.
- [show:how] Names are compared ignoring case, spaces and a simple plural, with a small table of synonyms, and matching units add their amounts together.
- [count:{{fact:src/jarvis/groceries/tools.py:MAX_ITEMS}}] The brain can read, add and tick off, at most {{fact:src/jarvis/groceries/tools.py:MAX_ITEMS}} items at a time, all through the gateway under your Groceries row.
- [show:example] In the example, Leela adds milk on Monday, her husband adds more on Tuesday, and the one line grows; on Wednesday, yogurt finds Curd already there.
- [show:costs] It costs nothing: Google Tasks is free.
- [show:fails] [count:{{fact:src/jarvis/groceries/items.py:NAME_MAX}}] A name over {{fact:src/jarvis/groceries/items.py:NAME_MAX}} characters is refused before Google is called, and ticking off never deletes: the item waits under Completed.
- [page:pg_card_c26] [show:title] The fourth part is family calendars.
- [show:plain] When family members share their Google calendars with you, JARVIS can tell you what each has on, and when everyone is free.
- On a calendar you may edit, it can also add an event, but only after you approve a card, because the other person sees it at once.
- [show:how] [count:{{fact:src/jarvis/family/models.py:MAX_MEMBERS}}] JARVIS first checks with Google that a calendar really is shared with you, and keeps at most {{fact:src/jarvis/family/models.py:MAX_MEMBERS}} members.
- The add-event tool always shows a card, never offers Allow, and can never be approved from Telegram.
- [show:example] In the example, Arjun asks when the family is all free on Saturday, then approves a card that puts a lunch on Priya's calendar.
- [show:costs] It costs nothing: ordinary Google Calendar calls through your own Google link.
- [show:fails] A calendar not yet shared with you is refused, with how to ask for it, and Google's own error text never reaches you.
- [page:pg_card_c27] [show:title] The fifth part is parcels.
- [show:plain] Ask where your parcels are, and JARVIS reads your order and shipping mails from known shops and couriers, with plain rules, no AI, and nothing kept.
- [show:how] [count:{{fact:src/jarvis/packages/tools.py:DEFAULT_DAYS}}] It searches the last {{fact:src/jarvis/packages/tools.py:DEFAULT_DAYS}} days by default, and never more than {{fact:src/jarvis/packages/tools.py:MAX_DAYS}}.
- A sender counts as known only when Gmail's own check says the mail really came from there; a From line alone proves nothing.
- A tracking number is taken only right after a tracking word, in the exact format of the named courier, so phone numbers, codes and amounts never are.
- [show:example] In the example, Ritu's kettle is shipped and her phone cover is out for delivery, and a mail pretending to be from a shop is ignored.
- [show:costs] It costs nothing: a few Gmail reads and plain rules, with no tracking service.
- [show:fails] The courier number formats are Unverified against real mail, so a miss means no tracking number shown, never a wrong one.
- [page:pg_card_c60] [show:title] The sixth part is the helpers themselves.
- [show:plain] Helpers are small, free jobs that look ahead for you, and nearly all are plain code, so they keep working with the AI off.
- [show:how] [count:{{fact:settings.helpers_clock_budget_s}}] The regular jobs ride the watchdog's call within {{fact:settings.helpers_clock_budget_s}} seconds, and the daily Gmail scans ride the morning tick.
- Pay builds a UPI link from your saved bill only after you approve its card, and the link is shown once, never kept.
- [count:{{fact:settings.weather_poll_minutes}}] Weather is read about every {{fact:settings.weather_poll_minutes}} minutes for your rounded location, and SACHET's warnings every {{fact:settings.disaster_poll_minutes}}, keeping only your district's.
- [count:{{fact:src/jarvis/helpers/house/night.py:MAX_NIGHT_RINGS}}] At night, at most {{fact:src/jarvis/helpers/house/night.py:MAX_NIGHT_RINGS}} different disaster warnings ring, and the rest fold into one morning summary.
- After a recipe idea, a code check has the last word, so meat is never shown to a vegetarian kitchen.
- [show:example] In the example, Vikram taps Pay on his electricity bill, approves with his passkey, and a UPI link and QR code appear once, for his own app and his PIN.
- [show:costs] [count:{{fact:src/jarvis/helpers/kitchen/recipes.py:MAX_TOKENS}}] The one exception to free is a new recipe idea: a single AI call of at most {{fact:src/jarvis/helpers/kitchen/recipes.py:MAX_TOKENS}} tokens, counted against your limit.
- [show:fails] A warning no channel took is tried again on the next run, and with no private brain, recipe ideas fall back to your saved recipes.
- [page:pg_card_c61] [show:title] The seventh part gathers the fixes for problems you reported.
- [show:plain] JARVIS never replies with an empty filler any more, and a batch of calendar events goes on one approval card, with Undo all.
- [show:how] [count:{{fact:settings.calendar_batch_max}}] One card holds up to {{fact:settings.calendar_batch_max}} events, and creates only what is missing, so a retry never makes an event twice.
- [show:example] In the example, Nisha's yoga course goes on one card, and when she skips a session, one card moves it and every later one.
- [show:costs] Most fixes are plain code at no cost, and their AI use counts against your monthly limit like any reply.
- [show:fails] An answer still empty after its retry says so in a fixed line, and is never stored for a model to copy.
- [page:pg_screen_brief] [show:title] Now the screens, starting with Brief.
- [show:plain] Brief is your morning page: today's calendar with its clashes and free gaps, your mail, to-dos, parcels, family calendars and waiting approvals.
- [show:how] Opening the panel makes the brief if none is made yet, and the round arrow makes today's again.
- Switching on the AI summary or the inbox copy opens a window that says what will happen, and nothing changes until you press its button.
- [show:example] In the example, the brief shows a clash between a review and a call, and when a meeting moves, you make it again from the round arrow.
- [show:costs] The brief costs nothing in AI; only the summary uses the paid Claude brain, never the free one.
- [show:fails] If making the brief fails, the panel says so, with the reason and a Try again button.
- [page:pg_screen_helpers] [show:title] Next, the Helpers screen.
- [show:plain] Its tabs are Today, Home, Nudges and Kitchen, plus Watch for your steps, heart rate and sleep, and Wardrobe for clothes and laundry.
- [show:how] Each tab starts with any paused line, and Home shows SACHET's alerts in SACHET's own words, never as JARVIS's.
- [show:example] In the example, you press "Ask to pay this" on a bill, approve the card, pay in your UPI app, and press Paid.
- [show:costs] The helpers use free sources and JARVIS's own records, and the Kitchen tab itself never calls the AI.
- [show:fails] [count:{{fact:src/jarvis/api/helpers.py:CHANGES_PER_MINUTE}}] If a change fails, the tab says so, with the reason, and changes are limited to {{fact:src/jarvis/api/helpers.py:CHANGES_PER_MINUTE}} a minute.
- [page:pg_service_ndma_sachet] [show:title] Now two free outside services, starting with NDMA SACHET.
- [show:plain] It is the government's public feed of official disaster and weather warnings, and JARVIS is only a second channel after the official app, SMS and cell broadcast.
- Nothing about you goes to SACHET: the matching against your district happens inside JARVIS.
- [show:how] [count:{{fact:src/jarvis/helpers/sources.py:OUTSIDE_TIMEOUT_S}}] Each read uses no key, follows no redirect and must finish within {{fact:src/jarvis/helpers/sources.py:OUTSIDE_TIMEOUT_S}} seconds, and the alert is a fixed sentence.
- [show:fails] If SACHET doesn't answer, the panel says since when, and JARVIS keeps trying on the next runs.
- [page:pg_service_open_meteo] [show:title] Last, Open-Meteo.
- [show:plain] It is a free weather service with no account and no key, and all it receives is a map point near your home, rounded to about a kilometre, and your time zone.
- [show:how] At most one weather warning of each kind goes out a day, and a value that isn't a plausible number is left out.
- [show:fails] Unverified: exactly what Open-Meteo does if its free daily limit is ever passed.
- That is the Daily helpers chapter: a day laid out by code, reminders that keep to your caps, and nothing paid or sent without you.
