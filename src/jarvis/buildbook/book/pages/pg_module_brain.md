---
page: pg_module_brain
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "evals/r14/noai.py": "69b6e5dadd2c7717"
  "evals/r14/offer.py": "34a9f67c5791bdb9"
  "scripts/skill_coverage.py": "6f090841daa37782"
  "src/jarvis/api/offline.py": "5b454d255da1ba33"
  "src/jarvis/api/r14_status.py": "efb328e795d63aa9"
  "src/jarvis/api/skills.py": "8266dcf3731b82b2"
  "src/jarvis/api/static/console-offline.js": "395fb571a35cce6f"
  "src/jarvis/billing/ledger.py": "db2a8ce52cc2c908"
  "src/jarvis/core/brain.py": "e418eb8e4df90505"
  "src/jarvis/core/brain_types.py": "fa3d9df28ac632ba"
  "src/jarvis/core/channel.py": "0c46ee25a780e41b"
  "src/jarvis/core/finish.py": "76f1255343c6e042"
  "src/jarvis/core/fixed_lines.py": "f7628651dff9b5b5"
  "src/jarvis/core/guardrails.py": "906dc22e6f5c1678"
  "src/jarvis/core/models.py": "deff434beeb1cc0d"
  "src/jarvis/core/persona.py": "d6e0eef9c4ed2d2a"
  "src/jarvis/core/prompts.py": "d609029d91d73e5b"
  "src/jarvis/core/rounds.py": "4e7f24f94d989836"
  "src/jarvis/core/saving.py": "c92f295af587766d"
  "src/jarvis/core/window.py": "06c365d979fdc3cf"
  "src/jarvis/helpers/house/service_request.py": "94e882c398af35c0"
  "src/jarvis/llm/anthropic_provider.py": "60484f5c3cd11faf"
  "src/jarvis/llm/base.py": "8904b3d0d806dc4a"
  "src/jarvis/llm/brains.py": "a1fa670cdd1f62ae"
  "src/jarvis/llm/factory.py": "bc538ec75083020d"
  "src/jarvis/llm/fallback.py": "785b07e24d85a2ff"
  "src/jarvis/llm/gemini_provider.py": "46855ef23dd8aabb"
  "src/jarvis/llm/local_provider.py": "aa111fafc89f4a46"
  "src/jarvis/llm/mock_provider.py": "e846975cd22e657f"
  "src/jarvis/llm/openai_compat_provider.py": "4d0317770f7ba34f"
  "src/jarvis/llm/pricing.py": "2def5f9e481da2f1"
  "src/jarvis/llm/router.py": "c72db7b28cbba849"
  "src/jarvis/offline/phrases_r14.py": "54b514aeebeee23e"
  "src/jarvis/offline/r14_part.py": "6d70ec07cf642990"
  "src/jarvis/offline/said.py": "571a7157094332b5"
  "src/jarvis/people/routes.py": "1a14f337e5c1b049"
  "src/jarvis/skills/catalogue.json": "5d199a221efb71a8"
  "src/jarvis/skills/ids.py": "5978ff2b3a2b549e"
  "src/jarvis/skills/offer.py": "7d55ef5bbc813fac"
  "src/jarvis/skills/open_tool.py": "86b05e4f2e426f2d"
  "src/jarvis/skills/part.py": "f67e6ee91d243b74"
  "src/jarvis/skills/ports.py": "3164c55711111ac1"
  "src/jarvis/skills/registry.py": "5ce48b8dadfcbcb1"
  "src/jarvis/storage/sessions.py": "c9a8ec12966d54db"
  "src/jarvis/tools/calendar_gather.py": "bb5900cc1d2b3878"
  "src/jarvis/tools/external.py": "fcc26ec8b93fd836"
  "src/jarvis/tools/provenance.py": "5618fb13067e690f"
  "src/jarvis/tools/spoken.py": "1c3db255f7c0e5f8"
  "src/jarvis/tools/taint.py": "fffb2835e3b38bed"
---
## In plain words
This module is the thinking part of JARVIS. The core loop takes your message, gathers the recent conversation and what JARVIS remembers about you, asks an AI model for a reply, lets it use tools through the gateway, and saves the turn. The brain router picks the model: every part of JARVIS asks for a level of effort, fast, balanced or strong, never a particular product, so models are easy to swap. If Claude is out of reach, a small model on your laptop answers instead, and a No-AI switch makes JARVIS answer from fixed rules with no model at all.

## Example (made up)
At 8:05 Vikram types "What's on tomorrow? Add gym at 7 am." JARVIS loads his last 12 turns, adds 2 facts from memory, and offers the brain only the calendar and reminder tools. The balanced brain looks up tomorrow, proposes the gym event as a card, and replies in about 3 seconds for ₹0.42. One evening Claude's service is down: the same kind of question goes to the small model on his laptop, which answers with a note that it is in offline mode, and any change it wants becomes a one-tap card.

## How it works
`Brain` handles one message at a time per conversation: it loads the conversation from `DocSessionStore`, checks the text with `guard_input`, and builds the recent window with `build_window`. The window holds at most {{fact:settings.session_max_turns}} turns and about {{fact:settings.session_max_chars}} characters, cutting older tool results to {{fact:settings.history_tool_result_chars}} characters (`src/jarvis/core/window.py`). `Persona` picks the system prompt for your wit level, addressing you as {{fact:settings.user_honorific}} (`src/jarvis/core/prompts.py`). Every model call is checked against your monthly limit first, and its cost is added afterwards (`src/jarvis/core/brain.py`). `SkillOffer` sends the model only the tools this message needs: groups your words name, tools used in recent turns and a small core, and a skill opens on request (`src/jarvis/skills/open_tool.py`). Tools run through the gateway for at most {{fact:settings.tool_max_rounds}} rounds (`Rounds`). `tainted_round` marks a round in which other people's text reached the model, and `wrap_external` fences that text as data, never orders. An answer cut short is asked for once more, and an empty one becomes a fixed line chosen by code (`reply_text`). `ModelRouter` maps tiers to models, by default {{fact:settings.model_fast}}, {{fact:settings.model_balanced}} and {{fact:settings.model_strong}}. A passing error retries {{fact:settings.llm_max_retries}} times, with a {{fact:settings.llm_timeout_s}}-second timeout, then drops a tier (`src/jarvis/llm/router.py`). An unreachable cloud sends the same call to the laptop through `FallbackBrain`, and the cloud is skipped for {{fact:src/jarvis/llm/fallback.py:BREAKER_S}} seconds after (`Breaker`). `BrainRegistry` lists the brains you pick from: Claude, Gemini's free tier and one OpenAI-compatible slot; a brain that may train on what it reads never receives tools. With `brain_mode` set to No-AI, `src/jarvis/offline/phrases_r14.py` answers whole-message requests such as "what's on my shopping list" through the gateway, and `src/jarvis/offline/said.py` words the result. `TokenLedgerStore` counts each chat call's tokens and cost by part, never a word of text, for {{fact:src/jarvis/billing/ledger.py:LEDGER_DAYS}} days. Only `src/jarvis/llm/` talks to model vendors.

## What it costs
The brain's tokens are JARVIS's main cost: Claude is priced per million tokens and counted in rupees against your monthly limit, while Gemini's free tier, the laptop brain and No-AI mode cost nothing (`src/jarvis/llm/pricing.py`). Keeping the persona and history cached with `cache_history` makes repeated parts of each call cheaper (`src/jarvis/llm/anthropic_provider.py`).

## When it fails
A brain error becomes a short, friendly message, never the vendor's text (`src/jarvis/llm/base.py`). At the monthly limit the reply says so and no paid call is made (`src/jarvis/core/brain.py`). A message that clashes with a change from another window is not stored and no model is called; you send it again (`DocSessionStore`). With the cloud and the laptop both silent you see "Claude can't be reached and your laptop didn't answer." (`FallbackFailed`). A No-AI switch that can't be read counts as No-AI (`src/jarvis/llm/router.py`), and an unreadable skill catalogue means every tool is offered (`src/jarvis/skills/offer.py`).
