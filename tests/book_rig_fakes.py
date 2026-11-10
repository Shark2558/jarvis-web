# tests/book_rig_fakes.py -- builder C's BookService on in-process documents, a recording notifier,
# a software audit chain and the worst-case brain (R6 D8-D14). Imported bare by tests.
from __future__ import annotations

from typing import Any

from book_show_fakes import (
    OWNER_EMAIL,
    Clock,
    FixtureSource,
    FlakyDocs,
    Prefs,
    RecordingNotifier,
    WorstCaseProvider,
    keyring,
)

from jarvis.billing.service import Billing
from jarvis.buildbook.lock import DocShowLock
from jarvis.buildbook.service import BookService
from jarvis.buildbook.sessions import DocBookSessions
from jarvis.buildbook.talk import BookTalk
from jarvis.config import Settings
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.router import ModelTier
from jarvis.tools.audit import AuditLog

TIERS = {ModelTier.FAST: "f", ModelTier.BALANCED: "b", ModelTier.STRONG: "s"}


class AiMode:
    def __init__(self) -> None:
        self.value = "ai"

    async def load(self, uid: str) -> str:
        return self.value


class ServiceRig:
    """BookService as I1 wires it, every part reachable for the test."""

    def __init__(self, settings: Settings, *, questions: int = 20) -> None:
        self.docs, self.audit, self.sent = FlakyDocs(), AuditLog(), RecordingNotifier()
        self.clock, self.prefs, self.model = Clock(), Prefs(), WorstCaseProvider()
        self.mode = AiMode()
        brains = BrainRegistry([BrainSpec("m", "M", self.model, TIERS)], default_id="m")
        self.billing = Billing.in_memory(brains, settings)
        self.sessions = DocBookSessions(self.docs, keyring(), questions=questions)
        self.lock = DocShowLock(self.docs, cache_s=0)
        self.talk = BookTalk(
            brains,
            self.billing,
            self.mode,
            FixtureSource(),
            self.sessions,
            prefs=self.prefs,
            owner_emails=(OWNER_EMAIL,),
        )
        self.svc = BookService(
            source=FixtureSource(),
            sessions=self.sessions,
            lock=self.lock,
            talk=self.talk,
            audit=self.audit,
            notifier=self.sent,
            docs=self.docs,
            owner_emails=(OWNER_EMAIL,),
        )

    async def tools(self) -> list[tuple[str, str]]:
        tail = await self.audit.tail(100)
        return [(e.tool, e.detail) for e in tail.entries]

    async def open(self, uid: str, audience: str = "guest") -> Any:
        return await self.svc.open(uid, audience, how="passkey 1a2b", now=self.clock())  # type: ignore[arg-type]

    def notices(self) -> list[str]:
        return [m for _, _, m in self.sent.sent]


__all__ = ["AiMode", "ServiceRig"]
