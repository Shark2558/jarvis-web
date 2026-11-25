---
page: pg_card_c16
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
sources:
  "src/jarvis/llm/__init__.py": "838b6f0468da343f"
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
  "src/jarvis/llm/tryon.py": "839f8746d75d6c7d"
  "src/jarvis/llm/tryon_gemini.py": "3e233dc06019ff0c"
---
## In plain words
This is the only part of JARVIS that talks to AI companies. Everything else asks for a level of thinking, fast, balanced or strong, never a particular model, so a brain is easy to swap without touching the rest (`src/jarvis/llm/router.py:ModelTier`). It also decides what happens when a brain is busy or out of reach: a smaller model, or the free brain on your laptop (`src/jarvis/llm/router.py`).

## Example (made up)
At 14:30 you ask JARVIS to plan a week of meals. The request asks for the balanced tier. Anthropic is overloaded and answers "busy" three times, so the router tries the fast tier, and your plan arrives a few seconds later. That evening Anthropic has an outage, and its service stops answering JARVIS's server in the cloud. The call times out, so the same kind of question goes to the small brain on your laptop, over its encrypted Tailscale address, and for the next two minutes JARVIS goes straight there before trying Anthropic again.

## How it works
Callers ask `ModelRouter` for a `ModelTier`, and `tiers_for` maps each tier to a model; for Claude today those are {{fact:settings.model_fast}}, {{fact:settings.model_balanced}} and {{fact:settings.model_strong}} (`src/jarvis/llm/router.py`). `build_provider` makes the provider that `llm_backend` names: Anthropic, Gemini, any OpenAI-compatible service, or a mock for tests. `BrainRegistry` holds every brain that has a key, each a `BrainSpec`, so you can pick one per conversation (`src/jarvis/llm/brains.py`). A brain that may train on what it is sent never gets tools or tool output; that follows from its settings and can't be switched on separately (`BrainSpec`). Each provider turns the shared message format of `src/jarvis/llm/base.py` into its vendor's own and back. Claude calls wait at most {{fact:settings.llm_timeout_s}} seconds and retry {{fact:settings.llm_max_retries}} times (`src/jarvis/llm/factory.py`). A busy error moves the call one tier down, strong to balanced to fast (`ModelRouter`). An unreachable cloud, meaning no connection, a timeout or a server error, sends the call to the laptop brain when it is ready; for the next {{fact:src/jarvis/llm/fallback.py:BREAKER_S}} seconds calls go straight there, then the cloud is tried again (`Breaker`). With No-AI mode on, every call is refused with `BrainOff`, and the switch is re-read at most every {{fact:src/jarvis/llm/router.py:GUARD_REFRESH_S}} seconds (`src/jarvis/llm/router.py`). `cost_usd` prices each call from its tokens (`src/jarvis/llm/pricing.py`). `src/jarvis/llm/tryon.py` is the port for the wardrobe's try-on pictures, unused while `tryon_pictures` is {{fact:settings.tryon_pictures}}.

## What it costs
Each call is charged by its vendor per token; `cost_usd` turns the tokens into dollars from a price table, and the billing meter shows them in rupees (`src/jarvis/llm/pricing.py`). Gemini's free tier is priced at nothing, but Google may use what you type, so that brain gets no tools (`src/jarvis/llm/brains.py`); with `gemini_paid_tier` on, Gemini is priced from Google's paid prices, read on a stated day from Google's own price list (`use_gemini_paid_tier`, `src/jarvis/llm/pricing.py`). A model missing from the price table is metered at nothing and logged as a warning, and billing then counts it as "price unknown" at the `dearest` known price, never as free (`price_unknown`). Claude's history caching, `cache_history` ({{fact:settings.cache_history}}), lowers the price of history it has already read (`src/jarvis/llm/factory.py`).

## When it fails
A vendor's own error text never reaches you: errors are sorted into busy, unreachable, refused key, no credit or declined, each with fixed words (`src/jarvis/llm/base.py`). A rate limit or a refused key never goes to the laptop; no credit goes straight to the free laptop brain when it is set up (`src/jarvis/llm/router.py`). If the cloud and the laptop both fail, `FallbackFailed` says so in plain words. If the No-AI switch can't be read, no model is called (`ModelRouter`). The router remembers how the last call ended, so the console's brain light shows it without a call (`BrainHealth`).
