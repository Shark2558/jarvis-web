# src/jarvis/brief/service.py
"""BriefService (Layer 3 orchestration): today / generate / tick.

generate:  settings → time zone (calendar, else cached, else config) → claim (transaction) →
           collect (fixed GETs) → audit (counts only) → optional AI lines → render → finish
           (only the claim holder) → prune old briefs, cache the zone. One failing step marks
           the brief failed with a friendly reason; it never raises vendor text.
tick:      for each owner: due? → generate(trigger=scheduled) → inbox delivery if switched on
           (at most once a day). A quiet tick reads two documents and calls nothing else.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.brief.collect import Collected, Collector
from jarvis.brief.deliver import InboxDelivery
from jarvis.brief.models import (
    AIBlock,
    AIView,
    BriefRecord,
    BriefSettings,
    BriefView,
    SettingsPatch,
    SettingsView,
    TickResult,
    TodayView,
    Trigger,
    parse_brief_time,
)
from jarvis.brief.render import render_text
from jarvis.brief.schedule import (
    STALE_CLAIM,
    claim_is_stale,
    due_at,
    in_delivery_window,
    is_due,
    local_date,
)
from jarvis.brief.store import BriefStore, ClaimOutcome
from jarvis.brief.summarize import Summarizer
from jarvis.core.guardrails import ActionRisk, ApprovalStore
from jarvis.integrations.google import GoogleConnector, can_insert
from jarvis.llm.base import Usage
from jarvis.llm.brains import BrainRegistry
from jarvis.llm.pricing import cost_usd
from jarvis.llm.router import ModelTier
from jarvis.logging import get_logger
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)

MAX_GENERATIONS = 6
USD_TO_INR = 88.0  # approximate; the note says "about"
TYPICAL_USAGE = Usage(input_tokens=8_000, output_tokens=600)  # one brief (plan, verified)

NOTE_NO_BRAIN = "No private AI brain is configured, so no AI summary (your data stays private)."
NOTE_NOTHING = "Nothing for the AI to summarise: calendar and inbox were not available."
NOTE_CAP = "Daily AI summary limit reached; the facts above are complete."
NOTE_FAILED = "The AI summary could not be written this time; the facts above are complete."
NOTE_EMPTY = "The AI had nothing to add today."
ERR_FAILED = "The brief could not be made just now. Refresh to try again."
ERR_KEPT = "Refreshing failed; this is the earlier brief from today."
ERR_STALE = "The brief did not finish. Refresh to try again."
MSG_LIMIT = "You've made {n} briefs today, Sir; that's the daily limit. Try again tomorrow."
MSG_SPEND = "Turning on the AI summary has a small cost; confirm it to switch it on."
MSG_INBOX = "Putting the brief in your Gmail inbox needs your confirmation."
MSG_SCOPE = "Reconnect Google (Integrations) to allow inbox delivery, then try again."


class BriefLimitReached(RuntimeError):
    """Today's generation budget is spent (→ 429)."""


class SettingsRejected(ValueError):
    """A settings change that needs a confirmation, a permission, or a valid time (→ 422)."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def _zone(name: str | None) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def apply_patch(
    cur: BriefSettings, p: SettingsPatch, *, insert_ok: bool, now: datetime
) -> BriefSettings:
    if p.time is not None:
        try:
            parse_brief_time(p.time)
        except ValueError as exc:
            raise SettingsRejected(str(exc)) from None
    if p.ai_summary and not cur.ai_summary and not p.confirm_spend:
        raise SettingsRejected(MSG_SPEND)
    if p.inbox_delivery and not cur.inbox_delivery:
        if not p.confirm_inbox:
            raise SettingsRejected(MSG_INBOX)
        if not insert_ok:
            raise SettingsRejected(MSG_SCOPE)
    changes = {
        k: v
        for k, v in p.model_dump(
            include={"enabled", "time", "ai_summary", "inbox_delivery"}
        ).items()
        if v is not None
    }
    return BriefSettings.model_validate({**cur.model_dump(), **changes, "updated_at": now})


def settings_view(s: BriefSettings) -> SettingsView:
    return SettingsView(
        enabled=s.enabled,
        time=s.time,
        ai_summary=s.ai_summary,
        inbox_delivery=s.inbox_delivery,
        updated_at=s.updated_at,
    )


def brief_view(rec: BriefRecord, now: datetime, max_generations: int) -> BriefView:
    status, error = rec.status, rec.error
    if claim_is_stale(rec, now):  # nobody will finish it: say so honestly
        status, error = ("ready", ERR_KEPT) if rec.data is not None else ("failed", ERR_STALE)
    inbox = rec.inbox
    if inbox.status == "sending" and inbox.at is not None and now - inbox.at > STALE_CLAIM:
        inbox = inbox.model_copy(update={"status": "unknown"})
    ai = rec.ai
    return BriefView(
        date=rec.date,
        tz=rec.tz,
        status=status,
        trigger=rec.trigger,
        created_at=rec.created_at,
        seen_at=rec.seen_at,
        data=rec.data,
        ai_note=rec.ai_note,
        text=rec.text,
        error=error,
        ai=AIView(lines=ai.lines, model=ai.model, cost_usd=ai.cost_usd) if ai else None,
        inbox=inbox,
        ai_calls_today=rec.ai_calls_today,
        generations_left=max(0, max_generations - rec.generations),
    )


class BriefService:
    def __init__(
        self,
        *,
        store: BriefStore,
        google: GoogleConnector | None,
        brains: BrainRegistry,
        approvals: ApprovalStore | None,
        audit: AuditTrail,
        owners: Sequence[str],
        default_tz: str,
        ai_daily_cap: int = 6,
        retention_days: int = 7,
        max_generations: int = MAX_GENERATIONS,
        clock: Callable[[], datetime] = utcnow,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._store = store
        self._google = google
        self._collector = Collector(google, approvals)
        self._summarizer = summarizer or Summarizer(brains)
        self._audit = audit
        self._delivery = InboxDelivery(google, store, audit) if google is not None else None
        self._owners = list(owners)
        self._default_tz = default_tz
        self._ai_cap = ai_daily_cap
        self._retention = retention_days
        self._max_gen = max_generations
        self._clock = clock

    # ---- views --------------------------------------------------------------------------------

    def _cached_zone(self, s: BriefSettings) -> ZoneInfo:
        return _zone(s.tz) or _zone(self._default_tz) or ZoneInfo("UTC")

    async def _link(self, uid: str) -> tuple[bool, bool]:
        """(Google usable, inbox insert allowed)."""
        if self._google is None:
            return False, False
        st = await self._google.status(uid)
        ok = bool(st["connected"]) and not st["needs_reconnect"]
        return ok, ok and can_insert(st["scopes"])

    def cost_note(self) -> str:
        spec = self._summarizer.brain
        if spec is None:
            return NOTE_NO_BRAIN
        month = cost_usd(spec.tiers[ModelTier.FAST], TYPICAL_USAGE) * 31
        if month <= 0:
            return f"No charge on this brain; at most {self._ai_cap} summaries a day."
        return (
            f"About ₹{month * USD_TO_INR:.0f} a month (≈ ${month:.3f}) for one short summary a "
            f"day on the fast model; at most {self._ai_cap} a day."
        )

    async def today(self, uid: str) -> TodayView:
        now = self._clock()
        s = await self._store.get_settings(uid)
        tz = self._cached_zone(s)
        day = local_date(now, tz)
        rec = await self._store.get_brief(uid, day.isoformat())
        connected, insert_ok = await self._link(uid)
        brief = brief_view(rec, now, self._max_gen) if rec is not None else None
        return TodayView(
            date=day.isoformat(),
            tz=tz.key,
            status=brief.status if brief else "none",
            brief=brief,
            settings=settings_view(s),
            due_at=due_at(s, day, tz) if s.enabled else None,
            google_connected=connected,
            ai_available=self._summarizer.available,
            inbox_available=insert_ok,
            ai_cost_note=self.cost_note(),
        )

    # ---- settings / seen -----------------------------------------------------------------------

    async def get_settings(self, uid: str) -> SettingsView:
        return settings_view(await self._store.get_settings(uid))

    async def update_settings(self, uid: str, patch: SettingsPatch) -> SettingsView:
        insert_ok = (await self._link(uid))[1] if patch.inbox_delivery else False
        now = self._clock()
        new = await self._store.update_settings(
            uid, lambda cur: apply_patch(cur, patch, insert_ok=insert_ok, now=now)
        )
        log.info(
            "brief settings changed",
            extra={"enabled": new.enabled, "ai": new.ai_summary, "inbox": new.inbox_delivery},
        )
        return settings_view(new)

    async def mark_seen(self, uid: str, day: str) -> datetime | None:
        rec = await self._store.mark_seen(uid, day, self._clock())
        return rec.seen_at if rec is not None else None

    # ---- generation ----------------------------------------------------------------------------

    async def generate(
        self, uid: str, *, trigger: Literal["manual", "open"], force: bool
    ) -> TodayView:
        s = await self._store.get_settings(uid)
        if trigger == "open" and not s.enabled:
            return await self.today(uid)
        _, outcome = await self._generate(uid, s, trigger=trigger, force=force)
        if outcome is ClaimOutcome.CAPPED:
            raise BriefLimitReached(MSG_LIMIT.format(n=self._max_gen))
        return await self.today(uid)

    async def _generate(
        self, uid: str, s: BriefSettings, *, trigger: Trigger, force: bool
    ) -> tuple[BriefRecord, ClaimOutcome]:
        tz = await self._collector.time_zone(uid, s.tz or self._default_tz)
        now = self._clock()
        day = local_date(now, tz).isoformat()
        claim = await self._store.claim(
            uid,
            day,
            tz=tz.key,
            trigger=trigger,
            force=force,
            now=now,
            max_generations=self._max_gen,
        )
        if claim.outcome is not ClaimOutcome.CLAIMED:
            return claim.record, claim.outcome
        rec = await self._build(claim.record, tz, s)
        if await self._store.finish(rec) and rec.error is None:
            await self._after_success(uid, tz, s, date.fromisoformat(day))
        log.info(
            "brief generated",
            extra={"trigger": trigger, "status": rec.status, "generation": rec.generations},
        )
        return rec, ClaimOutcome.CLAIMED

    async def _build(self, rec: BriefRecord, tz: ZoneInfo, s: BriefSettings) -> BriefRecord:
        try:
            got = await self._collector.collect(rec.user_id, tz, date.fromisoformat(rec.date))
            await self._audit_collect(rec, got)
            ai, note, calls = await self._ai(s, got, rec.ai_calls_today)
            return rec.model_copy(
                update={
                    "status": "ready",
                    "data": got.data,
                    "ai": ai,
                    "ai_note": note,
                    "error": None,
                    "text": render_text(got.data, ai, note),
                    "ai_calls_today": calls,
                    "created_at": self._clock(),
                }
            )
        except Exception as exc:  # noqa: BLE001 — a failed brief is reported, never raised
            log.error("brief generation failed", extra={"reason": type(exc).__name__})
            if rec.data is not None:  # a refresh failed: keep showing the earlier brief
                return rec.model_copy(update={"status": "ready", "error": ERR_KEPT})
            return rec.model_copy(
                update={"status": "failed", "error": ERR_FAILED, "created_at": self._clock()}
            )

    async def _ai(
        self, s: BriefSettings, got: Collected, calls: int
    ) -> tuple[AIBlock | None, str | None, int]:
        if not s.ai_summary:
            return None, None, calls
        if not self._summarizer.available:
            return None, NOTE_NO_BRAIN, calls
        st = got.data.sections_status
        if st.calendar != "ok" and st.inbox != "ok":
            return None, NOTE_NOTHING, calls
        if calls >= self._ai_cap:
            return None, NOTE_CAP, calls
        try:
            block = await self._summarizer.summarize(got.data, got.snippets)
        except Exception as exc:  # noqa: BLE001 — vendor text stays out of the brief
            log.warning("brief AI summary failed", extra={"reason": type(exc).__name__})
            return None, NOTE_FAILED, calls + 1
        if not block.lines:
            return None, NOTE_EMPTY, calls + 1
        return block, None, calls + 1

    async def _audit_collect(self, rec: BriefRecord, got: Collected) -> None:
        d, st = got.data, got.data.sections_status
        detail = (
            f"calendar={st.calendar} events={len(d.calendar.today)} inbox={st.inbox} "
            f"unread={d.inbox.total} approvals={d.jarvis.approvals_waiting}"
        )
        try:
            await self._audit.append(
                agent="morning_brief",
                tool="morning_brief.collect",
                risk=ActionRisk.READ_ONLY,
                outcome="executed",
                args={"date": rec.date, "trigger": rec.trigger},
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 — reads already happened; log loudly
            log.error(
                "AUDIT WRITE FAILED for brief collection", extra={"error": type(exc).__name__}
            )

    async def _after_success(self, uid: str, tz: ZoneInfo, s: BriefSettings, day: date) -> None:
        try:
            await self._store.prune(uid, keep_from=day - timedelta(days=self._retention - 1))
            if s.tz != tz.key:
                await self._store.update_settings(
                    uid, lambda c: c.model_copy(update={"tz": tz.key})
                )
        except Exception as exc:  # noqa: BLE001 — housekeeping only
            log.warning("brief housekeeping failed", extra={"reason": type(exc).__name__})

    # ---- scheduled ---------------------------------------------------------------------------

    async def tick(self) -> TickResult:
        generated = delivered = 0
        for uid in self._owners:
            try:
                g, d = await self._tick_one(uid)
            except Exception as exc:  # noqa: BLE001 — one owner never blocks another
                log.error("brief tick failed for an owner", extra={"reason": type(exc).__name__})
                continue
            generated, delivered = generated + g, delivered + d
        return TickResult(checked=len(self._owners), generated=generated, delivered=delivered)

    async def _tick_one(self, uid: str) -> tuple[int, int]:
        now = self._clock()
        s = await self._store.get_settings(uid)
        tz = self._cached_zone(s)
        if not s.enabled or not in_delivery_window(now, s, tz):
            return 0, 0
        rec = await self._store.get_brief(uid, local_date(now, tz).isoformat())
        made = 0
        if is_due(now=now, settings=s, tz=tz, existing=rec):
            rec, outcome = await self._generate(uid, s, trigger="scheduled", force=False)
            made = int(outcome is ClaimOutcome.CLAIMED)
        if not s.inbox_delivery or self._delivery is None or rec is None:
            return made, 0
        if rec.status != "ready" or rec.inbox.status != "off":
            return made, 0
        return made, int(await self._delivery.deliver(uid, rec, now=self._clock()))


__all__ = [
    "BriefLimitReached",
    "BriefService",
    "SettingsRejected",
    "apply_patch",
    "brief_view",
    "settings_view",
    "utcnow",
]
