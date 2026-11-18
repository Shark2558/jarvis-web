# src/jarvis/api/tryon_wiring.py
"""R13.1 I0 seam 6 (docs/plans/r13-1-try-on.md D10; plan review L12): `ctx.tryon`, the try-on
provider, for `api/r13_wiring.context`.

- `tryon_provider(s)`: a callable that builds the provider on its first call and keeps it:
  `llm.tryon.build_tryon` with ADC bearer tokens (`voice.adc.AdcTokens`, made ONLY while
  `tryon_pictures` is on: no credentials are looked up otherwise) and the project
  (`firestore_project`, else `adc_project()`, looked up late). None while pictures are off, the
  model and location are unpriced, or Part C's adapter is not built yet.
- `adc_project()`: the project Application Default Credentials name, off the event loop, at most
  5 s; None when there is none.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from jarvis.config import Settings
from jarvis.llm.tryon import TryOnProvider, build_tryon
from jarvis.logging import get_logger

log = get_logger(__name__)

ADC_TIMEOUT_S = 5.0


async def adc_project() -> str | None:
    """The Google Cloud project Application Default Credentials name (None when none)."""
    import google.auth

    try:
        _, found = await asyncio.wait_for(asyncio.to_thread(google.auth.default), ADC_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - no project: no picture, said in words by C
        return None
    return found if isinstance(found, str) and found else None


def tryon_provider(s: Settings) -> Callable[[], TryOnProvider | None]:
    """`ctx.tryon`: the provider, built on first use and kept (None while pictures are off)."""
    made: list[TryOnProvider | None] = []

    async def project() -> str | None:
        return s.firestore_project or await adc_project()

    def get() -> TryOnProvider | None:
        if made:
            return made[0]
        if not s.tryon_pictures:
            made.append(None)
            return None
        from jarvis.voice.adc import AdcTokens

        try:
            made.append(build_tryon(s, tokens=AdcTokens(), project=project))
        except Exception as exc:  # noqa: BLE001 - a broken adapter is "not configured", in words
            log.error("try-on provider not built", extra={"error": type(exc).__name__})
            made.append(None)
        return made[0]

    return get


__all__ = ["ADC_TIMEOUT_S", "adc_project", "tryon_provider"]
