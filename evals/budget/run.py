# evals/budget/run.py
"""Slice 7b eval harness — costs in rupees and the owner's monthly limit (mock only).

Usage:
    python evals/budget/run.py            # mock (CI)
    python evals/budget/run.py --mock     # same (run_all_mock passes it)
    python evals/budget/run.py --only b07,b08

One suite, cases.jsonl: under / at / over the limit, no limit, the free and unpriced brains,
rollover at IST midnight, the stream, tool rounds that cross the limit mid-turn, approval
narration, the brief's AI lines, an unreadable limit (fail closed), one reply's overshoot, a
failing meter write, per-owner limits, the confirm rule for raising / removing the limit, and a
stored limit or month total that is corrupted (fail closed, never "no limit" / "₹0 spent"; any
change to an unreadable limit needs the confirm).
Gate (hard): 100 % of cases, 0 paid calls made at or over the limit, and 0 "$" in anything the
owner reads (the 402 detail, the brief's note, its cost note). Negative control: the same cases
with the spending gate switched off (Billing.ensure_allowed a no-op) MUST fail — the suite is not
blind to a missing check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from jarvis.billing import (
    Billing,
    BudgetPatch,
    BudgetReached,
    BudgetRejected,
    BudgetStore,
    BudgetUnavailable,
    FxRates,
    UsageMeter,
    UsageUnreadable,
)
from jarvis.brief.models import SettingsPatch
from jarvis.brief.service import BriefService
from jarvis.brief.store import BriefStore
from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import GoogleTokens, MemoryTokenStore
from jarvis.llm.base import Completion, ToolCall
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.pricing import cost_usd
from jarvis.llm.router import ModelTier
from jarvis.logging import configure_logging
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import Doc, MemoryDocs, Set
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.builtin import InMemoryWorld, builtin_tools

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "brief"))
from fake_google import FakeBriefGoogle  # noqa: E402

UID = "u_owner"
OTHER = "u_other"
RATE = 95.24
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)
PAID = {
    ModelTier.FAST: "claude-haiku-5-5",
    ModelTier.BALANCED: "claude-sonnet-5-5",
    ModelTier.STRONG: "claude-opus-5-5",
}
FREE = {t: "gemini-3.8-flash" for t in ModelTier}
UNPRICED = {t: "llama-local-70b" for t in ModelTier}


class PricedMock(MockProvider):
    """The mock brain, but its completions cost money (a fixed amount per call)."""

    def __init__(self, per_call: float | None = 0.01) -> None:
        super().__init__()
        self.per_call = per_call

    async def complete(self, **kw: Any) -> Completion:  # type: ignore[override]
        c = await super().complete(**kw)
        cost = self.per_call if self.per_call is not None else cost_usd(c.model, c.usage)
        return c.model_copy(update={"cost_usd": cost})


class FlakyDocs(MemoryDocs):
    def __init__(self, *, reads: bool = False, writes: bool = False) -> None:
        super().__init__()
        self.fail_reads, self.fail_writes = reads, writes

    async def get(self, path: str) -> Doc | None:
        if self.fail_reads:
            raise RuntimeError("eval: firestore read down")
        return await super().get(path)

    async def transaction(self, fn: Any) -> Any:
        if self.fail_writes:
            raise RuntimeError("eval: firestore write down")
        return await super().transaction(fn)


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


class Rig:
    def __init__(self, c: dict[str, Any]) -> None:
        self.c = c
        self.clock = Clock(datetime.fromisoformat(c["now"]) if "now" in c else NOW)
        self.paid = PricedMock(c.get("per_call", 0.01))
        self.free = PricedMock(0.0)
        self.brains = BrainRegistry(
            [
                BrainSpec(id="anthropic", label="Claude", provider=self.paid, tiers=PAID),
                BrainSpec(
                    id="gemini",
                    label="Gemini (free)",
                    provider=self.free,
                    tiers=FREE,
                    trains_on_content=True,
                ),
                BrainSpec(id="custom", label="Local", provider=PricedMock(None), tiers=UNPRICED),
            ],
            default_id="anthropic",
        )
        self.docs = FlakyDocs()
        self.billing = Billing(
            fx=FxRates(docs=None, http=None, default_rate=RATE, clock=self.clock),
            meter=UsageMeter(self.docs, tz="Asia/Kolkata"),
            budgets=BudgetStore(self.docs),
            brains=self.brains,
            clock=self.clock,
        )
        self.world = InMemoryWorld()
        reg = ToolRegistry()
        for t in builtin_tools(self.world):
            reg.register(t)
        self.gateway = Gateway(
            registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog()
        )
        self.settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            env="dev",
            llm_backend=LLMBackend.MOCK,
            session_backend=SessionBackend.MEMORY,
            usd_inr_live=False,
        )
        self.brain = Brain(
            brains=self.brains,
            store=InMemorySessionStore(ttl_s=3600),
            settings=self.settings,
            gateway=self.gateway,
            billing=self.billing,
        )

    async def seed(self) -> None:
        uid = OTHER if self.c.get("as_other_owner") else UID
        if self.c.get("limit") is not None:
            await self.billing.budgets.update(uid, BudgetPatch(monthly_limit_inr=self.c["limit"]))
        if self.c.get("spent"):
            at = (
                datetime.fromisoformat(self.c["spent_at"])
                if "spent_at" in self.c
                else self.clock.at
            )
            spent = float(self.c["spent"])
            await self.billing.meter.add(
                uid, brain_id="anthropic", cost_usd=spent / RATE, cost_inr=spent, now=at
            )
        if "raw_limit" in self.c:  # a corrupted / hand-edited budget document
            v = self.c["raw_limit"]
            doc = {"user_id": uid} if v == "__missing__" else {"monthly_limit_inr": v}
            await self.docs.write([Set(f"jarvis_budget/{uid}", doc)])
        if "raw_month_total" in self.c:  # a corrupted month document
            month = self.billing.meter.month_of(self.clock())
            raw = {"inr_total": self.c["raw_month_total"], "calls": 3}
            await self.docs.write([Set(f"jarvis_usage/{uid}_{month}", raw)])
        self.docs.fail_reads = bool(self.c.get("broken_reads"))
        self.docs.fail_writes = bool(self.c.get("broken_writes"))

    def req(self, text: str = "hello", **kw: Any) -> ChatRequest:
        return ChatRequest(message=text, user_id=UID, brain=self.c.get("brain"), **kw)

    async def month(self) -> tuple[str, int | None, float | None]:
        self.docs.fail_reads = False
        month = self.billing.meter.month_of(self.clock())
        try:
            m = await self.billing.meter.get(UID, month)
        except UsageUnreadable:  # the case corrupted it on purpose
            return month, None, None
        return month, m.calls, m.inr_total


# ---- one case ------------------------------------------------------------------------------------


async def _chat(r: Rig, obs: dict[str, Any]) -> None:
    try:
        await r.brain.chat(r.req())
        obs["outcome"] = "answered"
    except BudgetReached as exc:
        obs["outcome"], obs["detail"] = "refused", str(exc)
    except BudgetUnavailable as exc:
        obs["outcome"], obs["detail"] = "unavailable", str(exc)


async def _chat_twice(r: Rig, obs: dict[str, Any]) -> None:
    first = await r.brain.chat(r.req())
    try:
        await r.brain.chat(r.req("again", session_id=first.session_id))
        obs["outcome"] = "answered_twice"
    except BudgetReached as exc:
        obs["outcome"], obs["detail"] = "answered_then_refused", str(exc)


async def _stream(r: Rig, obs: dict[str, Any]) -> None:
    chunks: list[str] = []
    try:
        async for d in r.brain.chat_stream(r.req("stream")):
            chunks.append(d)
        obs["outcome"] = "answered"
    except BudgetReached as exc:
        obs["outcome"], obs["detail"] = "refused", str(exc)
    obs["chunks"] = len(chunks)


async def _tools(r: Rig, obs: dict[str, Any]) -> None:
    for i in range(int(r.c.get("rounds", 2))):
        r.paid.script_tool_calls([ToolCall(id=f"t{i}", name="list_tasks", arguments={})])
    r.paid.script("done")
    await _chat(r, obs)


async def _narration(r: Rig, obs: dict[str, Any]) -> None:
    # the action is proposed before the limit exists; the owner approves once it is reached
    limit, spent = r.c.pop("limit"), r.c.pop("spent")
    r.paid.script_tool_calls(
        [ToolCall(id="s1", name="send_message", arguments={"to": "p@example.com", "body": "3pm"})],
        "Awaiting your approval, Sir.",
    )
    first = await r.brain.chat(r.req("tell P"))
    r.c["limit"], r.c["spent"] = limit, spent
    await r.seed()
    before = len(r.paid.calls)
    done = await r.brain.approve(
        first.pending_approvals[0].id, session_id=first.session_id, user_id=UID
    )
    obs["outcome"] = "answered"
    obs["narration_calls"] = len(r.paid.calls) - before
    obs["action_ran"] = r.world.sent == [{"to": "p@example.com", "body": "3pm"}]
    obs["reply"] = done.reply


async def _brief(r: Rig, obs: dict[str, Any]) -> None:
    tokens = MemoryTokenStore()
    await tokens.put(
        UID,
        GoogleTokens(
            email="owner@example.com",
            access_token=SecretStr("a"),
            refresh_token=SecretStr("r"),
            expires_at=4_000_000_000.0,
            scopes=["https://www.googleapis.com/auth/calendar.readonly"],
        ),
    )
    svc = BriefService(
        store=BriefStore(MemoryDocs()),
        google=GoogleConnector(
            tokens, client_id="e", client_secret=SecretStr("e"), http=FakeBriefGoogle().client()
        ),
        brains=r.brains,
        approvals=None,
        audit=AuditLog(),
        owners=[UID],
        default_tz="Asia/Kolkata",
        clock=r.clock,
        billing=r.billing,
    )
    obs["cost_note"] = svc.cost_note()
    await svc.update_settings(UID, SettingsPatch(ai_summary=True, confirm_spend=True))
    view = await svc.generate(UID, trigger="manual", force=False)
    b = view.brief
    assert b is not None
    obs["outcome"] = "ai_lines" if b.ai is not None else "skipped"
    obs["note"] = b.ai_note or ""


async def _budget(r: Rig, obs: dict[str, Any]) -> None:
    out: list[Any] = []
    for p in r.c["patches"]:
        try:
            out.append(await r.billing.budgets.update(UID, BudgetPatch.model_validate(p)))
        except BudgetRejected as exc:
            out.append("rejected")
            obs.setdefault("rejections", []).append(str(exc))
    obs["outcome"], obs["results"] = "done", out


KINDS = {
    "chat": _chat,
    "chat_twice": _chat_twice,
    "stream": _stream,
    "tools": _tools,
    "narration": _narration,
    "brief": _brief,
    "budget": _budget,
}


def _check(c: dict[str, Any], obs: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    e = c["expect"]
    for key, want in e.items():
        if key == "detail_has" and want not in obs.get("detail", ""):
            fails.append(f"detail lacks {want!r}: {obs.get('detail')!r}")
        elif key == "reply_has" and want not in obs.get("reply", ""):
            fails.append(f"reply lacks {want!r}")
        elif key == "note_has" and want not in obs.get("note", ""):
            fails.append(f"brief note lacks {want!r}: {obs.get('note')!r}")
        elif key == "metered_inr_above" and not obs["inr_total"] > want:
            fails.append(f"metered ₹{obs['inr_total']} not above {want}")
        elif key == "inr_total_above" and not obs["inr_total"] > want:
            fails.append(f"month ₹{obs['inr_total']} not above {want}")
        elif key not in {
            "detail_has",
            "reply_has",
            "note_has",
            "metered_inr_above",
            "inr_total_above",
        }:
            if obs.get(key) != want:
                fails.append(f"{key}: want {want!r}, got {obs.get(key)!r}")
    return fails


async def run_case(c: dict[str, Any]) -> dict[str, Any]:
    r = Rig(dict(c))
    if c["kind"] != "narration":
        await r.seed()
    obs: dict[str, Any] = {}
    try:
        await KINDS[c["kind"]](r, obs)
    except Exception as exc:  # noqa: BLE001 — a crash is a failed case, not a crashed harness
        obs["outcome"] = f"crash: {type(exc).__name__}: {str(exc)[:120]}"
    obs["paid_calls"] = len(r.paid.calls) if c["kind"] != "narration" else obs.get("paid_calls")
    obs["free_calls"] = len(r.free.calls)
    obs["month"], obs["meter_calls"], obs["inr_total"] = await r.month()
    fails = _check(c, obs)
    shown = [obs.get("detail", ""), obs.get("note", ""), obs.get("cost_note", "")]
    shown += obs.get("rejections", [])
    dollars = sum("$" in s for s in shown)
    if dollars:
        fails.append("a '$' in text the owner reads")
    over = (
        obs["outcome"] in {"refused", "skipped", "unavailable"}
        and c["kind"] != "tools"
        and (obs["paid_calls"] or 0)
    )
    if over:
        fails.append("a paid call was made although the limit refused the turn")
    return {
        "id": c["id"],
        "kind": c["kind"],
        "why": c["why"],
        "passed": not fails,
        "failures": fails,
        "dollars": dollars,
        "paid_calls_past_limit": int(bool(over)),
        "observed": {k: v for k, v in obs.items() if k != "cost_note"},
    }


async def negative_control(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Every case again with the gate removed: the limit cases must now fail."""
    real = Billing.ensure_allowed

    async def no_gate(self: Billing, uid: str, spec: BrainSpec) -> None:
        return None

    Billing.ensure_allowed = no_gate  # type: ignore[method-assign]
    try:
        results = [await run_case(c) for c in cases]
    finally:
        Billing.ensure_allowed = real  # type: ignore[method-assign]
    failed = [r["id"] for r in results if not r["passed"]]
    return {"failed_cases": len(failed), "ids": failed, "suite_failed": bool(failed)}


def _load(only: str | None) -> list[dict[str, Any]]:
    text = (HERE / "cases.jsonl").read_text(encoding="utf-8")
    cases = [json.loads(ln) for ln in text.split("\n") if ln.strip()]
    keep = set(only.split(",")) if only else None
    return [c for c in cases if keep is None or c["id"] in keep]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="default; kept for run_all_mock")
    ap.add_argument("--only", default=None, help="comma-separated case ids")
    args = ap.parse_args()
    configure_logging("CRITICAL", False)
    cases = _load(args.only)
    results = [await run_case(c) for c in cases]
    control = await negative_control(cases)
    print("\nBUDGET (costs in rupees, the monthly limit)")
    for r in results:
        print(
            f"  {r['id']:4} {'PASS' if r['passed'] else 'FAIL'}  {r['why']}"
            + (f"  ← {'; '.join(r['failures'])}" if r["failures"] else "")
        )
    rate = sum(r["passed"] for r in results) / len(results) if results else 0.0
    dollars = sum(r["dollars"] for r in results)
    past = sum(r["paid_calls_past_limit"] for r in results)
    # b02 b03 b08 b09 b11 b13 b15 b16 b21 b22 b24 b25 must fail with the gate off
    blind = not args.only and control["failed_cases"] < 12
    gate = rate == 1 and dollars == 0 and past == 0 and not blind
    gate = gate and len(results) >= (12 if not args.only else 1)
    print(
        f"budget: {rate:.0%} ({len(results)} cases, gate 100%), paid calls past the limit {past}, "
        f"'$' shown {dollars} (gates 0) → {'PASS' if gate else 'FAIL'}"
    )
    verdict = (
        "suite fails as it must" if control["suite_failed"] and not blind else "TOO FEW: blind"
    )
    print(f"  negative control (gate off): {control['failed_cases']} case(s) fail → {verdict}")
    report = {
        "mode": "mock",
        "gate": gate,
        "suites": {
            "budget": {
                "pass_rate": rate,
                "cases": len(results),
                "paid_calls_past_limit": past,
                "dollars_shown": dollars,
                "negative_control": control,
                "gate": gate,
                "results": results,
            }
        },
    }
    (HERE / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print("\nGATE:", "PASS" if gate else "FAIL")
    return 0 if gate else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
