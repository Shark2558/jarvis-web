# evals/r14/needles_day.py
"""The needles eval's simulated day (evals/r14/needles.py; integrated security review M5).

One day of R14 on the existing fakes, every part built through its own `build` (the app's
wiring) on in-memory stores, Part A's fake admin and walk, a recording notifier and a mock model,
with Part B's errors handler on the root logger as in the app:

- a whole restore drill on the drill day (it walks the needle vault and opens its file), the
  canary job, Vitals; three more drills where Google refuses or fails (list, restore, delete) and
  a notifier that raises; `vitals_backups` and the drill card through a gateway;
- Part B's watch: a job that keeps raising, sixty code-shaped logger names, a brief service that
  raises, the 5-minute and the daily job;
- a Brain turn with the ledger (persona, his message, a tool result, a memory note, a mail
  subject, a parcel merchant), a ledger whose store raises, a model provider that raises;
- No-AI: the inbox with a hostile subject, a service request, one carrying a phone number (refused),
  then the AI back on (the window);
- Telegram: the drill card; then the four status routes.

Every write, log record, audit entry, alert, Vitals item, route body and Telegram message lands
in `Sinks` (needles_fakes.py). Nothing calls Google or spends.
"""

from __future__ import annotations

import datetime as dt
import logging
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from needles_fakes import (  # noqa: E402
    DAY1,
    DIGITS,
    EXC,
    LOGGER_WORD,
    MEMORY_WORD,
    MERCHANT,
    OWNER_WORD,
    PHONE,
    PROBLEM,
    SUBJECT,
    TOOL_WORD,
    UID,
    WHEN,
    Clock,
    NeedleAdmin,
    NeedleDocs,
    Notes,
    Sinks,
    brief_and_billing,
    canary_zone,
    captured,
    fixed_nonce,
    inbox_tools,
    installed,
    needle_world,
    service_tool,
    settings,
)
from r14_fakes_a import FakeAdmin, FakeWalk, World, ring  # noqa: E402

from jarvis.backup import part as backup_part  # noqa: E402
from jarvis.backup.names import SHOW, START  # noqa: E402
from jarvis.billing.ledger import TokenLedgerStore  # noqa: E402
from jarvis.config import Settings  # noqa: E402
from jarvis.core.brain import Brain  # noqa: E402
from jarvis.core.guardrails import ActionRisk, ConfirmationGate  # noqa: E402
from jarvis.core.models import ChatRequest  # noqa: E402
from jarvis.hardening.ports import HardeningContext, HardeningPart  # noqa: E402
from jarvis.llm.base import Role, ToolCall  # noqa: E402
from jarvis.llm.mock_provider import MockProvider  # noqa: E402
from jarvis.llm.router import ModelRouter, ModelTier  # noqa: E402
from jarvis.memory.inmemory import InMemorySessionStore  # noqa: E402
from jarvis.notify.ports import Notifier  # noqa: E402
from jarvis.offline import phrases_r14 as p14  # noqa: E402
from jarvis.selfwatch import part as selfwatch_part  # noqa: E402
from jarvis.skills import part as skills_part  # noqa: E402
from jarvis.skills.ports import BrainSlots  # noqa: E402
from jarvis.storage.docs import Docs, MemoryDocs  # noqa: E402
from jarvis.ticks import TickObserver, run_jobs  # noqa: E402
from jarvis.tools import AuditLog, Gateway, Policy, Tool, ToolRegistry  # noqa: E402

OWNERS = (UID,)
TIERS = {
    ModelTier.FAST: "mock-fast",
    ModelTier.BALANCED: "mock-balanced",
    ModelTier.STRONG: "mock-strong",
}
ROUTES = ("/v1/backup", "/v1/selfwatch", "/v1/skills", "/v1/costs/ledger")
FAILING = {  # Google refuses or fails: the drill must keep only a code
    "restore": {"restore": lambda: RuntimeError(EXC)},
    "delete": {"delete_database": lambda: RuntimeError(EXC)},
    "access": {
        "list_backups": lambda: PermissionError(EXC),
        "schedules": lambda: PermissionError(EXC),
    },
}


def _ctx(
    s: Settings, docs: Docs | None, notes: Notifier, state: dict[str, Any]
) -> HardeningContext:
    return HardeningContext(s=s, docs=docs, audit=None, state=state.get, notifier=lambda: notes)


def _gateway(tools: list[Tool], sinks: Sinks) -> Gateway:
    audit, reg = AuditLog(), ToolRegistry()
    for t in tools:
        reg.register(t)
    sinks.audits.append(audit)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=audit)


def _fake(name: str, result: dict[str, Any]) -> Tool:
    async def run(_a: dict[str, Any]) -> dict[str, Any]:
        return result

    empty = {"type": "object", "properties": {}}
    return Tool(name, f"made-up {name}", empty, ActionRisk.READ_ONLY, run)


# ---- Part A: the drill, the canary, Vitals; Google failing ------------------------------------


async def _backup_part(
    s: Settings, world: World, admin: FakeAdmin, notes: Notifier, clock: Clock
) -> HardeningPart:
    return backup_part.build_with(
        _ctx(s, world.live, notes, {}), admin=admin, walk=lambda: FakeWalk(world), keys=ring(),
        clock=clock,
    )  # fmt: skip


async def _ticks(part: HardeningPart, observe: TickObserver, clock: Clock, n: int) -> None:
    for _ in range(n):
        await run_jobs(part.daily_jobs, OWNERS, observer=observe)
        clock.at += dt.timedelta(minutes=30)


async def drill_day(sinks: Sinks, observe: TickObserver, s: Settings) -> HardeningPart:
    world, clock = await needle_world(), Clock(DAY1)
    sinks.stores.append(world.live)
    part = await _backup_part(s, world, FakeAdmin(world), Notes(sinks), clock)
    await _ticks(part, observe, clock, 10)
    last = await part.services["backup"].log.last_result()
    sinks.facts["drill"] = last.outcome if last else None
    sinks.facts["compared"] = bool(last and last.items and last.samples and last.files)
    sinks.facts["copy_deleted"] = world.drill is None
    sinks.facts["drill_run_cleared"] = (await part.services["backup"].log.state()).run is None
    for reader in part.vitals:
        sinks.told += [repr(item) for item in await reader(UID, clock(), canary_zone())]
    return part


async def failing_drills(sinks: Sinks, observe: TickObserver, s: Settings) -> None:
    for name, fail in FAILING.items():
        world, clock = await needle_world(), Clock(DAY1)
        sinks.stores.append(world.live)
        notes = Notes(sinks, fail=name == "restore")  # the notifier raises too
        admin = NeedleAdmin(world, fail)
        part = await _backup_part(s, world, admin, notes, clock)
        await _ticks(part, observe, clock, 8)
        sinks.facts[f"failed_{name}"] = sorted(set(admin.names()) & set(fail))  # it was reached


async def backup_tools(sinks: Sinks, part: HardeningPart) -> None:
    gw = _gateway(list(part.tools), sinks)
    for name in (SHOW, START):
        got = await gw.execute(ToolCall(id=f"n-{name}", name=name, arguments={}), scope=f"{UID}:s1")
        sinks.facts[f"tool_{name}"] = got.outcome.value


# ---- Part B: the watch ------------------------------------------------------------------------


class NeedleJob:
    name, budget_s = "needle_job", 5.0

    async def run(self, owners: Any) -> dict[str, int]:
        raise RuntimeError(EXC)


async def watch_runs(sinks: Sinks, watch: HardeningPart, observe: TickObserver) -> None:
    handler = watch.services["log_handler"]
    for i in range(60):  # code-shaped names; their text goes straight to the handler
        handler.handle(
            logging.makeLogRecord(
                {"name": f"{LOGGER_WORD}{i:02d}", "levelno": logging.ERROR,
                 "levelname": "ERROR", "msg": EXC}
            )
        )  # fmt: skip
    for _ in range(5):
        await run_jobs(
            (*watch.clock_jobs, NeedleJob()), OWNERS, observer=observe, clock="watchdog",
            total_budget_s=50.0,
        )  # fmt: skip
    await run_jobs(watch.daily_jobs, OWNERS, observer=observe)
    sinks.facts["job_failing_told"] = any("job_failing" in t for t in sinks.told)


# ---- Part C: a Brain turn with the ledger; a ledger and a model that raise ---------------------


def _brain(s: Settings, gw: Gateway, provider: MockProvider) -> Brain:
    store = InMemorySessionStore(ttl_s=3600)
    return Brain(router=ModelRouter(provider, TIERS), store=store, settings=s, gateway=gw)


async def brain_turns(sinks: Sinks, s: Settings, docs: MemoryDocs) -> tuple[HardeningPart, Gateway]:
    state: dict[str, Any] = {}
    skills = skills_part.build(_ctx(s, docs, Notes(sinks), state))
    memory = _fake("memory_search", {"notes": [{"text": f"{MEMORY_WORD} likes tea"}]})
    lookup = _fake("needle_lookup", {"subject": SUBJECT, "merchant": MERCHANT, "word": TOOL_WORD})
    gw = _gateway([*skills.tools, memory, lookup], sinks)
    state["gateway"] = gw
    provider = MockProvider()
    brain = _brain(s, gw, provider)
    brain.slots = BrainSlots(
        offer=skills.services.get("offer"), ledger=skills.services.get("ledger")
    )
    calls = [
        ToolCall(id="c1", name="skills_open", arguments={"skill": "research"}),
        ToolCall(id="c2", name="memory_search", arguments={}),
        ToolCall(id="c3", name="needle_lookup", arguments={}),
    ]
    provider.script_tool_calls(calls, "Done, Sir.")
    said = await brain.chat(
        ChatRequest(message=f"{OWNER_WORD}: look it up; I'm on {PHONE}", user_id=UID)
    )
    sinks.facts["brain_tool_calls"] = said.tool_calls
    seen = str([m.content for m in provider.calls[-1].messages]) if provider.calls else ""
    words = (TOOL_WORD, MEMORY_WORD, SUBJECT, MERCHANT, OWNER_WORD)
    sinks.facts["model_saw_the_words"] = all(w in seen for w in words)
    sinks.facts["ledger_days"] = await skills.services["ledger_view"].days(UID)
    await _failing_ledger_and_model(sinks, s, gw)
    return skills, gw


class NeedleProvider(MockProvider):
    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(EXC)


async def _failing_ledger_and_model(sinks: Sinks, s: Settings, gw: Gateway) -> None:
    provider = MockProvider()
    broken = _brain(s, gw, provider)
    broken.slots = BrainSlots(ledger=TokenLedgerStore(NeedleDocs()))
    provider.script("Fine, Sir.")
    said = await broken.chat(ChatRequest(message="and now?", user_id=UID))
    sinks.facts["reply_despite_ledger"] = said.reply == "Fine, Sir."
    try:
        await _brain(s, gw, NeedleProvider()).chat(ChatRequest(message="hello", user_id=UID))
        sinks.facts["model_failed"] = None
    except Exception as exc:  # noqa: BLE001 - what reaches the API is recorded, by class
        sinks.facts["model_failed"] = type(exc).__name__


# ---- Part D: No-AI, the inbox and a service request; the AI back on ----------------------------


async def no_ai(sinks: Sinks, s: Settings) -> None:
    gw = _gateway([*await inbox_tools(UID), await service_tool()], sinks)
    provider = MockProvider()
    brain = _brain(s.model_copy(update={"brain_mode": "none"}), gw, provider)
    brain.noai.mode.add_phrases(p14.ROUTERS)  # as the app does

    async def say(text: str, sid: str | None = None) -> Any:
        return await brain.chat(ChatRequest(message=text, session_id=sid, user_id=UID))

    off = await say("check my email")
    sinks.facts["noai_quoted"] = SUBJECT in off.reply
    asked = await say(f"book a plumber to fix the {PROBLEM} {WHEN}", off.session_id)
    sinks.facts["service_request"] = PROBLEM in asked.reply
    refused = await say(f"book a plumber to fix the tap, call {DIGITS} tomorrow", off.session_id)
    sinks.facts["digits_refused"] = DIGITS not in refused.reply and "phone" in refused.reply
    await brain.noai.mode.set(UID, "ai", by="eval")
    provider.script("Noted, Sir.")
    await say("thanks", off.session_id)
    sent = provider.calls[-1].messages if provider.calls else []
    quoted = [m for m in sent if m.role is Role.ASSISTANT and "Glimmerfax" in str(m.content)]
    sinks.window = str(quoted[0].content) if quoted else ""


# ---- Telegram's drill card; the four status routes ---------------------------------------------


async def telegram(sinks: Sinks) -> None:
    from telegram_fakes import build_world, callback, dev_settings, message

    ctx = HardeningContext(s=dev_settings(), docs=MemoryDocs(), audit=None, state=lambda _: None)
    w = build_world(extra_tools=[t for t in backup_part.build(ctx).tools if t.name == START])
    await w.pair()
    w.provider.script_tool_calls([ToolCall(id="c1", name=START, arguments={})], "Needs your OK.")
    await w.send(message(1, f"test my backup {OWNER_WORD}"))
    pending = await w.gateway.pending()
    if pending:
        await w.send(callback(2, f"a:{pending[0].id}"))
    sinks.facts["telegram_card"] = len(pending)
    sinks.telegram += w.bot.texts
    sinks.audits.append(w.audit)


async def routes(sinks: Sinks, parts: dict[str, HardeningPart], s: Settings, gw: Gateway) -> None:
    import httpx
    from fastapi import FastAPI

    from jarvis.api import backup as backup_api
    from jarvis.api import selfwatch as selfwatch_api
    from jarvis.api import skills as skills_api
    from jarvis.api.auth import require_auth
    from jarvis.api.identity import current_user

    app = FastAPI()
    for router in (backup_api.router, selfwatch_api.router, skills_api.router):
        app.include_router(router)
    app.state.settings, app.state.r14_parts, app.state.gateway = s, parts, gw
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://needles") as client:
        for path in ROUTES:
            got = await client.get(path)
            sinks.routes[path] = {"status": got.status_code, "body": got.json()}


# ---- the day ----------------------------------------------------------------------------------


async def day() -> Sinks:
    sinks, s, shared = Sinks(), settings(), MemoryDocs()
    sinks.stores.append(shared)
    with captured(sinks), fixed_nonce():
        ctx = _ctx(s, shared, Notes(sinks), brief_and_billing())
        watch = selfwatch_part.build(ctx)
        observe = watch.services["tick_observer"]
        with installed(watch.services["log_handler"]):
            drill = await drill_day(sinks, observe, s)
            await failing_drills(sinks, observe, s)
            await backup_tools(sinks, drill)
            skills, gw = await brain_turns(sinks, s, shared)
            await no_ai(sinks, s)
            await telegram(sinks)
            await watch_runs(sinks, watch, observe)
        await routes(sinks, {"backup": drill, "selfwatch": watch, "skills": skills}, s, gw)
    return sinks


__all__ = ["ROUTES", "day"]
