---
page: pg_service_frankfurter
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/backup/part.py": "acc12e13dbcb26b4"
  "src/jarvis/billing/fx.py": "a1f636e96ac588a7"
  "src/jarvis/billing/service.py": "f8cd9507563514e1"
  "src/jarvis/config.py": "965b3658da16361e"
  "src/jarvis/wardrobe/catalog/part.py": "107e069a8eb76134"
  "src/jarvis/wardrobe/seeme/make.py": "5f40b732edadfa8a"
  "src/jarvis/wardrobe/seeme/part.py": "414e788c2a14b47d"
---
## In plain words
Frankfurter is a free service that publishes daily currency exchange rates, with no account and no key. JARVIS asks it once a day for one number: how many rupees a US dollar is worth. Anthropic and Google bill in dollars, while you think in rupees, so JARVIS uses that number to show every cost in rupees and to keep track of your monthly limit. Nothing about you goes to Frankfurter: the request is the same for everybody and carries no name or account. Every rupee figure is an estimate, because your bank converts at its own rate.

## Example (made up)
At 9:00 you open the Costs panel. The first reply of the day already started JARVIS's daily rate check in the background, and Frankfurter answered with 95.80 rupees to the dollar for that day. This month's Claude use of 4.10 dollars shows as about ₹392.78, marked as an estimate, with the rate and its date beside it.

## How it works
`FxRates` asks Frankfurter's one fixed address at most once a day, with an overall deadline of {{fact:src/jarvis/billing/fx.py:FETCH_TIMEOUT_S}} seconds and no retries (`src/jarvis/billing/fx.py`). `parse_rate` reads only the documented places in the answer and accepts a rate only if it is a real number between {{fact:src/jarvis/billing/fx.py:RATE_MIN}} and {{fact:src/jarvis/billing/fx.py:RATE_MAX}} rupees. A good rate is kept in memory and in the database, so a fresh start of the server reads one record instead of calling out again (`FxRates`). A reply never waits for the rate: `FxRates` answers at once with what it knows and starts the day's check in the background. `Billing` prices each metered call in rupees at the rate of that moment, and the Costs panel waits briefly for the day's check so it shows the newest rate (`src/jarvis/billing/service.py`). With `usd_inr_live` off, `fx_client` makes no connection at all and JARVIS uses only the setting `usd_inr_rate` ({{fact:settings.usd_inr_rate}}). The backup restore drill and the "See it on me" try-on pictures use the same rate for their rupee estimates and caps (`src/jarvis/backup/part.py`, `src/jarvis/wardrobe/seeme/part.py`).

## What it costs
Nothing in rupees: Frankfurter is free and needs no key, and JARVIS calls it at most once a day.

## When it fails
If Frankfurter doesn't answer in time, answers with an error or sends a strange number, JARVIS keeps the last good rate; if it never had one, it uses {{fact:src/jarvis/billing/fx.py:DEFAULT_RATE}} rupees to the dollar from the setting `usd_inr_rate` (`src/jarvis/billing/fx.py:FxRates`). It tries again the next day. The panel says where the rate came from: Frankfurter today, the stored rate, or the default (`src/jarvis/billing/service.py:RateView`). Nothing else fails: a rate problem never stops a reply.
