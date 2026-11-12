# evals/r11_1/plan.py
"""R11.1 eval, Part A (`plan`): observations O1, O2, O2b and O12 on fakes (a scripted brain that
can answer empty, cut off or with sixty single calls; an in-memory Google Calendar and Gmail),
through the real Brain, Gateway and the part's own `build(ctx)`. Every gate is decided by what
the model was SENT, what the owner was told and what the fake Google RECEIVED.

O1   a 60-row CSV plus "add these to my calendar" ends in a real answer or ONE approval card
     when the brain answers empty, cut off, or with sixty single calls; the old filler is never
     a reply and never stored; a retry happens at most once and is paid for; a model's window
     never holds a filler or a fixed line; the round-limit summary and the stream do the same.
O2   sixty events are one card listing sixty, one approval, sixty creates; a failed create is
     reported by item and a retry creates nothing twice; one Undo removes them and leaves a
     changed event alone; a guest is refused; the model's own undo is a card.
O2b  "skipped" on session 7 of 60 moves 54, the count stays 60, a busy evening is avoided and
     nothing moves before the approval; the check-in is sent once, held at night, and an answer
     works with no model at all.
O12  unread mail in Updates and Promotions is counted, the count is the INBOX label's, a
     one-time code is withheld, and "Never" on the mail row means no read: for the tool and
     for the morning brief's own background read.

Controls (each must make its own cases fail, or this part reports that its control is too weak):
  filler      the old line restored: `reply = completion.text or FILLER`, no retry
  singles     the batch split into single calls: many single creates are no longer gathered
  drop_last   the re-plan drops its last session
  primary     the Primary-only query of the last day
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from r11_1_fakes_a import (
    CUT,
    UID,
    PlanGoogle,
    PlanRig,
    Said,
    ScriptedBrain,
    call,
    connector,
    followed,
    letter,
    plan_rig,
    weekday_sessions,
)

from jarvis.brief.collect import Collector
from jarvis.config import Settings
from jarvis.core import brain as brain_module
from jarvis.core import finish
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ConfirmationGate
from jarvis.core.models import ChatRequest, Session, Turn
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.llm.base import Role, ToolCall
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.no_ai import run_no_ai
from jarvis.series import replan
from jarvis.series.phrases import route
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import calendar_batch as cb
from jarvis.tools import gmail_digest as gd
from jarvis.tools.audit import AuditLog
from jarvis.tools.background import BackgroundReads
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.google_calendar import calendar_tools
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust

PART = "plan"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]
IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 11, 12, 9, 0, tzinfo=IST)
AFTER_7 = datetime(2026, 11, 24, 20, 20, tzinfo=IST)  # twenty minutes after session 7
DAY = date(2026, 11, 12)
TIERS = {t: f"mock-{t.value}" for t in ModelTier}
OLD_FILLER = "I have nothing to add, Sir."
ASK = "add these to my calendar"
CODE = "482913"
OLD_QUERY = "is:unread in:inbox category:primary newer_than:1d"
CONTROL_OF = {"o1": "filler", "o2": "singles", "o2b": "drop_last", "o12": "primary"}
# "singles" is O2's control, and the case it must fail is the brain's: sixty single calls
TARGET = {"singles": "o1-sixty-single-calls"}


def _check(ok: bool, why: str) -> list[str]:
    return [] if ok else [why]


# ---- O1: the brain ------------------------------------------------------------------------------
class Mind:
    """The real Brain over a scripted model, the plan part's tools and a 60-row CSV to attach."""

    def __init__(self, rig: PlanRig) -> None:
        self.rig, self.model, self.store = rig, ScriptedBrain(), InMemorySessionStore()
        for t in calendar_tools(rig.state["google"], undo=rig.bin):
            rig.gw.registry.register(t)  # the single-event tool the batch replaces
        self.docs = DocumentService(AttachmentStore(MemoryDocs()))
        self.brain = Brain(
            router=ModelRouter(self.model, TIERS),
            store=self.store,
            settings=Settings(_env_file=None, env="dev"),
            gateway=rig.gw,
            documents=self.docs,
        )

    async def ask(self, text: str = ASK, **kw: Any) -> Any:
        rows = ["topic,start,end", *(f"{e['summary']},{e['start']},{e['end']}" for e in SIXTY)]
        ref = await self.docs.upload(UID, "plan.csv", "\n".join(rows).encode())
        return await self.brain.chat(
            ChatRequest(message=text, user_id=UID, attachments=[ref.id], **kw)
        )

    async def turns(self, sid: str) -> list[Turn]:
        session = await self.store.get(sid)
        return session.turns if session is not None else []

    def sent(self) -> str:
        """Everything any model call was sent, as one text."""
        out: list[str] = []
        for c in self.model.calls:
            out += [m.content if isinstance(m.content, str) else m.text() for m in c.messages]
        return "\n".join(out)


SIXTY = weekday_sessions(60)


async def _mind() -> Mind:
    return Mind(await plan_rig(T0))


async def _clean(m: Mind, resp: Any) -> list[str]:
    """The old filler is neither the reply nor a stored turn."""
    stored = [t.content for t in await m.turns(resp.session_id)]
    return _check(OLD_FILLER not in resp.reply, "the reply is the old filler") + _check(
        all(OLD_FILLER not in t for t in stored), "the old filler was stored"
    )


async def _o1_empty_answer() -> list[str]:
    m = await _mind()
    m.model.say(Said(""))
    resp = await m.ask()
    last = (await m.turns(resp.session_id))[-1]
    return (
        await _clean(m, resp)
        + _check(resp.reply == finish.EMPTY, f"reply {resp.reply!r}")
        + _check(last.tool_derived is True, "the fixed line is stored as a model's own words")
    )


async def _o1_cut_off_then_words() -> list[str]:
    m = await _mind()
    m.model.say(Said("", stop=CUT, cost_usd=0.02), Said("Here is the plan, Sir.", cost_usd=0.01))
    resp = await m.ask()
    paid = abs(resp.cost_usd - 0.03) < 1e-9
    return (
        await _clean(m, resp)
        + _check(resp.reply == "Here is the plan, Sir.", f"reply {resp.reply!r}")
        + _check(len(m.model.calls) == 2, f"{len(m.model.calls)} model calls, want 2")
        + _check(paid, f"cost {resp.cost_usd}: the retry was not paid for")
        + _check(m.model.calls[-1].max_tokens == m.brain.s.work_output_tokens, "no working cap")
    )


async def _o1_cut_off_twice() -> list[str]:
    m = await _mind()
    m.model.say(Said("", stop=CUT), Said("", stop=CUT), Said("never asked"))
    resp = await m.ask()
    return (
        await _clean(m, resp)
        + _check(resp.reply == finish.CUT_OFF, f"reply {resp.reply!r}")
        + _check(len(m.model.calls) == 2, f"{len(m.model.calls)} model calls: more than one retry")
    )


def _singles() -> tuple[ToolCall, ...]:
    return tuple(call(cb.SINGLE, i, **e) for i, e in enumerate(SIXTY))


async def _o1_sixty_single_calls() -> list[str]:
    m = await _mind()
    m.model.say(Said(calls=_singles()), Said(""))
    resp = await m.ask()
    cards = resp.pending_approvals
    one = len(cards) == 1 and cards[0].tool == cb.CREATE
    return (
        await _clean(m, resp)
        + _check(one, f"{len(cards)} cards: {[c.tool for c in cards]}")
        + _check(one and len(cards[0].arguments["events"]) == 60, "the card does not list sixty")
        + _check(resp.reply == "I've prepared 1 approval for you, Sir.", f"reply {resp.reply!r}")
        + _check(m.rig.fake.sent("POST", "/events") == [], "an event was made before approval")
    )


async def _o1_window_has_no_filler() -> list[str]:
    m = await _mind()
    old = Session(user_id=UID)
    for role, text in [(Role.USER, "add them"), (Role.ASSISTANT, OLD_FILLER)] * 3:
        old.append(Turn(role=role, content=text))
    await m.store.save(old)
    m.model.say(Said(""), Said("On it, Sir."))
    first = await m.brain.chat(ChatRequest(message=ASK, user_id=UID, session_id=old.id))
    second = await m.brain.chat(ChatRequest(message="go on", user_id=UID, session_id=old.id))
    seen = m.sent()
    return (
        _check(first.reply == finish.EMPTY and second.reply == "On it, Sir.", "wrong replies")
        + _check(OLD_FILLER not in seen, "a model was shown the old filler")
        + _check("empty answer" not in seen, "a model was shown a fixed line")
    )


async def _o1_round_limit() -> list[str]:
    m = await _mind()
    rounds = m.brain.s.tool_max_rounds
    m.model.say(*(Said(calls=(call("series_list", i),)) for i in range(rounds)), Said(""))
    resp = await m.ask()
    want = f"I did {rounds} steps but the AI gave me no words to report them."
    return await _clean(m, resp) + _check(resp.reply.startswith(want), f"reply {resp.reply!r}")


async def _o1_stream() -> list[str]:
    m = await _mind()

    async def stream(text: str) -> str:
        req = ChatRequest(message=text, user_id=UID)
        return "".join([d async for d in m.brain.chat_stream(req)])

    m.model.say(Said(""))
    empty = await stream("hello")
    m.model.say(Said("", stop=CUT), Said("", stop=CUT), Said("never asked"))
    before = len(m.model.calls)
    cut = await stream("write the long plan")
    stored = [t.content for s in await m.store.list_for_user(UID) for t in await m.turns(s.id)]
    return (
        _check(empty == finish.EMPTY, f"silent stream said {empty!r}")
        + _check(cut == finish.CUT_OFF, f"cut-off stream said {cut!r}")
        + _check(len(m.model.calls) - before == 2, "the stream retried more than once")
        + _check(all(OLD_FILLER not in t and t.strip() for t in stored), "a filler or empty turn")
    )


# ---- O2: the batch ------------------------------------------------------------------------------
BATCH_ARGS: dict[str, Any] = {"events": SIXTY, "title_prefix": "CCA"}


async def _o2_one_card() -> list[str]:
    rig = await plan_rig(T0)
    with context_trust(untrusted=True):  # the list came from a file
        asked = await rig.run(cb.CREATE, BATCH_ARGS)
    cards = await rig.gw.pending()
    ok = asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION and len(cards) == 1
    return (
        _check(ok, f"{asked.outcome.value}, {len(cards)} cards")
        + _check(ok and len(cards[0].arguments["events"]) == 60, "the card does not list sixty")
        + _check(ok and "60 events" in cards[0].summary, "the card does not say sixty")
        + _check(rig.fake.sent("POST", "/events") == [], "an event was made before approval")
    )


async def _o2_one_approval_sixty_creates() -> list[str]:
    rig = await plan_rig(T0)
    out = await rig.approved(cb.CREATE, BATCH_ARGS)
    res = out.result if out.outcome is GatewayOutcome.EXECUTED else {}
    marks = {cb.number_of(e, res.get("batch", "")) for e in rig.fake.live()}
    return (
        _check(out.outcome is GatewayOutcome.EXECUTED, f"{out.outcome.value}: {out.error}")
        + _check(len(rig.fake.sent("POST", "/events")) == 60, "not sixty creates")
        + _check(res.get("created") == 60 and len(res.get("items", [])) == 60, "no per-item result")
        + _check(marks == set(range(1, 61)), "the events do not carry their batch numbers")
        + _check(rig.fake.most_at_once <= 5, "more than five writes at a time")
    )


async def _o2_failed_item_and_retry() -> list[str]:
    rig = await plan_rig(T0)
    rig.fake.fail_creates = {7: 400}
    first = (await rig.approved(cb.CREATE, BATCH_ARGS)).result
    bad = [i for i in first["items"] if i["status"] == "failed"]
    rig.fake.fail_creates = {}
    again = [{**SIXTY[i["n"] - 1], "n": i["n"]} for i in bad]
    retry_args = {"events": again, "title_prefix": "CCA", "batch": first["batch"]}
    second = (await rig.approved(cb.CREATE, retry_args)).result
    whole = (await rig.approved(cb.CREATE, {**BATCH_ARGS, "batch": first["batch"]})).result
    numbers = sorted(cb.number_of(e, first["batch"]) or 0 for e in rig.fake.live())
    return (
        _check(first["created"] == 59 and len(bad) == 1, f"first run: {first['message']}")
        + _check(bool(bad) and bool(bad[0].get("why")), "the failed item gives no reason")
        + _check(second.get("created") == 1, f"the retry: {second.get('message')}")
        + _check(whole.get("created") == 0 and whole.get("already_there") == 60, "made twice")
        + _check(numbers == list(range(1, 61)), f"{len(numbers)} events, or a number twice")
    )


async def _o2_one_undo() -> list[str]:
    rig = await plan_rig(T0)
    made = (await rig.approved(cb.CREATE, BATCH_ARGS)).result
    kept = rig.fake.live()[9]["id"]
    rig.fake.owner_edits(kept, location="Library")  # he changed this one himself
    asked = await rig.run(cb.UNDO, {"batch": made["batch"]})
    waiting = asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION and len(rig.fake.live()) == 60
    done = await rig.run(cb.UNDO, {"batch": made["batch"]}, confirmation_id=asked.pending.id)
    res = done.result if done.outcome is GatewayOutcome.EXECUTED else {}
    binned = await rig.bin.store.recent(UID, limit=100)
    return (
        _check(waiting, "the model's undo ran without a card")
        + _check((res.get("removed"), res.get("kept")) == (59, 1), f"undo: {res.get('message')}")
        + _check([e["id"] for e in rig.fake.live()] == [kept], "the changed event was not kept")
        + _check(len(binned) == 59, f"{len(binned)} in Recently deleted, want 59")
    )


async def _o2_guest_refused() -> list[str]:
    rig = await plan_rig(T0)
    events = [dict(e) for e in SIXTY[:5]]
    events[2]["attendees"] = ["guest@example.com"]
    out = await rig.run(cb.CREATE, {"events": events})
    return (
        _check(out.outcome is GatewayOutcome.ERROR, f"a guest was accepted: {out.outcome.value}")
        + _check(await rig.gw.pending() == [], "a card was made")
        + _check(rig.fake.requests == [], "Google was called")
    )


async def _o2_always_a_card() -> list[str]:
    allow = [PolicyRule(tool_pattern="calendar_*", effect=Effect.ALLOW)]
    rig = await plan_rig(T0, rules=allow)
    with context_trust(untrusted=False):  # his own typed words, and his row says Allow
        asked = await rig.run(cb.CREATE, {"events": SIXTY[:4]})
        made = await rig.run(cb.CREATE, {"events": SIXTY[:4]}, confirmation_id=asked.pending.id)
        undo = await rig.run(cb.UNDO, {"batch": made.result["batch"]})
    return _check(
        asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION, "a batch ran without a card"
    ) + _check(undo.outcome is GatewayOutcome.AWAITING_CONFIRMATION, "an undo ran without a card")


# ---- O2b: the followed series -------------------------------------------------------------------
async def _skipped(rig: PlanRig) -> Any:
    await followed(rig, 60)
    rig.clock.at = AFTER_7
    return await rig.run("series_checkin", {"answer": "skipped"})


async def _o2b_skip_moves_54() -> list[str]:
    rig = await plan_rig(T0)
    out = await _skipped(rig)
    cards = await rig.gw.pending()
    if len(cards) != 1 or cards[0].tool != "series_reschedule":
        return [f"no re-plan card: {out.result.get('message') if out.result else out.error}"]
    before = len(rig.fake.sent("PATCH"))
    done = await rig.approve(cards[0].id)
    plan = (await rig.svc.book(UID)).plans[0]
    starts = [s.start for s in plan.sessions]
    return (
        _check("Move 54 sessions" in cards[0].summary, cards[0].summary.splitlines()[0])
        + _check("60 sessions before, 60 after" in cards[0].summary, "the count is not on the card")
        + _check(cards[0].summary.count(" → ") == 54, "the card does not list 54 moves")
        + _check(before == 0, "a session moved before the approval")
        + _check(done.outcome is GatewayOutcome.EXECUTED, f"{done.outcome.value}: {done.error}")
        + _check(len(rig.fake.sent("PATCH")) == 54, f"{len(rig.fake.sent('PATCH'))} moves")
        + _check(plan.total == 60 and len(set(starts)) == 60, "a session was lost")
        + _check(len(rig.fake.live()) == 60, "an event was lost")
    )


async def _o2b_busy_avoided() -> list[str]:
    rig = await plan_rig(T0)
    await followed(rig, 10)
    rig.fake.events["dinner"] = {
        "id": "dinner",
        "status": "confirmed",
        "summary": "Dinner",
        "start": {"dateTime": "2026-11-30T18:30:00+05:30"},
        "end": {"dateTime": "2026-11-30T20:30:00+05:30"},
    }
    rig.clock.at = AFTER_7
    await rig.run("series_checkin", {"answer": "skipped"})
    cards = await rig.gw.pending()
    if len(cards) != 1:
        return ["no re-plan card"]
    return _check("Mon 30 Nov" not in cards[0].summary, "a session was put on a busy evening")


async def _o2b_refuses_a_lost_session() -> list[str]:
    rig = await plan_rig(T0)
    await _skipped(rig)
    plan = (await rig.svc.book(UID)).plans[0]
    moves = replan.build(plan, 7, [], now=AFTER_7, tz=IST, until=AFTER_7 + timedelta(weeks=20))
    try:
        replan.verify(plan, 7, moves[:-1], now=AFTER_7)
    except ValueError as exc:
        return _check("lose a session" in str(exc), f"refused with {exc}")
    return ["a re-plan that loses a session was accepted"]


async def _o2b_checkin_once_and_held() -> list[str]:
    rig = await plan_rig(T0)
    await followed(rig, 3)
    job = rig.part.clock_jobs[0]
    rig.clock.at = datetime(2026, 11, 16, 20, 20, tzinfo=IST)
    first, second = await job.run([UID]), await job.run([UID])
    night = await plan_rig(T0)
    await followed(night, 3)
    night.told.action = "hold"
    night.clock.at = datetime(2026, 11, 16, 23, 30, tzinfo=IST)
    held, again = (
        await night.part.clock_jobs[0].run([UID]),
        await night.part.clock_jobs[0].run([UID]),
    )
    return (
        _check(first["asked"] == 1 and second["asked"] == 0, f"asked {first}, then {second}")
        + _check(len(rig.told.sent) == 1 and rig.told.sent[0][1] == "series_checkin", "not once")
        + _check(held["held"] == 1 and again == {"asked": 0, "held": 0, "failed": 0}, "night")
        + _check(len(await night.svc.waiting(UID)) == 1, "a held check-in was dropped")
    )


async def _o2b_no_ai() -> list[str]:
    rig = await plan_rig(T0)
    await followed(rig, 60)
    rig.clock.at = AFTER_7
    scope = f"{UID}:sess_noai"
    done = await run_no_ai(rig.gw, "session 6 done", AFTER_7, scope=scope, extra=(route,))
    skipped = await run_no_ai(rig.gw, "session skipped", AFTER_7, scope=scope, extra=(route,))
    cards = await rig.gw.pending()
    return (
        _check(done.reply == "Session 6 of 60 in your CCA plan is marked done, Sir.", done.reply)
        + _check("marked skipped" in skipped.reply, skipped.reply)
        + _check(len(cards) == 1 and "Move 54 sessions" in cards[0].summary, "no re-plan card")
        + _check(rig.fake.sent("PATCH") == [], "a session moved before the approval")
    )


# ---- O12: the whole inbox -----------------------------------------------------------------------
def _inbox() -> list[dict[str, Any]]:
    return [
        letter("m01", "Priya Menon <priya@example.com>", "Budget review on Friday"),
        letter(
            "m02", "Power Board <billing@power.example>", "Your bill is ready", category="UPDATES"
        ),
        letter("m03", "Forum <news@forum.example>", "Weekly digest", category="UPDATES"),
        letter(
            "m04",
            "Bank <alerts@bank.example>",
            f"{CODE} is your one-time password",
            category="UPDATES",
            snippet=f"Use OTP {CODE} to sign in. Do not share it.",
        ),
        letter("m05", "Deals <deals@shop.example>", "50% off today", category="PROMOTIONS"),
        letter("m06", "Travel <offers@travel.example>", "Fly for less", category="PROMOTIONS"),
        letter(
            "m07",
            "Old Friend <friend@example.org>",
            "From three days ago",
            internal_ms=1_794_300_000_000 - 3 * 86_400_000,
        ),
    ]


async def _summary(**kw: Any) -> tuple[Any, PlanGoogle]:
    rig = await plan_rig(T0, **kw)
    rig.fake.mails, rig.fake.unread = _inbox(), 132
    return await rig.run(gd.SUMMARY_TOOL, {}), rig.fake


async def _o12_every_category_counted() -> list[str]:
    out, _ = await _summary()
    if out.outcome is not GatewayOutcome.EXECUTED:
        return [f"{out.outcome.value}: {out.error}"]
    got = {k: g["unread"] for k, g in out.result["groups"].items()}
    want = {"people": 2, "bills": 1, "updates": 1, "promotions": 2, "social": 0}
    return _check(got == want, f"counted {got}, want {want}")


async def _o12_count_is_the_label() -> list[str]:
    out, fake = await _summary()
    label = [r for r in fake.gmail_reads() if r.url.path.endswith("/labels/INBOX")]
    unread = out.result.get("unread") if out.result else None
    return _check(unread == 132, f"unread {unread}, want 132") + _check(
        len(label) == 1, "the INBOX label was not read exactly once"
    )


async def _o12_code_withheld() -> list[str]:
    out, _ = await _summary()
    said = json.dumps(out.result) + out.for_model()
    return (
        _check(out.result.get("withheld") == 1, f"withheld {out.result.get('withheld')}")
        + _check(CODE not in said, "the code reached the model")
        + _check("bank.example" not in said, "the bank's message reached the model")
    )


async def _o12_never_means_no_read() -> list[str]:
    out, fake = await _summary(rules=[PolicyRule(tool_pattern="gmail_*", effect=Effect.DENY)])
    return _check(out.outcome is GatewayOutcome.DENIED, f"{out.outcome.value}") + _check(
        fake.gmail_reads() == [], "Gmail was read"
    )


async def _o12_brief_whole_inbox() -> list[str]:
    fake = PlanGoogle(mails=_inbox(), unread=132)
    got = await Collector(await connector(fake), None).collect(UID, IST, DAY)
    subjects = [i.subject for i in got.data.inbox.items]
    seen = [*subjects, *got.snippets]
    return (
        _check(got.data.inbox.total == 132, f"the brief says {got.data.inbox.total} unread")
        + _check("Your bill is ready" in subjects, "mail in Updates is not on the brief")
        + _check("50% off today" not in subjects, "a promotion is listed on the brief")
        + _check(not any(CODE in x for x in seen), "the code is on the brief")
    )


class _Never:
    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        del user_id
        return [PolicyRule(tool_pattern="gmail_*", effect=Effect.DENY, source="owner")]


async def _o12_brief_never() -> list[str]:
    fake = PlanGoogle(mails=_inbox(), unread=132)
    conn = await connector(fake)
    reg = ToolRegistry()
    for t in gd.inbox_tools(lambda: conn, max_reads=30):
        reg.register(t)
    gw = Gateway(
        registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog(), rules=_Never()
    )
    got = await Collector(conn, None, reads=BackgroundReads.of(gw)).collect(UID, IST, DAY)
    return _check(fake.gmail_reads() == [], "the brief read mail on a Never row") + _check(
        # I1 code review M4: "paused" by his Permissions, said as his choice, never as a fault
        got.data.sections_status.inbox == "paused",
        "the brief does not say his Permissions paused it",
    )


CASES: dict[str, Case] = {
    "o1-empty-answer-is-honest": _o1_empty_answer,
    "o1-cut-off-retried-once-and-paid": _o1_cut_off_then_words,
    "o1-cut-off-twice-says-so": _o1_cut_off_twice,
    "o1-sixty-single-calls-one-card": _o1_sixty_single_calls,
    "o1-window-never-holds-a-filler": _o1_window_has_no_filler,
    "o1-round-limit-summary": _o1_round_limit,
    "o1-stream": _o1_stream,
    "o2-sixty-events-one-card": _o2_one_card,
    "o2-one-approval-sixty-creates": _o2_one_approval_sixty_creates,
    "o2-failed-item-and-retry": _o2_failed_item_and_retry,
    "o2-one-undo-leaves-a-changed-event": _o2_one_undo,
    "o2-guest-refused": _o2_guest_refused,
    "o2-always-a-card": _o2_always_a_card,
    "o2b-skip-7-moves-54-count-stays-60": _o2b_skip_moves_54,
    "o2b-busy-evening-avoided": _o2b_busy_avoided,
    "o2b-a-lost-session-is-refused": _o2b_refuses_a_lost_session,
    "o2b-check-in-once-held-at-night": _o2b_checkin_once_and_held,
    "o2b-no-ai-answer": _o2b_no_ai,
    "o12-every-category-counted": _o12_every_category_counted,
    "o12-count-is-the-label": _o12_count_is_the_label,
    "o12-code-withheld": _o12_code_withheld,
    "o12-never-means-no-read": _o12_never_means_no_read,
    "o12-brief-counts-the-whole-inbox": _o12_brief_whole_inbox,
    "o12-brief-obeys-the-mail-row": _o12_brief_never,
}


async def _run() -> list[dict[str, Any]]:
    out = []
    for name, case in CASES.items():
        try:
            failures = await case()
        except Exception as exc:  # noqa: BLE001 - a case that crashes fails, it never hides
            failures = [f"raised {type(exc).__name__}: {str(exc)[:120]}"]
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    got = await _run()
    print(f"{PART}: {sum(r['passed'] for r in got)} of {len(got)} cases passed")
    return got


# ---- the negative controls ----------------------------------------------------------------------
@contextmanager
def _swapped(owner: Any, name: str, value: Any) -> Iterator[None]:
    real = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, real)


def _old_reply(completion: Any, **_: Any) -> str:
    return completion.text or OLD_FILLER  # the line this release removed


async def _no_retry(ask: Any, msgs: Any, tries: Any, *, working: bool) -> Any:
    del tries
    return await ask(msgs, working)


def _not_gathered(calls: Any, registry: Any, limit: int) -> tuple[Any, Any]:
    del registry, limit
    return list(calls), lambda out: out


def _dropping(real: Any) -> Any:
    def build(*a: Any, **kw: Any) -> Any:
        return real(*a, **kw)[:-1]  # the last session is lost

    return build


@contextmanager
def _control(name: str) -> Iterator[None]:
    if name == "filler":
        with _swapped(finish, "reply_text", _old_reply), _swapped(finish, "asked", _no_retry):
            yield
    elif name == "singles":
        with _swapped(brain_module, "gathered", _not_gathered):
            yield
    elif name == "drop_last":
        with _swapped(replan, "build", _dropping(replan.build)):
            yield
    else:
        with _swapped(gd, "INBOX_QUERY", OLD_QUERY):
            yield


async def control() -> dict[str, Any]:
    """Each of the four controls in turn. The suite counts as failed only when EVERY control
    made at least one case of its own observation fail."""
    failed: dict[str, list[str]] = {}
    for name in CONTROL_OF.values():
        with _control(name):
            got = await _run()
        failed[name] = [r["id"] for r in got if not r["passed"]]
    weak = [
        name
        for prefix, name in CONTROL_OF.items()
        if not any(i.startswith(f"{PART}:{TARGET.get(name, prefix)}-") for i in failed[name])
    ]
    return {
        "name": "plan: " + " / ".join(CONTROL_OF.values()),
        "suite_failed": not weak,
        "failed_cases": sorted({i for ids in failed.values() for i in ids}),
        "by_control": failed,
        "too_weak": weak,
    }
