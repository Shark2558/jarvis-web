# evals/reminders/run.py
"""Slice 11 B eval harness — reminders (plan evals 5 and 6) behind the real Brain + Gateway.

Usage:
    python evals/reminders/run.py --mock            # CI (run_all_mock passes --mock)
    python evals/reminders/run.py --mock --only e5-remind-at-5pm

Mock only: the scripted model makes the calls a case names, so every gate is decided by what the
in-memory Google (evals/slice6/fake_google.py — which, like Google, filters Events.list by
`privateExtendedProperty` and leaves `transparent` events out of freeBusy) RECEIVED, not by what
the model said. After each chat the harness itself asks, through the same gateway, what
`reminders_list` shows and whether `calendar_free_slots` still gives the same answer as before
the chat.

Suite (cases_reminders.jsonl; gates hard):
  Plan eval 5 — "Remind me to call Ravi at 5 pm": a tagged, transparent 5-minute event at 17:00
  local with one pop-up; reminders_list shows it; free slots unchanged. Plus: minutes before,
  weekday repeat, a past time refused, change one, an ordinary event refused, a spoken request
  and an injected mail each wait as a card.
  Plan eval 6 — "Remind me 30 minutes before my 3 pm meeting": a pop-up override on that event
  (R2 when only the owner is on it, an R3 card when others are), and alerts on a new event.
  A write after a calendar read in the same round is an R2 card (slice 10 TAINTED_WRITES_ASK:
  event titles may be other people's words — kept unchanged by the plan); the cases that look
  the event up first expect that one-tap card, then the change once approved.
  Gate: 100 % of cases, and 0 writes reached Google in a case that must wait for the owner.
  Negative control: the same cases with every new reminder made to block time and lose its tag
  right after it is created MUST fail (eval 5 among them): the checks test something real.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from jarvis.config import LLMBackend, get_settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import GoogleTokens, MemoryTokenStore
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.logging import configure_logging, new_trace_id
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.gmail import gmail_tools
from jarvis.tools.google_calendar import calendar_tools
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.reminders import reminder_tools

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "slice6"))
from fake_google import FakeGoogleServer  # noqa: E402

OWNER = "owner"  # ChatRequest's default user id → gateway scope "owner:<session>"
NOW = datetime(2027, 1, 15, 3, 0, tzinfo=UTC)  # 08:30 in India, Friday 15 Jan 2027
TIERS = {t: f"mock-{t.value}" for t in ModelTier}
ABSENT = "<absent>"
LINK = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


@dataclasses.dataclass
class Harness:
    brain: Brain
    gateway: Gateway
    server: FakeGoogleServer
    provider: MockProvider

    def script(self, rounds: list[list[dict[str, Any]]], final: str) -> None:
        for i, calls in enumerate(rounds):
            self.provider.script_tool_calls(
                [ToolCall(id=f"c{i}_{j}", **c) for j, c in enumerate(calls)]
            )
        self.provider.script(final)

    def results_seen(self) -> str:
        out: list[str] = []
        for call in self.provider.calls:
            for m in call.messages:
                if isinstance(m.content, list):
                    out += [b.content for b in m.content if getattr(b, "type", "") == "tool_result"]
        return "\n".join(out)

    async def direct(self, name: str, args: dict[str, Any]) -> Any:
        """The harness's own read through the gateway (as the owner, outside any turn)."""
        out = await self.gateway.execute(
            ToolCall(id="h", name=name, arguments=args), scope=f"{OWNER}:harness"
        )
        if out.outcome is not GatewayOutcome.EXECUTED:
            raise RuntimeError(f"{name}: {out.outcome.value} {out.error}")
        return out.result


async def build(case: dict[str, Any]) -> Harness:
    server = FakeGoogleServer.from_fixture(str(HERE.parent / "slice6" / "fixture_calendar.json"))
    for event in case.get("plant", []):
        server.plant_event(**event)
    if mail := case.get("plant_mail"):
        server.plant_mail(**mail)
    tokens = MemoryTokenStore()
    await tokens.put(
        OWNER,
        GoogleTokens(
            email="owner@example.com",
            access_token=SecretStr("a"),
            refresh_token=SecretStr("r"),
            expires_at=4_000_000_000.0,
            scopes=LINK,
        ),
    )
    conn = GoogleConnector(
        tokens, client_id="e", client_secret=SecretStr("e"), http=server.client()
    )
    reg = ToolRegistry()
    for t in calendar_tools(conn) + reminder_tools(conn, clock=lambda: NOW) + gmail_tools(conn):
        reg.register(t)
    gateway = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    s = get_settings().model_copy(update={"llm_backend": LLMBackend.MOCK, "tools_enabled": True})
    provider = MockProvider()
    brain = Brain(
        router=ModelRouter(provider, TIERS),
        store=InMemorySessionStore(),
        settings=s,
        gateway=gateway,
    )
    return Harness(brain, gateway, server, provider)


def _load(only: str | None) -> list[dict[str, Any]]:
    path = HERE / "cases_reminders.jsonl"
    cases = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    if only:
        keep = set(only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    return cases


def _holds(got: Any, want: Any) -> bool:
    """`want` is a subset of `got`: dicts key by key (ABSENT = the key must be missing),
    everything else equal."""
    if isinstance(want, dict) and isinstance(got, dict):
        return all(
            (k not in got) if v == ABSENT else (k in got and _holds(got[k], v))
            for k, v in want.items()
        )
    return bool(got == want)


def _mutation_failures(h: Harness, want: list[dict[str, Any]], when: str) -> list[str]:
    got = h.server.mutations
    if len(got) != len(want):
        return [f"{when}: {len(got)} write(s) at Google, want {len(want)}: {[m.kind for m in got]}"]
    return [
        f"{when}: {m.kind} {m.detail} does not hold {w}"
        for m, w in zip(got, want, strict=True)
        if m.kind != w["kind"] or not _holds(m.detail, w.get("body", {}))
    ]


def _sabotage(h: Harness) -> None:
    """Negative control: every reminder the chat created now blocks time and has no tag."""
    for m in h.server.mutations:
        e = h.server.events.get(m.detail.get("id", ""))
        if m.kind == "create_event" and e is not None and "extendedProperties" in e:
            e["transparency"] = "opaque"
            e.pop("extendedProperties")


async def _after_checks(h: Harness, ex: dict[str, Any], baseline: Any) -> list[str]:
    fails: list[str] = []
    if "listed" in ex:
        listed = await h.direct("reminders_list", {})
        texts = " ".join(r["text"] for r in listed["reminders"])
        fails += [f"reminders_list lacks {t!r}" for t in ex["listed"] if t not in texts]
    if baseline is not None:
        after = await h.direct("calendar_free_slots", ex["free_slots_unchanged"])
        if after["slots"] != baseline["slots"]:
            fails.append(f"free slots changed: {baseline['slots']} → {after['slots']}")
    return fails


async def run_case(c: dict[str, Any], *, sabotage: bool = False) -> dict[str, Any]:
    new_trace_id()
    h = await build(c)
    ex = c["expect"]
    free = ex.get("free_slots_unchanged")
    baseline = await h.direct("calendar_free_slots", free) if free else None
    h.script(c["rounds"], "Done, Sir.")
    req = ChatRequest(message=c["owner_message"], channel=c.get("channel", "text"))
    resp = await h.brain.chat(req)
    seen = h.results_seen()
    fails = [f"results lack {s!r}" for s in ex.get("result_contains", []) if s not in seen]
    fails += [f"results have {s!r}" for s in ex.get("result_absent", []) if s in seen]
    pending = resp.pending_approvals
    if len(pending) != ex.get("pending", 0):
        fails.append(f"{len(pending)} approval card(s), want {ex.get('pending', 0)}")
    card = pending[0].summary if pending else ""
    fails += [f"card lacks {s!r}" for s in ex.get("card_contains", []) if s not in card]
    if "card_risk" in ex and (not pending or pending[0].tool_risk != ex["card_risk"]):
        got = pending[0].tool_risk if pending else None
        fails.append(f"card risk {got}, want {ex['card_risk']} (R2: one tap, no passkey)")
    fails += _mutation_failures(h, ex.get("mutations", []), "before approval")
    unapproved = len(h.server.mutations) if ex.get("pending", 0) else 0
    if c.get("approve") and pending:
        h.provider.script("Done, Sir.")
        await h.brain.approve(pending[0].id, session_id=resp.session_id)
        fails += _mutation_failures(h, ex["after_approval"], "after approval")
    if sabotage:
        _sabotage(h)
    fails += await _after_checks(h, ex, baseline)
    return {
        "id": c["id"],
        "eval": c.get("eval"),
        "desc": c["desc"],
        "passed": not fails,
        "failures": fails,
        "unapproved_writes": unapproved,
    }


def _print(title: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n{title}")
    for r in rows:
        print(f"  {r['id']:32} {'PASS' if r['passed'] else 'FAIL'}  {'; '.join(r['failures'])}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="accepted for run_all_mock; always mock")
    ap.add_argument("--only", default=None, help="comma-separated case ids")
    args = ap.parse_args()
    configure_logging("ERROR", False)
    cases = _load(args.only)
    rows = [await run_case(c) for c in cases]
    control = [await run_case(c, sabotage=True) for c in cases]
    _print("REMINDERS", rows)
    rate = sum(r["passed"] for r in rows) / len(rows) if rows else 0.0
    unapproved = sum(r["unapproved_writes"] for r in rows)
    control_failed = [r["id"] for r in control if not r["passed"]]
    eval5_caught = any(r["id"].startswith("e5-remind-at-5pm") for r in control if not r["passed"])
    suite_failed = bool(control_failed) and (eval5_caught or args.only is not None)
    gate = rate == 1.0 and unapproved == 0 and suite_failed
    print(
        f"reminders: {rate:.0%} of {len(rows)} (gate 100%); writes before the owner's approval "
        f"{unapproved} (gate 0) → {'PASS' if rate == 1.0 and unapproved == 0 else 'FAIL'}"
    )
    verdict = "suite fails as it must" if suite_failed else "DID NOT FAIL: the suite proves nothing"
    print(
        f"  negative control (new reminders block time, tag removed): "
        f"{len(control_failed)} case(s) fail → {verdict}"
    )
    report = {
        "mode": "mock",
        "gate": gate,
        "suite": {
            "cases": len(rows),
            "pass_rate": rate,
            "unapproved_writes": unapproved,
            "negative_control": {"failed_cases": control_failed, "suite_failed": suite_failed},
            "results": rows,
        },
    }
    (HERE / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print("\nGATE:", "PASS" if gate else "FAIL")
    return 0 if gate else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
