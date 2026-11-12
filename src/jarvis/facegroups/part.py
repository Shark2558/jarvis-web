# src/jarvis/facegroups/part.py
"""R11.1 Part C (Photos, faces and the home kit): the part's one join with the app.

`build(ctx)` hands the app what it wires for O6 and O7 (docs/plans/r11-1-observations.md D14,
D15, D21-C):

- services  `groups` (`FaceGroupsService`: the laptop's unnamed face groups, naming one with the
            consent check, forgetting), `photos` (the R4 `PhotosService`, found late on
            `app.state.photos` and given the owner's `photos_max_picked` / `photos_import_batch`),
            `limit` (the routes' per-owner change limit)
- tools     `faces_groups`, `photos_import_status` (two reads)
- clock     `photos_import` (one step of a running import), `face_groups_poll`
- privacy   "Photos being read" and "Face groups"

Nothing is read from `app.state` while `build` runs: Photos, Faces and the home client are found
when a route, a tool or a job is CALLED, and a missing one means "off", in plain words.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from jarvis.api.ratelimit import RateLimiter
from jarvis.facegroups.jobs import FaceGroupsPollJob, PhotosImportJob
from jarvis.facegroups.privacy import FaceGroupsPrivacy, PhotoImportPrivacy
from jarvis.facegroups.service import FaceGroupsService
from jarvis.facegroups.store import GroupsStore
from jarvis.facegroups.tools import face_group_tools
from jarvis.fixes.ports import FixContext, FixPart
from jarvis.photos.models import ImportLimits
from jarvis.photos.service import PhotosService

CHANGES_PER_MINUTE = 30
READY = "ready"
NO_DOCS = "off: no document store on this server"
PHOTOS_OFF = "off: needs Google sign-in, Faces and the home kit"


def build(ctx: FixContext) -> FixPart:
    if ctx.docs is None:
        return FixPart("photos", ready=NO_DOCS)
    limits = ImportLimits(ctx.s.photos_max_picked, ctx.s.photos_import_batch)

    def photos() -> PhotosService | None:
        found = ctx.state("photos")
        if not isinstance(found, PhotosService):
            return None
        found.limits = limits  # the owner's settings, wherever the import is driven from
        return found

    def laptop_online() -> Callable[[str], Awaitable[bool]] | None:
        probe = ctx.state("faces_laptop")
        return probe if callable(probe) else None

    groups = FaceGroupsService(
        photos,
        GroupsStore(ctx.docs, prefix=ctx.prefix),
        notifier=ctx.notifier,
        audit=ctx.audit,
        laptop_online=laptop_online,
    )
    return FixPart(
        "photos",
        tools=tuple(face_group_tools(groups, photos)),
        clock_jobs=(PhotosImportJob(photos, laptop_online), FaceGroupsPollJob(groups)),
        privacy=(PhotoImportPrivacy(photos), FaceGroupsPrivacy(lambda: groups)),
        services={
            "groups": groups,
            "photos": photos,
            "limit": RateLimiter(CHANGES_PER_MINUTE),
            "limits": limits,
        },
        ready=READY,
    )


__all__ = ["CHANGES_PER_MINUTE", "PHOTOS_OFF", "READY", "build"]
