# src/jarvis/understand/part.py
"""R11.1 Part B (Voice and files): the part's one join with the app
(docs/plans/r11-1-observations.md O3, O4; `jarvis.fixes.ports`).

`build(ctx)` hands the app nothing to register: no tool (reading a file stays the `doc_*` tools
in `jarvis.documents`), no clock or daily job, no privacy row (a picture lives with its attached
file and is deleted with it). It hands its own routes (`api/fix_files.py`, under `/v1/input`):

    services["understand"]   `UnderstandService`: "heard / understood as" and the per-turn hints
    services["estimate"]     `Estimator`: the rupee estimate before a costly reply (D12)

Both read the gateway's neighbours late (`ctx.state(...)`: brains, billing, the brain-mode
switch, the documents and the conversations), at call time, and treat a missing one as "off".
"""

from __future__ import annotations

from jarvis.fixes.ports import FixContext, FixPart
from jarvis.understand.estimate import Estimator
from jarvis.understand.service import UnderstandService

READY = "ready"
READY_NO_UNDERSTAND = "ready (understood-as is switched off)"


def build(ctx: FixContext) -> FixPart:
    services = {"understand": UnderstandService(ctx), "estimate": Estimator(ctx)}
    ready = READY if ctx.s.voice_understand else READY_NO_UNDERSTAND
    return FixPart("files", services=services, ready=ready)


__all__ = ["READY", "READY_NO_UNDERSTAND", "build"]
