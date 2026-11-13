# evals/r7/contract.py
"""R7 eval, I0's own part (`contract`, BUILT): the phone's signed request (D6, D24) that the
server (Part C) and the app's `core` module (Part E) both write, checked against the shared
vectors (tests/fixtures/r7/phone_vectors.json):

- each case's signing string is exactly `jarvis.mobile.contract.signing_string(...)`;
- its header parses to the case's device, time and nonce;
- the signature verifies against the vectors' public key exactly when the case says it should
  (good cases yes; a changed body, another key and a changed path no);
- a payload's canonical JSON is the case's body byte for byte (the app's tiny JSON writer);
- a path with a query string, or that is not one of the door's four routes, is refused.

Negative control: one byte of every case's body is flipped (and nothing else changes): every
good case must then fail, so this part cannot pass whatever it is given.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from jarvis.mobile import contract  # noqa: E402

PART = "contract"
BUILT = True
VECTORS = ROOT / "tests" / "fixtures" / "r7" / "phone_vectors.json"


def _vectors() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(VECTORS.read_text(encoding="utf-8"))
    return data


def _flip(body: bytes) -> bytes:
    return body[:-1] + bytes([body[-1] ^ 0x01]) if body else b"\x01"


def _verifies(key: ec.EllipticCurvePublicKey, signature: bytes, string: bytes) -> bool:
    try:
        key.verify(signature, string, ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False


def _case(
    v: dict[str, Any], key: ec.EllipticCurvePublicKey, c: dict[str, Any], tamper: bool
) -> dict[str, Any]:
    failures: list[str] = []
    body = c["body"].encode("utf-8")
    body = _flip(body) if tamper else body
    string = contract.signing_string(
        v["device_id"], c["t"], c["nonce"], c["method"], c["path"], body
    )
    if string.decode("ascii") != c["string"]:
        failures.append("the signing string differs")
    auth = contract.parse_header(c["header"])
    if auth is None or (auth.device_id, auth.t, auth.nonce) != (v["device_id"], c["t"], c["nonce"]):
        failures.append("the header does not parse to the case")
    elif _verifies(key, auth.signature, string) is not c["verifies"]:
        failures.append("the signature check is not what the case says")
    if "payload" in c and contract.canonical_json(c["payload"]) != body:
        failures.append("the payload's canonical JSON is not the body")
    return {"id": f"{PART}:{c['name']}", "passed": not failures, "failures": failures}


def _refusals(v: dict[str, Any]) -> dict[str, Any]:
    failures = []
    for path in v["refused_paths"]:
        try:
            contract.signing_string(v["device_id"], 1, "a" * 32, "POST", path, b"")
            failures.append(f"{path} was accepted")
        except ValueError:
            pass
    return {"id": f"{PART}:refused_paths", "passed": not failures, "failures": failures}


def _run(tamper: bool) -> list[dict[str, Any]]:
    v = _vectors()
    key = serialization.load_der_public_key(bytes.fromhex(v["public_key_spki_der_hex"]))
    assert isinstance(key, ec.EllipticCurvePublicKey)
    return [*(_case(v, key, c, tamper) for c in v["cases"]), _refusals(v)]


async def cases() -> list[dict[str, Any]]:
    return _run(tamper=False)


async def control() -> dict[str, Any]:
    failed = [r["id"] for r in _run(tamper=True) if not r["passed"]]
    good = {f"{PART}:{c['name']}" for c in _vectors()["cases"] if c["verifies"]}
    return {
        "name": "contract: one byte of every body flipped",
        "suite_failed": good <= set(failed),
        "failed_cases": failed,
    }
