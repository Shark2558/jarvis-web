# Release R1 — Alpha: the core loop answers and remembers the conversation

Status: PLAN v1 · 2026-10-01 · a fixture for the build book generator (tests/fixtures/book).
Questions go to the owner at owner.fixture@example.com or +91 9000012345.
Not in this plan: voice, the home camera.

## How it fits the architecture
| Feature | Layer · skill | Phase | Verdict |
|---|---|---|---|
| Core loop | L4 reasoning · Task & Productivity | 0 | Build now |
| Sealed sessions | L7 data · Security Advisor | 0 | Build now |

## Decisions (binding)

**D1 · One loop.** Text in, one model call, text out (`core/loop.py`).

**D2 · Sessions sealed.** Every conversation is stored sealed (`vault/store.py`).

## Risks
- A slow model makes the loop feel stuck; the console shows progress.

## Open questions
1. Should the loop keep more than 20 turns? Reviewed with Kavya Fixturename.
