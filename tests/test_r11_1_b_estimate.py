# tests/test_r11_1_b_estimate.py -- R11.1 Part B (plan D12): before a paid reply on large or
# complex files the owner sees "About ₹N on <tier>; about ₹M on the stronger tier" and chooses.
# The figure is characters / 4 plus the output cap's typical use at the price table and the day's
# rate; it appears from ₹5 and never below, never for a free brain, never in No-AI mode, and it
# is always rupees.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from billing_fakes import PAID_TIERS, RATE, PricedMock, registry
from billing_fakes import billing as make_billing
from httpx import ASGITransport, AsyncClient
from r11_1_fakes_b import make_png, make_xlsx

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.fixes.ports import FixContext
from jarvis.llm.base import Usage
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.pricing import cost_usd
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.mode import BrainMode
from jarvis.storage.docs import MemoryDocs
from jarvis.understand.estimate import (
    LARGE_CHARS,
    PICTURE_TOKENS,
    SHOW_FROM_INR,
    Estimator,
    is_large,
)

UID = "u_owner"


def words(chars: int) -> bytes:
    return ("word " * (chars // 5 + 1))[:chars].encode()


class Rig:
    def __init__(self, settings: Settings, *, default: str = "anthropic") -> None:
        self.s = settings
        self.brains = registry(PricedMock(), default=default)
        self.docs = DocumentService(AttachmentStore(MemoryDocs()))
        self.state: dict[str, Any] = {
            "brains": self.brains,
            "billing": make_billing(self.brains),
            "brain_mode": BrainMode(settings),
            "documents": self.docs,
        }
        self.est = Estimator(FixContext(s=settings, docs=None, audit=None, state=self.state.get))

    async def up(self, name: str, data: bytes) -> str:
        return (await self.docs.upload(UID, name, data)).id


@pytest.fixture
def rig(settings: Settings) -> Rig:
    return Rig(settings)


def expected_inr(settings: Settings, tier: ModelTier, chars: int, pictures: int = 0) -> float:
    usage = Usage(
        input_tokens=-(-chars // 4) + pictures * PICTURE_TOKENS,
        output_tokens=settings.work_output_tokens // 4,
    )
    return cost_usd(PAID_TIERS[tier], usage) * RATE


async def test_a_large_file_shows_both_tiers_in_rupees_with_about(rig: Rig) -> None:
    aid = await rig.up("long.txt", words(250_000))
    e = await rig.est.estimate(UID, attachments=[aid], message="Summarise it")
    assert e.show and (e.tier, e.stronger_tier) == ("balanced", "strong")
    chars = 250_000 + len("Summarise it")
    assert e.inr == pytest.approx(expected_inr(rig.s, ModelTier.BALANCED, chars), rel=0.01)
    assert e.stronger_inr == pytest.approx(expected_inr(rig.s, ModelTier.STRONG, chars), rel=0.01)
    assert e.inr >= SHOW_FROM_INR and e.stronger_inr is not None and e.stronger_inr > e.inr
    assert e.line == (
        f"About ₹{round(e.inr)} for one reply on the balanced tier; about "
        f"₹{round(e.stronger_inr)} on the stronger tier."
    )  # "for one reply": a reply that uses tools reads the files again (code review L7)
    assert "$" not in e.line and e.suggest == "balanced"  # long, but plain text


async def test_nothing_is_shown_below_five_rupees(rig: Rig) -> None:
    aid = await rig.up("medium.txt", words(60_000))  # large enough to ask, about ₹4.8 on balanced
    e = await rig.est.estimate(UID, attachments=[aid])
    assert expected_inr(rig.s, ModelTier.BALANCED, 60_000) < SHOW_FROM_INR
    assert not e.show and e.line == "" and e.inr < SHOW_FROM_INR
    edge = await rig.up("edge.txt", words(70_000))  # about ₹5.3
    assert (await rig.est.estimate(UID, attachments=[edge])).show is True


async def test_small_or_simple_files_are_never_estimated(rig: Rig) -> None:
    small = await rig.up("note.txt", words(5_000))
    e = await rig.est.estimate(UID, attachments=[small])
    assert not e.show and e.inr == 0  # not large: nothing is even worked out
    assert not (await rig.est.estimate(UID, attachments=[])).show
    assert not (await rig.est.estimate(UID, attachments=["doc_" + "0" * 20])).show


async def test_a_complex_workbook_suggests_the_stronger_tier(rig: Rig) -> None:
    sheets = {f"S{i}": [[f"row {r}", "made-up words " * 40] for r in range(120)] for i in range(5)}
    aid = await rig.up("books.xlsx", make_xlsx(sheets))
    e = await rig.est.estimate(UID, attachments=[aid])
    assert e.show and e.suggest == "strong" and e.stronger_tier == "strong"
    assert "stronger tier" in e.line


def test_what_counts_as_large_or_complex() -> None:
    assert not is_large(chars=LARGE_CHARS, sheets=3, rows=2_000, pictures=2)
    assert is_large(chars=LARGE_CHARS + 1, sheets=0, rows=0, pictures=0)
    assert is_large(chars=10, sheets=4, rows=0, pictures=0)
    assert is_large(chars=10, sheets=1, rows=2_001, pictures=0)
    assert is_large(chars=0, sheets=0, rows=0, pictures=3)


async def test_pictures_count_only_for_a_brain_that_will_see_them(rig: Rig) -> None:
    ids = [await rig.up(f"{i}.png", make_png()) for i in range(3)]
    ids.append(await rig.up("long.txt", words(80_000)))
    blind = await rig.est.estimate(UID, attachments=ids)
    assert blind.inr == pytest.approx(expected_inr(rig.s, ModelTier.BALANCED, 80_000), rel=0.01)
    PricedMock.vision = True
    try:
        seeing = await rig.est.estimate(UID, attachments=ids)
    finally:
        PricedMock.vision = False
    assert seeing.inr == pytest.approx(expected_inr(rig.s, ModelTier.BALANCED, 80_000, 3), rel=0.01)


async def test_the_strongest_tier_has_no_stronger_one(rig: Rig) -> None:
    aid = await rig.up("long.txt", words(250_000))
    e = await rig.est.estimate(UID, attachments=[aid], tier="strong")
    assert e.show and e.tier == "strong" and e.stronger_tier is None and e.stronger_inr is None
    assert e.line == f"About ₹{round(e.inr)} for one reply on the strong tier."
    fast = await rig.est.estimate(UID, attachments=[aid], tier="fast")
    assert not fast.show  # 250,000 characters on the fast tier is well under ₹5
    assert (await rig.est.estimate(UID, attachments=[aid], tier="nonsense")).tier == "balanced"


async def test_a_free_or_unpriced_brain_and_no_ai_mode_show_nothing(rig: Rig) -> None:
    aid = await rig.up("long.txt", words(250_000))
    assert not (await rig.est.estimate(UID, attachments=[aid], brain="gemini")).show
    assert not (await rig.est.estimate(UID, attachments=[aid], brain="custom")).show
    assert (await rig.est.estimate(UID, attachments=[aid], brain="no-such-brain")).show  # default
    rig.s.brain_mode = "none"
    assert not (await rig.est.estimate(UID, attachments=[aid])).show


async def test_someone_elses_or_already_sent_files_are_not_counted(rig: Rig) -> None:
    theirs = (await rig.docs.upload("someone-else", "long.txt", words(250_000))).id
    assert not (await rig.est.estimate(UID, attachments=[theirs])).show


async def test_a_missing_service_means_no_estimate_never_an_error(settings: Settings) -> None:
    est = Estimator(FixContext(s=settings, docs=None, audit=None, state=lambda _: None))
    assert not (await est.estimate(UID, attachments=["doc_" + "0" * 20])).show


@pytest.mark.parametrize("broken", ["rate", "store", "brain_mode"])
async def test_an_estimate_that_cannot_be_worked_out_says_so(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, broken: str
) -> None:
    """Code review M2: a fault never looks like "under ₹5": the answer says it could not
    estimate, and the console asks the owner before a large message goes."""
    aid = await rig.up("long.txt", words(250_000))

    async def fails(*_: Any, **__: Any) -> Any:
        raise RuntimeError("down")

    target = {
        "rate": (rig.state["billing"], "inr"),
        "store": (rig.docs.store, "get"),
        "brain_mode": (rig.state["brain_mode"], "load"),
    }[broken]
    monkeypatch.setattr(*target, fails)
    e = await rig.est.estimate(UID, attachments=[aid], message="Summarise it")
    assert (e.show, e.unavailable, e.inr, e.line) == (False, True, 0.0, "")


async def test_nothing_to_estimate_is_not_a_fault(rig: Rig) -> None:
    small = await rig.up("note.txt", words(5_000))
    for e in (
        await rig.est.estimate(UID, attachments=[small]),
        await rig.est.estimate(UID, attachments=[]),
        await rig.est.estimate(UID, attachments=[small], brain="gemini"),
    ):
        assert not e.show and not e.unavailable


# ---- the route -----------------------------------------------------------------------------------


@pytest.fixture
async def client(settings: Settings, provider: MockProvider) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, provider=provider, store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


async def test_the_estimate_route_answers_and_is_quiet_on_a_free_brain(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/attachments",
        content=words(250_000),
        headers={"X-Jarvis-Filename": "long.txt", "Content-Type": "application/octet-stream"},
    )
    aid = r.json()["id"]
    r = await client.post("/v1/input/estimate", json={"attachments": [aid], "message": "hi"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["show"] is False and body["line"] == ""  # the mock brain costs nothing
    assert set(body) == {
        *("show", "tier", "inr", "stronger_tier", "stronger_inr", "suggest", "line"),
        "unavailable",
    }
    assert body["unavailable"] is False
    bad = await client.post("/v1/input/estimate", json={"attachments": ["x"] * 30})
    assert bad.status_code == 422


async def test_the_console_takes_what_counts_as_large_from_the_server(client: AsyncClient) -> None:
    """Code review L3: one source for the thresholds (`understand/estimate.py`)."""
    from pathlib import Path

    from jarvis.understand.estimate import MANY_PICTURES, MANY_ROWS, MANY_SHEETS

    large = (await client.get("/v1/input")).json()["limits"]["large"]
    assert large == {
        "chars": LARGE_CHARS,
        "sheets": MANY_SHEETS,
        "rows": MANY_ROWS,
        "pictures": MANY_PICTURES,
    }
    js = (
        Path(__file__).resolve().parents[1] / "src/jarvis/api/static/console-r111-files.js"
    ).read_text(encoding="utf-8")
    assert "l.large" in js and "large = Object.freeze" in js
