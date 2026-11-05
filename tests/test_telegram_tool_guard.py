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

from jarvis.config import get_settings
from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ActionRisk
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.drive.client import DriveClient
from jarvis.drive.roots import RootsStore
from jarvis.drive.service import DriveService
from jarvis.integrations.google_key import GoogleKeyClient
from jarvis.media.service import MediaServices, YouTubeService
from jarvis.places.service import MapsService
from jarvis.places.store import MapsPlaces
from jarvis.quota.ledger import QuotaLedger
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.rules import PRIVATE_PATTERNS, ChannelRules
from jarvis.telegram.store import TelegramStore
from jarvis.tools.gateway import Gateway
from jarvis.tools.policy import Effect
from jarvis.tools.setup import build_gateway
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
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


async def linked_gateway() -> Gateway:
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
    return build_gateway(
        get_settings(),
        google=google,
        memory=memory_rig().svc,
        web=web,
        documents=files,
        undo=UndoBin(DeletedStore(MemoryDocs())),
        drive=drive,
        media=media,
        docs=docs,
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
