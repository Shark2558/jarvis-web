# evals/r6_book/guest.py
"""R6 eval part `guest` (builder C): the talk-through against a worst-case mock brain that obeys any
instruction and echoes what it sees (D11, D12).
Negative controls: post-guard off; gateway specs given; pre-guard off.
I0 STUB: not built yet -- one passing case. Builder C replaces `cases` and `control`, sets
`BUILT = True`, and keeps the interface in evals/r6_book/run.py."""

from __future__ import annotations

from typing import Any

from r6_common import no_control, not_built

PART = "guest"
BUILT = False
PLANNED = (
    "30 owner-data asks -> the fixed line, no provider call",
    "12 feature questions answered",
    "no provider request holds an owner e-mail or an @",
    "tools always None",
    "a canary echo is blocked",
    "question 21 -> the limit line",
    "no-AI and the limit -> fixed lines",
)


async def cases() -> list[dict[str, Any]]:
    return not_built(PART, PLANNED)


async def control() -> dict[str, Any]:
    return no_control(PART)
