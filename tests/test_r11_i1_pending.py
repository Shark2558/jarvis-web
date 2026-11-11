# tests/test_r11_i1_pending.py -- R11 I1, D9's "approvals waiting" pending source (INTEGRATION-A
# 3.2): `pending_all()` gives every part's pending sources plus one line for his approval cards
# that wait (read from the gateway late; another owner's cards never count), so "what is pending"
# and "top priority now" include them, and with no card or no gateway it adds nothing.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from r11_fakes import UID

import jarvis.api.r11_wiring as r11
from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs

NOW = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)


@dataclass
class Card:
    scope: str | None


class Gw:
    def __init__(self, *scopes: str | None) -> None:
        self.cards = [Card(s) for s in scopes]

    async def pending(self) -> list[Card]:
        return self.cards


async def test_his_waiting_cards_are_one_pending_line_and_others_cards_never_count() -> None:
    st = SimpleNamespace(gateway=Gw(f"{UID}:s1", f"{UID}:s2", "someone-else:s1", None))
    got = await r11.ApprovalsPending(st).pending(UID, NOW)
    assert [(i.source, i.label, i.urgency) for i in got] == [
        ("approvals", "2 approvals waiting for your OK", "today")
    ]
    st.gateway = Gw(f"{UID}:s1")
    assert [i.label for i in await r11.ApprovalsPending(st).pending(UID, NOW)] == [
        "1 approval waiting for your OK"
    ]
    assert await r11.ApprovalsPending(SimpleNamespace(gateway=Gw())).pending(UID, NOW) == []
    assert await r11.ApprovalsPending(SimpleNamespace()).pending(UID, NOW) == []


async def test_pending_all_ends_with_the_approvals_and_part_a_lists_them(
    settings: Settings,
) -> None:
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        st: Any = app.state
        c = r11._context(app, settings, MemoryDocs(), st.gateway.audit, st.helpers_sender, "nudges")  # noqa: SLF001
        sources = c.pending_all()
        assert isinstance(sources[-1], r11.ApprovalsPending)
        assert {s.name for s in sources} >= {"approvals", "today", "house"}
        uid = r11.owners_of(settings)[0]
        real = st.gateway
        st.gateway = Gw(f"{uid}:s1")
        try:
            groups = await st.r11_parts["today"].services["pending"].grouped(uid, NOW)
        finally:
            st.gateway = real
        assert ("approvals", ["1 approval waiting for your OK"]) in [
            (src, [i.label for i in items]) for src, items in groups
        ]
