# src/jarvis/buildbook/show_script.py
"""What the show says (R6 D13, D15; `GET /v1/book/show/script`, `POST /v1/book/show/speak`). All
facts come from the release's book.json (`book.show`, scenes 1-11, and `book.costs`); scenes 12 and
13 and every spoken refusal are D13's fixed lines (`lines.py`), filled with the honorific, its
possessive and the creator credit from Book settings. The owner's month spend (₹) is added for the
owner only: a guest never sees it (D1). Book settings that can't be read mean the defaults (no
creator name, the cloud voice).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from jarvis.buildbook.lines import CLOSING, LINES, credit_by, possessive, render
from jarvis.buildbook.model import LINE_ID, Audience, SessionView, TalkState
from jarvis.buildbook.ports import BookSource
from jarvis.logging import get_logger

log = get_logger(__name__)
_LINE = re.compile(LINE_ID)


class Prefs(Protocol):
    async def get(self, uid: str) -> Mapping[str, Any]: ...


class ShowScript:
    def __init__(
        self,
        source: BookSource,
        *,
        honorific: str,
        prefs: Prefs | None = None,
        spend: Callable[[str], Awaitable[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.source, self._h, self._read, self._spend = source, honorific, prefs, spend

    async def prefs(self, uid: str) -> Mapping[str, Any]:
        if self._read is None:
            return {}
        try:
            return await self._read.get(uid)
        except Exception as exc:  # noqa: BLE001 - defaults: no name, cloud voice
            log.warning("book settings unreadable", extra={"error": type(exc).__name__})
            return {}

    async def words(self, uid: str) -> dict[str, str]:
        name = (await self.prefs(uid)).get("creator_name")
        return {
            "h": self._h,
            "his": possessive(self._h),
            "by": credit_by(name if isinstance(name, str) else None),
        }

    async def line_text(self, uid: str, line_id: str) -> str | None:
        """What `POST /v1/book/show/speak {line_id}` reads: a beat of this book or a D13 line."""
        if line_id in LINES:
            return render(line_id, **await self.words(uid))
        if not _LINE.fullmatch(line_id):
            return None
        beats = (b for s in self.source.book().show.scenes for b in s.beats)
        return next((b.text for b in beats if b.id == line_id), None)

    async def voice(self, uid: str) -> str:
        return "browser" if (await self.prefs(uid)).get("show_voice") == "browser" else "cloud"

    def fixed_scenes(self, audience: Audience, words: dict[str, str]) -> list[dict[str, Any]]:
        ask = {"id": "ask", "text": LINES["ask"], "focus": ""}
        closing = [{"id": i, "text": render(i, **words), "focus": ""} for i in CLOSING[audience]]
        return [
            {"n": 12, "id": "questions", "title": "Questions", "beats": [ask], "facts": []},
            {"n": 13, "id": "closing", "title": "Closing", "beats": closing, "facts": []},
        ]

    async def costs(self, uid: str, audience: Audience) -> dict[str, Any]:
        costs: dict[str, Any] = self.source.book().costs.model_dump(mode="json")
        if audience != "owner" or self._spend is None:
            return costs  # D1: a guest never sees the owner's spend
        try:
            spent = await self._spend(uid)
        except Exception as exc:  # noqa: BLE001 - the show goes on without the figure
            log.warning("month spend unreadable", extra={"error": type(exc).__name__})
            return costs
        return {**costs, **{k: spent.get(k) for k in ("month_inr", "limit_inr")}}

    async def build(self, uid: str, session: SessionView, talk: TalkState) -> dict[str, Any]:
        """`GET /v1/book/show/script`: {release, audience, scenes (1-13), closing, costs, talk,
        voice, session}."""
        book, audience = self.source.book(), session.audience
        words = await self.words(uid)
        scenes = [s.model_dump(mode="json") for s in book.show.scenes]
        fixed = self.fixed_scenes(audience, words)
        hand_back = {"id": "hand_back", "text": LINES["hand_back"]}
        return {
            "release": book.release.model_dump(mode="json"),
            "audience": audience,
            "scenes": scenes + fixed,
            "closing": {
                "lines": [{"id": b["id"], "text": b["text"]} for b in fixed[1]["beats"]],
                "hand_back": hand_back if audience == "guest" else None,
            },
            "costs": await self.costs(uid, audience),
            "talk": talk.model_dump(),
            "voice": await self.voice(uid),
            "session": {
                "until": session.until,
                "idle_until": session.idle_until,
                "questions_left": session.questions_left,
            },
        }


__all__ = ["Prefs", "ShowScript"]
