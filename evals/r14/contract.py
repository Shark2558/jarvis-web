# evals/r14/contract.py
"""R14 eval, I0's own part (`contract`, BUILT): the parts' contract (jarvis.hardening.ports),
through the real wiring (jarvis.api.r14_wiring) on in-memory fakes:

- every part builds through `build_parts` and is a `HardeningPart` under its own name, not
  "setup failed";
- every tool it registers is inside its `TOOL_FAMILIES`, every job is one of its own
  `R14_JOB_NAMES` (the 5-minute one only as a clock job), every service is one it owns;
- the check refuses a stray part: another part's tool, another part's job, a daily job offered as
  a clock job, another part's service, a part under the wrong name.

Negative control: the contract check is taken away (`check_part` returns whatever it is given):
every refusal case must then fail, so this part cannot pass whatever the parts do.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from jarvis.api import r14_wiring as wiring  # noqa: E402
from jarvis.config import Settings  # noqa: E402
from jarvis.core.guardrails import ActionRisk  # noqa: E402
from jarvis.hardening.ports import (  # noqa: E402
    PARTS,
    HardeningContext,
    HardeningPart,
    tool_allowed,
)
from jarvis.storage.docs import MemoryDocs  # noqa: E402
from jarvis.tools.audit import AuditLog  # noqa: E402
from jarvis.tools.base import Tool  # noqa: E402

PART = "contract"
BUILT = True


def _tool(name: str) -> Tool:
    async def run(_: dict[str, object]) -> str:
        return "ok"

    return Tool(
        name, "a stray tool", {"type": "object", "properties": {}}, ActionRisk.READ_ONLY, run
    )


class _Job:
    def __init__(self, name: str) -> None:
        self.name, self.budget_s = name, 5.0

    async def run(self, owners: Any) -> dict[str, int]:
        return {}


STRAYS: dict[str, tuple[str, HardeningPart]] = {
    "another_parts_tool": ("noai", HardeningPart("noai", tools=(_tool("vitals_backups"),))),
    "another_parts_job": ("skills", HardeningPart("skills", daily_jobs=(_Job("backup_drill"),))),
    "daily_job_as_clock": ("backup", HardeningPart("backup", clock_jobs=(_Job("backup_canary"),))),
    "another_parts_service": ("backup", HardeningPart("backup", services={"offer": object()})),
    "wrong_name": ("selfwatch", HardeningPart("skills")),
}


def _ctx() -> HardeningContext:
    state: dict[str, Any] = {}
    return HardeningContext(
        s=Settings(_env_file=None), docs=MemoryDocs(), audit=AuditLog(), state=state.get
    )


def _built_cases() -> list[dict[str, Any]]:
    parts = wiring.build_parts(_ctx())
    out: list[dict[str, Any]] = []
    for name in PARTS:
        part = parts.get(name)
        failures: list[str] = []
        if not isinstance(part, HardeningPart) or part.name != name:
            failures.append("not a HardeningPart under its own name")
        elif part.ready == wiring.SETUP_FAILED:
            failures.append("left out: setup failed")
        else:
            failures += [f"tool {t.name}" for t in part.tools if not tool_allowed(name, t.name)]
        out.append({"id": f"contract:{name}_builds", "passed": not failures, "failures": failures})
    return out


def _refusal_cases(check: Callable[[Any, Any], Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for case, (name, part) in STRAYS.items():
        try:
            check(name, part)
            failures = ["accepted"]
        except ValueError:
            failures = []
        out.append({"id": f"contract:refuses_{case}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    return _built_cases() + _refusal_cases(wiring.check_part)


async def control() -> dict[str, Any]:
    results = _refusal_cases(lambda name, part: part)  # the contract check taken away
    failed = [r["id"] for r in results if not r["passed"]]
    return {"name": "no contract check", "suite_failed": bool(failed), "failed_cases": failed}
