# tests/test_permissions_slice12.py — slice 12 D8: the permission rows for the five integrations
# (Drive, Maps, YouTube, Contacts, WhatsApp drafts): R1, Allow / Ask first / Never, plain-English
# labels, a sensible order. The Drive / Maps / YouTube tools are built in parallel by other
# builders, so their calls are stub tools registered here under the planned names; Contacts and
# WhatsApp are the real tools (wired by build_gateway when Google is linked).
from __future__ import annotations

from typing import Any

import pytest
from people_fakes import FakePeople, people_connector, person

from jarvis.config import get_settings
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.permissions.groups import GROUPS, group_ids, groups_for, rules_for, validate_choices
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool, ToolCall
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
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


# ---- through the real gateway, with stub tools for the parallel builders --------------------


class Rules:
    def __init__(self, choices: dict[str, Effect]) -> None:
        self.choices = choices

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return rules_for(self.choices)


def _gw(name: str, choices: dict[str, Effect], ran: list[Any]) -> Gateway:
    reg = ToolRegistry()
    reg.register(Tool(name, "stub", {"type": "object", "properties": {}}, R1, ran.append))
    return Gateway(
        registry=reg,
        policy=Policy(),
        gate=ConfirmationGate(),
        audit=AuditLog(),
        rules=Rules(choices),
    )


OUTCOME = {
    Effect.ALLOW: GatewayOutcome.EXECUTED,
    Effect.ASK: GatewayOutcome.AWAITING_CONFIRMATION,
    Effect.DENY: GatewayOutcome.DENIED,
}
CELLS = [(gid, name, e) for gid in NEW for name in PLANNED[gid] for e in Effect]


@pytest.mark.parametrize(("gid", "name", "effect"), CELLS)
async def test_allow_ask_never_for_every_planned_tool(gid: str, name: str, effect: Effect) -> None:
    ran: list[Any] = []
    gw = _gw(name, validate_choices({gid: effect.value}), ran)
    with context_trust(untrusted=False):
        out = await gw.execute(ToolCall(id="p", name=name, arguments={}), scope="u:s")
    assert out.outcome is OUTCOME[effect]
    assert bool(ran) == (effect is Effect.ALLOW)
    if effect is Effect.DENY:
        assert "switched off by the owner in Permissions" in (out.error or "")
        entry = (await gw.audit.tail(1)).entries[-1]
        assert entry.detail == f"policy:owner:{gid}"


async def test_never_on_one_row_leaves_the_others_alone() -> None:
    for gid in NEW:
        others = [x for x in NEW if x != gid]
        for other in others:
            ran: list[Any] = []
            gw = _gw(PLANNED[other][0], {gid: Effect.DENY}, ran)
            with context_trust(untrusted=False):
                out = await gw.execute(
                    ToolCall(id="o", name=PLANNED[other][0], arguments={}), scope="u:s"
                )
            assert out.outcome is GatewayOutcome.EXECUTED, (gid, other)


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
