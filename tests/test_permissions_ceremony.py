# tests/test_permissions_ceremony.py — WebAuthn ceremonies through py_webauthn with a software
# authenticator (no browser, no network): what verifies, and every way a response is refused.
from __future__ import annotations

import secrets

import pytest
from passkey_fakes import SoftAuthenticator, b64u

from jarvis.permissions.ceremony import (
    CeremonyFailed,
    RelyingParty,
    authentication_options,
    registration_options,
    verify_assertion,
    verify_registration,
)

RP = RelyingParty(id="jarvis.example.com", origin="https://jarvis.example.com")


@pytest.mark.parametrize(
    ("url", "rp_id", "origin"),
    [
        ("https://jarvis.example.com", "jarvis.example.com", "https://jarvis.example.com"),
        ("https://Jarvis.Example.com/", "jarvis.example.com", "https://jarvis.example.com"),
        ("https://jarvis.example.com:443/x", "jarvis.example.com", "https://jarvis.example.com"),
        ("http://localhost:8000", "localhost", "http://localhost:8000"),
        ("https://run.app:8443", "run.app", "https://run.app:8443"),
    ],
)
def test_relying_party_from_the_public_address(url: str, rp_id: str, origin: str) -> None:
    rp = RelyingParty.from_base_url(url)
    assert rp is not None and (rp.id, rp.origin) == (rp_id, origin)


@pytest.mark.parametrize(
    "url", [None, "", "ftp://x.example", "http://127.0.0.1:8000", "https://[::1]"]
)
def test_no_relying_party_where_passkeys_cannot_work(url: str | None) -> None:
    assert RelyingParty.from_base_url(url) is None


def _register(auth: SoftAuthenticator) -> tuple[str, str, int]:
    challenge = secrets.token_bytes(32)
    opts = registration_options(
        RP, challenge=challenge, user_handle=b"u_1", user_name="owner", exclude=[]
    )
    assert opts["authenticatorSelection"]["userVerification"] == "required"
    assert opts["rp"]["id"] == RP.id and opts["attestation"] == "none"
    new = verify_registration(RP, auth.create(opts), challenge=challenge)
    return new.id, new.public_key, new.sign_count


def _assert(auth: SoftAuthenticator, cid: str, pk: str, count: int, **kw: object) -> int:
    challenge = secrets.token_bytes(32)
    opts = authentication_options(RP, challenge=challenge, allow=[(cid, ("internal",))])
    assert opts["userVerification"] == "required" and opts["rpId"] == RP.id
    assert [c["id"] for c in opts["allowCredentials"]] == [cid]
    cred = auth.get(opts, **kw)  # type: ignore[arg-type]
    return verify_assertion(RP, cred, challenge=challenge, public_key=pk, sign_count=count)


def test_register_then_assert_round_trip_and_counter_grows() -> None:
    auth = SoftAuthenticator(origin=RP.origin)
    cid, pk, count = _register(auth)
    assert count == 0
    assert _assert(auth, cid, pk, count) == 1
    assert _assert(auth, cid, pk, 1) == 2


def test_registration_refused_without_user_verification_or_from_another_origin() -> None:
    for auth, kw in (
        (SoftAuthenticator(origin=RP.origin, user_verified=False), {}),
        (SoftAuthenticator(origin="https://evil.example"), {}),
        (SoftAuthenticator(origin=RP.origin), {"rp_id": "evil.example"}),
    ):
        challenge = secrets.token_bytes(32)
        opts = registration_options(
            RP, challenge=challenge, user_handle=b"u", user_name="o", exclude=[]
        )
        with pytest.raises(CeremonyFailed):
            verify_registration(RP, auth.create(opts, **kw), challenge=challenge)  # type: ignore[arg-type]


def test_registration_refused_for_another_challenge() -> None:
    auth = SoftAuthenticator(origin=RP.origin)
    opts = registration_options(
        RP, challenge=secrets.token_bytes(32), user_handle=b"u", user_name="o", exclude=[]
    )
    with pytest.raises(CeremonyFailed):
        verify_registration(RP, auth.create(opts), challenge=secrets.token_bytes(32))


@pytest.mark.parametrize(
    "kw",
    [
        {"origin": "https://evil.example"},
        {"rp_id": "evil.example"},
        {"sign_count": 0},  # counter went backwards after a use: a cloned authenticator
    ],
)
def test_assertion_refused_for_wrong_origin_rp_or_counter(kw: dict[str, object]) -> None:
    auth = SoftAuthenticator(origin=RP.origin)
    cid, pk, _ = _register(auth)
    _assert(auth, cid, pk, 0)
    with pytest.raises(CeremonyFailed):
        _assert(auth, cid, pk, 1, **kw)


def test_assertion_refused_without_user_verification() -> None:
    auth = SoftAuthenticator(origin=RP.origin)
    cid, pk, _ = _register(auth)
    auth.user_verified = False
    with pytest.raises(CeremonyFailed):
        _assert(auth, cid, pk, 0)


def test_assertion_refused_for_another_key_or_challenge_or_garbage() -> None:
    auth = SoftAuthenticator(origin=RP.origin)
    cid, pk, _ = _register(auth)
    other_cid, other_pk, _ = _register(auth)
    with pytest.raises(CeremonyFailed):
        _assert(auth, cid, other_pk, 0)  # signed by one key, checked with another
    challenge = secrets.token_bytes(32)
    opts = authentication_options(RP, challenge=challenge, allow=[(cid, ())])
    cred = auth.get(opts)
    with pytest.raises(CeremonyFailed):
        verify_assertion(RP, cred, challenge=secrets.token_bytes(32), public_key=pk, sign_count=0)
    for junk in ({}, {"id": "x"}, {"id": b64u(b"x"), "rawId": b64u(b"x"), "response": "no"}):
        with pytest.raises(CeremonyFailed):
            verify_assertion(RP, junk, challenge=challenge, public_key=pk, sign_count=0)


def test_counterless_authenticators_are_accepted_while_both_stay_zero() -> None:
    auth = SoftAuthenticator(origin=RP.origin, counter_step=0)
    cid, pk, _ = _register(auth)
    assert _assert(auth, cid, pk, 0) == 0
    assert _assert(auth, cid, pk, 0) == 0
