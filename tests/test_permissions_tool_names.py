# tests/test_permissions_tool_names.py — slice 10 integration: the permission groups (D) cover the
# REAL tools the other workstreams register (B web, C to-do, E documents), by the names and risks
# the factories declare — not a hand-written list that could drift from them.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from tasks_fakes import FakeTasks, tasks_connector
from web_fakes import FakeTavily

from jarvis.config import get_settings
from jarvis.core.guardrails import ActionRisk
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.permissions.groups import groups_for
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.gateway import Gateway
from jarvis.tools.setup import build_gateway
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.web.allowance import WebAllowance
from jarvis.web.service import WebService
from jarvis.web.tavily import TavilyProvider

R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)

# tool → (the risk its factory declares, the groups it must land in)
INTENDED: dict[str, tuple[ActionRisk, set[str]]] = {
    "web_search": (R1, {"web"}),
    "web_read": (R1, {"web"}),
    "tasks_list": (R1, {"todo_change"}),
    "task_add": (R2, {"todo_change"}),
    "task_update": (R2, {"todo_change"}),
    "task_complete": (R2, {"todo_change"}),
    # slice 11: with the Recently deleted bin a delete is undo-able (R2) and has its own row
    # ("Delete your own to-dos"); an assigned to-do's delete (R3) has its ask-or-never row
    "task_delete": (R2, {"todo_remove"}),
    "doc_read": (R1, {"documents"}),
    "doc_search": (R1, {"documents"}),
}


async def _gateway() -> Gateway:
    web = WebService(
        TavilyProvider(SecretStr("tvly-k"), http=FakeTavily().client()),
        WebAllowance(MemoryDocs(), now=lambda: NOW),
    )
    return build_gateway(
        get_settings(),
        google=await tasks_connector(FakeTasks()),
        web=web,
        documents=DocumentService(AttachmentStore(MemoryDocs())),
        undo=UndoBin(DeletedStore(MemoryDocs())),
    )


async def test_the_wiring_registers_every_slice_10_tool_with_its_declared_risk() -> None:
    gw = await _gateway()
    for name, (risk, _) in INTENDED.items():
        tool = gw.registry.get(name)
        assert tool is not None, name
        assert tool.risk is risk, name


@pytest.mark.parametrize("name", sorted(INTENDED))
async def test_each_real_tool_lands_in_its_intended_group(name: str) -> None:
    tool = (await _gateway()).registry.get(name)
    assert tool is not None
    _, want = INTENDED[name]
    assert {g.id for g in groups_for(tool.name, tool.risk)} == want


async def test_no_slice_10_tool_falls_outside_every_group() -> None:
    gw = await _gateway()
    families = ("web_", "task_", "tasks_", "doc_")
    names = [s.name for s in gw.registry.specs() if s.name.startswith(families)]
    assert sorted(names) == sorted(INTENDED)  # a new tool in these families needs a row here
    for name in names:
        tool = gw.registry.get(name)
        assert tool is not None and groups_for(name, tool.risk), name
