# evals/r6_book/lock.py
"""R6 eval part `lock` (builder C): the guest lock (D10). Negative control: /auth/me allow-listed.
I0 STUB: not built yet -- one passing case. Builder C replaces `cases` and `control`, sets
`BUILT = True`, and keeps the interface in evals/r6_book/run.py."""

from __future__ import annotations

from typing import Any

from r6_common import no_control, not_built

PART = "lock"
BUILT = False
PLANNED = (
    "during a guest lock /auth/me, /v1/chat, /v1/vault, /v1/memory -> 423 and / -> 302",
    "... for the presenting session, an older one and a NEW sign-in after log-out",
    "show routes pass",
    "only a book_resume passkey lifts it",
)


async def cases() -> list[dict[str, Any]]:
    return not_built(PART, PLANNED)


async def control() -> dict[str, Any]:
    return no_control(PART)
