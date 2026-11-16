# src/jarvis/api/r13_wiring.py
"""R13 on the app (docs/plans/r13-wardrobe.md "The I0 seam list" 10): the four parts' one join.

- `wire_r13(app, s, docs, audit)`: builds each part (`jarvis.wardrobe.ports`) into
  `app.state.r13_parts`, after R14's parts and BEFORE the gateway (their tools). A part whose build
  raises, or that names itself, a tool, a job, a service or a data source it doesn't own, is left
  empty ("setup failed") and the others still run. Then `join_store` (B's review writer and every
  observer, C's refresh first, bound into A's store: a hold is written with its entry, D4.4),
  `register_bin` (A's restorer and purger for `wardrobe_item` in Recently deleted) and
  `install_r13_phrases` (D's No-AI routers, FIRST, ahead of R14's `things`, D6).
- `app.state.wardrobe_now`: the wardrobe's one clock (UTC), the real one unless a test set its
  own before the start; `owner_zone` his zone (the brief store's, else `user_timezone`).
- `r13_tools(parts)`: every part's tools, for `tools.setup.build_gateway(r13=...)`.
- `r13_tick_jobs(app)` / `r13_clock_jobs(app)`: the morning tick's and the 5-minute clock's jobs
  (`api/tick_wiring.py`; `outfit_clock` is advisory on the watchdog, `home/watchdog.py`).
- `r13_privacy_sources(app)`: the parts' privacy rows, for `api/personal.py` (before home's).
- `BODY_CAPS`: the restore's body cap for `api/body.py` (H3): the wardrobe backup's upper bound
  (30 MB) plus room for the envelope, on both restore paths (the check reads the file too); the
  routes read it with `read_capped` at `wardrobe_backup_max_mb`.
- `install_r13_routes(app)`: `GET /v1/r13` and the parts' routers (`api/wardrobe.py`,
  `api/laundry.py`, `api/outfits.py`; each part owns its own).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from importlib import import_module
from typing import Any, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI

from jarvis.api.laundry import router as laundry_router
from jarvis.api.outfits import router as outfits_router
from jarvis.api.r4_wiring import _notifier
from jarvis.api.r13_status import router as status_router
from jarvis.api.wardrobe import router as wardrobe_router
from jarvis.brief.store import BriefStore
from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.privacy.ports import PrivacySource
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditTrail
from jarvis.tools.background import BackgroundReads
from jarvis.tools.base import Tool
from jarvis.wardrobe.catalog.jobs import Closer, WardrobeSweep
from jarvis.wardrobe.kept import stand_ins
from jarvis.wardrobe.ports import (
    CLOCK_JOB_NAMES,
    JOB_OWNER,
    PARTS,
    SERVICE_OWNER,
    ChangeObserver,
    PartName,
    PrivacyRow,
    ReviewWriter,
    WardrobeContext,
    WardrobeData,
    WardrobePart,
    WardrobeStore,
    tool_allowed,
)
from jarvis.wardrobe.styling.rules import Rules
from jarvis.wardrobe.styling.wear import close_forgotten

log = get_logger(__name__)

PART_MODULES: Mapping[PartName, str] = {
    "catalog": "jarvis.wardrobe.catalog.part",
    "laundry": "jarvis.wardrobe.laundry.part",
    "styling": "jarvis.wardrobe.styling.part",
    "phone": "jarvis.wardrobe.phone.part",
}
SETUP_FAILED = "setup failed"
RESTORE_PATHS = ("/v1/wardrobe/restore", "/v1/wardrobe/restore/check")
RESTORE_BODY_BYTES = 30 * 1024 * 1024 + 64 * 1024  # wardrobe_backup_max_mb's ceiling + envelope
BODY_CAPS: Mapping[str, int] = dict.fromkeys(RESTORE_PATHS, RESTORE_BODY_BYTES)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _build(name: PartName, ctx: WardrobeContext) -> WardrobePart:
    part: WardrobePart = import_module(PART_MODULES[name]).build(ctx)
    return part


def _check_jobs(name: PartName, part: WardrobePart) -> None:
    for job, clock in [(j, True) for j in part.clock_jobs] + [(j, False) for j in part.daily_jobs]:
        jname = getattr(job, "name", None)
        if JOB_OWNER.get(str(jname)) != name or (jname in CLOCK_JOB_NAMES) is not clock:
            where = "clock" if clock else "daily"
            raise ValueError(f"part {name} offers a {where} job it doesn't own: {jname}")


def check_part(name: PartName, part: object) -> WardrobePart:
    """The part's contract: its own name, and only the tools, jobs and services it owns; its
    observers and data sources of the right shape."""
    if not isinstance(part, WardrobePart) or part.name != name:
        raise ValueError(f"part {name} must return WardrobePart({name!r})")
    bad = [t.name for t in part.tools if not tool_allowed(name, t.name)]
    if bad:
        raise ValueError(f"part {name} registers tools it doesn't own: {bad}")
    _check_jobs(name, part)
    taken = [k for k, owner in SERVICE_OWNER.items() if k in part.services and owner != name]
    if taken:
        raise ValueError(f"part {name} offers services it doesn't own: {taken}")
    if not all(isinstance(o, ChangeObserver) for o in part.observers):
        raise ValueError(f"part {name} offers an observer without changed()")
    if not all(isinstance(d, WardrobeData) for d in part.data):
        raise ValueError(f"part {name} offers data without count, export and delete")
    if any(d.row not in get_args(PrivacyRow) for d in part.data):
        raise ValueError(f"part {name} offers data with no Privacy row")
    return part


def build_parts(ctx: WardrobeContext) -> dict[PartName, WardrobePart]:
    built: dict[PartName, WardrobePart] = {}
    for name in PARTS:
        try:
            built[name] = check_part(name, _build(name, ctx))
        except Exception as exc:  # noqa: BLE001 - one part never stops the others or the app
            log.error(
                "R13 part left out: setup failed",
                extra={"part": name, "error": type(exc).__name__},
            )
            built[name] = WardrobePart(name, ready=SETUP_FAILED)
        built[name] = _with_kept(built[name], ctx)
    return built


def _with_kept(part: WardrobePart, ctx: WardrobeContext) -> WardrobePart:
    """A part that is off or failed offers no data of its own: it still answers for what it left
    on disk (Privacy says "Couldn't check right now" and can delete it; never "Nothing kept")."""
    if part.data or ctx.docs is None:
        return part
    return replace(part, data=stand_ins(part.name, ctx.docs, ctx.s.firestore_prefix))


def _parts(app: FastAPI) -> Mapping[PartName, WardrobePart]:
    return getattr(app.state, "r13_parts", None) or {}


def service(app: FastAPI, name: str) -> Any:
    """A named service from its one owner (`SERVICE_OWNER`), or None."""
    part = _parts(app).get(SERVICE_OWNER[name])
    return part.services.get(name) if part is not None else None


def wardrobe_store(app: FastAPI) -> WardrobeStore | None:
    store = service(app, "store")
    return store if isinstance(store, WardrobeStore) else None


def owner_zone(docs: Docs | None, s: Settings) -> Any:
    """`ctx.zone(uid)`: the brief store's zone for him (his calendar's, as last seen), else
    `user_timezone` (D15). A zone that can't be read is the setting's, never the server's."""
    store = BriefStore(docs, prefix=s.firestore_prefix) if docs is not None else None

    async def zone(uid: str) -> ZoneInfo:
        name = s.user_timezone
        if store is not None:
            try:
                name = (await store.get_settings(uid)).tz or name
            except Exception as exc:  # noqa: BLE001 - a zone that can't be read is the setting's
                log.warning("R13: his zone unreadable", extra={"error": type(exc).__name__})
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo(s.user_timezone)

    return zone


def _outside(app: FastAPI) -> Any:
    """R11 B's OutsideStore for C's weather (D14), read late through the house part's service."""
    parts: Mapping[str, Any] = getattr(app.state, "r11_parts", None) or {}
    house = parts.get("house")
    svc = house.services.get("house") if house is not None else None
    return getattr(svc, "outside", None)


def context(
    app: FastAPI, s: Settings, docs: Docs | None, audit: AuditTrail | None
) -> WardrobeContext:
    st = app.state
    if not callable(getattr(st, "wardrobe_now", None)):
        st.wardrobe_now = _utcnow
    reads = (
        BackgroundReads(lambda: getattr(st, "gateway", None), audit=audit, now=st.wardrobe_now)
        if audit is not None
        else None
    )
    return WardrobeContext(
        s=s,
        docs=docs,
        keyring=Keyring.from_settings(s),
        audit=audit,
        now=lambda: st.wardrobe_now(),
        zone=owner_zone(docs, s),
        state=lambda name: getattr(st, name, None),
        notifier=lambda: _notifier(app),
        reads=lambda: reads,
        outside=lambda: _outside(app),
        store=lambda: wardrobe_store(app),
    )


async def wire_r13(app: FastAPI, s: Settings, docs: Docs | None, audit: AuditTrail | None) -> None:
    """The four parts on `app.state.r13_parts`, after R14's and before the gateway."""
    st = app.state
    st.r13_parts = build_parts(context(app, s, docs, audit)) if s.wardrobe_enabled else {}
    join_store(app)
    join_sweep(app)
    register_bin(app)
    install_r13_phrases(app)


def join_store(app: FastAPI) -> None:
    """B's review writer and every part's observers (C's refresh first) into A's store, once."""
    store = wardrobe_store(app)
    if store is None:
        return
    writer = service(app, "review_writer")
    refresh = service(app, "refresh")
    observers: list[ChangeObserver] = [refresh] if isinstance(refresh, ChangeObserver) else []
    observers += [o for p in _parts(app).values() for o in p.observers if o is not refresh]
    store.bind(
        review_writer=writer if isinstance(writer, ReviewWriter) else None, observers=observers
    )


def sweep_closer(store: WardrobeStore, rules: Rules) -> Closer:
    """A's sweep closes a forgotten wear by C's rule: the one source of the rewear rule."""

    async def close(uid: str, now: datetime, zone: ZoneInfo, at: str) -> int:
        return await close_forgotten(store, uid, now=now, zone=zone, close=at, rules=rules)

    return close


def join_sweep(app: FastAPI) -> None:
    """Bind A's `wardrobe_sweep` to C's checked rules (C off or failed: the step is skipped)."""
    store = wardrobe_store(app)
    styling = getattr(service(app, "refresh"), "styling", None)
    rules = getattr(styling, "rules", None)
    catalog = _parts(app).get("catalog")
    if store is None or rules is None or catalog is None:
        return
    for job in catalog.daily_jobs:
        if isinstance(job, WardrobeSweep):
            job.closer = sweep_closer(store, rules)


def register_bin(app: FastAPI) -> None:
    """A's restorer and purger for the bin's in-place kind `wardrobe_item` (D16)."""
    undo = getattr(app.state, "undo", None)
    bin_ = service(app, "bin")
    if undo is None or bin_ is None:
        return
    if callable(getattr(bin_, "restore", None)) and callable(getattr(bin_, "purge", None)):
        undo.register("wardrobe_item", bin_, bin_)


def install_r13_phrases(app: FastAPI) -> None:
    """D's routers into the app's BrainMode FIRST (`add_phrases(..., first=True)`), one at a time
    and in their own order: one that does not fit is an error in the log, never a stop."""
    mode = getattr(app.state, "brain_mode", None)
    found = service(app, "phrases")
    if mode is None or not found:
        return
    new = [r for r in found if r not in mode.phrases]
    for n, router in enumerate(reversed(new), start=1):  # each goes first: reversed keeps order
        try:
            mode.add_phrases([router], first=True)
        except ValueError as exc:
            log.error(
                "an R13 phrase did not fit into No-AI mode",
                extra={
                    "phrase": getattr(router, "__name__", type(router).__name__),
                    "left": len(new) - n,
                    "reason": str(exc),
                },
            )


def r13_tools(parts: Mapping[PartName, WardrobePart] | None) -> tuple[Tool, ...]:
    return tuple(t for p in (parts or {}).values() for t in p.tools)


def r13_tick_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    return tuple(j for p in _parts(app).values() for j in p.daily_jobs)


def r13_clock_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    return tuple(j for p in _parts(app).values() for j in p.clock_jobs)


def r13_privacy_sources(app: FastAPI) -> tuple[PrivacySource, ...]:
    return tuple(src for p in _parts(app).values() for src in p.privacy)


def r13_data(app: FastAPI) -> Sequence[WardrobeData]:
    """Every part's `WardrobeData`, for D's Privacy rows (`wardrobe/phone/privacy.py`)."""
    return tuple(d for p in _parts(app).values() for d in p.data)


def install_r13_routes(app: FastAPI) -> None:
    for router in (status_router, wardrobe_router, laundry_router, outfits_router):
        app.include_router(router)


__all__ = [
    "BODY_CAPS",
    "PART_MODULES",
    "RESTORE_BODY_BYTES",
    "RESTORE_PATHS",
    "SETUP_FAILED",
    "build_parts",
    "check_part",
    "context",
    "install_r13_phrases",
    "install_r13_routes",
    "join_store",
    "join_sweep",
    "owner_zone",
    "r13_clock_jobs",
    "r13_data",
    "r13_privacy_sources",
    "r13_tick_jobs",
    "r13_tools",
    "register_bin",
    "service",
    "sweep_closer",
    "wardrobe_store",
    "wire_r13",
]
