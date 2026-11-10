# src/jarvis/permissions/models.py
"""Request and response shapes of /v1/permissions and /v1/passkeys (slice 10 D).

Browser credentials arrive as the JSON a `PublicKeyCredential` serialises to (base64url fields).
Every field is length-capped here, before py_webauthn parses anything; unknown fields are ignored.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.permissions.passkeys import LABEL_MAX

B64 = r"^[A-Za-z0-9_-]*$"
CHALLENGE_ID = r"^[A-Za-z0-9_-]{16,64}$"
CRED_ID_MAX = 1400  # a credential id is ≤ 1023 bytes


class _In(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AssertionResponse(_In):
    clientDataJSON: str = Field(max_length=4096, pattern=B64)  # noqa: N815 — the browser's name
    authenticatorData: str = Field(max_length=4096, pattern=B64)  # noqa: N815
    signature: str = Field(max_length=2048, pattern=B64)
    userHandle: str | None = Field(default=None, max_length=1024, pattern=B64)  # noqa: N815


class AssertionCredential(_In):
    id: str = Field(min_length=1, max_length=CRED_ID_MAX, pattern=B64)
    rawId: str = Field(min_length=1, max_length=CRED_ID_MAX, pattern=B64)  # noqa: N815
    type: Literal["public-key"]
    response: AssertionResponse
    authenticatorAttachment: str | None = Field(default=None, max_length=32)  # noqa: N815


class PasskeyProof(_In):
    """A fresh `navigator.credentials.get()` answer to a POST /v1/passkeys/challenge challenge."""

    challenge_id: str = Field(pattern=CHALLENGE_ID)
    credential: AssertionCredential

    def as_json(self) -> dict[str, Any]:
        return self.credential.model_dump(exclude_none=True)


class AttestationResponse(_In):
    clientDataJSON: str = Field(max_length=4096, pattern=B64)  # noqa: N815
    attestationObject: str = Field(max_length=65_536, pattern=B64)  # noqa: N815
    transports: list[str] = Field(default_factory=list, max_length=8)


class RegistrationCredential(_In):
    id: str = Field(min_length=1, max_length=CRED_ID_MAX, pattern=B64)
    rawId: str = Field(min_length=1, max_length=CRED_ID_MAX, pattern=B64)  # noqa: N815
    type: Literal["public-key"]
    response: AttestationResponse
    authenticatorAttachment: str | None = Field(default=None, max_length=32)  # noqa: N815


Purpose = Literal[
    "approve",
    "remove",
    "add",
    "disable",
    "cancel_reset",
    # R2: unlock the vault, delete a privacy category (or Remove now), export everything
    "vault_unlock",
    "privacy_delete",
    "privacy_export",
    # R3 D8: switch the burglar alert off, bound to "<home_id>:<arm rev>"
    "home_disarm",
    # R6 D8 / D10: open the build book (no target), lift a guest lock (bound to "bl_<12 hex>")
    "book_open",
    "book_resume",
]
# The purposes whose challenge is bound to (owner, purpose, target); checked by `check_purpose`.
TARGETED_PURPOSES: tuple[str, ...] = (
    "vault_unlock",
    "privacy_delete",
    "privacy_export",
    "home_disarm",
    "book_open",
    "book_resume",
)
TARGET_PATTERN = r"^[A-Za-z0-9_.:=-]{1,64}$"
HOME_DISARM_TARGET = r"^h_[0-9a-f]{8}:[0-9]{1,12}$"
BOOK_LOCK_TARGET = r"^bl_[0-9a-f]{12}$"


class ChallengeRequest(_In):
    purpose: Purpose
    approval_id: str | None = Field(default=None, max_length=64)
    credential_id: str | None = Field(default=None, max_length=CRED_ID_MAX, pattern=B64)
    # what a targeted purpose is for (a privacy category and its rev, a bin id), bound into the
    # challenge so a proof made for one target can't serve another
    target: str | None = Field(default=None, max_length=64, pattern=TARGET_PATTERN)


class RegisterOptionsRequest(_In):
    proof: PasskeyProof | None = None


class RegisterRequest(_In):
    challenge_id: str = Field(pattern=CHALLENGE_ID)
    credential: RegistrationCredential
    label: str = Field(default="", max_length=200)  # cleaned and cut to 40 by the service


class RemoveRequest(_In):
    proof: PasskeyProof | None = None


class CancelResetRequest(_In):
    proof: PasskeyProof | None = None


class PermissionsPatch(_In):
    groups: dict[str, str] | None = Field(default=None, max_length=48)  # R3: 33 rows
    require_passkey: bool | None = None
    proof: PasskeyProof | None = None


class ChallengeView(BaseModel):
    challenge_id: str
    public_key: dict[str, Any]  # navigator.credentials.get/create `publicKey` (base64url bytes)
    expires_in_s: int


class GroupView(BaseModel):
    id: str
    section: str
    label: str
    hint: str
    irreversible: bool
    choices: list[str]
    effect: str
    default: str
    # slice 11 fix HIGH-1: Never only because the owner chose Never for deletes before the split
    # (the hint says so); False once the owner's choices are written again
    inherited: bool = False
    # R1 D9: the row is ALWAYS listed; when the feature isn't connected yet `note` says what to do
    # (permissions/availability.py). Fail-soft default: available, no note.
    available: bool = True
    note: str = ""


class PasskeyView(BaseModel):
    id: str
    label: str
    created_at: str
    last_used_at: str | None
    backed_up: bool
    via_recovery: bool = Field(description="Set up right after a reset by Google sign-in")


class ResetView(BaseModel):
    requested_at: str
    effective_at: str  # all passkeys are removed then, unless cancelled with a passkey


class PermissionsView(BaseModel):
    groups: list[GroupView]
    require_passkey: bool  # in force: switched on AND at least one passkey registered
    passkeys: list[PasskeyView]
    passkeys_available: bool
    passkeys_note: str = Field(description="Why passkeys can't be used here (plain words)")
    passkeys_error: str = Field(
        default="", description="The stored passkeys can't be read (irreversible actions blocked)"
    )
    reset: ResetView | None = Field(
        default=None, description="A pending reset of all passkeys (requested by Google sign-in)"
    )
    can_reauth: bool = Field(description="Google sign-in exists: the 5-minute recovery path")
    fresh_sign_in_s: int | None = Field(
        description="Seconds left in which a recent Google sign-in may stand in for a passkey"
    )
    max_passkeys: int
    label_max: int = LABEL_MAX
    rev: int


__all__ = [
    "AssertionCredential",
    "BOOK_LOCK_TARGET",
    "CancelResetRequest",
    "ChallengeRequest",
    "ChallengeView",
    "GroupView",
    "HOME_DISARM_TARGET",
    "PasskeyProof",
    "PasskeyView",
    "PermissionsPatch",
    "PermissionsView",
    "TARGETED_PURPOSES",
    "TARGET_PATTERN",
    "Purpose",
    "RegisterOptionsRequest",
    "RegisterRequest",
    "RegistrationCredential",
    "RemoveRequest",
    "ResetView",
]
