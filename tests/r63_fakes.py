# tests/r63_fakes.py -- R6.3 I0's shared fakes (docs/plans/r6-3-book-content.md seam 12). Imported
# bare (`from r63_fakes import ...`; CI runs plain pytest from the repository root, which is not on
# sys.path). Each part has its own file (`r63_fakes_a.py` ... `r63_fakes_d.py`, UNIQUE names).
# Every clock here is FIXED (IST); nothing here calls a model, Google or Anthropic.
#
#   IST, NOW, ist(...), FixedClock   24 Nov 2026 10:00 IST (the day after approval stop 2)
#   UID, RING                        the primary owner's id, a keyring from fixed bytes
#   FIXTURE_FILES / fixture_repo     a tiny repository: a three-card guide (C01-C03, one module
#                                    "demo"), its code, a plan, the settings (`demo_limit`)
#   FIXTURE_FACTS                    the fact pack part A must compute for that repository (what B's
#                                    packs, checks and filler and r63_fake_brains' drafts use)
#   source_zip(files)                a deterministic zip of the fixture (R6's ZIP_STAMP)
#   FakeBilling                      `record` and `usage` with a monthly limit (fail-closed switch)
#   FakeSource                       R6's `BookSource` + `facts()` over in-memory bytes
#   writer_context(...)              a `WriterContext` over MemoryDocs, the real R6 vault, the
#                                    scripted brains of r63_fake_brains and the fixed clock
from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from r63_fake_brains import registry

from jarvis.buildbook.facts_model import (
    CardFact,
    FactIndex,
    FactPack,
    FactValue,
    IndexedPage,
    ModuleFact,
    Route,
    Setting,
)
from jarvis.buildbook.model import ZIP_STAMP, Book, FileKind, Release, ReleaseRef
from jarvis.buildbook.ports import BookUnavailable
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.writer.ports import WriterContext
from jarvis.keyring import Keyring
from jarvis.llm.brains import BrainRegistry
from jarvis.storage.docs import MemoryDocs

IST = ZoneInfo("Asia/Kolkata")
UID = "owner-r63"
RING = Keyring(bytes(range(63, 95)))
SHA = "63" * 20
RELEASE = ReleaseRef(
    id=SHA[:7],
    sha=SHA,
    label="R6.3",
    committed_at="2026-11-24T09:00:00+05:30",
    version="v6.3.0",
)


def ist(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


NOW = ist(2026, 11, 24, 10, 0)


class FixedClock:
    """A clock that moves only when told (`advance`); every writer test takes one."""

    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kw: float) -> datetime:
        self.at += timedelta(**kw)
        return self.at


# ---- the fixture repository (three cards, one module) -------------------------------------------
_CARD = """#### {cid} · {title}

| Field | Value |
|---|---|
| Name | {title} |
| What it does | {does} |
| Layer | L4 |
| Skill | Learning |
| Where in the code | {where} |
| Depends on | None |
| Data it keeps | None |
| Outside services | {services} |
| Cost (₹ a month) | 0 |
| When it fails | It says so plainly. |
| Since | R6.3 |
"""
GUIDE = (
    "Version v6.3.0 · 24 Nov 2026, 09:00 IST · Release R6.3 · Status: Current · Owner: Fixture\n\n"
    "# Fixture guide\n\n## 3. Component catalogue\n\n"
    + _CARD.format(
        cid="C01",
        title="Demo router",
        does="Picks one tier for each request.",
        where="`src/jarvis/demo/router.py` (`pick`)",
        services="Anthropic",
    )
    + _CARD.format(
        cid="C02",
        title="Demo store",
        does="Keeps the demo's notes.",
        where="`src/jarvis/demo/store.py`",
        services="Firestore",
    )
    + _CARD.format(
        cid="C03",
        title="Demo console",
        does="Shows the demo in the console.",
        where="`console-demo.js`",
        services="None",
    )
    + "\n## 11. Roadmap (PLANNED)\n\n| Release | What |\n|---|---|\n| R9 | A voice picker. |\n"
)
FIXTURE_FILES: dict[str, str] = {
    "docs/architecture/JARVIS-Architecture.md": GUIDE,
    "docs/plans/r6-3-fixture.md": "# Release R6.3 — The fixture\n\n## Risks\n\n- A made-up risk.\n",
    "src/jarvis/__init__.py": '__version__ = "6.3.0"\n',
    "src/jarvis/demo/__init__.py": '"""The demo."""\n',
    "src/jarvis/demo/router.py": (
        '"""The demo router: one tier a request."""\n\nMAX_TRIES = 3\n\n\n'
        'def pick(asked: str) -> str:\n    """The tier for `asked`."""\n    return "balanced"\n'
    ),
    "src/jarvis/demo/store.py": '"""The demo store."""\n\nKEEP_DAYS = 30\n',
    "src/jarvis/config.py": (
        "from pydantic import Field\n\n\nclass Settings:\n"
        "    demo_limit: int = Field(default=5, ge=1, le=10)\n"
    ),
    "src/jarvis/api/static/console-demo.js": "// the demo's console module\n",
}


def fixture_repo(tmp: Path) -> Path:
    for rel, text in FIXTURE_FILES.items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text(text, encoding="utf-8")
    return tmp


def source_zip(files: Mapping[str, str] = FIXTURE_FILES) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(files):
            zf.writestr(zipfile.ZipInfo(rel, date_time=ZIP_STAMP), files[rel])
    return buf.getvalue()


def _v(value: Any, source: str, *, verified: bool = True) -> FactValue:
    return FactValue(value=value, source=source, verified=verified)


_PATHS = tuple(sorted(FIXTURE_FILES))
_ROUTER, _STORE = "src/jarvis/demo/router.py", "src/jarvis/demo/store.py"
_JS = "src/jarvis/api/static/console-demo.js"
FIXTURE_FACTS = FactPack(
    release=RELEASE,
    values={
        "cards.count": _v(3, "docs/architecture/JARVIS-Architecture.md"),
        "modules.count": _v(1, "src/jarvis/buildbook/gen/modules.py"),
        f"{_ROUTER}:MAX_TRIES": _v(3, f"{_ROUTER}:MAX_TRIES"),
        f"{_STORE}:KEEP_DAYS": _v(30, f"{_STORE}:KEEP_DAYS"),
        "settings.demo_limit": _v(5, "src/jarvis/config.py:demo_limit"),
        "hosting.region": _v("asia-south1", "deploy/cloudrun.sh", verified=False),
        "release.label": _v("R6.3", "src/jarvis/__init__.py"),
    },
    index=FactIndex(
        paths=_PATHS,
        symbols=(f"{_ROUTER}:pick",),
        constants=(f"{_ROUTER}:MAX_TRIES", f"{_STORE}:KEEP_DAYS"),
        settings=("demo_limit",),
        collections=("demo_notes",),
        routes=("GET /v1/demo",),
    ),
    routes=(Route(method="GET", path="/v1/demo", module="src/jarvis/demo/router.py"),),
    settings=(Setting(name="demo_limit", kind="int", default=5, ge=1, le=10),),
    collections=("demo_notes",),
    modules=(ModuleFact(id="demo", title="The demo", cards=("C01", "C02", "C03")),),
    cards=(
        CardFact(
            id="C01", title="Demo router", module="demo", refs=(_ROUTER,), services=("Anthropic",)
        ),
        CardFact(
            id="C02", title="Demo store", module="demo", refs=(_STORE,), services=("Firestore",)
        ),
        CardFact(id="C03", title="Demo console", module="demo", refs=(_JS,)),
    ),
    services=("Anthropic", "Firestore"),
    pages=(
        IndexedPage(
            id="pg_chapter_example",
            kind="chapter",
            title="The running example",
            part="plain",
            refs=(_ROUTER, _STORE),
            sources=("C01", "C02"),
        ),
        IndexedPage(
            id="pg_module_demo",
            kind="module",
            title="The demo",
            part="modules",
            refs=(_ROUTER, _STORE, _JS),
            sources=("C01", "C02", "C03"),
        ),
        IndexedPage(
            id="pg_card_c01",
            kind="card",
            title="Demo router",
            part="parts",
            chapter="demo",
            refs=(_ROUTER,),
            sources=("C01",),
        ),
        IndexedPage(
            id="pg_card_c02",
            kind="card",
            title="Demo store",
            part="parts",
            chapter="demo",
            refs=(_STORE,),
            sources=("C02",),
        ),
        IndexedPage(
            id="pg_card_c03",
            kind="card",
            title="Demo console",
            part="parts",
            chapter="demo",
            refs=(_JS,),
            sources=("C03",),
        ),
        IndexedPage(
            id="pg_service_anthropic",
            kind="service",
            title="Anthropic",
            part="services",
            refs=(_ROUTER,),
            sources=("C01",),
        ),
    ),
)


# ---- money and the release ----------------------------------------------------------------------
class FakeBilling:
    """`record(uid, brain, usd)` adds to the month; `usage(uid)` answers his limit (None: none).
    `broken = True` makes both raise (an unreadable meter: the writer refuses, fail closed)."""

    def __init__(self, limit_inr: int | None = 3_000, rate: float = 95.24) -> None:
        self.limit_inr, self.rate, self.broken = limit_inr, rate, False
        self.recorded: list[tuple[str, str, float]] = []

    async def record(self, uid: str, brain_id: str, cost_usd: float) -> float:
        if self.broken:
            raise RuntimeError("meter unreadable")
        self.recorded.append((uid, brain_id, cost_usd))
        return round(cost_usd * self.rate, 2)

    async def usage(self, uid: str) -> Any:
        if self.broken:
            raise RuntimeError("meter unreadable")
        used = round(sum(c for u, _, c in self.recorded if u == uid) * self.rate, 2)
        return type("Usage", (), {"used_inr": used, "limit_inr": self.limit_inr})()


class FakeSource:
    """R6's `BookSource` plus `facts()` (R6.3) over in-memory bytes; `book()` is not needed by the
    writer's tests and raises unless a book is given."""

    def __init__(
        self,
        facts: FactPack = FIXTURE_FACTS,
        *,
        zipped: bytes | None = None,
        book: Book | None = None,
    ) -> None:
        self._facts, self._zip, self._book = facts, zipped or source_zip(), book
        digest = hashlib.sha256(self._zip).hexdigest()
        self._release = Release(**RELEASE.model_dump(), book_sha256=digest, source_sha256=digest)

    def current(self) -> Release | None:
        return self._release

    def read(self, kind: FileKind) -> bytes:
        if kind == "source":
            return self._zip
        raise BookUnavailable("no book.json in this fake")

    def book(self) -> Book:
        if self._book is None:
            raise BookUnavailable("no book.json in this fake")
        return self._book

    def facts(self) -> FactPack:
        return self._facts


def writer_context(
    *,
    brains: BrainRegistry | None = None,
    billing: FakeBilling | None = None,
    source: FakeSource | None = None,
    docs: MemoryDocs | None = None,
    clock: FixedClock | None = None,
    limit_mb: int = 60,
) -> WriterContext:
    store = docs or MemoryDocs()
    return WriterContext(
        docs=store,
        keyring=RING,
        brains=brains or registry(),
        billing=billing or FakeBilling(),
        source=source or FakeSource(),
        vault=DocsBookVault(store, RING, prefix="jarvis_", limit_mb=limit_mb),
        notifier=None,
        audit=None,
        prefix="jarvis_",
        limit_mb=limit_mb,
        uid=UID,
        owner_emails=("owner@example.com",),
        honorific="Sir",
        timezone="Asia/Kolkata",
        clock=clock or FixedClock(),
    )


__all__ = [
    "FIXTURE_FACTS",
    "FIXTURE_FILES",
    "GUIDE",
    "IST",
    "NOW",
    "RELEASE",
    "RING",
    "UID",
    "FakeBilling",
    "FakeSource",
    "FixedClock",
    "fixture_repo",
    "ist",
    "source_zip",
    "writer_context",
]
