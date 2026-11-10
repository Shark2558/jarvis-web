# evals/r6_book/wipe.py
"""R6 eval part `wipe` (builder C): close and wipe (D14). Negative control: delete skipped.
I0 STUB: not built yet -- one passing case. Builder C replaces `cases` and `control`, sets
`BUILT = True`, and keeps the interface in evals/r6_book/run.py."""

from __future__ import annotations

from typing import Any

from r6_common import no_control, not_built

PART = "wipe"
BUILT = False
PLANNED = (
    "after close a needle question is in no document, log, audit entry or Activity row",
    "... nor in any memory store, session store or Telegram text",
    "one content-free book_session_closed",
    "the audit holds exactly book_open + book_close",
    "an abandoned session is swept (ended by itself)",
)


async def cases() -> list[dict[str, Any]]:
    return not_built(PART, PLANNED)


async def control() -> dict[str, Any]:
    return no_control(PART)
