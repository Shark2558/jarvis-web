# src/jarvis/wardrobe/seeme/books.py
"""R13.1 Part C: the press's books (docs/plans/r13-1-try-on.md D13.6, D15; review C-1 findings 5
and 12), out of `make.py` at I1 (its 400-line guard; the integrated reviews' fixes needed room).

- `closed(close)`: a settle or a release of the cap's hold. The cap tries it three times, then
  logs it at ERROR with its request id and keeps it for his next press and the daily job: never
  the reason a made picture, or the refusal he is owed, becomes "can't be reached".
- `record(billing, uid, usd)`: his usage month, label `tryon` (Vitals: "Try-on"). It hears every
  billed call whatever the settle did; `Billing.record` never raises, and if it ever did, it is
  logged and the press goes on (the cap has counted the call).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from jarvis.logging import get_logger

log = get_logger(__name__)


async def closed(close: Awaitable[None]) -> None:
    """A settle or release, its failure already logged and kept by the cap (`TryonCap.pending`)."""
    try:
        await close
    except Exception:  # noqa: BLE001 - logged and kept by the cap
        return


async def record(billing: Any, uid: str, usd: float) -> None:
    """A billed call in his usage month (nothing when there is no billing or nothing billed)."""
    if billing is None or usd <= 0:
        return
    try:
        await billing.record(uid, "tryon", usd)
    except Exception as exc:  # noqa: BLE001 - belt and braces
        log.error(
            "see it on me: his usage month missed a call", extra={"error": type(exc).__name__}
        )


__all__ = ["closed", "record"]
