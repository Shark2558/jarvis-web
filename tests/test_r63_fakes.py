# tests/test_r63_fakes.py -- R6.3 I0 seam 12: the shared fakes hold what the parts build on. The
# fixture's fact pack is a valid pack whose index holds every reference the good draft cites; each
# bad draft breaks exactly what it is named for; the scripted brains go through the real registry
# (and its laptop fallback); the fixed clock moves only when told. (R6.3.1 D8: the writer's billing
# fake and context went with the writer.)
from __future__ import annotations

import re
from pathlib import Path

from r63_fake_brains import (
    EMAIL_DRAFT,
    FAKE_PATH_DRAFT,
    GOOD_DRAFT,
    INVENTED_DRAFT,
    PLANNED_OUTSIDE_DRAFT,
    TYPED_NUMBER_DRAFT,
    UNVERIFIED_DRAFT,
    claude_like,
    gemini_like,
    registry,
)
from r63_fakes import (
    FIXTURE_FACTS,
    FIXTURE_FILES,
    NOW,
    FakeSource,
    FixedClock,
    fixture_repo,
    source_zip,
)

from jarvis.buildbook.facts_model import canonical_facts, load_facts
from jarvis.buildbook.gen import modules
from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.writer.model import DRAFT_SECTIONS, FACT_PLACEHOLDER, HEADINGS
from jarvis.llm.router import ModelTier

SPAN = re.compile(r"`([^`]+)`")


def test_the_fixture_pack_round_trips_and_passes_the_scrub() -> None:
    assert load_facts(canonical_facts(FIXTURE_FACTS)) == FIXTURE_FACTS
    default_scrubber().verify(FIXTURE_FACTS.model_dump(mode="json"))


def test_the_fixture_guide_has_three_cards_in_one_module(tmp_path: Path) -> None:
    root = fixture_repo(tmp_path)
    cards = modules.guide_cards((root / "docs/architecture/JARVIS-Architecture.md").read_text())
    assert cards == ("C01", "C02", "C03")
    table = tuple(modules.Module(m.id, m.title, m.cards) for m in FIXTURE_FACTS.modules)
    modules.check(cards, table=table)
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) == sorted(
        FIXTURE_FILES
    )


def test_the_good_draft_cites_only_what_the_index_holds() -> None:
    idx = FIXTURE_FACTS.index
    known = {*idx.paths, *idx.settings, *(s.split(":")[1] for s in idx.symbols)}
    spans = SPAN.findall(GOOD_DRAFT)
    assert spans and set(spans) <= known
    keys = FACT_PLACEHOLDER.findall(GOOD_DRAFT)
    assert keys and all(k in FIXTURE_FACTS.values for k in keys)
    heads = re.findall(r"^## (.+)$", GOOD_DRAFT, re.MULTILINE)
    assert heads == [HEADINGS[s] for s in DRAFT_SECTIONS]


def test_each_bad_draft_breaks_one_thing() -> None:
    assert "`src/jarvis/demo/ghost.py`" in FAKE_PATH_DRAFT
    assert "ghost.py" not in " ".join(FIXTURE_FACTS.index.paths)
    assert "at most 3 times" in TYPED_NUMBER_DRAFT
    assert "@example.org" in EMAIL_DRAFT and "email" in default_scrubber().findings(EMAIL_DRAFT)
    assert "books flights" in INVENTED_DRAFT and "Soon it will" in PLANNED_OUTSIDE_DRAFT
    key = FACT_PLACEHOLDER.findall(UNVERIFIED_DRAFT)[-1]
    assert FIXTURE_FACTS.values[key].verified is False
    for bad in (FAKE_PATH_DRAFT, TYPED_NUMBER_DRAFT, EMAIL_DRAFT, INVENTED_DRAFT):
        assert bad != GOOD_DRAFT


def test_the_scripted_brains_are_the_real_registrys() -> None:
    reg = registry(claude_like(), gemini_like())
    assert [b.id for b in reg.list()] == ["anthropic", "gemini"]
    assert reg.get("gemini").trains_on_content and not reg.get("anthropic").trains_on_content
    assert reg.router_for("anthropic").resolve(ModelTier.BALANCED) == "claude-sonnet-5-5"


async def test_the_fakes_source() -> None:
    src = FakeSource()
    assert src.facts() is FIXTURE_FACTS and src.read("source") == source_zip()
    assert source_zip() == source_zip()  # deterministic


def test_the_clock_is_fixed() -> None:
    clock = FixedClock()
    assert clock() == NOW == clock() and clock.advance(minutes=5) > NOW
