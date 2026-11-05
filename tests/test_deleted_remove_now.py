# tests/test_deleted_remove_now.py -- R2 I1 (plan D8, "Re-checked at R2 I0"): "Remove now" on a
# vault document, a note or a thing can't be brought back, so DELETE /v1/deleted/{id} asks for a
# passkey check made for exactly that bin entry (purpose privacy_delete, target = the bin id), or,
# with no passkeys in force, a Google sign-in under 5 minutes old. Other kinds are unchanged. A
# restored entry is never purgeable and asks for nothing.
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.permissions.errors import PasskeyDataUnreadable, PasskeyRejected, PasskeyRequired
from jarvis.storage.docs import MemoryDocs
from jarvis.undo.models import DeletedItem
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore

UID = "owner"
H = {"X-Requested-With": "JARVIS"}
PROOF = {
    "challenge_id": "c" * 20,
    "credential": {
        "id": "Y3JlZA",
        "rawId": "Y3JlZA",
        "type": "public-key",
        "response": {"clientDataJSON": "e30", "authenticatorData": "YQ", "signature": "c2ln"},
    },
}


class Purger:
    def __init__(self) -> None:
        self.purged: list[str] = []

    async def purge(self, uid: str, item: DeletedItem) -> None:
        self.purged.append(item.id)


class Restorer:
    async def restore(self, uid: str, item: DeletedItem, *, outside: bool = False) -> Any:
        raise AssertionError("not used")


@dataclass
class Perms:
    in_force: bool = False
    fail: Exception | None = None
    seen: list[tuple[str, str | None, Any]] = field(default_factory=list)

    async def passkey_required(self, uid: str) -> bool:
        return self.in_force

    async def check_purpose(
        self, uid: str, purpose: str, target: str | None, proof: Any
    ) -> str | None:
        self.seen.append((purpose, target, proof))
        if not self.in_force:
            return None
        if self.fail is not None:
            raise self.fail
        if proof is None:
            raise PasskeyRequired("Approve this with your passkey.")
        return "passkey pk_1"


@dataclass
class Rig:
    client: AsyncClient
    app: Any
    undo: UndoBin
    purger: Purger
    perms: Perms


@pytest.fixture
async def rig(settings: Settings) -> AsyncIterator[Rig]:
    undo = UndoBin(DeletedStore(MemoryDocs()))
    purger = Purger()
    for kind in ("note", "thing", "vault_item", "event"):
        undo.register(kind, Restorer(), purger)  # type: ignore[arg-type]
    s = settings.model_copy(update={"tools_enabled": True})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore(), undo=undo)
    async with app.router.lifespan_context(app):
        perms = Perms()
        app.state.permissions = perms
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield Rig(c, app, undo, purger, perms)


async def _keep(rig: Rig, kind: str) -> str:
    item = await rig.undo.keep(UID, kind, "A note from 3 Nov", {"ref": "n_000000000000"})  # type: ignore[arg-type]
    return item.id


@pytest.mark.parametrize("kind", ["note", "thing", "vault_item"])
async def test_without_passkeys_in_dev_remove_now_works_and_binds_the_bin_id(
    rig: Rig, kind: str
) -> None:
    uid = await _keep(rig, kind)
    r = await rig.client.request("DELETE", f"/v1/deleted/{uid}", headers=H)
    assert r.status_code == 200, r.text
    assert rig.purger.purged == [uid]
    assert rig.perms.seen == [("privacy_delete", uid, None)]


@pytest.mark.parametrize("kind", ["note", "thing", "vault_item"])
async def test_with_passkeys_in_force_no_proof_is_refused_and_nothing_goes(
    rig: Rig, kind: str
) -> None:
    rig.perms.in_force = True
    uid = await _keep(rig, kind)
    r = await rig.client.request("DELETE", f"/v1/deleted/{uid}", headers=H)
    assert r.status_code == 403 and r.json()["error"] == "passkey_required"
    assert rig.purger.purged == []
    assert await rig.undo.get(UID, uid) is not None


async def test_with_a_proof_made_for_this_entry_it_goes(rig: Rig) -> None:
    rig.perms.in_force = True
    uid = await _keep(rig, "note")
    proof = PROOF
    r = await rig.client.request("DELETE", f"/v1/deleted/{uid}", headers=H, json={"proof": proof})
    assert r.status_code == 200, r.text
    assert rig.purger.purged == [uid]
    purpose, target, seen = rig.perms.seen[-1]
    assert (purpose, target) == ("privacy_delete", uid) and seen is not None
    entries = [e for e in rig.app.state.gateway.audit._entries if e.tool == "deleted_purge"]
    assert entries and "passkey pk_1" in entries[-1].detail


async def test_a_rejected_proof_is_refused(rig: Rig) -> None:
    rig.perms.in_force = True
    rig.perms.fail = PasskeyRejected("other_action", "That check was for something else.")
    uid = await _keep(rig, "thing")
    proof = PROOF
    r = await rig.client.request("DELETE", f"/v1/deleted/{uid}", headers=H, json={"proof": proof})
    assert r.status_code == 403 and r.json()["error"] == "passkey_rejected"
    assert rig.purger.purged == []


async def test_unreadable_passkeys_fail_closed(rig: Rig) -> None:
    rig.perms.in_force = True
    rig.perms.fail = PasskeyDataUnreadable()
    uid = await _keep(rig, "vault_item")
    proof = PROOF
    r = await rig.client.request("DELETE", f"/v1/deleted/{uid}", headers=H, json={"proof": proof})
    assert r.status_code == 503 and rig.purger.purged == []


async def test_google_sign_in_mode_without_a_fresh_sign_in_is_refused(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jarvis.api.deleted as mod
    from jarvis.api.auth import require_auth

    uid = await _keep(rig, "note")
    s = rig.app.state.settings
    rig.app.state.settings = s.model_copy(update={"auth_mode": AuthMode.GOOGLE})
    left = {"s": 0}
    monkeypatch.setattr(mod, "fresh_sign_in_left", lambda request, settings: left["s"])
    rig.app.dependency_overrides[require_auth] = lambda: None
    r = await rig.client.request("DELETE", f"/v1/deleted/{uid}", headers=H)
    assert r.status_code == 403
    assert r.json()["error"] == "proof_required" and r.json()["reason"] == "reauth"
    assert rig.purger.purged == []
    left["s"] = 120  # signed in again a minute ago
    r = await rig.client.request("DELETE", f"/v1/deleted/{uid}", headers=H)
    assert r.status_code == 200 and rig.purger.purged == [uid]


async def test_other_kinds_need_no_proof(rig: Rig) -> None:
    rig.perms.in_force = True
    uid = await _keep(rig, "event")
    r = await rig.client.request("DELETE", f"/v1/deleted/{uid}", headers=H)
    assert r.status_code == 200 and rig.purger.purged == [uid]
    assert rig.perms.seen == []


async def test_a_restored_entry_is_not_found_and_asks_for_nothing(rig: Rig) -> None:
    rig.perms.in_force = True
    uid = await _keep(rig, "note")
    await rig.undo.store.settle(UID, uid, restored_id="n_000000000000", now=rig.undo.now())
    r = await rig.client.request("DELETE", f"/v1/deleted/{uid}", headers=H)
    assert r.status_code == 404 and rig.perms.seen == [] and rig.purger.purged == []


async def test_an_unknown_or_malformed_id_is_not_found_without_a_proof(rig: Rig) -> None:
    rig.perms.in_force = True
    for bad in ("del_" + "0" * 20, "nope"):
        r = await rig.client.request("DELETE", f"/v1/deleted/{bad}", headers=H)
        assert r.status_code == 404
    assert rig.perms.seen == []


@pytest.mark.parametrize("env", ["prod", "staging"])
@pytest.mark.parametrize("kind", ["note", "thing", "vault_item"])
async def test_token_mode_outside_dev_needs_a_proof_even_without_passkeys(
    settings: Settings, env: str, kind: str
) -> None:
    """R2 review S2: with no passkey in force, only token-mode dev removes for good without a
    proof (as the vault's console-only rule). Token mode in prod or staging has no Google
    sign-in to stand in for one, so it is refused and nothing is purged."""
    undo = UndoBin(DeletedStore(MemoryDocs()))
    purger = Purger()
    undo.register(kind, Restorer(), purger)  # type: ignore[arg-type]
    token = "t" * 40
    s = settings.model_copy(
        update={"env": env, "api_token": SecretStr(token), "tools_enabled": True}
    )
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore(), undo=undo)
    async with app.router.lifespan_context(app):
        perms = Perms()  # no passkeys in force
        app.state.permissions = perms
        item = await undo.keep(UID, kind, "A note from 3 Nov", {"ref": "n_000000000000"})  # type: ignore[arg-type]
        bearer = {"Authorization": f"Bearer {token}", **H}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.request("DELETE", f"/v1/deleted/{item.id}", headers=bearer)
    assert r.status_code == 403, r.text
    assert r.json()["error"] == "proof_required" and r.json()["reason"] == "reauth"
    assert purger.purged == [] and await undo.get(UID, item.id) is not None
    assert perms.seen == [("privacy_delete", item.id, None)]


async def test_a_body_that_is_not_a_proof_is_refused(rig: Rig) -> None:
    uid = await _keep(rig, "note")
    r = await rig.client.request("DELETE", f"/v1/deleted/{uid}", headers=H, json={"x": 1})
    assert r.status_code == 422 and rig.purger.purged == []
