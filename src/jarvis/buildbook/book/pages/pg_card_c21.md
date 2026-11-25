---
page: pg_card_c21
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-people.js": "90b76851b4821be7"
  "src/jarvis/people/INTEGRATION.md": "c39fef88f4a4ff4f"
  "src/jarvis/people/__init__.py": "6954595b224d9038"
  "src/jarvis/people/cache.py": "b84393587bfc93ea"
  "src/jarvis/people/classifier.py": "422f0bbc944a4657"
  "src/jarvis/people/gate.py": "b3ff32f47cbdf982"
  "src/jarvis/people/guard.py": "0d49d81d06d1c2d9"
  "src/jarvis/people/model.py": "333739d39b55c9bb"
  "src/jarvis/people/models.py": "c8de04ca2a7f4547"
  "src/jarvis/people/offer.py": "adad51547ca21512"
  "src/jarvis/people/offer_card.py": "23b0076a0d96c6d9"
  "src/jarvis/people/privacy.py": "44c44990e5ba04b4"
  "src/jarvis/people/research.py": "73398280e904b794"
  "src/jarvis/people/routes.py": "1a14f337e5c1b049"
  "src/jarvis/people/sources.py": "6c68d609363782f4"
  "src/jarvis/people/tools.py": "e89d3c3a97717b4b"
  "src/jarvis/picture/turnguard.py": "42e7fe96e76ba0ce"
---
## In plain words
People research gives you a short, sourced profile of a public figure, or of someone you are meeting for work, from public sources only (`src/jarvis/people/research.py`). It is built not to become a tool for snooping on private people: a check must prove a public or professional role before any link comes out, and JARVIS never names a person from a photo (`src/jarvis/people/gate.py`).

## Example (made up)
Before a meeting on Monday you ask JARVIS about Ishaan Varma, "founder of Tealeaf Robotics". JARVIS runs one search, finds the company's own site and a news story naming him as founder, and returns a profile with his company page and a professional profile, each opened only when you press its button. Later you ask "where does she live?" about a neighbour; JARVIS refuses in fixed words before any search is spent. You attach a party photo and ask "who is this?"; JARVIS says it doesn't identify people from pictures.

## How it works
`check_scope` reads your request first, with no AI, and refuses private phrasing such as homes, movements or relationships; tricks like spaced letters, look-alike characters or digits for letters don't hide a word (`src/jarvis/people/guard.py`). One search follows, and `verify` must then find a public figure, by an encyclopaedia page or, with AI on, news on {{fact:src/jarvis/people/gate.py:NEWS_MIN_SITES}} different sites naming a public role, or a work subject tied to the organisation by a page the person didn't write themselves (`src/jarvis/people/gate.py`). With the AI on, `classify` makes one fast, tool-less call that can only refuse, never upgrade, and any error fails closed (`src/jarvis/people/classifier.py`). With the AI off, only the encyclopaedia route verifies (`verify`). Links are then limited by kind: the public set for a public figure, professional ones only for a work subject, never personal social accounts (`profile_platforms`). Everything found is treated as untrusted, fenced before a model reads it, and nothing is written to memory (`PeopleService`). Each profile is a card with its own "Open in browser" button, one tab a press (`src/jarvis/api/static/console-people.js`). On a turn whose message carried a picture, `TurnGuard` accepts only a name you typed in that message; a name read off the picture's own text becomes a "Look up" card you press, and anything else is refused (`src/jarvis/picture/turnguard.py`). Your last research is kept for {{fact:src/jarvis/people/cache.py:TTL_S}} seconds in `people_last`, and a refused name is never stored (`src/jarvis/people/cache.py`). Requests are limited per owner, a burst of {{fact:src/jarvis/people/research.py:RATE_BURST}} at a time (`src/jarvis/people/research.py`).

## What it costs
Each research spends search credits one call at a time, so a refusal costs at most one (`src/jarvis/people/research.py`). With the AI on, it adds up to two small fast-tier calls, the check and an optional summary, metered against your monthly limit as one entry a profile (`src/jarvis/people/model.py`). That entry is made whenever a model was asked, a check that refuses included, so on a brain with no known price it counts as "price unknown", never as ₹0 (`src/jarvis/people/research.py`). Whether a credit is free depends on the web search provider's allowance (`src/jarvis/people/research.py`).

## When it fails
A subject that can't be verified gets a fixed refusal, with no links and nothing opened later (`src/jarvis/people/gate.py`). A search that fails is reported plainly (`SearchFailed`), and too many requests in a short time are told to wait (`RateLimited`). If the classifier errs, the answer is a refusal, never a guess (`src/jarvis/people/classifier.py`). A follow-up is checked together with the request before it, so "what about her home?" can't slip through on its own (`src/jarvis/people/cache.py`).
