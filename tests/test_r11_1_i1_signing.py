# tests/test_r11_1_i1_signing.py -- R11.1 I1 owns Part C's additive change to R3's one HMAC module
# (home/signing.py: BODY_HASH_HEADER, body_hash, verify_declared; review C-sec M1). The MAC is
# unchanged: golden headers computed with the R3 version of the module (as it was at r11-1-i0)
# still come out byte for byte, and a request without the new header verifies as before. The
# check over a DECLARED hash passes only for the real signature, refuses a wrong or malformed
# hash, a stale time, a seen nonce and a bad target, and never remembers the nonce itself.
from __future__ import annotations

import pytest

from jarvis.home.signing import (
    BODY_HASH_HEADER,
    NonceCache,
    SignatureError,
    body_hash,
    derive_keys,
    parse,
    sign,
    verify,
    verify_declared,
)

KEYS = derive_keys(bytes(range(32)))
HOME, NOW, NONCE = "h_0123abcd", 1_800_000_000, "n" * 22
PHOTO = ("down", "POST", "/bridge/v1/faces/photos", b"\xff\xd8 a picture")
# computed by the R3 module (git show r11-1-i0:src/jarvis/home/signing.py), same inputs
GOLDEN = [
    (PHOTO, "XfW2Ttppczjg-SYeGEMB4RuXHrkB2mkFux7wFb25di4"),
    (("up", "GET", "/bridge/v1/health", b""), "SN3YoS4mH5zaDK1AJ2IFhLf6fnuo6yZREmo8wLoxj0Q"),
    (
        ("down", "POST", "/bridge/v1/faces/enrol", b'{"person":"p_1"}'),
        "8bq6fo4yB3hV00fvm_dKT9Yrqtc7WUhfwJ2E8HOX-50",
    ),
]


def _sign(direction: str, method: str, target: str, body: bytes) -> str:
    return sign(
        KEYS, direction, home_id=HOME, method=method, target=target, body=body,  # type: ignore[arg-type]
        now=NOW, nonce=NONCE,
    )  # fmt: skip


@pytest.mark.parametrize(("args", "mac"), GOLDEN)
def test_the_mac_is_byte_for_byte_r3_s(args: tuple[str, str, str, bytes], mac: str) -> None:
    assert _sign(*args) == f"v1;h={HOME};t={NOW};n={NONCE};s={mac}"


def test_a_request_without_the_new_header_verifies_as_before() -> None:
    direction, method, target, body = PHOTO
    nonces = NonceCache()
    verify(parse(_sign(*PHOTO)), KEYS, direction, method=method, target=target, body=body,
           now=NOW, nonces=nonces)  # type: ignore[arg-type]  # fmt: skip
    with pytest.raises(SignatureError, match="nonce"):  # remembered by the full check
        verify(parse(_sign(*PHOTO)), KEYS, direction, method=method, target=target, body=body,
               now=NOW, nonces=nonces)  # type: ignore[arg-type]  # fmt: skip


def _declared(digest: object, *, now: float = NOW, target: str = PHOTO[2], nonces=None) -> None:  # type: ignore[no-untyped-def]
    verify_declared(
        parse(_sign(*PHOTO)), KEYS, "down", method="POST", target=target,
        digest=digest, now=now, nonces=nonces or NonceCache(),  # type: ignore[arg-type]
    )  # fmt: skip


def test_the_declared_hash_check_passes_for_the_real_body_and_remembers_nothing() -> None:
    assert BODY_HASH_HEADER == "X-Jarvis-Body-Sha256" and len(body_hash(PHOTO[3])) == 64
    nonces = NonceCache()
    _declared(body_hash(PHOTO[3]), nonces=nonces)
    _declared(body_hash(PHOTO[3]), nonces=nonces)  # the nonce was not remembered by the pre-check
    direction, method, target, body = PHOTO
    verify(parse(_sign(*PHOTO)), KEYS, direction, method=method, target=target, body=body,
           now=NOW, nonces=nonces)  # type: ignore[arg-type]  # fmt: skip


@pytest.mark.parametrize(
    ("digest", "why"),
    [
        (body_hash(b"another body"), "mac"),
        (body_hash(PHOTO[3]).upper(), "shape"),
        ("ab" * 31, "shape"),
        (None, "shape"),
        (123, "shape"),
    ],
)
def test_a_wrong_or_malformed_declared_hash_is_refused(digest: object, why: str) -> None:
    with pytest.raises(SignatureError, match=why):
        _declared(digest)


def test_a_stale_time_a_seen_nonce_or_another_target_is_refused_before_the_body() -> None:
    good = body_hash(PHOTO[3])
    with pytest.raises(SignatureError, match="time"):
        _declared(good, now=NOW + 3600)
    seen = NonceCache()
    seen.remember(HOME, NONCE, NOW)
    with pytest.raises(SignatureError, match="nonce"):
        _declared(good, nonces=seen)
    with pytest.raises(SignatureError, match="mac"):
        _declared(good, target="/bridge/v1/faces/enrol")
