# tests/tasks_fakes.py — the in-memory Google Tasks (evals/tasks/fake_tasks.py, shared with the
# eval harness so both pin the same behaviour) plus token/connector helpers for the to-do tests.
# A plain module (not conftest) so test files can import it under pytest's default import mode.
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from pydantic import SecretStr

from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import GoogleTokens, MemoryTokenStore

_PATH = Path(__file__).resolve().parents[1] / "evals" / "tasks" / "fake_tasks.py"
_spec = importlib.util.spec_from_file_location("fake_tasks", _PATH)
assert _spec is not None and _spec.loader is not None
_mod = sys.modules.get("fake_tasks") or importlib.util.module_from_spec(_spec)
if "fake_tasks" not in sys.modules:
    sys.modules["fake_tasks"] = _mod  # dataclasses resolve annotations through sys.modules
    _spec.loader.exec_module(_mod)

FakeTasks = _mod.FakeTasks
COMPLETED_AT = _mod.COMPLETED_AT

TASKS_UID = "u_owner"
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"
LINK_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


def link(*, tasks: bool = True, needs_reconnect: bool = False) -> GoogleTokens:
    return GoogleTokens(
        email="akash@example.com",
        access_token=SecretStr("acc"),
        refresh_token=SecretStr("ref"),
        expires_at=4_000_000_000.0,
        scopes=[*LINK_SCOPES, *([TASKS_SCOPE] if tasks else [])],
        needs_reconnect=needs_reconnect,
    )


async def tasks_connector(
    fake: object, *, linked: bool = True, tasks: bool = True, uid: str = TASKS_UID
) -> GoogleConnector:
    store = MemoryTokenStore()
    if linked:
        await store.put(uid, link(tasks=tasks))
    return GoogleConnector(
        store,
        client_id="cid",
        client_secret=SecretStr("s"),
        http=fake.client(),  # type: ignore[attr-defined]
    )


__all__ = [
    "COMPLETED_AT",
    "LINK_SCOPES",
    "TASKS_SCOPE",
    "TASKS_UID",
    "FakeTasks",
    "link",
    "tasks_connector",
]
