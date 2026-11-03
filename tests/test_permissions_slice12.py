# tests/test_permissions_slice12.py — slice 12 D8: the permission rows for the five integrations
# (Drive, Maps, YouTube, Contacts, WhatsApp drafts): R1, Allow / Ask first / Never, plain-English
# labels, a sensible order. The matrix runs the REAL registered tools — all of slice 12, wired by
# build_gateway with Google linked, Drive configured and the server's API key — over in-memory
# fakes of the People, Drive and Maps / YouTube APIs; every registered slice 12 tool falls in
# exactly one row.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from drive_fakes import FakeDrive, StaticTokens
from media_fakes import KEY, FakeGoogleKeyAPIs
from people_fakes import PEOPLE_UID, FakePeople, people_connector, person
from pydantic import SecretStr

from jarvis.config import get_settings
from jarvis.core.guardrails import ActionRisk
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.drive.client import DriveClient
from jarvis.drive.roots import RootsStore
from jarvis.drive.service import DriveService
from jarvis.integrations.google_key import GoogleKeyClient
from jarvis.media.service import MediaServices, YouTubeService
from jarvis.permissions.groups import GROUPS, group_ids, groups_for, rules_for, validate_choices
from jarvis.places.service import MapsService
from jarvis.places.store import MapsPlaces
from jarvis.quota.ledger import QuotaLedger
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.base import ToolCall
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, PolicyRule
from jarvis.tools.setup import build_gateway
from jarvis.tools.taint import context_trust

R1, R2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE
NEW = ("drive", "maps", "youtube", "contacts", "whatsapp")
# The tool names the plan gives each builder (docs/plans/phase2-slice12-integrations.md D1–D6).
PLANNED: dict[str, tuple[str, ...]] = {
    "drive": ("drive_folders", "drive_list", "drive_search", "drive_read"),
    "maps": ("maps_search", "maps_route"),
    "youtube": ("youtube_search", "youtube_my_playlists", "youtube_playlist"),
    "contacts": ("contacts_search",),
    "whatsapp": ("whatsapp_draft",),
}


def test_the_five_rows_read_as_planned() -> None:
    by_id = {g.id: g for g in GROUPS}
    want = {
        "drive": ("Drive", "Read your chosen Drive folders"),
        "maps": ("Maps", "Search places and travel times"),
        "youtube": ("YouTube", "Search YouTube and read your playlists"),
        "contacts": ("Contacts", "Look up your contacts"),
        "whatsapp": ("WhatsApp", "Write WhatsApp drafts"),
    }
    for gid, (section, label) in want.items():
        g = by_id[gid]
        assert (g.section, g.label) == (section, label)
        assert g.risk is R1 and not g.irreversible
        assert g.choices == (Effect.ALLOW, Effect.ASK, Effect.DENY) and g.default is Effect.ALLOW
        assert g.hint and "$" not in g.hint
    assert "Send" in by_id["whatsapp"].hint and "Nothing is sent" in by_id["whatsapp"].hint
    assert "Grant" in by_id["contacts"].hint and "Grant" in by_id["youtube"].hint
    assert "read only" in by_id["drive"].hint.lower()


def test_the_rows_sit_in_a_sensible_order() -> None:
    order = group_ids()
    # people: right after the Email rows; files after Documents; Maps and YouTube last
    assert order.index("email_send") < order.index("contacts") < order.index("whatsapp")
    assert order.index("whatsapp") < order.index("todo_change")
    assert order.index("documents") < order.index("drive") < order.index("maps")
    assert order.index("maps") < order.index("youtube") == len(order) - 1
    sections = [g.section for g in GROUPS]
    for s in set(sections):  # each section's rows are together (one heading each)
        first, last = sections.index(s), len(sections) - 1 - sections[::-1].index(s)
        assert set(sections[first : last + 1]) == {s}, s


@pytest.mark.parametrize("gid", NEW)
def test_each_planned_tool_lands_only_in_its_row(gid: str) -> None:
    for name in PLANNED[gid]:
        assert {g.id for g in groups_for(name, R1)} == {gid}, name


def test_no_older_row_matches_the_new_tools_and_no_new_row_the_older_ones() -> None:
    older = ("gmail_search", "web_search", "doc_read", "tasks_list", "calendar_list_events")
    for name in older:
        assert not {g.id for g in groups_for(name, R1)} & set(NEW), name


# ---- through the real gateway: every slice 12 tool, real, over in-memory fakes ----------------


class Rules:
    def __init__(self, choices: dict[str, Effect]) -> None:
        self.choices = choices

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return rules_for(self.choices)


OWNER_EMAIL = "akash@example.com"  # the owner people_connector links
SCOPE = f"{PEOPLE_UID}:s"  # the owner whose link and folders the fakes serve


class DriveTokens(StaticTokens):
    async def email(self) -> str:
        return "jarvis-run@proj-123.iam.gserviceaccount.com"


@dataclass
class Rig:
    gateway: Gateway
    people: FakePeople
    drive: FakeDrive
    keyed: FakeGoogleKeyAPIs

    def requests(self) -> int:
        """Every request any fake Google API has seen so far."""
        return len(self.people.requests) + len(self.drive.requests) + len(self.keyed.requests)


async def _real_gw(choices: dict[str, Effect]) -> Rig:
    people = FakePeople(contacts=[person("c1", "Ravi", phones=["98765 43210"])])
    google = await people_connector(people)
    d = FakeDrive()
    d.folder("root1", "Registry", shared_by=OWNER_EMAIL)
    d.file("doc1", "Steering notes", "root1", "Budget is four crore.")
    files = DocumentService(AttachmentStore(MemoryDocs()))
    drive = DriveService(
        DriveClient(DriveTokens(), http=d.client()), RootsStore(MemoryDocs()), extract=files.extract
    )
    await drive.set_use(PEOPLE_UID, OWNER_EMAIL, "root1", True)
    keyed = FakeGoogleKeyAPIs()
    client = GoogleKeyClient(SecretStr(KEY), http=keyed.client())
    docs = MemoryDocs()
    ledger = QuotaLedger(docs)
    media = MediaServices(
        client=client,
        ledger=ledger,
        maps=MapsService(client, ledger, MapsPlaces(docs)),
        youtube=YouTubeService(client, ledger, google=google),
    )
    gw = build_gateway(get_settings(), google=google, drive=drive, media=media)
    gw.rules = Rules(choices)
    return Rig(gw, people, d, keyed)


OUTCOME = {
    Effect.ALLOW: GatewayOutcome.EXECUTED,
    Effect.ASK: GatewayOutcome.AWAITING_CONFIRMATION,
    Effect.DENY: GatewayOutcome.DENIED,
}
CELLS = [(gid, name, e) for gid in NEW for name in PLANNED[gid] for e in Effect]
# Arguments each real tool accepts (a card that can't be written crashed the reply under "Ask
# first" once: review S2 — so every tool runs for real, never a stand-in)
REAL_ARGS: dict[str, dict[str, Any]] = {
    "drive_folders": {},
    "drive_list": {"folder": "root1"},
    "drive_search": {"query": "Steering"},
    "drive_read": {"file": "doc1"},
    "maps_search": {"query": "cafe in Kowdiar"},
    "maps_route": {"from": "Kowdiar, Thiruvananthapuram", "to": "Technopark"},
    "youtube_search": {"query": "Malayalam film songs"},
    "youtube_my_playlists": {},
    "youtube_playlist": {"playlist": 1},
    "contacts_search": {"name": "Ravi"},
    "whatsapp_draft": {"to": "98765 43210", "text": "Running late"},
}


async def _run(rig: Rig, name: str) -> Any:
    call = ToolCall(id="p", name=name, arguments=REAL_ARGS[name])
    with context_trust(untrusted=False, owner_text="WhatsApp 98765 43210; find Ravi"):
        return await rig.gateway.execute(call, scope=SCOPE)


def test_every_planned_tool_has_real_arguments() -> None:
    assert set(REAL_ARGS) == {n for names in PLANNED.values() for n in names}


async def test_every_registered_slice_12_tool_is_in_exactly_one_row() -> None:
    gw = (await _real_gw({})).gateway
    families = ("drive_", "maps_", "youtube_", "contacts_", "whatsapp_")
    names = sorted(s.name for s in gw.registry.specs() if s.name.startswith(families))
    assert names == sorted(REAL_ARGS)  # exactly the planned tools, all registered
    for name in names:
        tool = gw.registry.get(name)
        assert tool is not None and tool.risk is R1
        rows = {g.id for g in groups_for(name, tool.risk)}
        assert len(rows) == 1 and rows <= set(NEW), (name, rows)


@pytest.mark.parametrize(("gid", "name", "effect"), CELLS)
async def test_allow_ask_never_for_every_planned_tool(gid: str, name: str, effect: Effect) -> None:
    rig = await _real_gw(validate_choices({gid: effect.value}))
    before = rig.requests()
    out = await _run(rig, name)
    assert out.outcome is OUTCOME[effect], out.error
    assert rig.gateway.registry.get(name) is not None  # the registered tool, not a stand-in
    if effect is Effect.ASK:
        assert out.pending is not None and out.pending.summary
    if effect is not Effect.ALLOW:
        assert rig.requests() == before  # nothing reached Google before the owner says so
    if effect is Effect.DENY:
        assert "switched off by the owner in Permissions" in (out.error or "")
        entry = (await rig.gateway.audit.tail(1)).entries[-1]
        assert entry.detail == f"policy:owner:{gid}"


async def test_never_on_one_row_leaves_the_others_alone() -> None:
    for gid in NEW:
        rig = await _real_gw(validate_choices({gid: Effect.DENY.value}))
        for other in (x for x in NEW if x != gid):
            out = await _run(rig, PLANNED[other][0])
            assert out.outcome is GatewayOutcome.EXECUTED, (gid, other, out.error)


async def test_the_wiring_registers_contacts_and_whatsapp_in_their_rows() -> None:
    fake = FakePeople(contacts=[person("c1", "Ravi", phones=["98765 43210"])])
    gw = build_gateway(get_settings(), google=await people_connector(fake))
    for name, gid in (("contacts_search", "contacts"), ("whatsapp_draft", "whatsapp")):
        tool = gw.registry.get(name)
        assert tool is not None and tool.risk is R1
        assert {g.id for g in groups_for(tool.name, tool.risk)} == {gid}
    families = ("contacts_", "whatsapp_")
    assert sorted(s.name for s in gw.registry.specs() if s.name.startswith(families)) == [
        "contacts_search",
        "whatsapp_draft",
    ]


def test_without_google_whatsapp_drafts_still_exist_for_typed_numbers() -> None:
    names = {s.name for s in build_gateway(get_settings()).registry.specs()}
    assert "whatsapp_draft" in names and "contacts_search" not in names
