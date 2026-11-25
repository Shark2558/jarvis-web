---
page: pg_card_c10
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/memory.py": "b4f86cb6ed2117cc"
  "src/jarvis/api/static/console-memory.js": "b88a7282d9e272d9"
  "src/jarvis/recall/__init__.py": "5207ccd232bffe4f"
  "src/jarvis/recall/errors.py": "c742515ecad7b236"
  "src/jarvis/recall/extract.py": "ddcf3adf4025acf4"
  "src/jarvis/recall/gate.py": "22c95d9fca6cd5d7"
  "src/jarvis/recall/learning.py": "30444b7f3976b22e"
  "src/jarvis/recall/lease.py": "6465b36467b96fb7"
  "src/jarvis/recall/models.py": "b0f629b5a0e5913e"
  "src/jarvis/recall/ops.py": "79c9d026d1f07f36"
  "src/jarvis/recall/pasted.py": "a77b328d6aa5e999"
  "src/jarvis/recall/retrieval.py": "0bc41a8c48d2a64b"
  "src/jarvis/recall/sensitive.py": "fa22d0f5ae61f93e"
  "src/jarvis/recall/service.py": "3e5793cfff79673d"
  "src/jarvis/recall/store.py": "4b6778d0bda49525"
  "src/jarvis/recall/text.py": "87af0afdb69a2657"
  "src/jarvis/recall/tools.py": "97d7793c597b4aa8"
---
## In plain words
Long-term memory is what JARVIS knows about you beyond a single chat: the people, places and preferences you tell it, shown in the Memory panel as "About you" (`src/jarvis/api/static/console-memory.js`). With each message it brings along only the notes that matter, and shows which it used. If you switch learning on, it also picks up new facts from what you type, in the background, and a filter refuses ID numbers, card numbers and passwords whatever their source (`src/jarvis/recall/sensitive.py`).

## Example (made up)
In March you tell JARVIS "remember that Ravi's birthday is 14 June and he hates surprises". In June you ask "what should I get Ravi?". Of your 85 notes, JARVIS sends the 4 about Ravi, and the reply shows a chip, "Used 4 memories". Later you mention in passing that you have moved to the night shift; with learning on, a cheap background call a few minutes later adds that fact. When you type your bank account number, nothing is saved, and the reason names only the kind of data.

## How it works
`MemoryService` does three jobs: recall for each reply, learning after it, and the changes you make in the panel (`src/jarvis/recall/service.py`). Recall first asks `memory_allowed`: a brain that may train on what it sees never gets your notes (`src/jarvis/recall/gate.py`). A small memory, at most {{fact:src/jarvis/recall/models.py:SEND_ALL_UNDER}} facts that fit {{fact:src/jarvis/recall/models.py:FACTS_BLOCK_CAP}} characters, is sent whole; otherwise `select_facts` ranks facts by the words of your message, keywords counting double, lifts pinned, recent and often used ones, and sends at most {{fact:src/jarvis/recall/models.py:MAX_FACTS_PER_TURN}} (`src/jarvis/recall/retrieval.py`). Two facts that disagree are both sent, dated and marked, never quietly merged (`conflict_of`). The notes go in under a heading that calls them data, not instructions (`render_block`). Learning, when on, waits for {{fact:src/jarvis/recall/learning.py:BATCH}} new messages, reads only what you typed yourself, never pasted text, spoken messages or tool results, and makes one fast-tier call (`src/jarvis/recall/learning.py`). It runs under a lease, so two servers never learn the same messages twice; it checks your monthly limit first and only adds or replaces learned facts, never deletes (`src/jarvis/recall/lease.py`). Every write passes `sensitive_reason`, and a learned fact about health, religion, caste, politics or sexuality is dropped (`src/jarvis/recall/sensitive.py`). Facts live in `memory` and `memory_shards`, {{fact:src/jarvis/recall/models.py:SHARD_SIZE}} to a shard, up to {{fact:src/jarvis/recall/models.py:MAX_ACTIVE}} active facts (`src/jarvis/recall/models.py`). The brain's memory tools come from `memory_tools`: saving a fact becomes a card when outside text was in view, and forgetting one always asks you (`src/jarvis/recall/tools.py`). `GET /v1/memory/export` gives you a copy, and `DELETE /v1/memory` is "Forget everything" (`src/jarvis/api/memory.py`).

## What it costs
With learning off, nothing: recall is a database read and a little sorting (`src/jarvis/recall/retrieval.py`). With learning on, each run is one small fast-tier call of at most {{fact:src/jarvis/recall/extract.py:MAX_TOKENS}} tokens out, metered as "memory" against your monthly limit, with a cap on runs a day (`src/jarvis/recall/extract.py`). A run on a model with no known price names that model to the meter, so it is counted as "price unknown", never as ₹0 (`src/jarvis/recall/learning.py`). The notes sent with a reply add at most {{fact:src/jarvis/recall/models.py:FACTS_BLOCK_CAP}} characters of facts to that reply's call (`src/jarvis/recall/models.py`).

## When it fails
A memory outage means a reply without notes, never a failed reply (`src/jarvis/recall/service.py`). At your monthly limit learning is skipped and nothing is counted (`src/jarvis/recall/learning.py`). A run that stops midway is picked up again, and a batch that fails {{fact:src/jarvis/recall/lease.py:MAX_ATTEMPTS}} times is skipped (`src/jarvis/recall/lease.py`). A full memory, sensitive text or an oversized import is refused with a plain reason that never repeats the value (`src/jarvis/recall/errors.py`). A memory record that can't be read is never overwritten; notes are kept until you delete them, as plain JSON in the database rather than sealed with a key of JARVIS's own (`src/jarvis/recall/store.py`).
