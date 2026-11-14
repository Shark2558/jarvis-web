# src/jarvis/offline/r14_part.py
"""R14 Part D (No-AI pass 2, rows 101/102, the leftovers): the part's one join with the app
(`jarvis.hardening.ports`). I0's stub: its phrases (none yet) and "not built yet". Part D's
`maint_service_request` is one of R11's house tools (helpers/house/tools.py), not this part's.
"""

from __future__ import annotations

from jarvis.hardening.ports import HardeningContext, HardeningPart
from jarvis.offline.phrases_r14 import ROUTERS


def build(ctx: HardeningContext) -> HardeningPart:
    return HardeningPart("noai", services={"phrases": ROUTERS})


__all__ = ["build"]
