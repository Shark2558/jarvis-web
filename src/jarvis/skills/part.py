# src/jarvis/skills/part.py
"""R14 Part C (cost and the skill register, docs/plans/r14-hardening.md D8-D11): the part's one
join with the app (`jarvis.hardening.ports`).

- tool `skills_open` (R1, no side effect; `skills.open_tool`);
- services: `offer` (`skills.offer.SkillOffer`, the brain's tool slot, only while `tool_offer` is
  "by_skill"), `ledger` (`billing.ledger.TokenLedgerStore`, the brain's record slot, only while
  `token_ledger_enabled` and a document store exists), and for its own routes `register` (the
  `SkillRegister`) and `ledger_view` (the same store, read only, whatever the switch says);
- the Vitals item `ai_parts` ("Where the AI money goes", in ₹, quiet: it never rings);
- the privacy row `token_ledger` (counts, 90 days; no export or delete: counts only).
A catalogue that can't be read raises, so the wiring leaves the part out ("setup failed") and the
brain offers every tool, as before R14.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final
from zoneinfo import ZoneInfo

from jarvis.billing.fx import DEFAULT_RATE
from jarvis.billing.ledger import LEDGER_DAYS, TokenLedgerStore, ai_parts_note
from jarvis.hardening.ports import HardeningContext, HardeningPart
from jarvis.logging import get_logger
from jarvis.privacy.sources import GOOGLE_ENC, SEC_ACTIVITY, CallbackSource, Look, Spec
from jarvis.skills.offer import SkillOffer
from jarvis.skills.open_tool import skills_open_tool
from jarvis.skills.registry import CatalogueError, SkillRegister, load_catalogue
from jarvis.tools.registry import ToolRegistry
from jarvis.vitals.own import OwnItem, own_item

log = get_logger(__name__)

READY: Final = "ready"
ALL_TOOLS: Final = "every tool offered (tool_offer = all)"
LEDGER_OFF: Final = "the token ledger is switched off"
NO_DOCS: Final = "the token ledger needs the document store"
VITALS_ID: Final = "ai_parts"
PRIVACY_ID: Final = "token_ledger"
_COUNTED = "counted from this month's model calls"
_OFF_NOTE = "The token ledger is switched off in the settings."
_UNREAD_NOTE = "The token ledger can't be read just now."


def _late_registry(ctx: HardeningContext) -> ToolRegistry | None:
    registry = getattr(ctx.state("gateway"), "registry", None)
    return registry if isinstance(registry, ToolRegistry) else None


async def _rate(ctx: HardeningContext) -> float:
    """₹ per $ now: the app's own daily rate (`Billing.inr`), else the default."""
    billing = ctx.state("billing")
    try:
        got = await billing.inr(1.0) if billing is not None else 0.0
    except Exception as exc:  # noqa: BLE001 - a display figure never fails the board
        log.warning("rupee rate unreadable", extra={"error": type(exc).__name__})
        got = 0.0
    return float(got) if got and got > 0 else DEFAULT_RATE


def _vitals(ctx: HardeningContext, store: TokenLedgerStore | None, on: bool) -> Any:
    async def read(uid: str, now: datetime, tz: ZoneInfo) -> Sequence[OwnItem]:
        if store is None or not on:
            note = _OFF_NOTE if store is not None else NO_DOCS.capitalize() + "."
            return [own_item(VITALS_ID, "unknown", "switched off", note=note, kind="billing")]
        try:
            month = await store.month(uid, now)
        except Exception as exc:  # noqa: BLE001 - an unreadable ledger says so, quietly
            log.warning("token ledger unreadable", extra={"error": type(exc).__name__})
            return [own_item(VITALS_ID, "unknown", "can't be read now", note=_UNREAD_NOTE)]
        note = ai_parts_note(month, await _rate(ctx))
        return [own_item(VITALS_ID, "ok", _COUNTED, note=note, kind="billing")]

    return read


def _privacy(store: TokenLedgerStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        days = await store.days(uid)
        return Look(days, [days], deletable=False)

    return CallbackSource(
        Spec(
            PRIVACY_ID,
            SEC_ACTIVITY,
            "Where the AI money goes",
            "Per day: how many AI calls JARVIS made, their token counts, how many characters "
            "each part of the prompt had, the tools offered and the skills opened. Counts only: "
            "never a word of what was said.",
            "days",
            f"{LEDGER_DAYS} days",
            GOOGLE_ENC,
            note="Counts only, so there is nothing to export or delete; old days go by themselves.",
        ),
        look,
    )


def _ready(ctx: HardeningContext) -> str:
    s, notes = ctx.s, []
    if s.tool_offer == "all":
        notes.append(ALL_TOOLS)
    if ctx.docs is None:
        notes.append(NO_DOCS)
    elif not s.token_ledger_enabled:
        notes.append(LEDGER_OFF)
    return READY + (": " + "; ".join(notes) if notes else "")


def build(ctx: HardeningContext) -> HardeningPart:
    try:
        register = SkillRegister(load_catalogue())
    except CatalogueError:
        log.error("skill register unreadable: every tool is offered")
        raise
    s = ctx.s
    store = None
    if ctx.docs is not None:
        store = TokenLedgerStore(ctx.docs, prefix=s.firestore_prefix, tz=s.user_timezone)
    services: dict[str, Any] = {"register": register, "ledger_view": store}
    if s.tool_offer == "by_skill":
        services["offer"] = SkillOffer(register, sticky_s=s.tool_offer_sticky_s)
    if store is not None and s.token_ledger_enabled:
        services["ledger"] = store
    return HardeningPart(
        "skills",
        tools=(skills_open_tool(register, lambda: _late_registry(ctx)),),
        privacy=(_privacy(store),) if store is not None else (),
        vitals=(_vitals(ctx, store, s.token_ledger_enabled),),
        services=services,
        ready=_ready(ctx),
    )


__all__ = [
    "ALL_TOOLS",
    "LEDGER_OFF",
    "NO_DOCS",
    "PRIVACY_ID",
    "READY",
    "VITALS_ID",
    "CatalogueError",
    "build",
    "load_catalogue",
]
