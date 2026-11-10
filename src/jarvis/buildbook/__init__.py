# src/jarvis/buildbook/__init__.py
"""The build book (R6, docs/plans/r6-build-book.md): JARVIS documents himself at every release,
seals the book and that release's source code in the vault, and presents himself behind the
owner's passkey and a fresh Google sign-in, with a guest mode that reaches nothing of his.

D11 boundary (tests/test_r6_seams.py): nothing in this package imports `jarvis.core.brain`,
`jarvis.tools`, `jarvis.memory`, `jarvis.documents` or `jarvis.integrations.google*`. The
talk-through is a separate minimal lane over the model router; the audit chain is reached
through `ports.BookAudit`.
"""
