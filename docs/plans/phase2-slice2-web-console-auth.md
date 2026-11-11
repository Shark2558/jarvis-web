Version v0.2.0 · 1 Nov 2026 · Release Slice 2 · Status: Superseded by the build log · Owner: 🛠 Mark I

# Phase 2 · Slice 2 — Web console + owner-only Google sign-in + hosting

Status: DONE (pending owner go-live) · 2026-11-01 · 65 tests · security-reviewed (0 critical/high; 2 medium + 2 low fixed) · follows ECC loop

## Owner decision that drove this slice
"It has to be a web app, I should be able to access it from anywhere." → JARVIS is served
as a hosted web page. No desktop install. Therefore sign-in must be strong before go-live.

## Goal
1. A browser console at `/` (chat, pending approvals with Approve/Decline, activity log).
2. Owner-only sign-in with Google (OIDC) + email allowlist; API bearer token kept for CLI/eval.
3. One-click hosting on Render (Blueprint `render.yaml`), Docker image unchanged.

## Deviation from default stack (flagged, deliberate)
Default says Next.js + Tailwind for the frontend. This slice ships a single static HTML/JS
page served by FastAPI instead. Reason: one deployable, one bill, one URL for a non-technical
owner; the console is ~300 lines and has no routing/SSR needs. Next.js remains the plan for
the Phase 6 multi-device app; the API contract (`/v1/*`) is unchanged so nothing is thrown away.

## Design
```
Browser ──GET /──► static console (HTML/JS)        [no auth needed to load shell]
   │  fetch /v1/* with cookie + X-Requested-With: JARVIS
   ▼
require_auth:  bearer token (CLI/eval)  OR  signed session cookie whose email ∈ OWNER_EMAILS
   │                                        └ state-changing + cookie ⇒ CSRF header required
/auth/login ──► Google (authlib, state+nonce) ──► /auth/callback ──► allowlist check ──► cookie
/auth/logout, /auth/me
RateLimiter middleware: token bucket per client IP (auth: 20/min, api: 120/min)
```
- `jarvis/api/auth.py` — `AuthMode {token, google}`, `require_auth`, Google OIDC routes (authlib).
- `jarvis/api/ratelimit.py` — tiny in-memory token bucket middleware (single instance is fine for now).
- `jarvis/api/static/console.html` — the console. Vanilla JS, no build step, escapes all model/tool text.
- `config.py` — `auth_mode`, `google_client_id/secret`, `owner_emails`, `session_secret`,
  `public_base_url`, `cookie_secure`; `require_prod_invariants` enforces google-mode completeness.
- Cookie: HttpOnly, SameSite=Lax, Secure outside dev, 12 h max age, signed (itsdangerous via Starlette SessionMiddleware).
- `render.yaml` — Docker web service, secrets `sync: false`, health check `/health`.

## Security notes
- Allowlist is the authorization boundary; Google only authenticates. Non-listed email ⇒ 403, no cookie, audit-style log line.
- CSRF: cookie-authenticated POST/DELETE without `X-Requested-With: JARVIS` ⇒ 403. (Custom header can't be set cross-origin without CORS preflight; we send no CORS headers.)
- Secrets never logged; `GatewayResult`/audit unchanged.
- Known limitation (next slice): sessions, pending approvals, audit chain are in-memory → lost on restart. Postgres slice fixes.

## Tests (write first)
- console: `GET /` is HTML containing "JARVIS"; served in both auth modes.
- auth/google: login redirects to Google with `state`; callback (mocked token exchange) with allow-listed email sets cookie and `/auth/me` returns email; non-listed email ⇒ 403 and `/auth/me` ⇒ 401; cookie + POST without CSRF header ⇒ 403, with header ⇒ 200; logout clears; bearer token still accepted; token mode unchanged.
- settings: google mode without client id / owner emails / session secret ⇒ RuntimeError outside dev.
- ratelimit: burst over the limit ⇒ 429 with Retry-After.

## Exit criteria
pytest green, ruff clean, security review of auth path, owner can sign in on the hosted URL.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v0.2.0 | 11 Nov 2026 | R6.1 | Version line and change log added in R6.1 | 🛠 Mark XIII |
