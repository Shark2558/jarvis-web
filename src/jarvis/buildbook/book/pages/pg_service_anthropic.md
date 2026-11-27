---
page: pg_service_anthropic
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/config.py": "965b3658da16361e"
  "src/jarvis/llm/brains.py": "a1fa670cdd1f62ae"
  "src/jarvis/llm/factory.py": "bc538ec75083020d"
  "src/jarvis/llm/router.py": "c72db7b28cbba849"
  "src/jarvis/vitals/own.py": "9f8aef630fa0d168"
---
## In plain words
Anthropic makes Claude, JARVIS's main brain. Claude reads your message, writes the reply and decides when a tool is needed, such as your calendar, your e-mail or a web search. It does the small background jobs too: picking out facts to remember, the morning brief's optional summary and the checks in people research. What goes to Anthropic for a reply: the recent conversation, the memory facts that match it and the results of the tools used in that turn. JARVIS treats Claude as a brain that does not learn from your words, which is why it may be given tools and personal data while a brain that may learn from prompts never is (`src/jarvis/llm/brains.py:BrainSpec`). Claude is a paid service.

## Example (made up)
At 6:15 in the evening you type: "Move Friday's dentist visit to 5 pm." JARVIS asks Claude on the balanced tier. Claude asks for the calendar tool, finds the visit and proposes the move; you approve the card. The reply used about 3,000 words' worth of tokens in and 120 out, and the Costs panel adds about ₹1.10 to this month.

## How it works
`BrainRegistry` offers Claude as a brain, labelled "Claude", only when `anthropic_api_key` is set (`src/jarvis/llm/brains.py`). `anthropic_provider` builds the client with that secret, a timeout of `llm_timeout_s` ({{fact:settings.llm_timeout_s}} seconds), `llm_max_retries` ({{fact:settings.llm_max_retries}}) retries and the `cache_history` switch (`src/jarvis/llm/factory.py`). Skills ask for a tier, never a model: `tiers_for` maps fast to `model_fast` ({{fact:settings.model_fast}}), balanced to `model_balanced` ({{fact:settings.model_balanced}}) and strong to `model_strong` ({{fact:settings.model_strong}}). A plain chat reply is at most `max_output_tokens` ({{fact:settings.max_output_tokens}}) tokens; a turn that works with tools or files gets `work_output_tokens` ({{fact:settings.work_output_tokens}}). `ModelRouter` handles trouble: a busy answer on the strong tier is tried again on balanced, then on fast (`src/jarvis/llm/router.py`). An unreachable cloud (no connection, a timeout, a server error) goes to your laptop's brain when one is ready, and so does a "no credit left" answer; a refused key is never retried (`src/jarvis/llm/router.py:ModelRouter`). Before every call `ModelRouter` re-reads the No-AI switch, at most every {{fact:src/jarvis/llm/router.py:GUARD_REFRESH_S}} seconds, and while it is off `BrainOff` stops the call before anything is sent. `ModelRouter` keeps how the last real call ended in `BrainHealth`, and the Vitals board reads that record for its "Claude (paid AI) key" line without making a call (`src/jarvis/vitals/own.py:Own`). When `llm_backend` names Claude as the default brain, `src/jarvis/config.py:Settings` refuses to start the server without the key.

## What it costs
Anthropic bills per token in US dollars from prepaid credit; there is no free allowance. JARVIS prices each call in rupees, at the day's rate, or at {{fact:settings.usd_inr_rate}} to the dollar when that rate is unavailable (`usd_inr_rate`), and counts it against your monthly limit. The fast tier is the cheapest and the strong tier the dearest. Background uses have their own daily caps: at most {{fact:settings.brief_ai_daily_cap}} brief summaries (`brief_ai_daily_cap`) and {{fact:settings.memory_learn_daily_cap}} memory-learning runs (`memory_learn_daily_cap`). In No-AI mode nothing is spent.

## When it fails
With no key, Claude is not offered; if Claude is the default brain, the server refuses to start and says the key is required (`src/jarvis/llm/brains.py:BrainRegistry`). A busy Claude drops a tier, and Vitals shows "is busy right now" in amber. A refused key shows "was refused" in red. When the prepaid credit is used up, Vitals turns red and your laptop's brain answers if you set one up (`src/jarvis/vitals/own.py`). When Anthropic is unreachable and no laptop brain is ready, each lower tier is tried and then the reply fails with a plain message (`src/jarvis/llm/router.py:ModelRouter`). At your monthly limit in rupees, paid calls stop.
