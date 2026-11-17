# src/jarvis/wardrobe/tryon/ports.py
"""R13.1's seams between its two server parts (docs/plans/r13-1-try-on.md seam 4, D12, D16):

- `SeeMeErase`: C's `seeme` service as A's OPS-05 delete sees it: `erase(uid)` deletes his try-on
  pictures, then his photo, then his YES (never the month's spend), and says how many documents
  went. A's `erase_all` calls it, else `kept.erase_seeme` by path (C off or failed), then deletes
  `tryon/{uid}`.
- `TryonLooks`: A's `tryon_looks` service as C sees it: `look(uid, plan)` is the look the console
  shows (`http.TryonLook`, read fresh), so C checks what a picture may send against the same
  record the figure shows (a private piece, a piece without a front crop, a slot that isn't a
  garment are never sent).
- `service_of(ctx, name)`, `photo_vault(ctx)`, `seeme_service(ctx)`, `looks_service(ctx)`: a
  named service from its one owner (`ports.SERVICE_OWNER`), read LATE from the app (parts are built
  one after the other: A is built before C, so never read one at build time). R13's catalog
  `PhotoVault.get(uid, photo)` opens a saved crop for C's request (the only crops that leave).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from jarvis.wardrobe.ports import SERVICE_OWNER, PhotoVault, WardrobeContext
from jarvis.wardrobe.tryon.http import TryonLook


@runtime_checkable
class SeeMeErase(Protocol):
    async def erase(self, uid: str) -> int: ...


@runtime_checkable
class TryonLooks(Protocol):
    async def look(self, uid: str, plan: str) -> TryonLook: ...


def service_of(ctx: WardrobeContext, name: str) -> Any:
    """The named service from its owner's built part, read now (None when it isn't there)."""
    parts: Mapping[str, Any] = ctx.state("r13_parts") or {}
    part = parts.get(SERVICE_OWNER[name])
    services = getattr(part, "services", None) or {}
    return services.get(name)


def photo_vault(ctx: WardrobeContext) -> PhotoVault | None:
    vault = service_of(ctx, "photos")
    return vault if isinstance(vault, PhotoVault) else None


def seeme_service(ctx: WardrobeContext) -> SeeMeErase | None:
    found = service_of(ctx, "seeme")
    return found if isinstance(found, SeeMeErase) else None


def looks_service(ctx: WardrobeContext) -> TryonLooks | None:
    found = service_of(ctx, "tryon_looks")
    return found if isinstance(found, TryonLooks) else None


__all__ = [
    "SeeMeErase",
    "TryonLooks",
    "looks_service",
    "photo_vault",
    "seeme_service",
    "service_of",
]
