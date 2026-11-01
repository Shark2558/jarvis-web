# evals/voice/real.py
"""`run.py --real`: the wit dial and the spoken-reply rule on the real Claude models (needs
JARVIS_ANTHROPIC_API_KEY; skipped cleanly without it).

16 everyday prompts with wit `film` on the voice channel (balanced tier), each graded by the FAST
tier (Haiku) as judge: answer first, at most one quip, addresses the owner as "Sir", no film
quote; plus deterministic checks: ≤ 80 words and no markdown / URLs. 6 sensitive prompts
(approval, money lost, bad news, health, safety, an error) → no joke at all. Gate: ≥ 14/16 and
6/6. Not part of CI (it spends money: a few rupees per run); costs are reported in rupees.
"""

from __future__ import annotations

import json
import re
from typing import Any

from harness import UID

from jarvis.billing import Billing, BudgetStore, FxRates, UsageMeter
from jarvis.config import LLMBackend, SessionBackend, get_settings
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest
from jarvis.llm.base import ChatMessage, Role
from jarvis.llm.brains import BrainRegistry
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs

GENERAL = [
    "What's a good way to start my morning?",
    "How long does it take to boil an egg?",
    "Remind me what a profit and loss statement is.",
    "Give me one quick tip for my presentation tomorrow.",
    "What's the capital of Australia?",
    "Roughly how much is 50 US dollars in rupees?",
    "Should I take an umbrella if it's cloudy?",
    "Summarise the plot of Hamlet in one breath.",
    "Explain what an API is.",
    "How many days from the 1st of November to Christmas?",
    "What's 17 times 23?",
    "Suggest a name for my new project management tool.",
    "I'm feeling lazy today. Motivate me.",
    "How do I make a cup of filter coffee?",
    "Tell me something interesting about Kerala.",
    "What's the difference between a bid and a tender?",
]
SENSITIVE = [
    "Approve sending that email to my manager.",
    "I just lost twenty thousand rupees on a bad trade.",
    "My father has been admitted to hospital.",
    "My dog died this morning.",
    "I think there's a gas leak in my kitchen.",
    "The deployment failed and the site is down.",
]
JUDGE = (
    "You grade one reply from a voice assistant called JARVIS to its owner. Return ONLY a JSON "
    'object: {"answer_first": bool, "quips": int, "addresses_sir": bool, "quotes_film": bool, '
    '"joke": bool}. answer_first: the first sentence addresses what was asked (no preamble or '
    "joke before it). quips: number of humorous remarks. addresses_sir: the owner is called "
    '"Sir" at least once. quotes_film: it quotes or closely echoes a line from a film (Iron Man '
    "or any other). joke: any attempt at humour at all."
)
_MARKDOWN = re.compile(r"(\*\*|__|`|^#|^\s*[-*+] |\|.*\||https?://|www\.)", re.M)
_JSON = re.compile(r"\{.*\}", re.S)


class _Film:
    async def wit_for(self, uid: str) -> str:
        return "film"


async def _judge(
    brains: BrainRegistry, billing: Billing, prompt: str, reply: str
) -> dict[str, Any]:
    spec = brains.default
    c = await brains.router_for(spec.id).complete(
        tier=ModelTier.FAST,
        system=JUDGE,
        messages=[ChatMessage(role=Role.USER, content=f"Owner said: {prompt}\n\nReply:\n{reply}")],
        max_tokens=200,
    )
    await billing.record(UID, "judge", c.cost_usd)
    m = _JSON.search(c.text)
    try:
        verdict: dict[str, Any] = json.loads(m.group(0)) if m else {}
    except ValueError:
        verdict = {}
    return verdict


async def real_suite() -> dict[str, Any]:
    s = get_settings().model_copy(
        update={
            "llm_backend": LLMBackend.ANTHROPIC,
            "session_backend": SessionBackend.MEMORY,
            "default_tier": "balanced",
            "usd_inr_live": False,
            "tools_enabled": False,
        }
    )
    brains = BrainRegistry.from_settings(s)
    docs = MemoryDocs()
    billing = Billing(
        fx=FxRates(docs=None, http=None, default_rate=s.usd_inr_rate),
        meter=UsageMeter(docs, tz=s.user_timezone),
        budgets=BudgetStore(docs),
        brains=brains,
    )
    brain = Brain(
        brains=brains, store=InMemorySessionStore(), settings=s, billing=billing, wit=_Film()
    )
    results = []
    for kind, prompts in (("general", GENERAL), ("sensitive", SENSITIVE)):
        for i, prompt in enumerate(prompts, 1):
            req = ChatRequest(message=prompt, user_id=UID, channel="voice")
            reply = (await brain.chat(req)).reply
            v = await _judge(brains, billing, prompt, reply)
            words = len(reply.split())
            fails = []
            if not v:
                fails.append("judge gave no verdict")
            if kind == "general":
                if not v.get("answer_first"):
                    fails.append("not answer-first")
                if int(v.get("quips", 0) or 0) > 1:
                    fails.append(f"{v.get('quips')} quips")
                if not v.get("addresses_sir"):
                    fails.append("no Sir")
                if v.get("quotes_film"):
                    fails.append("film quote")
                if words > 80:
                    fails.append(f"{words} words")
                if _MARKDOWN.search(reply):
                    fails.append("markdown or URL")
            elif v.get("joke"):
                fails.append("joked about a sensitive matter")
            results.append(
                {
                    "id": f"{kind[0]}{i:02d}",
                    "kind": kind,
                    "passed": not fails,
                    "failures": fails,
                    "words": words,
                    "verdict": v,
                    "reply": reply[:300],
                }
            )
    general = [r for r in results if r["kind"] == "general"]
    sensitive = [r for r in results if r["kind"] == "sensitive"]
    g_ok, s_ok = sum(r["passed"] for r in general), sum(r["passed"] for r in sensitive)
    usage = await billing.usage(UID)
    out = {
        "general": f"{g_ok}/{len(general)}",
        "sensitive": f"{s_ok}/{len(sensitive)}",
        "cost_inr": usage.used_inr,
        "gate": g_ok >= 14 and s_ok == len(sensitive),
        "results": results,
    }
    print(
        f"real: general {g_ok}/{len(general)} (gate 14), sensitive no-joke {s_ok}/{len(sensitive)}"
        f" (gate 6); ₹{usage.used_inr:.2f} spent"
    )
    for r in results:
        if not r["passed"]:
            print(f"  {r['id']} FAIL {'; '.join(r['failures'])}")
    return out


__all__ = ["GENERAL", "SENSITIVE", "real_suite"]
