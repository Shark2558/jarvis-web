# src/jarvis/api/outfits.py
"""R13 Part C's routes, under `/v1/outfits` (docs/plans/r13-wardrobe.md "The HTTP contract", D13).

    GET /v1/outfits             today's and tomorrow's plans (or a suggestion) with their looks
                                and reasons, and tomorrow's weather assumption (`OutfitsView`)
    GET /v1/outfits/calendars   his calendars by a keyed reference and their names, shown live
                                (a governed read on the Calendar row: "Allow" only), or why not
    PUT /v1/outfits/settings    the calendar (a reference from that list, or none: off), the
                                fields JARVIS may read, the evening alert, auto-swap
                                (`OutfitSettings` -> `SettingsView`); the contract's `lead_h`
                                is accepted and never stored (code review M8: dropped)

Owner-only (`require_auth`), `no-store`, limited per owner (30 changes and 60 reads a minute,
`api.r13_status.limited`); the styling service is read per request from
`app.state.r13_parts["styling"]` (through its refresh: C offers no other service name). Errors
are plain words. Switching his calendar off keeps its plans as his own; a settings change is
recorded on the audit chain (`record_change`: whether a calendar is chosen and the field names,
never an id).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.r13_status import NO_STORE, limited, part_of
from jarvis.api.settings_audit import record_change
from jarvis.wardrobe import http
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.styling import texts, views
from jarvis.wardrobe.styling.calendar import manual_from_now
from jarvis.wardrobe.styling.plans import Choice, StylingDoc
from jarvis.wardrobe.styling.service import Answer, Here, Styling

router = APIRouter(dependencies=[Depends(require_auth)])
NOT_SET_UP = "Outfits aren't set up on this JARVIS."
SENT_FIELDS = frozenset({"fields", "plan_alerts", "auto_swap"})  # `lead_h`: never stored (M8)


def _ok(model: Any) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), headers=NO_STORE)


def _err(status: int, words: str) -> JSONResponse:
    return JSONResponse({"detail": words}, status_code=status, headers=NO_STORE)


def _refresh(request: Request) -> Any:
    part = part_of(request, "styling")
    return part.services.get("refresh") if part is not None else None


def _styling(request: Request) -> tuple[Styling | None, str]:
    found = _refresh(request)
    s = getattr(found, "styling", None)
    if not isinstance(s, Styling):
        return None, NOT_SET_UP
    return s, s.off() or ""


async def _day(
    s: Styling, uid: str, here: Here, doc: StylingDoc, view: WardrobeView, day_off: int
) -> list[Answer]:
    day = here.today + timedelta(days=day_off)
    found = [await s.answer(uid, here, doc, view, p) for p in doc.on(day)]
    return found or [await s.fresh(uid, here, doc, view, day=day, occasion=None, code=None)]


@router.get("/v1/outfits", include_in_schema=False)
async def outfits(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    if (refused := limited(request, "outfits", uid, change=False)) is not None:
        return refused
    s, off = _styling(request)
    if s is None or off:
        return _err(503, off or NOT_SET_UP)
    view = await s.view(uid)
    if view is None:
        return _err(503, texts.NOT_READY_YET)
    here, doc = await s.where(uid), await s.plans.read(uid)
    show = view.settings.show_private
    today = await _day(s, uid, here, doc, view, 0)
    tomorrow = await _day(s, uid, here, doc, view, 1)

    def shown(answers: list[Answer]) -> tuple[http.PlanView, ...]:
        return tuple(
            views.plan_view(view, a, s.rules, here.zone, show_private=show) for a in answers
        )

    part = part_of(request, "styling")
    ready = part.ready if part is not None else NOT_SET_UP
    body = http.OutfitsView(
        ready=ready, today=shown(today), tomorrow=shown(tomorrow), weather=tomorrow[0].weather.words
    )
    return _ok(body)


@router.get("/v1/outfits/calendars", include_in_schema=False)
async def calendars(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    if (refused := limited(request, "outfits_calendars", uid, change=False)) is not None:
        return refused
    s, off = _styling(request)
    calendar = getattr(_refresh(request), "calendar", None)
    if s is None or off or calendar is None:
        return _ok(http.Calendars(why=off or NOT_SET_UP))
    found, why = await calendar.calendars(uid)
    choices = tuple(
        http.CalendarChoice(id_ref=ref, title=name or "A calendar", primary=primary)
        for ref, _id, name, primary in found
    )
    return _ok(http.Calendars(calendars=choices, why=why))


def _settings_view(s: Styling, choice: Choice, view: WardrobeView | None) -> http.SettingsView:
    a = view.settings if view is not None else None
    return http.SettingsView(
        calendar_chosen=choice.calendar is not None, fields=choice.fields,
        plan_alerts=choice.plan_alerts, auto_swap=choice.auto_swap,
        ai_tagging=a.ai_tagging if a else False, show_private=a.show_private if a else False,
        tag_month_inr=view.tag_inr if view is not None else 0.0,
        tag_cap_inr=s.ctx.s.wardrobe_ai_tag_month_inr,
        custom_types=a.custom_types if a else (),
    )  # fmt: skip


@router.put("/v1/outfits/settings", include_in_schema=False)
async def put_settings(
    request: Request, body: http.OutfitSettings, uid: str = Depends(current_user)
) -> JSONResponse:
    """What he sent changes; what he did not send stays (code review H2: D's panel sends one
    toggle without `calendar`). An explicit `"calendar": null` switches his calendar off."""
    if (refused := limited(request, "outfits_settings", uid, change=True)) is not None:
        return refused
    s, off = _styling(request)
    if s is None or off:
        return _err(422, off or NOT_SET_UP)
    keep_cal = "calendar" not in body.model_fields_set
    calendar = getattr(_refresh(request), "calendar", None)
    cal_id: str | None = None
    if not keep_cal and body.calendar is not None:
        cal_id, why = await calendar.resolve(uid, body.calendar) if calendar else (None, NOT_SET_UP)
        if cal_id is None:
            return _err(422, why)
    sent = body.model_dump(include=set(body.model_fields_set) & SENT_FIELDS)
    here, moved = await s.where(uid), {"calendar": False}

    def apply(d: StylingDoc) -> StylingDoc:
        cal = d.choice.calendar if keep_cal else cal_id
        choice = d.choice.model_copy(update={**sent, "calendar": cal})
        moved["calendar"] = d.choice.calendar != cal
        if not moved["calendar"]:
            return d.model_copy(update={"choice": choice})
        out = manual_from_now(d, here.now) if d.choice.calendar else d
        return out.model_copy(update={"choice": choice, "cal_read_at": None, "cal_failed_at": None})

    doc = await s.change(uid, apply)
    if moved["calendar"] and calendar is not None:
        await calendar.sealed.delete(uid)  # the last read of a calendar he left (security L5)
    await record_change(request, agent="outfits", tool="outfit_settings",
                        args={"calendar": doc.choice.calendar is not None,
                              "fields": sorted(doc.choice.fields)})  # fmt: skip
    return _ok(_settings_view(s, doc.choice, await s.view(uid)))


__all__ = ["router"]
