# src/jarvis/phone/part.py
"""R7 Part C (Phone link and security): the part's one join with the app
(`jarvis.mobile.ports`): the link and the devices, the door's `hello` and `inbox` handlers
(`services["door"]`), the app lock's check (`services["app_lock"]`) and the privacy rows.

I0 stub: nothing is built yet. Part C replaces the body of `build` and adds its modules to this
package; see docs/plans/r7-mobile.md and docs/plans/r7-integration/BRIEF-COMMON.md.
"""

from __future__ import annotations

from jarvis.mobile.ports import MobileContext, MobilePart


def build(ctx: MobileContext) -> MobilePart:
    del ctx
    return MobilePart("phone")


__all__ = ["build"]
