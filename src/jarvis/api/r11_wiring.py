# src/jarvis/api/r11_wiring.py
"""R11: the free proactive helpers on the app (docs/plans/r11-free-helpers.md D2, D3). Kept out of
`api/app.py`, as R4's and R6's wiring are. It is the ONLY wiring the four parts share: each part
fills `jarvis.helpers.<part>.part.build(ctx)` and its own `api/helpers_<part>.py` router, never
this file. app.py calls:

- `wire_r11` (lifespan, right after `wire_r6`, BEFORE the gateway and the Brain): the one
  `HelperSender` (the gate) over the alert policy, then the parts A, B, C, D in that order, each
  from a `HelperContext` with its own bound sender, the gateway's governed path for background
  reads (`reads`, read late), Part B's rain hint (`rain`, read late) and every part's pending
  sources plus the approvals waiting (`pending_all`, I1); each part's contract is checked
  (`check_part`: its tool families, job names and privacy ids). A part whose build fails or breaks
  the contract is left empty ("setup failed", logged by class name) and the others still run.
  The two composites (`helpers_clock`, `helpers_daily`) and the parts' No-AI phrases (into the one
  `BrainMode`) are made here. `helpers_enabled` off: every R11 part is None / empty.
- `install_r11_routes` (before the console router): `/v1/helpers` (api/helpers.py, I0) and the
  four parts' routers (`/v1/helpers/today`, `/house`, `/nudges`, `/kitchen`).
- `register_r11_tools(reg, parts)` (from `tools/setup.build_gateway(r11=...)`): every part's tools,
  so every call passes the gateway (policy, cards, R3 tokens, audit).
- `r11_tick_jobs(app)`: both composites for the morning tick; `helpers_clock` is also added once
  to the home watchdog (every 5 minutes, advisory) when Home is on. With Home off the watchdog
  route runs `app.state.helpers_clock` itself (api/home.py).
- `r11_privacy_sources(app)`: I0's `helpers_nudge` row and every part's rows (D17), before Faces.
- `helpers_brief(app)`: the brief's Helpers section over every part's contributors (or None).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI

from jarvis.api.helpers import change_limiter
from jarvis.api.helpers import router as helpers_router
from jarvis.api.helpers_house import router as house_router
from jarvis.api.helpers_kitchen import router as kitchen_router
from jarvis.api.helpers_nudges import router as nudges_router
from jarvis.api.helpers_today import router as today_router
from jarvis.api.identity import LEGACY_USER_ID, user_id_for_email
from jarvis.api.r4_wiring import _notifier
from jarvis.config import Settings
from jarvis.helpers.brief import HelpersBrief
from jarvis.helpers.clock import (
    ClockStatus,
    Composite,
    SweepJob,
    clock_composite,
    daily_composite,
)
from jarvis.helpers.gate import GateStore, HelperSender
from jarvis.helpers.house import part as house_part
from jarvis.helpers.kinds import (
    CLOCK_JOBS,
    DAILY_JOBS,
    PARTS,
    PRIVACY_IDS,
    PartName,
    tool_allowed,
)
from jarvis.helpers.kitchen import part as kitchen_part
from jarvis.helpers.nudges import part as nudges_part
from jarvis.helpers.ports import HelperContext, HelperPart, PendingItem, PendingSource
from jarvis.helpers.privacy import nudge_privacy
from jarvis.helpers.today import part as today_part
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.privacy.ports import PrivacySource
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditTrail
from jarvis.tools.background import BackgroundReads
from jarvis.tools.registry import ToolRegistry

log = get_logger(__name__)

Builder = Callable[[HelperContext], HelperPart]
BUILDERS: Mapping[PartName, Builder] = {
    "today": today_part.build,
    "house": house_part.build,
    "nudges": nudges_part.build,
    "kitchen": kitchen_part.build,
}
# what wire_r11 puts on app.state (None / {} = off); the routes read them per request
R11_STATE = (
    "helpers_sender",
    "helpers_status",
    "helpers_clock",
    "helpers_daily",
)
SETUP_FAILED = "setup failed"
HELPERS_OFF_NOTE = "The R11 helpers are OFF: JARVIS_HELPERS_ENABLED is off"


def owners_of(s: Settings) -> tuple[str, ...]:
    """The configured owners (the brief's list): the helpers serve these, never a client's id."""
    return tuple(dict.fromkeys(user_id_for_email(e) for e in s.owner_emails)) or (LEGACY_USER_ID,)


def check_part(name: PartName, part: object) -> HelperPart:
    """The part's contract (D2): its own name, tool families, job names and privacy ids."""
    if not isinstance(part, HelperPart) or part.name != name:
        raise ValueError(f"part {name} must return HelperPart(name={name!r})")
    bad_tools = [t.name for t in part.tools if not tool_allowed(name, t.name)]
    bad_jobs = [j.name for j in part.clock_jobs if j.name not in CLOCK_JOBS[name]]
    bad_jobs += [j.name for j in part.daily_jobs if j.name not in DAILY_JOBS[name]]
    bad_rows = [p.id for p in part.privacy if p.id not in PRIVACY_IDS[name]]
    if bad_tools or bad_jobs or bad_rows:
        raise ValueError(
            f"part {name} uses names it doesn't own: {bad_tools + bad_jobs + bad_rows}"
        )
    return part


def _off(app: FastAPI, why: str | None) -> None:
    st = app.state
    for name in R11_STATE:
        setattr(st, name, None)
    st.r11_parts = {}
    st.r11_jobs = None
    st.helpers_off = why


class ApprovalsPending:
    """D9 (Part A's note 3.2): his waiting approval cards as one pending line, read when asked.
    The gateway is read late (it is built after the parts); no gateway: nothing waiting."""

    name = "approvals"

    def __init__(self, st: Any) -> None:
        self._st = st

    async def pending(self, uid: str, now: datetime) -> list[PendingItem]:
        gw = getattr(self._st, "gateway", None)
        if gw is None:
            return []
        mine = [a for a in await gw.pending() if (a.scope or "").startswith(f"{uid}:")]
        n = len(mine)
        label = f"{n} approval{'s' if n != 1 else ''} waiting for your OK"
        return [PendingItem("approvals", label, "today")] if n else []


def _rain(st: Any) -> Callable[[], Any]:
    """Part B's rain hint for Part C (plan D12), read late: house.services["rain"]."""

    def rain() -> Any:
        parts: dict[str, HelperPart] = getattr(st, "r11_parts", None) or {}
        house = parts.get("house")
        return house.services.get("rain") if house is not None else None

    return rain


def _context(
    app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail, sender: HelperSender, name: PartName
) -> HelperContext:
    st = app.state
    approvals = ApprovalsPending(st)

    def pending_all() -> tuple[PendingSource, ...]:
        parts: dict[str, HelperPart] = getattr(st, "r11_parts", None) or {}
        return (*(src for p in parts.values() for src in p.pending), approvals)

    return HelperContext(
        settings=s,
        docs=docs,
        sender=sender.for_part(name),
        owners=owners_of(s),
        tz=s.user_timezone,
        prefix=s.firestore_prefix,
        now=st.helpers_now,
        audit=audit,
        pending_all=pending_all,
        permissions=lambda: getattr(st, "permissions", None),
        keyring=Keyring.from_settings(s),
        google=getattr(st, "google", None),
        billing=getattr(st, "billing", None),
        brains=getattr(st, "brains", None),
        brain_mode=getattr(st, "brain_mode", None),
        # CLAUDE.md: a background read takes the gateway's governed path (read late)
        reads=BackgroundReads(
            lambda: getattr(st, "gateway", None), audit=audit, now=st.helpers_now
        ),
        rain=_rain(st),
    )


def build_parts(
    app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail, sender: HelperSender
) -> dict[PartName, HelperPart]:
    """A, B, C, D in order; a part that fails is left empty and the others still run."""
    built: dict[PartName, HelperPart] = {}
    app.state.r11_parts = built  # read late by pending_all(), so C sees A's sources
    for name in PARTS:
        try:
            built[name] = check_part(
                name, BUILDERS[name](_context(app, s, docs, audit, sender, name))
            )
        except Exception as exc:  # noqa: BLE001 - one part never takes the others down
            log.error("an R11 part is OFF", extra={"part": name, "error": type(exc).__name__})
            built[name] = HelperPart(name=name, ready=SETUP_FAILED)
    return built


def _wire(app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail) -> None:
    st = app.state
    store = GateStore(docs, prefix=s.firestore_prefix)
    sender = HelperSender(_notifier(app), store, s, now=st.helpers_now)
    parts = build_parts(app, s, docs, audit, sender)
    status = ClockStatus(docs, prefix=s.firestore_prefix)
    owners = owners_of(s)
    st.helpers_sender, st.helpers_status = sender, status
    st.helpers_clock = clock_composite(
        [j for p in parts.values() for j in p.clock_jobs],
        owners,
        budget_s=s.helpers_clock_budget_s,
        now=st.helpers_now,
        status=status,
    )
    daily = [j for p in parts.values() for j in p.daily_jobs]
    sweep = SweepJob(store, tz=s.user_timezone, now=st.helpers_now)
    st.helpers_daily = daily_composite([*daily, sweep], owners, now=st.helpers_now)
    mode = getattr(st, "brain_mode", None)
    if mode is not None:
        mode.add_phrases([r for p in parts.values() for r in p.phrases])


async def wire_r11(app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail) -> None:
    """Everything R11 on `app.state` (None / empty when off), after R6 and before the gateway."""
    st = app.state
    if not callable(getattr(st, "helpers_now", None)):
        st.helpers_now = lambda: datetime.now(UTC)
    _off(app, None)
    if not s.helpers_enabled:
        log.info(HELPERS_OFF_NOTE)
        _off(app, "switched_off")
        return
    try:
        _wire(app, s, docs, audit)
    except Exception as exc:  # noqa: BLE001 - optional part: never fatal at start
        log.error("The R11 helpers are OFF: setup failed", extra={"error": type(exc).__name__})
        _off(app, "setup_failed")


def install_r11_routes(app: FastAPI) -> None:
    app.state.helpers_limit = change_limiter()
    for router in (helpers_router, today_router, house_router, nudges_router, kitchen_router):
        app.include_router(router)


def register_r11_tools(reg: ToolRegistry, parts: Mapping[str, HelperPart] | None) -> None:
    for part in (parts or {}).values():
        for tool in part.tools:
            reg.register(tool)


def r11_tick_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    """Both composites on the morning tick; the clock also on the home watchdog, added once."""
    st = app.state
    built: tuple[TickJob, ...] | None = getattr(st, "r11_jobs", None)
    if built is not None:
        return built
    clock: Composite | None = getattr(st, "helpers_clock", None)
    daily: Composite | None = getattr(st, "helpers_daily", None)
    jobs: tuple[TickJob, ...] = tuple(j for j in (clock, daily) if j is not None)
    if clock is not None and getattr(st, "home_watchdog", None) is not None:
        st.home_watchdog.extend(clock)  # around the clock, every 5 minutes (D3)
    st.r11_jobs = jobs
    return jobs


def r11_privacy_sources(app: FastAPI) -> tuple[PrivacySource, ...]:
    st = app.state
    sender: HelperSender | None = getattr(st, "helpers_sender", None)
    if sender is None:
        return ()
    parts: dict[str, HelperPart] = getattr(st, "r11_parts", None) or {}
    return (nudge_privacy(sender.store), *(src for p in parts.values() for src in p.privacy))


def helpers_brief(app: FastAPI) -> HelpersBrief | None:
    st = app.state
    if getattr(st, "helpers_sender", None) is None:
        return None

    def contributors() -> list[Any]:
        parts: dict[str, HelperPart] = getattr(st, "r11_parts", None) or {}
        return [c for p in parts.values() for c in p.brief]

    return HelpersBrief(contributors)


__all__ = [
    "BUILDERS",
    "ApprovalsPending",
    "R11_STATE",
    "SETUP_FAILED",
    "build_parts",
    "check_part",
    "helpers_brief",
    "install_r11_routes",
    "owners_of",
    "r11_privacy_sources",
    "r11_tick_jobs",
    "register_r11_tools",
    "wire_r11",
]
