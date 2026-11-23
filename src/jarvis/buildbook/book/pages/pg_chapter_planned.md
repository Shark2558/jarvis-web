---
page: pg_chapter_planned
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "docs/architecture/JARVIS-Architecture.md": "165280977e9069c3"
  "docs/plans/r6-3-book-content.md": "88de5316dd8af32f"
---
## In plain words
This chapter is the list of what isn't part of JARVIS yet, so you know which parts you use today and which exist only on paper. Every other page of this book describes the code as it runs now.
Planned: the next releases in the order you set them, from the architecture guide's roadmap. First the Build Book's new look, with a guest-safe full book, search and print. Then JARVIS making and answering phone calls from your laptop, the voice fixes you asked for, the home cameras' setup with the first home vision uses, and the kitchen vision uses. Later: care uses and a fitness coach, smart-home extras, subscription releases, a new core skill for Health and Wellbeing, a trading desk (to be decided), and deeper tracing. Nothing here is built, and plans change.

## Example (made up)
Priya opens the Book on her phone one evening and wonders whether JARVIS can already answer a phone call for her. She opens this chapter and finds "phone calls from your laptop" in the list, second after the Book's new look. So she doesn't hunt for it in the console. She turns instead to the Voice page, which tells her what the microphone does today, and makes a note to look again after the next 2 releases.

## How it works
The architecture guide, `docs/architecture/JARVIS-Architecture.md`, gives every part of JARVIS a card and marks in capitals any part that isn't built yet, so a reader never mistakes a plan for a feature. Its roadmap section lists the next releases in the order the owner set, with what each one holds, and says plainly that nothing in it is built (`docs/architecture/JARVIS-Architecture.md`). The short tour reads its "next" and "after that" lines from the first two rows of that table (`docs/plans/r6-3-book-content.md`). A page of this book may name unbuilt work only in a separate paragraph marked for it, so the rest of each page sticks to what the code does (`docs/plans/r6-3-book-content.md`).
Planned: R6.4, the Book's new look, a guest-safe full book, search and print. Then calls made and answered from the laptop; R5.2, the voice build; R8, the home cameras' setup and the first home vision uses on JARVIS's on-device vision engine, each starting after you confirm its cameras; R8.1, the next release in your order; R9, the kitchen vision uses. Later: R10 care and the fitness coach, R12 smart-home extras, R15 to R18 subscription releases, the Health and Wellbeing skill, R19 a trading desk with the decision left for later, and tracing with OpenTelemetry.

## What it costs
Reading this list costs nothing. What a release on it would cost is worked out in that release's own plan, before any work starts, and is not guessed here (`docs/architecture/JARVIS-Architecture.md`).

## When it fails
A roadmap row goes out of date when plans change; the guide is updated with each release, and its change log at the end says what moved (`docs/architecture/JARVIS-Architecture.md`). If a page of this book named unbuilt work outside that marked paragraph, the page would fail its checks and the reader would show the plain generated text in its place (`docs/plans/r6-3-book-content.md`).
