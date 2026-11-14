# src/jarvis/api/skills.py
"""R14 Part C's routes (docs/plans/r14-hardening.md D8, D11). Owner-only (`require_auth`,
`current_user`), `no-store`, counts and names only (never a tool's description, a prompt or a
reply). Each reads Part C's services from `app.state.r14_parts["skills"]` per request.

GET /v1/skills         {part, ready, tool_offer, tools, without_ai, core, skills: [{id, label,
                       about, tools, without_ai}]}: the register, the 11 skills with how many
                       registered tools each holds and how many of those work with the AI off
GET /v1/costs/ledger   {part, ready, enabled, month, days, calls, cold_calls, tokens, chars,
                       tools_offered, tools_per_call, skills_opened, cache_share, inr, inr_total,
                       inr_per_usd}: this month's token ledger, the money by part in ₹
Before the part is built, or when it is left out, both answer {part, ready} only.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.r14_status import NO_STORE, part_of, ready_of
from jarvis.billing.fx import DEFAULT_RATE
from jarvis.billing.ledger import MonthLedger, TokenLedgerStore
from jarvis.hardening.ports import PartName
from jarvis.logging import get_logger
from jarvis.skills.registry import SkillRegister
from jarvis.tools.registry import ToolRegistry

log = get_logger(__name__)
PART: PartName = "skills"
router = APIRouter(dependencies=[Depends(require_auth)])


def _service(request: Request, key: str) -> Any:
    part = part_of(request, PART)
    return part.services.get(key) if part is not None else None


def _registry(request: Request) -> ToolRegistry:
    got = getattr(getattr(request.app.state, "gateway", None), "registry", None)
    return got if isinstance(got, ToolRegistry) else ToolRegistry()


async def _rate(request: Request) -> float:
    billing = getattr(request.app.state, "billing", None)
    try:
        got = await billing.inr(1.0) if billing is not None else 0.0
    except Exception as exc:  # noqa: BLE001 - a display figure: the default rate instead
        log.warning("rupee rate unreadable", extra={"error": type(exc).__name__})
        got = 0.0
    return float(got) if got and got > 0 else DEFAULT_RATE


@router.get("/v1/skills", include_in_schema=False)
async def skills(request: Request) -> JSONResponse:
    body: dict[str, Any] = {"part": PART, "ready": ready_of(request, PART)}
    register = _service(request, "register")
    if isinstance(register, SkillRegister):
        registry = _registry(request)
        summaries = register.summaries(registry)
        body |= {
            "tool_offer": request.app.state.settings.tool_offer,
            "tools": len(registry),
            "without_ai": sum(x.without_ai for x in summaries),
            "core": list(register.catalogue.core),
            "skills": [asdict(x) for x in summaries],
        }
    return JSONResponse(body, headers=NO_STORE)


def _month_body(month: MonthLedger, rate: float) -> dict[str, Any]:
    return {
        "month": month.month,
        "days": month.days,
        "calls": month.calls,
        "cold_calls": month.cold_calls,
        "tokens": month.tokens,
        "chars": month.chars,
        "tools_offered": month.tools_offered,
        "tools_per_call": round(month.tools_offered / month.calls, 1) if month.calls else 0.0,
        "skills_opened": month.skills_opened,
        "cache_share": round(month.cache_share(), 3),
        "inr": {p: round(v * rate, 2) for p, v in month.usd.items()},
        "inr_total": round(month.usd_total * rate, 2),
        "inr_per_usd": rate,
    }


@router.get("/v1/costs/ledger", include_in_schema=False)
async def ledger(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    body: dict[str, Any] = {"part": PART, "ready": ready_of(request, PART)}
    store = _service(request, "ledger_view")
    if part_of(request, PART) is None or not _service(request, "register"):
        return JSONResponse(body, headers=NO_STORE)
    body["enabled"] = isinstance(store, TokenLedgerStore) and bool(_service(request, "ledger"))
    if not isinstance(store, TokenLedgerStore):
        return JSONResponse(body, headers=NO_STORE)
    try:
        month = await store.month(uid)
    except Exception as exc:  # noqa: BLE001 - the class name in the log, nothing in the answer
        log.warning("token ledger unreadable", extra={"error": type(exc).__name__})
        return JSONResponse({**body, "error": "ledger_unreadable"}, 503, headers=NO_STORE)
    return JSONResponse(body | _month_body(month, await _rate(request)), headers=NO_STORE)


__all__ = ["router"]
