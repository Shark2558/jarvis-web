---
page: pg_service_gemini
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/config.py": "e223e4b9e6e6333b"
  "src/jarvis/llm/brains.py": "a1fa670cdd1f62ae"
  "src/jarvis/llm/gemini_provider.py": "46855ef23dd8aabb"
  "src/jarvis/llm/router.py": "c72db7b28cbba849"
  "src/jarvis/vitals/own.py": "cd127fbc1ca087c6"
---
## In plain words
Gemini is Google's AI model, and JARVIS offers it as a second, free brain for plain chat. You pick it in the console when you want an answer that costs nothing. On Google's free tier, Google may use what you type to improve its products, so JARVIS gives this brain no tools and no personal data: no calendar, no e-mail, no memory facts, no attached files (`src/jarvis/llm/brains.py:BrainSpec`). The console shows a warning on it saying exactly that. What goes to Google is only the conversation you type to it, with any earlier tool results taken out.

## Example (made up)
On a Sunday afternoon you switch to the Gemini (free) brain and ask: "Give me three ideas for a rainy-day game with two children." Gemini answers in about four seconds with a treasure hunt, a paper-plane contest and a story chain. Nothing is added to the month's AI spend. Later you ask it to check tomorrow's meetings; this brain has no calendar tool, so it has no way to look; you switch back to Claude for that.

## How it works
`BrainRegistry` offers Gemini only when `gemini_api_key` is set; its label reads "Gemini (free)" unless `gemini_paid_tier` is on (`src/jarvis/llm/brains.py`). `BrainSpec` marks it as a brain that trains on content, and such a brain is never allowed tools; `GeminiProvider` drops any tools it is offered all the same (`src/jarvis/llm/gemini_provider.py`). Earlier turns that held a tool exchange are flattened to plain text, with the exchange replaced by a "withheld" note, so neither tool names nor tool output reach Google (`src/jarvis/llm/gemini_provider.py:GeminiProvider`). `GeminiProvider` calls Google's public REST service directly, with the key in a request header, and no vendor library is used. Skills still ask for a tier: `tiers_for` maps fast to `gemini_model_fast` ({{fact:settings.gemini_model_fast}}) and balanced and strong to `gemini_model_balanced` and `gemini_model_strong` ({{fact:settings.gemini_model_balanced}}). Gemini thinks before it answers and its thinking shares the output budget, so the request asks for the larger of {{fact:src/jarvis/llm/gemini_provider.py:MIN_OUTPUT_TOKENS}} tokens and {{fact:src/jarvis/llm/gemini_provider.py:OUTPUT_PAD}} times the reply's own cap (`GeminiProvider`). `ModelRouter` treats it like any brain: busy means a lower tier, unreachable means the laptop when ready (`src/jarvis/llm/router.py`). The Vitals board shows a "Gemini (free AI) key" line from the router's record of the last call (`src/jarvis/vitals/own.py:Own`).

## What it costs
Nothing in rupees on the free tier: JARVIS uses Google's free allowance, and its own rupee counter prices these models at nothing. With `gemini_paid_tier` on, Google bills the key's project, and JARVIS prices each reply from Google's published paid prices, counts it in rupees in Costs and holds it to your monthly limit (`src/jarvis/llm/brains.py`). The free tier's limits are Google's own and change from time to time.

## When it fails
With no key, Gemini is not in the brain list. A refused key gives a fixed "refused" message and Vitals shows "was refused" in red. When the free limit is reached, Google answers "too many requests"; JARVIS tries a lower tier, and Vitals says it "has reached its free limit for now" (`src/jarvis/vitals/own.py`). A timeout or a broken connection is reported in fixed words that never carry the key (`_unreachable`). An empty or blocked answer is reported as no answer.
