# tests/test_r2_bin_wipe.py -- R2 integrated review H2: deleting a whole category from the privacy
# dashboard (notes, the vault, things) also clears that category's Recently deleted entries (one
# shared helper over the public UndoBin API); a restore whose item is gone for good is a plain
# "It's gone" (404 not_found), never a 502; the vault's bin title names no document type.
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest
from belongings_fakes import things
from httpx import ASGITransport, AsyncClient
from kb_fakes import build_rig
from vault_fakes import PDF, make

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.undo.service import MSG_GONE, Gone, UndoBin, discard_kind
from jarvis.undo.store import DeletedStore
from jarvis.undo.tools import undo_tools
from jarvis.vault.service import VAULT_BIN_TITLE, VaultPurger, VaultRestorer

H = {"X-Requested-With": "JARVIS"}


@dataclass
class Kind:
    """One R2 kind: its service, its bin, and how to make / delete / wipe one item."""

    uid: str
    undo: UndoBin
    remove: Callable[[], Awaitable[str]]  # makes one item, deletes it, returns the bin id
    wipe: Callable[[], Awaitable[int]]


async def _note() -> Kind:
    r = build_rig()
    from kb_fakes import UID

    async def remove() -> str:
        n = await r.svc.add(UID, kind="note", text="the spare key is with Neha", origin="typed")
        return (await r.svc.remove(UID, n.id)).id

    return Kind(UID, r.undo, remove, lambda: r.svc.wipe(UID))


async def _vault() -> Kind:
    from vault_fakes import UID

    undo = UndoBin(DeletedStore(MemoryDocs()))
    svc, _, _ = make(undo=undo)
    undo.register("vault_item", VaultRestorer(svc), VaultPurger(svc))

    async def remove() -> str:
        item = (await svc.add_file(UID, PDF, type_hint="passport")).item
        return await svc.remove(UID, item.id)

    return Kind(UID, undo, remove, lambda: svc.wipe(UID))


async def _thing() -> Kind:
    from belongings_fakes import UID

    t = things()

    async def remove() -> str:
        await t.svc.put(UID, "Keys", "hook")
        return (await t.svc.remove(UID, "keys"))[1].id

    return Kind(UID, t.undo, remove, lambda: t.svc.wipe(UID))


KINDS: dict[str, Callable[[], Awaitable[Kind]]] = {
    "note": _note,
    "vault_item": _vault,
    "thing": _thing,
}


@pytest.mark.parametrize("kind", list(KINDS))
async def test_wipe_clears_bin_entries(kind: str) -> None:
    k = await KINDS[kind]()
    await k.remove()
    other = await k.undo.keep(k.uid, "event", "Dentist", {"ref": "e"})  # not ours to touch
    stranger = await k.undo.keep("u_someone_else", kind, "A thing", {"ref": "x"})  # type: ignore[arg-type]
    await k.wipe()
    assert [i.id for i in await k.undo.recent(k.uid)] == [other.id]
    assert await k.undo.get("u_someone_else", stranger.id) is not None


@pytest.mark.parametrize("kind", list(KINDS))
async def test_restore_of_a_wiped_item_says_it_is_gone_and_drops_the_entry(kind: str) -> None:
    k = await KINDS[kind]()
    bin_id = await k.remove()
    entry = await k.undo.get(k.uid, bin_id)
    assert entry is not None
    await k.wipe()
    await k.undo.store.add(entry)  # an entry the wipe could not clear (say, the bin was down)
    with pytest.raises(Gone) as e:
        await k.undo.restore(k.uid, bin_id)
    assert str(e.value) == MSG_GONE
    assert await k.undo.get(k.uid, bin_id) is None  # nothing can ever bring it back: dropped


async def test_the_vault_bin_title_names_no_document_type() -> None:
    from vault_fakes import UID

    undo = UndoBin(DeletedStore(MemoryDocs()))
    svc, _, _ = make(undo=undo)
    item = (await svc.add_file(UID, PDF, type_hint="passport")).item
    await svc.remove(UID, item.id)
    (entry,) = await undo.recent(UID)
    assert entry.title == VAULT_BIN_TITLE == "A document"
    assert "passport" not in entry.model_dump_json().lower()


# ---- the shared helper ---------------------------------------------------------------------------


async def test_discard_kind_drops_only_that_kind_of_that_owner_and_counts() -> None:
    undo = UndoBin(DeletedStore(MemoryDocs()))
    for kind in ("note", "note", "thing"):
        await undo.keep("u1", kind, "x", {"ref": "r"})  # type: ignore[arg-type]
    await undo.keep("u2", "note", "x", {"ref": "r"})
    assert await discard_kind(undo, "u1", "note") == 2
    assert [i.kind for i in await undo.recent("u1")] == ["thing"]
    assert len(await undo.recent("u2")) == 1


async def test_discard_kind_never_raises_and_accepts_no_bin() -> None:
    assert await discard_kind(None, "u1", "note") == 0

    class Down:
        async def recent(self, uid: str) -> list[Any]:
            raise RuntimeError("firestore down")

    assert await discard_kind(Down(), "u1", "note") == 0  # type: ignore[arg-type]


async def test_vault_wipe_still_works_when_the_bin_cannot_be_listed() -> None:
    from vault_fakes import UID, Bin

    svc, _, _ = make(undo=Bin())  # a stand-in with no `recent`
    await svc.add_file(UID, PDF)
    assert await svc.wipe(UID) == 1


# ---- the tool and the API -----------------------------------------------------------------------


class GoneRestorer:
    async def restore(self, uid: str, item: Any, *, outside: bool = False) -> Any:
        raise Gone()


async def test_the_restore_tool_says_it_is_gone_in_plain_words() -> None:
    undo = UndoBin(DeletedStore(MemoryDocs()))
    undo.register("note", GoneRestorer())
    reg = ToolRegistry()
    for t in undo_tools(undo):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    entry = await undo.keep("owner", "note", "A note from 4 Nov", {"ref": "n_000000000000"})
    call = ToolCall(id="r1", name="deleted_restore", arguments={"undo_id": entry.id})
    out = await gw.execute(call, scope="owner:s")
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert out.result == {"restored": False, "status": "gone", "message": MSG_GONE}


async def test_restore_of_a_missing_target_is_404_not_502(settings: Settings) -> None:
    undo = UndoBin(DeletedStore(MemoryDocs()))
    undo.register("note", GoneRestorer())
    s = settings.model_copy(update={"tools_enabled": True})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore(), undo=undo)
    async with app.router.lifespan_context(app):
        entry = await undo.keep("owner", "note", "A note from 4 Nov", {"ref": "n_000000000000"})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/v1/deleted/{entry.id}/restore", headers=H)
    assert r.status_code == 404, r.text
    assert r.json() == {"error": "not_found", "detail": MSG_GONE}
    assert await undo.get("owner", entry.id) is None
