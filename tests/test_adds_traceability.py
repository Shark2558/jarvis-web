"""The ADD's traceability generator (scripts/docs/adds_traceability.py).

Every case builds its own tiny workbook and a tiny fake repository in tmp_path; the real
requirements workbook (which holds personal remarks) is never read here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

openpyxl = pytest.importorskip("openpyxl")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "docs" / "adds_traceability.py"
HEADER = ["Serial No.", "Phase", "Module", "Feature", "Type", "Status", "Remarks", "Release"]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("adds_traceability", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["adds_traceability"] = module
    spec.loader.exec_module(module)
    return module


tr = _load()


def _workbook(path: Path, rows: list[list[object]], sheet: str = "Requirements") -> Path:
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = sheet
    ws.append(HEADER)
    for row in rows:
        ws.append(row)
    ws.append([None, None, None, "Summary block", None, None, None, None])
    book.save(path)
    return path


def _repo(root: Path) -> Path:
    (root / "src/jarvis/wardrobe").mkdir(parents=True)
    (root / "src/jarvis/wardrobe/catalog.py").write_text(
        "# INV-01: map wardrobe storage places\n", encoding="utf-8"
    )
    (root / "src/jarvis/vitals").mkdir(parents=True)
    (root / "src/jarvis/vitals/board.py").write_text(
        "def quota_board(): 'every quota and limit'\n", encoding="utf-8"
    )
    return root


ROWS: list[list[object]] = [
    [1, "P5", "Wardrobe", "INV-01: Map wardrobe storage", "Free", "Done", "secret remark", "R13"],
    [2, "P7", "Vitals", "Vitals board: every quota and limit", "Free", "Done", "", "R4"],
    [3, "P7", "Vitals", "Telescope calibration wizard", "Free", "Done", "", "R4"],
    [4, "P6", "Brand new module", "Something new", "Free", "Pending", "", "R20"],
    ["5", "P5", "Wardrobe", "INV-02: Pending piece", "Free", "Next up", "", "R13"],
]


def test_reads_numbered_rows_only_and_skips_the_summary(tmp_path: Path) -> None:
    reqs = tr.read_workbook(_workbook(tmp_path / "w.xlsx", ROWS))
    assert [r.serial for r in reqs] == [1, 2, 3, 4, 5]
    assert reqs[0].module == "Wardrobe"
    assert reqs[3].release == "R20"


def test_missing_sheet_or_columns_are_refused(tmp_path: Path) -> None:
    with pytest.raises(tr.WorkbookError, match="Requirements"):
        tr.read_workbook(_workbook(tmp_path / "a.xlsx", ROWS, sheet="Other"))
    book = openpyxl.Workbook()
    book.active.title = "Requirements"
    book.active.append(["Serial No.", "Feature"])
    book.save(tmp_path / "b.xlsx")
    with pytest.raises(tr.WorkbookError, match="missing columns"):
        tr.read_workbook(tmp_path / "b.xlsx")


def test_done_rows_are_located_by_case_id_or_their_own_words(tmp_path: Path) -> None:
    reqs = tr.read_workbook(_workbook(tmp_path / "w.xlsx", ROWS))
    rows = tr.build_rows(reqs, tr.CodeIndex(_repo(tmp_path / "repo")))
    by = {r.req.serial: r for r in rows}
    assert by[1].code == "`src/jarvis/wardrobe/catalog.py`"
    assert by[2].code == "`src/jarvis/vitals/board.py`"
    assert by[3].code == tr.NOT_CONFIRMED  # built, but its words are nowhere: never guessed
    assert by[5].code == "—"  # not Done


def test_unknown_module_has_no_home_and_is_listed(tmp_path: Path) -> None:
    reqs = tr.read_workbook(_workbook(tmp_path / "w.xlsx", ROWS))
    rows = tr.build_rows(reqs, tr.CodeIndex(_repo(tmp_path / "repo")))
    text = tr.render(rows, tr.DEFAULT_VERSION, "w.xlsx")
    assert "| 4 | Something new | — | — | R20 | Pending | — |" in text
    assert "Modules with no architectural home:** Brand new module." in text


def test_rendered_chapter_has_version_line_summary_and_change_log(tmp_path: Path) -> None:
    reqs = tr.read_workbook(_workbook(tmp_path / "w.xlsx", ROWS))
    rows = tr.build_rows(reqs, tr.CodeIndex(_repo(tmp_path / "repo")))
    text = tr.render(rows, tr.DEFAULT_VERSION, "w.xlsx")
    assert text.startswith("Version v6.4.1 · ")
    assert "3 Done, 1 Next up, 1 Pending" in text
    assert "located from their own words:** 2 of 3" in text
    assert text.rstrip().splitlines()[-1].startswith("| v6.4.1 |")
    assert "## Change log" in text
    assert "secret remark" not in text  # remarks never leave the workbook


def test_titles_are_cut_at_a_word_and_pipes_escaped() -> None:
    long = "word " * 40
    cut = tr.short_title(long)
    assert len(cut) <= tr.TITLE_MAX and cut.endswith("…")
    assert tr.short_title("a | b") == "a / b"


def test_distinctive_words_skip_stop_words_and_short_ones() -> None:
    assert tr.distinctive_words("Vitals board: every quota and limit") == [
        "vitals", "board", "quota", "limit"
    ]


def test_main_writes_the_chapter_and_rejects_a_bad_workbook(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path / "repo")
    book = _workbook(tmp_path / "w.xlsx", ROWS)
    assert tr.main([str(book), "--repo", str(repo), "--out", "out/10.md"]) == 0
    assert (repo / "out/10.md").read_text(encoding="utf-8").startswith("Version ")
    assert "2 of 3 Done rows located" in capsys.readouterr().out
    bad = tmp_path / "bad.xlsx"
    bad.write_text("not a workbook", encoding="utf-8")
    assert tr.main([str(bad), "--repo", str(repo)]) == 2


def test_kotlin_package_folders_are_folded_in_located_paths() -> None:
    shown = tr._shown("android/core/src/main/kotlin/io/github/someone/jarvis/core/Rules.kt")
    assert shown == "`android/core/src/main/kotlin/…/jarvis/core/Rules.kt`"
