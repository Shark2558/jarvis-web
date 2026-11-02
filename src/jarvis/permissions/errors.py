# src/jarvis/permissions/errors.py
"""What the permissions API can refuse, in plain words (slice 10 D). Mapped to the app's error
shape {error, detail, reason?} in `jarvis.api.permissions`."""

from __future__ import annotations

from jarvis.permissions.groups import PermissionRejected


class PasskeysUnavailable(Exception):
    """409 passkeys_unavailable: no relying party (JARVIS_PUBLIC_BASE_URL unset or an IP)."""


class PasskeyRequired(PermissionError):
    """403 passkey_required: an irreversible approval without a passkey check."""


class ProofRequired(PermissionError):
    """403 proof_required {reason}: "passkey" — a passkey check made for exactly this; "reauth" —
    a Google sign-in in this browser in the last 5 minutes (/auth/login?reauth=1)."""

    def __init__(self, detail: str, *, reason: str = "passkey") -> None:
        super().__init__(detail)
        self.reason = reason


class PasskeyRejected(PermissionError):
    """403 passkey_rejected: the check was replayed, expired, for another action, from another
    site, by an unknown passkey, or did not verify. `reason` is a stable code for the console."""

    def __init__(self, reason: str, detail: str, *, audit_detail: str = "") -> None:
        super().__init__(detail)
        self.reason = reason
        self.audit_detail = audit_detail or reason  # what the audit records (never shown)


class PasskeyNotFound(LookupError):
    """404: no such passkey for this owner."""


class PasskeyDataUnreadable(Exception):
    """503 passkeys_unreadable: the owner's passkeys can't be read; irreversible approvals are
    blocked (fail closed) until the owner resets their passkeys."""


__all__ = [
    "PasskeyDataUnreadable",
    "PasskeyNotFound",
    "PasskeyRejected",
    "PasskeyRequired",
    "PasskeysUnavailable",
    "PermissionRejected",
    "ProofRequired",
]
