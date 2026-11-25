---
page: pg_service_tavily
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/r4_wiring.py": "379192618b74836f"
  "src/jarvis/config.py": "e223e4b9e6e6333b"
  "src/jarvis/web/service.py": "15e1408e1103720f"
  "src/jarvis/web/tavily.py": "c7d6fb49c2d660e0"
---
## In plain words
Tavily is a web search service. When a question needs something from the web, such as today's news or a shop's opening hours, JARVIS sends Tavily the search words and gets back a short list of pages, each with its title and a few lines of text. JARVIS then answers with numbered sources, each a page you may open. When a few lines are not enough, JARVIS asks Tavily to read one whole page and hand back its text (`src/jarvis/web/tavily.py:TavilyProvider`). People research uses the same searches. What goes to Tavily is only the search words and the address of a page to read; a guard refuses a search that would send your personal details.

## Example (made up)
At 7:40 you ask: "What did the city council decide about the new metro line yesterday?" JARVIS sends Tavily the words "city council metro line decision" for the past day. Five results come back. JARVIS asks Tavily to read the top article, then answers in three lines with sources 1 and 2. This month's counter moves from 212 to 214 credits, far from the stop.

## How it works
`build_web_service` builds web search only when `web_configured` finds the setting `web_search_enabled` on and a `tavily_api_key` set; otherwise the web tools are never registered. `TavilyProvider` calls Tavily directly over HTTPS, with the key only in a bearer header, never in a body, a log line or an error (`src/jarvis/web/tavily.py`). A search asks for basic depth with no ready-made answer, no images and no raw pages, and `_time_range` turns "the last few days" into Tavily's day, week, month or year. Each result is checked field by field: at most {{fact:src/jarvis/web/tavily.py:MAX_HITS}} are kept, and an address longer than {{fact:src/jarvis/web/tavily.py:URL_LIMIT}} characters is dropped (`src/jarvis/web/tavily.py:_text`). To read a page, Tavily fetches it itself within {{fact:src/jarvis/web/tavily.py:EXTRACT_TIMEOUT_S}} seconds, so no request to that website leaves your server, and the text is cut at {{fact:src/jarvis/web/tavily.py:MAX_PAGE_CHARS}} characters (`src/jarvis/web/tavily.py:TavilyProvider`). Every call has a deadline of {{fact:src/jarvis/web/tavily.py:DEADLINE_S}} seconds, redirects are not followed, and an answer larger than {{fact:src/jarvis/web/tavily.py:MAX_RESPONSE_BYTES}} bytes is refused (`src/jarvis/web/tavily.py`). `_credits` reads how many credits Tavily says a call used, so the month's count stays true. `WebService` keeps each owner's searches of the last hour (`HOUR_S`). Once a day the scheduler's tick asks Tavily for its own count of the month, which uses no credit, and `_vendor_usage` reads it (`src/jarvis/web/service.py:WebService`). People research is switched on only when this web search exists (`src/jarvis/api/r4_wiring.py:wire_people`).

## What it costs
Nothing in rupees. JARVIS uses only Tavily's free monthly credits: a search and a page read both use credits, JARVIS keeps its own count of the month and stops before the free credits run out, and pay-as-you-go is never used (`src/jarvis/web/service.py:usage_view`). The Vitals board shows the month's count. A search turn makes the brain's reply a little longer, and that is counted with the brain's own cost, not here.

## When it fails
With no key, or with `web_search_enabled` off, the web tools are missing and JARVIS says web search is not set up. When the month's free credits are used up, Tavily answers with its "used up" status, JARVIS says so in one sentence and searches nothing more that month (`_friendly`). A refused key, too many searches at once, a busy or broken Tavily, an answer past the deadline or an unreadable answer each give one plain sentence, never Tavily's own text. A page Tavily fails to read (a sign-in wall, or not text) is reported as not read, and the answer goes on without it.
