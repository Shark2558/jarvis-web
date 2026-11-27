Version v6.4.5 · 27 Nov 2026, 22:15 IST · Release R5.2 · Status: Current · Owner: 🛠 Mark XXV

# 00 · The JARVIS Architecture Design Document

## In one page

**What this is.** This is the engineering reference for how JARVIS is built: its parts, where
each one runs, how data is kept, how it stays safe, what it costs and why it was built this way.
You asked for it on 27 Nov 2026: "create a new architecture design document as per the build and
the requirements, verify the architecture, and refer to it in future". It is called the ADD
(Architecture Design Document) from here on.

**How it differs from the guide you already have.** The *JARVIS Architecture & Technology Guide*
(`docs/architecture/JARVIS-Architecture.md`, edition v5.2.1 since R5.2's catalogue; the guide's
version follows the release that changed it last) explains JARVIS in plain words, one
card per part. This document is for whoever plans, builds or reviews a change. It does not replace
the guide; the guide stays the place to read what a part does for you.

**The one rule.** From now on every plan, build and review starts from this document. A plan that
disagrees with it must say so, and the disagreement is settled by writing down a decision (an
"ADR", chapter 08) before anything is built. Each release updates this document in its paperwork
step, as it already does for the guide.

**What you can trust in it.** Every statement about the system names the file it was checked
against on 27 Nov 2026. Anything that could not be checked says *unverified*. Anything not built
yet says PLANNED. Money is in rupees (₹) and every ₹ figure is an estimate.

**R18 in this edition.** Release R18, "Calls from your laptop", is built but not yet live: JARVIS
can place a call from your own phone number after your tap, speak in the call through your laptop,
and keep a sealed recording and summary. Chapters 02–08, 11 and 12 describe it, each part marked
"(R18)"; chapter 12, section 6 lists what is not finished.

**R5.2 in this edition.** Release R5.2, "Your voice", is built but not yet live. A free speech kit
on your laptop can listen for JARVIS, so Google's free minutes last longer; a 20-minute voice
session teaches JARVIS how you speak and picks the engine that understands you best; your own
"Hey Jarvis" can be trained on your laptop; and a speaker check in your browser lets only your
voice interrupt JARVIS (it never approves anything). It costs ₹0 a month. Chapters 02–08, 11 and
12 describe it, each part marked "(R5.2)"; chapter 08 adds ADR-40 to ADR-46, and chapter 12,
section 7 lists what is not finished and what is open for R5.2's review.

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
For what is marked R18, "as built" means R18's code with its combined review's fixes, program
version `18.0.0`; it is not yet in `main` or deployed. This edition was first written on the ADD's
own branch (`main` at `8e95780` plus the `r18-review` branch at `7d7ce19`); the review's later
fixes (`docs/plans/r18-integration/REVIEW.md`: the approvals seal, the deploy's speech keys, the
free-first eval, outfit plans kept 90 days) were then checked into chapters 02, 04–08 and 11–13 on
the R18 release branch (`r18-release` at `c036ca1`). For what is marked R5.2, "as built" means
R5.2's code on its Build Book branch (`r5-2-book` at `1db5988`) with R18's final release
(`r18-release` at `48d35d4`) merged, on the ADD's own branch `add-r52`, program version `5.2.0`;
it is not yet in `main` or deployed. R5.2's combined review fixes its code on another branch at
the same time; the chapters describe the code before those fixes, and the Workshop brings them in
line afterwards (chapter 12, section 7).

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
| Phone Link (R18) | Microsoft's Windows app that lets a laptop make and take a phone's calls over Bluetooth, like a car kit. |
| Call desk (R18) | JARVIS's Windows program on the laptop that hears a call through Phone Link and speaks into it. |
| VB-CABLE (R18) | A free virtual audio cable for Windows; during a JARVIS call it is the microphone Phone Link hears. |
| Loopback recording (R18) | Recording what the laptop's own speaker plays (Windows' WASAPI loopback); how the desk hears the call. |
| Language check (R18) | The test every call language must pass before it is offered: hearing and speaking over a simulated phone line, speed, and a person's score. |
| FLEURS (R18) | Google's public set of recorded test sentences in many languages (CC BY 4.0) that the language check uses. |
| Speech option (R18) | One way to hear and speak a language on a call: Google, Azure's free tier, Bhashini, Sarvam (paid), or the laptop's own models. |
| Dial grant (R18) | What the owner's approval of a call card issues: it lets exactly one call be dialled, within 10 minutes. |
| Reply guard (R18) | The check every line JARVIS is about to say in a call passes: no codes, account numbers or promises to pay. |
| Doorbell (R18) | A Web Push message with no details that tells the phone app to fetch its signed commands. |
| A2P call (R18) | TRAI's term for a call started by software without a person dialling it. |
| DPDP Act (R18) | India's Digital Personal Data Protection Act, 2023. |
| Laptop speech kit (R5.2) | JARVIS's small speech program on the owner's laptop: it listens for JARVIS, keeps the voice session's recordings and trains his own wake word. |
| Tailscale Funnel | Tailscale's feature that gives one program on the laptop a public https address on port 443, 8443 or 10000; the encryption ends on the laptop. |
| Caddy gate | A small free web server on the laptop that lets a request through to a JARVIS program only with that program's key. |
| Voice session (R5.2) | About 120 short lines the owner reads aloud in 20 minutes, from which JARVIS ranks listening engines on his voice and learns his corrections and words. |
| Voice profile (R5.2) | What the voice session learned, kept in the cloud: each engine's score for his voice, the chosen engine, the corrections. Never audio. |
| Word error rate | The share of words an engine got wrong (left out, added or changed); lower is better. |
| Whisper (faster-whisper) | OpenAI's open speech-recognition model (MIT), run on the laptop through the faster-whisper library. |
| Wake-word verifier and owned model (R5.2) | Stage 1: a small check trained on the owner's "Hey Jarvis" that runs after today's detector. Stage 2: a whole wake-word model trained by and owned by him. |
| Barge-in | Talking over JARVIS to interrupt him while he speaks. |
| Voice print and speaker check (R5.2) | A device's summary of the owner's voice, made and kept only in that browser, and the check that uses it to let only his voice barge in. It never approves anything. |
| Pinned transport | JARVIS's way of calling the laptop: the address's name is looked up again for every request and the connection made to the address just checked. |
| Git blob id (R5.2) | The SHA-1 fingerprint git gives a file; the kit accepts it for small text model files at a fixed commit, where Hugging Face shows no SHA-256 (ADR-42). |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 14:05 IST | R6.4 | First edition: what the ADD is, the canonical-reference rule, how conflicts are settled, the chapter list (00–12), the three new figures, the single-file copy, how it was checked, the shared glossary | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): chapter 13 added to the list; how the document was verified; the proposed ADRs now in chapter 08 | 🛠 Mark XXV |
| v6.4.3 | 27 Nov 2026, 21:10 IST | R18 | R18 "Calls from your laptop": what this edition adds, in plain words; what "as built" means for R18 (not yet in `main`); twelve terms added to the glossary | 🛠 Mark XXV |
| v6.4.4 | 27 Nov 2026, 21:25 IST | R18 | The R18 review's later fixes: what "as built" means for R18 now (the release branch `r18-release` at `c036ca1`, after `docs/plans/r18-integration/REVIEW.md`) and which chapters took the approvals seal, the deploy's speech keys, the free-first eval and outfit plans kept 90 days | 🛠 Mark XXV |
| v6.4.5 | 27 Nov 2026, 22:15 IST | R5.2 | R5.2 "Your voice": what this edition adds, in plain words; what "as built" means for R5.2 (its Book branch with R18's final release, on `add-r52`; not yet in `main`; the review's fixes synced afterwards); the guide's edition; twelve terms added to the glossary | 🛠 Mark XXV |
