---
page: pg_service_openai_compatible
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/config.py": "3d154bdd78268162"
  "src/jarvis/llm/brains.py": "a1fa670cdd1f62ae"
  "src/jarvis/llm/router.py": "c72db7b28cbba849"
---
## In plain words
Many AI services speak the same "OpenAI-style" language: hosted ones such as Groq or OpenRouter, and programs you run yourself such as Ollama or LM Studio. JARVIS keeps one slot for any one of them, shown in the console as its own brain next to Claude and Gemini, under the name you give it (`openai_compat_label`, {{fact:settings.openai_compat_label}} by default). It is a spare brain for chat. Private by default: unless you say the vendor does not learn from prompts, JARVIS assumes it does, and then this brain gets no tools and none of your personal data (`openai_compat_trains_on_content`).

## Example (made up)
You sign up for a free hosted service, put its address and a model name into the settings and call the slot "Quick". After the next deploy the brain list shows Claude, Gemini (free) and Quick. You ask Quick to rewrite a birthday message in a warmer tone; it answers in two seconds. It shows the training warning, and when you ask it to put the party in your calendar, it has no calendar tool to do so.

## How it works
`BrainRegistry` adds the slot only when both `openai_compat_base_url` and `openai_compat_model_balanced` are set, using `openai_compat_api_key` when there is one, since local servers have none (`src/jarvis/llm/brains.py`). The address must start with https, except for a private address such as your laptop on the home network, so a key is never sent in clear text to a remote server (`src/jarvis/config.py:_is_private_host`). A Tailscale name, one ending in ts.net, is not private here: from the cloud it reaches Tailscale's public relays, so it always needs https (`src/jarvis/config.py:_is_private_host`). `tiers_for` gives every tier the balanced model unless `openai_compat_model_fast` or `openai_compat_model_strong` names another (`src/jarvis/llm/router.py`). `BrainSpec` reads `openai_compat_trains_on_content` ({{fact:settings.openai_compat_trains_on_content}} by default): while it is on, the brain is marked as training and gets no tools and a warning in the console (`src/jarvis/llm/brains.py:BrainSpec`). Turned off, the slot is trusted like Claude and receives tools (`BrainSpec`). The slot shares the timeout `llm_timeout_s` ({{fact:settings.llm_timeout_s}} seconds) with the other brains. `ModelRouter` treats it like any brain: busy means a lower tier, unreachable means your laptop's brain when ready (`src/jarvis/llm/router.py:ModelRouter`). When `llm_backend` makes it the default brain, the server refuses to start without the address and the model (`src/jarvis/config.py:Settings`).

## What it costs
That depends entirely on the vendor you plug in. A program on your own machine costs nothing, and many hosted vendors have free plans. JARVIS has no price list for these models, so Costs shows their replies apart as "price unknown", with their tokens, never as nothing spent; the vendor's own page shows the real bill. Under a monthly limit JARVIS counts those replies at the dearest price it knows, so this brain stops at the limit like a paid one.

## When it fails
Left empty, the slot simply does not appear. An address that uses plain http to a remote host or to a Tailscale name stops the server at start-up with a plain message that asks for https (`src/jarvis/config.py:Settings`). If it is the default brain and the address or model is missing, the server refuses to start (`src/jarvis/llm/brains.py:BrainRegistry`). A busy or unreachable vendor drops a tier, or hands the reply to your laptop's brain when one is ready (`src/jarvis/llm/router.py:ModelRouter`).
