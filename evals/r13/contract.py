# evals/r13/contract.py
"""R13 eval, I0's own part (`contract`, BUILT): the parts' contract (jarvis.wardrobe.ports),
through the real wiring (jarvis.api.r13_wiring) on in-memory fakes:

- every part builds through `build_parts` and is a `WardrobePart` under its own name, not
  "setup failed";
- every tool it registers is one of the 18 and its own (`TOOL_OWNER`), every job one of its own
  `R13_JOB_NAMES` (the 5-minute one only as a clock job), every service one it owns; each part's
  router (`api/wardrobe.py`, `api/laundry.py`, `api/outfits.py`) answers only under its own prefix
  and only routes of the HTTP contract (`wardrobe.http.ROUTES`);
- the check refuses a stray part: another part's tool, a tool that is not one of the 18,
  another part's job, a daily job as a clock job, the clock job as a daily one, another part's
  service, an observer without `changed`, data without count / export / delete, a wrong name.

Negative control: the contract check is taken away (`check_part` returns whatever it is given):
every refusal case must then fail, so this part cannot pass whatever the parts do.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from jarvis.api import r13_wiring as wiring  # noqa: E402
from jarvis.api.laundry import router as laundry_router  # noqa: E402
from jarvis.api.outfits import router as outfits_router  # noqa: E402
from jarvis.api.wardrobe import router as wardrobe_router  # noqa: E402
from jarvis.config import Settings  # noqa: E402
from jarvis.core.guardrails import ActionRisk  # noqa: E402
from jarvis.storage.docs import MemoryDocs  # noqa: E402
from jarvis.tools.audit import AuditLog  # noqa: E402
from jarvis.tools.base import Tool  # noqa: E402
from jarvis.wardrobe.http import ROUTES  # noqa: E402
from jarvis.wardrobe.ports import (  # noqa: E402
    PARTS,
    ROUTE_PREFIX,
    WardrobeContext,
    WardrobePart,
    tool_allowed,
)

PART = "contract"
BUILT = True
ROUTERS = {"catalog": wardrobe_router, "laundry": laundry_router, "styling": outfits_router}


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


STRAYS: dict[str, tuple[str, WardrobePart]] = {
    "another_parts_tool": ("phone", WardrobePart("phone", tools=(_tool("wardrobe_find"),))),
    "not_one_of_the_18": ("catalog", WardrobePart("catalog", tools=(_tool("wardrobe_wipe"),))),
    "another_parts_job": ("styling", WardrobePart("styling", daily_jobs=(_Job("laundry_daily"),))),
    "daily_job_as_clock": (
        "catalog",
        WardrobePart("catalog", clock_jobs=(_Job("wardrobe_sweep"),)),
    ),
    "clock_job_as_daily": ("styling", WardrobePart("styling", daily_jobs=(_Job("outfit_clock"),))),
    "another_parts_service": ("phone", WardrobePart("phone", services={"store": object()})),
    "observer_without_changed": ("laundry", WardrobePart("laundry", observers=(object(),))),  # type: ignore[arg-type]
    "data_without_methods": ("styling", WardrobePart("styling", data=(object(),))),  # type: ignore[arg-type]
    "wrong_name": ("laundry", WardrobePart("styling")),
}


def _ctx() -> WardrobeContext:
    async def zone(uid: str) -> ZoneInfo:
        return ZoneInfo("Asia/Kolkata")

    state: dict[str, Any] = {}
    return WardrobeContext(
        s=Settings(_env_file=None),
        docs=MemoryDocs(),
        keyring=None,
        audit=AuditLog(),
        now=lambda: datetime(2026, 11, 16, 6, 30, tzinfo=UTC),  # a fixed clock: 12:00 IST
        zone=zone,
        state=state.get,
    )


def _route_failures(name: str) -> list[str]:
    router = ROUTERS.get(name)
    if router is None:
        return []
    planned = {(m, p) for m, p, part, *_ in ROUTES if part in (name, "any")}
    out: list[str] = []
    for route in router.routes:
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", None) or ())
        if not any(path.startswith(x) for x in ROUTE_PREFIX[name]):
            out.append(f"route {path} outside {ROUTE_PREFIX[name]}")
        out += [
            f"route {m} {path} not in the contract" for m in methods if (m, path) not in planned
        ]
    return out


def _built_cases() -> list[dict[str, Any]]:
    parts = wiring.build_parts(_ctx())
    out: list[dict[str, Any]] = []
    for name in PARTS:
        part = parts.get(name)
        failures: list[str] = []
        if not isinstance(part, WardrobePart) or part.name != name:
            failures.append("not a WardrobePart under its own name")
        elif part.ready == wiring.SETUP_FAILED:
            failures.append("left out: setup failed")
        else:
            failures += [f"tool {t.name}" for t in part.tools if not tool_allowed(name, t.name)]
            failures += _route_failures(name)
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
