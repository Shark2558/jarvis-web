# tests/test_session_store.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jarvis.core.models import Session, Turn
from jarvis.llm.base import Role, Usage
from jarvis.memory.inmemory import InMemorySessionStore


async def test_roundtrip_and_isolation(store: InMemorySessionStore) -> None:
    s = Session(user_id="owner")
    s.append(Turn(role=Role.USER, content="hi"))
    await store.save(s)

    loaded = await store.get(s.id)
    assert loaded is not None and loaded.id == s.id and len(loaded.turns) == 1

    # mutating the returned copy must not change stored state until save()
    loaded.append(Turn(role=Role.ASSISTANT, content="hello"))
    again = await store.get(s.id)
    assert again is not None and len(again.turns) == 1


async def test_running_totals(store: InMemorySessionStore) -> None:
    s = Session(user_id="owner")
    s.append(Turn(role=Role.USER, content="q"))
    s.append(
        Turn(
            role=Role.ASSISTANT,
            content="a",
            usage=Usage(input_tokens=10, output_tokens=5),
            cost_usd=0.001,
        )
    )
    s.append(
        Turn(
            role=Role.ASSISTANT,
            content="b",
            usage=Usage(input_tokens=20, output_tokens=5),
            cost_usd=0.002,
        )
    )
    assert s.total_input_tokens == 30
    assert s.total_output_tokens == 10
    assert s.total_cost_usd == 0.003


async def test_list_delete_and_ttl() -> None:
    store = InMemorySessionStore(ttl_s=60)
    a = Session(user_id="owner")
    b = Session(user_id="owner")
    other = Session(user_id="someone-else")
    for s in (a, b, other):
        await store.save(s)

    listed = await store.list_for_user("owner")
    assert {x.id for x in listed} == {a.id, b.id}

    assert await store.delete(a.id) is True
    assert await store.delete(a.id) is False
    assert await store.get(a.id) is None

    # expire b by backdating it
    b.updated_at = datetime.now(UTC) - timedelta(seconds=120)
    await store.save(b)
    assert await store.get(b.id) is None
    assert await store.list_for_user("owner") == []
