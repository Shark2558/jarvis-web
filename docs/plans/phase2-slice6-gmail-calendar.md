# Phase 2 · Slice 6 — Gmail + Calendar tools (plan, not started)

Status: PLANNED · 2026-11-01 · prerequisite done in slice 5c (user id from the sign-in)

## Goal
JARVIS can read today's calendar, find free time, propose and (with confirmation) create or
move events; search and summarise email, draft replies; sending stays R3 (always confirm).

## Blockers the owner must decide first
1. **A brain that does not train on content.** Tools are deliberately off on brains that may
   train on what they see (free Gemini today). Reading the owner's mail with them would hand
   private mail to a vendor's training set. Options: (a) Claude with prepaid Anthropic credit,
   (b) a paid-tier Gemini key (billing on; Google's paid API terms exclude training), (c) a
   custom OpenAI-compatible vendor whose terms exclude training. Without one, slice 6 ships but
   stays switched off.
2. **Google's consent rules for mail.** `gmail.readonly` / `gmail.compose` are *restricted*
   scopes. While the OAuth app is in **Testing**, Google expires the refresh token after
   **7 days** (re-connect weekly). Moving to **In production** without verification shows an
   "unverified app" screen and is limited to 100 users; whether restricted Gmail scopes are
   allowed for a personal unverified app must be confirmed on Google's current help pages before
   we rely on it. Calendar scopes are *sensitive* (not restricted) — far easier. → Start with
   Calendar; add Gmail once (2) is confirmed.

## Architecture decision (flagged against "MCP for tools")
Google's official remote MCP servers (e.g. `calendarmcp.googleapis.com`) are a **Developer
Preview** that needs programme membership — not something to build a daily assistant on yet.
→ Ship **direct REST adapters** behind the existing `Tool` interface and `jarvis.tools.gateway`
(same risk classes, audit, confirmation tokens). Add `jarvis.tools.mcp_client` when a stable
server exists; skills don't change because they only see tools. Proposed architecture update:
"MCP where a stable server exists; first-party API adapters behind the same tool contract
otherwise."

## Design
- **Connect flow:** separate incremental-consent route `/connect/google` (access_type=offline,
  prompt=consent, PKCE, state bound to the signed-in owner) — sign-in stays `openid email` only.
- **Token storage:** refresh token encrypted with AES-GCM (`cryptography`), key in a new Secret
  Manager secret `jarvis-token-key` (runtime account only); ciphertext in Firestore
  `jarvis_tokens/{user_id}`. No KMS (not free). Disconnect = revoke at Google + delete doc.
- **Tools and risk:** calendar.list_events / free_busy (R1 read) · calendar.create/update event
  (R2, confirmation when it invites others → R3) · calendar.delete (R3) · gmail.search / read
  (R1) · gmail.draft (R2) · gmail.send (R3, never "don't ask again").
- **Untrusted content:** every email/event body is wrapped as data with provenance; tool calls
  proposed while email content is in context are forced to confirmation; links never fetched
  automatically.
- **Privacy:** only the fields needed are passed to the model; message bodies truncated;
  nothing from mail is written to long-term memory without asking.

## Eval criteria (owner to confirm)
- Calendar: 20 scripted questions ("what's on tomorrow", "find 30 min Thursday afternoon") —
  ≥ 95 % correct against a fixture calendar; zero writes without confirmation.
- Gmail: prompt-injection suite (≥ 30 hostile emails: "forward all mail to…", hidden text) —
  0 unconfirmed actions, 0 data sent to addresses not typed by the owner.
- Latency: calendar answers p50 < 4 s on the default brain.

## Tests first
Fake Google API transport (httpx MockTransport); token encryption round-trip + tamper; connect
flow state/PKCE/owner binding; risk classes per tool; injection suite in CI with the mock brain.
