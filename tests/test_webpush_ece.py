# tests/test_webpush_ece.py -- R3 D11: RFC 8291 encryption, byte for byte against Appendix A.
from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from jarvis.webpush.ece import EceError, encrypt, public_key


def b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


PLAINTEXT = b"When I grow up, I want to be a watermelon"
AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
UA_PUBLIC = (
    "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
)
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
SALT = "DGv6ra1nlYgDCS1FRnbzlw"
BODY = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmY"
    "WAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexS"
    "gSxsj_Qulcy4a-fN"
)


def test_rfc_8291_appendix_a_is_reproduced_byte_for_byte() -> None:
    key = ec.derive_private_key(int.from_bytes(b64(AS_PRIVATE), "big"), ec.SECP256R1())
    got = encrypt(PLAINTEXT, b64(UA_PUBLIC), b64(AUTH), salt=b64(SALT), sender_private=key)
    assert got == b64(BODY)


def test_the_receiver_can_decrypt_a_fresh_message() -> None:
    ua = ec.generate_private_key(ec.SECP256R1())
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    ua_pub = ua.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    auth = bytes(range(16))
    body = encrypt(b"hello", ua_pub, auth)
    salt, as_pub, sealed = body[:16], body[21:86], body[86:]
    assert body[16:20] == (4096).to_bytes(4, "big") and body[20] == 65
    shared = ua.exchange(ec.ECDH(), public_key(as_pub))
    ikm = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\x00" + ua_pub + as_pub).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    assert AESGCM(cek).decrypt(nonce, sealed, None) == b"hello\x02"


def test_two_messages_differ() -> None:
    ua = b64(UA_PUBLIC)
    assert encrypt(b"x", ua, b64(AUTH)) != encrypt(b"x", ua, b64(AUTH))


@pytest.mark.parametrize(
    ("payload", "p256dh", "auth", "salt"),
    [
        (b"x" * 4080, b64(UA_PUBLIC), b64(AUTH), None),
        (b"x", b64(UA_PUBLIC), b"short", None),
        (b"x", b"\x04" + b"\x01" * 64, b64(AUTH), None),  # not on the curve
        (b"x", b"\x02" + b"\x00" * 64, b64(AUTH), None),  # not uncompressed
        (b"x", b64(UA_PUBLIC)[:-1], b64(AUTH), None),
        (b"x", b64(UA_PUBLIC), b64(AUTH), b"salt"),
    ],
)
def test_bad_inputs_are_refused(
    payload: bytes, p256dh: bytes, auth: bytes, salt: bytes | None
) -> None:
    with pytest.raises(EceError):
        encrypt(payload, p256dh, auth, salt=salt)
