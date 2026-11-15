# src/jarvis/wardrobe/phone/part.py
"""R13 Part D's one join (docs/plans/r13-wardrobe.md "Part split"): phone.

Phone and panel (OPS-01, the UI of every part, the Privacy rows, the No-AI sentences). D owns no
tool, job or collection: its console modules draw the other parts' routes (`wardrobe/http.py`)
and send every change through their tools. What the wiring takes from it:

- `services["phrases"]`: the No-AI routers of `offline/phrases_r13.py`, installed FIRST and in
  their order (`api/r13_wiring.install_r13_phrases`), ahead of R14's `things` (D6);
- `privacy`: the section "Wardrobe" (`wardrobe/phone/privacy.py`), four rows over every built
  part's `WardrobeData`, read late from `app.state.r13_parts` through `ctx.state`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from jarvis.offline.phrases_r13 import ROUTERS
from jarvis.wardrobe.phone.privacy import privacy_rows
from jarvis.wardrobe.ports import WardrobeContext, WardrobeData, WardrobePart

READY = "ready"


def build(ctx: WardrobeContext) -> WardrobePart:
    def data() -> Sequence[WardrobeData]:
        parts: Mapping[str, Any] = ctx.state("r13_parts") or {}
        return tuple(d for p in parts.values() for d in getattr(p, "data", ()))

    return WardrobePart(
        "phone", privacy=privacy_rows(data), services={"phrases": ROUTERS}, ready=READY
    )


__all__ = ["READY", "build"]
