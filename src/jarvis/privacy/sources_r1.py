# src/jarvis/privacy/sources_r1.py
"""The R1 categories of the privacy dashboard (R2 D14): Telegram, Activity, the laptop brain,
the Groceries list, family calendars and parcels. Public methods of each store only.

Nothing secret is ever shown: the Telegram bot token is not stored per owner at all (it lives in
the environment); the laptop brain's address and key are stored encrypted and are not read into a
view or an export - only whether one is set.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from jarvis.activity.store import ActivityStore, day_key
from jarvis.family.store import FamilyStore
from jarvis.groceries.store import GroceryStore
from jarvis.offline.store import LocalBrainStore
from jarvis.privacy.sources import (
    OURS_ENC,
    SEC_ACTIVITY,
    SEC_CONNECT,
    CallbackSource,
    Look,
    Spec,
)
from jarvis.telegram.store import TelegramStore

ACTIVITY_DAYS = 8  # kept 7 days; one more for the day boundary
SWEEP_ROUNDS = 40
FAR_FUTURE_DAY = "99991231"


def telegram_source(store: TelegramStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        link = await store.get(uid)
        return Look(
            0 if link is None else 1,
            [] if link is None else [link.paired_at, link.rev, link.allow_private_reads],
            deletable=link is not None,
        )

    async def export(uid: str) -> dict[str, Any]:
        link = await store.get(uid)
        if link is None:
            return {"paired": False}
        return {
            "paired": True,
            "paired_at": link.paired_at,
            "allow_private_reads": link.allow_private_reads,
            "allow_personal_reads": link.allow_personal_reads,  # R2 D12
            "alerts": link.alerts.model_dump(mode="json"),
        }

    async def delete(uid: str) -> int:
        return 1 if await store.unpair(uid) else 0

    return CallbackSource(
        Spec(
            "telegram",
            SEC_CONNECT,
            "Telegram",
            "The pairing between your Telegram account and JARVIS, and its alert choices.",
            "pairing",
            "Until you unpair.",
            "Firestore",
            delete="simple",
            recoverable=True,
            note="Unpairing stops Telegram messages. You can pair again.",
        ),
        look,
        export,
        delete,
    )


def activity_source(
    store: ActivityStore, today: Callable[[], date] = lambda: datetime.now(UTC).date()
) -> CallbackSource:
    async def rows(uid: str) -> list[Any]:
        out: list[Any] = []
        for i in range(ACTIVITY_DAYS):
            out += await store.day(uid, day_key(today() - timedelta(days=i)))
        return out

    async def look(uid: str) -> Look:
        r = await rows(uid)
        return Look(len(r), [x.id for x in r], deletable=bool(r))

    async def export(uid: str) -> dict[str, Any]:
        return {
            "rows": [
                {
                    "at": x.at.isoformat(),
                    "tool": x.tool,
                    "kind": x.kind,
                    "outcome": x.outcome,
                    "words": x.words,
                    "channel": x.channel,
                }
                for x in await rows(uid)
            ]
        }

    async def delete(uid: str) -> int:
        gone = 0
        for _ in range(SWEEP_ROUNDS):  # a sweep removes a bounded batch per day per call
            n = await store.sweep([uid], keep_from=FAR_FUTURE_DAY)
            gone += n
            if n == 0:
                break
        return gone

    return CallbackSource(
        Spec(
            "activity",
            SEC_ACTIVITY,
            "Activity",
            "A plain-words list of what JARVIS did for you lately.",
            "rows",
            "7 days.",
            "Firestore",
            delete="passkey",
        ),
        look,
        export,
        delete,
    )


def offline_source(store: LocalBrainStore) -> CallbackSource:
    """The laptop brain is one per server: `uid` is not part of its path."""

    async def look(uid: str) -> Look:
        cfg = await store.get()
        return Look(
            0 if cfg is None else 1,
            [] if cfg is None else [cfg.enabled, cfg.model],
            deletable=cfg is not None,
        )

    async def delete(uid: str) -> int:
        had = await store.get() is not None
        await store.delete()
        return 1 if had else 0

    return CallbackSource(
        Spec(
            "offline",
            SEC_CONNECT,
            "Laptop brain",
            "The address and key of the AI that runs on your own laptop.",
            "setups",
            "Until you remove it.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="simple",
            recoverable=True,
            note="The address and key are not shown or downloaded.",
        ),
        look,
        None,
        delete,
    )


def groceries_source(store: GroceryStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        lid = await store.list_id(uid)
        return Look(0 if lid is None else 1, [lid], deletable=lid is not None)

    async def export(uid: str) -> dict[str, Any]:
        return {"list_id": await store.list_id(uid), "title": "Groceries"}

    async def delete(uid: str) -> int:
        had = await store.list_id(uid) is not None
        await store.forget(uid)
        return 1 if had else 0

    return CallbackSource(
        Spec(
            "groceries",
            SEC_CONNECT,
            "Groceries list",
            "Which Google Tasks list is your Groceries list.",
            "lists",
            "Until you remove it.",
            "Firestore",
            delete="simple",
            recoverable=True,
            note="The list itself stays in Google Tasks.",
        ),
        look,
        export,
        delete,
    )


def family_source(store: FamilyStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        m = await store.members(uid)
        return Look(len(m), [x.id for x in m], deletable=bool(m))

    async def export(uid: str) -> dict[str, Any]:
        return {
            "members": [
                {
                    "name": m.name,
                    "calendar": m.calendar_id,
                    "access": m.access,
                    "added_at": m.added_at,
                }
                for m in await store.members(uid)
            ]
        }

    async def delete(uid: str) -> int:
        gone = 0
        for m in await store.members(uid):
            if await store.remove(uid, m.id):
                gone += 1
        return gone

    return CallbackSource(
        Spec(
            "family",
            SEC_CONNECT,
            "Family calendars",
            "The family calendars you added, and the names you gave them.",
            "people",
            "Until you remove them.",
            "Firestore",
            delete="simple",
            recoverable=True,
            note="Their calendars stay with them.",
        ),
        look,
        export,
        delete,
    )


def packages_source() -> CallbackSource:
    async def look(uid: str) -> Look:
        return Look(0)

    return CallbackSource(
        Spec(
            "packages",
            SEC_CONNECT,
            "Parcels",
            "Parcel tracking found in your Gmail.",
            "parcels",
            "Not kept.",
            "Not stored",
            note="Nothing is stored. Parcels are looked up from your Gmail when you ask.",
        ),
        look,
    )


@dataclass(frozen=True)
class R1Parts:
    telegram: TelegramStore | None = None
    activity: ActivityStore | None = None
    offline: LocalBrainStore | None = None
    groceries: GroceryStore | None = None
    family: FamilyStore | None = None
    today: Callable[[], date] = lambda: datetime.now(UTC).date()  # noqa: E731


def r1_sources(p: R1Parts) -> list[CallbackSource]:
    """The R1 categories in panel order; a part that is None (the feature is off) is left out.
    Parcels are always listed: they say plainly that nothing is stored."""
    out: list[CallbackSource | None] = [
        telegram_source(p.telegram) if p.telegram else None,
        activity_source(p.activity, p.today) if p.activity else None,
        offline_source(p.offline) if p.offline else None,
        groceries_source(p.groceries) if p.groceries else None,
        family_source(p.family) if p.family else None,
        packages_source(),
    ]
    return [s for s in out if s is not None]


__all__ = [
    "R1Parts",
    "activity_source",
    "family_source",
    "groceries_source",
    "offline_source",
    "packages_source",
    "r1_sources",
    "telegram_source",
]
