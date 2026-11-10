"""Alerts to the owner, from fixed templates (build book fixture)."""

from __future__ import annotations

TEMPLATES = {"brief_ready": "Your morning brief is ready."}


def text_for(kind: str) -> str:
    return TEMPLATES[kind]
