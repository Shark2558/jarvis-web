# src/jarvis/backup/__init__.py
"""R14 Part A: Firestore's own daily backups, kept 7 days, and a monthly restore drill into a
throw-away database whose code can't write the live one (docs/plans/r14-hardening.md D3, D4).
I0 owns this file and `ports.py`; Part A builds the rest (`part.py` is its join)."""
