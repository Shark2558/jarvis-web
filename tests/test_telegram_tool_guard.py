# tests/test_telegram_tool_guard.py -- review slice 1 M1 / slice 3 #6: every READ tool the real,
# fully linked gateway registers is classified for Telegram. Either the private-reads patterns
# cover it (denied on Telegram unless the owner allows private reads), or it is named below as
# safe to answer on Telegram. A new tool therefore fails this test until someone decides.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from drive_fakes import FakeDrive, StaticTokens
from media_fakes import KEY, FakeGoogleKeyAPIs
from memory_fakes import rig as memory_rig
from people_fakes import FakePeople, people_connector
from pydantic import SecretStr
from telegram_fakes import UID, Clock
from web_fakes import FakeTavily

from jarvis.belongings.service import BelongingsService
from jarvis.belongings.store import BelongingsStore
from jarvis.config import get_settings
from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ActionRisk
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.drive.client import DriveClient
from jarvis.drive.roots import RootsStore
from jarvis.drive.service import DriveService
from jarvis.integrations.google_key import GoogleKeyClient
from jarvis.kb.service import NotesService
from jarvis.kb.store import NotesStore
from jarvis.keyring import Keyring
from jarvis.llm.base import ToolCall
from jarvis.media.service import MediaServices, YouTubeService
from jarvis.places.service import MapsService
from jarvis.places.store import MapsPlaces
from jarvis.quota.ledger import QuotaLedger
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.rules import PRIVATE_PATTERNS, ChannelRules, wrap_rules
from jarvis.telegram.store import TelegramStore
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect
from jarvis.tools.setup import build_gateway
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.vault.crypto import VaultCrypto
from jarvis.vault.service import VaultService
from jarvis.vault.store import VaultStore
from jarvis.web.allowance import WebAllowance
from jarvis.web.service import WebService
from jarvis.web.tavily import TavilyProvider

R1 = ActionRisk.READ_ONLY

# Reads that are safe to answer on Telegram: the owner's own lists and facts, public look-ups, or
# an answer shaped to carry no titles / locations / subjects.
TELEGRAM_SAFE = frozenset(
    {
        "calendar_free_slots",  # times only
        "calendar_list_events",  # the owner's own calendar
        "family_free_slots",  # member names and times only: no titles, no locations
        "gmail_track_packages",  # shaped: status only unless private reads are on
        "grocery_list",  # the owner's own list
        "list_tasks",
        "tasks_list",
        "reminders_list",
        "memory_search",  # the owner's own memory
        "whatsapp_draft",  # a draft of the owner's own words
        "maps_search",
        "maps_route",
        "youtube_search",
        "youtube_my_playlists",
        "youtube_playlist",
        "web_read",  # public pages
        "web_search",
    }
)


class DriveTokens(StaticTokens):
    async def email(self) -> str:
        return "jarvis-run@proj-123.iam.gserviceaccount.com"


async def linked_gateway(undo: UndoBin | None = None) -> Gateway:
    google = await people_connector(FakePeople())
    docs = MemoryDocs()
    files = DocumentService(AttachmentStore(MemoryDocs()))
    drive = DriveService(
        DriveClient(DriveTokens(), http=FakeDrive().client()),
        RootsStore(MemoryDocs()),
        extract=files.extract,
    )
    client = GoogleKeyClient(SecretStr(KEY), http=FakeGoogleKeyAPIs().client())
    ledger = QuotaLedger(docs)
    media = MediaServices(
        client=client,
        ledger=ledger,
        maps=MapsService(client, ledger, MapsPlaces(docs)),
        youtube=YouTubeService(client, ledger, google=google),
    )
    web = WebService(
        TavilyProvider(SecretStr("tvly-k"), http=FakeTavily().client()),
        WebAllowance(MemoryDocs(), now=lambda: datetime(2026, 11, 15, tzinfo=UTC)),
    )
    ring = Keyring(bytes(range(1, 33)))
    undo = undo if undo is not None else UndoBin(DeletedStore(MemoryDocs()))
    crypto = VaultCrypto(ring)
    return build_gateway(
        get_settings(),
        google=google,
        memory=memory_rig().svc,
        web=web,
        documents=files,
        undo=undo,
        drive=drive,
        media=media,
        docs=docs,
        # R2 I1: the vault list, notes and things (the second private group, D12)
        vault=VaultService(VaultStore(docs, crypto), crypto, undo=undo),
        notes=NotesService(NotesStore(docs, ring), web=web, undo=undo),
        belongings=BelongingsService(BelongingsStore(docs, ring), undo),
    )


def read_tools(gw: Gateway) -> list[str]:
    out = []
    for spec in gw.registry.specs():
        tool = gw.registry.get(spec.name)
        if tool is not None and tool.risk is R1:
            out.append(spec.name)
    return sorted(out)


async def denied_on_telegram(names: list[str]) -> set[str]:
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=Clock())
    rules = ChannelRules(None, store)  # nothing paired: private reads are off
    with telegram_turn():
        got = await rules.rules_for(UID)
    return {n for n in names if any(r.effect is Effect.DENY and r.matches(n, {}, R1) for r in got)}


async def test_every_read_tool_is_either_private_or_named_safe_for_telegram() -> None:
    reads = read_tools(await linked_gateway())
    assert len(reads) > 20  # the linked gateway really is whole
    private = await denied_on_telegram(reads)
    unclassified = [n for n in reads if n not in private and n not in TELEGRAM_SAFE]
    assert unclassified == [], (
        "classify these read tools for Telegram: add a pattern to telegram.rules.PRIVATE_PATTERNS "
        f"or name them in TELEGRAM_SAFE: {unclassified}"
    )


async def test_the_safe_list_has_no_stale_or_doubly_classified_names() -> None:
    reads = read_tools(await linked_gateway())
    private = await denied_on_telegram(reads)
    assert TELEGRAM_SAFE <= set(reads), sorted(TELEGRAM_SAFE - set(reads))
    assert not TELEGRAM_SAFE & private, sorted(TELEGRAM_SAFE & private)


@pytest.mark.parametrize(
    "tool", ["family_calendar_events", "deleted_list", "gmail_search", "drive_read", "doc_read"]
)
async def test_private_titles_are_denied_on_telegram_by_default(tool: str) -> None:
    assert await denied_on_telegram([tool]) == {tool}


def test_the_patterns_are_not_a_catch_all() -> None:
    assert "*" not in PRIVATE_PATTERNS


R2_READS = (
    "vault_list",
    "vault_expiring",
    "kb_search",
    "kb_read",
    "belongings_where",
    "belongings_list",
    "belongings_history",
)


async def test_every_r2_read_is_registered_and_private_on_telegram() -> None:
    reads = read_tools(await linked_gateway())
    assert set(R2_READS) <= set(reads)
    assert await denied_on_telegram(list(R2_READS)) == set(R2_READS)


@pytest.mark.parametrize("tool", R2_READS)
async def test_gate_with_defaults_an_r2_read_is_refused_on_a_telegram_turn(tool: str) -> None:
    """R2 D12 gate: through the real gateway with the wired Telegram rules, nothing paired or
    switched on: the call is refused and audited as denied; nothing is read."""
    gw = await linked_gateway()
    gw.rules = wrap_rules(gw.rules, TelegramStore(MemoryDocs(), prefix="t_", clock=Clock()))
    args = {"item": "passport"} if tool in ("belongings_where", "belongings_history") else {}
    if tool == "kb_search":
        args = {"query": "plumber"}
    elif tool == "kb_read":
        args = {"id": "n_000000000000"}
    with telegram_turn():
        out = await gw.execute(ToolCall(id="t1", name=tool, arguments=args), scope=f"{UID}:tg")
    assert out.outcome is GatewayOutcome.DENIED, (tool, out.error)
    assert "Telegram" in (out.error or "")


# ---- Recently deleted on Telegram (R2 integrated review H1 / S1) --------------------------------
# deleted_list needs the first switch, and shows vault documents, notes and things only when the
# second is on too; deleted_restore (any kind) needs both. Through the real gateway.
SWITCHES = [(False, False), (True, False), (False, True), (True, True)]
EVERY_KIND = (
    ("event", "Dentist"),
    ("task", "Pay the bill"),
    ("vault_item", "A document"),
    ("note", "A note from 4 Nov"),
    ("thing", "A thing you noted"),
)


async def _switched(gw: Gateway, *, private: bool, personal: bool) -> None:
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=Clock())
    code, _ = await store.start_pairing(UID)
    await store.finish_pairing(code, tg_user_id=1, chat_id=2)
    await store.set_settings(UID, allow_private_reads=private, allow_personal_reads=personal)
    gw.rules = wrap_rules(gw.rules, store)


async def _bin_with_every_kind(undo: UndoBin) -> dict[str, str]:
    ids: dict[str, str] = {}
    for kind, title in EVERY_KIND:
        item = await undo.keep(UID, kind, title, {"ref": "x"}, owner_authored=True)  # type: ignore[arg-type]
        ids[kind] = item.id
    return ids


@pytest.mark.parametrize(("private", "personal"), SWITCHES)
async def test_gate_deleted_list_shows_r2_entries_only_with_both_switches(
    private: bool, personal: bool
) -> None:
    undo = UndoBin(DeletedStore(MemoryDocs()))
    gw = await linked_gateway(undo)
    await _switched(gw, private=private, personal=personal)
    await _bin_with_every_kind(undo)
    call = ToolCall(id="t1", name="deleted_list", arguments={})
    with telegram_turn():
        out = await gw.execute(call, scope=f"{UID}:tg")
    if not private:
        assert out.outcome is GatewayOutcome.DENIED and "Telegram" in (out.error or "")
        return
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    kinds = {i["kind"] for i in out.result["items"]}
    if personal:
        assert kinds == {"event", "to-do", "vault document", "note", "thing"}
        assert "note" not in out.result
    else:
        assert kinds == {"event", "to-do"}
        assert "Telegram" in out.result["note"] and "3" not in out.result["note"]
        blob = str(out.result)
        assert "A document" not in blob and "A note from" not in blob and "A thing" not in blob


async def test_off_telegram_deleted_list_shows_every_kind() -> None:
    undo = UndoBin(DeletedStore(MemoryDocs()))
    gw = await linked_gateway(undo)
    await _switched(gw, private=False, personal=False)
    await _bin_with_every_kind(undo)
    out = await gw.execute(ToolCall(id="t1", name="deleted_list", arguments={}), scope=f"{UID}:s")
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert len(out.result["items"]) == len(EVERY_KIND) and "note" not in out.result


@pytest.mark.parametrize(("private", "personal"), SWITCHES)
@pytest.mark.parametrize("kind", ["event", "note", "vault_item", "thing"])
async def test_gate_deleted_restore_needs_both_switches_on_telegram(
    private: bool, personal: bool, kind: str
) -> None:
    undo = UndoBin(DeletedStore(MemoryDocs()))
    gw = await linked_gateway(undo)
    await _switched(gw, private=private, personal=personal)
    ids = await _bin_with_every_kind(undo)
    call = ToolCall(id="t2", name="deleted_restore", arguments={"undo_id": ids[kind]})
    with telegram_turn():
        out = await gw.execute(call, scope=f"{UID}:tg")
    if private and personal:
        assert out.outcome is not GatewayOutcome.DENIED, out.error
        return
    assert out.outcome is GatewayOutcome.DENIED, (kind, out.outcome)
    assert "Telegram" in (out.error or "") and "both" in (out.error or "")
    item = await undo.get(UID, ids[kind])
    assert item is not None and not item.restored and item.restoring_since is None
