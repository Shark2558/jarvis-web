# evals/r14/noai.py
"""R14 eval, Part D's suite (`noai`): No-AI pass 2 (plan D12), on fakes, through a real `Brain`
with the AI off:

- every example of every D12 row (`tests/r14_fakes_d.py` `D12_ROWS`) makes ZERO provider calls
  and ends in exactly its one tool through the gateway (a read runs; a write or the drill waits on
  one card for exactly that call);
- the fixed lines (disarm never routes; the time and the date from the clock; "what can you do")
  and the generative asks (they keep `NO_AI_LINE`) make no provider call and no tool call;
- row 102's request carries no address or phone number: one with a phone number is refused.

Negative control: Part D's phrases switched off (the Brain gets no R14 router): every D12 row
then misses its tool, so this part must fail.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from r14_fakes_d import CARDS, D12_ROWS, GENERATIVE, WRITES, no_ai_brain  # noqa: E402

from jarvis.core.models import ChatRequest  # noqa: E402
from jarvis.helpers.house.service_request import CONTACT_REFUSAL, service_request  # noqa: E402
from jarvis.offline.phrases_r14 import ABILITIES_LINE, DISARM_LINE, ROUTERS  # noqa: E402
from jarvis.offline.rules import NO_AI_LINE, NoAIRouter  # noqa: E402

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
    return [await _row(n, *row, phrases) for n, row in enumerate(D12_ROWS, 1)]


async def cases() -> list[dict[str, Any]]:
    fixed = [await _fixed(n, text, line) for n, (text, line) in enumerate(FIXED, 1)]
    return [*await _rows(ROUTERS), *fixed, await _no_contact()]


async def control() -> dict[str, Any]:
    results = await _rows(())  # Part D's phrases switched off
    failed = [r["id"] for r in results if not r["passed"]]
    return {"name": "R14 phrases off", "suite_failed": bool(failed), "failed_cases": failed}
