# tests/test_r11_i1_real_reads.py -- R11 integrated review (code, focus 2): the unit tests of the
# background readers use a fake registry where every name is a read, so the real tool names each
# reader asks the gateway about were only checked by grep. Here they are pinned against the REAL
# gateway (tools/setup.build_gateway with Google linked and the four parts): every name a reader
# or its "paused" check asks for is a registered READ_ONLY tool, and the governed path over that
# gateway allows each one on default rows.
from __future__ import annotations

from dataclasses import replace
from typing import Any

from people_fakes import FakePeople, people_connector
from r11_fakes import NO_ROWS, UID, ctx

from jarvis.api.r11_wiring import BUILDERS
from jarvis.config import get_settings
from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.house import breach
from jarvis.helpers.kitchen import spend
from jarvis.helpers.nudges import calendar
from jarvis.helpers.paused import PauseCheck
from jarvis.helpers.today import birthdays, pending
from jarvis.keyring import Keyring
from jarvis.tools.background import BackgroundReads
from jarvis.tools.gateway import Gateway
from jarvis.tools.setup import build_gateway

READERS: dict[str, tuple[str, ...]] = {
    "birthdays": (birthdays.TOOL,),
    "pending": (pending.TASKS_TOOL,),
    "breach_watch": breach.ROW_TOOLS,
    "nudges": (calendar.CALENDAR_TOOL,),
    "grocery_spend": spend.ROW_TOOLS,
}
WANT = {
    "birthdays": ("contacts_birthdays",),
    "pending": ("tasks_list",),
    "breach_watch": ("gmail_search", "breach_status"),
    "nudges": ("calendar_list_events",),
    "grocery_spend": ("gmail_search", "spend_month"),
}


async def _real() -> tuple[Gateway, dict[str, Any]]:
    google = await people_connector(FakePeople())
    ring = Keyring(bytes(range(1, 33)))
    parts = {}
    for name, build in BUILDERS.items():
        c, _, _, _ = ctx(name)
        parts[name] = build(replace(c, keyring=ring, google=google))
    gw = build_gateway(get_settings(), google=google, r11=parts)
    gw.rules = NO_ROWS
    return gw, parts


def test_the_readers_ask_for_these_rows() -> None:
    assert WANT == READERS


async def test_every_name_a_reader_asks_for_is_a_real_read_tool() -> None:
    gw, parts = await _real()
    for job, tools in READERS.items():
        for name in tools:
            tool = gw.registry.get(name)
            assert tool is not None, f"{job}: {name} is not a registered tool"
            assert tool.risk is ActionRisk.READ_ONLY, f"{job}: {name} is not a read"
        assert (await BackgroundReads.of(gw).verdict(UID, *tools)).ok, job
    checked = {
        t for p in parts.values() for c in p.paused if isinstance(c, PauseCheck) for t in c.tools
    }
    assert checked == {t for tools in READERS.values() for t in tools}
    for name in checked:
        assert gw.registry.get(name) is not None, name
