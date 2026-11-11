Version v0.4.0 · 1 Nov 2026 · Release Slice 4 · Status: Superseded by the build log · Owner: 🛠 Mark I

# Phase 2 · Slice 4 — Brain selector (switch Claude / Gemini / OpenAI-compatible from the console) + Gemini latency fix

Status: DONE · 2026-11-01 · 112 tests · ECC loop · fresh-context review: 1 HIGH + 4 MEDIUM found and fixed

## Owner ask
"Will I be able to switch between Claude and Gemini or any other free local API like Ollama
whenever I want from the front end?" → yes: a dropdown in the console header, per session.

## Incident folded in
Live Gemini replies took ~61 s. Logs show the request to `gemini-3.8-flash` (BALANCED) running
to the 60 s client timeout, then degrading to `gemini-3.5-flash-lite`, which answered in ~1 s.
No WARNING-level log survived (Cloud Run log read returned blank), so the exact cause is
unconfirmed. Fix: default `llm_timeout_s` 60 → 20 (a stuck model costs seconds, not a
minute), and the deploy script now exports `JARVIS_LLM_TIMEOUT_S=20`.

## Design
1. **BrainRegistry** (`jarvis/llm/brains.py`). A *brain* = provider + tier map + two flags:
   `trains_on_content` (vendor may use prompts to improve products) and `tools_allowed`
   (**derived, not configurable: `not trains_on_content`** — a training brain never sees
   email/calendar/tool output; this is enforced in code in `Brain`, not by a banner).
   Brains are built from settings at startup: `anthropic` (if key), `gemini` (if key),
   `custom` = one OpenAI-compatible slot (if base URL), `mock` (dev/tests).
   `JARVIS_LLM_BACKEND` remains the **default** brain and must be configured.
2. **OpenAI-compatible provider** (`jarvis/llm/openai_compat_provider.py`, httpx, no SDK):
   `POST {base_url}/chat/completions`, optional bearer key (Ollama/LM Studio need none),
   tool calling in the OpenAI `tools`/`tool_calls`/`role:tool` shape, SSE streaming
   (`data: [DONE]`). Covers Groq, OpenRouter, Ollama, LM Studio, vLLM.
   `JARVIS_OPENAI_COMPAT_TRAINS_ON_CONTENT` defaults **true** (private by default: assume the
   vendor trains unless the owner says otherwise). `max_tokens` is used (widest support);
   `Effort` is not mapped (no portable field).
3. **Per-session brain.** `ChatRequest.brain` (optional). Resolution order: request →
   `session.metadata["brain"]` → registry default. The choice is persisted on the session so
   follow-up turns stay on the same brain; an unknown id → 404 `not_found`.
   Switching mid-session is allowed, with a **history cutoff**: switching INTO a training brain
   records `session.metadata["brain_cutoff"]`; that brain only ever sees turns after it, and never
   a turn carrying tool blocks (review finding: replaying history would have leaked earlier tool
   output). Approval narration is skipped (deterministic reply) on a training brain.
4. **API.** `GET /v1/brains` → `[{id,label,default,trains_on_content,tools_allowed,warning,models}]`.
   `ChatResponse.brain` reports what answered. `/console/config` unchanged (default brain).
5. **Console.** `<select id="brainSel">` in the header, filled from `/v1/brains`; the amber
   banner follows the *selected* brain; the choice is remembered in `localStorage`; the
   selection is sent with every `/v1/chat`.
6. **Deploy script.** Asks for each brain's key separately (Enter = skip), the default brain,
   and the optional OpenAI-compatible slot; env/secret lists are built dynamically.
7. **Ollama on the owner's laptop** is out of scope for Cloud Run (unreachable without a tunnel).
   The `custom` slot makes it a config change once a tunnel exists.

## Security notes
- Brain id from the request is validated against the registry; model names and base URLs come
  only from config. Keys never leave `SecretStr`; error text has the key redacted.
- Tool specs are withheld from training brains by `Brain._tools_for()`; the provider-level
  drop in `GeminiProvider` remains as defence in depth.
- `/v1/brains` requires auth (reveals configured vendors + model ids).

## Tests (first)
- registry: built from settings; default must exist; tools_allowed derived; unknown id.
- openai-compat: request shape (bearer, system messages, tools), response (text, tool_calls,
  usage, finish reasons), tool-block mapping, errors + key redaction, stream `[DONE]`.
- brain: request brain wins, sticks to the session, default otherwise; training brain gets no
  tools even with a gateway; unknown brain → LookupError.
- API: `/v1/brains` lists; chat with `brain` echoes `brain`; 404 on unknown.
- config: timeout default 20.

## Exit criteria
pytest green, ruff clean, fresh-context review, deploy script re-run offers multiple brains,
owner switches brain from the dropdown on the live site.

## Review outcome (fresh context)
- HIGH fixed: history replay leaked tool output to training brains → cutoff + block filter (`Brain._window_for`), tests added.
- MEDIUM fixed: deploy `optional_secret` ran in a subshell (gcloud failure silently dropped a brain); stale custom key could be sent to a different host (host label + refusal); non-JSON 200 crashed instead of `LLMError`; base URL validated (https unless private host).
- LOW fixed: orphan session on unknown brain id; Gemini flatten no longer reveals tool names; `tiers_for` moved to router.py (no lazy import); default-brain prompt accepts "claude".
- Open (LOW): `jarvis chat` CLI has no `--brain`; `JARVIS_GEMINI_PAID_TIER` not offered by the script.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v0.4.0 | 11 Nov 2026 | R6.1 | Version line and change log added in R6.1 | 🛠 Mark XIII |
