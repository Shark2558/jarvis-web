# Release R2 — Beta: the second fixture plan (tests only)

Status: PLAN v1 (fixture). Reviewer: write to beta.reviewer@example.org or call 9123456780.

## How it fits the architecture
| Feature | Layer · skill | Phase | Verdict |
|---|---|---|---|
| Model router | L4 core reasoning · Code & DevOps | 2 | Build now |

## Decisions (binding)

**D1 · Tiers, not models.** A skill asks `jarvis.llm.router.pick` for a tier, never a model id.

## Needs the owner (safe defaults until answered)
1. Choose the default tier (default: balanced).

## Open questions
- Should the router remember the last tier per skill? Deferred until there are two skills.

## Deferred
A local model fallback is deferred to R3.
