# src/jarvis/photos/errors.py
"""Errors shared by the Photos modules (plain words only, never vendor text)."""

from __future__ import annotations

BAD_ANSWER = "Google Photos returned something JARVIS can't use."
BAD_PICTURE = "One of the photos couldn't be read."


class PickerError(RuntimeError):
    """The Picker answered something unusable (plain words)."""


class PickerRetry(PickerError):
    """Google could not hand a photo over just now (5xx, 429, a timeout, a dropped connection):
    try again later; the photo is not bad (R11.1 review C-code M1)."""


__all__ = ["BAD_ANSWER", "BAD_PICTURE", "PickerError", "PickerRetry"]
