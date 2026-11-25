---
page: pg_chapter_planned
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
sources:
  "docs/architecture/JARVIS-Architecture.md": "c46b1009dc7a77a9"
  "docs/plans/r6-4-book-look.md": "b7976e034965205f"
---
## In plain words
This chapter lists what isn't part of JARVIS yet, so you know which parts you use today and which exist only on paper; every other page describes the code as it runs now. This release, {{fact:release.label}}, is built and has left the list: the Book's own look, the full book on a page of its own with search, its chapters narrated with varied effects, and fixes for costs and Tailscale addresses.
Planned: after it, the guide's roadmap in your order. First phone calls from your laptop, then the voice fixes you asked for, the home cameras with the first home vision uses, and the kitchen vision uses. Later: care, a fitness coach, smart-home extras, subscription releases, a Health and Wellbeing skill, a trading desk and deeper tracing. Left out of R6.4 for later: a guest-safe full book, print views, a Simple or Technical toggle and an interactive architecture map. None of it is built, and plans change.

## Example (made up)
Priya opens the Book on her phone one evening and wonders whether JARVIS can already answer a phone call for her. She opens this chapter and finds "phone calls from your laptop" at the top of the list, just after the release she is reading. So she doesn't hunt for it in the console. She turns instead to the Voice page, which tells her what the microphone does today, presses Play to hear its chapter, and makes a note to look again after the next 2 releases.

## How it works
The architecture guide, `docs/architecture/JARVIS-Architecture.md`, gives every part of JARVIS a card and marks in capitals any part that isn't built yet, so a reader never mistakes a plan for a feature. Its roadmap section lists the next releases in the order the owner set, with what each one holds, and says plainly that nothing in it is built (`docs/architecture/JARVIS-Architecture.md`). The short tour reads its "next" and "after that" lines from the first two rows of that table (`docs/architecture/JARVIS-Architecture.md`). Each release has its own plan, which says what it holds and what it leaves out: the plan for {{fact:release.label}}, `docs/plans/r6-4-book-look.md`, holds the Book's own reader with contents and search, the full book narrated chapter by chapter with varied effects, the https rule for a Tailscale address, and Costs pricing paid Gemini and flagging a model with no known price. The running version, {{fact:release.version}}, is that release: {{fact:release.new}}, so those parts are described as built on the pages that tell them (`docs/plans/r6-4-book-look.md`). The same plan names under "Not in R6.4" what was left for later, so those items stay on this list until a release takes them (`docs/plans/r6-4-book-look.md`).
Planned: after {{fact:release.label}}, calls made and answered from the laptop; R5.2, the voice build; R8, the home cameras' setup and the first home vision uses on JARVIS's on-device vision engine, each starting after you confirm its cameras; R8.1, the next release in your order; R9, the kitchen vision uses. Later: R10 care and the fitness coach, R12 smart-home extras, R15 to R18 subscription releases, the Health and Wellbeing skill, R19 a trading desk with the decision left for later, and tracing with OpenTelemetry. From R6.4's "Not in R6.4", added later on request: a Simple or Technical toggle, an interactive architecture map, print views and a guest-safe full book.

## What it costs
Reading this list costs nothing. What a release on it would cost is worked out in that release's own plan, before any work starts, and is not guessed here (`docs/architecture/JARVIS-Architecture.md`).

## When it fails
A roadmap row goes out of date when plans change; the guide is updated with each release, and its change log at the end says what moved (`docs/architecture/JARVIS-Architecture.md`). A plan's own change log says what changed in it after approval, as {{fact:release.label}}'s records the owner's answers and the effects added at his request (`docs/plans/r6-4-book-look.md`).
