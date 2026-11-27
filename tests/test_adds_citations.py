"""The ADD's citation check (scripts/docs/adds_citations.py, chapter 13 of the design document).

Each case builds a tiny repository in tmp_path; the last one runs on this repository's chapters.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "docs" / "adds_citations.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("adds_citations", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["adds_citations"] = module
    spec.loader.exec_module(module)
    return module


ac = _load()


def _repo(root: Path, chapter: str) -> Path:
    (root / "src/jarvis/tools").mkdir(parents=True)
    (root / "src/jarvis/tools/gateway.py").write_text(
        "LIMIT = 5\n\nclass Gateway:\n    MAX = 1\n\n    def execute(self): ...\n\n"
        "def _tightened(): ...\n",
        encoding="utf-8",
    )
    (root / "android/app/src/main/java/io/github/someone/jarvis/shell").mkdir(parents=True)
    (root / "android/app/src/main/java/io/github/someone/jarvis/shell/Tile.kt").write_text(
        "// tile\n", encoding="utf-8"
    )
    (root / "Dockerfile").write_text("FROM python\n", encoding="utf-8")
    design = root / "docs/architecture/design"
    design.mkdir(parents=True)
    (design / "01-x.md").write_text(chapter, encoding="utf-8")
    return root


def test_existing_paths_symbols_and_methods_pass(tmp_path: Path) -> None:
    text = (
        "See `src/jarvis/tools/gateway.py:Gateway.execute`, `src/jarvis/tools/gateway.py:LIMIT`,\n"
        "`src/jarvis/tools/gateway.py:_tightened`, `src/jarvis/tools/gateway.py:Gateway.MAX`,\n"
        "`src/jarvis/tools/` and `Dockerfile` (`HEALTHCHECK`).\n"
    )
    report = ac.check(_repo(tmp_path, text))
    assert report.problems == []
    assert report.checked == 6


def test_a_missing_path_or_symbol_is_reported_with_its_line(tmp_path: Path) -> None:
    text = "One `src/jarvis/tools/gone.py`.\nTwo `src/jarvis/tools/gateway.py:Gateway.nope`.\n"
    report = ac.check(_repo(tmp_path, text))
    assert report.problems == [
        "docs/architecture/design/01-x.md:1 `src/jarvis/tools/gone.py`: no such path",
        "docs/architecture/design/01-x.md:2 `src/jarvis/tools/gateway.py:Gateway.nope`: "
        "no symbol Gateway.nope in that file",
    ]


def test_a_folded_package_path_matches_through_the_ellipsis(tmp_path: Path) -> None:
    text = "The tile `android/app/src/main/java/…/jarvis/shell/Tile.kt`.\n"
    assert ac.check(_repo(tmp_path, text)).problems == []


def test_a_path_on_a_branch_or_planned_is_listed_not_failed(tmp_path: Path) -> None:
    text = (
        "Plan: `docs/plans/r99.md`, on branch `r99-plan` (not yet in `main`).\n"
        "The kit (`deploy/kit/`, PLANNED).\n"
    )
    report = ac.check(_repo(tmp_path, text))
    assert report.problems == []
    assert report.elsewhere == [
        "docs/architecture/design/01-x.md:1 `docs/plans/r99.md`",
        "docs/architecture/design/01-x.md:2 `deploy/kit/`",
    ]


def test_words_that_only_look_like_names_are_not_citations(tmp_path: Path) -> None:
    text = "The job `docs-check`, the key `deploy.needs`, the field `tools_allowed`.\n"
    assert ac.check(_repo(tmp_path, text)).checked == 0


def test_code_blocks_are_skipped(tmp_path: Path) -> None:
    text = "```bash\ncat `src/jarvis/none.py`\n```\n"
    assert ac.check(_repo(tmp_path, text)).problems == []


def test_main_exits_one_on_a_problem(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, "Gone: `src/jarvis/gone.py`.\n")
    assert ac.main(["--root", str(repo)]) == 1
    assert "no such path" in capsys.readouterr().out


def test_this_repositorys_design_document_cites_only_what_exists() -> None:
    report = ac.check(ROOT)
    assert report.problems == []
    assert report.checked > 700
