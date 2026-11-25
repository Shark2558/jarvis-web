---
page: pg_card_c68
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "evals/r14/noai.py": "69b6e5dadd2c7717"
  "evals/r14/offer.py": "34a9f67c5791bdb9"
  "scripts/skill_coverage.py": "6f090841daa37782"
  "src/jarvis/api/r14_status.py": "efb328e795d63aa9"
  "src/jarvis/api/skills.py": "8266dcf3731b82b2"
  "src/jarvis/billing/ledger.py": "db2a8ce52cc2c908"
  "src/jarvis/core/brain.py": "e418eb8e4df90505"
  "src/jarvis/core/prompts.py": "d609029d91d73e5b"
  "src/jarvis/core/window.py": "06c365d979fdc3cf"
  "src/jarvis/helpers/house/service_request.py": "94e882c398af35c0"
  "src/jarvis/llm/anthropic_provider.py": "60484f5c3cd11faf"
  "src/jarvis/llm/base.py": "8904b3d0d806dc4a"
  "src/jarvis/llm/factory.py": "bc538ec75083020d"
  "src/jarvis/offline/phrases_r14.py": "54b514aeebeee23e"
  "src/jarvis/offline/r14_part.py": "6d70ec07cf642990"
  "src/jarvis/offline/said.py": "571a7157094332b5"
  "src/jarvis/skills/__init__.py": "e183f17eb3bde99b"
  "src/jarvis/skills/catalogue.json": "5d199a221efb71a8"
  "src/jarvis/skills/ids.py": "5978ff2b3a2b549e"
  "src/jarvis/skills/offer.py": "7d55ef5bbc813fac"
  "src/jarvis/skills/open_tool.py": "86b05e4f2e426f2d"
  "src/jarvis/skills/part.py": "f67e6ee91d243b74"
  "src/jarvis/skills/ports.py": "3164c55711111ac1"
  "src/jarvis/skills/registry.py": "5ce48b8dadfcbcb1"
---
## In plain words
JARVIS has a great many tools, from reminders to the home alarm. Sending all of them to the brain with every message is slow and costs money, so this part files each tool under one of JARVIS's skills and offers the brain only the ones your message needs (`src/jarvis/skills/offer.py`). When the brain needs another skill, it opens it in one step (`src/jarvis/skills/open_tool.py`). A ledger counts where the AI money goes, part by part, and with the AI off more plain phrases still get a real answer (`src/jarvis/offline/phrases_r14.py`).

## Example (made up)
At 08:10 you write "add milk and eggs to my grocery list and check when the AC was last serviced". The brain is offered the groceries and home-upkeep groups plus a small core, about 12 tools instead of 140. Later you ask something its words don't cover; the brain opens the right skill and answers one step later. In Vitals, "Where the AI money goes" splits this month's ₹310 into the rule book, the tool list, the conversation and the replies. With the AI off, "book a plumber for tomorrow morning" still gets a prepared request and the booking site's address, never a booking.

## How it works
`src/jarvis/skills/catalogue.json` lists the skills, their groups of tools and the words, English and common Hinglish, that point to each group. `SkillRegister` files every tool by its name with its risk, permission rows and Telegram class, and its check reports a tool filed nowhere or twice, or a pattern that matches nothing (`src/jarvis/skills/registry.py`). With `tool_offer` set to {{fact:settings.tool_offer}}, `SkillOffer` builds each turn's set once: the groups your words name, the groups of tools used in the last {{fact:src/jarvis/skills/offer.py:HISTORY_TURNS}} turns, the previous turn's set while it is under {{fact:settings.tool_offer_sticky_s}} seconds old and holds at most {{fact:src/jarvis/skills/offer.py:STICKY_MAX_TOOLS}} tools, a small core, and any tool a replayed call names (`src/jarvis/skills/offer.py`). `skills_open_tool` lets the brain open one more skill, whose tools it holds from its next step. The offer only narrows what the brain sees; every call still passes the gateway and its rules (`SkillOffer`). The persona tells the brain to open a skill before it says something isn't connected (`src/jarvis/core/prompts.py`). Claude calls with tools get a second cache point on the last message, so a reply's later rounds reuse what was read (`src/jarvis/llm/anthropic_provider.py`). `TokenLedgerStore` counts each chat reply's model calls per day: calls, tokens, characters by part, tools offered and cost by part, never a word of what was said, kept {{fact:src/jarvis/billing/ledger.py:LEDGER_DAYS}} days in `token_ledger` (`src/jarvis/billing/ledger.py`). `GET /v1/costs/ledger` and `GET /v1/skills` show them, at most {{fact:src/jarvis/api/r14_status.py:READS_PER_MINUTE}} reads a minute (`src/jarvis/api/skills.py`). In No-AI mode the anchored phrases of `src/jarvis/offline/phrases_r14.py` answer whole messages, such as your grocery list or home status, with one tool call each, and `src/jarvis/offline/said.py` says the result in words. `service_request` writes a home-service request from a fixed template and gives the booking site's address as text; it never books or pays (`src/jarvis/helpers/house/service_request.py`).

## What it costs
Nothing to run beyond one small ledger write to the document store per model call (`src/jarvis/billing/ledger.py`). Offering fewer tools sends fewer words with each message, so each reply costs less; the size of that saving is for the ledger to measure, and any figure before then is Unverified (`src/jarvis/skills/offer.py`). The ledger counts chat replies only, not memory, the brief or the helpers, so the billed total is higher than its sum (`TokenLedgerStore`).

## When it fails
If the catalogue can't be read, the part is left out and the brain is offered every tool, as before (`src/jarvis/skills/part.py`). If building the offer fails, every tool is sent, and a failed ledger write is logged while the reply goes on (`src/jarvis/skills/ports.py:BrainSlots`). A tool the offer missed costs one extra step through `skills_open_tool`. With `tool_offer` set to "all", every tool is offered again, and a brain that trains on content still gets none (`src/jarvis/skills/offer.py`).
