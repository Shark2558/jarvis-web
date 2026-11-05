# tests/test_vault_unlock.py -- R2 D6: unlock window, single-use tickets, HMAC at rest
from __future__ import annotations

import datetime as dt

import pytest
from vault_fakes import NOW, OTHER, UID, ring, scan

from jarvis.storage.docs import MemoryDocs
from jarvis.vault.unlock import (
    MAX_GRANTS,
    MAX_TICKETS,
    TICKET_S,
    TicketGone,
    UnlockStore,
)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += dt.timedelta(seconds=seconds)


def build(minutes: int = 10) -> tuple[UnlockStore, MemoryDocs, Clock]:
    docs, clock = MemoryDocs(), Clock()
    return UnlockStore(docs, ring(), minutes=minutes, clock=clock), docs, clock


async def test_grant_is_valid_for_the_window_then_expires() -> None:
    store, _, clock = build(10)
    g = await store.grant(UID)
    assert len(g.token) >= 43 and g.until == NOW + dt.timedelta(minutes=10)
    assert await store.valid(UID, g.token)
    clock.advance(599)
    assert await store.valid(UID, g.token)
    clock.advance(2)
    assert not await store.valid(UID, g.token)


async def test_token_is_only_stored_as_a_mac_and_belongs_to_one_owner() -> None:
    store, docs, _ = build()
    g = await store.grant(UID)
    assert not scan(docs, g.token)
    assert not await store.valid(OTHER, g.token)
    assert not await store.valid(UID, g.token + "x") and not await store.valid(UID, "")


async def test_at_most_three_live_grants() -> None:
    store, _, _ = build()
    grants = [await store.grant(UID) for _ in range(MAX_GRANTS + 2)]
    live = [await store.valid(UID, g.token) for g in grants]
    assert live == [False, False, True, True, True]


async def test_ticket_is_single_use_and_bound_to_item_and_file() -> None:
    store, docs, _ = build()
    g = await store.grant(UID)
    t = await store.ticket(UID, g.token, "v_000000000001", "f_000000000001")
    assert t.expires_in_s == TICKET_S == 60 and not scan(docs, t.ticket)
    got = await store.take(UID, t.ticket)
    assert (got.item, got.fid) == ("v_000000000001", "f_000000000001")
    with pytest.raises(TicketGone):
        await store.take(UID, t.ticket)


async def test_ticket_expires_after_60_seconds() -> None:
    store, _, clock = build()
    g = await store.grant(UID)
    t = await store.ticket(UID, g.token, "v_000000000001", "f_000000000001")
    clock.advance(61)
    with pytest.raises(TicketGone):
        await store.take(UID, t.ticket)


async def test_ticket_needs_a_live_token_and_is_owner_bound() -> None:
    store, _, clock = build()
    with pytest.raises(PermissionError):
        await store.ticket(UID, "nope", "v_000000000001", "f_000000000001")
    g = await store.grant(UID)
    t = await store.ticket(UID, g.token, "v_000000000001", "f_000000000001")
    with pytest.raises(TicketGone):
        await store.take(OTHER, t.ticket)
    clock.advance(601)
    with pytest.raises(PermissionError):
        await store.ticket(UID, g.token, "v_000000000001", "f_000000000001")


async def test_export_ticket() -> None:
    store, _, _ = build()
    g = await store.grant(UID)
    t = await store.ticket(UID, g.token, None, "export")
    got = await store.take(UID, t.ticket)
    assert got.fid == "export" and got.item is None


async def test_at_most_five_live_tickets() -> None:
    store, _, _ = build()
    g = await store.grant(UID)
    ts = [await store.ticket(UID, g.token, "v_000000000001", "f_000000000001") for _ in range(7)]
    gone = 0
    for t in ts:
        try:
            await store.take(UID, t.ticket)
        except TicketGone:
            gone += 1
    assert gone == 7 - MAX_TICKETS


async def test_lock_forgets_tokens_and_tickets() -> None:
    store, _, _ = build()
    g = await store.grant(UID)
    t = await store.ticket(UID, g.token, "v_000000000001", "f_000000000001")
    await store.lock(UID)
    assert not await store.valid(UID, g.token)
    with pytest.raises(TicketGone):
        await store.take(UID, t.ticket)


async def test_sweep_drops_expired() -> None:
    store, docs, clock = build()
    await store.grant(UID)
    clock.advance(700)
    assert await store.sweep(UID) == 1
    assert docs._data[f"jarvis_vault_unlocks/{UID}"] == {"grants": [], "tickets": []}
