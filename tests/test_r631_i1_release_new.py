# tests/test_r631_i1_release_new.py
"""R6.3.1 I1: `release.new` names the plan whose title carries this release's exact version, so
a follow-up release (R6.3.1, v6.3.2, labelled "R6.3" by its version) is not described by R6.3's
plan title."""

from __future__ import annotations

from pathlib import Path

from r63_fakes_a import SHA, write_files

from jarvis.buildbook.gen import facts_values
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import default_scrubber

S = default_scrubber()
R63 = "Version v6.3.3 · 23 Nov 2026 · Release R6.3\n\n# Release R6.3 — The old title (`v6.3.0`)\n"
R631 = "Version v6.3.1 · 24 Nov 2026 · Release R6.3.1\n\n# Release R6.3.1 — The new title (`v6.3.2`)\n"


def _repo(tmp: Path, version: str, plans: dict[str, str]) -> Repo:
    files = {"src/jarvis/__init__.py": f'__version__ = "{version}"\n', **plans}
    return Repo.from_dir(write_files(tmp, files), sha=SHA, committed_at="2026-11-24T00:00:00+00:00")


def test_the_plan_with_the_exact_version_names_the_release(tmp_path: Path) -> None:
    plans = {"docs/plans/r6-3-book-content.md": R63, "docs/plans/r6-3-1-book-at-build.md": R631}
    got = facts_values.release_values(_repo(tmp_path, "6.3.2", plans), S)
    assert got["release.new"].value == "The new title"
    assert got["release.new"].source == "docs/plans/r6-3-1-book-at-build.md"


def test_without_a_version_match_the_release_s_own_plan_still_names_it(tmp_path: Path) -> None:
    plans = {"docs/plans/r6-3-book-content.md": R63}
    got = facts_values.release_values(_repo(tmp_path, "6.3.0", plans), S)
    assert got["release.new"].value == "The old title"


def test_a_hotfix_with_no_plan_of_its_own_keeps_its_release_s_title(tmp_path: Path) -> None:
    plans = {"docs/plans/r6-3-book-content.md": R63}
    got = facts_values.release_values(_repo(tmp_path, "6.3.1", plans), S)
    assert got["release.new"].value == "The old title"
