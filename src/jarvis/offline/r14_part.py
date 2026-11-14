# src/jarvis/offline/r14_part.py
"""R14 Part D (No-AI pass 2, rows 101/102, the leftovers): the part's one join with the app
(`jarvis.hardening.ports`). It hands the wiring its No-AI routers (`phrases`, D12), which the
wiring puts into No-AI mode one at a time; it registers no tool of its own: row 102's
`maint_service_request` is one of R11's house tools (helpers/house/tools.py), row 101's car-service
reminder one of R11's upkeep starters. Plain code only: nothing here calls a model.
"""

from __future__ import annotations

from jarvis.hardening.ports import HardeningContext, HardeningPart
from jarvis.offline.phrases_r14 import ROUTERS

READY = "ready"


def build(ctx: HardeningContext) -> HardeningPart:
    return HardeningPart("noai", services={"phrases": ROUTERS}, ready=READY)


__all__ = ["READY", "build"]
