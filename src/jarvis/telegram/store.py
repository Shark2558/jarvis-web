# src/jarvis/telegram/store.py
"""Telegram state on the Docs port (R1 data model; Layer 7). Equality + one order_by only.

{prefix}telegram/{uid}                  TelegramLink
{prefix}telegram_users/{tg_user_id}     {uid, paired_at}     reverse look-up on every update
{prefix}telegram_pairing/{uid}          {code_hash, expires_at, tries}   one pending code
{prefix}telegram_updates/{update_id}    {at}                 create-only claim, swept after 48 h
{prefix}telegram_alerts/{uid}_{YYYYMMDD} {count, hours:{HH:n}}  alert rate counter (fail closed)
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, DocExists, Docs, DocTx, Query, Set
from jarvis.telegram.models import AlertToggles, TelegramLink
from jarvis.telegram.pairing import CODE_TTL_S, MAX_TRIES, hash_code, new_code, normalise

log = get_logger(__name__)
UPDATE_KEEP = timedelta(hours=48)
COUNTER_KEEP_DAYS = 3


def _utc() -> datetime:
    return datetime.now(UTC)


class TelegramStore:
    def __init__(
        self, docs: Docs, *, prefix: str = "", clock: Callable[[], datetime] = _utc
    ) -> None:
        self._d = docs
        self._p = prefix
        self._now = clock

    def _path(self, coll: str, key: str | int) -> str:
        return f"{self._p}{coll}/{key}"

    # ---- the link --------------------------------------------------------------------------

    async def get(self, uid: str) -> TelegramLink | None:
        raw = await self._d.get(self._path("telegram", uid))
        if raw is None:
            return None
        try:
            return TelegramLink.model_validate(raw)
        except ValidationError:
            log.error("telegram link unreadable; treated as unpaired")
            return None

    async def uid_for(self, tg_user_id: int) -> str | None:
        raw = await self._d.get(self._path("telegram_users", tg_user_id))
        uid = raw.get("uid") if raw else None
        return uid if isinstance(uid, str) else None

    async def _update(
        self, uid: str, change: Callable[[TelegramLink], TelegramLink]
    ) -> TelegramLink | None:
        path = self._path("telegram", uid)

        async def fn(tx: DocTx) -> TelegramLink | None:
            raw = await tx.get(path)
            if raw is None:
                return None
            cur = TelegramLink.model_validate(raw)
            new = change(cur).model_copy(update={"rev": cur.rev + 1})
            tx.set(path, new.model_dump(mode="json"))
            return new

        return await self._d.transaction(fn)

    async def set_settings(
        self,
        uid: str,
        *,
        allow_private_reads: bool | None = None,
        alerts: dict[str, bool] | None = None,
    ) -> TelegramLink | None:
        def change(cur: TelegramLink) -> TelegramLink:
            out = cur
            if allow_private_reads is not None:
                out = out.model_copy(update={"allow_private_reads": allow_private_reads})
            if alerts:
                toggles = out.alerts.model_copy(update=alerts)
                out = out.model_copy(update={"alerts": AlertToggles.model_validate(toggles)})
            return out

        return await self._update(uid, change)

    async def set_session(self, uid: str, session_id: str | None) -> None:
        await self._update(uid, lambda cur: cur.model_copy(update={"session_id": session_id}))

    # ---- pairing ---------------------------------------------------------------------------

    async def start_pairing(self, uid: str) -> tuple[str, int]:
        code = new_code()
        expires = self._now() + timedelta(seconds=CODE_TTL_S)
        await self._d.write(
            [
                Set(
                    self._path("telegram_pairing", uid),
                    {"code_hash": hash_code(code), "expires_at": expires.isoformat(), "tries": 0},
                )
            ]
        )
        return code, CODE_TTL_S

    def _live(self, doc: dict[str, Any]) -> bool:
        try:
            alive = datetime.fromisoformat(str(doc["expires_at"])) > self._now()
            return alive and int(doc.get("tries", 0)) < MAX_TRIES
        except (KeyError, ValueError, TypeError):
            return False

    async def finish_pairing(self, code: str, *, tg_user_id: int, chat_id: int) -> str | None:
        """The owner id the code belongs to (now bound to this Telegram account), else None."""
        want = hash_code(code) if normalise(code) else None
        rows = await self._d.query(Query(self._p + "telegram_pairing"))
        live = [(uid, d) for uid, d in rows if self._live(d)]
        if want is not None:
            for uid, d in live:
                if hmac.compare_digest(str(d.get("code_hash", "")), want):
                    return await self._bind(uid, want, tg_user_id, chat_id)
        for uid, _ in live:  # a wrong try counts against every pending code
            await self._count_try(uid)
        return None

    async def _count_try(self, uid: str) -> None:
        path = self._path("telegram_pairing", uid)

        async def fn(tx: DocTx) -> None:
            d = await tx.get(path)
            if d is not None:
                tx.set(path, {**d, "tries": int(d.get("tries", 0)) + 1})

        await self._d.transaction(fn)

    async def _bind(self, uid: str, want: str, tg_user_id: int, chat_id: int) -> str | None:
        pairing = self._path("telegram_pairing", uid)
        link_path = self._path("telegram", uid)
        user_path = self._path("telegram_users", tg_user_id)
        now = self._now().isoformat()

        async def fn(tx: DocTx) -> str | None:
            pend = await tx.get(pairing)
            owner = await tx.get(user_path)
            old = await tx.get(link_path)
            if pend is None or pend.get("code_hash") != want or not self._live(pend):
                return None
            if owner is not None and owner.get("uid") != uid:
                return None  # that Telegram account already belongs to someone else
            tx.delete(pairing)  # single use
            if old is not None and old.get("tg_user_id") != tg_user_id:
                tx.delete(self._path("telegram_users", int(old["tg_user_id"])))
            link = TelegramLink(tg_user_id=tg_user_id, chat_id=chat_id, paired_at=now)
            tx.set(link_path, link.model_dump(mode="json"))
            tx.set(user_path, {"uid": uid, "paired_at": now})
            return uid

        return await self._d.transaction(fn)

    async def unpair(self, uid: str) -> bool:
        link = await self.get(uid)
        ops: list[Delete] = [Delete(self._path("telegram_pairing", uid))]
        if link is not None:
            ops += [
                Delete(self._path("telegram_users", link.tg_user_id)),
                Delete(self._path("telegram", uid)),
            ]
        await self._d.write(ops)
        return link is not None

    # ---- updates, alert counters, sweep ------------------------------------------------------

    async def claim_update(self, update_id: int) -> bool:
        """Create-only: True the first time an update id is seen, False for a retry."""
        from jarvis.storage.docs import Create

        try:
            await self._d.write(
                [Create(self._path("telegram_updates", update_id), {"at": self._now().isoformat()})]
            )
        except DocExists:
            return False
        return True

    async def count_alert(self, uid: str, *, per_hour: int, per_day: int) -> bool:
        """Take one alert from today's allowance; False when spent. Errors propagate (the caller
        fails closed)."""
        now = self._now()
        path = self._path("telegram_alerts", f"{uid}_{now:%Y%m%d}")
        hour = f"{now:%H}"

        async def fn(tx: DocTx) -> bool:
            d = await tx.get(path) or {"count": 0, "hours": {}}
            hours = dict(d.get("hours") or {})
            if int(d.get("count", 0)) >= per_day or int(hours.get(hour, 0)) >= per_hour:
                return False
            hours[hour] = int(hours.get(hour, 0)) + 1
            tx.set(path, {"count": int(d.get("count", 0)) + 1, "hours": hours})
            return True

        return await self._d.transaction(fn)

    async def sweep(self) -> int:
        """Delete update claims older than 48 hours and alert counters older than a few days."""
        now = self._now()
        ops: list[Delete] = []
        for uid, d in await self._d.query(Query(self._p + "telegram_updates")):
            try:
                if now - datetime.fromisoformat(str(d["at"])) > UPDATE_KEEP:
                    ops.append(Delete(self._path("telegram_updates", uid)))
            except (KeyError, ValueError):
                ops.append(Delete(self._path("telegram_updates", uid)))
        swept = len(ops)
        cutoff = f"{now - timedelta(days=COUNTER_KEEP_DAYS):%Y%m%d}"
        for key, _ in await self._d.query(Query(self._p + "telegram_alerts")):
            if key.rsplit("_", 1)[-1] < cutoff:
                ops.append(Delete(self._path("telegram_alerts", key)))
        if ops:
            await self._d.write(ops)
        return swept


__all__ = ["TelegramStore"]
