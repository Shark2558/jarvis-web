# evals/r6_book/seal.py
"""R6 eval part `seal` (builder B): sealing, retention and download (D6, D7).
Negative control: retention 4.
I0 STUB: not built yet -- one passing case. Builder B replaces `cases` and `control`, sets
`BUILT = True`, and keeps the interface in evals/r6_book/run.py."""

from __future__ import annotations

from typing import Any

from r6_common import no_control, not_built

PART = "seal"
BUILT = False
PLANNED = (
    "two releases -> two sealed, two notices",
    "a 4th -> 3 kept; the oldest's index entry and chunks gone",
    "a tampered chunk and a sha mismatch fail closed (+ book_seal_failed)",
    "a restart sends no notice",
    "two racing sealers seal once",
)


async def cases() -> list[dict[str, Any]]:
    return not_built(PART, PLANNED)


async def control() -> dict[str, Any]:
    return no_control(PART)
