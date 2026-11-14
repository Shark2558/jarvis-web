# src/jarvis/api/r7_wiring.py
"""R7 on the app (docs/plans/r7-mobile.md "The I0 seams" 8, 14, 20): the four parts' one join.

- `wire_r7(app, s, docs, audit)`: builds each part (`jarvis.mobile.ports`) into
  `app.state.r7_parts`, BEFORE the R11 helpers are wired. A part whose build
  raises, or that names itself, a tool, a door route or a service it doesn't own, is left empty
  ("setup failed") and the others still run. It also hands Part D's `sos_hook` to the Telegram
  front door (`TelegramService.sos`), when both exist.
- `mobile_tick_jobs(app)`: the parts' clock and daily jobs as TWO tick jobs of their own,
  `mobile_clock` (also on the one 5-minute clock, R14 D7) and `mobile_daily`, built once and
  independent of the R11 helpers (switched off or failed at set-up: the 400-day sweeps and
  `watch_stale` still run), inside the tick's own deadline (I1 fixer, code M5).
- `mobile_tools(parts)`: every part's tools, for `tools.setup.build_gateway(r7=...)`.
- `install_r7_routes(app)`: the parts' routers (`api/app_shell.py`, `vision.py`, `phone.py`,
  `watch.py`, `sos.py`; each part owns its own).
- `mobile_privacy_sources(app)`: the parts' privacy rows, for `api/personal.py`.
- `mobile_phrases(app)` / `install_mobile_phrases(app)`: the parts' No-AI phrase routers
  (`services["phrases"]`), put into `BrainMode` once, after the helpers' and R11.1's own.
- `mobile_brief(app)`: the parts' morning-brief contributors (`services["brief"]`).
- `mobile_sleep(app)`: the brief's sleep line (`BriefData.sleep`) from Part D's contributor (I1).
- `door_handlers(app)`: {door route: handler} from the parts that own each route (`DOOR_OWNER`),
  for Part C's door (`/phone/v1/<route>`).
- `install_app_lock(app)`: the app lock's slot (D21). Added BEFORE R6's show lock, so it runs
  inside it, and both run inside the session middleware (it reads the cookie session). Until
  Part C puts its check into `services["app_lock"]` it passes everything through; then a locked
  cookie session gets 423 {error: device_locked} on every route that is not on D21's
  never-locked list (`ports.never_locked`), and a check that fails 503 {error: lock_unreadable}.
- `BODY_CAPS`: the body caps of `/phone/v1/inbox` and `/app/share/in` for `api/body.py`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from datetime import UTC, date, datetime, tzinfo
from importlib import import_module
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from jarvis.api.app_shell import router as shell_router
from jarvis.api.phone import router as phone_router
from jarvis.api.r4_wiring import _notifier
from jarvis.api.sos import router as sos_router
from jarvis.api.vision import router as vision_router
from jarvis.api.watch import router as watch_router
from jarvis.brief.models import SleepLine
from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.mobile.ports import (
    DOOR_CAPS,
    DOOR_OWNER,
    DOOR_PREFIX,
    PARTS,
    MobileContext,
    MobilePart,
    PartName,
    PhoneHandler,
    never_locked,
    tool_allowed,
)
from jarvis.privacy.ports import PrivacySource
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditTrail
from jarvis.tools.base import Tool

log = get_logger(__name__)

PART_MODULES: Mapping[PartName, str] = {
    "shell": "jarvis.api.app_shell",
    "vision": "jarvis.vision.part",
    "phone": "jarvis.phone.part",
    "body": "jarvis.watch.part",
}
SETUP_FAILED = "setup failed"
SHARE_IN_PATH = "/app/share/in"
_MB = 1024 * 1024
BODY_CAPS: Mapping[str, int] = {
    f"{DOOR_PREFIX}inbox": DOOR_CAPS["inbox"],
    # five shared items of at most 10 MB: only reaches the server when the share worker is not
    # installed yet, and that route discards the body unread (D15)
    SHARE_IN_PATH: 5 * 10 * _MB + 64 * 1024,
}
# a service only one part may offer (I1: `sos_contacts`, Part D's, read by Part C's hello)
SERVICE_OWNER: Mapping[str, PartName] = {
    "app_lock": "phone",
    "sos_hook": "body",
    "sos_contacts": "body",
    "linked_since": "phone",  # I1: Part C's link time, read by Part D's watch_stale
}
LOCKED = "JARVIS is locked on this device. Unlock it with your passkey."
UNREADABLE = "JARVIS couldn't check its lock just now. Try again in a moment."
WS_LOCKED, WS_UNREADABLE = 4423, 4503


def _build(name: PartName, ctx: MobileContext) -> MobilePart:
    part: MobilePart = import_module(PART_MODULES[name]).build(ctx)
    return part


def check_part(name: PartName, part: object) -> MobilePart:
    """The part's contract: its own name, and only the tools, door routes and services it owns."""
    if not isinstance(part, MobilePart) or part.name != name:
        raise ValueError(f"part {name} must return MobilePart({name!r})")
    bad = [t.name for t in part.tools if not tool_allowed(name, t.name)]
    if bad:
        raise ValueError(f"part {name} registers tools it doesn't own: {bad}")
    door = part.services.get("door") or {}
    if not isinstance(door, Mapping) or any(DOOR_OWNER.get(r) != name for r in door):
        raise ValueError(f"part {name} offers door routes it doesn't own: {sorted(door)}")
    taken = [k for k, owner in SERVICE_OWNER.items() if k in part.services and owner != name]
    if taken:
        raise ValueError(f"part {name} offers services it doesn't own: {taken}")
    return part


def build_parts(ctx: MobileContext) -> dict[PartName, MobilePart]:
    built: dict[PartName, MobilePart] = {}
    for name in PARTS:
        try:
            built[name] = check_part(name, _build(name, ctx))
        except Exception as exc:  # noqa: BLE001 - one part never stops the others or the app
            log.error(
                "R7 part left out: setup failed",
                extra={"part": name, "error": type(exc).__name__},
            )
            built[name] = MobilePart(name, ready=SETUP_FAILED)
    return built


async def wire_r7(app: FastAPI, s: Settings, docs: Docs | None, audit: AuditTrail | None) -> None:
    """The four parts on `app.state.r7_parts`, after R6 and before the R11 helpers."""
    st = app.state

    def late(name: str) -> Any:
        return getattr(st, name, None)

    ctx = MobileContext(s=s, docs=docs, audit=audit, state=late, notifier=lambda: _notifier(app))
    st.r7_parts = build_parts(ctx)
    from jarvis.api.r11_wiring import owners_of  # late: r11_wiring imports this module

    st.r7_owners = owners_of(s)  # the configured owners, as the helpers' composites serve them
    hook = st.r7_parts["body"].services.get("sos_hook")
    telegram = getattr(st, "telegram", None)
    if hook is not None and telegram is not None:
        telegram.sos = hook  # D20: the one hook in the Telegram front door


def _parts(app: FastAPI) -> Mapping[PartName, MobilePart]:
    return getattr(app.state, "r7_parts", None) or {}


def mobile_tools(parts: Mapping[PartName, MobilePart] | None) -> tuple[Tool, ...]:
    return tuple(t for p in (parts or {}).values() for t in p.tools)


MOBILE_CLOCK, MOBILE_DAILY = "mobile_clock", "mobile_daily"
CLOCK_BUDGET_S, DAILY_BUDGET_S = 20.0, 60.0  # each inside MAX_BUDGET_S and the tick's 150 s


def mobile_tick_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    """R7's own two tick jobs (never the R11 helpers' composites), built once. The clock one also
    rides the one 5-minute clock (R14 D7: Home on or off), as R11's does."""
    from jarvis.helpers.clock import Composite  # a plain runner of jobs: it needs no R11 wiring

    st = app.state
    built: tuple[TickJob, ...] | None = getattr(st, "r7_jobs", None)
    if built is not None:
        return built
    owners = tuple(getattr(st, "r7_owners", ()) or ())
    now = lambda: datetime.now(UTC)  # noqa: E731 - only the composite's own bookkeeping
    clock, daily = mobile_clock_jobs(app), mobile_daily_jobs(app)
    jobs: list[TickJob] = []
    if clock:
        jobs.append(Composite(MOBILE_CLOCK, clock, owners, budget_s=CLOCK_BUDGET_S, now=now))
    if daily:
        jobs.append(Composite(MOBILE_DAILY, daily, owners, budget_s=DAILY_BUDGET_S, now=now))
    if clock:  # around the clock, every 5 minutes, Home on or off (R14 D7)
        from jarvis.api.tick_wiring import add_clock_job

        add_clock_job(app, jobs[0])
    st.r7_jobs = built = tuple(jobs)
    return built


def mobile_clock_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    return tuple(j for p in _parts(app).values() for j in p.clock_jobs)


def mobile_daily_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    return tuple(j for p in _parts(app).values() for j in p.daily_jobs)


def mobile_privacy_sources(app: FastAPI) -> tuple[PrivacySource, ...]:
    return tuple(src for p in _parts(app).values() for src in p.privacy)


def mobile_phrases(app: FastAPI) -> tuple[Any, ...]:
    """The parts' No-AI routers (`BrainMode.add_phrases`)."""
    return tuple(r for p in _parts(app).values() for r in p.services.get("phrases", ()) or ())


def install_mobile_phrases(app: FastAPI) -> None:
    """The parts' phrases into the app's BrainMode once, ONE AT A TIME (as R11.1's): one that does
    not fit is an error in the log and never drops the others or stops the start."""
    mode = getattr(app.state, "brain_mode", None)
    if mode is None:
        return
    new = [r for r in mobile_phrases(app) if r not in mode.phrases]
    for n, router in enumerate(new, start=1):
        try:
            mode.add_phrases([router])
        except ValueError as exc:
            log.error(
                "an R7 phrase did not fit into No-AI mode",
                extra={
                    "phrase": getattr(router, "__name__", type(router).__name__),
                    "left": len(new) - n,
                    "reason": str(exc),
                },
            )


def mobile_brief(app: FastAPI) -> tuple[Any, ...]:
    """The parts' brief contributors (`helpers.ports.BriefContributor`)."""
    return tuple(c for p in _parts(app).values() if (c := p.services.get("brief")) is not None)


class MobileSleep:
    """R7 D18 (I1): the brief's sleep line from the part that offers it (`services["brief"]`
    with a `sleep(uid, tz, day)`: Part D's `SleepBrief`), read late. Not a Helpers contributor:
    that section is e-mailed and sent to Telegram, and this line never is."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def sleep(self, uid: str, tz: tzinfo, day: date) -> SleepLine | None:
        for part in _parts(self._app).values():
            read = getattr(part.services.get("brief"), "sleep", None)
            if callable(read):
                got = await read(uid, tz, day)
                return got if isinstance(got, SleepLine) else None
        return None


def mobile_sleep(app: FastAPI) -> MobileSleep:
    """The source `BriefService(sleep=...)` reads (`api/app.py` `build_brief_service`)."""
    return MobileSleep(app)


def door_handlers(app: FastAPI) -> dict[str, PhoneHandler]:
    """{door route: handler}, each from the one part that owns the route."""
    out: dict[str, PhoneHandler] = {}
    for name, part in _parts(app).items():
        for route, handler in (part.services.get("door") or {}).items():
            if DOOR_OWNER.get(route) == name and callable(handler):
                out[route] = handler
    return out


def install_r7_routes(app: FastAPI) -> None:
    for router in (shell_router, vision_router, phone_router, watch_router, sos_router):
        app.include_router(router)


# ---- the app lock's slot (D21) ------------------------------------------------------------------
Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]
LockCheck = Callable[[Scope], Awaitable[bool]]


def _lock_check(scope: Scope) -> LockCheck | None:
    owner = scope.get("app")
    parts = getattr(getattr(owner, "state", None), "r7_parts", None) or {}
    phone = parts.get("phone")
    check = phone.services.get("app_lock") if phone is not None else None
    return check if callable(check) else None


class AppLockSlot:
    """Pure ASGI (no body is read). A pass-through until Part C's check is wired."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope.get("type")
        method = str(scope.get("method") or "GET")
        check = _lock_check(scope) if kind in ("http", "websocket") else None
        if check is None or never_locked(method, str(scope.get("path") or "")):
            await self.app(scope, receive, send)
            return
        try:
            locked = await check(scope)
        except Exception as exc:  # noqa: BLE001 - a lock that can't be read never opens
            log.warning("app lock unreadable", extra={"error": type(exc).__name__})
            await _refuse(scope, receive, send, 503, "lock_unreadable", UNREADABLE)
            return
        if locked:
            await _refuse(scope, receive, send, 423, "device_locked", LOCKED)
            return
        await self.app(scope, receive, send)


async def _refuse(
    scope: Scope, receive: Receive, send: Send, status: int, code: str, detail: str
) -> None:
    if scope.get("type") == "websocket":
        await send(
            {"type": "websocket.close", "code": WS_LOCKED if status == 423 else WS_UNREADABLE}
        )
        return
    body = {"error": code, "detail": detail}
    await JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})(
        scope, receive, send
    )


def install_app_lock(app: FastAPI) -> None:
    app.add_middleware(AppLockSlot)


__all__ = [
    "BODY_CAPS",
    "PART_MODULES",
    "SETUP_FAILED",
    "AppLockSlot",
    "build_parts",
    "check_part",
    "door_handlers",
    "install_app_lock",
    "install_mobile_phrases",
    "install_r7_routes",
    "mobile_brief",
    "MOBILE_CLOCK",
    "MOBILE_DAILY",
    "mobile_clock_jobs",
    "mobile_daily_jobs",
    "mobile_tick_jobs",
    "mobile_phrases",
    "mobile_privacy_sources",
    "mobile_tools",
    "wire_r7",
]
