# src/jarvis/buildbook/gen/__init__.py
"""The build book generator, `python -m jarvis.buildbook.gen` (R6 part A;
docs/plans/r6-build-book.md D2-D5). Fixed code: it parses text and ASTs and imports only pure-data
modules (`jarvis.llm.pricing`, `jarvis.billing.fx`, `Settings.model_fields` defaults), never the
app, and makes no model call.

Writes `src/jarvis/buildbook/_book/{book.json, source.zip, release.json}` (git-ignored; package data
so the image carries it). `--check` builds twice and compares bytes (the CI gate); `--best-effort`
writes `release.json` with `error` and no book when a build fails, so a deploy never stops on it.
"""
