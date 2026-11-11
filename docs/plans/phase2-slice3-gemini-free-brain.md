Version v0.3.0 · 1 Nov 2026 · Release Slice 3 · Status: Superseded by the build log · Owner: 🛠 Mark I

# Phase 2 · Slice 3 — Gemini as a free, swappable brain (chat-only) + friendly LLM errors

Status: DONE · 2026-11-01 · 84 tests · ECC loop · live Gemini API NOT exercised (no key in CI)

## Why
Owner has no Anthropic API credit and wants zero payment. The core is model-agnostic
(`LLMProvider`), so a second provider is the architecture working as designed.

## Facts verified against Google docs (ai.google.dev, pages dated 2026-10-28)
- Free of charge: `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`.
  NOT free: `gemini-4-argon`, `gemini-3.1-pro-preview`.
- **Free plan: "Content used to improve our products" = Yes. Paid plan: No.**
- Free tier applies to projects *without billing*. A key created in the billed JARVIS project
  would be a paid-tier key. → The owner must create the key in a NEW project (AI Studio:
  "Create API key in new project").
- 3.x models think by default; thought tokens count against `maxOutputTokens`.
- RPM/RPD limits are not published in docs (visible in AI Studio) → expect 429s; map to transient.

## Design decisions
1. **Chat-only.** The provider drops `tools` (logs a warning). Reasons: (a) free tier trains on
   content → must never see email/calendar/tool results; (b) Gemini 3 thought-signature
   round-tripping for function calling is not worth building for a test brain.
2. REST via `httpx` (already a dependency), header `x-goog-api-key` (key never in URL/logs),
   `generateContent` + `streamGenerateContent?alt=sse`. No new SDK.
3. Tier mapping: FAST=`gemini-3.5-flash-lite`, BALANCED=STRONG=`gemini-3.8-flash` (no free strong model).
4. Effort → `generationConfig.thinkingConfig.thinkingLevel` (low/medium/high). If Google answers 400
   mentioning "thinking", retry once without `thinkingConfig` (we could not test the live API).
5. `maxOutputTokens` is padded (x4, min 2048) because thinking shares the budget.
6. Cost metered at $0 for free-tier models; `gemini_paid_tier=true` setting flips the privacy banner off.
7. Console shows a visible banner when the active brain trains on content.
8. LLM errors shown to the owner are friendly; raw vendor text stays in server logs only.

## Tests (first)
- request shape: header key, systemInstruction (2 parts), roles user/model, merged same-role turns,
  generationConfig, tools dropped, tool blocks flattened to text.
- response: text from parts (thought parts skipped), usage incl. thoughtsTokenCount, stop reason map.
- errors: 401/403 auth, 429/503 transient, 400 other, blocked prompt, thinking-400 retry.
- stream: SSE chunks yield deltas.
- config/router: backend=gemini picks gemini models, requires key; env parsing.
- API: friendly error body; /console/config exposes brain + privacy warning.

## Exit criteria
pytest green, ruff clean; deploy script offers Claude/Gemini choice; owner can chat on the free brain.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v0.3.0 | 11 Nov 2026 | R6.1 | Version line and change log added in R6.1 | 🛠 Mark XIII |
