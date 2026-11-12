# src/jarvis/series/tools.py
"""The plan tools (R11.1 O2b; docs/plans/r11-1-observations.md D6, D7; Layer 5/6, Task &
Productivity). All in the "Calendar plans" row (`series_*`).

series_list        R1  his plans: counts, the next session, the ones waiting for an answer.
                       Numbers and times only (titles stay in the calendar), so it is his own
                       list: trusted, it does not taint the round.
series_checkin     R2  {answer: done | skipped, series?, session?}: record whether a session
                       happened: the named one, else the one that is waiting. It changes only
                       JARVIS's own record and is easy to put right, so a spoken answer runs
                       without a card (`spoken_ok`). "skipped" then PROPOSES the re-plan through
                       the gateway: one `series_reschedule` card in the same conversation.
series_reschedule  R2  {series?, session?}: move a skipped session and every later one to the
                       next free slots. `ask_when` always: ONE approval card, whoever asks. The
                       card is written by a read-only look-up (`SeriesService.proposal`): how
                       many move, the count before and after, every "old date -> new date". At
                       approval the gateway looks again: if the calendar changed, the card is
                       withdrawn and proposed anew. Nothing moves before the approval; a re-plan
                       that would lose a session is refused in code (`replan.verify`).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.series import cards
from jarvis.series.models import OPEN_STATES, Plan, ReplanRefused
from jarvis.series.service import NOT_LINKED, SeriesService, Waiting
from jarvis.series.store import PlansUnreadable
from jarvis.tools.base import Preview, Tool
from jarvis.tools.context import require_tool_context
from jarvis.tools.provenance import vouch

log = get_logger(__name__)

LIST, CHECKIN, RESCHEDULE = "series_list", "series_checkin", "series_reschedule"
ANSWERS = ("done", "skipped")
SERIES_MAX = 80
NO_DATES = "I couldn't propose new dates just now; say 're-plan my sessions' to try again."
# a look-up the gateway refused is ITS fixed words, then "(<error class>: <its words>)". Only these
# two classes carry JARVIS's own sentences (numbers, never a title); the whole error must be
# exactly that shape (`fullmatch`), so a reason quoted inside another error is never repeated.
LOOKUP_FAILED = "could not look it up first, so nothing was proposed or done"
_OWN_REASON = re.compile(
    re.escape(LOOKUP_FAILED) + r" \((?P<kind>ReplanRefused|GoogleNotConnected): (?P<why>.{1,160})\)"
)
_SERIES = {"type": "string", "maxLength": SERIES_MAX, "description": "The plan's name or id."}
_SESSION = {"type": "integer", "minimum": 1, "description": "The session's number in the plan."}


def session_arg(value: Any) -> int | None:
    """A session number as a whole number or its digits (a No-AI phrase sends text)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | str) or not str(value).isdigit():
        raise ValueError("session must be the session's number")
    n = int(value)
    if not 1 <= n <= 999:
        raise ValueError("session must be the session's number")
    return n


def _series_arg(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > SERIES_MAX:
        raise ValueError("series must be the plan's name")
    return value


def own_reason(error: str | None) -> str:
    """Why a re-plan was not proposed, in JARVIS's own words; "" when the reason isn't his."""
    found = _OWN_REASON.fullmatch(error or "")
    if found is None:
        return ""
    return NOT_LINKED if found["kind"] == "GoogleNotConnected" else found["why"]


def _refused(message: str) -> Any:
    return vouch({"refused": True, "message": message}, True)  # our own words only


def _view(plan: Plan, waiting: list[Waiting]) -> dict[str, Any]:
    upcoming = sorted((s for s in plan.sessions if s.state in OPEN_STATES), key=lambda s: s.start)
    asked = {w.session.n for w in waiting if w.plan.id == plan.id}
    nxt = next((s for s in upcoming if s.n not in asked), None)
    return {
        "id": plan.id,
        "name": "" if plan.outside else plan.name,  # a name a file gave is not repeated
        "sessions": plan.total,
        "done": sum(s.state == "done" for s in plan.sessions),
        "skipped": sum(s.state == "skipped" for s in plan.sessions),
        "waiting": sorted(asked, reverse=True),
        "next": {"n": nxt.n, "start": nxt.start.isoformat()} if nxt is not None else None,
    }


class SeriesTools:
    """`gateway`: read when a call runs (the gateway is built after this part)."""

    def __init__(self, svc: SeriesService, gateway: Callable[[], Any]) -> None:
        self._svc, self._gateway = svc, gateway

    async def list(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        try:
            book, waiting = await self._svc.book(uid), await self._svc.waiting(uid)
        except PlansUnreadable as exc:
            return _refused(str(exc))
        plans = [_view(p, waiting) for p in book.plans]
        note = "" if plans else "You follow no plan yet, Sir."
        return vouch({"plans": plans, **({"message": note} if note else {})}, True)

    def check_answer(self, a: dict[str, Any]) -> None:
        if a.get("answer") not in ANSWERS:
            raise ValueError("answer must be done or skipped")
        session_arg(a.get("session"))
        _series_arg(a.get("series"))

    async def checkin(self, a: dict[str, Any]) -> Any:
        ctx = require_tool_context()
        try:
            got = await self._svc.mark(
                ctx.user_id,
                a["answer"],
                series=_series_arg(a.get("series")),
                session=session_arg(a.get("session")),
            )
        except (LookupError, PlansUnreadable) as exc:
            return _refused(str(exc))
        words = cards.marked(got.plan, got.session)
        out: dict[str, Any] = {
            "marked": got.session.state,
            "session": got.session.n,
            "of": got.plan.total,
            "plan": got.plan.id,
        }
        if a["answer"] == "skipped":
            words, extra = await self._propose(ctx.scope, got, words)
            out.update(extra)
        return vouch({**out, "message": words}, True)

    async def _propose(self, scope: str, got: Waiting, words: str) -> tuple[str, dict[str, Any]]:
        """The re-plan card for a session just marked skipped, through the gateway (its policy,
        the message's card budget, the audit). Never raises: the mark stands either way."""
        gateway = self._gateway()
        if gateway is None:
            return f"{words} {NO_DATES}", {}
        args = {"series": got.plan.id, "session": got.session.n}
        call = ToolCall(id=f"replan-{uuid.uuid4().hex[:8]}", name=RESCHEDULE, arguments=args)
        try:
            res = await gateway.execute(call, scope=scope)
        except Exception as exc:  # noqa: BLE001 - the answer is recorded; say what is missing
            log.warning("re-plan not proposed", extra={"error": type(exc).__name__})
            return f"{words} {NO_DATES}", {}
        if res.pending is None:
            why = own_reason(res.error)
            return f"{words} {why or NO_DATES}", {"why": why or res.outcome.value}
        head = res.pending.summary.splitlines()[0]
        said = f"{words} A new schedule is waiting for your approval. {head}"
        return said, {"approval": {"id": res.pending.id, "will_do": head}}

    def check_move(self, a: dict[str, Any]) -> None:
        session_arg(a.get("session"))
        _series_arg(a.get("series"))

    async def preview_move(self, a: dict[str, Any]) -> Preview:
        uid = require_tool_context().user_id
        p = await self._svc.proposal(
            uid, _series_arg(a.get("series")), session_arg(a.get("session"))
        )
        return Preview(cards.replan_card(p.plan, p.session, p.moves, p.tz, p.kept))

    async def move(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        try:
            done = await self._svc.move(
                uid, _series_arg(a.get("series")), session_arg(a.get("session"))
            )
        except (LookupError, ReplanRefused, PlansUnreadable) as exc:
            return _refused(str(exc))
        return vouch(
            {
                "moved": done.moved,
                "kept": done.kept,
                "missing": done.missing,
                "failed": done.failed,
                "unconfirmed": done.unconfirmed,
                "left": [n for n, _ in done.left],  # numbers only: never a title
                "recorded": not done.unrecorded,
                "sessions": done.plan.total,
                "message": cards.moved_words(done.plan, done),
            },
            True,
        )


def series_tools(svc: SeriesService, gateway: Callable[[], Any]) -> list[Tool]:
    api = SeriesTools(svc, gateway)
    return [
        Tool(
            LIST,
            "The owner's followed plans (study plans and other series of calendar sessions): "
            "how many sessions, how many done or skipped, the next one, and which wait for "
            "his answer.",
            {"type": "object", "properties": {}},
            ActionRisk.READ_ONLY,
            api.list,
            agent="plans",
            may_vouch=True,
        ),
        Tool(
            CHECKIN,
            "Record whether a session of a followed plan happened: answer done or skipped. "
            "Without a session number it is the session JARVIS last asked about. 'skipped' "
            "also puts a new schedule on an approval card (nothing moves until he approves).",
            {
                "type": "object",
                "properties": {
                    "answer": {"type": "string", "enum": list(ANSWERS)},
                    "series": _SERIES,
                    "session": _SESSION,
                },
                "required": ["answer"],
            },
            ActionRisk.REVERSIBLE,
            api.checkin,
            agent="plans",
            check=api.check_answer,
            summary_template="Mark a plan session as {answer}",
            spoken_ok=True,
            may_vouch=True,
            activity_words="A plan session marked done or skipped",
        ),
        _reschedule(api),
    ]


def _reschedule(api: SeriesTools) -> Tool:
    """`series_reschedule`: always one card (`ask_when`), its text from a read-only look-up."""
    return Tool(
        RESCHEDULE,
        "Move a skipped session of a followed plan, and every later one, to the next free "
        "slots of the plan's own weekdays and time (always an approval card first, listing "
        "every old and new date; the number of sessions never changes). Without arguments: "
        "the session he last skipped.",
        {"type": "object", "properties": {"series": _SERIES, "session": _SESSION}},
        ActionRisk.REVERSIBLE,
        api.move,
        agent="plans",
        check=api.check_move,
        preview=api.preview_move,
        ask_when=lambda _a: True,
        may_vouch=True,
        activity_words="Plan sessions moved to new dates",
    )


__all__ = [
    "ANSWERS",
    "CHECKIN",
    "LIST",
    "RESCHEDULE",
    "SeriesTools",
    "own_reason",
    "series_tools",
    "session_arg",
]
