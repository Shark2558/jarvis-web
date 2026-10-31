# evals/phase0/run.py
"""Phase 0 eval harness — the exit gate for the core loop.

Usage:
    python evals/phase0/run.py                # real provider (needs JARVIS_ANTHROPIC_API_KEY)
    python evals/phase0/run.py --mock         # plumbing smoke test only; checks will mostly fail
    python evals/phase0/run.py --tier strong  # run against a different tier

Gate (all must hold to exit Phase 0):
    pass rate            >= 90%   (deterministic string checks, see cases.jsonl)
    p95 end-to-end turn  <= 4000 ms on the balanced tier
    mean cost per turn   <= $0.01

Writes evals/phase0/report.json for diffing between prompt / model changes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis.config import LLMBackend, Settings, get_settings
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter
from jarvis.logging import configure_logging, new_trace_id
from jarvis.memory.inmemory import InMemorySessionStore

HERE = Path(__file__).parent
PASS_RATE_GATE = 0.90
P95_MS_GATE = 4000
COST_GATE_USD = 0.01


@dataclass
class CaseResult:
    id: str
    category: str
    passed: bool
    failures: list[str]
    final_reply: str
    turns: int
    total_ms: int
    cost_usd: float


def _check(reply: str, checks: dict) -> list[str]:
    fails: list[str] = []
    low = reply.lower()
    if "contains_any" in checks and not any(k.lower() in low for k in checks["contains_any"]):
        fails.append(f"missing any of {checks['contains_any']}")
    if "not_contains_any" in checks:
        hit = [k for k in checks["not_contains_any"] if k.lower() in low]
        if hit:
            fails.append(f"contains forbidden {hit}")
    if "max_words" in checks and len(reply.split()) > checks["max_words"]:
        fails.append(f"{len(reply.split())} words > max {checks['max_words']}")
    return fails


async def run_case(brain: Brain, case: dict, tier: str | None) -> CaseResult:
    sid: str | None = None
    t0 = time.perf_counter()
    cost = 0.0
    reply = ""
    for msg in case["turns"]:
        new_trace_id()
        resp = await brain.chat(ChatRequest(message=msg, session_id=sid, tier=tier))
        sid, reply, cost = resp.session_id, resp.reply, cost + resp.cost_usd
    fails = _check(reply, case.get("checks", {}))
    return CaseResult(
        id=case["id"],
        category=case["category"],
        passed=not fails,
        failures=fails,
        final_reply=reply,
        turns=len(case["turns"]),
        total_ms=int((time.perf_counter() - t0) * 1000),
        cost_usd=round(cost, 6),
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--tier", default=None)
    ap.add_argument("--only", default=None, help="comma-separated case ids")
    args = ap.parse_args()

    s: Settings = get_settings()
    if args.mock:
        s = s.model_copy(update={"llm_backend": LLMBackend.MOCK})
    configure_logging("WARNING", False)
    provider = MockProvider() if args.mock else None
    brain = Brain(
        router=ModelRouter.from_settings(s, provider),
        store=InMemorySessionStore(),
        settings=s,
    )

    lines = (HERE / "cases.jsonl").read_text().splitlines()
    cases = [json.loads(line) for line in lines if line.strip()]
    if args.only:
        keep = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in keep]

    results = [await run_case(brain, c, args.tier) for c in cases]

    passed = sum(r.passed for r in results)
    rate = passed / len(results) if results else 0.0
    per_turn_ms = [r.total_ms / r.turns for r in results]
    p95 = statistics.quantiles(per_turn_ms, n=20)[18] if len(per_turn_ms) >= 2 else max(per_turn_ms)
    mean_cost = statistics.mean(r.cost_usd / r.turns for r in results) if results else 0.0

    print(f"\n{'id':8} {'category':22} {'result':6} {'ms/turn':>8} {'$/turn':>9}  notes")
    for r in results:
        note = "; ".join(r.failures) if r.failures else ""
        print(
            f"{r.id:8} {r.category:22} {'PASS' if r.passed else 'FAIL':6} "
            f"{r.total_ms / r.turns:8.0f} {r.cost_usd / r.turns:9.5f}  {note}"
        )
    print(
        f"\npass {passed}/{len(results)} = {rate:.0%} (gate {PASS_RATE_GATE:.0%}) | "
        f"p95 {p95:.0f} ms (gate {P95_MS_GATE}) | "
        f"mean ${mean_cost:.5f}/turn (gate ${COST_GATE_USD})"
    )

    report = {
        "provider": brain.router.provider.name,
        "tier": args.tier or s.default_tier,
        "model": brain.router.resolve(brain._tier(ChatRequest(message="x", tier=args.tier))),
        "pass_rate": rate,
        "p95_ms_per_turn": p95,
        "mean_cost_per_turn": mean_cost,
        "results": [asdict(r) for r in results],
    }
    (HERE / "report.json").write_text(json.dumps(report, indent=2))

    gate_ok = rate >= PASS_RATE_GATE and p95 <= P95_MS_GATE and mean_cost <= COST_GATE_USD
    print("GATE:", "PASS" if gate_ok else "FAIL")
    return 0 if gate_ok or args.mock else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
