# src/jarvis/buildbook/seal_words.py
"""The sealer's notice words and D3's last check (R6 D3, D7; builder B; L8 notify), kept out of
sealer.py. Every notice names a release by its label and short id only: never book text, a path,
an address or a size beyond the configured limit. `{h}` is the owner's honorific.
"""

from __future__ import annotations

from collections.abc import Sequence

from jarvis.buildbook import owner_id

LOCAL_PART_MIN = owner_id.TOKEN_MIN  # a shorter local-part token is not a name

SEALED = (
    "{h}, the build book for {label} ({id}) is sealed in your vault with this release's code. "
    "{kept} kept."
)
UNBUILT = "{h}, the build book for {label} ({id}) could not be built at deploy, so it isn't sealed."
FAILED = "{h}, the build book for {label} ({id}) could not be sealed in your vault; I'll try again."
PERSONAL = (
    "{h}, the build book for {label} ({id}) holds your e-mail address, so I refused to seal it."
)
PERSONAL_WORD = (
    "{h}, the build book for {label} ({id}) holds a word from your e-mail address, so I refused "
    "to seal it."
)
OVER_LIMIT = (
    "{h}, the build book for {label} ({id}) doesn't fit in the build book's {mb} MB storage "
    "limit beside your newest sealed release, so it isn't sealed. Raise the limit "
    "(book_max_total_mb) to seal it."
)
INDEX_TAMPERED = "{h}, your sealed build books failed their integrity check, so they stay closed."
READ_TAMPERED = (
    "{h}, the sealed build book for {label} ({id}) failed its integrity check, so it stays closed."
)


def kept_words(n: int) -> str:
    return f"{n} release" if n == 1 else f"{n} releases"


def personal_words(hit: owner_id.Hit) -> str:
    """D3's refusal notice, naming what matched (the address, or a word from it) but never the
    word itself."""
    return PERSONAL if hit == "address" else PERSONAL_WORD


def owner_hit(book: bytes, owner_emails: Sequence[str]) -> owner_id.Hit | None:
    """D3's last check before sealing (`owner_id.in_book`, the one rule the guest door and the
    reply guard use too): "address", "word" or None."""
    return owner_id.in_book(book, owner_emails)


def holds_owner_email(book: bytes, owner_emails: Sequence[str]) -> bool:
    """Does book.json name a configured owner (`owner_hit` is not None)?"""
    return owner_hit(book, owner_emails) is not None


__all__ = [
    "FAILED",
    "INDEX_TAMPERED",
    "LOCAL_PART_MIN",
    "OVER_LIMIT",
    "PERSONAL",
    "PERSONAL_WORD",
    "READ_TAMPERED",
    "SEALED",
    "UNBUILT",
    "holds_owner_email",
    "kept_words",
    "owner_hit",
    "personal_words",
]
