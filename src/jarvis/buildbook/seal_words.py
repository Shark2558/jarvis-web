# src/jarvis/buildbook/seal_words.py
"""The sealer's notice words and D3's last check (R6 D3, D7; builder B; L8 notify), kept out of
sealer.py. Every notice names a release by its label and short id only: never book text, a path,
an address or a size beyond the configured limit. `{h}` is the owner's honorific.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence

LOCAL_PART_MIN = 3  # a shorter local part is a common word, not a name

SEALED = (
    "{h}, the build book for {label} ({id}) is sealed in your vault with this release's code. "
    "{kept} kept."
)
UNBUILT = "{h}, the build book for {label} ({id}) could not be built at deploy, so it isn't sealed."
FAILED = "{h}, the build book for {label} ({id}) could not be sealed in your vault; I'll try again."
PERSONAL = (
    "{h}, the build book for {label} ({id}) holds your e-mail address, so I refused to seal it."
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


def _marks(emails: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    for raw in emails:
        email = unicodedata.normalize("NFKC", raw).casefold().strip()
        local, at, _ = email.partition("@")
        if not at or not local:
            continue
        out.append(email)
        if len(local) >= LOCAL_PART_MIN:
            out.append(local)
    return tuple(out)


def holds_owner_email(book: bytes, owner_emails: Sequence[str]) -> bool:
    """D3's last check before sealing: does book.json name a configured owner address or its
    local part, as a whole word (NFKC, case-folded, JSON escapes undone)?"""
    marks = _marks(owner_emails)
    if not marks:
        return False
    try:
        text = json.dumps(json.loads(book), ensure_ascii=False)
    except ValueError:
        text = book.decode("utf-8", "replace")
    text = unicodedata.normalize("NFKC", text).casefold()
    return any(re.search(rf"(?<![\w.+-]){re.escape(m)}(?![\w-])", text) for m in marks)


__all__ = [
    "FAILED",
    "INDEX_TAMPERED",
    "LOCAL_PART_MIN",
    "OVER_LIMIT",
    "PERSONAL",
    "READ_TAMPERED",
    "SEALED",
    "UNBUILT",
    "holds_owner_email",
    "kept_words",
]
