# tests/test_r1_tools_wiring.py -- R1 D: r1_tools() returns the eight tools the plan lists, each in
# its permission row, with the declared risks; one gateway can hold them with the existing ones.
from __future__ import annotations

from pydantic import SecretStr

from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.permissions.groups import groups_for
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.gmail import gmail_tools
from jarvis.tools.google_tasks import tasks_tools
from jarvis.tools.r1_tools import r1_tools
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.task_marks import OutsideTasks

R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
EXPECTED = {
    "gmail_track_packages": (R1, "email_read"),
    "gmail_unread_digest": (R1, "email_read"),
    "grocery_list": (R1, "groceries"),
    "grocery_add": (R2, "groceries"),
    "grocery_remove": (R2, "groceries"),
    "family_calendar_events": (R1, "family_read"),
    "family_free_slots": (R1, "family_read"),
    "family_event_add": (R3, "family_change"),
}


def _conn() -> GoogleConnector:
    return GoogleConnector(MemoryTokenStore(), client_id="c", client_secret=SecretStr("s"))


def _settings() -> Settings:
    return Settings(_env_file=None, user_timezone="Asia/Kolkata")


def test_r1_tools_are_the_planned_set_with_risks_and_rows() -> None:
    docs = MemoryDocs()
    tools = r1_tools(_conn(), docs=docs, s=_settings(), marks=OutsideTasks(docs))
    assert {t.name for t in tools} == set(EXPECTED)
    assert len(tools) == 8
    for t in tools:
        risk, row = EXPECTED[t.name]
        assert t.risk is risk
        assert row in [g.id for g in groups_for(t.name, t.risk)], t.name


def test_only_the_two_grocery_writes_are_spoken_ok() -> None:
    tools = r1_tools(_conn(), docs=MemoryDocs(), s=_settings())
    assert {t.name for t in tools if t.spoken_ok} == {"grocery_add", "grocery_remove"}


def test_only_the_owners_own_grocery_list_may_vouch() -> None:
    tools = r1_tools(_conn(), docs=MemoryDocs(), s=_settings())
    assert {t.name for t in tools if t.may_vouch} == {
        "grocery_list",
        "grocery_add",
        "grocery_remove",
    }
    assert not any(t.trusted_output for t in tools)


def test_registering_beside_the_existing_google_tools_has_no_name_clash() -> None:
    reg = ToolRegistry()
    conn = _conn()
    every = gmail_tools(conn) + tasks_tools(conn) + r1_tools(conn, docs=MemoryDocs(), s=_settings())
    for t in every:
        reg.register(t)  # raises on a duplicate name
    assert len(reg.specs()) == 4 + 5 + 8


def test_new_names_fall_into_no_unrelated_row() -> None:
    for name, (risk, row) in EXPECTED.items():
        ids = {g.id for g in groups_for(name, risk)}
        assert row in ids, name
        assert not ids & {"calendar_change", "todo_change", "email_send"}, name
