# evals/r6_book/access.py
"""R6 eval part `access` (builder C): passkey AND a fresh sign-in (D8, D9).
I0 STUB: not built yet -- one passing case. Builder C replaces `cases` and `control`, sets
`BUILT = True`, and keeps the interface in evals/r6_book/run.py."""

from __future__ import annotations

from typing import Any

from r6_common import no_control, not_built

PART = "access"
BUILT = False
PLANNED = (
    "a stale sign-in -> reauth_required",
    "no proof -> passkey_required",
    "no passkey -> passkey_setup_needed",
    "bearer -> console_only",
    "a vault_unlock proof fails",
    "an expired or idle token -> 401",
    "a guest token can't read sections, older books or download code",
)


async def cases() -> list[dict[str, Any]]:
    return not_built(PART, PLANNED)


async def control() -> dict[str, Any]:
    return no_control(PART)
