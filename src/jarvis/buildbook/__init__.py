# src/jarvis/buildbook/__init__.py
"""The build book (R6, docs/plans/r6-build-book.md; cross-cutting quality + Layer 7 vault, Layer 8
show). JARVIS documents himself at every release (`gen`, deterministic, no model call), seals the
book and that release's source code in the vault, and presents them behind the owner's passkey and
a fresh Google sign-in, with a guest mode that reaches nothing of his.

- `model`: the ONE schema every part reads (release.json, book.json v1, sealed releases, sessions).
- `ports`: the Protocols the builders implement independently (source, vault, sessions, lock, talk).
- `lines`: D13's fixed lines, pinned.

D11: nothing in this package imports `jarvis.core.brain`, `jarvis.tools`, `jarvis.memory`,
`jarvis.documents` or `jarvis.integrations.google*` (a static test, tests/test_r6_seams.py).
"""
