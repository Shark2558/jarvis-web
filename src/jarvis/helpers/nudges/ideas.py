# src/jarvis/helpers/nudges/ideas.py
"""Part C's `freetime_*` tools (item 12; plan D16 row `household`): his own free-time list, and a
pick for now made by code (`freetime.suggest`), never by a model.

- `freetime_suggest` (R1): an idea that fits the free time before his next event (or the minutes
  he gives), not done in the last 3 days, indoors when rain is likely.
- `freetime_list` (R1), `freetime_add` (R2; a card when the round read outside content, so an
  e-mail can't add to his list), `freetime_remove` (R2), `freetime_done` (R2: "I did it today").
"""

from __future__ import annotations

from typing import Any

from jarvis.helpers.nudges import freetime
from jarvis.helpers.nudges.models import MAX_IDEAS, Idea, NudgeSettings, Place
from jarvis.helpers.nudges.service import NudgeService
from jarvis.helpers.nudges.tools import R1, R2, make_tool, owner_id
from jarvis.helpers.nudges.words import a_number
from jarvis.tools.base import Tool
from jarvis.tools.taint import content_tainted

_TEXT = {"type": "string", "maxLength": 80, "description": "the idea, in his words"}
_MIN = {"type": "integer", "minimum": 5, "maximum": 480}


def _place(value: Any) -> Place:
    word = str(value or "any").strip().lower()
    if word in ("inside", "indoors"):
        word = "indoor"
    if word in ("outside", "outdoors"):
        word = "outdoor"
    if word not in ("indoor", "outdoor", "any"):
        raise ValueError("Say indoor, outdoor or any, Sir.")
    return word  # type: ignore[return-value]


def find(s: NudgeSettings, said: Any) -> Idea:
    text = " ".join(str(said or "").lower().split())
    exact = [i for i in s.ideas if i.id == text or i.text.lower() == text]
    near = [i for i in s.ideas if text and text in i.text.lower()]
    found = exact or near
    if len(found) != 1:
        raise ValueError(
            "That isn't on your free-time list, Sir."
            if not found
            else "More than one idea matches, Sir; say more of it."
        )
    return found[0]


def _listed(s: NudgeSettings) -> str:
    if not s.ideas:
        return "Your free-time list is empty, Sir. Say 'add to my free-time list: ...'."
    items = "; ".join(f"{i.text} ({i.minutes} min, {i.place})" for i in s.ideas)
    return f"Your free-time list, Sir: {items}."


def _suggest_tool(svc: NudgeService) -> Tool:
    async def run(a: dict[str, Any]) -> dict[str, Any]:
        uid, now = owner_id(), svc.now()
        given = a_number(a["minutes"], lo=5, hi=480, what="minutes") if "minutes" in a else None
        s = await svc.settings(uid)
        if not s.ideas:
            return {"spoken": _listed(s)}
        idea, gap = await freetime.suggest(svc, uid, s, now, given)
        if gap is None:
            return {"spoken": "Your calendar isn't linked, Sir. Say how many minutes you have."}
        if idea is None:
            return {"spoken": "Nothing on your list fits that time, Sir."}
        return {"spoken": freetime.say(idea, gap), "idea": idea.text, "minutes": idea.minutes}

    return make_tool(
        "freetime_suggest",
        "Suggest something from his own free-time list for now.",
        {"minutes": _MIN},
        R1,
        run,
        trusted_output=True,
        words="Suggested free time",
    )


def _show_tool(svc: NudgeService) -> Tool:
    async def show(a: dict[str, Any]) -> dict[str, Any]:
        return {"spoken": _listed(await svc.settings(owner_id()))}

    return make_tool(
        "freetime_list",
        "Show his free-time list.",
        {},
        R1,
        show,
        trusted_output=True,
        words="Looked at the free-time list",
    )


def _add_tool(svc: NudgeService) -> Tool:
    async def add(a: dict[str, Any]) -> dict[str, Any]:
        minutes = a_number(a.get("minutes", 30), lo=5, hi=480, what="minutes")
        idea = Idea.new(str(a.get("text", "")), minutes, _place(a.get("place")))
        await svc.store.change(owner_id(), lambda s: s.with_idea(idea))
        return {"spoken": f"Added to your free-time list, Sir: {idea.text} ({minutes} min)."}

    props = {
        "text": _TEXT,
        "minutes": _MIN,
        "place": {"type": "string", "enum": ["indoor", "outdoor", "any"]},
    }
    return make_tool(
        "freetime_add",
        f"Add an idea to his free-time list (at most {MAX_IDEAS}).",
        props,
        R2,
        add,
        required=["text"],
        ask_when=lambda a: content_tainted(),
        words="Added a free-time idea",
        summarize=lambda a: "Add an idea to your list",
    )


def _remove_tool(svc: NudgeService) -> Tool:
    async def remove(a: dict[str, Any]) -> dict[str, Any]:
        gone: list[Idea] = []

        def drop(s: NudgeSettings) -> NudgeSettings:  # may run again if the store retries
            idea = find(s, a.get("text"))
            gone.append(idea)
            return s.with_ideas(tuple(i for i in s.ideas if i.id != idea.id))

        await svc.store.change(owner_id(), drop)
        return {"spoken": f"Removed from your free-time list, Sir: {gone[-1].text}."}

    return make_tool(
        "freetime_remove",
        "Remove an idea from his free-time list.",
        {"text": _TEXT},
        R2,
        remove,
        required=["text"],
        words="Removed a free-time idea",
    )


def _done_tool(svc: NudgeService) -> Tool:
    async def done(a: dict[str, Any]) -> dict[str, Any]:
        today, hit = svc.day_of().isoformat(), []

        def mark(s: NudgeSettings) -> NudgeSettings:  # may run again if the store retries
            new = find(s, a.get("text")).model_copy(update={"last_done": today})
            hit.append(new)
            return s.with_ideas(tuple(new if i.id == new.id else i for i in s.ideas))

        await svc.store.change(owner_id(), mark)
        return {"spoken": f"Noted, Sir: {hit[-1].text}, done today."}

    return make_tool(
        "freetime_done",
        "Mark an idea from his list done today.",
        {"text": _TEXT},
        R2,
        done,
        required=["text"],
        words="Marked a free-time idea done",
    )


def freetime_tools(svc: NudgeService) -> list[Tool]:
    return [_suggest_tool(svc), _show_tool(svc), _add_tool(svc), _remove_tool(svc), _done_tool(svc)]


__all__ = ["find", "freetime_tools"]
