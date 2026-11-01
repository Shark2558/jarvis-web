# evals/memory/real.py
"""`run.py --real`: the memory loop on the real Claude models (needs JARVIS_ANTHROPIC_API_KEY).

20 planted facts are said by the owner in first person (4 conversations × 5 messages), learned by
the FAST model (4 runs), then 20 paraphrased questions are asked on the FAST tier with the notes
block. Reports how many facts were learned, how many answers contain the expected word, and the
cost in rupees (learning metered as "memory", answers under the brain). Gate: ≥ 80 % answers.
Not part of CI (it spends money: well under ₹1 per run at Haiku 5.5 prices)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from harness import UID

from jarvis.billing import Billing, BudgetStore, FxRates, UsageMeter
from jarvis.config import LLMBackend, SessionBackend, get_settings
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest, Session, Turn
from jarvis.llm.base import Role
from jarvis.llm.brains import BrainRegistry
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.recall.models import SettingsPatch
from jarvis.recall.service import MemoryService
from jarvis.recall.store import MemoryStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

BATCH = 5


def _session(sid: str, lines: list[str]) -> Session:
    s = Session(id=sid, user_id=UID)
    at = datetime.now(UTC) - timedelta(minutes=20)
    for i, text in enumerate(lines):
        s.append(Turn(role=Role.USER, content=text, created_at=at + timedelta(seconds=i)))
        s.append(Turn(role=Role.ASSISTANT, content="Noted, Sir."))
    return s


async def real_suite(cases: list[dict[str, Any]]) -> dict[str, Any]:
    s = get_settings().model_copy(
        update={
            "llm_backend": LLMBackend.ANTHROPIC,
            "session_backend": SessionBackend.MEMORY,
            "default_tier": "fast",
            "usd_inr_live": False,
        }
    )
    brains = BrainRegistry.from_settings(s)
    spec = brains.get(LLMBackend.ANTHROPIC.value)
    docs = MemoryDocs()
    billing = Billing(
        fx=FxRates(docs=None, http=None, default_rate=s.usd_inr_rate),
        meter=UsageMeter(docs, tz=s.user_timezone),
        budgets=BudgetStore(docs),
        brains=brains,
    )
    svc = MemoryService(
        store=MemoryStore(docs),
        brains=brains,
        billing=billing,
        audit=AuditLog(),
        tz=s.user_timezone,
    )
    brain = Brain(
        brains=brains, store=InMemorySessionStore(), settings=s, billing=billing, memory=svc
    )
    await svc.update_settings(UID, SettingsPatch(learn=True, confirm_spend=True))
    statuses = []
    for i in range(0, len(cases), BATCH):
        lines = [c["say"] for c in cases[i : i + BATCH]]
        res = await svc.learn(UID, _session(f"sess_real{i}", lines), spec)
        statuses.append(res.status.value)
    learned = len((await svc.store.load(UID)).active())
    results = []
    for c in cases:
        reply = (await brain.chat(ChatRequest(message=c["question"], user_id=UID))).reply
        ok = c["expect"].lower() in reply.lower()
        results.append({"id": c["id"], "passed": ok, "expect": c["expect"], "reply": reply[:200]})
    usage = await billing.usage(UID)
    memory_inr = sum(b.used_inr for b in usage.by_brain if b.brain == "memory")
    rate = sum(r["passed"] for r in results) / len(results)
    out = {
        "facts_said": len(cases),
        "learning_runs": statuses,
        "facts_learned": learned,
        "answers_correct": sum(r["passed"] for r in results),
        "recall": round(rate, 4),
        "cost_inr_total": usage.used_inr,
        "cost_inr_learning": round(memory_inr, 4),
        "cost_inr_per_learning_run": round(memory_inr / max(1, len(statuses)), 4),
        "gate": rate >= 0.8,
        "results": results,
    }
    print(
        f"real: learned {learned}/{len(cases)} facts in {len(statuses)} runs; "
        f"answers {out['answers_correct']}/{len(cases)} ({rate:.0%}); "
        f"₹{usage.used_inr:.2f} total, ₹{out['cost_inr_per_learning_run']:.3f} per learning run"
    )
    return out


__all__ = ["real_suite"]
