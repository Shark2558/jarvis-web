---
page: pg_card_c54
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-usage.js": "1595a84e680dde87"
  "src/jarvis/api/usage.py": "9f60c602bd371c86"
  "src/jarvis/billing/__init__.py": "39064ef052748a9f"
  "src/jarvis/billing/budget.py": "2a6c2da568569f75"
  "src/jarvis/billing/fx.py": "a1f636e96ac588a7"
  "src/jarvis/billing/ledger.py": "db2a8ce52cc2c908"
  "src/jarvis/billing/meter.py": "25554dab6a58d209"
  "src/jarvis/billing/service.py": "9778ed2f38fc3f08"
  "src/jarvis/billing/spend.py": "fad90ef7371200bc"
  "src/jarvis/llm/pricing.py": "2def5f9e481da2f1"
---
## In plain words
Paid AI replies and paid cloud voice cost real money, billed in US dollars. This part turns every such call into rupees, shows you what this month has cost, brain by brain, and holds to the monthly limit you set in Vitals. Once the limit is reached, JARVIS makes no more paid calls that month; free brains keep answering. Raising or removing the limit always asks you to confirm.

## Example (made up)
You set a limit of ₹500 a month. By the 20th the Vitals bar reads ₹410 of ₹500 and turns amber. On the 27th a long research question takes the month to ₹503, because the check happens before each call and one reply can go a little over. Your next question gets "This month's limit of ₹500 is used up (₹503 spent). Raise it in Vitals, or switch to the free brain."

## How it works
Before every call to a paid brain, or to one whose price is unknown, `Billing` checks this month's rupees against your limit and refuses with `BudgetReached` when it is used up; free brains are never blocked (`metered_brain`).
After each reply, `cost_usd` prices the tokens from the model's price table, and `Billing` adds the cost in rupees to the month in one transaction, never failing the reply over a write (`src/jarvis/llm/pricing.py`).
A reply from a model with no price is never counted as nothing: `UsageMeter` keeps it apart as "price unknown" with its tokens, and the limit counts those at the `dearest` known price, an upper estimate (`price_unknown`).
`FxRates` fetches the day's dollar-to-rupee rate from Frankfurter once a day with a {{fact:src/jarvis/billing/fx.py:FETCH_TIMEOUT_S}}-second limit, accepts only a rate between {{fact:src/jarvis/billing/fx.py:RATE_MIN}} and {{fact:src/jarvis/billing/fx.py:RATE_MAX}}, and keeps it in `fx` so a restart reads it back (`src/jarvis/billing/fx.py`).
Your limit is a whole number of rupees from {{fact:src/jarvis/billing/budget.py:LIMIT_MIN}} to {{fact:src/jarvis/billing/budget.py:LIMIT_MAX}} in `budget`; lowering it is immediate, while raising or removing it needs your confirmation (`needs_confirm`).
`UsageMeter` keeps the month's rupees and call counts in `usage`, plus the deployment's free cloud-voice allowance, which is free up to its amount and priced above it (`src/jarvis/billing/meter.py`).
For a priced action that is not a brain call, such as a try-on picture, `ensure_spend_allowed` checks the same limit with tax added by `with_tax` (`src/jarvis/billing/spend.py`).
`TokenLedgerStore` records, per day for {{fact:src/jarvis/billing/ledger.py:LEDGER_DAYS}} days, counts only: calls, tokens and characters by part, never a word of a message (`src/jarvis/billing/ledger.py`).
Vitals shows it all in rupees, never a dollar sign, with a "Price unknown" line when some replies have no price, from `GET /v1/usage`, and saves the limit through `PUT /v1/usage/budget` (`src/jarvis/api/static/console-usage.js`).

## What it costs
The meter itself costs nothing: the daily rate comes from Frankfurter, which needs no key and makes no charge (`FxRates`). It keeps your limit, the month's totals, the day's rate and the token ledger (`budget`, `usage`, `fx`, `token_ledger`).

## When it fails
If the day's rate can't be fetched, the last stored rate is used, or else the built-in one of ₹{{fact:src/jarvis/billing/fx.py:DEFAULT_RATE}} (`FxRates`). If your limit or the month's total can't be read, or holds a broken value, no paid call is made and Vitals says so; a damaged total never reads as nothing spent (`BudgetUnavailable`). A failed meter write is logged and the reply still goes out (`Billing`).
