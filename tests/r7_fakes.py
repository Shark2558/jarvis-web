# tests/r7_fakes.py -- R7 I0 (docs/plans/r7-mobile.md seam 9): the phone door's fake and the
# shared vectors, for every part's tests. Never imported from conftest.
#
#   load_vectors()                       tests/fixtures/r7/phone_vectors.json (public key only)
#   phone_key()                          a fresh P-256 key made in the test (never committed)
#   sign_request(key, device, method, path, payload, t=, nonce=) -> (headers, body bytes)
#                                        what the app's signed client sends (canonical JSON)
#   FakeDoor(handlers).call(route, body) the door AFTER its checks passed: Parts C and D test their
#                                        handlers (`MobilePart.services["door"]`) against it
#
# Part C's real door is tested with `sign_request` (good and bad signatures, stale times, replayed
# nonces, a query string); the handlers never see a request that failed a check.
from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from jarvis.mobile import contract
from jarvis.mobile.ports import DOOR_ROUTES, PhoneHandler, PhoneReply, PhoneRequest

VECTORS = Path(__file__).parent / "fixtures" / "r7" / "phone_vectors.json"
DEVICE = "ph_0123456789ab"
UID = "owner"


def load_vectors() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(VECTORS.read_text(encoding="utf-8"))
    return data


def phone_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def sign_request(
    key: ec.EllipticCurvePrivateKey,
    device_id: str,
    method: str,
    path: str,
    payload: Any,
    *,
    t: int | None = None,
    nonce: str | None = None,
) -> tuple[dict[str, str], bytes]:
    body = payload if isinstance(payload, bytes) else contract.canonical_json(payload)
    when = int(time.time()) if t is None else t
    n = nonce or os.urandom(16).hex()
    string = contract.signing_string(device_id, when, n, method, path, body)
    signature = key.sign(string, ec.ECDSA(hashes.SHA256()))
    return {contract.HEADER: contract.header_value(device_id, when, n, signature)}, body


class FakeDoor:
    """The door with every check already passed: route -> the registered handler."""

    def __init__(
        self, handlers: Mapping[str, PhoneHandler], *, device_id: str = DEVICE, uid: str = UID
    ) -> None:
        self.handlers = dict(handlers)
        self.device_id = device_id
        self.uid = uid

    async def call(self, route: str, body: bytes, *, at: float | None = None) -> PhoneReply:
        handler = self.handlers.get(route)
        if route not in DOOR_ROUTES or handler is None:
            return PhoneReply(404, {"error": "not_found"})
        req = PhoneRequest(
            route=route,
            device_id=self.device_id,
            uid=self.uid,
            body=body,
            at=time.time() if at is None else at,
        )
        return await handler(req)


__all__ = ["DEVICE", "UID", "FakeDoor", "load_vectors", "phone_key", "sign_request"]
