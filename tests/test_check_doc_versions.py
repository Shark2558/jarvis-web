# tests/test_check_doc_versions.py -- R6.1 D4 (acceptance check 3): every docs/plans/*.md and
# docs/architecture/*.md opens with its version line and ends with its change log
# (scripts/check_doc_versions.py, run by CI's test job, never by the deploy job).
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_doc_versions.py"
BACKFILL = ROOT / "docs" / "github-backfill.tsv"

LINE = (
    "Version v6.1.1 · 11 Nov 2026, 12:00 IST · Release R6.1 · Status: Current · Owner: 🛠 Mark XIII"
)
HEAD = "| Version | Date | Release | What changed | By |\n|---|---|---|---|---|\n"
LOG = (
    "## Change log\n\n| Version | Date | Release | What changed | By |\n|---|---|---|---|---|\n"
    "| v6.1.1 | 11 Nov 2026 | R6.1 | First edition | 🛠 Mark XIII |\n"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_doc_versions", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cdv = _load()


def doc(tmp: Path, rel: str, text: str) -> Path:
    path = tmp / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


GOOD = f"{LINE}\n\n# A plan\n\nBody.\n\n## Risks\n\n- One.\n\n{LOG}"


# ---- one file -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "line",
    [
        LINE,
        "Version v0.9.0 · 1 Nov 2026 · Release Slice 9 · Status: Superseded by the build log · "
        "Owner: 🛠 Mark V",
        "Version v5.1.1 · 10 Nov 2026 · Release R5.1 · Status: Superseded by the build log · "
        "Owner: 🛠 Mark XI",
        "Version v0.12.0 · 3 Nov 2026 · Release Slice 12 · Status: Superseded by the build log · "
        "Owner: 🛠 Mark VII–VIII",
    ],
)
def test_good_version_lines_pass(line: str) -> None:
    assert cdv.problems(f"{line}\n\n# T\n\n{LOG}") == []


@pytest.mark.parametrize(
    "line",
    [
        "# A plan",  # no version line at all
        "Version 6.1.1 · 11 Nov 2026 · Release R6.1 · Status: Current · Owner: 🛠 Mark XIII",
        "Version v6.1.1 · 2026-11-11 · Release R6.1 · Status: Current · Owner: 🛠 Mark XIII",
        "Version v6.1.1 · 11 Nov 2026 · R6.1 · Status: Current · Owner: 🛠 Mark XIII",
        "Version v6.1.1 · 11 Nov 2026 · Release R6.1 · Owner: 🛠 Mark XIII",
        "Version v6.1.1 · 11 Nov 2026 · Release R6.1 · Status: Current",
        "Status: PLAN v1 · 2026-11-05 · branch r4-plan",
    ],
)
def test_a_missing_or_malformed_version_line_fails(line: str) -> None:
    got = cdv.problems(f"{line}\n\n# T\n\n{LOG}")
    assert got and "version line" in got[0]


def test_the_version_line_must_be_the_first_line() -> None:
    assert cdv.problems(f"# T\n\n{LINE}\n\n{LOG}")


@pytest.mark.parametrize(
    "tail",
    [
        "",  # no change log
        "## Change log\n\nNothing yet.\n",  # a heading, no table
        "## Change log\n\n" + HEAD,
        "## Change log\n\n| Version | Date | What changed |\n|---|---|---|\n"
        "| v1.0.0 | 1 Nov 2026 | x |\n",
        "## Change log\n\n" + HEAD + "| 1.0 | 1 Nov 2026 | R1 | x | y |\n",  # not a version
        f"{LOG}\n## Sources\n\n- a page\n",  # not at the end
    ],
    ids=["none", "no-table", "no-rows", "wrong-columns", "bad-version", "not-last"],
)
def test_a_missing_or_malformed_change_log_fails(tail: str) -> None:
    got = cdv.problems(f"{LINE}\n\n# T\n\nBody.\n\n{tail}")
    assert got and "change log" in got[-1]


def test_a_numbered_change_log_heading_is_fine() -> None:
    assert (
        cdv.problems(f"{LINE}\n\n# T\n\n{LOG.replace('## Change log', '## 14. Change log')}") == []
    )


# ---- the folders ----------------------------------------------------------------------------
def test_every_plan_and_architecture_doc_is_checked(tmp_path: Path) -> None:
    doc(tmp_path, "docs/plans/good.md", GOOD)
    doc(tmp_path, "docs/plans/bad.md", "# No version\n")
    doc(tmp_path, "docs/architecture/JARVIS-Architecture.md", "# Guide\n")
    doc(tmp_path, "docs/architecture/diagrams/notes.md", "# not checked: a sub-folder\n")
    doc(tmp_path, "docs/other.md", "# not checked: another folder\n")

    found = cdv.check(tmp_path)

    assert sorted(found) == ["docs/architecture/JARVIS-Architecture.md", "docs/plans/bad.md"]
    assert all(len(v) == 2 for v in found.values())  # both the line and the log are missing


def test_a_tree_without_an_architecture_folder_is_fine(tmp_path: Path) -> None:
    doc(tmp_path, "docs/plans/good.md", GOOD)
    assert cdv.check(tmp_path) == {}


def test_no_plans_at_all_is_an_error_not_a_pass(tmp_path: Path) -> None:
    assert cdv.main(["--root", str(tmp_path)]) == 1


def test_the_cli_lists_what_is_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc(tmp_path, "docs/plans/good.md", GOOD)
    assert cdv.main(["--root", str(tmp_path)]) == 0
    doc(tmp_path, "docs/plans/bad.md", "# No version\n")
    assert cdv.main(["--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "docs/plans/bad.md" in out and "Version v" in out


def test_the_script_runs_with_the_standard_library_alone(tmp_path: Path) -> None:
    doc(tmp_path, "docs/plans/good.md", GOOD)
    done = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stdout + done.stderr


# ---- this repository --------------------------------------------------------------------------
def test_this_repository_passes() -> None:
    assert cdv.check(ROOT) == {}


def _tsv() -> dict[str, tuple[str, str]]:
    """'Slice 9' / 'R6' -> (version, Mark) from the back-fill map (releases, not hotfixes)."""
    out = {}
    for ln in BACKFILL.read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("#"):
            continue
        _n, ver, title, mark, kind, _pre = ln.split("\t")
        if kind == "release":
            name = re.match(r"^(Slice \w+|R[\d.]+) ", title.split(" · ")[1])
            assert name, title
            out[name.group(1)] = (ver, mark.replace("-", "–"))
    return out


def test_back_filled_plans_carry_their_release_version_and_mark() -> None:
    """Release plans: v<release>.1 (R6 -> v6.0.1); slice plans: the map's own version."""
    tsv = _tsv()
    seen = 0
    for path in sorted((ROOT / "docs" / "plans").glob("*.md")):
        first = path.read_text(encoding="utf-8").splitlines()[0]
        m = re.match(
            r"^Version (v\S+) · .+ · Release (.+?) · Status: (.+?) · Owner: 🛠 Mark (\S+)$", first
        )
        assert m, path.name
        version, release, status, mark = m.groups()
        if release not in tsv:
            continue  # R6.1 itself, and slices that shipped without a pull request of their own
        seen += 1
        ver, want_mark = tsv[release]
        if release.startswith("R"):
            major, minor, _ = ver[1:].split(".")
            assert version == f"v{major}.{minor}.1", path.name
        else:
            assert version == ver, path.name
        assert (mark, status) == (want_mark, "Superseded by the build log"), path.name
    assert seen == 17


# ---- CI -----------------------------------------------------------------------------------------
def test_ci_runs_it_in_the_test_job_only() -> None:
    ci: dict[str, Any] = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"))
    where = [
        name
        for name, job in ci["jobs"].items()
        if "check_doc_versions.py" in "\n".join(str(s.get("run", "")) for s in job.get("steps", []))
    ]
    assert where == ["test"]
