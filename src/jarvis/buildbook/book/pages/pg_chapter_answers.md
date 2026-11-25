---
page: pg_chapter_answers
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
sources:
  "evals/r14/noai.py": "69b6e5dadd2c7717"
  "evals/r14/offer.py": "34a9f67c5791bdb9"
  "scripts/skill_coverage.py": "6f090841daa37782"
  "src/jarvis/api/offline.py": "5b454d255da1ba33"
  "src/jarvis/api/r14_status.py": "efb328e795d63aa9"
  "src/jarvis/api/skills.py": "8266dcf3731b82b2"
  "src/jarvis/api/static/console-offline.js": "395fb571a35cce6f"
  "src/jarvis/billing/ledger.py": "db2a8ce52cc2c908"
  "src/jarvis/core/brain.py": "976861b3c96f073a"
  "src/jarvis/core/brain_types.py": "fa3d9df28ac632ba"
  "src/jarvis/core/channel.py": "0c46ee25a780e41b"
  "src/jarvis/core/finish.py": "29da647acc47e7e7"
  "src/jarvis/core/fixed_lines.py": "f7628651dff9b5b5"
  "src/jarvis/core/guardrails.py": "906dc22e6f5c1678"
  "src/jarvis/core/models.py": "b81cc65f474ac5d8"
  "src/jarvis/core/persona.py": "d6e0eef9c4ed2d2a"
  "src/jarvis/core/prompts.py": "d609029d91d73e5b"
  "src/jarvis/core/rounds.py": "f6a5203fab82caa5"
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
  "src/jarvis/llm/pricing.py": "a2d1278419157236"
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
  "src/jarvis/tools/calendar_gather.py": "bb5900cc1d2b3878"
  "src/jarvis/tools/external.py": "fcc26ec8b93fd836"
  "src/jarvis/tools/provenance.py": "5618fb13067e690f"
  "src/jarvis/tools/spoken.py": "1c3db255f7c0e5f8"
  "src/jarvis/tools/taint.py": "fffb2835e3b38bed"
---
## In plain words
This chapter follows one message from the moment you send it to the reply you read or hear. On the way JARVIS gathers the conversation so far and what it remembers about you, chooses which tools the model may see, asks a model at the level of effort the job needs, lets it act only through the tool gateway, and checks each step against your rules and your monthly limit. The module pages on the brain, approvals, memory, voice and costs each tell one part of this journey in detail; this chapter is the whole road.

## Example (made up)
At 18:10 Sanjay writes on Telegram: "Did the electricity bill mail come? Add paying it to my to-dos for Saturday." JARVIS reads his recent mail. That mail is someone else's words, so the to-do no longer happens at once: it becomes a card. The reply on his phone says the bill came and reads the amount as "an amount", because mail sent to a phone is masked. At 19:30, home at his laptop, he approves the card in the console and the to-do appears for Saturday.

## How it works
A message arrives from the console, voice or Telegram, and `src/jarvis/core/channel.py` notes the surface, so that surface's rules apply. `guard_input` caps its size and strips control characters, and `build_window` gathers the recent conversation. `Persona` adds the system prompt: JARVIS's manner and its hard rules, among them that outside text is data, never orders (`src/jarvis/core/prompts.py`). `SkillOffer` narrows the tools to the groups the message needs, as `SkillRegister` files them from `src/jarvis/skills/catalogue.json`. `ModelRouter` sends the call to a tier, drops a tier on a passing error, and hands it to the laptop's `FallbackBrain` when the cloud is unreachable. When the model asks for a tool, `Rounds` passes the call to the gateway. Mail, web pages and documents come back fenced by `wrap_external`, and `tainted_round` then turns every write into a card. A result made only of your own words, such as an event you created alone, is trusted by `src/jarvis/tools/provenance.py`, so looking it up and changing it needs no card. On a voice or Telegram turn, `src/jarvis/tools/spoken.py` masks links, addresses, amounts and long numbers from mail before they are spoken or sent. When the model is done, `reply_text` gives its words, or a fixed, honest line chosen by code if it wrote none, and the turn is saved (`src/jarvis/core/saving.py`). Every model call is admitted against your monthly limit first and metered afterwards, and `src/jarvis/billing/ledger.py` counts where the tokens went. With the AI switched off, fixed phrase routers answer through the same gateway instead (`src/jarvis/offline/r14_part.py`); one of them prepares a home-service request from a template and never books or pays (`src/jarvis/helpers/house/service_request.py`).

## What it costs
An answer costs the model's tokens: nothing on Gemini's free tier, the laptop brain or with the AI off; otherwise Claude's price per million tokens, or Google's paid-tier price once the setting `gemini_paid_tier` says your Gemini key has billing, counted in rupees against your monthly limit (`src/jarvis/llm/pricing.py`). A model with no known price is marked "price unknown", never ₹0, and the limit counts it at the dearest price JARVIS knows (`dearest`). Offering only the tools a message needs keeps each call smaller (`src/jarvis/skills/offer.py`).

## When it fails
A brain failure becomes a short, plain message, never the vendor's words (`src/jarvis/llm/base.py`). When trust is unclear, the call asks you first (`src/jarvis/tools/taint.py`). If a turn clashes with another window, your message is not stored and no model is called, but after an approved action the save never fails, so nothing runs twice (`src/jarvis/core/saving.py`). An answer cut short is asked for once more, and its half-written tool calls never run (`src/jarvis/core/finish.py`).
