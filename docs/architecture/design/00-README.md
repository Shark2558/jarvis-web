Version v6.4.2 · 27 Nov 2026 · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV

# 00 · The JARVIS Architecture Design Document

## In one page

**What this is.** This is the engineering reference for how JARVIS is built: its parts, where
each one runs, how data is kept, how it stays safe, what it costs and why it was built this way.
You asked for it on 27 Nov 2026: "create a new architecture design document as per the build and
the requirements, verify the architecture, and refer to it in future". It is called the ADD
(Architecture Design Document) from here on.

**How it differs from the guide you already have.** The *JARVIS Architecture & Technology Guide*
(`docs/architecture/JARVIS-Architecture.md`, edition v6.4.2) explains JARVIS in plain words, one
card per part. This document is for whoever plans, builds or reviews a change. It does not replace
the guide; the guide stays the place to read what a part does for you.

**The one rule.** From now on every plan, build and review starts from this document. A plan that
disagrees with it must say so, and the disagreement is settled by writing down a decision (an
"ADR", chapter 08) before anything is built. Each release updates this document in its paperwork
step, as it already does for the guide.

**What you can trust in it.** Every statement about the system names the file it was checked
against on 27 Nov 2026. Anything that could not be checked says *unverified*. Anything not built
yet says PLANNED. Money is in rupees (₹) and every ₹ figure is an estimate.

## How to use this document

| You are | Read first | Then |
|---|---|---|
| Planning a release | 01 (the rules every plan obeys), 08 (decisions already taken) | the chapters the plan touches; 09–12 for requirements and the roadmap |
| Building a part | 03 (the layer and its ports), 04 (the data it may keep), 05 (the security rules) | 07 (the tests and checks it must pass) |
| Reviewing a change | 01 and 05 | 08: does the change contradict an accepted ADR? |
| Checking cost or capacity | 06 | 02 (the Cloud Run settings) |

**Conflicts.** If code, a plan or a request disagrees with this document, the person who finds it
flags it in the plan or the pull request. It is resolved in one of two ways, never silently:
(1) the change is brought back in line, or (2) a new ADR in chapter 08 changes the design, and the
affected chapters are updated in the same pull request.

**Keeping it current.** Every release's paperwork step (the same step that updates the guide and
the build log) updates the chapters the release changed, adds its ADRs, and adds a row to each
changed chapter's change log. Each chapter carries its own version line and change log under the
workshop rules' section 6 format, which `scripts/check_doc_versions.py` defines.

**How to cite.** A citation is `path` or `path:Symbol`, relative to the repository root, for
example `src/jarvis/tools/gateway.py:Gateway.execute`. "As built" means present in `main` at
merge `83331a1` (27 Nov 2026), program version `6.4.0` (`src/jarvis/__init__.py:__version__`).

## Chapters

| # | File | What it covers | Kind | Written by |
|---|---|---|---|---|
| 00 | `00-README.md` | This page: what the ADD is and how to use it | — | 🛠 Mark XXV (as-built writer) |
| 01 | `01-principles.md` | The architecture principles and exactly where each is enforced in code | As built | as-built writer |
| 02 | `02-context-and-deployment.md` | System context, deployment (Cloud Run, Firestore, the home kit, CI/CD, backups), trust boundaries | As built | as-built writer |
| 03 | `03-layers.md` | The eight layers: components, ports, data, failure modes; the 11 skills and their tools | As built | as-built writer |
| 04 | `04-data.md` | Firestore collections, the vault and keys, retention, privacy rows, backups, what stays on a device | As built | as-built writer |
| 05 | `05-security.md` | Authentication, authorisation and the gateway, secrets, audit, threat model, residual risks | As built | as-built writer |
| 06 | `06-cost-and-capacity.md` | Metering, prices, free allowances, caps and limits; Cloud Run capacity | As built | as-built writer |
| 07 | `07-quality.md` | Tests, coverage, evals, CI jobs, docs checks, the Build Book's build-time generation, releases | As built | as-built writer |
| 08 | `08-decisions.md` | The ADR log: every significant decision and the code that implements it | As built + proposals | as-built writer |
| 09 | `09-requirements.md` | The requirements baseline | Requirements | requirements writer |
| 10 | `10-traceability.md` | Every requirement mapped to layer, skill and status | Requirements | requirements writer |
| 11 | `11-roadmap.md` | Planned releases and their design notes | PLANNED | requirements writer |
| 12 | `12-gaps-and-risks.md` | Gaps, conflicts, scaling limits, debt (the proposed ADRs moved to 08) | Analysis | requirements writer |
| 13 | `13-verification.md` | The independent check of chapters 00–12 against the code and the workbook: method, counts, every fix, what stays unverified, how to re-run | Verification | verifier |

## Diagrams

Diagrams are Markdy sources in `docs/architecture/diagrams/` with an SVG and a PNG beside each.
The ADD adds three (15 to 17) and reuses the guide's fourteen by number.

| Figure | Source | Used in |
|---|---|---|
| 15 · JARVIS as built: the containers | `diagrams/15-containers.markdy` | 02 |
| 16 · Trust boundaries | `diagrams/16-trust-boundaries.markdy` | 02, 05 |
| 17 · A request through the layers | `diagrams/17-request-path.markdy` | 03 |
| 1–14 (the guide's) | `diagrams/01-context.markdy` … `diagrams/14-privacy-map.markdy` | referenced where they fit |

## Building the single-file copy

The chapters are plain Markdown and read on their own. To make one file (for printing or for
your Drive copy), from the repository's top folder:

```bash
mkdir -p build
for f in docs/architecture/design/[0-9][0-9]-*.md; do cat "$f"; printf '\n\n---\n\n'; done \
  > build/JARVIS-ADD.md
```

`build/` is ignored by git (`.gitignore`), so the copy is never committed. `pandoc` turns it into
HTML if wanted (`pandoc build/JARVIS-ADD.md -o build/JARVIS-ADD.html`; image paths are relative
to `docs/architecture/design/`, so run pandoc with `--resource-path=docs/architecture/design`).
The chapters' own version lines stay in the copy, so each part shows its edition.

## How this document was checked

Written on 27 Nov 2026 from the code at `83331a1`, the deploy scripts, both CI workflows, the
evals and the plans. The as-built chapters' counts were measured, not copied: `pytest
--collect-only` (19,530 items), `scripts/skill_coverage.py` (157 tools in 11 skills) and
`scripts/arch_coverage.py`'s inventory (66 packages and modules, 126 Firestore collections, 31
outside services, 2 Scheduler jobs); a wider search found 5 collections the inventory misses (131
in all, chapter 04). The secret scan of `scripts/arch_coverage.py` covers every
file under `docs/architecture/`, these chapters included.

On the same day a second reader who had not written it checked every chapter against the code and
the requirements workbook, fixed what was wrong in place and marked what can't be checked from the
repository as *Unverified*; chapter 13 lists every fix and how to repeat the checks. Since then
`scripts/check_doc_versions.py` checks this folder's version lines too.

## Glossary (terms used across the chapters)

| Term | Meaning |
|---|---|
| ADD | This Architecture Design Document. |
| ADR | Architecture Decision Record: one decision, its context, its consequences and the code that carries it out (chapter 08). |
| As built / PLANNED | In the code on `main` today / designed but not built. |
| Port | A small interface a part depends on instead of a concrete service, so the service can be swapped (for example `Docs` for the database). |
| Gateway | `jarvis.tools.gateway`: the one checkpoint every tool call passes. |
| Risk tier | How much a tool call can change: R1 read, R2 reversible, R3 irreversible (chapter 05). Not the same as a release name such as "R7". |
| Card | An approval card: what a held action will do, waiting for the owner's Approve. |
| Passkey | A sign-in key kept on the owner's phone or laptop, opened with a fingerprint or PIN (WebAuthn). |
| Sealed | Encrypted by JARVIS with its own key before Google stores it (AES-256-GCM). |
| Taint | The mark a conversation round gets when other people's text (mail, web, a document) reached the model; writes then ask first. |
| Tick | A scheduled wake-up call from Cloud Scheduler. |
| Home kit | The programs on the owner's laptop: Home Assistant, Frigate, Mosquitto, the home bridge (and optionally the laptop brain). |
| TWA | Trusted Web Activity: an Android app whose screen is the website drawn by Chrome. |
| No-AI mode | A saved switch under which no AI model is called at all; fixed phrases still run tools. |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 14:05 IST | R6.4 | First edition: what the ADD is, the canonical-reference rule, how conflicts are settled, the chapter list (00–12), the three new figures, the single-file copy, how it was checked, the shared glossary | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): chapter 13 added to the list; how the document was verified; the proposed ADRs now in chapter 08 | 🛠 Mark XXV |
