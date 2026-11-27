---
page: pg_service_redis
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/selfcheck_wiring.py": "1acfee7d6ea08779"
  "src/jarvis/config.py": "965b3658da16361e"
  "src/jarvis/memory/__init__.py": "b201fcff1ddce9e7"
---
## In plain words
Redis is a small, fast storage program that keeps data in memory. JARVIS uses it only when it runs on a developer's own machine with Docker, to remember the conversations of that run. Your live JARVIS on the internet does not use Redis at all: it keeps conversations in Firestore. So nothing of yours goes to Redis in normal use, and there is no Redis company or account involved; it is a free program on the same machine.

## Example (made up)
A developer starts JARVIS on a laptop with Docker for a test evening. Redis starts beside it. They chat for twenty minutes, stop JARVIS, start it again, and the conversation is still in the list. They leave it alone; a day after the last message, Redis forgets it.

## How it works
`build_session_store` picks where conversations live from the setting `session_backend` (`src/jarvis/memory/__init__.py`). With "memory", the default for tests, everything stays inside the running program; with "redis" it opens Redis at the address in `redis_url`; with "firestore", which the live server uses, it uses Firestore (`src/jarvis/config.py:SessionBackend`). In Redis each conversation is one record that expires after `session_ttl_s` ({{fact:settings.session_ttl_s}} seconds) without activity, and a per-person list keeps them in order of last use (`build_session_store`). Only conversations go there in that mode; approvals and the audit trail stay inside the running program (`src/jarvis/config.py:SessionBackend`). The systems check pings Redis only when `session_backend` is "redis", so the live server never checks for it (`src/jarvis/api/selfcheck_wiring.py:health_probes`).

## What it costs
Nothing in rupees: Redis is free, open-source software that runs on the developer's own machine, and the live server doesn't use it.

## When it fails
If Redis is not running in a Docker run, conversations can't be saved or loaded and the systems check reports Redis as not answering (`src/jarvis/api/selfcheck_wiring.py`). A conversation left idle longer than its expiry is gone for good in that mode. None of this touches the live JARVIS.
