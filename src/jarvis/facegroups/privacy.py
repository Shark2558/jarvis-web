# src/jarvis/facegroups/privacy.py
"""R11.1 Part C in the privacy dashboard (plan D21-C): two rows in the "Faces" section.

- "Face groups": the unnamed groups and stray faces the home laptop keeps (as it last said; the
  cloud holds their ids and counts, never a face). Delete all asks the laptop to forget them and
  is DONE only when the laptop answers with its own counts. While the laptop is away the ask
  waits (the 5-minute poll retries it), the row keeps its count and says so, and the dashboard
  reports what is left rather than a clean success.
- "Photos being read": a running Google Photos import's progress (counts and the ids of the
  picked photos still to do). Delete stops the import and drops the ids.
Named people are the "People JARVIS recognises" row (R3): their groups go with them.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from typing import Any

from jarvis.facegroups.service import OFF, FaceGroupsService
from jarvis.photos.imports import describe
from jarvis.photos.service import PhotosService
from jarvis.privacy.ports import CategoryView

SECTION = "Faces"
GROUPS_ID = "face_groups"
IMPORT_ID = "photo_imports"
ASK_BUDGET_S = 3.0  # inside the dashboard's 5 s a row: a sleeping laptop never hides the row
PENDING = "Delete asked. It is NOT done yet: it happens when your home laptop is back on."
# R11.1 I1 (INTEGRATION-C 3.4): what the dashboard says right after a delete the laptop has not
# confirmed yet (`pending_note`), instead of its generic "Try again in a moment"
PENDING_NOTE = "Pending: it finishes when your home laptop is back on."
AS_HEARD = (
    "As your laptop last said. Deleting removes the unnamed groups and stray faces from your "
    "laptop; your photos are never touched. If the laptop is off, the delete waits and "
    "finishes when it is back: until then this row says NOT done yet."
)


def _rev(*parts: object) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:16]


class FaceGroupsPrivacy:
    id = GROUPS_ID
    section = SECTION
    label = "Face groups"

    def __init__(self, service: Callable[[], FaceGroupsService | None]) -> None:
        self._svc = service

    async def describe(self, uid: str) -> CategoryView:
        base: dict[str, Any] = {
            "id": self.id,
            "section": self.section,
            "label": self.label,
            "what": "Groups of unnamed faces your home laptop found in your photos. JARVIS "
            "keeps each group's code and how many photos it is in; the faces are only on "
            "your laptop.",
            "unit": "groups and stray faces",
            "retention": "On your laptop until you name or forget them, at most 90 days unless "
            "you changed FACE_GROUPS_KEEP_DAYS",  # the laptop's own number replaces it below
            "where": "Your home laptop; ids and counts in Firestore",
        }
        svc = self._svc()
        if svc is None:
            return CategoryView(**base, count=0, note=OFF)
        try:
            async with asyncio.timeout(ASK_BUDGET_S):
                view = await svc.view(uid)
        except TimeoutError:
            view = await svc.view(uid, ask=False)
        if not view.available:
            return CategoryView(**base, count=0, note=view.reason)
        doc = await svc.store.get(uid)
        count = doc.kept
        if doc.heard_at:  # the laptop's own setting, as it last said (review C-code M9)
            days = doc.home.keep_days
            base["retention"] = (
                f"On your laptop until you name or forget them, at most {days:,} "
                f"day{'s' if days != 1 else ''} (FACE_GROUPS_KEEP_DAYS on the laptop)"
            )
        return CategoryView(
            **base,
            count=count,
            export=True,
            delete="confirm" if count else "none",
            recoverable=False,
            note=PENDING if doc.forget_all else AS_HEARD,
            # what a delete would remove, not when the laptop was last heard: stable till it changes
            rev=_rev(count, doc.forget_all, len(doc.forget), *(g.id for g in doc.home.groups)),
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        svc = self._svc()
        if svc is None:
            return None
        doc = await svc.store.get(uid)
        return {
            "groups": [
                {"id": g.id, "number": g.n, "photos": g.photos, "first": g.first, "last": g.last}
                for g in doc.home.groups
            ],
            "stray_faces": doc.home.strays,
            "named_groups": doc.home.named,
            "heard_at": doc.heard_at,
            "faces": "only on your laptop",
        }

    def pending_note(self) -> str:
        """The dashboard's words when a delete left rows: the laptop finishes it later."""
        return PENDING_NOTE

    async def delete(self, uid: str) -> int:
        """How many the LAPTOP confirmed it forgot (0 while it is away: the ask then waits)."""
        svc = self._svc()
        if svc is None:
            return 0
        done = await svc.forget_all(uid)
        return done.forgotten if done.done else 0


class PhotoImportPrivacy:
    id = IMPORT_ID
    section = SECTION
    label = "Photos being read"

    def __init__(self, photos: Callable[[], PhotosService | None]) -> None:
        self._photos = photos

    async def describe(self, uid: str) -> CategoryView:
        base: dict[str, Any] = {
            "id": self.id,
            "section": self.section,
            "label": self.label,
            "what": "While JARVIS reads photos you picked in Google Photos it keeps Google's "
            "ids of the ones still to read and the counts so far. Never a picture.",
            "unit": "photos still to read",
            "retention": "Until the import ends or you stop it",
            "where": "Firestore",
        }
        photos = self._photos()
        if photos is None:
            return CategoryView(**base, count=0, note=OFF)
        doc = await photos.imports.get(uid)
        running = doc.state != "none"
        return CategoryView(
            **base,
            count=len(doc.todo),
            export=running,
            delete="simple" if running else "none",
            recoverable=False,
            note=describe(doc, photos.limits.max_picked) or "No import is running.",
            rev=_rev(doc.session_id, doc.state, doc.done, len(doc.todo)),
            delete_count=len(doc.todo) if running else None,
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        photos = self._photos()
        if photos is None:
            return None
        doc = await photos.imports.get(uid)
        return {
            "state": doc.state,
            "picked": doc.total,
            "read": doc.done,
            "faces_found": doc.faces,
            "could_not_be_read": doc.skipped,
            "still_to_read": len(doc.todo),
        }

    async def delete(self, uid: str) -> int:
        photos = self._photos()
        if photos is None:
            return 0
        before = len((await photos.imports.get(uid)).todo)
        await photos.stop(uid)
        return before


__all__ = ["GROUPS_ID", "IMPORT_ID", "SECTION", "FaceGroupsPrivacy", "PhotoImportPrivacy"]
