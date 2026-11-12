# src/jarvis/picture/part.py
"""R11.1 Part D (People, pictures and Vitals): the part's one join with the app
(`jarvis.fixes.ports`; docs/plans/r11-1-observations.md D17, D21-D).

`build(ctx)` hands back the `picture_research` tool and the service the part's routes read
(`app.state.r111_parts["look"].services["research"]`). Everything the service needs from the app
is read LATE, when it is called: the brains and billing (the one look), the No-AI switch, the web
search service, the gateway (whose rules decide the web search) and the document store that Part
B's `turn_pictures` reads. Nothing is read while `build` runs, and a missing piece means "not
set up" in plain words, never an error.

The rest of Part D lives where it belongs: profile cards in `console-people.js`, the Vitals rows
in `jarvis.vitals` and `jarvis.integrations.github`, the persona rule in `jarvis.core.prompts`.
"""

from __future__ import annotations

from jarvis.documents.pictures import turn_pictures
from jarvis.fixes.ports import FixContext, FixPart
from jarvis.llm.base import ImageBlock
from jarvis.picture.eyes import BrainEyes
from jarvis.picture.research import PictureResearch
from jarvis.picture.search import WebFinder
from jarvis.picture.tools import picture_tools

SERVICE = "research"
READY = "ready"
OFF = "off: switched off in settings"


def build(ctx: FixContext) -> FixPart:
    if not ctx.s.picture_research_enabled:
        return FixPart("look", ready=OFF)

    async def pictures(uid: str, session_id: str) -> list[ImageBlock]:
        return await turn_pictures(ctx.state("documents"), uid, session_id)

    eyes = BrainEyes(
        brains=lambda: ctx.state("brains"),
        billing=lambda: ctx.state("billing"),
        mode=lambda: ctx.state("brain_mode"),
    )
    finder = WebFinder(web=lambda: ctx.state("web"), gateway=lambda: ctx.state("gateway"))
    service = PictureResearch(eyes, pictures, finder)
    return FixPart(
        "look", tools=tuple(picture_tools(service)), services={SERVICE: service}, ready=READY
    )


__all__ = ["OFF", "READY", "SERVICE", "build"]
