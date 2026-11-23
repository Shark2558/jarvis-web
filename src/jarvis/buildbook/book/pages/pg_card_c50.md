---
page: pg_card_c50
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/logging.py": "ce88f3d3fe3403b8"
---
## In plain words
JARVIS keeps a diary of what its server does, one line for each event, so that when something goes wrong the cause is easy to trace afterwards. Each request carries its own short trace id, and every line written while that request runs carries the same id, so all the lines of one request are easy to find together (`src/jarvis/logging.py`). The diary is for fixing faults: secrets, tokens and the words of your messages are kept out of it by the parts that write to it.

## Example (made up)
At 19:20 Kiran asks JARVIS to add "call the plumber" to her to-dos, and it fails. The request got the trace id 8c41e2d09a7b3f15, and four lines carry it: the request arrived, the to-do tool was called, Google answered with an error, the reply said "couldn't add it". Searching the logs for 8c41e2d09a7b3f15 shows all four lines and the error in one place, without a word of her to-do in them.

## How it works
Every part of JARVIS asks `get_logger` for its logger, so they all write the same way, and the first call sets logging up if nothing has yet (`src/jarvis/logging.py`).
At the start of a request `new_trace_id` makes a fresh random id, or `set_trace_id` keeps the one the caller sent, and `get_trace_id` reads it back for as long as that request runs.
A filter, `_TraceFilter`, adds that id to every line.
With the setting `log_json` on, `_JsonFormatter` writes each event as one JSON line with its time, level, place, trace id and message, plus any extra fields the caller passed and the details of an error.
With it off, `_TextFormatter` writes a plain line for a person to read, with the extra fields after it.
`configure_logging` sets the level it is given (the server passes the setting `log_level`), sends every line to the server's standard output, and quietens the busiest libraries so their routine chatter doesn't bury JARVIS's own lines.

## What it costs
Nothing in JARVIS itself: `configure_logging` sends every line to standard output, where the hosting's own log service collects them. How long that service keeps them, and whether it stays inside its free allowance, is Unverified.

## When it fails
`get_logger` sets logging up the first time it is needed, so a part that logs before start-up has finished still gets a working logger. A value that can't be written as JSON is written as text instead of breaking the line (`_JsonFormatter`). The lines hold only what the calling code passes in, so keeping secrets and message text out of them is each caller's duty, not this file's (`src/jarvis/logging.py`).
