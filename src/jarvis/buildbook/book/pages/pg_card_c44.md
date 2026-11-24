---
page: pg_card_c44
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/quota/__init__.py": "493f43b4a282cfb3"
  "src/jarvis/quota/counter.py": "80db2ef65a8d1c4f"
  "src/jarvis/quota/ledger.py": "389439829a569c8c"
---
## In plain words
Google gives every cloud project a free monthly allowance of Maps searches and routes, and a free daily allowance of YouTube look-ups. This part is JARVIS's tally of that free use. It counts every call before it is made and stops at {{fact:src/jarvis/quota/ledger.py:STOP_PERCENT}} per cent of the free amount, so Maps and YouTube never turn into a bill. When a stop is reached, JARVIS tells you plainly and says when it starts again.

## Example (made up)
It is the 26th and you have asked for a lot of two-wheeler routes this month. The ledger shows the month's two-wheeler counter at its stop, so when you ask "how long to the station by bike?" JARVIS answers "Maps two-wheeler routes are paused: this month's 900 free two-wheeler routes are used up. They start again next month." A car route still works, because it has its own counter.

## How it works
`QuotaLedger` keeps one counter for each kind of Google call and each period, shared by the whole deployment, in `api_quota` (`src/jarvis/quota/ledger.py`).
Each kind is a `Sku`: Maps searches, car, two-wheeler and walking routes are counted by the month, and YouTube searches and look-ups by the day, all in Pacific time, as Google bills and resets them.
`skus_for` picks the free amounts from Google's global or Indian price list; the global list is the default, so a wrong guess only stops early.
Before a call, `take` reserves a unit in one transaction, so two calls never both take the last one (`src/jarvis/quota/counter.py`).
A `Reservation` is given back only when Google clearly never got the call, and when Google itself says the quota is gone, the period is marked used up for good (`QuotaLedger`).
`counted` refuses a stored count that is not a whole number of zero or more: the counter is then unreadable and nothing is called, never silently reset (`src/jarvis/quota/counter.py`).
Bookkeeping after a call, like a give-back, never fails the call itself; any problem is only logged (`quietly`).
`stops_answered` turns a stop into a plain answer for the brain, "paused" or "unreadable", rather than an error (`src/jarvis/quota/ledger.py`).
`HourlyCounter` adds a per-person hourly limit on top, counting over {{fact:src/jarvis/quota/ledger.py:HOUR_S}} seconds, and Vitals reads the counts to show them (`src/jarvis/quota/ledger.py`).

## What it costs
Nothing: its whole job is keeping Maps and YouTube at no rupees by stopping at {{fact:src/jarvis/quota/ledger.py:STOP_PERCENT}} per cent of the free allowance (`QuotaLedger`). It keeps only the counters (`api_quota`).

## When it fails
At a stop the tools answer "paused" with the day or month they start again (`QuotaReached`). A counter that can't be read stops the call rather than risking paid use, with "JARVIS can't read" the count and nothing sent to Google (`unreadable_message`). The counter starts at zero on the first deploy even if the same Google project was used elsewhere that month, so the deploy script warns when other projects share the billing account (`src/jarvis/quota/ledger.py`).
