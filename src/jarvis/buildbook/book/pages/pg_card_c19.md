---
page: pg_card_c19
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/brief.py": "384e3c31e281a98b"
  "src/jarvis/api/static/console-brief-sections.js": "e11e4eafe28cf198"
  "src/jarvis/api/static/console-brief.js": "11856702dcd2439c"
  "src/jarvis/brief/__init__.py": "527f4ea4e9d78524"
  "src/jarvis/brief/collect.py": "0c7fe20d706cd207"
  "src/jarvis/brief/deliver.py": "b961684f4ad40dc0"
  "src/jarvis/brief/deliveries.py": "efe59bc1f029c5aa"
  "src/jarvis/brief/family_day.py": "4989e49a7d023c4f"
  "src/jarvis/brief/home_overnight.py": "5f5e4b1de238e306"
  "src/jarvis/brief/models.py": "18f095d54c93f9da"
  "src/jarvis/brief/render.py": "32f1bf4099646d9b"
  "src/jarvis/brief/schedule.py": "52274a0ab4a042b2"
  "src/jarvis/brief/service.py": "8ff72b107aa66083"
  "src/jarvis/brief/store.py": "ac59a270b5aa2e10"
  "src/jarvis/brief/summarize.py": "36b5ba1bfc41dfe9"
  "src/jarvis/brief/vault_due.py": "36119edb9f207fa5"
---
## In plain words
Each morning, at the time you pick, JARVIS lays out your day on one screen: today's calendar and free time, unread mail by kind, parcels on the way, family calendars, documents about to expire, what the home camera noted overnight, your sleep and the Vitals that need you. Every fact is written by code, so it is the same every time (`src/jarvis/brief/render.py`). An optional "what matters today" summary by AI is off until you agree to its cost. The brief can also be put in your own Gmail inbox as a message to yourself (`src/jarvis/brief/deliver.py`).

## Example (made up)
Farhan sets his brief for 07:00. At 07:00 JARVIS finds three meetings, a free block from 13:00 to 15:30, 14 unread mails (5 from people, 9 promotions, 2 bank messages withheld), a parcel out for delivery and his car insurance expiring in 21 days. He has the AI summary on, so two lines sit under the facts, marked as AI: "Your 10:00 review moved to 11:00. Renew the car insurance this week." A copy lands in his Gmail inbox at 07:01.

## How it works
The scheduler's tick asks `BriefService` whether each owner's brief is due, and `is_due` decides from the time you set, your time zone and today's record, catching up a brief missed at its time.
A claim in one transaction (`BriefStore`) makes sure only one worker builds today's brief; it is kept in `briefs` beside your `brief_settings`.
`Collector` makes fixed read-only Google calls for the calendar, the inbox and your to-dos, reads at most {{fact:src/jarvis/brief/collect.py:MAX_READS}} messages, withholds codes and bank messages, and reads mail only when your "Search and read email" row says Allow (`src/jarvis/brief/collect.py`).
Parcels come from `DeliveriesBrief`, documents due from the vault through `src/jarvis/brief/vault_due.py` (within {{fact:src/jarvis/brief/vault_due.py:WITHIN_DAYS}} days, or expired in the last {{fact:src/jarvis/brief/vault_due.py:EXPIRED_DAYS}}), and the night's camera events from `HomeOvernightBrief`.
`render_text` turns it all into plain text, shows other people's words in quotes and disarms any link in them, so a hostile subject line can't borrow JARVIS's name (`defang`).
The optional summary is one fast AI call through `Summarizer`, only to a brain that does not train on your content, with no tools, at most {{fact:src/jarvis/brief/summarize.py:MAX_LINES}} short lines, and links and addresses stripped.
`InboxDelivery` puts the brief into your own mailbox at most once a day; nothing leaves your account (`src/jarvis/brief/deliver.py`).
JARVIS makes at most {{fact:src/jarvis/brief/service.py:MAX_GENERATIONS}} briefs a day, after which it asks you to try tomorrow (`BriefLimitReached`), and the console draws the brief in `src/jarvis/api/static/console-brief.js`.

## What it costs
The facts cost nothing: they are fixed Google reads within free limits and no AI (`src/jarvis/brief/collect.py`). The optional summary is one small AI call per brief, capped at {{fact:src/jarvis/brief/summarize.py:MAX_TOKENS}} tokens of output, and it first checks your monthly limit and is added to the month's meter after (`src/jarvis/brief/service.py`). Like any AI call, it shows on the month's meter in Costs (`BriefService`).

## When it fails
One failing section, such as Gmail being down, marks just that section unavailable and the rest still shows (`src/jarvis/brief/collect.py`). The next ticks make the brief again, up to {{fact:src/jarvis/brief/schedule.py:MAX_SECTION_RETRIES}} times, but never for "not connected", which only you can fix (`src/jarvis/brief/schedule.py`). At the monthly limit the summary is left out with a note and the facts stay complete (`BriefService`). The inbox copy is never retried after an error, so you never get two (`src/jarvis/brief/deliver.py`).
