# tests/test_r14_d_noai_app.py -- R14 D12 through the real app with the AI off: Part D's routers
# reach No-AI mode through I0's wiring (one at a time, after the helpers' own phrases), no earlier
# router takes a D12 phrase, and a chat turn makes ZERO provider calls: each phrase ends in its
# tool through the gateway (a read runs, a write waits on a card) or a fixed line. On a Telegram
# turn the private rows stay refused (the router adds no way around the Telegram rules).
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from belongings_fakes import UID, things
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r14_fakes_d import CARDS, D12_ROWS, WRITES, Seen, fake_tool
from telegram_fakes import Clock

from jarvis.api import create_app
from jarvis.belongings.tools import NOT_NOTED, belongings_tools
from jarvis.config import Settings
from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline import phrases_r14 as p14
from jarvis.offline.no_ai import run_no_ai
from jarvis.offline.rules import NO_AI_LINE, route_no_ai
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.rules import wrap_rules
from jarvis.telegram.store import TelegramStore
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.gateway import GatewayOutcome

NOW = datetime(2026, 11, 14, 16, 5, tzinfo=ZoneInfo("Asia/Kolkata"))
ROWS = D12_ROWS


@pytest.fixture
async def rig(settings: Settings) -> AsyncIterator[tuple[FastAPI, AsyncClient, MockProvider, Seen]]:
    seen, reg = Seen(), ToolRegistry()
    for name in sorted({tool for _, tool, _ in ROWS}):
        reg.register(fake_tool(name, seen))
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    provider = MockProvider()
    s = settings.model_copy(update={"brain_mode": "none", "max_input_chars": 2_000})
    app = create_app(s, provider=provider, store=InMemorySessionStore(), gateway=gw)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c, provider, seen


async def test_the_routers_are_installed_after_the_helpers_and_none_is_shadowed(rig: Any) -> None:
    app, *_ = rig
    phrases = app.state.brain_mode.phrases
    assert all(r in phrases for r in p14.ROUTERS)
    assert phrases[-len(p14.ROUTERS) :] == p14.ROUTERS  # one at a time, in order, after the rest
    for text, tool, args in ROWS:
        [call] = route_no_ai(text, NOW, phrases).calls
        assert (call.tool, call.arguments) == (tool, args), text


@pytest.mark.parametrize(("text", "tool", "args"), ROWS)
async def test_a_turn_with_the_ai_off_calls_no_model(
    rig: Any, text: str, tool: str, args: dict[str, Any]
) -> None:
    _, c, provider, seen = rig
    r = await c.post("/v1/chat", json={"message": text})
    assert r.status_code == 200, r.text
    body = r.json()
    assert provider.calls == [] and body["model"] == "no-ai" and body["cost_usd"] == 0.0
    if tool in CARDS:
        assert [p["tool"] for p in body["pending_approvals"]] == [tool] and seen.calls == []
    elif seen.calls:
        assert seen.calls == [(tool, args)]
    else:  # a write the default policy holds for his OK: one card for exactly that call
        assert tool in WRITES and [p["tool"] for p in body["pending_approvals"]] == [tool]


@pytest.mark.parametrize(
    ("text", "reply"),
    [
        ("disarm the alarm", p14.DISARM_LINE),
        ("what time is it", "It's "),
        ("what can you do without the AI", "With the AI off I can still do these, Sir"),
        ("draft an email to the plumber", NO_AI_LINE),
        ("summarise my inbox", NO_AI_LINE),
    ],
)
async def test_fixed_lines_call_no_model_and_no_tool(rig: Any, text: str, reply: str) -> None:
    _, c, provider, seen = rig
    body = (await c.post("/v1/chat", json={"message": text})).json()
    assert provider.calls == [] and seen.calls == [] and body["tool_calls"] == 0
    assert body["reply"].startswith(reply) and body["pending_approvals"] == []


@pytest.mark.parametrize(
    ("text", "tool"),
    [
        ("where did I put my passport", "belongings_where"),
        ("I kept the keys in the drawer", "belongings_put"),
        ("what's expiring in my vault", "vault_expiring"),
        ("check my email", "gmail_inbox_summary"),
        ("what did I delete", "deleted_list"),
    ],
)
async def test_on_a_telegram_turn_the_private_rows_stay_refused(text: str, tool: str) -> None:
    """Security review L3: a D12 phrase on Telegram goes through the same gateway and its
    Telegram rules (nothing switched on): the vault, things, the inbox and Recently deleted are
    refused and nothing is read; the router itself adds no way around it."""
    seen, reg = Seen(), ToolRegistry()
    for name in sorted({t for _, t, _ in ROWS}):
        reg.register(fake_tool(name, seen))
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    gw.rules = wrap_rules(None, TelegramStore(MemoryDocs(), prefix="t_", clock=Clock()))
    with telegram_turn():
        out = await run_no_ai(gw, text, NOW, scope="u_owner:tg", extra=p14.ROUTERS)
    assert [c.name for c in out.calls] == [tool]
    assert [r.outcome for r in out.results] == [GatewayOutcome.DENIED]
    assert seen.calls == [] and out.pending == [] and "Sir" in out.reply


async def test_where_with_nothing_kept_says_so_and_a_place_never_asks() -> None:
    """Code review: through the REAL belongings tool, a thing he never noted gets its fixed
    not-found words (`NOT_NOTED`, nothing of his); "where's the toilet" never reaches it. The
    No-AI renderer shows that result as compact JSON (`note` is not one of its summary keys):
    INTEGRATION-D, Needs I1."""
    box, reg = things(), ToolRegistry()
    for tool in belongings_tools(box.svc):
        reg.register(tool)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    out = await run_no_ai(gw, "where's my passport", NOW, scope=f"{UID}:s1", extra=p14.ROUTERS)
    assert [c.name for c in out.calls] == ["belongings_where"]
    assert NOT_NOTED in out.reply and "passport" not in out.reply
    place = await run_no_ai(gw, "where's the toilet", NOW, scope=f"{UID}:s1", extra=p14.ROUTERS)
    assert place.calls == () and place.reply == NO_AI_LINE
