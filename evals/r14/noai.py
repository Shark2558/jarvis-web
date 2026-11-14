# evals/r14/noai.py
"""R14 eval, Part D's suite (`noai`): No-AI pass 2 (plan D12), on fakes, through a real `Brain`
with the AI off:

- every example of every D12 row (`noai_fakes.py` `D12_ROWS`, beside this file) makes ZERO
  provider calls and ends in exactly its one tool through the gateway (a read runs; a write or the
  drill waits on one card for exactly that call);
- the fixed lines (disarm never routes; the time and the date from the clock; "what can you do")
  and the generative asks (they keep `NO_AI_LINE`) make no provider call and no tool call;
- row 102's request carries no address or phone number: one with a phone number is refused.

Negative control: Part D's phrases switched off (the Brain gets no R14 router): every D12 row
then misses its tool, so this part must fail.

The fakes are loaded by file path under the name `tests/r14_fakes_d.py` uses too (one module;
this eval needs nothing from tests/ nor any sys.path change).
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest
from jarvis.helpers.house.service_request import CONTACT_REFUSAL, service_request
from jarvis.llm.mock_provider import MockProvider
from jarvis.offline.phrases_r14 import ABILITIES_LINE, DISARM_LINE, ROUTERS
from jarvis.offline.rules import NO_AI_LINE, NoAIRouter
from jarvis.tools.taint import context_trust

FAKES_NAME = "jarvis_eval_r14_noai_fakes"
Row = tuple[str, str, dict[str, Any]]


def _fakes() -> ModuleType:
    if FAKES_NAME in sys.modules:
        return sys.modules[FAKES_NAME]
    spec = importlib.util.spec_from_file_location(
        FAKES_NAME, Path(__file__).with_name("noai_fakes.py")
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[FAKES_NAME] = mod  # dataclasses look their module up while the class is built
    spec.loader.exec_module(mod)
    return mod


_F = _fakes()
CARDS: frozenset[str] = _F.CARDS
D12_ROWS: list[Row] = _F.D12_ROWS
GENERATIVE: tuple[str, ...] = _F.GENERATIVE
WRITES: frozenset[str] = _F.WRITES
no_ai_brain: Callable[[Sequence[NoAIRouter]], tuple[Brain, MockProvider, Any]] = _F.no_ai_brain

PART = "noai"
BUILT = True
FIXED: tuple[tuple[str, str], ...] = (
    ("disarm the alarm", DISARM_LINE),
    ("turn off the burglar alarm", DISARM_LINE),
    ("what time is it", "It's "),
    ("what's the date", "Today is "),
    ("what can you do without the AI", ABILITIES_LINE),
    *((text, NO_AI_LINE) for text in GENERATIVE),
)


def _case(cid: str, failures: list[str]) -> dict[str, Any]:
    return {"id": f"{PART}:{cid}", "passed": not failures, "failures": failures}


async def _row(
    n: int, text: str, tool: str, args: dict[str, Any], phrases: Sequence[NoAIRouter]
) -> dict[str, Any]:
    brain, provider, seen = no_ai_brain(phrases)
    resp = await brain.chat(ChatRequest(message=text))
    failures = [f"{len(provider.calls)} provider calls"] if provider.calls else []
    failures += [] if resp.model == "no-ai" else [f"answered by {resp.model}"]
    pending = [p.tool for p in resp.pending_approvals]
    if tool in CARDS or (tool in WRITES and not seen.calls):
        ok = pending == [tool] and not seen.calls
    else:
        ok = seen.calls == [(tool, args)] and not pending
    failures += [] if ok else [f"{text!r}: ran {seen.calls}, cards {pending}, said {resp.reply!r}"]
    return _case(f"row{n:02d}_{tool}", failures)


async def _fixed(n: int, text: str, line: str) -> dict[str, Any]:
    brain, provider, seen = no_ai_brain(ROUTERS)
    resp = await brain.chat(ChatRequest(message=text))
    failures = [f"{len(provider.calls)} provider calls"] if provider.calls else []
    failures += [f"tools ran: {seen.calls}"] if seen.calls or resp.pending_approvals else []
    failures += [] if resp.reply.startswith(line) else [f"{text!r} said {resp.reply!r}"]
    return _case(f"fixed{n:02d}", failures)


async def _no_contact() -> dict[str, Any]:
    said = "book a plumber, the kitchen tap drips"  # his typed words: the request keeps them plain
    with context_trust(untrusted=False, owner_text=said):
        out = await service_request({"job": "plumber", "problem": "the kitchen tap drips"})
    failures = [] if not any(c.isdigit() for c in out["request"]) else ["digits in the request"]
    failures += [] if out["booked"] is False and out["paid"] is False else ["it booked or paid"]
    try:
        await service_request({"job": "plumber", "problem": "call 98765 43210"})
        failures.append("a phone number went into a request")
    except ValueError as exc:
        failures += [] if str(exc) == CONTACT_REFUSAL else [f"refused with {exc}"]
    return _case("service_request_has_no_contact", failures)


async def _rows(phrases: Sequence[NoAIRouter]) -> list[dict[str, Any]]:
    return [
        await _row(n, text, tool, args, phrases) for n, (text, tool, args) in enumerate(D12_ROWS, 1)
    ]


async def cases() -> list[dict[str, Any]]:
    fixed = [await _fixed(n, text, line) for n, (text, line) in enumerate(FIXED, 1)]
    return [*await _rows(ROUTERS), *fixed, await _no_contact()]


async def control() -> dict[str, Any]:
    results = await _rows(())  # Part D's phrases switched off
    failed = [r["id"] for r in results if not r["passed"]]
    return {"name": "R14 phrases off", "suite_failed": bool(failed), "failed_cases": failed}
