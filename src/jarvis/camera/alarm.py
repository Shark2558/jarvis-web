# src/jarvis/camera/alarm.py
"""The burglar alarm's arm state (R3 D8; Layer 6 IoT, Security Advisor).

    {prefix}home_arm/{uid}   ArmRecord {armed, mode, rev, set_at, set_via, acked_rev,
                             pending_since, failed_rev, dropped_disarmed}   (no personal data)

The cloud decides, the laptop confirms:

- `arm` bumps `rev`, pushes the new arm state to the bridge and is "armed" to the owner only once
  the bridge's ack (`ack`) covers that rev (`ArmView.confirmed`). No ack in 5 minutes:
  `ArmPendingJob` sends one `home_arm_failed` alert per rev.
- `disarm` is the security downgrade. `Alarm.disarm` only runs with a `DisarmPass`, and only
  `DisarmGate` issues one: a passkey check made for exactly (this home, this arm rev), or - when no
  passkeys are in force - a Google sign-in under 5 minutes old. Nothing spoken, typed in chat,
  sent from Telegram or run as a tool can reach `disarm`: the `home_disarm` tool only points to the
  Home panel.
- Both ends filter: the cloud's record is what drops a detection that arrives while disarmed.
- Every change keeps the record readable or fails closed (`CameraUnavailable`); an unreadable
  record is never overwritten.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from jarvis.camera.models import ARM_FAIL_AFTER_S, ArmRecord, Mode, SetVia
from jarvis.camera.ports import AlarmRefused, CameraUnavailable, HomeDirectory
from jarvis.home.ports import ArmView, HomeCaller, HomeUnavailable
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.storage.docs import Docs, DocTx
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

STATE_PATH = "/bridge/v1/state"
UNREADABLE = "JARVIS couldn't read your alarm state just now. Try again in a minute."
NEEDS_CONSOLE = "Disarming has to be approved on screen with your passkey."
NEEDS_REAUTH = "Sign in with Google again to disarm."
NOT_LINKED = "Your home laptop isn't linked yet: link it in Integrations -> Home."
CHANGED = "The alarm changed while you were deciding. Check it and try again."
NO_PASS = "That disarm was not approved."
WAIT_STEP_S = 0.5

_SEAL = object()  # only this module can make a valid DisarmPass


@dataclass(frozen=True)
class DisarmPass:
    """Proof that a disarm was approved for exactly one owner and one arm rev. Valid only when the
    gate made it: a hand-built one is refused by `Alarm.disarm`."""

    uid: str
    rev: int
    how: str
    seal: object = None


class PermissionChecker:
    """The slice of `PermissionsService` the gate uses (documentation only)."""

    async def check_purpose(
        self, uid: str, purpose: str, target: str | None, proof: Any
    ) -> str | None:  # pragma: no cover - interface
        raise NotImplementedError


class Alarm:
    def __init__(
        self,
        docs: Docs,
        *,
        caller: HomeCaller | None = None,
        clock: Callable[[], float] = time.time,
        prefix: str = "jarvis_",
        has_zones: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self._has_zones = has_zones
        self._d = docs
        self._caller = caller
        self._clock = clock
        self._coll = f"{prefix}home_arm"

    def now(self) -> float:
        return self._clock()

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._coll}/{uid}"

    @staticmethod
    def _open(doc: dict[str, Any] | None) -> ArmRecord:
        return ArmRecord() if doc is None else ArmRecord.model_validate(doc)

    async def record(self, uid: str) -> ArmRecord:
        try:
            return self._open(await self._d.get(self._path(uid)))
        except ValueError:
            raise
        except (ValidationError, Exception) as exc:  # noqa: BLE001 - read nothing, say so
            log.warning("arm record unreadable", extra={"reason": type(exc).__name__})
            raise CameraUnavailable(UNREADABLE) from None

    async def _change(
        self, uid: str, fn: Callable[[ArmRecord], ArmRecord | None]
    ) -> tuple[ArmRecord, bool]:
        path = self._path(uid)

        async def tx(t: DocTx) -> tuple[ArmRecord, bool]:
            try:
                cur = self._open(await t.get(path))
            except Exception as exc:  # noqa: BLE001
                log.warning("arm record corrupt; refusing", extra={"reason": type(exc).__name__})
                raise CameraUnavailable(UNREADABLE) from None
            new = fn(cur)
            if new is None or new == cur:
                return cur, False
            t.set(path, new.model_dump(mode="json"))
            return new, True

        try:
            return await self._d.transaction(tx)
        except (CameraUnavailable, ValueError, AlarmRefused):
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("arm record not saved", extra={"reason": type(exc).__name__})
            raise CameraUnavailable(UNREADABLE) from None

    @staticmethod
    def _view(rec: ArmRecord) -> ArmView:
        return ArmView(
            armed=rec.armed,
            mode=rec.mode,
            rev=rec.rev,
            confirmed=rec.confirmed,
            pending_since=None if rec.confirmed else rec.pending_since,
        )

    async def protecting(self, uid: str) -> bool:
        """Can an alert fire at all? False when no camera has an alarm zone: armed, but nothing
        is watched (the owner is told so)."""
        return True if self._has_zones is None else await self._has_zones(uid)

    async def view(self, uid: str) -> ArmView:
        return self._view(await self.record(uid))

    # ---- arm ---------------------------------------------------------------------------------

    async def arm(self, uid: str, mode: Mode, via: SetVia) -> ArmView:
        now = self._clock()

        def change(cur: ArmRecord) -> ArmRecord | None:
            if cur.armed and cur.mode == mode:
                return None
            return cur.model_copy(
                update={
                    "armed": True,
                    "mode": mode,
                    "rev": cur.rev + 1,
                    "set_at": now,
                    "set_via": via,
                    "pending_since": now,
                }
            )

        rec, _ = await self._change(uid, change)
        await self.push(uid, rec)
        return self._view(rec)

    # ---- disarm (only with a pass) -----------------------------------------------------------

    async def disarm(self, uid: str, approved: DisarmPass, *, via: SetVia) -> ArmView:
        if not isinstance(approved, DisarmPass) or approved.seal is not _SEAL:
            raise AlarmRefused("no_pass", NO_PASS)
        if approved.uid != uid:
            raise AlarmRefused("no_pass", NO_PASS)
        now = self._clock()

        def change(cur: ArmRecord) -> ArmRecord | None:
            if cur.rev != approved.rev:
                raise AlarmRefused("changed", CHANGED)
            if not cur.armed:
                return None
            return cur.model_copy(
                update={
                    "armed": False,
                    "rev": cur.rev + 1,
                    "set_at": now,
                    "set_via": via,
                    "pending_since": now,
                }
            )

        rec, _ = await self._change(uid, change)
        await self.push(uid, rec)
        return self._view(rec)

    # ---- the bridge --------------------------------------------------------------------------

    async def push(self, uid: str, rec: ArmRecord | None = None) -> bool:
        """Tell the bridge the arm state now. False when the laptop didn't answer (the next
        heartbeat reply carries it)."""
        if self._caller is None:
            return False
        try:
            r = rec or await self.record(uid)
            body = {"arm": {"armed": r.armed, "mode": r.mode, "rev": r.rev}}
            await self._caller.call(uid, "POST", STATE_PATH, body)
        except (HomeUnavailable, CameraUnavailable):
            return False
        except Exception as exc:  # noqa: BLE001
            log.warning("arm push failed", extra={"reason": type(exc).__name__})
            return False
        return True

    async def ack(self, uid: str, rev: int) -> bool:
        """The bridge applied arm `rev`. Only an ack that covers the current rev confirms."""

        def change(cur: ArmRecord) -> ArmRecord | None:
            if rev <= cur.acked_rev or rev > cur.rev:
                return None
            done = rev >= cur.rev
            return cur.model_copy(
                update={"acked_rev": rev, "pending_since": None if done else cur.pending_since}
            )

        rec, _ = await self._change(uid, change)
        return rec.confirmed and rec.acked_rev >= rev

    async def wait_confirmed(
        self,
        uid: str,
        timeout_s: float,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> ArmView:
        """The arm state, waiting up to `timeout_s` for the bridge's ack."""
        view = await self.view(uid)
        for _ in range(int(timeout_s / WAIT_STEP_S)):
            if view.confirmed:
                break
            await sleep(WAIT_STEP_S)
            view = await self.view(uid)
        return view

    async def count_dropped(self, uid: str) -> int:
        """A detection reached the cloud while disarmed: dropped, counted (D8)."""
        rec, _ = await self._change(
            uid, lambda cur: cur.model_copy(update={"dropped_disarmed": cur.dropped_disarmed + 1})
        )
        return rec.dropped_disarmed

    async def mark_failed(self, uid: str, rev: int) -> bool:
        """Remember the "couldn't arm" alert for `rev`; False when it was already sent."""
        sent = False

        def change(cur: ArmRecord) -> ArmRecord | None:
            nonlocal sent
            if cur.failed_rev >= rev:
                return None
            sent = True
            return cur.model_copy(update={"failed_rev": rev})

        await self._change(uid, change)
        return sent

    async def wipe(self, uid: str) -> None:
        """Forget the arm state, but never the counter: a tombstone keeps `rev` going up, so a
        bridge that remembers rev 7 still follows the next arm (a reset to 1 would be ignored)."""
        now = self._clock()

        def change(cur: ArmRecord) -> ArmRecord | None:
            rev = cur.rev + 1
            return ArmRecord(rev=rev, acked_rev=rev, set_at=now, failed_rev=rev)

        await self._change(uid, change)


class DisarmGate:
    """The only door to `Alarm.disarm`. `permissions` answers `check_purpose` (None: not wired, so
    the Google sign-in rule applies); `homes` names the owner's home."""

    def __init__(
        self,
        alarm: Alarm,
        homes: HomeDirectory,
        permissions: PermissionChecker | None = None,
    ) -> None:
        self._alarm = alarm
        self.homes = homes
        self.permissions = permissions

    def _issue(self, uid: str, rev: int, how: str) -> DisarmPass:
        return DisarmPass(uid=uid, rev=rev, how=how, seal=_SEAL)

    async def panel_pass(
        self, uid: str, proof: Any, *, fresh_left_s: int | None
    ) -> DisarmPass | None:
        """The Disarm button: None when the home is already disarmed (nothing to approve), else a
        pass for this home and rev. Raises the permissions errors (passkey) or `AlarmRefused`
        (`console_only`, `reauth_required`, `not_linked`)."""
        rec = await self._alarm.record(uid)
        if not rec.armed:
            return None
        home = await self.homes.home_id(uid)
        if home is None:
            raise AlarmRefused("not_linked", NOT_LINKED)
        if fresh_left_s is None:
            raise AlarmRefused("console_only", NEEDS_CONSOLE)
        how: str | None = None
        if self.permissions is not None:
            how = await self.permissions.check_purpose(
                uid, "home_disarm", f"{home}:{rec.rev}", proof
            )
        if how is None:
            if fresh_left_s <= 0:
                raise AlarmRefused("reauth_required", NEEDS_REAUTH)
            how = "re-sign-in"
        return self._issue(uid, rec.rev, how)


class ArmPendingJob:
    """Watchdog step (D9): an arm the laptop never acked for 5 minutes -> one `home_arm_failed`."""

    name = "home_arm_pending"
    budget_s = 20.0

    def __init__(self, alarm: Alarm, notifier: Notifier, *, tz: str) -> None:
        self._alarm = alarm
        self._notifier = notifier
        self._tz = tz

    async def _one(self, uid: str) -> int:
        rec = await self._alarm.record(uid)
        since = rec.pending_since
        if not rec.armed or rec.confirmed or since is None:
            return 0
        if self._alarm.now() - since < ARM_FAIL_AFTER_S:
            return 0
        if not await self._alarm.mark_failed(uid, rec.rev):
            return 0
        when = datetime.fromtimestamp(since, UTC).astimezone(ZoneInfo(self._tz)).strftime("%H:%M")
        text = f"JARVIS couldn't arm your home at {when}: the laptop didn't answer."
        await self._notifier.notify(uid, Signal(source="home", kind="home_arm_failed"), text)
        return 1

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        alerted = failed = 0
        for uid in owners:
            try:
                alerted += await self._one(uid)
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning("arm check failed", extra={"reason": type(exc).__name__})
                failed += 1
        return {"alerted": alerted, "failed": failed}


__all__ = [
    "CHANGED",
    "NEEDS_CONSOLE",
    "NEEDS_REAUTH",
    "NOT_LINKED",
    "Alarm",
    "ArmPendingJob",
    "DisarmGate",
    "DisarmPass",
]
