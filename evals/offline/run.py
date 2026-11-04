# evals/offline/run.py
"""R1 workstream C eval harness -- offline mode (the fallback brain on the owner's laptop).

Usage:
    python evals/offline/run.py --mock       # CI (run_all_mock passes --mock); all gates hard
    python evals/offline/run.py --suite url

No network, no model. The real Brain, ModelRouter, LocalFallback, OfflineRules and gateway run; the
"cloud" is a real OpenAI-compatible provider over a scripted httpx transport (so the classification
of connect errors, timeouts and HTTP statuses is exercised end to end) and the "laptop" is another.

  fallback  15 cases (cases.jsonl): connect error / timeout / 503 / 529 -> the laptop answers with
            the offline marker, metered at zero; 429 / 401 / 400 / the monthly limit -> no fallback
            and the laptop is never contacted; not configured or switched off -> the original
            error; laptop down too -> the friendly error; the breaker (2 minutes straight to the
            laptop, then one cloud try); a stream falls back only before its first text.
  tools     5 cases: only the offline tool set is offered (never an R3 or a document tool); a call
            to anything else is dropped; a write in an offline turn becomes a card and does not
            run; the same write runs when the cloud answers (the control).
  url       9 cases (cases.jsonl): the tunnel address rule (https, ts.net, no IP literal, no
            userinfo, public resolution, redirects refused, a name that later points inward).
  Negative controls (each must make its suite FAIL, or the suite is blind): fallback on every error
  -> the fallback suite fails; writes-ask off -> the tools suite fails; URL rule off -> the url
  suite fails.
Gate (hard): every suite 100 %; every negative control fails its suite.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).parent

from jarvis.alerts import NoAlerts  # noqa: E402
from jarvis.billing import Billing  # noqa: E402
from jarvis.billing.budget import BudgetPatch  # noqa: E402
from jarvis.billing.service import BudgetReached  # noqa: E402
from jarvis.config import LLMBackend, SessionBackend, Settings  # noqa: E402
from jarvis.core import channel  # noqa: E402
from jarvis.core.brain import Brain  # noqa: E402
from jarvis.core.guardrails import ActionRisk, ConfirmationGate  # noqa: E402
from jarvis.core.models import ChatRequest  # noqa: E402
from jarvis.integrations.vault import TokenCipher  # noqa: E402
from jarvis.llm import router as router_mod  # noqa: E402
from jarvis.llm.base import LLMError  # noqa: E402
from jarvis.llm.brains import BrainRegistry, BrainSpec  # noqa: E402
from jarvis.llm.fallback import OFFLINE_TOOLS, FallbackFailed  # noqa: E402
from jarvis.llm.local_provider import LocalBrainProvider  # noqa: E402
from jarvis.llm.openai_compat_provider import OpenAICompatProvider  # noqa: E402
from jarvis.llm.router import ModelTier  # noqa: E402
from jarvis.logging import configure_logging  # noqa: E402
from jarvis.memory.inmemory import InMemorySessionStore  # noqa: E402
from jarvis.offline import config as url_rule  # noqa: E402
from jarvis.offline import rules as rules_mod  # noqa: E402
from jarvis.offline.config import UrlRejected, check_url  # noqa: E402
from jarvis.offline.rules import OfflineRules  # noqa: E402
from jarvis.offline.service import LocalFallback  # noqa: E402
from jarvis.offline.store import LocalBrainStore  # noqa: E402
from jarvis.storage.docs import MemoryDocs  # noqa: E402
from jarvis.tools import AuditLog, Gateway, Policy, Tool, ToolRegistry  # noqa: E402

URL = "https://laptop.tail1234.ts.net/v1"
KEY = "eval-key-0123456789-abcdefghijklmnop"
MODEL = "qwen2.5:7b"
UID = "owner"
CLOUD_MODELS = {t: "claude-sonnet-5-5" for t in ModelTier}
STATUS = {"503": 503, "529": 529, "429": 429, "401": 401, "400": 400}


# ---- the world ---------------------------------------------------------------------------------


def _completion(text: str, calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = calls
    return {"choices": [{"message": msg, "finish_reason": "stop"}], "usage": {}}


def _call(name: str, **args: Any) -> dict[str, Any]:
    fn = {"name": name, "arguments": json.dumps(args)}
    return {"id": f"call_{name}", "type": "function", "function": fn}


def _sse(words: list[str]) -> bytes:
    chunks = "".join(
        "data: " + json.dumps({"choices": [{"delta": {"content": w}}]}) + "\n\n" for w in words
    )
    return (chunks + "data: [DONE]\n\n").encode()


class Cloud:
    """The cloud brain: a scripted httpx transport behind a real OpenAICompatProvider."""

    def __init__(self, kind: str = "ok", *, mid_stream: bool = False) -> None:
        self.kind = kind
        self.mid_stream = mid_stream
        self.hits = 0
        self.queue: list[dict[str, Any]] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.hits += 1
        if self.kind == "connect":
            raise httpx.ConnectError("no route to cloud")
        if self.kind == "timeout":
            raise httpx.ReadTimeout("cloud too slow")
        if self.kind in STATUS:
            return httpx.Response(STATUS[self.kind], json={"error": {"message": "vendor text"}})
        stream = json.loads(req.content or b"{}").get("stream")
        if stream:
            return httpx.Response(200, content=_sse(["cloud ", "words "]))
        body = self.queue.pop(0) if self.queue else _completion("from the cloud")
        return httpx.Response(200, json=body)

    def provider(self) -> OpenAICompatProvider:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return OpenAICompatProvider("https://cloud.test/v1", api_key="c", client=client)


class Laptop:
    def __init__(self, *, up: bool = True) -> None:
        self.up = up
        self.requests: list[httpx.Request] = []
        self.queue: list[dict[str, Any]] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if not self.up:
            raise httpx.ConnectError("laptop asleep")
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        body = json.loads(req.content or b"{}")
        if body.get("stream"):
            return httpx.Response(200, content=_sse(["lap ", "top "]))
        return httpx.Response(200, json=self.queue.pop(0) if self.queue else _completion("laptop"))

    def tools_offered(self) -> list[str]:
        for r in self.requests:
            body = json.loads(r.content or b"{}")
            if "messages" in body:
                return [t["function"]["name"] for t in body.get("tools", [])]
        return []


async def _resolver(host: str) -> list[str]:
    return ["8.8.8.8"]


class World:
    def __init__(self, cloud: Cloud, laptop: Laptop, *, laptop_state: str = "on") -> None:
        self.cloud, self.laptop = cloud, laptop
        self.ran: list[str] = []
        self.clock = [1000.0]
        docs = MemoryDocs()
        self.store = LocalBrainStore(docs, TokenCipher(bytes(range(32))))
        self.svc = LocalFallback(
            self.store,
            alerts=NoAlerts(),
            timeout_s=5.0,
            resolver=_resolver,
            transport=httpx.MockTransport(laptop.handler),
            clock=lambda: self.clock[0],
        )
        self.laptop_state = laptop_state
        self.settings = Settings(
            _env_file=None,
            env="dev",
            llm_backend=LLMBackend.MOCK,
            session_backend=SessionBackend.MEMORY,
            usd_inr_live=False,
        )
        spec = BrainSpec(id="mock", label="Claude", provider=cloud.provider(), tiers=CLOUD_MODELS)
        self.brains = BrainRegistry([spec], default_id="mock", fallback=self.svc)
        router = self.brains.router_for("mock")
        router._breaker._clock = lambda: self.clock[0]  # the breaker's 2 minutes, on our clock
        self.billing = Billing.in_memory(self.brains, self.settings)
        self.brain = Brain(
            store=InMemorySessionStore(ttl_s=3600),
            settings=self.settings,
            brains=self.brains,
            gateway=self._gateway(),
            billing=self.billing,
        )

    async def setup(self) -> World:
        from pydantic import SecretStr

        if self.laptop_state != "unconfigured":
            await self.store.put(
                url=URL,
                key=SecretStr(KEY),
                model=MODEL,
                enabled=self.laptop_state != "off",
                set_by=UID,
            )
        return self

    def _gateway(self) -> Gateway:
        reg = ToolRegistry()

        def add(name: str, risk: ActionRisk) -> None:
            async def run(args: dict[str, Any]) -> dict[str, Any]:
                self.ran.append(name)
                return {"ok": True}

            schema = {"type": "object", "properties": {"text": {"type": "string"}}}
            reg.register(Tool(name, name, schema, risk, run, summarize=lambda a, n=name: f"Do {n}"))

        add("calendar_list_events", ActionRisk.READ_ONLY)
        add("reminder_add", ActionRisk.REVERSIBLE)
        add("gmail_send", ActionRisk.IRREVERSIBLE)
        add("doc_read", ActionRisk.READ_ONLY)

        class NoRules:
            async def rules_for(self, user_id: str) -> list[Any]:
                return []

        return Gateway(
            registry=reg,
            policy=Policy(),
            gate=ConfirmationGate(),
            audit=AuditLog(),
            rules=OfflineRules(NoRules()),
        )

    async def chat(self, text: str = "what is on today?") -> Any:
        return await self.brain.chat(ChatRequest(message=text, user_id=UID))


def _result(case: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    return {"id": case["id"], "passed": not failures, "failures": failures, "why": case["id"]}


# ---- suite: fallback ---------------------------------------------------------------------------


async def _fb_chat(case: dict[str, Any]) -> list[str]:
    w = await World(
        Cloud(case["cloud"]), Laptop(up=case.get("laptop") != "down"), laptop_state=_state(case)
    ).setup()
    out: list[str] = []
    try:
        resp = await w.chat()
    except Exception as exc:  # noqa: BLE001 - the case decides what is right
        return _expect_error(case, exc, w)
    if case["expect"] == "error":
        return [f"expected {case['error']} but the turn answered (offline={resp.offline})"]
    if not (resp.offline and resp.reply == "laptop"):
        out.append(f"not answered by the laptop: offline={resp.offline} reply={resp.reply!r}")
    if case.get("zero_cost") and (resp.cost_usd != 0 or resp.cost_inr != 0):
        out.append(f"offline reply was metered: {resp.cost_usd}")
    return out


def _state(case: dict[str, Any]) -> str:
    return case.get("laptop") if case.get("laptop") in ("unconfigured", "off") else "on"


def _expect_error(case: dict[str, Any], exc: Exception, w: World) -> list[str]:
    out: list[str] = []
    if case["expect"] != "error":
        return [f"{type(exc).__name__}: the laptop should have answered"]
    names = {c.__name__ for c in type(exc).__mro__}
    if case["error"] not in names:
        out.append(f"raised {type(exc).__name__}, wanted {case['error']}")
    if case["error"] != "FallbackFailed" and w.laptop.requests:
        out.append("the laptop was contacted")
    if case["error"] == "FallbackFailed" and "your laptop didn't answer" not in str(exc):
        out.append("the error is not in plain words")
    if isinstance(exc, FallbackFailed) and "vendor text" in str(exc):
        out.append("vendor text leaked")
    return out


async def _fb_budget(case: dict[str, Any]) -> list[str]:
    w = await World(Cloud(case["cloud"]), Laptop()).setup()
    await w.billing.budgets.update(UID, BudgetPatch(monthly_limit_inr=1))
    await w.billing.record(UID, "mock", 5.0)  # far past Rs 1
    try:
        await w.chat()
    except BudgetReached:
        return [] if not w.laptop.requests and w.cloud.hits == 0 else ["a call was made"]
    except Exception as exc:  # noqa: BLE001
        return [f"raised {type(exc).__name__}, wanted BudgetReached"]
    return ["the turn was answered past the limit"]


async def _fb_breaker(case: dict[str, Any]) -> list[str]:
    w = await World(Cloud("503"), Laptop()).setup()
    out: list[str] = []
    first = await w.chat()
    hits_after_first = w.cloud.hits
    w.cloud.kind = "ok"
    w.clock[0] += 60
    second = await w.chat("again")
    if not (first.offline and second.offline):
        out.append("the first two turns were not both offline")
    if w.cloud.hits != hits_after_first:
        out.append("the cloud was asked during the 2 minutes")
    w.clock[0] += 61
    third = await w.chat("later")
    if third.offline or w.cloud.hits == hits_after_first:
        out.append("no cloud try after the 2 minutes")
    return out


async def _fb_stream_early(case: dict[str, Any]) -> list[str]:
    w = await World(Cloud(case["cloud"]), Laptop()).setup()
    got = "".join([d async for d in w.brain.chat_stream(ChatRequest(message="hi", user_id=UID))])
    out = [] if got == "lap top " else [f"stream text {got!r}"]
    if not channel.answered_offline():
        out.append("the stream was not marked offline")
    return out


async def _fb_stream_mid(case: dict[str, Any]) -> list[str]:
    cloud = Cloud("ok")
    w = await World(cloud, Laptop()).setup()
    real = cloud.handler

    def cut(req: httpx.Request) -> httpx.Response:
        if json.loads(req.content or b"{}").get("stream"):

            class Dies(httpx.AsyncByteStream):
                async def __aiter__(self):  # type: ignore[no-untyped-def]
                    yield b'data: {"choices":[{"delta":{"content":"cloud "}}]}\n\n'
                    raise httpx.ReadError("connection dropped")

            return httpx.Response(200, stream=Dies())
        return real(req)

    w.brains.get("mock").provider._client = httpx.AsyncClient(transport=httpx.MockTransport(cut))  # type: ignore[attr-defined]
    got: list[str] = []
    try:
        async for d in w.brain.chat_stream(ChatRequest(message="hi", user_id=UID)):
            got.append(d)
    except LLMError:
        pass
    else:
        return ["the stream did not fail"]
    out = []
    if w.laptop.requests:
        out.append("switched to the laptop mid-stream")
    if got != ["cloud "]:
        out.append(f"text before the cut: {got!r}")
    return out


FALLBACK_MODES: dict[str, Callable[[dict[str, Any]], Awaitable[list[str]]]] = {
    "chat": _fb_chat,
    "budget": _fb_budget,
    "breaker": _fb_breaker,
    "stream_early": _fb_stream_early,
    "stream_mid": _fb_stream_mid,
}


def _cases(suite: str) -> list[dict[str, Any]]:
    rows = [json.loads(x) for x in (HERE / "cases.jsonl").read_text().splitlines() if x.strip()]
    return [r for r in rows if r["suite"] == suite]


async def suite_fallback() -> dict[str, Any]:
    results = []
    for case in _cases("fallback"):
        try:
            failures = await FALLBACK_MODES[case["mode"]](case)
        except Exception as exc:  # noqa: BLE001
            failures = [f"harness error {type(exc).__name__}: {exc}"]
        results.append(_result(case, failures))
    return _suite(results)


# ---- suite: tools ------------------------------------------------------------------------------


async def suite_tools() -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    async def offline_world(reply: dict[str, Any] | None) -> World:
        w = await World(Cloud("503"), Laptop()).setup()
        if reply is not None:
            w.laptop.queue.append(reply)
        return w

    def add(case_id: str, failures: list[str]) -> None:
        results.append(_result({"id": case_id}, failures))

    w = await offline_world(None)
    await w.chat()
    offered = w.laptop.tools_offered()
    bad = [n for n in offered if n not in OFFLINE_TOOLS]
    risky = [n for n in offered if n in ("gmail_send", "doc_read")]
    add(
        "only-the-offline-tool-set-is-offered",
        ([f"offered outside the set: {bad}"] if bad else [])
        + ([f"R3 / document tool offered: {risky}"] if risky else [])
        + ([] if set(offered) == {"calendar_list_events", "reminder_add"} else [f"got {offered}"]),
    )

    for name in ("doc_read", "gmail_send"):
        w = await offline_world(_completion("", [_call(name)]))
        resp = await w.chat()
        fails = []
        if w.ran:
            fails.append(f"{name} ran: {w.ran}")
        if "can't do that in offline mode" not in resp.reply:
            fails.append(f"no plain refusal: {resp.reply!r}")
        add(f"call-to-{name}-is-dropped", fails)

    w = await offline_world(_completion("", [_call("reminder_add", text="call mum")]))
    resp = await w.chat("remind me to call mum")
    fails = []
    if w.ran:
        fails.append("the write ran without a card")
    if len(resp.pending_approvals) != 1:
        fails.append(f"{len(resp.pending_approvals)} cards, wanted 1")
    add("write-in-an-offline-turn-becomes-a-card", fails)

    w = await World(Cloud("ok"), Laptop()).setup()
    w.cloud.queue.append(_completion("", [_call("reminder_add", text="call mum")]))
    resp = await w.chat("remind me to call mum")
    add(
        "control-same-write-runs-when-the-cloud-answers",
        [] if w.ran == ["reminder_add"] and not resp.pending_approvals else [f"ran={w.ran}"],
    )
    return _suite(results)


# ---- suite: url --------------------------------------------------------------------------------


async def _url_case(case: dict[str, Any]) -> list[str]:
    mode = case.get("mode")
    if mode == "redirect":
        hits: list[str] = []

        def h(req: httpx.Request) -> httpx.Response:
            hits.append(str(req.url))
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

        p = LocalBrainProvider(URL, api_key=KEY, timeout_s=5, transport=httpx.MockTransport(h))
        from jarvis.llm.base import ChatMessage, Role

        try:
            await p.complete(
                system="s",
                messages=[ChatMessage(role=Role.USER, content="x")],
                model=MODEL,
                max_tokens=5,
            )
        except LLMError:
            return [] if len(hits) == 1 else ["the redirect was followed"]
        return ["a redirect was accepted"]
    if mode == "rebind":
        w = await World(Cloud("503"), Laptop()).setup()

        async def inward(host: str) -> list[str]:
            return ["127.0.0.1"]

        w.svc._resolver = inward
        try:
            await w.chat()
        except LLMError:
            return [] if not w.laptop.requests else ["the laptop was called"]
        return ["answered through an address that points inward"]

    async def resolve(host: str) -> list[str]:
        return list(case["resolves"])

    try:
        await check_url(case["url"], resolver=resolve)
    except UrlRejected:
        return [] if case["expect"] == "refused" else ["a good address was refused"]
    return [] if case["expect"] == "ok" else ["a bad address was accepted"]


async def suite_url() -> dict[str, Any]:
    results = []
    for case in _cases("url"):
        try:
            failures = await _url_case(case)
        except Exception as exc:  # noqa: BLE001
            failures = [f"harness error {type(exc).__name__}: {exc}"]
        results.append(_result(case, failures))
    return _suite(results)


# ---- negative controls -------------------------------------------------------------------------


def _suite(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = sum(r["passed"] for r in results)
    rate = ok / len(results) if results else 0.0
    return {"cases": len(results), "pass_rate": rate, "gate": rate == 1.0, "results": results}


@contextmanager
def _patched(obj: Any, name: str, value: Any):  # type: ignore[no-untyped-def]
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


async def suite_negative() -> dict[str, Any]:
    variants: dict[str, dict[str, Any]] = {}
    with _patched(router_mod, "LLMUnreachable", LLMError):  # fall back on EVERY error
        s = await suite_fallback()
    variants["fallback_on_every_error"] = _variant(s)
    with _patched(rules_mod, "WRITES_ASK", False):
        s = await suite_tools()
    variants["writes_ask_off"] = _variant(s)
    with _patched(url_rule, "ENFORCE_URL_RULE", False):
        s = await suite_url()
    variants["url_rule_off"] = _variant(s)
    gate = all(v["suite_failed"] for v in variants.values())
    return {"cases": len(variants), "pass_rate": 1.0 if gate else 0.0, "gate": gate,
            "variants": variants, "results": []}  # fmt: skip


def _variant(s: dict[str, Any]) -> dict[str, Any]:
    failed = sum(not r["passed"] for r in s["results"])
    return {"suite_failed": failed > 0, "metric": failed}


SUITES: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
    "fallback": suite_fallback,
    "tools": suite_tools,
    "url": suite_url,
    "negative": suite_negative,
}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="default; kept for run_all_mock")
    ap.add_argument("--suite", choices=("all", *SUITES), default="all")
    args = ap.parse_args()
    configure_logging("CRITICAL", False)
    out: dict[str, Any] = {}
    for name, fn in SUITES.items():
        if args.suite not in ("all", name):
            continue
        s = await fn()
        out[name] = s
        if name == "negative":
            parts = [
                f"{v} -> "
                + ("fails as it must" if d["suite_failed"] else "DID NOT FAIL: suite is blind")
                + f" (metric {d['metric']})"
                for v, d in s["variants"].items()
            ]
            print(f"{name:9} {'PASS' if s['gate'] else 'FAIL'}  " + "; ".join(parts))
        else:
            verdict = "PASS" if s["gate"] else "FAIL"
            print(f"{name:9} {verdict}  {s['pass_rate']:.0%} of {s['cases']} cases")
            for r in s["results"]:
                if not r["passed"]:
                    print(f"    {r['id']}: {'; '.join(r['failures'])}")
    report = {"mode": "mock", "suites": out, "gate": all(s["gate"] for s in out.values())}
    (HERE / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print("\nGATE:", "PASS" if report["gate"] else "FAIL")
    return 0 if report["gate"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
