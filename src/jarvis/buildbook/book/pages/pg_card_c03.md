---
page: pg_card_c03
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
sources:
  "src/jarvis/cli.py": "fe0bb250afc25bfa"
---
## In plain words
The terminal client lets someone talk to JARVIS from a computer's command line, with no browser and no server running. It is mainly a tool for building and testing: a line goes in, the brain answers, the next line follows. The same command is also how the server that the web console talks to is started (`src/jarvis/cli.py:main`).

## Example (made up)
Late one evening Arjun, who looks after the code, wants to try a change to the brain before it goes live. He types jarvis chat --stream and asks "What is on my list for tomorrow?". The answer appears word by word as it arrives. He types /new for a clean conversation, starts again with --brain gemini to compare the two answers, and leaves with /quit. Without --stream, each answer ends with a small line such as "412 tok · ≈ ₹0.18 · 950 ms".

## How it works
`main` reads the command: "chat" opens a conversation in the terminal, and "serve" starts the HTTP API on the address and port given (`src/jarvis/cli.py`). For a chat, `_repl` loads the settings, refuses a setup that isn't safe outside development, and sets up logging with `log_level` and `log_json`. It builds the same session store, brain register and monthly spending meter as the server, so a chat here counts against the same limit as the console (`src/jarvis/cli.py:_repl`). A brain asked for by name is checked by `_resolve_brain` against the configured brains. Each line typed gets a fresh trace id and goes to the brain as one request, and a blank line is skipped (`src/jarvis/cli.py:_repl`). With streaming on, the words print as they arrive, and the new conversation is looked up in `sessions` so the next line continues it. Without streaming, the whole reply prints, then a line from `reply_meta` with the model, the tokens used, the cost in rupees and the time taken; a model JARVIS has no price for shows "price unknown" there, never a cost of nothing (`src/jarvis/cli.py:_repl`). Typing /new starts a fresh conversation; /quit, /exit or Ctrl-D ends the session and closes the store on the way out (`src/jarvis/cli.py:_repl`).

## What it costs
The client itself costs nothing; each answer is paid like any other message to the chosen brain, and it is counted in the same monthly meter and limit as the console (`src/jarvis/cli.py:_repl`). An answer from a model with no known price is counted there as "price unknown", not as free (`reply_meta`).

## When it fails
When the monthly limit is reached, No-AI mode is on, or the brain returns an error, the client prints a short note in brackets and waits for the next line instead of stopping (`src/jarvis/cli.py:_repl`). A brain name that isn't configured stops it at once with the list of brains that are (`_resolve_brain`). A missing key or an unsafe setting stops it before the first line, with the reason (`src/jarvis/cli.py:_repl`).
