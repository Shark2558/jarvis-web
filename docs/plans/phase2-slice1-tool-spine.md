# Phase 2 · Slice 1 — Tool spine: registry, policy gateway, tool-calling loop

Status: DONE · 2026-11-01 · 49 tests · reviewed (8 findings fixed) · follows ECC loop (plan → test → implement → review → verify)

## Goal
Give the Brain the ability to call tools, with every call passing a deterministic
policy gateway (deny → ask → allow) and landing in an append-only audit log. No real
connectors yet: in-memory calendar/tasks/reminders tools prove the spine end-to-end.

## Out of scope (later slices)
Gmail/Calendar OAuth, MCP client, web search, sandboxed FS, Postgres persistence,
trifecta tracker, saga/plan log, web console.

## Design
```
Brain.chat ─► ToolLoop (≤ N rounds)
               │  router.complete(tools=registry.specs())
               │  for each tool_use → Gateway.execute(call, confirmation_id?)
               │        ├ policy.decide(tool, args) → DENY | ASK | ALLOW
               │        ├ ASK & no token → PendingAction (existing ConfirmationGate) → return awaiting
               │        ├ ALLOW → tool.run(args) → AuditLog.append(...)
               │        └ DENY → AuditLog.append(denied) → tool_result(error)
               └ final text → persist turn
```
- `jarvis/tools/base.py` — `Tool` protocol: name, description, input_schema, risk (ActionRisk), `run(args)`.
- `jarvis/tools/registry.py` — `ToolRegistry`: register, get, `specs()` (vendor-neutral JSON-schema list).
- `jarvis/tools/policy.py` — `Policy`: ordered rules `(tool_pattern, effect, arg_constraints)`; default by risk: R0/R1 ALLOW, R3 ASK; explicit DENY rules win; never a standing ALLOW for R3.
- `jarvis/tools/audit.py` — `AuditLog`: append-only, hash-chained (sha256(prev|json(entry))), `verify()`.
- `jarvis/tools/gateway.py` — `Gateway` composes policy + ConfirmationGate + audit.
- `jarvis/tools/builtin.py` — in-memory `get_calendar`, `list_tasks`, `create_reminder` (R1), `send_message` (R3 stub).
- `jarvis/llm/base.py` — add `ToolSpec`, `ToolCall`, `ToolResult`, `ChatMessage.content: str | list[Block]`; providers map to vendor tool-use format. Mock provider: scripted tool calls.
- `jarvis/core/brain.py` — `ToolLoop` when registry non-empty; cap rounds (default 6); confirmation flow: `ChatRequest.confirmation_id` resumes a pending action.
- API: `POST /v1/approvals/{id}/approve|decline`, `GET /v1/approvals`, `GET /v1/audit`.

## Tests (write first)
- registry: register/duplicate/specs shape.
- policy: default by risk; DENY beats ALLOW; arg constraint (e.g. `to` must be in contacts); R3 standing-allow rejected at construction.
- audit: chain verifies; tampering detected.
- gateway: ALLOW runs tool + audits; ASK without token returns awaiting + pending; ASK with valid token runs; arg drift rejected; DENY never runs tool.
- tool loop (mock provider): one round tool call → result fed back → final text; round cap; R3 pauses loop and reply mentions approval; approve endpoint executes.
- anthropic provider: request carries `tools` and tool_result blocks (MockTransport).

## Exit criteria for this slice
pytest green, ruff clean, mock eval still passes, 0 R3 executions without a token in tests.
