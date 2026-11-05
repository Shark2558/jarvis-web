# tests/test_vault_build.py -- the vault stack is built only with a key and the switch on
from __future__ import annotations

from pydantic import SecretStr
from vault_fakes import PDF, UID, Bin

from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs
from jarvis.ticks import TickJob
from jarvis.vault.build import build_vault
from jarvis.vault.ports import VaultIntake

KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def settings(**kw: object) -> Settings:
    return Settings(_env_file=None, env="dev", firestore_prefix="t_", **kw)  # type: ignore[arg-type]


def test_no_key_means_no_vault_and_nothing_stored() -> None:
    assert build_vault(settings(), MemoryDocs(), extract=None, undo=Bin()) is None


def test_switched_off_means_no_vault() -> None:
    s = settings(token_key=SecretStr(KEY_B64), vault_enabled=False)
    assert build_vault(s, MemoryDocs(), extract=None, undo=Bin()) is None


async def test_built_stack_uses_the_settings_and_prefix() -> None:
    docs = MemoryDocs()
    s = settings(token_key=SecretStr(KEY_B64), vault_max_total_mb=20, vault_unlock_minutes=3)
    stack = build_vault(s, docs, extract=None, undo=Bin())
    assert stack is not None
    assert isinstance(stack.service, VaultIntake) and isinstance(stack.reminders, TickJob)
    assert stack.unlock.minutes == 3 and stack.service.limit_mb == 20
    await stack.service.add_file(UID, PDF)
    assert [p for p in docs._data if p.startswith("t_vault/")]
    assert {t.name for t in stack.tools()} == {"vault_list", "vault_expiring", "vault_set_dates"}
