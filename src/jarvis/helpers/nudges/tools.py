# src/jarvis/helpers/nudges/tools.py
"""Part C's `nudge_*` tools (plan D6, D16 row `nudges`): every call passes the gateway (policy,
cards, audit by an argument hash, Activity by fixed words). Answers are JARVIS's fixed templates.

- `nudge_status` (R1): which nudges are on, snoozed or stopped, and today's water and stand-ups.
- `nudge_set` (R2): switch a nudge on/off, every N minutes, its window, days, times, the meeting
  variant and its word, the activity words. A card when the round read outside content.
- `nudge_snooze` / `nudge_stop` / `nudge_resume` (R2): the gate's own state (`GateStore`, the same
  documents the Helpers tab's taps change). Stop is for today; "for good" switches it off. Never
  a reminder: "don't remind me to stand up" stops the nudge.
- `nudge_water_log`, `nudge_standup_log`, `nudge_activity_checkin` (R2): the sealed log (off with
  no keyring, said in plain words).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.gate import ALL
from jarvis.helpers.nudges import activity, hydrate
from jarvis.helpers.nudges.models import LABEL, NUDGE_KINDS
from jarvis.helpers.nudges.service import NudgeService
from jarvis.helpers.nudges.store import OFF_WORDS, WellbeingOff
from jarvis.helpers.nudges.words import a_bool, a_kind, a_number, changes, describe
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context
from jarvis.tools.taint import content_tainted

R1, R2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE
AGENT = "nudges"
KIND_ARG = {
    "type": "string",
    "description": "Which nudge: standup, water, activity, free_time, focus (or all).",
}
_OBJ: dict[str, Any] = {"type": "object", "additionalProperties": False}
Run = Callable[[dict[str, Any]], Awaitable[Any]]


def _uid() -> str:
    return require_tool_context().user_id


def _name(kind: str) -> str:
    return "every nudge" if kind == ALL else f"the {LABEL[kind].lower()} nudge"


def _tool(
    name: str, text: str, props: dict[str, Any], risk: ActionRisk, run: Run, **kw: Any
) -> Tool:
    schema = {**_OBJ, "properties": props, "required": kw.pop("required", [])}
    words = kw.pop("words", text)
    return Tool(name, text, schema, risk, run, agent=AGENT, activity_words=words, **kw)


def _status_tool(svc: NudgeService) -> Tool:
    async def run(a: dict[str, Any]) -> dict[str, Any]:
        uid = _uid()
        s, gate = await svc.settings(uid), await svc.gate.state(uid)
        day = svc.day_of().isoformat()
        lines = [describe(k, s.nudge(k)) for k in NUDGE_KINDS]
        held = [LABEL[k] for k in NUDGE_KINDS if gate.stopped_on(k, day)]
        if held:
            lines.append("Stopped for today: " + ", ".join(held) + ".")
        if svc.well.on:
            logged = await svc.well.day(uid, day)
            lines.append(f"Today: {logged.water} glasses of water, {logged.stood} stand-ups.")
        return {"spoken": " ".join(lines), "on": list(s.on_kinds())}

    return _tool(
        "nudge_status",
        "Show which nudges are on, and today's water and stand-ups.",
        {},
        R1,
        run,
        trusted_output=True,
        words="Looked at the nudges",
    )


def _set_tool(svc: NudgeService) -> Tool:
    props = {
        "kind": KIND_ARG,
        "on": {"type": "boolean"},
        "every_minutes": {"type": "integer", "minimum": 15, "maximum": 240},
        "start": {"type": "string", "description": "HH:MM, the window opens"},
        "end": {"type": "string", "description": "HH:MM, the window closes"},
        "days": {"type": "string", "description": "e.g. 'Monday to Saturday', 'weekdays'"},
        "times": {"type": "string", "description": "focus / free time: 'HH:MM, HH:MM'"},
        "meeting": {"type": "boolean", "description": "stand-up: also 10 min before the meeting"},
        "word": {"type": "string", "description": "stand-up: the word the meeting's title holds"},
        "words": {"type": "string", "description": "activity: his words, e.g. 'walk, gym'"},
    }

    async def run(a: dict[str, Any]) -> dict[str, Any]:
        kind, change = a_kind(a.get("kind"), allow_all=False), changes(a)
        if not change:
            raise ValueError("What should change, Sir? On or off, every N minutes, or the times.")
        new = await svc.store.change(_uid(), lambda s: s.changed(kind, change))
        return {"spoken": "Done, Sir. " + describe(kind, new.nudge(kind))}

    return _tool(
        "nudge_set",
        "Switch a nudge on or off, or change how often and when it comes.",
        props,
        R2,
        run,
        required=["kind"],
        ask_when=lambda a: content_tainted(),
        words="Changed a nudge",
        summarize=lambda a: "Change a nudge's settings",
    )


def _snooze_tool(svc: NudgeService) -> Tool:
    props = {
        "kind": KIND_ARG,
        "minutes": {"type": "integer", "minimum": 15, "maximum": 720},
        "until": {"type": "string", "description": "'tomorrow' to hold it until tomorrow"},
    }

    async def run(a: dict[str, Any]) -> dict[str, Any]:
        uid, kind = _uid(), a_kind(a.get("kind") or "all")
        if str(a.get("until", "")).strip().lower() in ("tomorrow", "until tomorrow"):
            await svc.gate.stop_today(uid, kind, svc.day_of().isoformat())
            return {"spoken": f"Snoozed {_name(kind)} until tomorrow, Sir."}
        minutes = a_number(a.get("minutes", 60), lo=15, hi=720, what="minutes")
        await svc.gate.snooze(uid, kind, minutes, svc.now())
        return {"spoken": f"Snoozed {_name(kind)} for {minutes} minutes, Sir."}

    return _tool(
        "nudge_snooze",
        "Snooze a nudge (15 minutes to 12 hours, or until tomorrow).",
        props,
        R2,
        run,
        words="Snoozed a nudge",
    )


def _stop_tool(svc: NudgeService) -> Tool:
    props = {
        "kind": KIND_ARG,
        "for_good": {
            "type": "boolean",
            "description": "true: switch it off until he turns it on again",
        },
    }

    async def run(a: dict[str, Any]) -> dict[str, Any]:
        uid, kind = _uid(), a_kind(a.get("kind") or "all")
        if a_bool(a.get("for_good", False)):
            kinds = NUDGE_KINDS if kind == ALL else (kind,)

            def off(s: Any) -> Any:
                for k in kinds:
                    s = s.changed(k, {"on": False})
                return s

            await svc.store.change(uid, off)
            return {"spoken": f"Switched off {_name(kind)}, Sir. Say 'turn it on' to have it back."}
        await svc.gate.stop_today(uid, kind, svc.day_of().isoformat())
        return {
            "spoken": f"Stopped {_name(kind)} for today, Sir. "
            "Say 'turn it off for good' to stop it altogether."
        }

    return _tool(
        "nudge_stop",
        "Stop a nudge for today ('no more nudges today'), or for good. "
        "Use this, never a reminder, for 'don't remind me to stand up'.",
        props,
        R2,
        run,
        words="Stopped a nudge",
    )


def _resume_tool(svc: NudgeService) -> Tool:
    async def run(a: dict[str, Any]) -> dict[str, Any]:
        uid, kind = _uid(), a_kind(a.get("kind") or "all")
        await svc.gate.resume(uid, kind)
        s = await svc.settings(uid)
        off = [LABEL[k].lower() for k in NUDGE_KINDS if (kind in (ALL, k)) and not s.nudge(k).on]
        tail = f" It's switched off, though: say 'turn on {off[0]}'." if len(off) == 1 else ""
        return {"spoken": f"Resumed {_name(kind)}, Sir.{tail}"}

    return _tool(
        "nudge_resume",
        "Undo a snooze or a stop for today.",
        {"kind": KIND_ARG},
        R2,
        run,
        words="Resumed a nudge",
    )


def _logged(fn: Run) -> Run:
    async def run(a: dict[str, Any]) -> dict[str, Any]:
        try:
            return dict(await fn(a))
        except WellbeingOff:
            return {"spoken": OFF_WORDS}

    return run


def _log_tools(svc: NudgeService) -> list[Tool]:
    async def water(a: dict[str, Any]) -> dict[str, Any]:
        glasses = a_number(a.get("glasses", 1), lo=1, hi=10, what="glasses")
        day = await hydrate.log_water(svc, _uid(), glasses)
        return {"spoken": f"Logged, Sir: {day.water} glasses of water today."}

    async def stood(a: dict[str, Any]) -> dict[str, Any]:
        day = await hydrate.log_stood(svc, _uid())
        return {"spoken": f"Logged, Sir: {day.stood} stand-ups today."}

    async def checkin(a: dict[str, Any]) -> dict[str, Any]:
        word, outcome = str(a.get("word", "")).strip().lower(), str(a.get("outcome", ""))
        if outcome not in ("done", "missed", "moved") or not 2 <= len(word) <= 30:
            raise ValueError("Say which activity and whether it was done, missed or moved.")
        uid = _uid()
        words = (await svc.settings(uid)).nudge("nudge_activity").words
        if word not in words:
            listed = ", ".join(words) or "none yet"
            return {"spoken": f"That isn't one of your planned activities, Sir. Yours: {listed}."}
        await activity.check_in(svc, uid, word, outcome)  # type: ignore[arg-type]
        return {"spoken": f"Noted, Sir: your {word} is {outcome}."}

    glasses = {"glasses": {"type": "integer", "minimum": 1, "maximum": 10}}
    check = {
        "word": {"type": "string", "description": "his activity word, e.g. walk"},
        "outcome": {"type": "string", "enum": ["done", "missed", "moved"]},
    }
    return [
        _tool(
            "nudge_water_log",
            "Log glasses of water he drank.",
            glasses,
            R2,
            _logged(water),
            words="Logged water",
        ),
        _tool(
            "nudge_standup_log",
            "Log that he stood up and moved.",
            {},
            R2,
            _logged(stood),
            words="Logged a stand-up",
        ),
        _tool(
            "nudge_activity_checkin",
            "Check in a planned activity: done, missed or moved.",
            check,
            R2,
            _logged(checkin),
            required=["word", "outcome"],
            words="Checked in an activity",
        ),
    ]


def nudge_tools(svc: NudgeService) -> list[Tool]:
    return [
        _status_tool(svc),
        _set_tool(svc),
        _snooze_tool(svc),
        _stop_tool(svc),
        _resume_tool(svc),
        *_log_tools(svc),
    ]


__all__ = ["AGENT", "nudge_tools"]
