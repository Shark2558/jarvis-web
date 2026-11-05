# src/jarvis/faces/tools.py
"""`faces_list` (R3 D13, row `camera`, R1): who JARVIS is set up to recognise. Registered by I1
(`tools/setup.py`); refused on Telegram unless the owner switched on `allow_home_reads`
(`faces_*`), and never given to a training brain (I1 registers it only with the other private
tools). No tool adds, enrols or deletes a face: those are Faces-panel actions (D19).

- Names are the owner's own typed words but still reach the model fenced.
- A child's name is never spoken or sent to a phone: on a spoken or Telegram turn a child is
  "a child from your family".
- It lists the registry only. It never says who was seen, when, or where (that is
  `camera_history`, which names only through `faces.directory`).
- People being deleted are not listed: their name mapping is gone.
"""

from __future__ import annotations

from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.faces.models import NAME_MAX
from jarvis.faces.ports import FAMILY_CHILD
from jarvis.faces.service import FacesService
from jarvis.faces.store import FacesUnavailable
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context
from jarvis.tools.external import wrap_external
from jarvis.tools.provenance import vouch
from jarvis.tools.spoken import mask_for_speech, speaking_now

SOURCE = "your Faces list"
LISTED = "Listed the people JARVIS recognises"
EMPTY = "Nobody is added yet. People are added in the Faces panel, with their consent."


def _name(name: str, child: bool) -> str:
    if speaking_now():
        return (
            FAMILY_CHILD
            if child
            else wrap_external(mask_for_speech(name), source=SOURCE, limit=NAME_MAX)
        )
    return wrap_external(name, source=SOURCE, limit=NAME_MAX)


class FacesAPI:
    def __init__(self, svc: FacesService) -> None:
        self._svc = svc

    async def list(self, _a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        try:
            view = await self._svc.view(uid)
        except FacesUnavailable as exc:
            return {"status": "unavailable", "message": str(exc)}
        people = [
            {
                "name": _name(p.name, p.child),
                "relation": p.relation,
                "child": p.child,
                "recognised_at_home": p.state == "enrolled",
                "ready": "yes" if p.state == "enrolled" else "no pictures added on the laptop yet",
            }
            for p in view.people
            if p.state != "deleting"
        ]
        out: dict[str, Any] = {"count": len(people), "people": people}
        if not people:
            out["note"] = EMPTY
        return vouch(out, True)


def faces_tools(svc: FacesService) -> list[Tool]:
    api = FacesAPI(svc)
    return [
        Tool(
            "faces_list",
            "List the people JARVIS is set up to recognise at home (names, relation, whether "
            "pictures were added on the laptop). It says nothing about who was seen: use "
            "camera_history for that. Faces can't be added or removed from the chat.",
            {"type": "object", "properties": {}},
            ActionRisk.READ_ONLY,
            api.list,
            agent="faces",
            may_vouch=True,
            activity_words=LISTED,
        )
    ]


__all__ = ["EMPTY", "LISTED", "FacesAPI", "faces_tools"]
