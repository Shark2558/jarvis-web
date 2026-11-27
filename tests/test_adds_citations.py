"""The ADD's citation check (scripts/docs/adds_citations.py).

The Architecture Design Document is kept privately on the owner's Drive, not in the repository.
Each case builds a tiny repository and a small fixture ADD folder beside it in tmp_path; the last
one checks the private copy against this repository only where `JARVIS_ADD_DIR` names it.
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
PRIVATE_ADD = ac.add_folder()  # read before the fixture below hides the variable


@pytest.fixture(autouse=True)
def _no_private_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every case names its own ADD folder: the owner's private copy never leaks in."""
    monkeypatch.delenv(ac.ADD_ENV, raising=False)


def _repo(tmp: Path, chapter: str) -> tuple[Path, Path]:
    """(a tiny repository, an ADD folder outside it holding one chapter)."""
    root = tmp / "repo"
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
    add = tmp / "add"
    add.mkdir()
    (add / "01-x.md").write_text(chapter, encoding="utf-8")
    (add / "notes.md").write_text("Not a chapter: `src/jarvis/gone.py`.\n", encoding="utf-8")
    return root, add


def test_existing_paths_symbols_and_methods_pass(tmp_path: Path) -> None:
    text = (
        "See `src/jarvis/tools/gateway.py:Gateway.execute`, `src/jarvis/tools/gateway.py:LIMIT`,\n"
        "`src/jarvis/tools/gateway.py:_tightened`, `src/jarvis/tools/gateway.py:Gateway.MAX`,\n"
        "`src/jarvis/tools/` and `Dockerfile` (`HEALTHCHECK`).\n"
    )
    report = ac.check(*_repo(tmp_path, text))
    assert report.problems == []
    assert report.checked == 6


def test_a_missing_path_or_symbol_is_reported_with_its_line(tmp_path: Path) -> None:
    text = "One `src/jarvis/tools/gone.py`.\nTwo `src/jarvis/tools/gateway.py:Gateway.nope`.\n"
    root, add = _repo(tmp_path, text)
    report = ac.check(root, add)
    assert report.problems == [
        f"{add.as_posix()}/01-x.md:1 `src/jarvis/tools/gone.py`: no such path",
        f"{add.as_posix()}/01-x.md:2 `src/jarvis/tools/gateway.py:Gateway.nope`: "
        "no symbol Gateway.nope in that file",
    ]


def test_a_folded_package_path_matches_through_the_ellipsis(tmp_path: Path) -> None:
    text = "The tile `android/app/src/main/java/…/jarvis/shell/Tile.kt`.\n"
    assert ac.check(*_repo(tmp_path, text)).problems == []


def test_a_path_on_a_branch_or_planned_is_listed_not_failed(tmp_path: Path) -> None:
    text = (
        "Plan: `docs/plans/r99.md`, on branch `r99-plan` (not yet in `main`).\n"
        "The kit (`deploy/kit/`, PLANNED).\n"
    )
    root, add = _repo(tmp_path, text)
    report = ac.check(root, add)
    assert report.problems == []
    assert report.elsewhere == [
        f"{add.as_posix()}/01-x.md:1 `docs/plans/r99.md`",
        f"{add.as_posix()}/01-x.md:2 `deploy/kit/`",
    ]


def test_words_that_only_look_like_names_are_not_citations(tmp_path: Path) -> None:
    text = "The job `docs-check`, the key `deploy.needs`, the field `tools_allowed`.\n"
    assert ac.check(*_repo(tmp_path, text)).checked == 0


def test_code_blocks_are_skipped(tmp_path: Path) -> None:
    text = "```bash\ncat `src/jarvis/none.py`\n```\n"
    assert ac.check(*_repo(tmp_path, text)).problems == []


def test_main_exits_one_on_a_problem(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, add = _repo(tmp_path, "Gone: `src/jarvis/gone.py`.\n")
    assert ac.main(["--root", str(repo), "--add-dir", str(add)]) == 1
    assert "no such path" in capsys.readouterr().out


def test_main_reads_the_folder_from_the_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, add = _repo(tmp_path, "Gone: `src/jarvis/gone.py`.\n")
    monkeypatch.setenv(ac.ADD_ENV, str(add))
    assert ac.main(["--root", str(repo)]) == 1
    assert "01-x.md:1 `src/jarvis/gone.py`: no such path" in capsys.readouterr().out


@pytest.mark.parametrize("where", ["none", "argument", "environment"])
def test_main_skips_cleanly_when_the_private_copy_is_not_here(
    where: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _ = _repo(tmp_path, "Gone: `src/jarvis/gone.py`.\n")
    missing = str(tmp_path / "not-here")
    argv = ["--root", str(repo)] + (["--add-dir", missing] if where == "argument" else [])
    if where == "environment":
        monkeypatch.setenv(ac.ADD_ENV, missing)
    assert ac.main(argv) == 0
    assert capsys.readouterr().out.splitlines() == [ac.ADD_SKIPPED]


@pytest.mark.skipif(PRIVATE_ADD is None, reason="JARVIS_ADD_DIR names no private copy here")
def test_the_private_copy_cites_only_what_exists_in_this_repository() -> None:
    assert PRIVATE_ADD is not None
    report = ac.check(ROOT, PRIVATE_ADD)
    assert report.problems == []
    assert report.checked > 700
