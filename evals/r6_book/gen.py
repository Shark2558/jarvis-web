# evals/r6_book/gen.py
"""R6 eval part `gen` (builder A): the generator (D2-D5). Negative control: scrub off.
I0 STUB: not built yet -- one passing case. Builder A replaces `cases` and `control`, sets
`BUILT = True`, and keeps the interface in evals/r6_book/run.py."""

from __future__ import annotations

from typing import Any

from r6_common import no_control, not_built

PART = "gen"
BUILT = False
PLANNED = (
    "a double build is byte-equal",
    "every section is present",
    "the fixture's e-mail, phone and hashed name never reach book.json",
    "a planted AIza key refuses the snapshot; a listed fake passes",
    "a 16 MB snapshot is refused",
    "a flow naming a missing function fails",
    "MIT/Apache/GPL/unknown licences labelled, GPL flagged",
)


async def cases() -> list[dict[str, Any]]:
    return not_built(PART, PLANNED)


async def control() -> dict[str, Any]:
    return no_control(PART)
