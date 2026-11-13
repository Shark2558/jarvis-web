# src/jarvis/vision/part.py
"""R7 Part B (Camera and the vision engine): the part's one join with the app
(`jarvis.mobile.ports`): the kept-results store and the `vision_results` tool.

I0 stub: nothing is built yet. Part B replaces the body of `build` and adds its modules to this
package; see docs/plans/r7-mobile.md and docs/plans/r7-integration/BRIEF-COMMON.md.
"""

from __future__ import annotations

from jarvis.mobile.ports import MobileContext, MobilePart


def build(ctx: MobileContext) -> MobilePart:
    del ctx
    return MobilePart("vision")


__all__ = ["build"]
