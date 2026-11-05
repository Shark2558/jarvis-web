# src/jarvis/vault/ports.py
"""What the document vault offers other features (R2 D1, D9): one way in for a file.

The DigiLocker inbox job (workstream B) hands every new Drive file to `VaultIntake.intake`; the
vault service (workstream A) implements it (type check by magic bytes, size and total caps, dedupe
by SHA-256, encryption, a proposal for the dates). `NoVaultIntake` is used while the vault is off.
The result carries plain words only: never the file name, never a number from the file.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

VAULT_MIMES: tuple[str, ...] = ("application/pdf", "image/jpeg", "image/png")
MAX_FILE_BYTES = 10 * 1024 * 1024

Source = Literal["upload", "digilocker"]
IntakeStatus = Literal["added", "duplicate", "skipped"]


class IntakeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: IntakeStatus
    item_id: str | None = None  # the new item, or the one this file duplicates
    code: str = ""  # stable: too_big, unsupported, vault_full, unavailable, ...
    message: str = ""  # plain words for the owner


@runtime_checkable
class VaultIntake(Protocol):
    async def intake(
        self, uid: str, data: bytes, *, source: Source, drive_id: str | None = None
    ) -> IntakeResult: ...


class NoVaultIntake:
    """The intake when the vault is off (no encryption key, or switched off)."""

    async def intake(
        self, uid: str, data: bytes, *, source: Source, drive_id: str | None = None
    ) -> IntakeResult:
        return IntakeResult(
            status="skipped",
            code="unavailable",
            message="The vault isn't available on this server.",
        )


__all__ = [
    "MAX_FILE_BYTES",
    "VAULT_MIMES",
    "IntakeResult",
    "IntakeStatus",
    "NoVaultIntake",
    "Source",
    "VaultIntake",
]
