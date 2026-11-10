# tests/test_book_gen_flows.py
"""R6 D2: the Workflows section (`gen.flows`). Ten fixed flows (chat turn, approval, learning,
voice turn, morning tick, vault open, home alert, systems check, no-AI, build book); every step
names a real symbol (`jarvis.mod[:Name[.attr]]`), checked against the checkout's ASTs, so a
renamed function fails the build (the CI `--check`) instead of leaving the book wrong."""

from __future__ import annotations

from pathlib import Path

import pytest
from book_gen_fakes import FIXTURE_FLOWS, ROOT, fixture_repo

from jarvis.buildbook.gen import flows
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.model import FLOW_IDS
from jarvis.buildbook.sections import Workflow


@pytest.fixture(scope="module")
def real() -> Repo:
    return Repo.from_git(ROOT)


def test_the_ten_real_flows_resolve_in_order(real: Repo) -> None:
    got = flows.workflows(real)
    assert tuple(w.id for w in got) == FLOW_IDS
    assert all(isinstance(w, Workflow) and 3 <= len(w.steps) <= 16 for w in got)
    assert all(s.symbol.startswith("jarvis.") for w in got for s in w.steps)


def test_flow_symbols_are_kept_without_the_package_prefix() -> None:
    # gen/ holds no "jarvis.<x>" string, so the D11 import-boundary probe never misreads one
    assert not any(sym.startswith("jarvis") for _, _, steps in flows.FLOWS for _, sym in steps)


@pytest.mark.parametrize(
    ("symbol", "ok"),
    [
        ("core.brain", True),
        ("core.brain:Brain", True),
        ("core.brain:Brain.chat", True),
        ("core.guardrails:guard_input", True),
        ("llm.pricing:PRICES", True),
        ("core.brain:Brain.no_such_method", False),
        ("core.brain:no_such_function", False),
        ("core.no_such_module", False),
        ("core.guardrails:guard_input.attr", False),  # a function has no attributes here
    ],
)
def test_resolve(real: Repo, symbol: str, ok: bool) -> None:
    assert flows.resolve(real, symbol) is ok


def test_a_flow_naming_a_missing_function_fails_and_says_where(real: Repo) -> None:
    broken = tuple(
        (fid, title, (*steps, ("A step that moved", "core.brain:Brain.vanished")))
        if fid == "approval"
        else (fid, title, steps)
        for fid, title, steps in flows.FLOWS
    )
    with pytest.raises(GenError, match=r"approval.*jarvis\.core\.brain:Brain\.vanished"):
        flows.workflows(real, broken)


def test_every_flow_id_is_needed_once(real: Repo) -> None:
    with pytest.raises(GenError, match="no_ai"):
        flows.workflows(real, tuple(f for f in flows.FLOWS if f[0] != "no_ai"))
    with pytest.raises(GenError, match="twice"):
        flows.workflows(real, (*flows.FLOWS, flows.FLOWS[0]))


def test_the_fixture_flows_resolve_against_the_fixture(tmp_path: Path) -> None:
    fx = Repo.from_git(fixture_repo(tmp_path))
    got = flows.workflows(fx, FIXTURE_FLOWS)
    assert got[0].steps[0].symbol == "jarvis.core.loop:Loop.turn"
    with pytest.raises(GenError):
        flows.workflows(fx)  # the real flows name code the fixture doesn't have
