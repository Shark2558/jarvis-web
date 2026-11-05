# tests/notify_fakes.py -- the R3 D world: policy + storm + store + Telegram fake + push fake.
# Never imported from conftest.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from telegram_fakes import UID, World, build_world
from webpush_fakes import Browser, PushWorld

from jarvis.notify.service import NotifyService
from jarvis.notify.store import NotifyStore
from jarvis.notify.telegram_out import TelegramHomeAlerts

# 12:00 local (Asia/Kolkata) on 2027-01-15; MIDNIGHT is 00:30 local the same night
NOON = datetime(2027, 1, 15, 6, 30, tzinfo=UTC)
MIDNIGHT = datetime(2027, 1, 14, 19, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = NOON) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


@dataclass
class NotifyWorld:
    tg: World
    push: PushWorld
    store: NotifyStore
    alerts: TelegramHomeAlerts
    service: NotifyService
    clock: Clock
    photos: list[tuple[int, bytes, str]] = field(default_factory=list)

    @property
    def docs(self) -> Any:
        return self.tg.docs


async def build(
    now: datetime = NOON, *, paired: bool = True, with_push: bool = True
) -> NotifyWorld:
    tg = build_world()
    if paired:
        await tg.pair()
    push = PushWorld()
    clock = Clock(now)
    store = NotifyStore(tg.docs, push.ring)
    photos: list[tuple[int, bytes, str]] = []

    async def photo_sender(chat: int, data: bytes, caption: str) -> None:
        photos.append((chat, data, caption))

    alerts = TelegramHomeAlerts(
        tg.bot.client(), tg.store, store, tg.audit, photo_sender=photo_sender, now=clock
    )
    service = NotifyService(
        store,
        tg.audit,
        telegram=alerts,
        push=push.service if with_push else None,
        now=clock,
    )
    if with_push:
        await push.service.subscribe(UID, **Browser().sub())
    return NotifyWorld(tg, push, store, alerts, service, clock, photos)
