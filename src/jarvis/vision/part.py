# src/jarvis/vision/part.py
"""R7 Part B (Camera and the vision engine): the part's one join with the app
(`jarvis.mobile.ports`, I0 seams 8 and 20). `build(ctx)` gives, using only what `ctx` hands it:

- tools: `vision_results` (R1, the "Camera results" row), only when results can be kept;
- daily job `vision_sweep` (the morning tick): every owner's days past `vision_keep_days` go;
- privacy rows `vision_results` and `vision_device` (`jarvis.vision.privacy`);
- services: `vision` (`VisionService`: the kept-results store and the routes' change limit), read
  by `api/vision.py` per request.
Looking happens on the device (`console-vision.js`): no frame, picture or pixel ever reaches this
package. Off in settings (`vision_enabled`): nothing is offered. Without a token key the store is
off (never in clear) and the part says so; the Camera panel still looks.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from jarvis.api.ratelimit import RateLimiter
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.mobile.ports import MobileContext, MobilePart
from jarvis.vision.privacy import DevicePrivacy, results_privacy
from jarvis.vision.store import VisionStore
from jarvis.vision.tools import results_tool

log = get_logger(__name__)

SERVICE = "vision"
CHANGES_PER_MINUTE = 30
SWEEP_BUDGET_S = 30.0
READY = "ready"
OFF_SETTING = "off: switched off in settings (vision_enabled)"
OFF_KEY = "off: JARVIS has no token key, so no camera result can be kept (looking still works)"
OFF_STORE = "off: no document store, so no camera result can be kept (looking still works)"


@dataclass(frozen=True)
class VisionService:
    store: VisionStore
    limit: RateLimiter


class VisionSweep:
    """The 90-day sweep: each owner's kept days past the keep are deleted (counts only)."""

    def __init__(self, store: VisionStore) -> None:
        self.store = store
        self.name = "vision_sweep"
        self.budget_s = SWEEP_BUDGET_S

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        removed = 0
        for uid in owners:
            try:
                removed += await self.store.sweep(uid)
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning("vision sweep failed for an owner", extra={"error": type(exc).__name__})
        return {"days_removed": removed, "owners": len(owners)}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def build(ctx: MobileContext) -> MobilePart:
    s = ctx.s
    if not s.vision_enabled:
        return MobilePart("vision", ready=OFF_SETTING)
    if ctx.docs is None:
        return MobilePart("vision", ready=OFF_STORE)
    clock: Callable[[], datetime] = ctx.state("vision_now") or _utcnow  # tests set a clock
    store = VisionStore(
        ctx.docs,
        Keyring.from_settings(s),
        prefix=ctx.prefix,
        now=clock,
        tz=s.user_timezone,
        keep_days=s.vision_keep_days,
    )
    service = VisionService(store, RateLimiter(CHANGES_PER_MINUTE))
    privacy = (results_privacy(store), DevicePrivacy())
    if not store.sealed:
        return MobilePart("vision", privacy=privacy, services={SERVICE: service}, ready=OFF_KEY)
    return MobilePart(
        "vision",
        tools=(results_tool(store, honorific=s.user_honorific),),
        daily_jobs=(VisionSweep(store),),
        privacy=privacy,
        services={SERVICE: service},
        ready=READY,
    )


__all__ = ["SERVICE", "VisionService", "VisionSweep", "build"]
