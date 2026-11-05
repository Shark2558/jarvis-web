# src/jarvis/camera/tools.py
"""Alarm and camera-history tools (R3 D8, D15). Registered by I1 (`tools/setup.py`).

- `home_arm` (R2, `spoken_ok`, row `home_arm`): "Jarvis, arm the house" as he leaves. It says
  `confirmed` only once the laptop acked the new rev; before that the answer is "waiting for your
  laptop". Allowed from Telegram. A round that read other people's words turns it into a card.
- `home_disarm` (R3, row `home_secure`): never disarms. It answers with a fixed line that sends the
  owner to the Home panel, where the Disarm button needs his bound passkey (or a fresh Google
  sign-in). There is no gateway path to `Alarm.disarm`.
- `camera_history` (R1, row `camera`, `may_vouch`): times, places and counts only. Every word comes
  from cloud tables (labels the owner typed, fixed words, names from the consent registry), so the
  result is the owner's own; labels and names are still fenced as data. On a Telegram turn a child
  is "a child from your family". Never a picture, never a description of anyone.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from jarvis.camera.alarm import Alarm, DisarmGate
from jarvis.camera.history import History, HistoryRejected
from jarvis.camera.models import MAX_LIMIT, WHAT_VALUES, HistoryQuery, HistoryResult, SetVia
from jarvis.camera.ports import CameraUnavailable
from jarvis.core.channel import on_telegram
from jarvis.core.guardrails import ActionRisk
from jarvis.faces.ports import FAMILY_CHILD, UNKNOWN_PERSON
from jarvis.home.ports import ArmView, HomeUnavailable
from jarvis.tools.base import Tool
from jarvis.tools.context import ToolContext, require_tool_context
from jarvis.tools.external import wrap_external
from jarvis.tools.provenance import vouch
from jarvis.tools.spoken import mask_for_speech, speaking_now

SOURCE = "your camera history"
ARMED_WORDS = "Armed the home alarm"
DISARM_WORDS = "Pointed to the Home panel to disarm"
SEARCHED_WORDS = "Searched camera history"
CONFIRM_WAIT_S = 4.0
DISARM_ANSWER = "Disarming needs your passkey: open the Home panel and press Disarm."
NO_ZONES = (
    "The alarm is switched on but JARVIS is not protecting anything yet: no camera has an alarm "
    "zone. Tell the owner to pick the gate zone in the Home panel. Do not say the home is armed."
)
PENDING = (
    "Arming - waiting for your laptop. If it is off or asleep it will arm when it is back; "
    "JARVIS tells you if it hasn't answered in 5 minutes. Do not say the home is armed yet."
)


def via_of(ctx: ToolContext) -> SetVia:
    """How a change was asked for: voice (a spoken turn or a card from one), Telegram, or chat."""
    if on_telegram():
        return "telegram"
    return "voice" if ctx.spoken or speaking_now() else "chat"


def _arm_result(v: ArmView, protecting: bool = True) -> dict[str, Any]:
    if not protecting:
        return {
            "status": "no_zones",
            "confirmed": False,
            "mode": v.mode,
            "message": NO_ZONES,
        }
    if v.confirmed:
        return {
            "status": "done",
            "armed": True,
            "confirmed": True,
            "mode": v.mode,
            "message": f"The home alarm is on ({v.mode}).",
        }
    return {
        "status": "pending",
        "armed": True,
        "confirmed": False,
        "mode": v.mode,
        "message": PENDING,
    }


def _check_arm(a: dict[str, Any]) -> None:
    if a.get("mode", "away") not in ("away", "night"):
        raise ValueError("mode is away or night")


def _card_arm(a: dict[str, Any]) -> str:
    return f"Turn on the home burglar alarm ({a.get('mode', 'away')})"


def _parse_time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} is a time like 2026-11-04T18:00:00+05:30")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} is a time like 2026-11-04T18:00:00+05:30") from None


def _check_history(a: dict[str, Any]) -> None:
    _parse_time(a.get("start"), "start")
    _parse_time(a.get("end"), "end")
    if not isinstance(a.get("what", "any"), str):
        raise ValueError("what is a word")
    limit = a.get("limit", MAX_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit is a number")


def _say(text: str) -> str:
    plain = mask_for_speech(text) if speaking_now() else text
    return wrap_external(plain, source=SOURCE, limit=60)


def _shown(res: HistoryResult) -> dict[str, Any]:
    items = []
    for i in res.items:
        row: dict[str, Any] = {
            "at": i.at,
            "camera": _say(i.camera),
            "what": i.what,
            "who": None if i.who is None else _say_who(i.who),
        }
        if i.zone:
            row["zone"] = _say(i.zone)
        if i.seconds is not None:
            row["seconds"] = i.seconds
        items.append(row)
    out: dict[str, Any] = {
        "count": res.count,
        "items": items,
        "more": res.more,
        "kept_days": res.kept_days,
    }
    if res.note:
        out["note"] = res.note
    return out


def _say_who(who: str) -> str:
    return who if who in (UNKNOWN_PERSON, FAMILY_CHILD) else _say(who)


class CameraAPI:
    def __init__(
        self,
        alarm: Alarm,
        gate: DisarmGate,
        history: History,
        wait_s: float,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._wait_s = wait_s
        self._sleep = sleep
        self._alarm = alarm
        self._gate = gate
        self._history = history

    async def arm(self, a: dict[str, Any]) -> Any:
        ctx = require_tool_context()
        try:
            await self._alarm.arm(ctx.user_id, a.get("mode", "away"), via_of(ctx))
            view = await self._alarm.wait_confirmed(ctx.user_id, self._wait_s, sleep=self._sleep)
        except CameraUnavailable as exc:
            return {"status": "unavailable", "message": str(exc)}
        return _arm_result(view, await self._alarm.protecting(ctx.user_id))

    async def disarm(self, a: dict[str, Any]) -> Any:
        require_tool_context()
        return {"status": "refused", "code": "needs_console", "message": DISARM_ANSWER}

    async def history(self, a: dict[str, Any]) -> Any:
        ctx = require_tool_context()
        query = HistoryQuery(
            what=a.get("what", "any"),
            start=_parse_time(a["start"], "start"),
            end=_parse_time(a["end"], "end"),
            camera=a.get("camera"),
            zone=a.get("zone"),
            who=a.get("who"),
            limit=a.get("limit", MAX_LIMIT),
        )
        try:
            res = await self._history.search(ctx.user_id, query, hide_children=on_telegram())
        except HistoryRejected as exc:
            return {"status": "refused", "message": str(exc)}
        except HomeUnavailable as exc:
            return {"status": "unavailable", "message": exc.message}
        except CameraUnavailable as exc:
            return {"status": "unavailable", "message": str(exc)}
        return vouch(_shown(res), True)


def camera_tools(
    alarm: Alarm,
    gate: DisarmGate,
    history: History,
    *,
    confirm_wait_s: float = CONFIRM_WAIT_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[Tool]:
    api = CameraAPI(alarm, gate, history, confirm_wait_s, sleep)
    return [
        Tool(
            "home_arm",
            "Turn on the home burglar alarm (the camera at the gate starts alerting). Say it is "
            "armed ONLY when the result says confirmed: true; otherwise say you are waiting for "
            "the laptop. Use when the owner says 'arm the house' or is leaving.",
            {
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["away", "night"]}},
            },
            ActionRisk.REVERSIBLE,
            api.arm,
            agent="home",
            check=_check_arm,
            summarize=_card_arm,
            spoken_ok=True,
            activity_words=ARMED_WORDS,
        ),
        Tool(
            "home_disarm",
            "The home alarm cannot be turned off by JARVIS. Calling this only tells the owner to "
            "press Disarm in the Home panel with his passkey. Never say the alarm is off.",
            {"type": "object", "properties": {}},
            ActionRisk.READ_ONLY,
            api.disarm,
            agent="home",
            activity_words=DISARM_WORDS,
        ),
        Tool(
            "camera_history",
            "Search what the home camera saw (people, cars, packages): times, places and counts "
            "only. You never see pictures and never describe how anyone looks. Anyone the result "
            "does not name is 'someone JARVIS didn't recognise' - never a name, never 'probably'. "
            "Give start and end as ISO times with an offset (turn 'yesterday' into a range).",
            {
                "type": "object",
                "properties": {
                    "what": {"type": "string", "enum": list(WHAT_VALUES)},
                    "start": {"type": "string", "description": "ISO time with offset"},
                    "end": {"type": "string", "description": "ISO time with offset"},
                    "camera": {"type": "string"},
                    "zone": {"type": "string"},
                    "who": {
                        "type": "string",
                        "description": "known, unknown or a person id from faces_list",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
                },
                "required": ["start", "end"],
            },
            ActionRisk.READ_ONLY,
            api.history,
            agent="camera",
            check=_check_history,
            may_vouch=True,
            activity_words=SEARCHED_WORDS,
        ),
    ]


__all__ = [
    "ARMED_WORDS",
    "DISARM_ANSWER",
    "DISARM_WORDS",
    "NO_ZONES",
    "PENDING",
    "SEARCHED_WORDS",
    "CameraAPI",
    "camera_tools",
    "via_of",
]
