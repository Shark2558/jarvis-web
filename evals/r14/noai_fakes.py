# evals/r14/noai_fakes.py
"""R14 Part D's shared fakes, ONE implementation for the eval (`evals/r14/noai.py`) and the tests
(`tests/r14_fakes_d.py` loads this file by path; evals never import from tests/). The D12 table
as examples and a Brain with the AI off whose tools are fakes that only record what they were
asked. Nothing here calls a model or Google."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.mode import BrainMode
from jarvis.offline.rules import NoAIRouter
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.base import Tool

TIERS = {ModelTier.FAST: "mock-fast", ModelTier.BALANCED: "mock-balanced",
         ModelTier.STRONG: "mock-strong"}  # fmt: skip

# (what he says, the one tool it routes to, its arguments): one or more per row of plan D12
D12_ROWS: list[tuple[str, str, dict[str, Any]]] = [
    ("add milk and eggs to my grocery list", "grocery_add",
     {"items": [{"name": "milk"}, {"name": "eggs"}]}),
    ("Jarvis, put bread on the shopping list please", "grocery_add",
     {"items": [{"name": "bread"}]}),
    ("what's on my shopping list?", "grocery_list", {}),
    ("show me my grocery list", "grocery_list", {}),
    ("remove milk from my grocery list", "grocery_remove", {"items": ["milk"]}),
    ("tick off 2 kg rice and eggs from the groceries", "grocery_remove",
     {"items": ["rice", "eggs"]}),
    ("what's expiring in my vault", "vault_expiring", {}),
    ("which documents expire soon?", "vault_expiring", {}),
    ("where did I put my passport", "belongings_where", {"item": "passport"}),
    ("where are my spare keys?", "belongings_where", {"item": "spare keys"}),
    ("I kept the keys in the drawer", "belongings_put", {"item": "keys", "place": "the drawer"}),
    ("I've put my passport under the blue file.", "belongings_put",
     {"item": "passport", "place": "under the blue file"}),
    ("is the house armed", "home_status", {}),
    ("home status", "home_status", {}),
    ("arm the alarm", "home_arm", {"mode": "away"}),
    ("arm the house for the night", "home_arm", {"mode": "night"}),
    ("where's my parcel", "gmail_track_packages", {}),
    ("where are my orders?", "gmail_track_packages", {}),
    ("check my email", "gmail_inbox_summary", {}),
    ("any new mail?", "gmail_inbox_summary", {}),
    ("what did I delete", "deleted_list", {}),
    ("show recently deleted", "deleted_list", {}),
    ("what do you remember about Lekha", "memory_search", {"query": "Lekha"}),
    ("search your memory for the plumber's visit", "memory_search",
     {"query": "the plumber's visit"}),
    ("when was my last backup", "vitals_backups", {}),
    ("are my backups ok?", "vitals_backups", {}),
    ("test my backup", "vitals_drill_start", {}),
    ("run a restore drill", "vitals_drill_start", {}),
    ("book a plumber for tomorrow morning", "maint_service_request",
     {"job": "plumber", "when": "tomorrow morning"}),
    ("get an electrician to fix the fan on Saturday", "maint_service_request",
     {"job": "electrician", "problem": "fix the fan", "when": "Saturday"}),
    ("I need an AC repair to look at the bedroom AC", "maint_service_request",
     {"job": "ac", "problem": "look at the bedroom AC"}),
]  # fmt: skip
WRITES = frozenset({"grocery_add", "grocery_remove", "belongings_put", "home_arm"})
CARDS = frozenset({"vitals_drill_start"})  # R2 with `ask_when` always (Part A's drill card)
GENERATIVE = (
    "draft an email to the plumber",
    "summarise my inbox",
    "write me a poem about my grocery list",
    "explain what's expiring in my vault",
)


@dataclass
class Seen:
    """What the fake tools were asked, in order."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


def fake_tool(name: str, seen: Seen) -> Tool:
    async def run(a: dict[str, Any]) -> dict[str, Any]:
        seen.calls.append((name, dict(a)))
        return {"message": f"{name} answered"}

    write = name in WRITES or name in CARDS
    return Tool(
        name, f"fake {name}", {"type": "object", "properties": {}},
        ActionRisk.REVERSIBLE if write else ActionRisk.READ_ONLY, run,
        ask_when=(lambda _a: True) if name in CARDS else None,
    )  # fmt: skip


def no_ai_settings() -> Settings:
    return Settings(
        _env_file=None, env="dev", llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY, brain_mode="none",
        model_fast=TIERS[ModelTier.FAST], model_balanced=TIERS[ModelTier.BALANCED],
        model_strong=TIERS[ModelTier.STRONG], usd_inr_live=False,
    )  # fmt: skip


def no_ai_brain(phrases: Sequence[NoAIRouter]) -> tuple[Brain, MockProvider, Seen]:
    """A Brain with the AI off, a fake for every D12 tool, `phrases` added one at a time."""
    seen, reg = Seen(), ToolRegistry()
    for name in sorted({tool for _, tool, _ in D12_ROWS}):
        reg.register(fake_tool(name, seen))
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    s, provider = no_ai_settings(), MockProvider()
    mode = BrainMode(s)
    for router in phrases:
        mode.add_phrases([router])
    brain = Brain(
        router=ModelRouter(provider, TIERS), store=InMemorySessionStore(), settings=s,
        gateway=gw, brain_mode=mode,
    )  # fmt: skip
    return brain, provider, seen


__all__ = [
    "CARDS",
    "D12_ROWS",
    "GENERATIVE",
    "TIERS",
    "WRITES",
    "Seen",
    "fake_tool",
    "no_ai_brain",
    "no_ai_settings",
]
