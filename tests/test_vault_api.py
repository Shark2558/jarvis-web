# tests/test_vault_api.py -- R2 D6: owner-only routes, unlock, single-use tickets, console-only
from __future__ import annotations

import io
import zipfile
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from vault_fakes import JPEG, KEY, PDF, PNG, ring, scan

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.api.vault import VAULT_BODY_BYTES, VAULT_UPLOAD_PATH, install_vault
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.permissions.errors import PasskeyRejected, PasskeyRequired
from jarvis.storage.docs import MemoryDocs
from jarvis.vault.crypto import VaultCrypto
from jarvis.vault.service import VaultService
from jarvis.vault.store import VaultStore
from jarvis.vault.unlock import UnlockStore

OWNER = "akash@example.com"
OTHER = "partner@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
UID = user_id_for_email(OWNER)
_ = KEY


class Audit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.fail = False

    async def append(self, **kw: Any) -> None:
        if self.fail:
            raise RuntimeError("audit down")
        self.rows.append(kw)


class Perms:
    """A permissions stand-in: passkeys in force or not."""

    def __init__(self, in_force: bool = False) -> None:
        self.in_force = in_force
        self.calls: list[tuple[str, Any, Any]] = []
        self.verdict: Exception | None = None

    async def passkey_required(self, uid: str) -> bool:
        return self.in_force

    async def check_purpose(self, uid: str, purpose: str, target: Any, proof: Any) -> str | None:
        self.calls.append((purpose, target, proof))
        if not self.in_force:
            return None
        if self.verdict is not None:
            raise self.verdict
        if proof is None:
            raise PasskeyRequired("Use your passkey.")
        return "passkey abcd1234"


class Rig:
    def __init__(self, c: AsyncClient, app: Any, docs: MemoryDocs, audit: Audit, perms: Perms):
        self.c, self.app, self.docs, self.audit, self.perms = c, app, docs, audit, perms


@pytest.fixture
def gsettings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER, OTHER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
            "token_key": SecretStr(KEY_B64),
        }
    )


@pytest.fixture
async def rig(gsettings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        docs, audit, perms = MemoryDocs(), Audit(), Perms()
        crypto = VaultCrypto(ring())
        bin_ = SimpleNamespace()

        async def keep(uid: str, kind: str, title: str, snap: dict[str, Any], **_: Any) -> Any:
            return SimpleNamespace(id="del_" + "0" * 20)

        async def discard(uid: str, item_id: str) -> None:
            return None

        bin_.keep, bin_.discard = keep, discard
        app.state.vault = VaultService(VaultStore(docs, crypto), crypto, undo=bin_)
        app.state.vault_unlock = UnlockStore(docs, ring(), minutes=10)
        app.state.permissions = perms
        app.state.gateway = SimpleNamespace(audit=audit)
        install_vault(app)
        monkeypatch.setattr("jarvis.api.vault.fresh_sign_in_left", lambda r, s: 240)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield Rig(c, app, docs, audit, perms)


async def login(c: AsyncClient, email: str = OWNER) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": email, "email_verified": True, "sub": email}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await c.get("/auth/callback?code=a&state=b")).status_code in (302, 307)


async def upload(c: AsyncClient, data: bytes = PDF, qs: str = "") -> Any:
    return await c.post(f"{VAULT_UPLOAD_PATH}{qs}", content=data, headers=CSRF)


async def unlock(c: AsyncClient) -> str:
    r = await c.post("/v1/vault/unlock", json={}, headers=CSRF)
    assert r.status_code == 200, r.text
    return str(r.json()["token"])


async def ticket(c: AsyncClient, token: str, item: dict[str, Any]) -> str:
    r = await c.post(
        f"/v1/vault/items/{item['id']}/files/{item['files'][0]['fid']}/ticket",
        headers={**CSRF, "X-Jarvis-Vault": token},
    )
    assert r.status_code == 200, r.text
    assert r.json()["expires_in_s"] == 60
    return str(r.json()["ticket"])


def test_constants() -> None:
    assert VAULT_UPLOAD_PATH == "/v1/vault/upload" and VAULT_BODY_BYTES == 10 * 1024 * 1024 + 65536


async def test_every_route_needs_the_owner(rig: Rig) -> None:
    c = rig.c
    for method, path in [
        ("GET", "/v1/vault"),
        ("POST", VAULT_UPLOAD_PATH),
        ("PATCH", "/v1/vault/items/v_000000000001"),
        ("DELETE", "/v1/vault/items/v_000000000001"),
        ("POST", "/v1/vault/holders"),
        ("PUT", "/v1/vault/settings"),
        ("POST", "/v1/vault/unlock"),
        ("POST", "/v1/vault/export/ticket"),
        ("GET", "/v1/vault/download/" + "a" * 30),
    ]:
        r = await c.request(method, path, headers=CSRF)
        assert r.status_code == 401, (method, path)


async def test_cookie_writes_need_the_csrf_header(rig: Rig) -> None:
    await login(rig.c)
    assert (await rig.c.post(VAULT_UPLOAD_PATH, content=PDF)).status_code in (400, 403)
    assert (await rig.c.post("/v1/vault/unlock", json={})).status_code in (400, 403)


async def test_view_shape_and_unlock_requirement(rig: Rig) -> None:
    await login(rig.c)
    body = (await rig.c.get("/v1/vault")).json()
    assert (
        body["available"]
        and body["items"] == []
        and body["unlock"]
        == {
            "required": "sign_in",
            "console": True,
        }
    )
    assert body["totals"] == {"items": 0, "max_items": 100, "mb": 0.0, "limit_mb": 150}
    rig.perms.in_force = True
    assert (await rig.c.get("/v1/vault")).json()["unlock"]["required"] == "passkey"


async def test_without_a_vault_it_says_why(rig: Rig) -> None:
    await login(rig.c)
    rig.app.state.vault = None
    body = (await rig.c.get("/v1/vault")).json()
    assert body["available"] is False and "no encryption key" in body["reason"]
    assert (
        await rig.c.post("/v1/vault/holders", json={"label": "A"}, headers=CSRF)
    ).status_code == 503


async def test_upload_returns_item_and_proposal_and_stores_ciphertext(rig: Rig) -> None:
    await login(rig.c)
    rig.app.state.vault._extract = None
    r = await upload(rig.c, PDF + b"NEEDLE-ID-9988" * 10)
    assert r.status_code == 201
    body = r.json()
    assert body["duplicate"] is False and body["item"]["needs_check"] is True
    assert set(body["item"]["files"][0]) == {"fid", "mime", "size"}
    assert not scan(rig.docs, b"NEEDLE-ID-9988")
    again = await upload(rig.c, PDF + b"NEEDLE-ID-9988" * 10)
    assert again.status_code == 200 and again.json()["duplicate"] is True


async def test_upload_refusals_are_plain_words(rig: Rig) -> None:
    await login(rig.c)
    r = await upload(rig.c, b"GIF89a....")
    assert r.status_code == 415 and set(r.json()) == {"error", "detail"}
    assert (await upload(rig.c, b"")).status_code == 422
    big = await rig.c.post(
        VAULT_UPLOAD_PATH, content=b"%PDF-" + b"0" * (10 * 1024 * 1024), headers=CSRF
    )
    assert big.status_code == 413 and big.json()["error"] == "too_large"
    assert (await upload(rig.c, PDF, "?type=spaceship")).status_code == 422
    assert (await upload(rig.c, PDF, "?item=v_000000000099")).status_code == 404
    assert (await upload(rig.c, PDF, "?holder=h_00000000")).status_code == 422


async def test_second_file_by_item_query_and_type_hint(rig: Rig) -> None:
    await login(rig.c)
    first = (await upload(rig.c, PDF, "?type=passport")).json()["item"]
    assert first["type"] == "passport"
    second = (await upload(rig.c, JPEG, f"?item={first['id']}")).json()["item"]
    assert len(second["files"]) == 2
    assert (await upload(rig.c, PNG, f"?item={first['id']}")).status_code == 409


async def test_upload_is_rate_limited(rig: Rig) -> None:
    await login(rig.c)
    codes = [(await upload(rig.c, PDF + str(n).encode())).status_code for n in range(8)]
    assert codes[:6] == [201] * 6 and codes[6:] == [429, 429]


async def test_patch_delete_holders_settings(rig: Rig) -> None:
    await login(rig.c)
    item = (await upload(rig.c, PDF, "?type=driving_licence")).json()["item"]
    r = await rig.c.patch(
        f"/v1/vault/items/{item['id']}",
        json={"expires_on": "2034-03-14", "last4": "3456", "confirm": True},
        headers=CSRF,
    )
    assert r.status_code == 200 and r.json()["ends"] == "••3456"
    bad = await rig.c.patch(f"/v1/vault/items/{item['id']}", json={"last4": "123456"}, headers=CSRF)
    assert bad.status_code == 422 and "only the last 4" in bad.json()["detail"]
    unknown = await rig.c.patch(f"/v1/vault/items/{item['id']}", json={"sha": 1}, headers=CSRF)
    assert unknown.status_code == 422
    h = (await rig.c.post("/v1/vault/holders", json={"label": "Anjali"}, headers=CSRF)).json()
    assert h["label"] == "Anjali"
    s = await rig.c.put("/v1/vault/settings", json={"alert_detail": "type"}, headers=CSRF)
    assert s.json()["alert_detail"] == "type"
    assert (
        await rig.c.put("/v1/vault/settings", json={"alert_detail": "x"}, headers=CSRF)
    ).status_code == 422
    d = await rig.c.delete(f"/v1/vault/items/{item['id']}", headers=CSRF)
    assert d.status_code == 200 and d.json()["undo_id"].startswith("del_")
    assert d.json()["kind"] == "vault_item"
    assert (await rig.c.get("/v1/vault")).json()["items"] == []
    gone = await rig.c.delete(f"/v1/vault/holders/{h['id']}", headers=CSRF)
    assert gone.json() == {"removed": h["id"]}
    assert (await rig.c.delete("/v1/vault/holders/nope", headers=CSRF)).status_code == 404


async def test_another_owner_gets_404_not_the_item(rig: Rig) -> None:
    await login(rig.c)
    item = (await upload(rig.c)).json()["item"]
    await login(rig.c, OTHER)
    assert (await rig.c.get("/v1/vault")).json()["items"] == []
    r = await rig.c.patch(f"/v1/vault/items/{item['id']}", json={"title": "x"}, headers=CSRF)
    assert r.status_code == 404
    assert (await rig.c.delete(f"/v1/vault/items/{item['id']}", headers=CSRF)).status_code == 404
    token = await unlock(rig.c)
    t = await rig.c.post(
        f"/v1/vault/items/{item['id']}/files/{item['files'][0]['fid']}/ticket",
        headers={**CSRF, "X-Jarvis-Vault": token},
    )
    assert t.status_code == 404


async def test_a_bearer_token_can_never_unlock_or_download(rig: Rig) -> None:
    await login(rig.c)
    item = (await upload(rig.c)).json()["item"]
    token = await unlock(rig.c)
    t = await ticket(rig.c, token, item)
    rig.c.cookies.clear()
    r = await rig.c.post("/v1/vault/unlock", json={}, headers=BEARER)
    assert r.status_code == 403 and r.json()["error"] == "console_only"
    r = await rig.c.post("/v1/vault/export/ticket", headers={**BEARER, "X-Jarvis-Vault": token})
    assert r.json()["error"] == "console_only"
    r = await rig.c.get(f"/v1/vault/download/{t}", headers=BEARER)
    assert r.status_code == 403 and r.json()["error"] == "console_only"
    assert (await rig.c.get("/v1/vault", headers=BEARER)).json()["unlock"]["console"] is False


async def test_unlock_needs_a_recent_sign_in_without_passkeys(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await login(rig.c)
    monkeypatch.setattr("jarvis.api.vault.fresh_sign_in_left", lambda r, s: 0)
    r = await rig.c.post("/v1/vault/unlock", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "reauth_required"
    assert r.json()["reason"] == "reauth"


async def test_unlock_with_passkeys_in_force(rig: Rig) -> None:
    await login(rig.c)
    rig.perms.in_force = True
    r = await rig.c.post("/v1/vault/unlock", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "passkey_required"
    rig.perms.verdict = PasskeyRejected("replayed", "That check was already used.")
    r = await rig.c.post("/v1/vault/unlock", json={}, headers=CSRF)
    assert r.json() == {
        "error": "passkey_rejected",
        "detail": "That check was already used.",
        "reason": "replayed",
    }
    assert [c[0] for c in rig.perms.calls] == ["vault_unlock", "vault_unlock"]
    rig.perms.verdict = None
    proof = {
        "challenge_id": "c" * 32,
        "credential": {
            "id": "abc",
            "rawId": "abc",
            "type": "public-key",
            "response": {
                "clientDataJSON": "AAAA",
                "authenticatorData": "AAAA",
                "signature": "AAAA",
            },
        },
    }
    ok = await rig.c.post("/v1/vault/unlock", json={"proof": proof}, headers=CSRF)
    assert ok.status_code == 200, ok.text
    assert rig.perms.calls[-1][2] is not None
    assert [r["tool"] for r in rig.audit.rows][-1] == "vault_unlock"


async def test_download_flow_headers_single_use_and_audit(rig: Rig) -> None:
    await login(rig.c)
    data = PDF + b"payload" * 200
    item = (await upload(rig.c, data, "?type=passport")).json()["item"]
    token = await unlock(rig.c)
    assert not scan(rig.docs, token)
    t = await ticket(rig.c, token, item)
    r = await rig.c.get(f"/v1/vault/download/{t}")
    assert r.status_code == 200 and r.content == data
    h = r.headers
    assert h["content-disposition"] == 'attachment; filename="passport-you-1.pdf"'
    assert h["cache-control"] == "no-store" and h["x-content-type-options"] == "nosniff"
    assert h["content-type"] == "application/pdf"
    used = await rig.c.get(f"/v1/vault/download/{t}")
    assert used.status_code == 410 and used.json()["error"] == "gone"
    tools = [(r["tool"], r["agent"]) for r in rig.audit.rows]
    assert ("vault_unlock", "owner") in tools and ("vault_open", "owner") in tools
    row = next(r for r in rig.audit.rows if r["tool"] == "vault_open")
    assert row["args"] == {"item": item["id"], "file": item["files"][0]["fid"]}


async def test_ticket_needs_the_unlock_token_and_a_real_file(rig: Rig) -> None:
    await login(rig.c)
    item = (await upload(rig.c)).json()["item"]
    path = f"/v1/vault/items/{item['id']}/files/{item['files'][0]['fid']}/ticket"
    r = await rig.c.post(path, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "locked"
    r = await rig.c.post(path, headers={**CSRF, "X-Jarvis-Vault": "wrong"})
    assert r.status_code == 403
    token = await unlock(rig.c)
    r = await rig.c.post(
        f"/v1/vault/items/{item['id']}/files/f_000000000000/ticket",
        headers={**CSRF, "X-Jarvis-Vault": token},
    )
    assert r.status_code == 404
    await rig.c.delete("/v1/vault/unlock", headers=CSRF)
    assert (await rig.c.post(path, headers={**CSRF, "X-Jarvis-Vault": token})).status_code == 403


async def test_a_ticket_made_for_one_owner_is_gone_for_another(rig: Rig) -> None:
    await login(rig.c)
    item = (await upload(rig.c)).json()["item"]
    t = await ticket(rig.c, await unlock(rig.c), item)
    await login(rig.c, OTHER)
    assert (await rig.c.get(f"/v1/vault/download/{t}")).status_code == 410


async def test_nothing_is_sent_when_the_audit_cannot_be_written(rig: Rig) -> None:
    await login(rig.c)
    item = (await upload(rig.c)).json()["item"]
    t = await ticket(rig.c, await unlock(rig.c), item)
    rig.audit.fail = True
    r = await rig.c.get(f"/v1/vault/download/{t}")
    assert r.status_code == 503 and PDF[:5] not in r.content
    rig.audit.fail = True
    assert (await rig.c.post("/v1/vault/unlock", json={}, headers=CSRF)).status_code == 503


async def test_bad_ticket_shapes_are_gone_not_errors(rig: Rig) -> None:
    await login(rig.c)
    for t in ("short", "x" * 300, "a b" + "c" * 30):
        assert (await rig.c.get(f"/v1/vault/download/{t}")).status_code in (404, 410)


async def test_export_zip_through_a_ticket(rig: Rig) -> None:
    await login(rig.c)
    await upload(rig.c, PDF, "?type=passport")
    await upload(rig.c, JPEG, "?type=pan")
    token = await unlock(rig.c)
    t = (
        await rig.c.post("/v1/vault/export/ticket", headers={**CSRF, "X-Jarvis-Vault": token})
    ).json()["ticket"]
    r = await rig.c.get(f"/v1/vault/download/{t}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'filename="jarvis-vault.zip"' in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert sorted(zf.namelist()) == ["pan-you-1.jpg", "passport-you-1.pdf", "vault.json"]
    assert any(x["tool"] == "vault_export" and x["args"] == {"files": 2} for x in rig.audit.rows)


async def test_a_corrupt_file_is_a_503_and_never_partial(rig: Rig) -> None:
    await login(rig.c)
    item = (await upload(rig.c)).json()["item"]
    t = await ticket(rig.c, await unlock(rig.c), item)
    for p in [p for p in rig.docs._data if "vault_chunks" in p]:
        rig.docs._data[p]["blob"] = rig.docs._data[p]["blob"][:-8] + "AAAAAAAA"
    r = await rig.c.get(f"/v1/vault/download/{t}")
    assert r.status_code == 503 and r.json()["error"] == "unavailable"


async def test_the_panel_opening_runs_todays_reminders(rig: Rig) -> None:
    await login(rig.c)
    calls: list[str] = []

    class R:
        async def check(self, uid: str) -> int:
            calls.append(uid)
            return 0

    rig.app.state.vault_reminders = R()
    await rig.c.get("/v1/vault")
    assert calls == [UID]
