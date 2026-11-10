# Release R1 — Alpha: a fixture plan for the build book generator (tests only)

Status: PLAN v1 (fixture). Written for tests/fixtures/book (docs/plans/r6-build-book.md I0 item 7).
Questions to Vandrel at vandrel.fixture@example.com or +91 9876543210 before the build.

## How it fits the architecture
| Feature | Layer · skill | Phase | Verdict |
|---|---|---|---|
| Core loop | L4 core reasoning · Task & Productivity | 0 | Build now |
| Sealed notes | L7 vault · Security Advisor | 3 | Build now |

## Decisions (binding)

**D1 · One loop.** Text in, a reply out, through `jarvis.core.loop.turn`.

**D2 · Sealed at rest.** Notes are sealed by `jarvis.vault.store.seal` before they are written.

## Not in this plan
Voice is not in this plan; it comes later. Nothing here is spoken.

## Risks
- **A slow model**: the router picks a cheaper tier when the budget is low.
