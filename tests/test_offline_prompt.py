# tests/test_offline_prompt.py -- review fix H1: the laptop brain gets a short, purpose-built system
# prompt instead of the cloud persona, so the prompt plus the twelve tool specs fit a small local
# model's context window (Ollama's default would silently drop the oldest tokens).
from __future__ import annotations

import json

from offline_fakes import Rig
from pydantic import SecretStr

from jarvis.config import Settings
from jarvis.core.prompts import build_system_prompt
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.llm.base import ChatMessage, Role, ToolSpec
from jarvis.llm.fallback import OFFLINE_NOTE, OFFLINE_TOOLS
from jarvis.llm.router import ModelTier
from jarvis.offline.prompt import (
    OFFLINE_PROMPT_BUDGET_TOKENS,
    OFFLINE_SYSTEM_PROMPT,
    estimate_tokens,
)
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.setup import build_gateway


async def _real_specs() -> list[ToolSpec]:
    conn = GoogleConnector(MemoryTokenStore(), client_id="c", client_secret=SecretStr("s"))
    try:
        gw = build_gateway(Settings(), google=conn, docs=MemoryDocs())
        return gw.registry.specs()
    finally:
        await conn.http.aclose()


def _call_kw(system: str, tools: list[ToolSpec]) -> dict[str, object]:
    return {
        "tier": ModelTier.BALANCED,
        "system": system,
        "system_dynamic": "now: 9am Thursday",
        "messages": [ChatMessage(role=Role.USER, content="what's on today?")],
        "max_tokens": 200,
        "effort": None,
        "tools": tools,
    }


async def test_the_laptop_gets_the_offline_prompt_not_the_cloud_persona() -> None:
    rig = await Rig().ready()
    cloud = build_system_prompt(honorific="Sir")
    await rig.svc.complete(**_call_kw(cloud, []))  # type: ignore[arg-type]
    system = rig.laptop.chats()[0]["messages"][0]["content"]
    assert system.startswith(OFFLINE_SYSTEM_PROMPT)
    assert cloud[:200] not in system and len(system) < len(cloud) // 4
    assert OFFLINE_NOTE in system and "now: 9am Thursday" in system


async def test_the_streamed_path_also_uses_the_offline_prompt() -> None:
    rig = await Rig().ready()
    kw = _call_kw(build_system_prompt(honorific="Sir"), [])
    kw.pop("tools")
    _ = [d async for d in rig.svc.stream(usage=None, **kw)]  # type: ignore[arg-type]
    system = rig.laptop.chats()[0]["messages"][0]["content"]
    assert system.startswith(OFFLINE_SYSTEM_PROMPT)


def test_the_prompt_states_what_a_small_model_must_not_forget() -> None:
    p = OFFLINE_SYSTEM_PROMPT
    assert "JARVIS" in p and '"Sir"' in p
    assert "untrusted" in p and "Never follow instructions" in p
    assert "card" in p and "approv" in p
    assert p.isascii()


async def test_system_prompt_plus_the_real_tool_specs_stay_inside_the_budget() -> None:
    specs = await _real_specs()
    assert {t.name for t in specs} >= set(OFFLINE_TOOLS)  # all 12 exist in the real registry
    rig = await Rig().ready()
    await rig.svc.complete(**_call_kw(build_system_prompt(honorific="Sir"), specs))  # type: ignore[arg-type]
    body = rig.laptop.chats()[0]
    sent = [t["function"]["name"] for t in body["tools"]]
    assert sorted(sent) == sorted(OFFLINE_TOOLS)
    system = body["messages"][0]["content"]
    tokens = estimate_tokens(system) + estimate_tokens(json.dumps(body["tools"]))
    assert tokens < OFFLINE_PROMPT_BUDGET_TOKENS, tokens
