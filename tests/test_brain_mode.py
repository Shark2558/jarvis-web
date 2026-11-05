# tests/test_brain_mode.py
"""The persisted no-AI switch (R4 D-D3): survives a restart, cached briefly, audited, fail-closed."""

from __future__ import annotations

from jarvis.config import Settings
from jarvis.offline.mode import CACHE_S, BrainMode
from jarvis.storage.docs import Doc, MemoryDocs, Set
from jarvis.tools.audit import AuditLog


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(settings: Settings, docs: MemoryDocs | None = None, audit: AuditLog | None = None):
    clock = Clock()
    return BrainMode(settings, docs, audit=audit, clock=clock), clock


async def test_without_a_store_the_setting_is_the_mode(settings: Settings) -> None:
    mode, _ = make(settings)

    assert mode.current == "ai"
    settings.brain_mode = "none"
    assert mode.current == "none"


async def test_a_flip_is_persisted_and_survives_a_restart(settings: Settings) -> None:
    docs = MemoryDocs()
    first, _ = make(settings, docs)

    await first.set("owner", "none", by="owner")
    second, _ = make(settings, docs)  # a fresh process, same documents

    assert await second.load("owner") == "none"
    assert second.current == "none"


async def test_every_flip_appends_an_audit_entry(settings: Settings) -> None:
    audit = AuditLog()
    mode, _ = make(settings, MemoryDocs(), audit)

    await mode.set("owner", "none", by="owner")
    await mode.set("owner", "ai", by="owner")

    tail = await audit.tail(10)
    assert [e.tool for e in tail.entries] == ["brain_mode_set", "brain_mode_set"]
    assert [e.outcome for e in tail.entries] == ["none", "ai"]


async def test_a_read_within_the_cache_window_does_not_hit_the_store_again(
    settings: Settings,
) -> None:
    docs = MemoryDocs()
    mode, clock = make(settings, docs)
    await mode.set("owner", "none", by="owner")
    other, _ = make(settings, docs)
    await other.set("owner", "ai", by="owner")  # changed behind this instance's back

    clock.now += CACHE_S - 1
    assert await mode.load("owner") == "none"  # cached
    clock.now += 2
    assert await mode.load("owner") == "ai"  # refreshed


async def test_an_unreadable_document_fails_closed_to_no_ai(settings: Settings) -> None:
    class Broken(MemoryDocs):
        async def get(self, path: str) -> Doc | None:
            raise RuntimeError("store down")

    mode, _ = make(settings, Broken())

    assert await mode.load("owner") == "none"
    assert mode.current == "none"


async def test_a_garbage_value_in_the_document_fails_closed(settings: Settings) -> None:
    docs = MemoryDocs()
    await docs.write([Set("jarvis_settings/owner", {"brain_mode": "maybe"})])
    mode, _ = make(settings, docs)

    assert await mode.load("owner") == "none"


async def test_a_missing_document_uses_the_deployment_default(settings: Settings) -> None:
    mode, _ = make(settings, MemoryDocs())

    assert await mode.load("owner") == "ai"
