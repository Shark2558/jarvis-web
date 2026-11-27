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


def _rows(tmp_path: Path, **maps: dict[int, str]) -> dict[int, object]:
    """The fake workbook's rows against the fake repo, with only the given reviewed maps."""
    reqs = tr.read_workbook(_workbook(tmp_path / "w.xlsx", ROWS))
    repo = tmp_path / "repo" if (tmp_path / "repo").exists() else _repo(tmp_path / "repo")
    rows = tr.build_rows(
        reqs,
        tr.CodeIndex(repo),
        overrides=maps.get("overrides", {}),
        unlocated=maps.get("unlocated", {}),
    )
    return {r.req.serial: r for r in rows}


def test_done_rows_are_located_by_case_id_or_their_own_words(tmp_path: Path) -> None:
    reqs = tr.read_workbook(_workbook(tmp_path / "w.xlsx", ROWS))
    rows = tr.build_rows(
        reqs, tr.CodeIndex(_repo(tmp_path / "repo")), overrides={}, unlocated={}
    )
    by = {r.req.serial: r for r in rows}
    assert by[1].code == "`src/jarvis/wardrobe/catalog.py`"
    assert by[2].code == "`src/jarvis/vitals/board.py`"
    assert by[3].code == tr.NOT_CONFIRMED  # built, but its words are nowhere: never guessed
    assert by[5].code == "—"  # not Done


def test_unknown_module_has_no_home_and_is_listed(tmp_path: Path) -> None:
    reqs = tr.read_workbook(_workbook(tmp_path / "w.xlsx", ROWS))
    rows = tr.build_rows(
        reqs, tr.CodeIndex(_repo(tmp_path / "repo")), overrides={}, unlocated={}
    )
    text = tr.render(rows, tr.DEFAULT_VERSION, "w.xlsx")
    assert "| 4 | Something new | — | — | R20 | Pending | — |" in text
    assert "Modules with no architectural home:** Brand new module." in text


def test_rendered_chapter_has_version_line_summary_and_change_log(tmp_path: Path) -> None:
    reqs = tr.read_workbook(_workbook(tmp_path / "w.xlsx", ROWS))
    rows = tr.build_rows(
        reqs, tr.CodeIndex(_repo(tmp_path / "repo")), overrides={}, unlocated={}
    )
    text = tr.render(rows, tr.DEFAULT_VERSION, "w.xlsx")
    assert text.startswith("Version v6.4.2 · ")
    assert "3 Done, 1 Next up, 1 Pending" in text
    assert "**Done rows located:** 2 of 3" in text
    assert text.rstrip().splitlines()[-1].startswith("| v6.4.2 |")
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
    assert "of 3 Done rows located" in capsys.readouterr().out
    bad = tmp_path / "bad.xlsx"
    bad.write_text("not a workbook", encoding="utf-8")
    assert tr.main([str(bad), "--repo", str(repo)]) == 2


def test_kotlin_package_folders_are_folded_in_located_paths() -> None:
    shown = tr._shown("android/core/src/main/kotlin/io/github/someone/jarvis/core/Rules.kt")
    assert shown == "`android/core/src/main/kotlin/…/jarvis/core/Rules.kt`"


# ---- reviewed pointers, use-case tests, reasons (the ADD verification, chapter 13) ------------
def test_a_reviewed_pointer_wins_over_the_words(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / "src/jarvis/vitals/service.py").write_text("# the board itself\n", encoding="utf-8")
    by = _rows(tmp_path, overrides={2: "src/jarvis/vitals/service.py"})
    assert by[2].code == "`src/jarvis/vitals/service.py`"
    assert by[2].how == "reviewed"


def test_a_pointer_to_a_missing_path_or_a_row_not_done_is_never_shown(tmp_path: Path) -> None:
    _repo(tmp_path / "repo")
    by = _rows(tmp_path, overrides={2: "src/jarvis/gone.py", 5: "src/jarvis/vitals/board.py"})
    assert by[2].code == "`src/jarvis/vitals/board.py`" and by[2].how == "words"
    assert by[5].code == "—"  # Next up: a pointer never makes a row look built
    reqs = tr.read_workbook(tmp_path / "w.xlsx")
    stale = tr.stale_pointers(
        reqs, tr.CodeIndex(tmp_path / "repo"),
        {2: "src/jarvis/gone.py", 5: "src/jarvis/vitals/board.py", 99: "x"}, {},
    )
    assert stale == [
        "row 2: src/jarvis/gone.py does not exist",
        "row 5: not Done (Next up)",
        "row 99: no such row",
    ]


def test_a_row_that_cannot_be_located_says_why(tmp_path: Path) -> None:
    _repo(tmp_path / "repo")
    by = _rows(tmp_path, unlocated={3: "the telescope was retired in R9"})
    assert by[3].code == "not located: the telescope was retired in R9"
    assert by[3].how == "unlocated"


def test_a_use_case_row_points_at_the_test_named_after_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / "tests/browser").mkdir(parents=True)
    (repo / "tests/browser/test_a_page.py").write_text(
        "def test_inv01_the_page_shows_places(): ...\n", encoding="utf-8"
    )
    (repo / "tests/test_wardrobe_places.py").write_text(
        "def test_inv01_storage_places_are_mapped(): ...\ndef test_inv10_size(): ...\n",
        encoding="utf-8",
    )
    by = _rows(tmp_path)
    assert by[1].code == "`tests/test_wardrobe_places.py` (test)"  # unit tests before browser
    assert by[1].how == "test"


def test_names_like_inv_1_count_but_inv10_never_matches_inv_01(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / "tests").mkdir()
    (repo / "tests/test_a.py").write_text("def test_inv10_size(): ...\n", encoding="utf-8")
    (repo / "tests/test_b.py").write_text("def test_inv_1_places(): ...\n", encoding="utf-8")
    assert _rows(tmp_path)[1].code == "`tests/test_b.py` (test)"


def test_a_use_case_with_no_named_test_uses_a_test_file_that_names_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / "tests").mkdir()
    (repo / "tests/test_store.py").write_text("# covers INV-01 and INV-02\n", encoding="utf-8")
    assert _rows(tmp_path)[1].code == "`tests/test_store.py` (test)"


def test_a_use_case_with_no_test_at_all_falls_back_to_the_code(tmp_path: Path) -> None:
    by = _rows(tmp_path)
    assert by[1].code == "`src/jarvis/wardrobe/catalog.py`" and by[1].how == "words"


def test_the_summary_counts_each_kind_of_pointer(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / "tests").mkdir()
    (repo / "tests/test_w.py").write_text("def test_inv01_x(): ...\n", encoding="utf-8")
    reqs = tr.read_workbook(_workbook(tmp_path / "w.xlsx", ROWS))
    rows = tr.build_rows(
        reqs, tr.CodeIndex(repo), overrides={2: "src/jarvis/vitals/board.py"},
        unlocated={3: "retired"},
    )
    text = tr.render(rows, tr.DEFAULT_VERSION, "w.xlsx")
    assert "**Done rows located:** 2 of 3: 1 by a pointer reviewed against the code" in text
    assert "1 by the test named after its use case, 0 by their own words" in text
    assert "1 not located, each with its reason; 0 \"location not confirmed\"" in text


def test_the_change_log_keeps_its_earlier_rows(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    book = _workbook(tmp_path / "w.xlsx", ROWS)
    old = "Version v6.4.1 · 27 Nov 2026, 15:00 IST · Release R6.4 · Status: Current · Owner: X"
    assert tr.main([str(book), "--repo", str(repo), "--out", "10.md", "--version-line", old]) == 0
    assert tr.main([str(book), "--repo", str(repo), "--out", "10.md",
                    "--change", "Pointers reviewed"]) == 0
    assert tr.main([str(book), "--repo", str(repo), "--out", "10.md",
                    "--change", "Pointers reviewed"]) == 0  # the same version: not repeated
    log = (repo / "10.md").read_text(encoding="utf-8").split("## Change log")[1]
    rows = [ln for ln in log.splitlines() if ln.startswith("| v")]
    assert [r.split(" | ")[0] for r in rows] == ["| v6.4.1", "| v6.4.2"]
    assert "Pointers reviewed" in rows[1]


ROOT = Path(__file__).resolve().parents[1]


def test_every_reviewed_pointer_names_a_path_in_this_repository() -> None:
    missing = [f"{n}: {p}" for n, p in tr.OVERRIDES.items() if not (ROOT / p).exists()]
    assert missing == []
    assert not set(tr.OVERRIDES) & set(tr.NOT_LOCATED)
    assert all(len(reason) > 20 for reason in tr.NOT_LOCATED.values())
