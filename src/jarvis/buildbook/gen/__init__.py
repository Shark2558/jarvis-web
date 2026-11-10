# src/jarvis/buildbook/gen/__init__.py
"""The build book generator (R6 D2-D5; builder A): `python -m jarvis.buildbook.gen --out DIR`.

Fixed code builds `book.json`, `source.zip` and `release.json` from the repository's text and ASTs
(no model call, no network); it imports only pure-data modules and never the app (`jarvis.api`; a
static test, tests/test_r6_seams.py). Output schema: `jarvis.buildbook.model` (`Book` v1, `Release`,
`canonical_bytes`).
"""
