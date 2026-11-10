# tests/test_r51b_vitals_seams.py -- R5.1 Part B: the REAL feature classes fit the Vitals sources
# exactly as INTEGRATION-r51.md wires them (router health, Google connector, health store, web
# usage, GitHub client, home store): one board shows every item, with no attribute mismatch.
from __future__ import annotations

from datetime import UTC, datetime

import httpx
from faces_fakes import ROOT
from google_fakes import FakeGoogle
from pydantic import SecretStr
from r51b_fakes import OwnRig, with_keys

from jarvis.health.models import HealthReport, HealthState, ProbeResult
from jarvis.health.store import HealthStore
from jarvis.home.store import HomeStore
from jarvis.integrations.github import GithubClient, GithubStore
from jarvis.integrations.google import GoogleConnector
from jarvis.keyring import Keyring
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.vitals.own import OWN_IDS, OwnSources
from jarvis.web.ports import VendorUsage

UID = "u_owner"  # the same owner as google_fakes.GOOGLE_UID
NOW = datetime(2027, 1, 15, 8, 0, tzinfo=UTC)


class Tavily:
    async def usage(self) -> VendorUsage:
        return VendorUsage(used=300, limit=1000)


async def test_real_classes_fill_every_item(connected: GoogleConnector) -> None:
    docs, epoch = MemoryDocs(), NOW.timestamp()
    router = ModelRouter(MockProvider(), dict.fromkeys(ModelTier, "mock"))
    health = HealthStore(docs)
    result = ProbeResult(key="telegram", label="Telegram", status="ok", reason="ok", at=epoch)
    report = HealthReport(overall="ok", results=(result,), at=epoch)
    await health.save(UID, HealthState(report=report, alerted={}, streaks={}))
    fake = FakeGoogle()
    fake.on("GET", "https://api.github.com/user", httpx.Response(200, json={"login": "a"}))
    github = GithubClient(GithubStore(docs, Keyring(ROOT)), http=fake.client(), clock=lambda: epoch)
    await github.connect(UID, SecretStr("ghp_abcdefghijklmnopqrstuvwxyz0123456789"))
    home = HomeStore(docs, Keyring(ROOT), clock=lambda: epoch)
    await home.link(UID, "home1", "https://bridge.example", b"s" * 32)
    await home.seen(UID, parts={}, bridge_version="1")

    own = OwnSources(
        claude=router.health,
        gemini=router.health,
        google=connected,
        health=health,
        web=Tavily(),
        github=github,
        home=home,
        book=lambda: "RuntimeError",  # R6 review L2: the book item shows only when it failed
    )
    rig = OwnRig(own, settings=with_keys())
    rig.clock.now = NOW

    board = await rig.svc.board(UID)

    got = {v.provider.id: v for v in board.items}
    assert OWN_IDS <= got.keys()
    assert all(got[pid].status != "unknown" for pid in OWN_IDS), {
        pid: (got[pid].status, got[pid].reason) for pid in OWN_IDS
    }
    assert got["github_token"].provider.note == "This token doesn't expire."
    assert got["home_link"].provider.note == "Last heartbeat just now."
