# src/jarvis/vault/build.py
"""One call that builds the whole vault stack for the app (R2 I1 wires the result).

Returns None when the vault is off (`JARVIS_VAULT_ENABLED=false`, or no token key: nothing of the
owner's is ever stored in clear). Prefix is `Settings.firestore_prefix`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from jarvis.alerts import AlertSink, NoAlerts
from jarvis.keyring import Keyring
from jarvis.storage.docs import Docs
from jarvis.vault.crypto import VaultCrypto
from jarvis.vault.privacy import VaultPrivacy
from jarvis.vault.reminders import BriefTime, VaultReminders, ZoneFor
from jarvis.vault.service import Extractor, VaultPurger, VaultRestorer, VaultService
from jarvis.vault.store import VaultStore
from jarvis.vault.tools import vault_tools
from jarvis.vault.unlock import UnlockStore

if TYPE_CHECKING:
    from jarvis.config import Settings
    from jarvis.tools.base import Tool


@dataclass(frozen=True)
class VaultStack:
    service: VaultService
    unlock: UnlockStore
    reminders: VaultReminders
    privacy: VaultPrivacy
    restorer: VaultRestorer
    purger: VaultPurger

    def tools(self) -> list[Tool]:
        return vault_tools(self.service)


def build_vault(
    settings: Settings,
    docs: Docs,
    *,
    extract: Extractor | None,
    undo: Any,
    alerts: AlertSink | None = None,
    brief_time: BriefTime | None = None,
    zone_for: ZoneFor | None = None,
    clock: Callable[[], datetime] | None = None,
) -> VaultStack | None:
    if not settings.vault_enabled:
        return None
    ring = Keyring.from_settings(settings)
    if ring is None:
        return None
    prefix = settings.firestore_prefix
    crypto = VaultCrypto(ring)
    kw: dict[str, Any] = {} if clock is None else {"clock": clock}
    service = VaultService(
        VaultStore(docs, crypto, prefix=prefix, **kw),
        crypto,
        extract=extract,
        undo=undo,
        max_total_mb=settings.vault_max_total_mb,
        **kw,
    )
    return VaultStack(
        service=service,
        unlock=UnlockStore(docs, ring, minutes=settings.vault_unlock_minutes, prefix=prefix, **kw),
        reminders=VaultReminders(
            service,
            alerts or NoAlerts(),
            docs,
            prefix=prefix,
            brief_time=brief_time,
            zone_for=zone_for,
            **kw,
        ),
        privacy=VaultPrivacy(service),
        restorer=VaultRestorer(service),
        purger=VaultPurger(service),
    )


__all__ = ["VaultStack", "build_vault"]
