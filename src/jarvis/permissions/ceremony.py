# src/jarvis/permissions/ceremony.py
"""WebAuthn ceremonies (slice 10 D). The only module that imports `webauthn` — py_webauthn by Duo
Labs, BSD-3-Clause, 3.0.1 (the latest on PyPI, checked 2026-11-01).

The relying party is this server's public address (`JARVIS_PUBLIC_BASE_URL`): RP ID = its host,
expected origin = its scheme://host[:port]. Both are checked by py_webauthn on every response
(clientDataJSON origin, the RP ID hash in the authenticator data), as are the challenge, the
ceremony type, user presence, user verification (always required here) and — on an assertion —
the ES256 / EdDSA / RS256 signature and the sign counter (a counter that does not grow is refused
unless both stay 0, which authenticators without a counter report).

Every failure is one exception, `CeremonyFailed`, with a short internal reason for the log; the
owner sees plain words from the service, never library text.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidJSONStructure,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

TIMEOUT_MS = 120_000  # the browser's own prompt timeout; the challenge also expires at 2 minutes
RP_NAME = "JARVIS"


class CeremonyFailed(Exception):
    """The browser's response did not verify. `reason` is for logs, not for the owner."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RelyingParty:
    id: str
    origin: str
    name: str = RP_NAME

    @classmethod
    def from_base_url(cls, url: str | None) -> RelyingParty | None:
        """None when passkeys can't work at this address: no URL, not http(s), or an IP address
        (WebAuthn needs a domain name; "localhost" is one)."""
        if not url:
            return None
        u = urlsplit(url.strip())
        host = (u.hostname or "").lower()
        if u.scheme not in ("http", "https") or not host:
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        default = 443 if u.scheme == "https" else 80
        port = f":{u.port}" if u.port and u.port != default else ""
        return cls(id=host, origin=f"{u.scheme}://{host}{port}")


@dataclass(frozen=True)
class NewCredential:
    id: str  # base64url
    public_key: str  # base64url COSE key
    sign_count: int
    transports: tuple[str, ...]
    backed_up: bool


def _descriptors(ids: list[tuple[str, tuple[str, ...]]]) -> list[PublicKeyCredentialDescriptor]:
    out: list[PublicKeyCredentialDescriptor] = []
    for cid, transports in ids:
        known = [AuthenticatorTransport(t) for t in transports if t in _TRANSPORTS]
        out.append(PublicKeyCredentialDescriptor(id=base64url_to_bytes(cid), transports=known))
    return out


_TRANSPORTS = {t.value for t in AuthenticatorTransport}


def registration_options(
    rp: RelyingParty,
    *,
    challenge: bytes,
    user_handle: bytes,
    user_name: str,
    exclude: list[tuple[str, tuple[str, ...]]],
) -> dict[str, Any]:
    """`publicKey` options for navigator.credentials.create(), as JSON (base64url bytes)."""
    opts = generate_registration_options(
        rp_id=rp.id,
        rp_name=rp.name,
        user_id=user_handle,
        user_name=user_name,
        user_display_name=user_name,
        challenge=challenge,
        timeout=TIMEOUT_MS,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=_descriptors(exclude),
    )
    out: dict[str, Any] = json.loads(options_to_json(opts))
    return out


def authentication_options(
    rp: RelyingParty, *, challenge: bytes, allow: list[tuple[str, tuple[str, ...]]]
) -> dict[str, Any]:
    """`publicKey` options for navigator.credentials.get(): only this owner's passkeys."""
    opts = generate_authentication_options(
        rp_id=rp.id,
        challenge=challenge,
        timeout=TIMEOUT_MS,
        allow_credentials=_descriptors(allow),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    out: dict[str, Any] = json.loads(options_to_json(opts))
    return out


def verify_registration(
    rp: RelyingParty, credential: dict[str, Any], *, challenge: bytes
) -> NewCredential:
    try:
        v = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp.id,
            expected_origin=rp.origin,
            require_user_presence=True,
            require_user_verification=True,
        )
    except (InvalidRegistrationResponse, InvalidJSONStructure) as exc:
        raise CeremonyFailed(f"registration: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — malformed input must never become a 500
        raise CeremonyFailed(f"registration: {type(exc).__name__}") from exc
    response = credential.get("response") if isinstance(credential, dict) else None
    raw = response.get("transports") if isinstance(response, dict) else None
    transports = tuple(t for t in (raw or []) if isinstance(t, str) and t in _TRANSPORTS)[:6]
    return NewCredential(
        id=bytes_to_base64url(v.credential_id),
        public_key=bytes_to_base64url(v.credential_public_key),
        sign_count=v.sign_count,
        transports=transports,
        backed_up=bool(v.credential_backed_up),
    )


def verify_assertion(
    rp: RelyingParty,
    credential: dict[str, Any],
    *,
    challenge: bytes,
    public_key: str,
    sign_count: int,
) -> int:
    """The authenticator's new sign count, or CeremonyFailed."""
    try:
        v = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp.id,
            expected_origin=rp.origin,
            credential_public_key=base64url_to_bytes(public_key),
            credential_current_sign_count=sign_count,
            require_user_verification=True,
        )
    except (InvalidAuthenticationResponse, InvalidJSONStructure) as exc:
        raise CeremonyFailed(f"assertion: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — malformed input must never become a 500
        raise CeremonyFailed(f"assertion: {type(exc).__name__}") from exc
    return int(v.new_sign_count)


__all__ = [
    "CeremonyFailed",
    "NewCredential",
    "RelyingParty",
    "authentication_options",
    "registration_options",
    "verify_assertion",
    "verify_registration",
]
