---
page: pg_card_c09
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/core/window.py": "06c365d979fdc3cf"
  "src/jarvis/memory/__init__.py": "b201fcff1ddce9e7"
  "src/jarvis/memory/base.py": "48e575d4b911376e"
  "src/jarvis/memory/inmemory.py": "dfae2b5defa1a31a"
  "src/jarvis/memory/redis_store.py": "5bdc88555c4ed3df"
  "src/jarvis/storage/sessions.py": "c9a8ec12966d54db"
---
## In plain words
Conversations are JARVIS's short-term memory: each chat is kept whole, and with every new message the brain is sent the latest part of it, so it follows what you said a minute ago. Your conversations survive a restart and stay until you delete them (`src/jarvis/storage/sessions.py`). The rolling window keeps each message's size, and so its bill, in check (`src/jarvis/core/window.py`).

## Example (made up)
Over three evenings you plan a family trip to Hampi in one conversation: trains, a homestay, what to pack for Priya. By the third evening it has 90 turns. When you ask "and what time does our train leave?", the brain still gets the recent talk about trains, while the first evening's packing list is no longer sent. It is still there in History. You type on your tablet at the same moment as on your laptop; the tablet's message is refused with a request to send it again, and nothing is stored twice.

## How it works
Every conversation is kept whole, in order, by a store with one shared shape, `SessionStore` (`src/jarvis/memory/base.py`). `build_session_store` picks it from `session_backend`: `InMemorySessionStore` for tests, `RedisSessionStore` at `redis_url` for local Docker runs, or `DocSessionStore` in Firestore for the live system (`src/jarvis/memory/__init__.py`). In Firestore each conversation is a header plus one record per turn, with the header written last, so a reader never sees a header pointing at turns not yet written (`src/jarvis/storage/sessions.py`). Before each message `build_window` picks the most recent turns that fit both a turn limit and a character limit, and every part of a turn counts, tool results included (`src/jarvis/core/window.py`). When the window would pass a limit, `window_start` moves its start forward until it is down to a share of {{fact:src/jarvis/core/window.py:DROP_TO}} of that limit, so the start stays put for several replies and the provider's cache keeps working. Tool results older than the last {{fact:src/jarvis/core/window.py:KEEP_FULL_ROUNDS}} rounds are cut to {{fact:settings.history_tool_result_chars}} characters when sent (`shorten`), and what is stored is never changed. JARVIS's own fixed lines for an empty answer are left out, so the brain never learns to copy them (`_filler`). A reply made with the AI off from tool results, which may quote other people's words, is sent inside a fence that marks it as outside content (`_quotes_tools`). `_well_formed` makes the window start with your message, joins accidental repeats and drops a tool result cut off from its call.

## What it costs
Nothing beyond the document store's free allowance: a conversation already in memory costs one read, and a save writes only its new turns (`src/jarvis/storage/sessions.py`). Local runs keep Redis in Docker on the same machine (`src/jarvis/memory/redis_store.py`). The window's words are paid as part of each brain call, and its limits keep that bill bounded (`build_window`).

## When it fails
If another window added to the same conversation first, your message is not stored, no brain is called, and you are asked to send it again (`src/jarvis/memory/base.py:MessageNotSaved`). A clash on a later save loses only the reply, never your message (`SessionConflict`). A conversation header that can't be read is logged and left out of the list (`DocSessionStore`). In Redis or in memory, a conversation idle for {{fact:settings.session_ttl_s}} seconds expires (`session_ttl_s`); in Firestore it is kept until you delete it (`src/jarvis/storage/sessions.py`).
