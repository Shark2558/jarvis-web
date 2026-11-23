---
page: pg_card_c13
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/core/__init__.py": "cbb70bfb5ae294a7"
  "src/jarvis/core/approve_all.py": "59f16ea07d5207c5"
  "src/jarvis/core/brain.py": "5c361ba3e1e3e346"
  "src/jarvis/core/brain_decisions.py": "c952c68c5f5ad1d6"
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
  "src/jarvis/tools/calendar_gather.py": "bb5900cc1d2b3878"
---
## In plain words
The brain core loop is the heart of JARVIS: everything between you sending a message and the reply appearing. It loads the conversation, checks your monthly limit, asks the brain, lets it use tools through the safety gateway, records the cost and saves the turn (`src/jarvis/core/brain.py`). Anything that sends, pays or can't be undone stops at an approval card and waits for you (`src/jarvis/core/brain_decisions.py`).

## Example (made up)
At 18:20 you type "Put sports day, the parents' meeting and both dentist visits in my calendar". JARVIS checks that this month's spend is under your limit, stores your message, then asks the brain. In one round the brain asks for four separate calendar entries. As that is more than three, JARVIS gathers them onto one approval card that lists all four. The reply explains the card, and the turn cost about ₹0.40. You tap Approve; the four events are added, and JARVIS confirms it in one short sentence.

## How it works
Each message is handled by `Brain`, one message at a time per conversation, so two windows never tangle one turn (`src/jarvis/core/brain.py`). `guard_input` checks your words, at most {{fact:settings.max_input_chars}} characters, before anything is stored (`src/jarvis/core/guardrails.py`). With No-AI mode on, the message is answered without a brain; otherwise the monthly limit is checked before each paid call, and your message is saved before the brain is asked (`src/jarvis/core/saving.py:save_owner_message`). The brain gets the recent conversation from `build_window`, at most {{fact:settings.session_max_turns}} turns and {{fact:settings.session_max_chars}} characters, with your long-term notes and the persona's prompt (`src/jarvis/core/brain.py`). A brain that may train on what it sees gets no tools and no turns made from tool results (`Brain`). The brain answers or asks for tools; each call goes through the gateway, and each round is saved as it ends (`src/jarvis/core/rounds.py`). After {{fact:settings.tool_max_rounds}} rounds it is told to stop and sum up (`tool_max_rounds`). More than {{fact:src/jarvis/tools/calendar_gather.py:MANY}} single calendar entries in one round become one batch card (`gathered`). A turn that works with tools or files may write {{fact:settings.work_output_tokens}} tokens, a plain reply {{fact:settings.max_output_tokens}} (`output_cap`). An answer cut off by that cap is asked for again ({{fact:settings.empty_reply_retries}} retry a message), and its half-written tool calls never run (`src/jarvis/core/finish.py`). An answer with no words becomes a fixed, honest line chosen by code from what happened (`no_words`). Approve runs the waiting action and saves it before the brain narrates (`src/jarvis/core/brain_decisions.py`); Approve all does the same for up to {{fact:src/jarvis/core/approve_all.py:MAX_IDS}} cards that can be undone (`src/jarvis/core/approve_all.py`).

## What it costs
The loop itself is free; each call it makes to a paid brain is charged at that brain's token prices and added to the month's meter after the call (`src/jarvis/core/brain.py`). Tool rounds, the round-limit summary, an approval's narration and a retry are each a separate call, so a turn with tools costs more than a plain reply (`src/jarvis/core/finish.py`). No-AI mode spends nothing, and the limit never refuses it (`Brain`).

## When it fails
At your monthly limit the message is refused before it is stored, and no paid call is made (`src/jarvis/core/brain.py`). A brain error is logged with the conversation's id, and no reply is stored (`Brain`). If another window changed the conversation first, your message isn't stored and you are asked to send it again (`src/jarvis/core/saving.py`). Once a tool has changed something, saves never fail the turn, so nothing is done twice; if it still can't be recorded, tools stop and the reply says so (`src/jarvis/core/rounds.py`). A card that changed since you saw it is withdrawn and offered again, and nothing runs (`src/jarvis/core/brain_decisions.py`).
