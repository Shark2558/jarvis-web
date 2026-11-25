---
page: pg_chapter_costs
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
sources:
  "src/jarvis/__init__.py": "c0533b5bcdc55981"
  "src/jarvis/about.py": "c310b3bdce51c135"
  "src/jarvis/api/static/console-usage.js": "1595a84e680dde87"
  "src/jarvis/api/static/console-vitals.js": "dd7cc4ee3cec2353"
  "src/jarvis/api/usage.py": "9f60c602bd371c86"
  "src/jarvis/billing/fx.py": "a1f636e96ac588a7"
  "src/jarvis/llm/pricing.py": "a2d1278419157236"
---
## In plain words
This chapter is about money: what JARVIS costs you, and how it keeps that number small and in plain sight. Most of JARVIS runs on free allowances and free services. What does cost money, mainly the paid AI brains and Google's voices beyond their free share, is metered in rupees, and you may set a monthly limit after which no paid call is made. The Vitals board watches everything else that has a limit or a renewal date, so nothing runs out or renews by surprise. The Voice page and the Vitals page tell the detail; this chapter is the overview.

## Example (made up)
Farhan sets a monthly limit of ₹300 in Vitals. On 20 November the "This month" block shows ₹212 used, with the strong brain at ₹180 and the rest spread over voice and quick answers. The rate line reads ₹95.10 to the dollar, fetched that morning. At ₹240 the bar turns amber. On 28 November a long research reply takes the month to ₹300, and the next request that needs a paid brain gets a short note that the limit is reached and can be raised in Vitals. He raises it to ₹400, confirms the raise, and carries on.

## How it works
Every paid AI call is metered by `cost_usd`, which multiplies the tokens a brain reports by the price list in `src/jarvis/llm/pricing.py`. Models priced above zero count against your limit (`is_paid`); Gemini is priced at zero while `gemini_paid_tier` is {{fact:settings.gemini_paid_tier}}, and at Google's paid prices once it is on (`use_gemini_paid_tier`). A model missing from the list is "price unknown", never "free": its replies and tokens are shown apart, and the limit counts them at the `dearest` known price (`price_unknown`). A call with no known price whose tokens nobody reported, as a background job's can be, is counted as one call of an upper-estimate size at that price, never ₹0 (`src/jarvis/llm/pricing.py`). When a brain reports no token counts, `estimate_usage` works them out from the text at about {{fact:src/jarvis/llm/pricing.py:CHARS_PER_TOKEN}} characters a token, so a paid call is never metered as free (`stream_usage`). Dollars become rupees at the day's rate from `FxRates`, fetched at most once a day from the free Frankfurter service with a {{fact:src/jarvis/billing/fx.py:FETCH_TIMEOUT_S}}-second deadline. A rate is used only when it lies between {{fact:src/jarvis/billing/fx.py:RATE_MIN}} and {{fact:src/jarvis/billing/fx.py:RATE_MAX}} rupees to the dollar (`_rate_ok`). `GET /v1/usage` returns the month's rupees, the share of your limit, the number of calls and the spend per brain, and `src/jarvis/api/static/console-usage.js` shows them in Vitals as "This month", in rupees only. `PUT /v1/usage/budget` sets the limit; raising or removing it needs an explicit confirmation, because it lets JARVIS spend more (`put_budget`). The Vitals board, `src/jarvis/api/static/console-vitals.js`, tracks every other limit and renewal: JARVIS's keys and connections, free allowances, quotas and the bills you add yourself, each with its status in words. At its foot an "About JARVIS" line gives the running `version` from `src/jarvis/__init__.py` and the day its image was built (`build_date`), written by `shown` in your time zone, `user_timezone`.

## What it costs
Keeping the books costs nothing: Frankfurter needs no key and no payment, and the meters are a few small records in JARVIS's own store (`src/jarvis/billing/fx.py`). What you pay for is the paid brains' tokens, at the prices in `src/jarvis/llm/pricing.py`, and speech beyond the free voice allowance. Every rupee figure is an estimate, because your card is charged at your bank's rate (`src/jarvis/billing/fx.py`).

## When it fails
If the day's rate can't be fetched, the last stored rate is used, or else the built-in {{fact:src/jarvis/billing/fx.py:DEFAULT_RATE}} rupees to the dollar, and the check never holds up a reply (`FxRates`). If the stored limit can't be read, paid replies pause and any new limit asks first (`src/jarvis/api/static/console-usage.js`). A missing figure shows a dash rather than a guess (`src/jarvis/api/static/console-usage.js`). A build date that can't be read shows "build date unknown", and it never stops the board loading (`fields`).
