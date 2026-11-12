# src/jarvis/facegroups/tools.py
"""R11.1 Part C's tools (plan D15; the part's family: `faces_groups`, `faces_group_*`,
`photos_import_*`). Two reads, both R1; nothing here names, enrols or forgets a face: those are
Faces-panel actions with the consent statement, never a tool (as R3 D19 decided for Faces).

- `faces_groups` (row "Camera", as `faces_list`): how many unnamed groups of faces the home
  laptop has to name, by number and photo count. It can't say who anyone is: the cloud has no
  face, and the tool says where to look (the laptop's own page).
- `photos_import_status` (row "Connectors"): how far a Google Photos import has got, in plain
  words, from the stored counts.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.facegroups.service import FaceGroupsService
from jarvis.faces.ports import FAMILY_CHILD
from jarvis.photos.service import PhotosService
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context
from jarvis.tools.provenance import vouch

EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}
WHO = (
    "JARVIS can't see faces: to see who a group is, open http://localhost:8098/faces on your "
    "home laptop. Name a group in the Faces panel (the person, or a parent for a child, must "
    "agree first)."
)
NO_IMPORT = "No photo import is running. Ask me to import photos to start one."
PHOTOS_OFF = "Photos are off on this server: they need Google sign-in, Faces and the home kit."
MAX_LISTED = 20


def _uid() -> str:
    return require_tool_context().user_id


def face_group_tools(
    groups: FaceGroupsService, photos: Callable[[], PhotosService | None]
) -> list[Tool]:
    async def list_groups(_a: dict[str, Any]) -> Any:
        view = await groups.view(_uid())
        if not view.available:
            return {"status": "unavailable", "message": view.reason}
        rows = [{"group": f"Group {g.n}", "photos": g.photos} for g in view.groups[:MAX_LISTED]]
        out: dict[str, Any] = {
            "to_name": len(view.groups),
            "groups": rows,
            "laptop": view.laptop,
            "note": WHO,
        }
        if view.laptop != "online":
            out["stale"] = "Your home laptop isn't reachable: this is what it last said."
        return vouch(out, True)

    async def import_status(_a: dict[str, Any]) -> Any:
        svc = photos()
        if svc is None:
            return {"status": "unavailable", "message": PHOTOS_OFF}
        res = await svc.progress(_uid())
        if res.status == "no_session":
            return vouch({"status": "none", "message": NO_IMPORT}, True)
        named = [FAMILY_CHILD if p.child else "a person you added" for p in res.recognised]
        out = {
            "status": res.status,
            "progress": res.line,
            "photos_read": res.photos,
            "photos_picked": res.total,
            "faces_found": res.faces_found,
            "people_recognised": len(named),
        }
        return vouch(out, True)

    return [
        Tool(
            "faces_groups",
            "How many unnamed groups of faces your home laptop found in your photos and is "
            "waiting for you to name (group number and photo count only). It can't say who "
            "anyone is and can't name or forget a group: that is done in the Faces panel.",
            EMPTY_SCHEMA,
            ActionRisk.READ_ONLY,
            list_groups,
            agent="faces",
            may_vouch=True,
            activity_words="Listed the face groups to name",
        ),
        Tool(
            "photos_import_status",
            "How far the Google Photos import has got (photos read, faces found, why it is "
            "paused). Read only: use photos_import to start or continue one.",
            EMPTY_SCHEMA,
            ActionRisk.READ_ONLY,
            import_status,
            agent="connectors",
            may_vouch=True,
            activity_words="Checked the photo import",
        ),
    ]


__all__ = ["face_group_tools"]
