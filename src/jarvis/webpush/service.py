# src/jarvis/webpush/service.py
"""Web Push for the owner's browsers (R3 D11).

`subscribe` validates everything the browser sends (endpoint rule, a real P-256 point, a 16-byte
secret, a cleaned name, at most 5 devices) before anything is stored. `send` is the push
channel: one encrypted message per device, in parallel, each failure contained (a failing push
never blocks the other channels). A 404 or 410 removes the device. The payload is the fixed
template text, the kind and the click target (<= 1 KB), never a picture and never other text.
R7 D8 (Part A): the click target is the panel the alert is about, `/?open=<panel>` (`TARGETS`; a
test alert and an unknown kind open the console, `/`); the push worker hands it to the JARVIS
window already open (console-sw.js).
Each send is audited with counts only (agent "alerts", tool `webpush_send`).
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

import httpx

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.offline.config import PinnedTransport, Resolver, system_resolver
from jarvis.tools.audit import AuditTrail
from jarvis.webpush import endpoints
from jarvis.webpush.ece import AUTH_BYTES, EceError, encrypt, public_key
from jarvis.webpush.endpoints import BadEndpoint
from jarvis.webpush.store import Device, PushStore
from jarvis.webpush.vapid import VapidKey

log = get_logger(__name__)
MAX_PAYLOAD_BYTES = 1024
MAX_TEXT_CHARS = 300
NAME_MAX = 40
TIMEOUT_S = 8.0
TTL_INTRUDER_S = 600
TTL_DEFAULT_S = 86_400
GONE = frozenset({404, 410})
OK = frozenset({200, 201, 202})
_B64 = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")
_HELPERS = (
    "disaster_alert",
    "bill_due",
    "birthday",
    "chore_due",
    "maintenance_due",
    "weather_warning",
    "breach_notice",
    "nudge_standup",
    "nudge_hydrate",
    "nudge_activity",
    "nudge_free_time",
    "nudge_focus",
    "weather_note",
    "watch_stale",  # Helpers -> Watch
)
_HOME = (
    "home_intruder",
    "home_hazard",
    "home_package",
    "home_greeting",
    "home_offline",
    "home_online",
    "home_arm_failed",
    "home_summary",
    "home_offline_idle",
)
# R7 D8: the panel each alert opens (console-r7-links.js allows exactly the dock's panels). The
# systems check, Offline mode, the phone app and Emergency SOS are cards in Integrations.
TARGETS: Mapping[str, str] = {
    "approval_waiting": "approvals",
    "series_checkin": "approvals",  # the check-ins sit above the Approvals list (R11.1)
    "offline_on": "integrations",
    "offline_off": "integrations",
    "brief_ready": "brief",
    "vault_expiry": "vault",
    "vitals_warn": "vitals",
    "vitals_critical": "vitals",
    "health_fault": "integrations",
    "health_recovered": "integrations",
    "health_degraded": "integrations",
    "book_sealed": "book",
    "book_seal_failed": "book",
    "book_session_closed": "book",
    "faces_to_name": "faces",
    "sos_sent": "integrations",
    "sos_contact_left": "integrations",
    "phone_linked": "integrations",
    "phone_unlinked": "integrations",
    **{kind: "helpers" for kind in _HELPERS},
    **{kind: "home" for kind in _HOME},
}


class BadSubscription(ValueError):
    """The browser's subscription is refused (plain words)."""


def _unb64(text: object, *, max_chars: int) -> bytes:
    if not isinstance(text, str) or not text or len(text) > max_chars or not _B64.fullmatch(text):
        raise BadSubscription("That browser subscription isn't valid.")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def clean_name(name: object) -> str:
    one = re.sub(r"[\x00-\x1f\x7f<>]", " ", name if isinstance(name, str) else "")
    one = re.sub(r"\s+", " ", one).strip()
    if not one:
        raise BadSubscription("Give this device a name, like Chrome on Android.")
    return one[:NAME_MAX]


def payload_for(kind: str, text: str) -> bytes:
    """The whole push payload: kind, template text and click target. Never anything else."""
    body = {
        "kind": kind,
        "text": re.sub(r"\s+", " ", text).strip()[:MAX_TEXT_CHARS],
        "url": f"/?open={TARGETS[kind]}" if kind in TARGETS else "/",
    }
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    while len(raw) > MAX_PAYLOAD_BYTES:  # multi-byte text: trim until it fits
        body["text"] = body["text"][: len(body["text"]) // 2]
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    return raw


class PushService:
    def __init__(
        self,
        store: PushStore,
        vapid: VapidKey,
        audit: AuditTrail,
        *,
        http: httpx.AsyncClient | None = None,
        resolver: Resolver = system_resolver,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._vapid = vapid
        self._audit = audit
        self._http = http or httpx.AsyncClient(
            transport=PinnedTransport(resolver), follow_redirects=False, timeout=TIMEOUT_S
        )
        self._resolver = resolver
        self._now = now

    @property
    def public_key(self) -> str:
        return self._vapid.public_key

    async def aclose(self) -> None:
        await self._http.aclose()

    async def devices(self, uid: str) -> list[Device]:
        return await self._store.list(uid)

    async def subscribe(
        self, uid: str, *, name: object, endpoint: object, p256dh: object, auth: object
    ) -> Device:
        label = clean_name(name)
        try:
            await endpoints.check(str(endpoint), resolver=self._resolver)
        except BadEndpoint as exc:
            raise BadSubscription(str(exc)) from None
        key_raw = _unb64(p256dh, max_chars=120)
        auth_raw = _unb64(auth, max_chars=40)
        if len(auth_raw) != AUTH_BYTES:
            raise BadSubscription("That browser subscription isn't valid.")
        try:
            public_key(key_raw)
        except EceError:
            raise BadSubscription("That browser subscription isn't valid.") from None
        return await self._store.add(uid, label, str(endpoint), _b64url(key_raw), _b64url(auth_raw))

    async def remove(self, uid: str, device_id: str) -> bool:
        return await self._store.remove(uid, device_id)

    async def send(self, uid: str, *, kind: str, text: str, silent: bool = False) -> int:
        """Deliver to every device; the number that accepted it. Never raises."""
        try:
            devices = await self._store.list(uid)
        except Exception as exc:  # noqa: BLE001
            log.warning("push list unavailable", extra={"error": type(exc).__name__})
            await self._record("failed", kind, sent=0, failed=0)
            return 0
        if not devices:
            return 0
        payload = payload_for(kind, text)
        ttl = TTL_INTRUDER_S if kind == "home_intruder" else TTL_DEFAULT_S
        results = await asyncio.gather(
            *(self._one(uid, d, payload, ttl, silent) for d in devices), return_exceptions=True
        )
        sent = sum(1 for r in results if r is True)
        failed = len(devices) - sent
        await self._record("sent" if sent else "failed", kind, sent=sent, failed=failed)
        return sent

    async def _one(self, uid: str, dev: Device, payload: bytes, ttl: int, silent: bool) -> bool:
        try:
            await endpoints.check(dev.endpoint, resolver=self._resolver)
            body = encrypt(
                payload,
                base64.urlsafe_b64decode(dev.p256dh + "=" * (-len(dev.p256dh) % 4)),
                base64.urlsafe_b64decode(dev.auth + "=" * (-len(dev.auth) % 4)),
            )
            headers = {
                "Authorization": self._vapid.header(dev.endpoint, self._now()),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(ttl),
                "Urgency": "low" if silent else "high",
            }
            resp = await self._http.post(dev.endpoint, content=body, headers=headers)
        except Exception as exc:  # noqa: BLE001 - one device's failure is contained
            log.warning("push failed", extra={"error": type(exc).__name__})
            return False
        if resp.status_code in GONE:
            try:
                await self._store.remove(uid, dev.id)
            except Exception as exc:  # noqa: BLE001
                log.warning("push device not removed", extra={"error": type(exc).__name__})
            return False
        if resp.status_code not in OK:
            log.warning("push refused", extra={"status": resp.status_code})
            return False
        try:
            await self._store.mark_ok(uid, dev.id)
        except Exception as exc:  # noqa: BLE001
            log.warning("push mark failed", extra={"error": type(exc).__name__})
        return True

    async def _record(self, outcome: str, kind: str, *, sent: int, failed: int) -> None:
        try:
            await self._audit.append(
                agent="alerts",
                tool="webpush_send",
                risk=ActionRisk.READ_ONLY,
                outcome=outcome,
                args={"kind": kind, "sent": sent, "failed": failed},
            )
        except Exception as exc:  # noqa: BLE001 - the push already happened
            log.error("AUDIT WRITE FAILED for a push", extra={"error": type(exc).__name__})


__all__ = ["TARGETS", "BadSubscription", "PushService", "clean_name", "payload_for"]
