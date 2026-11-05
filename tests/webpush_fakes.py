# tests/webpush_fakes.py -- a fake browser and push service for the R3 D tests. Never imported
# from conftest.
from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.webpush.service import PushService
from jarvis.webpush.store import PushStore
from jarvis.webpush.vapid import VapidKey


class SpyAudit(AuditLog):
    """AuditLog that also keeps the args it was given (the real chain stores only a hash)."""

    def __init__(self) -> None:
        super().__init__()
        self.args: list[dict[str, Any]] = []

    async def append(self, **kw: Any) -> Any:
        self.args.append(kw["args"])
        return await super().append(**kw)


ROOT = bytes(range(1, 33))
NOW = datetime(2027, 1, 15, 6, 30, tzinfo=UTC)
GOOD = "https://fcm.googleapis.com/fcm/send/abc123"
PUBLIC_IP = "142.250.1.1"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Browser:
    """A subscriber with real P-256 keys."""

    def __init__(self, endpoint: str = GOOD) -> None:
        self.private = ec.generate_private_key(ec.SECP256R1())
        raw = self.private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        self.p256dh = b64(raw)
        self.auth = b64(bytes(range(16)))
        self.endpoint = endpoint

    def sub(self, name: str = "Chrome on Android") -> dict[str, Any]:
        return {"name": name, "endpoint": self.endpoint, "p256dh": self.p256dh, "auth": self.auth}


async def resolver(host: str) -> list[str]:
    return [PUBLIC_IP]


class PushWorld:
    def __init__(self, status: int | dict[str, int] = 201) -> None:
        self.docs = MemoryDocs()
        self.ring = Keyring(ROOT)
        self.store = PushStore(self.docs, self.ring)
        self.audit = SpyAudit()
        self.requests: list[httpx.Request] = []
        self.status = status
        self.vapid = VapidKey.from_secret(
            self.ring.secret("webpush_vapid", length=48), "https://j.example"
        )
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), follow_redirects=False
        )
        self.service = PushService(
            self.store, self.vapid, self.audit, http=http, resolver=resolver, now=lambda: NOW
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        st = self.status if isinstance(self.status, int) else self.status.get(request.url.path, 201)
        return httpx.Response(st)
