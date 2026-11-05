# src/jarvis/api/home_wiring.py
"""R3 I1: the home bridge, camera alerts, faces and the one alert policy on the app (plan
docs/plans/r3-home-camera.md "Workstreams -> I1"). Kept out of `api/app.py` so that file stays a
short list of named steps, as R2's `api/personal.py` does.

- `wire_notify` (in the core, right after Telegram, BEFORE anything takes `app.state.alerts`): D's
  `NotifyService` (policy, storm control, Telegram with the urgent bucket, Web Push), and
  `app.state.alerts = PolicyAlerts(service)`, so R1's and R2's alerts get quiet hours too. Without
  the token key the alert settings can't be sealed: alerts stay R1's Telegram ones.
- `wire_home` (after R2's personal data, before the gateway): A's link, devices, webhook and
  watchdog; B's camera (alarm, feed, history, packages); C's faces registry and directory. One
  `HomeWebhook` dispatches every kind to the handlers that take it (A: heartbeat, hazard; B:
  detection, face_seen, package, heartbeat, `arm:` acks; C: face_deleted acks, heartbeat); the
  heartbeat answer merges A's devices, B's arm and settings and C's faces. Faces off -> B's
  directory names nobody (`NoFaces`); a face lookup that fails is "not recognised" (B's
  `safe_resolve`), so recognition never suppresses an armed alert. `home_unlink_guard`: unlinking
  while armed needs the Disarm button's proof (integrated review S4).
- `notify_tick_jobs`: the alert policy's jobs run once, in the watchdog when Home is wired, else in
  the scheduler tick (review H3).
- `home_privacy_sources`: home, home_feed, camera_home, notify, webpush, then faces (LAST, where
  R2's placeholder was).
Everything is OFF (None, the routes say why) without the server's token key or with
`JARVIS_HOME_ENABLED=false`, and when a part fails to build (review M9: logged, never fatal).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI

from jarvis.alerts import AlertSink, NoAlerts
from jarvis.camera.guard import ArmedUnlinkGuard
from jarvis.camera.privacy import CameraHomePrivacy, HomeFeedPrivacy
from jarvis.camera.service import CameraServices, build_camera
from jarvis.config import Settings
from jarvis.faces.directory import Directory
from jarvis.faces.ports import FaceDirectory, NoFaces
from jarvis.faces.privacy import FacesPrivacy
from jarvis.faces.service import FacesService
from jarvis.faces.store import FacesStore
from jarvis.home.client import HomeClient
from jarvis.home.devices import DeviceService
from jarvis.home.heartbeat import HazardHandler, HeartbeatHandler
from jarvis.home.link import LinkService
from jarvis.home.parts import HomeParts
from jarvis.home.ports import HomeEventHandler, StateSource
from jarvis.home.privacy import HomePrivacy
from jarvis.home.store import HomeStore
from jarvis.home.tools import HomeStatusReader
from jarvis.home.watchdog import OfflineJob, Watchdog
from jarvis.home.webhook import HomeWebhook
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.notify.ports import DirectNotifier, Notifier
from jarvis.notify.privacy import notify_source, webpush_source
from jarvis.notify.service import NotifyService
from jarvis.notify.sink import PolicyAlerts
from jarvis.notify.store import NotifyStore
from jarvis.notify.telegram_out import TelegramHomeAlerts
from jarvis.privacy.ports import PrivacySource
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditTrail
from jarvis.webpush.service import PushService
from jarvis.webpush.store import PushStore
from jarvis.webpush.vapid import VapidKey

log = get_logger(__name__)

NO_KEY_NOTE = (
    "No encryption key on this server: Home, the camera, Faces and alert settings are OFF "
    "(never stored in clear)"
)
VAPID_BYTES = 48
HOME_STATE = (
    "home_store",
    "home_client",
    "home_link",
    "home_webhook",
    "home_watchdog",
    "home_devices",
    "home_status",
    "home_parts",
    "camera",
    "faces",
    "faces_laptop",
    "home_unlink_guard",
)
# The watchdog's own steps and the brief tick's sweeps: an added job may take none of these
RESERVED_HOME_JOBS = frozenset({"home_offline", "home_claims_sweep", "home_link_sweep"})


# ---- the one alert policy (D) ------------------------------------------------------------------


def _vapid_subject(s: Settings) -> str | None:
    if s.public_base_url:
        return str(s.public_base_url).rstrip("/")
    return f"mailto:{s.owner_emails[0]}" if s.owner_emails else None


def build_push(
    s: Settings, docs: Docs, ring: Keyring, audit: AuditTrail
) -> tuple[PushStore, PushService] | None:
    """Web Push (D11) on JARVIS's own VAPID key, derived from the token key (no new secret)."""
    subject = _vapid_subject(s)
    if not s.webpush_enabled or subject is None:
        return None
    vapid = VapidKey.from_secret(ring.secret("webpush_vapid", length=VAPID_BYTES), subject)
    store = PushStore(docs, ring, prefix=s.firestore_prefix)
    return store, PushService(store, vapid, audit)


def wire_notify(app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail) -> AlertSink:
    """`app.state.notify` / `push` / `push_store` / `notify_store` (None when off) and the alert
    sink every feature uses."""
    st = app.state
    st.notify = st.push = st.push_store = st.notify_store = None
    tg = st.telegram
    fallback: AlertSink = tg.alerts if tg is not None else NoAlerts("Telegram isn't set up")
    ring = Keyring.from_settings(s)
    if ring is None:
        return fallback
    store = NotifyStore(docs, ring, prefix=s.firestore_prefix)
    telegram = (
        TelegramHomeAlerts(tg.client, tg.store, store, audit, photo_sender=tg.client.send_photo)
        if tg is not None
        else None
    )
    try:  # M9: browser notifications are optional; their failure never takes the app down
        pushed = build_push(s, docs, ring, audit)
    except Exception as exc:  # noqa: BLE001 - log the class only; alerts still go to Telegram
        log.error(
            "browser notifications are OFF: setup failed", extra={"error": type(exc).__name__}
        )
        pushed = None
    st.push_store, st.push = pushed if pushed is not None else (None, None)
    st.notify_store = store
    st.notify = NotifyService(
        store, audit, telegram=telegram, push=st.push, timezone=s.user_timezone
    )
    return PolicyAlerts(st.notify)


# ---- small adapters between the workstreams ------------------------------------------------------


class _HomeIds:
    """B's `HomeDirectory`: the owner's home id from A's link record (None: not linked)."""

    def __init__(self, store: HomeStore) -> None:
        self._store = store

    async def home_id(self, uid: str) -> str | None:
        status = await self._store.status(uid)
        return status.home_id if status is not None else None


class _Snapshots:
    """B's `SnapshotPolicy`: D's opt-in (off when the settings can't be read: no photo)."""

    def __init__(self, notify: NotifyService) -> None:
        self._notify = notify

    async def snapshot_on(self, uid: str) -> bool:
        return bool((await self._notify.settings(uid)).snapshot.on)


class _LivePermissions:
    """The owner's passkey rules as built later in the wiring (`app.state.permissions`): B's
    Disarm button checks purpose `home_disarm` bound to `<home id>:<rev>`. None while they are
    not wired, which means the Google sign-in rule (a sign-in under 5 minutes old)."""

    def __init__(self, state: Any) -> None:
        self._state = state

    async def check_purpose(
        self, uid: str, purpose: str, target: str | None, proof: Any
    ) -> str | None:
        perms = getattr(self._state, "permissions", None)
        if perms is None:
            return None
        result: str | None = await perms.check_purpose(uid, purpose, target, proof)
        return result


def _laptop_online(
    store: HomeStore, offline_after_s: float, clock: Callable[[], float]
) -> Callable[[str], Awaitable[bool]]:
    async def online(uid: str) -> bool:
        status = await store.status(uid)
        if status is None or status.last_seen_at is None or status.state == "offline":
            return False
        return clock() - status.last_seen_at <= offline_after_s

    return online


class _EveryOwner:
    """D's ticks act on every owner they know themselves (held alerts, storm summaries, old rate
    counters); the watchdog's owner list (linked homes) is not theirs, so it is ignored."""

    budget_s = 20.0

    def __init__(self, name: str, run: Callable[[], Awaitable[int]]) -> None:
        self.name = name
        self._run = run

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        return {"done": int(await self._run())}


def notify_jobs(notify: NotifyService | None, clock: Callable[[], Any]) -> tuple[TickJob, ...]:
    if notify is None:
        return ()
    store = notify.store
    return (
        _EveryOwner("notify_held", notify.flush_all_held),
        _EveryOwner("notify_summaries", notify.flush_summaries),
        _EveryOwner("notify_rate_sweep", lambda: store.sweep(clock())),
    )


def notify_tick_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    """Integrated review H3: the alert policy's jobs (the held-alerts summary after quiet hours,
    storm summaries, old counters) run whether or not Home is on, and ONCE: in the home watchdog
    (every 5 minutes, all day) when it is wired, else in the scheduler tick. R1's and R2's alerts
    go through the policy too, so with Home off they would otherwise be held for ever."""
    st = app.state
    if getattr(st, "home_watchdog", None) is not None:
        return ()
    return notify_jobs(getattr(st, "notify", None), lambda: datetime.now(UTC))


def check_job_names(jobs: Sequence[TickJob]) -> None:
    from jarvis.api.personal import RESERVED_JOB_NAMES

    names = [j.name for j in jobs]
    if len(set(names)) != len(names) or (RESERVED_JOB_NAMES | RESERVED_HOME_JOBS) & set(names):
        raise RuntimeError("home tick job names must be unique and not a sweep's")


# ---- the home, the camera and faces (A, B, C) -------------------------------------------------


def _wire_faces(
    s: Settings, docs: Docs, ring: Keyring, client: HomeClient, audit: AuditTrail | None
) -> tuple[FacesService | None, FaceDirectory]:
    if not s.faces_enabled:
        return None, NoFaces()
    store = FacesStore(docs, ring, prefix=s.firestore_prefix)
    return FacesService(store, client, audit=audit), Directory(store)


def _notifier(app: FastAPI) -> Notifier:
    notify: NotifyService | None = app.state.notify
    return notify if notify is not None else DirectNotifier(app.state.alerts)


def wire_home(app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail | None = None) -> None:
    """Home, the camera and faces, or all OFF. M9: a part that fails to build (a bad setting, a
    store client that won't start) never takes the app down: it is logged by class name and
    everything Home stays None, so the routes say it is not available."""
    try:
        _wire_home(app, s, docs, audit)
    except Exception as exc:  # noqa: BLE001 - optional part: the rest of JARVIS keeps working
        log.error("Home is OFF: its setup failed", extra={"error": type(exc).__name__})
        for name in HOME_STATE:
            setattr(app.state, name, None)


def _wire_home(app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail | None) -> None:
    st = app.state
    for name in HOME_STATE:
        setattr(st, name, None)
    ring = Keyring.from_settings(s)
    if not s.home_enabled:
        return
    if ring is None:
        log.warning(NO_KEY_NOTE)
        return
    clock, prefix, tz = time.time, s.firestore_prefix, s.user_timezone
    store = HomeStore(docs, ring, prefix=prefix, clock=clock)
    client = HomeClient(store, clock=clock)
    faces, directory = _wire_faces(s, docs, ring, client, audit)
    notifier = _notifier(app)
    notify: NotifyService | None = st.notify
    camera = build_camera(
        docs=docs,
        keyring=ring,
        caller=client,
        faces=directory,
        notifier=notifier,
        homes=_HomeIds(store),
        permissions=_LivePermissions(st),  # type: ignore[arg-type]
        snapshots=_Snapshots(notify) if notify is not None else None,
        tz=tz,
        clock=clock,
        prefix=prefix,
    )
    devices = DeviceService(store, client, clock=clock)
    handlers: list[HomeEventHandler] = [
        HeartbeatHandler(store, notifier),
        HazardHandler(store, notifier),
        camera.events,
    ]
    sources: list[StateSource] = [devices, camera.state]
    if faces is not None:
        handlers.append(faces)
        sources.append(faces)
    jobs = (*camera.jobs, *notify_jobs(notify, lambda: datetime.now(UTC)))
    check_job_names(jobs)
    offline = OfflineJob(
        store, notifier, camera.alarm, clock=clock, offline_after_s=s.home_offline_after_s, tz=tz
    )
    store.on_unlink(camera.data.wipe)  # B: the arm state's rev never goes back (tombstone)
    st.home_store = store
    st.home_client = client
    st.home_link = LinkService(store, client, clock=clock)
    st.home_webhook = HomeWebhook(
        store, handlers, sources, clock=clock, per_minute=s.home_webhook_per_min
    )
    st.home_watchdog = Watchdog(store, offline, extra=jobs)
    st.home_devices = devices
    st.home_status = HomeStatusReader(
        store, clock=clock, offline_after_s=s.home_offline_after_s, tz=tz, arm=camera.alarm
    )
    st.camera = camera
    st.faces = faces
    st.faces_laptop = _laptop_online(store, s.home_offline_after_s, clock)
    st.home_parts = HomeParts(devices=devices, status=st.home_status, camera=camera, faces=faces)
    # S4: unlinking while armed switches the alarm off: the Disarm button's proof first
    st.home_unlink_guard = ArmedUnlinkGuard(camera.gate, camera.alarm, audit)


def home_privacy_sources(app: FastAPI) -> list[PrivacySource]:
    """In panel order; faces LAST (where R2's placeholder was)."""
    st = app.state
    camera: CameraServices | None = getattr(st, "camera", None)
    out: list[PrivacySource] = [
        HomePrivacy(getattr(st, "home_store", None), getattr(st, "home_unlink_guard", None)),
        camera.privacy[0] if camera is not None else HomeFeedPrivacy(None),
        camera.privacy[1] if camera is not None else CameraHomePrivacy(),
    ]
    if getattr(st, "notify_store", None) is not None:
        out.append(notify_source(st.notify_store))
    if getattr(st, "push_store", None) is not None:
        out.append(webpush_source(st.push_store))
    out.append(FacesPrivacy(getattr(st, "faces", None)))
    return out


__all__ = [
    "HOME_STATE",
    "build_push",
    "home_privacy_sources",
    "notify_jobs",
    "notify_tick_jobs",
    "wire_home",
    "wire_notify",
]
