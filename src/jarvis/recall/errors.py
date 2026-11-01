# src/jarvis/recall/errors.py
"""Errors the memory layer raises; the API maps each to one status and error code (§5)."""

from __future__ import annotations

MSG_FULL = "Memory is full (500 facts). Delete some facts, then try again."
MSG_SENSITIVE = (
    "That looks like private data (an ID, card or account number, password, PIN or OTP), "
    "so JARVIS won't store it."
)
MSG_UNAVAILABLE = "Memory can't be read just now. Try again in a minute."
MSG_TOO_LARGE = "That file is larger than 512 KB, so it was not imported."


class ConsentRequired(RuntimeError):
    """Switching learning on without `confirm_spend` (→ 409 consent_required)."""


class SensitiveRejected(ValueError):
    """The text hit the sensitive-data filter (→ 422 sensitive). The message never quotes it."""

    def __init__(self, detail: str = MSG_SENSITIVE) -> None:
        super().__init__(detail)


class MemoryFull(RuntimeError):
    """500 active facts already (→ 409 memory_full)."""

    def __init__(self, detail: str = MSG_FULL) -> None:
        super().__init__(detail)


class MemoryUnavailable(RuntimeError):
    """Storage down or a document unreadable (→ 503 memory_unavailable). Fail closed: an
    unreadable shard is never overwritten."""

    def __init__(self, detail: str = MSG_UNAVAILABLE) -> None:
        super().__init__(detail)


class ImportTooLarge(ValueError):
    """An import body over 512 KB (→ 413 too_large)."""

    def __init__(self, detail: str = MSG_TOO_LARGE) -> None:
        super().__init__(detail)


__all__ = [
    "MSG_FULL",
    "MSG_SENSITIVE",
    "ConsentRequired",
    "ImportTooLarge",
    "MemoryFull",
    "MemoryUnavailable",
    "SensitiveRejected",
]
