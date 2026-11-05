# src/jarvis/photos/errors.py
"""Errors shared by the Photos modules (plain words only, never vendor text)."""

from __future__ import annotations

BAD_ANSWER = "Google Photos returned something JARVIS can't use."
BAD_PICTURE = "One of the photos couldn't be read."


class PickerError(RuntimeError):
    """The Picker answered something unusable (plain words)."""


__all__ = ["BAD_ANSWER", "BAD_PICTURE", "PickerError"]
