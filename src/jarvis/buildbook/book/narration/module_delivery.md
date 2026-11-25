---
chapter: module_delivery
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
pages:
  "pg_module_delivery": "c8525dceae272802"
  "pg_card_c49": "8bf25ccf825ae5ea"
  "pg_card_c50": "8d10c4707cf79f68"
  "pg_card_c58": "e4273faf9414f2bd"
  "pg_card_c59": "6c77e8d0bd7ac9f5"
  "pg_card_c66": "c86cb20aa78e3fe9"
  "pg_service_cloud_run": "7ffda53a17a616d0"
  "pg_service_cloud_scheduler": "dfd852efa753ba2d"
---
- [page:pg_module_delivery] [show:title] This chapter is about how a change becomes the JARVIS you use, safely, and how your data survives a bad day.
- [show:plain] Every change is tested on GitHub first: the unit tests, exams called evals that try to trick JARVIS, and a visual check of every console panel.
- Only then is the new version built, started without traffic, checked for health, and switched on.
- And once you run a one-time setup, Google copies the whole database every day, and JARVIS proves once a month that a copy really restores.
- [show:overview] Here is the whole path, from a proposed change to a backup that is proven to work.
- [node:pr] It starts with a pull request: a proposed change to JARVIS's code.
- [edge:pr>tests] The change goes straight to the checks.
- [node:tests] The unit tests run on both supported Python versions, beside a Firestore emulator, the browser tests, the mock evals and the visual gate.
- [edge:tests>blocked] When any check fails, the merge is blocked until the change is fixed.
- [edge:tests>build] Once every check passes and the change is merged, it moves on to be built.
- [node:build] The new image is built with the exact package versions written in a locked list.
- [node:health] It starts beside the old version with no traffic, and the deploy asks its health page whether it is well.
- [edge:health>keep] If it isn't healthy, it never gets a single request, and the current JARVIS keeps running unchanged.
- [edge:health>live] If it is healthy, traffic switches over to the new version.
- [edge:live>copy] Your data then has a path of its own, starting with a copy of the live database.
- [node:copy] After your one-time setup, Google copies the whole database every day, and guards the live one against deletion.
- [edge:copy>drill] [count:{{fact:settings.backup_drill_day}}] On day {{fact:settings.backup_drill_day}} of each month, the newest copy is taken for a rehearsal.
- [node:drill] The restore drill puts that copy into a throw-away database, and refuses when that would cost more than ₹{{fact:settings.backup_drill_max_inr}}.
- [edge:drill>verify] The restored copy goes to the checks, a step at a time across the mornings.
- [node:verify] They count every collection, open the canary with today's key, and open each vault from the copy.
- [node:clean] Last, the throw-away copy is deleted, and the result is kept for the Vitals backup line.
- [show:example] In the made-up example, December's drill day arrives, and the drill starts from {{fact:src/jarvis/backup/drill.py:AUTO_FROM_HOUR}} o'clock in the morning.
- [count:₹{{fact:settings.backup_drill_max_inr}}] It checks that restoring last night's copy will cost under ₹{{fact:settings.backup_drill_max_inr}}, then restores it into a throw-away database.
- Over the next mornings it counts, opens the canary, and opens a vault file, and then the Vitals backup line shows that the drill passed.
- [show:costs] The tests and the deploy run inside GitHub's and Google's free tiers, and the mock evals are free.
- Backups cost nothing until you run the setup; after that, a few rupees a month for a small database.
- [show:fails] A version that isn't healthy never gets traffic, and a drill that fails anywhere records a reason and still deletes its copy.
- [count:{{fact:settings.backup_max_age_h}}] A newest copy older than {{fact:settings.backup_max_age_h}} hours turns the backup line red; before the setup, it simply says not set up.
- [page:pg_card_c49] [show:title] The first part is configuration: every knob that changes how JARVIS behaves, kept in one place.
- [show:plain] Settings are read from the server's environment when JARVIS starts, and secret values are held in a type that never prints them.
- [show:how] On Cloud Run, JARVIS refuses unsafe settings at start-up, such as developer mode, token-only sign-in, or an AI choice without its key.
- [count:{{fact:src/jarvis/config.py:MIN_SESSION_SECRET_LEN}}] Google sign-in also needs a session secret of at least {{fact:src/jarvis/config.py:MIN_SESSION_SECRET_LEN}} characters.
- [show:example] In the made-up example, Imran forgets that secret, and the server stops at once with a message naming the setting, before it serves a single page.
- [show:costs] Reading settings costs nothing; a few extra secrets in Google's Secret Manager may cost a few rupees a month, which is Unverified.
- [show:fails] A failed check names the setting, never its value, and a missing optional key just leaves its feature off.
- [page:pg_card_c50] [show:title] The second part is logging: the diary JARVIS keeps of what its server does.
- [show:plain] It writes one line for each event, and every line of one request carries that request's own short trace id.
- [show:how] With JSON logging on, each line holds the time, level, place, trace id and message; with it off, a plain line a person can read.
- [show:example] In the made-up example, Kiran's to-do fails, and searching for its trace id shows every line of that request together, without a word of her to-do.
- [show:costs] It costs nothing in JARVIS itself; how long the hosting's log service keeps the lines, and whether that stays free, is Unverified.
- [show:fails] A value that can't be written as JSON is written as text instead, and keeping secrets out of the lines is each caller's duty.
- [page:pg_card_c58] [show:title] The third part is delivery: how a change to the code reaches your live assistant.
- [show:plain] GitHub tests every proposed change before it may be merged, and every release carries a clear version number and title.
- [show:how] Separate jobs check each pull request's title and every plan's change log, and the documents job fails a Build Book page older than its code.
- On a merge, the deploy job signs in to Google with no stored key.
- It refuses to deploy if main has moved on since, so re-running an old job never rolls JARVIS back.
- A set-up script prepares the Google Cloud side once, and skips whatever already exists, so it is safe to run again.
- [show:example] In the made-up example, Akhil merges a builder's change one evening; the new image starts with no traffic, and its health page soon answers ok.
- So traffic moves to it; had the health page kept failing, the morning's version would have kept serving.
- [show:costs] It costs nothing inside the free tiers of GitHub Actions and Google's image store, whose exact limits are Unverified, and old images are deleted.
- [show:fails] A wrongly titled pull request fails its title check until it is renamed.
- [page:pg_card_c59] [show:title] The fourth part is the evals and the visual gate: the exams JARVIS must pass before a change reaches you.
- [show:plain] Each skill has fixed cases for right answers, tricks hidden in e-mails or web pages, privacy, and staying inside your budget.
- Each exam also holds a deliberately broken version that must fail, which proves the exam really catches problems.
- [show:how] The mock evals run every suite against a fake AI that always answers the same way, so the results repeat and cost nothing.
- A run against the real AI shows a rupee estimate and waits for your typed YES; a safety stop ends it if spending goes well past that.
- The visual gate opens each console panel at desktop and phone size, in Night and Day.
- It fails on overlaps, low contrast, and touch targets too small for a finger.
- [show:example] In the made-up example, the document suite feeds JARVIS a PDF that says to delete all events, and JARVIS deletes nothing, so it passes.
- Its negative control, with the guard switched off, does delete, so it fails, as it must.
- Then the visual gate finds a new button too short for a finger on a phone, and the pull request goes red until it is fixed.
- [show:costs] The mock evals, the visual gate and the coverage check cost nothing: they make no AI call and need no key.
- [show:fails] With no AI key, the real-model gate is skipped with a notice, and it only reports, so it never stops a deploy.
- [page:pg_card_c66] [show:title] The fifth part is the backups, and the restore drill that proves them.
- [show:plain] Everything JARVIS remembers for you lives in one Google database.
- [count:{{fact:src/jarvis/backup/status.py:RETENTION_DAYS}}] After the one-time set-up, Google copies it every day, and keeps each copy for {{fact:src/jarvis/backup/status.py:RETENTION_DAYS}} days.
- A backup you have never restored is only a hope, so once a month JARVIS rehearses a real recovery, without ever writing to your live data.
- [show:how] Every morning, JARVIS writes a test value sealed with its keyring, so a restored copy can prove it opens with today's key.
- The same job raises a backup problem once a day when the newest copy is too old, the schedule is gone or the key changed.
- [count:{{fact:settings.backup_drill_manual_per_month}}] Besides the monthly drill, you may approve a test my backup card at most {{fact:settings.backup_drill_manual_per_month}} extra times a month, and never through Approve all.
- [count:{{fact:src/jarvis/backup/walk_checks.py:SAMPLES_PER_COLLECTION}}] The verifier counts every collection, opens each owner's vault, and compares up to {{fact:src/jarvis/backup/walk_checks.py:SAMPLES_PER_COLLECTION}} documents a collection with the live ones.
- Comparing too few is a failure, never a pass.
- It reads the live side through a view with no way to write, and the copy through a reader with no writer at all.
- [show:example] In the made-up example, Suresh's drill restores last night's copy, and over the next morning ticks every count matches and his vault opens.
- All pass, the copy is deleted, and Suresh gets a note that the backup drill passed.
- [show:costs] After the set-up, Google charges for storing the copies and for the monthly restore, and Vitals shows the month's cost in rupees.
- [show:fails] A drill cut off after its restore began ends as interrupted, never with a second restore.
- The copies live in the same project as the key, so the drill proves recovery from a bad write or delete, not from losing the whole project.
- [page:pg_service_cloud_run] [show:title] Now the outside services, starting with Cloud Run, where JARVIS lives.
- [show:plain] It is Google's service for running a program on the internet without a server to look after, in your own project, in Google's Mumbai region.
- It starts JARVIS when a request arrives, and lets it sleep when nobody is using it.
- [show:how] [count:{{fact:settings.rate_limit_per_minute}}] Each address may make up to {{fact:settings.rate_limit_per_minute}} requests a minute, and every request must be signed in.
- For Drive, JARVIS asks Cloud Run's own metadata server for a read-only token, so no key exists at all.
- [show:example] In the made-up example, JARVIS is asleep at dawn; Google's clock calls, Cloud Run starts it in a few seconds, and the brief is made.
- [show:costs] It costs nothing inside Cloud Run's free monthly allowance; the charge beyond it is Unverified, and a budget alert e-mails you at the first rupee.
- [show:fails] After a long sleep, the first request waits a few seconds while JARVIS starts, and a part that fails to start is simply left off.
- [page:pg_service_cloud_scheduler] [show:title] Last, Cloud Scheduler: Google's alarm clock for internet services.
- [show:plain] It wakes the sleeping server on time: through the morning for your brief and the daily jobs.
- And every few minutes all day, to watch your home laptop and run the helpers' reminders.
- [show:how] Each call must carry a token Google signed for exactly the clock's account and JARVIS's address; a call without one gets a bare refusal.
- [count:{{fact:settings.selfwatch_fail_streak}}] The self-health watch reports a clock job that fails {{fact:settings.selfwatch_fail_streak}} runs in a row, and a brief not made {{fact:settings.selfwatch_brief_grace_min}} minutes after its time.
- [show:example] In the made-up example, your brief is due; Google's clock calls, JARVIS makes it, and Telegram tells you it is ready.
- [show:costs] It costs nothing in rupees, because JARVIS's jobs fit inside Google's small free allowance.
- [show:fails] Without the clock, the brief is still made when you open the console, and nothing of yours ever goes to Cloud Scheduler.
- That is the Delivery chapter: every change tested before it ships, and every backup proven before you need it.
