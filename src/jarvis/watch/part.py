# src/jarvis/watch/part.py
"""R7 Part D (Watch, sleep and SOS): the part's one join with the app (`jarvis.mobile.ports`).

`build(ctx)` hands back `MobilePart("body")` with:
- tools: `sleep_last_night`, `sleep_week`, `watch_today`, `sleep_note` (`jarvis.watch.tools`) and
  `sos_status` (`jarvis.sos.tools`), the brain's only SOS tool (a read). Registered
  whenever there is a document store (with none the part is `off: no document store` and has no
  tools); each says plainly when it is off (no token key, switched off). No tool sends an SOS (D19);
- services: `door` {health, sos} for Part C's door; `sos_hook` (the code behind I0's Telegram hook,
  `ContactHook`); `phrases` (the No-AI router); `brief` (`SleepBrief`: no Helpers line ever, the
  pinned `sleep()` for the console's brief); and for its own routes and other parts: `watch`
  (`WatchService`), `sos` (`SosService`) and `sos_contacts` (`SosService.sms_view`:
  `async (uid) -> {label, contacts: [{label, phone}]}` for the phone's `hello` reply, Part C);
- clock job `watch_stale`, daily job `body_sweep`, privacy rows `watch_days` and `sos`.
Everything it needs is read LATE from the app (`ctx.state`): the Telegram client, the clock
(`helpers_now`, set by R11's wiring) and the notifier.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from jarvis.keyring import Keyring
from jarvis.mobile.ports import MobileContext, MobilePart
from jarvis.sos.contacts_hook import ContactHook
from jarvis.sos.service import SosService
from jarvis.sos.store import SosStore
from jarvis.sos.tools import sos_tools
from jarvis.telegram.client import TelegramClient
from jarvis.watch.brief import SleepBrief
from jarvis.watch.door import health_handler, sos_handler
from jarvis.watch.jobs import BodySweep, WatchStale
from jarvis.watch.phrases import watch_phrases
from jarvis.watch.privacy import sos_privacy, watch_privacy
from jarvis.watch.service import WatchService
from jarvis.watch.store import WatchStore
from jarvis.watch.tools import watch_tools

READY = "ready"
NO_KEY = "off: no token key"
NO_STORE = "off: no document store"


def _clock(ctx: MobileContext) -> Callable[[], datetime]:
    def now() -> datetime:
        late = ctx.state("helpers_now")
        at = late() if callable(late) else datetime.now(UTC)
        return at if isinstance(at, datetime) else datetime.now(UTC)

    return now


def _telegram(ctx: MobileContext) -> Callable[[], TelegramClient | None]:
    def client() -> TelegramClient | None:
        found: Any = getattr(ctx.state("telegram"), "client", None)
        return found if isinstance(found, TelegramClient) else None

    return client


def _owners(ctx: MobileContext) -> tuple[str, ...]:
    from jarvis.api.identity import LEGACY_USER_ID, user_id_for_email

    found = tuple(dict.fromkeys(user_id_for_email(e) for e in ctx.s.owner_emails))
    return found or (LEGACY_USER_ID,)


def build(ctx: MobileContext) -> MobilePart:
    if ctx.docs is None:
        return MobilePart("body", ready=NO_STORE)
    s, now = ctx.s, _clock(ctx)
    ring = Keyring.from_settings(s)
    watch = WatchService(WatchStore(ctx.docs, ring, prefix=ctx.prefix, now=now), s, now=now)
    sos_store = SosStore(ctx.docs, ring, prefix=ctx.prefix, now=now)
    sos = SosService(
        sos_store,
        s,
        telegram=_telegram(ctx),
        notifier=ctx.notifier,
        audit=ctx.audit,
        now=now,
        owners=_owners(ctx),
    )
    return MobilePart(
        "body",
        tools=(*watch_tools(watch), *sos_tools(sos)),
        clock_jobs=(WatchStale(watch, notifier=ctx.notifier, now=now),),
        daily_jobs=(BodySweep(watch, sos_store, keep_days=s.watch_keep_days, now=now),),
        privacy=(watch_privacy(watch.store), sos_privacy(sos_store)),
        services={
            "door": {"health": health_handler(watch), "sos": sos_handler(sos)},
            "sos_hook": ContactHook(sos),
            "phrases": (watch_phrases,),
            "brief": SleepBrief(watch),
            "watch": watch,
            "sos": sos,
            "sos_contacts": sos.sms_view,
        },
        ready=READY if ring is not None else NO_KEY,
    )


__all__ = ["NO_KEY", "NO_STORE", "READY", "build"]
