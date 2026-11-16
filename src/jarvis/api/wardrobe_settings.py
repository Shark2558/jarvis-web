# src/jarvis/api/wardrobe_settings.py
"""R13 I1: the wardrobe's settings, joined across the parts (INTEGRATION-A 6.4, INTEGRATION-C 6.4,
INTEGRATION-D 6.5; docs/plans/r13-wardrobe.md D7, D10, D13).

    PUT /v1/wardrobe/settings   his own switches (AI tagging, the private display, his own
                                types): owner-only, limited, one "changed" line on the audit
                                chain with the names that moved, never his words; what he did
                                not send stays. It is a route, never a tool: the model cannot
                                reach it. Calendar, fields, the evening alert and auto-swap
                                are Part C's, at `PUT /v1/outfits/settings`.

`GET /v1/wardrobe` answers one `SettingsView`: A's three switches from his sealed index, C's four
from C's own sealed choice (one source each), and the ₹ one photo would cost on the brain that
would answer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.r13_status import part_of
from jarvis.api.settings_audit import record_change
from jarvis.logging import get_logger
from jarvis.wardrobe import http
from jarvis.wardrobe.catalog import tagging
from jarvis.wardrobe.catalog.routes_common import desk_of, off, ok, refused, too_many

log = get_logger(__name__)
router = APIRouter(dependencies=[Depends(require_auth)])


async def outfit_choice(request: Request, uid: str) -> Any:
    """C's sealed choice (calendar chosen, fields, alert, auto-swap), or None when C is off or
    its document can't be opened (the defaults then show; C's own routes say why)."""
    part = part_of(request, "styling")
    refresh = part.services.get("refresh") if part is not None else None
    plans = getattr(getattr(refresh, "styling", None), "plans", None)
    if plans is None:
        return None
    try:
        return (await plans.read(uid)).choice
    except Exception as exc:  # noqa: BLE001 - a settings view never fails for C's trouble
        log.info("outfit choice not shown", extra={"error": type(exc).__name__})
        return None


async def joined(
    request: Request, uid: str, desk: Any, mine: http.SettingsView
) -> http.SettingsView:
    """A's switches with C's four and the ₹ estimate."""
    choice = await outfit_choice(request, uid)
    update: dict[str, Any] = {}
    if choice is not None:
        update = {
            "calendar_chosen": choice.calendar is not None,
            "fields": choice.fields,
            "plan_alerts": choice.plan_alerts,
            "auto_swap": choice.auto_swap,
        }
    try:
        update["tag_estimate_inr"] = await desk.tagging.estimate_inr()
    except Exception as exc:  # noqa: BLE001 - the figure is a courtesy; the switch still shows
        log.info("tag estimate not shown", extra={"error": type(exc).__name__})
    return mine.model_copy(update=update)


@router.put("/v1/wardrobe/settings", include_in_schema=False)
async def put_settings(
    request: Request, body: http.WardrobeSettingsIn, uid: str = Depends(current_user)
) -> JSONResponse:
    if (busy := too_many(request, "wardrobe_settings", uid, change=True)) is not None:
        return busy
    if (desk := desk_of(request)) is None:
        return off(request)
    sent = {k: v for k, v in body.model_dump().items() if k in body.model_fields_set}
    try:
        view = await tagging.update_settings(desk.store, uid, **sent)
    except Exception as exc:  # noqa: BLE001
        return refused(exc, status=422)
    await record_change(
        request, agent="wardrobe", tool="wardrobe_settings", args={"changed": sorted(sent)}
    )
    return ok(await joined(request, uid, desk, desk.views.settings_view(view)))


__all__ = ["joined", "router"]
