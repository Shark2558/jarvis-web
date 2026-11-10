# tests/test_r51_i1_seams.py -- R5.1 I1: Part B's panel words ("If this stops: ...", the board's
# `impact`) read as one spoken sentence in Part C's briefing ("X is at 85% -- if it stops, ..."),
# for every automatic Vitals item JARVIS has fixed words for.
from __future__ import annotations

import pytest
from r51b_fakes import Brain, OwnRig

from jarvis.health.briefing import compose_briefing
from jarvis.health.models import HealthReport, ProbeResult
from jarvis.vitals.own import OwnSources
from jarvis.vitals.words import BY_REASON, WORDS

OK = HealthReport(
    overall="ok",
    results=(ProbeResult(key="docs", label="docs", status="ok", reason="x", at=1.0),),
    at=1.0,
)


@pytest.mark.parametrize(
    "impact", [w[0] for w in WORDS.values()] + [w[0] for w in BY_REASON.values()]
)
def test_no_vitals_impact_starts_a_spoken_clause_with_a_capital(impact: str) -> None:
    from jarvis.health.briefing import _plain  # noqa: PLC0415 - the one helper under test

    said = _plain(impact, "x")
    assert said[:1].islower(), said
    assert "If this" not in said and ": " not in said[:20]


async def test_the_out_of_credit_claude_key_reads_as_one_sentence() -> None:
    rig = OwnRig(OwnSources(claude=Brain("no_credit")))
    board = await rig.svc.board("u_owner")
    spoken = compose_briefing(OK, board).spoken
    assert (
        "Claude (paid AI) key is out of credit — paid AI replies are paused until the account "
        "is topped up" in spoken
    )
    assert "— If" not in spoken and "— Now" not in spoken
