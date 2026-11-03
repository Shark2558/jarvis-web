# tests/people_fakes.py — the in-memory People API (evals/contacts_whatsapp/fake_people.py, shared
# with the eval harness so both pin the same behaviour) plus a linked Google connector for it.
# A plain module (not conftest) so test files can import it under pytest's default import mode.
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from pydantic import SecretStr

from jarvis.integrations.google import CONTACTS_SCOPE, GoogleConnector
from jarvis.integrations.vault import GoogleTokens, MemoryTokenStore

_PATH = Path(__file__).resolve().parents[1] / "evals" / "contacts_whatsapp" / "fake_people.py"
_spec = importlib.util.spec_from_file_location("fake_people", _PATH)
assert _spec is not None and _spec.loader is not None
_mod = sys.modules.get("fake_people") or importlib.util.module_from_spec(_spec)
if "fake_people" not in sys.modules:
    sys.modules["fake_people"] = _mod  # dataclasses resolve annotations through sys.modules
    _spec.loader.exec_module(_mod)

FakePeople = _mod.FakePeople
person = _mod.person

PEOPLE_UID = "u_owner"
LINK_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


async def people_connector(
    fake: object, *, linked: bool = True, contacts: bool = True, needs_reconnect: bool = False
) -> GoogleConnector:
    store = MemoryTokenStore()
    if linked:
        await store.put(
            PEOPLE_UID,
            GoogleTokens(
                email="akash@example.com",
                access_token=SecretStr("acc"),
                refresh_token=SecretStr("ref"),
                expires_at=4_000_000_000.0,
                scopes=[*LINK_SCOPES, *([CONTACTS_SCOPE] if contacts else [])],
                needs_reconnect=needs_reconnect,
            ),
        )
    return GoogleConnector(
        store,
        client_id="cid",
        client_secret=SecretStr("s"),
        http=fake.client(),  # type: ignore[attr-defined]
    )


__all__ = ["PEOPLE_UID", "FakePeople", "people_connector", "person"]
