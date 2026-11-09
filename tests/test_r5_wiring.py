# tests/test_r5_wiring.py -- R5 I1: the app wires the owner's "words to recognise" into the privacy
# dashboard (docs/plans/r5-voice.md D16). The category sits right after Settings; the dashboard
# counts, exports and deletes the words through the real app; the delete writes the privacy audit
# the framework already writes (category and count, never a word).
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from httpx import ASGITransport, AsyncClient

from jarvis.api import create_app
from jarvis.brief.store import BriefStore
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.privacy import PrivacyRegistry
from jarvis.privacy.sources import ExistingParts, existing_sources
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.settings import VoiceSettingsPatch, VoiceSettingsStore

UID = "u_owner"
WORDS = ("Thiruvananthapuram", "Trivandrum")


@asynccontextmanager
async def plain_app(s: Settings) -> AsyncIterator[Any]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test"):
            yield app


def words(*items: str) -> VoiceSettingsPatch:
    return VoiceSettingsPatch.model_validate({"phrases": list(items)})


async def test_voice_words_are_listed_right_after_settings_when_the_voice_store_is_there() -> None:
    docs = MemoryDocs()
    parts = ExistingParts(briefs=BriefStore(docs), voice=VoiceSettingsStore(docs))
    reg = PrivacyRegistry()
    for s in existing_sources(parts):
        reg.register(s)
    ids = reg.ids()
    assert ids[ids.index("settings") + 1] == "voice_phrases"
    assert ids[-2:] == ["counters", "faces"]


async def test_without_the_voice_store_the_category_is_left_out() -> None:
    ids = [s.id for s in existing_sources(ExistingParts(briefs=BriefStore(MemoryDocs())))]
    assert "voice_phrases" not in ids


async def test_the_app_dashboard_counts_exports_and_deletes_the_voice_words(
    settings: Settings,
) -> None:
    async with plain_app(settings) as app:
        privacy, store = app.state.privacy, app.state.voice.store
        assert "voice_phrases" in privacy.registry.ids()
        await store.update(UID, words(*WORDS))
        view = next(c for c in (await privacy.view(UID)).categories if c.id == "voice_phrases")
        assert (view.count, view.export, view.delete) == (2, True, "simple")
        assert not any(w in view.model_dump_json() for w in WORDS)  # the look never lists them
        out = await privacy.export(UID, "voice_phrases")
        assert out["data"] == {"phrases": list(WORDS)}
        done = await privacy.delete(
            UID, "voice_phrases", rev=view.rev, confirm=None, proof=None, fresh_left_s=None
        )
        assert (done.deleted, done.remaining) == (2, 0)
        assert (await store.get(UID)).phrases == ()
        entries = (await privacy.audit.tail(50)).entries
        rows = [e for e in entries if e.tool in ("privacy_delete", "privacy_export")]
        assert {(e.tool, e.agent, e.outcome) for e in rows} == {
            ("privacy_export", "owner", "executed"),
            ("privacy_delete", "owner", "executed"),
        }
        deleted = next(e for e in rows if e.tool == "privacy_delete")
        assert deleted.detail.startswith("voice_phrases: 2")
        blob = " ".join(e.model_dump_json() for e in entries)
        assert not any(w in blob for w in WORDS)  # a count, never a word
