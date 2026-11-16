# tests/test_r13_i1_ship.py -- R13 I1: what the image ships and what the guards say about R13's
# tools (INTEGRATION-C 6.2, 6.7, 6.8).
from __future__ import annotations

import logging
from pathlib import Path

from jarvis.core.guardrails import NO_BULK_TOOLS, ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_the_dockerfile_checks_the_rules_file_after_the_install() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    install = text.index("pip install --no-build-isolation --no-deps .")
    check = text.index("from jarvis.wardrobe.styling.rules import load_rules; load_rules()")
    assert install < check < text.index("USER jarvis")  # fails the build, never the first start


def test_a_whole_plan_release_is_never_one_of_approve_all() -> None:
    assert {"wardrobe_merge", "wardrobe_retire", "outfit_plan"} <= NO_BULK_TOOLS


async def test_a_tool_that_raises_logs_its_class_never_its_text(
    caplog: object,
) -> None:
    secret = "needle-private-label-4417"

    async def boom(args: dict[str, object]) -> dict[str, object]:
        raise RuntimeError(f"could not save {secret}")

    reg = ToolRegistry()
    reg.register(
        Tool(name="wardrobe_find", description="x", input_schema={"type": "object"},
             risk=ActionRisk.READ_ONLY, run=boom)
    )  # fmt: skip
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    with caplog.at_level(logging.DEBUG):  # type: ignore[attr-defined]
        res = await gw.execute(ToolCall(id="t", name="wardrobe_find", arguments={}), scope="u:s")
    assert res.outcome is GatewayOutcome.ERROR
    records = caplog.records  # type: ignore[attr-defined]
    failed = [r for r in records if r.getMessage() == "tool failed"]
    assert failed and getattr(failed[0], "error", "") == "RuntimeError"
    assert failed[0].exc_info is None  # no traceback: it prints the exception's text
    assert secret not in "\n".join(f"{r.getMessage()} {r.__dict__}" for r in records)
