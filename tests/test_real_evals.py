# tests/test_real_evals.py — slice 10 A1: the real-model eval runner (deploy/run-real-evals.sh +
# evals/run_real.py). Everything that decides money is tested here without a key or a network:
# the rupee estimate, the 1.5× safety stop, the spend guard around the Claude provider, the
# plain-English gate summary and the runner's suite loop.
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import anthropic
import httpx2 as httpx
import pytest

from jarvis.billing.fx import Rate
from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import ChatMessage, Role
from jarvis.llm.pricing import PRICES
from jarvis.llm.router import ModelTier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

from realrun import estimate as est  # noqa: E402
from realrun import guard as grd  # noqa: E402
from realrun import summary as summ  # noqa: E402

TIERS = {
    ModelTier.FAST: "claude-haiku-5-5",
    ModelTier.BALANCED: "claude-sonnet-5-5",
    ModelTier.STRONG: "claude-opus-5-5",
}
RATE = Rate(95.24, "2026-11-01", "frankfurter")


# ---- the estimate


def test_tokens_use_four_characters_and_the_tokenizer_factor() -> None:
    assert est.TOKENIZER_FACTOR == 1.3 and est.CAP_FACTOR == 1.5
    assert est.tokens(4000) == 1300
    assert est.tokens(1) == 1 and est.tokens(0) == 0


def test_the_catalogue_counts_cases_from_the_suites_themselves() -> None:
    cat = est.catalogue(ROOT)
    assert list(cat) == ["phase0", "memory", "voice", "brief", "slice6"]
    turns = sum(
        len(json.loads(line)["turns"])
        for line in (ROOT / "evals/phase0/cases.jsonl").read_text().splitlines()
        if line.strip()
    )
    assert sum(c.count for c in cat["phase0"].calls) == turns
    voice = {c.what: c.count for c in cat["voice"].calls}
    assert set(voice.values()) == {22}  # 16 everyday + 6 sensitive prompts, each judged
    assert cat["memory"].argv[-1] == "--real" and cat["voice"].argv[-1] == "--real"
    assert "--mock" not in cat["slice6"].argv
    for s in cat.values():
        assert (ROOT / s.argv[0]).is_file(), s.argv
        assert s.report == f"evals/{s.key}/report.json"


def test_a_suite_costs_cases_times_tokens_times_the_price() -> None:
    s = est.Suite(
        key="x",
        title="X",
        argv=("evals/x.py",),
        calls=(est.Calls("replies", ModelTier.BALANCED, 10, 4000, 100),),
    )
    p = PRICES["claude-sonnet-5-5"]
    want = 10 * (1300 * p.input_per_mtok + 100 * p.output_per_mtok) / 1_000_000
    assert est.suite_usd(s, TIERS) == pytest.approx(want)


def test_an_unpriced_model_cannot_be_estimated() -> None:
    s = est.Suite("x", "X", ("evals/x.py",), (est.Calls("r", ModelTier.FAST, 1, 10, 10),))
    with pytest.raises(est.Unpriced):
        est.suite_usd(s, {**TIERS, ModelTier.FAST: "llama-local-70b"})


def test_the_estimate_rounds_up_to_whole_rupees_and_caps_at_one_and_a_half_times() -> None:
    cat = est.catalogue(ROOT)
    e = est.build_estimate([cat["phase0"]], TIERS, RATE)
    raw = est.suite_usd(cat["phase0"], TIERS) * RATE.inr_per_usd
    assert e.total_inr >= raw and e.total_inr == int(e.total_inr) and e.total_inr >= 1
    assert e.cap_inr == pytest.approx(1.5 * e.total_inr)
    assert e.cap_usd == pytest.approx(e.cap_inr / RATE.inr_per_usd)
    again = est.Estimate.from_json(e.to_json())
    assert again == e


def test_all_suites_cost_more_than_phase0_alone() -> None:
    cat = est.catalogue(ROOT)
    one = est.build_estimate([cat["phase0"]], TIERS, RATE)
    every = est.build_estimate(list(cat.values()), TIERS, RATE)
    assert every.total_inr > one.total_inr and len(every.lines) == 5


def test_the_estimate_is_plain_english_in_rupees_only() -> None:
    cat = est.catalogue(ROOT)
    text = est.render(est.build_estimate(list(cat.values()), TIERS, RATE))
    assert "$" not in text and "USD" not in text
    assert "₹" in text and "about ₹" in text
    assert "1. " in text and "5. " in text  # every suite numbered
    assert "stops by itself" in text and "estimate" in text
    default = Rate(95.24, None, "default")
    assert "could not be fetched" in est.render(est.build_estimate([cat["phase0"]], TIERS, default))


# ---- the spend guard


def _message(model: str = "claude-sonnet-5-5") -> dict[str, Any]:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "Sir."}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 100_000, "output_tokens": 1_000},  # $0.21 on Sonnet 5.5
    }


def _provider(calls: list[int]) -> AnthropicProvider:
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_message())

    p = AnthropicProvider("sk-test", timeout_s=5, max_retries=0)
    p._client = anthropic.AsyncAnthropic(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return p


MSGS = [ChatMessage(role=Role.USER, content="hi")]


async def test_the_guard_meters_every_call_and_refuses_once_over_the_cap(tmp_path: Path) -> None:
    ledger = grd.Ledger(tmp_path / "spend.json")
    guard = grd.SpendGuard(cap_usd=0.30, ledger=ledger)
    calls: list[int] = []
    undo = grd.install(guard)
    try:
        p = _provider(calls)
        await p.complete(system="s", messages=MSGS, model="claude-sonnet-5-5", max_tokens=5)
        assert ledger.read() == pytest.approx(0.21)
        with pytest.raises(grd.SpendCapReached):  # the second call crosses the cap
            await p.complete(system="s", messages=MSGS, model="claude-sonnet-5-5", max_tokens=5)
        with pytest.raises(grd.SpendCapReached):  # and nothing more is ever sent
            await p.complete(system="s", messages=MSGS, model="claude-sonnet-5-5", max_tokens=5)
        assert len(calls) == 2 and ledger.read() == pytest.approx(0.42)
    finally:
        undo()
    assert AnthropicProvider.complete is grd.ORIGINAL_COMPLETE  # uninstalled cleanly


async def test_the_guard_counts_what_earlier_suites_spent(tmp_path: Path) -> None:
    ledger = grd.Ledger(tmp_path / "spend.json")
    ledger.add(0.25)  # the previous suite
    guard = grd.SpendGuard(cap_usd=0.30, ledger=ledger)
    calls: list[int] = []
    undo = grd.install(guard)
    try:
        with pytest.raises(grd.SpendCapReached):
            await _provider(calls).complete(
                system="s", messages=MSGS, model="claude-sonnet-5-5", max_tokens=5
            )
    finally:
        undo()
    assert len(calls) == 1 and ledger.read() == pytest.approx(0.46)


async def test_the_guard_refuses_a_model_it_cannot_price(tmp_path: Path) -> None:
    guard = grd.SpendGuard(cap_usd=10, ledger=grd.Ledger(tmp_path / "spend.json"))
    calls: list[int] = []
    undo = grd.install(guard)
    try:
        with pytest.raises(grd.UnmeteredModel):
            await _provider(calls).complete(
                system="s", messages=MSGS, model="mystery", max_tokens=5
            )
    finally:
        undo()
    assert calls == []  # refused before anything was sent


SONNET = "claude-sonnet-5-5"


async def _call(p: AnthropicProvider, max_tokens: int = 5) -> None:
    await p.complete(system="s", messages=MSGS, model=SONNET, max_tokens=max_tokens)


# Review L3: the guard fails closed.
async def test_an_unreadable_spending_record_stops_before_any_call(tmp_path: Path) -> None:
    ledger = grd.Ledger(tmp_path / "spend.json")
    ledger.path.write_text("{not json")
    calls: list[int] = []
    undo = grd.install(grd.SpendGuard(cap_usd=10, ledger=ledger))
    try:
        with pytest.raises(grd.SpendCapReached):
            await _call(_provider(calls))
    finally:
        undo()
    assert calls == []


class FullDisk(grd.Ledger):
    def write(self, total: float) -> None:
        raise OSError(28, "No space left on device")


async def test_a_spending_record_that_cannot_be_written_stops_the_run(tmp_path: Path) -> None:
    calls: list[int] = []
    undo = grd.install(grd.SpendGuard(cap_usd=10, ledger=FullDisk(tmp_path / "spend.json")))
    p = _provider(calls)
    try:
        with pytest.raises(grd.SpendCapReached):  # a BaseException: no suite can swallow it
            await _call(p)
        with pytest.raises(grd.SpendCapReached):  # and nothing more is sent
            await _call(p)
    finally:
        undo()
    assert len(calls) == 1


async def test_a_record_that_cannot_even_be_reached_stops_before_any_call(tmp_path: Path) -> None:
    (tmp_path / "not-a-folder").write_text("")
    ledger = grd.Ledger(tmp_path / "not-a-folder" / "spend.json")
    calls: list[int] = []
    undo = grd.install(grd.SpendGuard(cap_usd=10, ledger=ledger))
    try:
        with pytest.raises(grd.SpendCapReached):
            await _call(_provider(calls))
    finally:
        undo()
    assert calls == []


async def test_a_record_lost_mid_run_never_resets_what_was_spent(tmp_path: Path) -> None:
    ledger = grd.Ledger(tmp_path / "spend.json")
    calls: list[int] = []
    undo = grd.install(grd.SpendGuard(cap_usd=0.30, ledger=ledger))
    p = _provider(calls)
    try:
        await _call(p)  # $0.21
        ledger.path.unlink()  # the file vanishes (or is reset by someone else)
        with pytest.raises(grd.SpendCapReached):  # the guard still knows: $0.42 > $0.30
            await _call(p)
    finally:
        undo()
    assert ledger.read() == pytest.approx(0.42)


# Review L4: calls in flight and failed calls count.
async def test_calls_in_flight_count_against_the_stop(tmp_path: Path) -> None:
    import asyncio

    release = asyncio.Event()
    calls: list[int] = []

    async def slow(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        await release.wait()
        return httpx.Response(200, json=_message())

    p = _provider(calls)
    p._client = anthropic.AsyncAnthropic(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(slow)),
    )
    # each call could cost up to 16k output tokens = US$0.16 on Sonnet 5.5; the stop is US$0.25
    undo = grd.install(grd.SpendGuard(cap_usd=0.25, ledger=grd.Ledger(tmp_path / "s.json")))
    try:
        first = asyncio.create_task(_call(p, max_tokens=16_000))
        for _ in range(500):
            if calls or first.done():
                break
            await asyncio.sleep(0.01)
        assert calls, first.exception() if first.done() else "the first call never started"
        with pytest.raises(grd.SpendCapReached):  # a second one at once could pass the stop
            await asyncio.wait_for(_call(p, max_tokens=16_000), 5)  # (admitted, it would hang)
        release.set()
        await first  # it finishes: US$0.21 actually spent, within the stop
    finally:
        release.set()
        undo()
    assert len(calls) == 1


async def test_a_failed_call_is_metered_at_its_estimated_input(tmp_path: Path) -> None:
    from jarvis.llm.base import LLMTransientError

    def timeout(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("the answer never came", request=req)

    p = _provider([])
    p._client = anthropic.AsyncAnthropic(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(timeout)),
    )
    ledger = grd.Ledger(tmp_path / "spend.json")
    undo = grd.install(grd.SpendGuard(cap_usd=10, ledger=ledger))
    long = [ChatMessage(role=Role.USER, content="x" * 40_000)]  # ≈ 13,000 tokens
    try:
        with pytest.raises(LLMTransientError):
            await p.complete(system="s", messages=long, model=SONNET, max_tokens=5)
    finally:
        undo()
    want = est.tokens(40_001) * PRICES[SONNET].input_per_mtok / 1_000_000
    assert ledger.read() == pytest.approx(want, rel=1e-3)


def test_the_guard_runs_a_suite_script_and_maps_a_breach_to_exit_3(tmp_path: Path) -> None:
    script = tmp_path / "spendy.py"
    script.write_text(
        "import asyncio, sys\n"
        "from realrun.guard import SpendCapReached\n"
        "async def main():\n"
        "    raise SpendCapReached('over')\n"
        "sys.exit(asyncio.run(main()))\n"
    )
    ok = tmp_path / "ok.py"
    ok.write_text("import sys\nprint(sys.argv[1:])\nsys.exit(1)\n")
    ledger = grd.Ledger(tmp_path / "spend.json")
    guard = grd.SpendGuard(cap_usd=1, ledger=ledger)
    assert grd.run_script(script, [], guard) == grd.EXIT_CAP
    assert grd.run_script(ok, ["--real"], guard) == 1  # the suite's own exit status


def test_a_suite_can_tell_it_runs_under_the_spend_guard(tmp_path: Path) -> None:
    """Integration review L6: `guarded()` is true only while the runner's guard wraps the Claude
    provider (a suite outside the runner refuses to spend)."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys\nfrom realrun.guard import guarded\nsys.exit(0 if guarded() else 7)\n"
    )
    assert not grd.guarded()
    guard = grd.SpendGuard(cap_usd=1, ledger=grd.Ledger(tmp_path / "spend.json"))
    assert grd.run_script(probe, [], guard) == 0
    assert not grd.guarded()  # put back afterwards


# ---- the plain-English summary


PHASE0 = {
    "pass_rate": 11 / 12,
    "passed": 11,
    "cases": 12,
    "pass_rate_gate": 0.9,
    "p95_ms_per_turn": 3200.0,
    "p95_gate_ms": 4000,
    "mean_cost_inr_per_turn": 0.41,
    "cost_gate_inr": 0.95,
    "gate": True,
}


def test_phase0_summary_says_each_gate_in_plain_words() -> None:
    ok, lines = summ.summarize("phase0", PHASE0)
    text = "\n".join(lines)
    assert ok is True and "PASSED" in text
    assert "11 of 12" in text and "90 %" in text
    assert "3.2 seconds" in text and "4 seconds" in text
    assert "₹0.41" in text and "₹0.95" in text and "$" not in text


def test_phase0_summary_names_what_failed() -> None:
    slow = {**PHASE0, "p95_ms_per_turn": 5100.0, "gate": False}
    ok, lines = summ.summarize("phase0", slow)
    text = "\n".join(lines)
    assert ok is False and "NOT PASSED" in text and "too slow" in text


@pytest.mark.parametrize(
    ("key", "report", "words"),
    [
        (
            "memory",
            {"gate": True, "suites": {"real": {"answers_correct": 18, "facts_said": 20,
                                               "facts_learned": 19, "gate": True}}},
            ["18 of 20", "PASSED"],
        ),
        (
            "voice",
            {"gate": False, "suites": {"real": {"general": "12/16", "sensitive": "6/6",
                                                "gate": False}}},
            ["12 of 16", "NOT PASSED"],
        ),
        (
            "slice6",
            {"gate": True, "suites": {
                "calendar": {"pass_rate": 0.95, "gate": True},
                "injection": {"irreversible_mutations": 0, "unconfirmed_executions": 0,
                              "sends_to_untyped_addresses": 0, "gate": True,
                              "results": [{}] * 32}}},
            ["95 %", "32", "without your approval"],
        ),
        ("brief", {"gate": True, "suites": {"injection": {"cases": 34, "gate": True}}},
         ["PASSED", "34"]),
    ],
)  # fmt: skip
def test_every_suite_has_a_plain_summary(
    key: str, report: dict[str, Any], words: list[str]
) -> None:
    ok, lines = summ.summarize(key, report)
    text = "\n".join(lines)
    assert ok is report["gate"]
    for w in words:
        assert w in text
    assert "$" not in text


def test_a_missing_or_odd_report_never_crashes_the_summary() -> None:
    assert summ.summarize("phase0", None)[0] is False
    ok, lines = summ.summarize("memory", {"gate": True, "suites": {}})
    assert ok is True and lines


# ---- phase0 reports p95 and rupees per reply


def test_phase0_reports_p95_and_rupees_per_turn_for_the_gate_summary() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    env.update(PYTHONPATH=str(ROOT / "src"), JARVIS_USD_INR_LIVE="false", JARVIS_USD_INR_RATE="90")
    r = subprocess.run(
        [sys.executable, str(ROOT / "evals/phase0/run.py"), "--mock"],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert "₹/turn" in r.stdout and "$" not in r.stdout
    report = json.loads((ROOT / "evals/phase0/report.json").read_text())
    assert report["usd_inr_rate"] == 90
    assert report["cost_gate_inr"] == pytest.approx(0.9)  # US$0.01 at the run's rate
    assert report["p95_gate_ms"] == 4000 and report["pass_rate_gate"] == 0.9
    assert report["cases"] == len(report["results"]) and "passed" in report
    assert isinstance(report["gate"], bool) and "mean_cost_inr_per_turn" in report
    assert all("cost_inr" in x for x in report["results"])
    ok, lines = summ.summarize("phase0", report)  # the runner can read it
    assert len(lines) == 4 and "Details are in" not in "\n".join(lines)


# ---- the runner (evals/run_real.py)


RUNNER = ROOT / "evals" / "run_real.py"


def _cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    base["PYTHONPATH"] = str(ROOT / "src")
    base["JARVIS_USD_INR_LIVE"] = "false"  # never call frankfurter.dev from tests
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        capture_output=True,
        text=True,
        env={**base, **(env or {})},
        cwd=ROOT,
        timeout=120,
    )


def test_estimate_writes_the_state_and_amount_reads_it(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    r = _cli("estimate", "--state", str(state))
    assert r.returncode == 0, r.stderr
    assert "Everyday conversation" in r.stdout and "$" not in r.stdout
    saved = json.loads(state.read_text())
    assert saved["suites"] == ["phase0"]
    amount = _cli("amount", "--state", str(state))
    assert amount.stdout.strip() == f"₹{int(saved['estimate']['total_inr'])}"
    every = _cli("estimate", "--all", "--state", str(state))
    assert every.returncode == 0 and len(json.loads(state.read_text())["suites"]) == 5


def test_suites_run_on_the_real_models_with_the_deployed_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import run_real

    monkeypatch.setenv("PYTHONPATH", "/elsewhere")
    monkeypatch.setenv("JARVIS_LLM_BACKEND", "mock")  # a stray .env / shell setting
    monkeypatch.setenv("JARVIS_EFFORT", "high")  # an explicit choice is kept
    e = est.build_estimate([est.catalogue(ROOT)["phase0"]], TIERS, RATE)
    env = run_real._child_env(e)
    assert env["JARVIS_LLM_BACKEND"] == "anthropic" and env["JARVIS_SESSION_BACKEND"] == "memory"
    assert env["JARVIS_USD_INR_LIVE"] == "false" and float(env["JARVIS_USD_INR_RATE"]) == 95.24
    assert env["PYTHONPATH"].split(os.pathsep) == [str(ROOT / "src"), "/elsewhere"]
    assert env["JARVIS_EFFORT"] == "high" and env["JARVIS_LLM_TIMEOUT_S"] == "20"
    cloudrun = (ROOT / "deploy" / "cloudrun.sh").read_text()
    for name, value in run_real.PROD_MODEL_SETTINGS.items():
        assert f"{name}={value}" in cloudrun  # the same values the live service gets


def test_run_refuses_without_the_key(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    _cli("estimate", "--state", str(state))
    r = _cli("run", "--state", str(state), "--ledger", str(tmp_path / "l.json"))
    assert r.returncode == 2 and "key" in r.stdout.lower()


def _fake_suite(tmp_path: Path, key: str, code: int, report: dict[str, Any]) -> dict[str, Any]:
    script = tmp_path / f"{key}.py"
    out = tmp_path / f"{key}-report.json"
    script.write_text(
        "import json, sys\n"
        f"open({str(out)!r}, 'w').write({json.dumps(json.dumps(report))})\n"
        f"sys.exit({code})\n"
    )
    return {"key": key, "title": key.title(), "argv": [str(script)], "report": str(out)}


def test_run_goes_through_the_suites_and_stops_at_the_safety_cap(tmp_path: Path) -> None:
    from realrun.runner import run_suites

    state = tmp_path / "state.json"
    e = est.build_estimate([est.catalogue(ROOT)["phase0"]], TIERS, RATE)
    suites = [
        _fake_suite(tmp_path, "phase0", 0, PHASE0),
        _fake_suite(tmp_path, "memory", grd.EXIT_CAP, {"gate": False}),
        _fake_suite(tmp_path, "voice", 0, {"gate": True}),
    ]
    state.write_text(json.dumps({"suites": [s["key"] for s in suites], "estimate": e.to_json()}))
    lines: list[str] = []
    code = run_suites(
        suites=[est.Suite.from_json(s) for s in suites],
        estimate=e,
        ledger=grd.Ledger(tmp_path / "spend.json"),
        logs=tmp_path / "logs",
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "JARVIS_ANTHROPIC_API_KEY": "x"},
        root=ROOT,
        say=lines.append,
    )
    text = "\n".join(lines)
    assert code == grd.EXIT_CAP
    assert "Everyday conversation (the Phase 0 check): PASSED" in text
    assert "Long-term memory: NOT PASSED" in text
    assert "Voice" not in text  # nothing runs after the safety stop
    assert "safety stop" in text.lower() and "$" not in text
    assert (tmp_path / "logs" / "phase0.log").exists()
