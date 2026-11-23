---
page: pg_card_c20
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-web.js": "249905ef58dc235d"
  "src/jarvis/api/web.py": "ef6843949c281f10"
  "src/jarvis/web/__init__.py": "cadc656ae9ff18c7"
  "src/jarvis/web/allowance.py": "e08529c45d1b8ab1"
  "src/jarvis/web/guard.py": "42839a9306a4adec"
  "src/jarvis/web/ledger.py": "048954a97700d930"
  "src/jarvis/web/ports.py": "b9d470053a26ad09"
  "src/jarvis/web/service.py": "15e1408e1103720f"
  "src/jarvis/web/sources.py": "7f73000400ba119e"
  "src/jarvis/web/tavily.py": "c7d6fb49c2d660e0"
  "src/jarvis/web/tools.py": "c85345589b8eaaa5"
  "src/jarvis/web/vendor_usage.py": "eb0ec459917921fe"
---
## In plain words
When a question needs fresh facts (today's news, a changed timetable, a product's price), JARVIS searches the web and reads pages for you, then answers with small numbered sources under the reply that you tap to check. A guard stops any search that would carry your private details, such as a phone number, an e-mail address or an ID number, to the search company. Web search runs on a free monthly allowance and stops before it runs out, so it never turns into a bill.

## Example (made up)
You ask "Has the Pune metro changed its weekend timings?". JARVIS makes one search, gets five results, reads one page and answers with [1] and [2] beside its sentences; under the reply two chips name the sites, and a tap opens each. Later you ask it to look up your own mobile number online. The guard refuses because the query holds a phone, account or ID number, and nothing is sent anywhere.

## How it works
`web_tools` gives the brain a search and a page read, both passing the tool gateway and audited like any other tool.
Every query first meets `query_problem`, which refuses an e-mail address, a run of {{fact:src/jarvis/web/guard.py:MIN_RUN_DIGITS}} or more digits however they are spaced, and anything the sensitive filter flags, such as card, Aadhaar, PAN or bank numbers; the reason names the kind of data, never the value (`src/jarvis/web/guard.py`).
Once other people's text is in the conversation, a query is held to {{fact:src/jarvis/web/tools.py:TAINTED_QUERY_LIMIT}} characters, so a web page can't smuggle a long secret out inside a search (`src/jarvis/web/tools.py`).
Each of your messages allows at most {{fact:src/jarvis/web/tools.py:MAX_SEARCHES_PER_TURN}} searches and {{fact:src/jarvis/web/tools.py:MAX_READS_PER_TURN}} page reads, and {{fact:src/jarvis/web/tools.py:MAX_SEARCHES_PER_HOUR}} searches an hour in all (`src/jarvis/web/tools.py`).
Before calling out, `WebAllowance` reserves a credit in a transaction, gives it back when nothing was charged, and stops the whole deployment at {{fact:src/jarvis/web/allowance.py:MONTHLY_CREDITS}} credits a month (`web_usage`).
`TavilyProvider` makes the call; results are kept https only, without duplicates, and numbered for the whole conversation (`src/jarvis/web/ledger.py`).
The brain sees each result's number, site, title and snippet, fenced as outside text, never the address itself, and a page read brings back at most {{fact:src/jarvis/web/tools.py:PAGE_TEXT_LIMIT}} characters (`src/jarvis/web/tools.py`).
A page is read only if it was a result in this conversation or a link you typed yourself, so a page saying "now open this address" gets nowhere (`Conversation`).
`cited_sources` turns the numbered marks in the reply into source chips, using only numbers this message's results really showed, and `src/jarvis/api/static/console-web.js` draws them as https links only.
The Vitals line shows this month's count from `GET /v1/web/usage`, and once a day the scheduler asks Tavily for its own count, which may only raise JARVIS's (`VendorCheck`).

## What it costs
No rupees for the searching: JARVIS stops at {{fact:src/jarvis/web/allowance.py:MONTHLY_CREDITS}} credits a month, inside Tavily's free plan, and never uses pay-as-you-go (`src/jarvis/web/allowance.py`). Searches and page reads both use credits. A reply that searched gives the brain more to read, so it costs a little more on your AI bill (C54).

## When it fails
With no Tavily key, or the switch off, the tools are not offered and JARVIS says web search is not set up (`web_configured`). At the month's limit it says "Web search is paused" and does not search (`AllowanceReached`). If the month's counter can't be read, nothing is searched rather than guessing (`AllowanceUnreadable`). When Tavily itself says the credits are gone, the month is closed at once (`CreditsExhausted`), and a failed search or read gives its credit back (`WebAllowance`). A refused query tells the brain to search for the general topic instead (`query_problem`).
