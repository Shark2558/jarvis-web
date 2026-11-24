# src/jarvis/buildbook/book/__init__.py
"""R6.3.1 (docs/plans/r6-3-1-book-at-build.md D1-D6): the Build Book written at build time.

The Workshop writes each of the full book's pages as `pages/<page_id>.md` (YAML front matter and
the five-section wire format of R6.3) and each chapter's and module's flowchart as
`flows/<page_id>.json`, following `AUTHORING.md`. `authored` reads and checks them; the generator
compiles them into the release (part E). Nothing here is ever a page's reference: the generator's
repository view leaves this folder out (`gen/repo.BOOK_DIR`).
"""
