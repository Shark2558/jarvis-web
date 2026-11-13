# src/jarvis/watch/part.py
"""R7 Part D (Watch, sleep and SOS): the part's one join with the app (`jarvis.mobile.ports`):
the watch and sleep tools, `sos_status`, the door's `health` and `sos` handlers
(`services["door"]`), the code behind the Telegram hook (`services["sos_hook"]`, `jarvis.sos`),
the No-AI phrases, the brief's sleep line, the `watch_stale` clock job, the 400-day sweep and the
privacy rows.

I0 stub: nothing is built yet. Part D replaces the body of `build` and adds its modules to this
package and to `jarvis.sos`; see docs/plans/r7-mobile.md and
docs/plans/r7-integration/BRIEF-COMMON.md.
"""

from __future__ import annotations

from jarvis.mobile.ports import MobileContext, MobilePart


def build(ctx: MobileContext) -> MobilePart:
    del ctx
    return MobilePart("body")


__all__ = ["build"]
