# tests/test_book_gen_cli.py
"""R6 D4 (review fixes): the generator as the deploy job runs it. Its data files ship as package
data (a non-editable install finds them through importlib.resources); a stale `_book/` from an
earlier run is never served as this release; best effort names the reason in one line (a file
name and a code place, never content or a path); a missing package still writes an error
release.json; a dirty checkout is never written as its commit."""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest
from book_gen_fakes import ROOT, commit_all, fixture_repo

from jarvis.buildbook.gen import __main__ as cli
from jarvis.buildbook.gen import fallback, scrub, snapshot, write
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.model import Release

GEN = "src/jarvis/buildbook/gen/"
BOOK_FILES = ("book.json", "source.zip", "release.json")


def _package_data() -> dict[str, list[str]]:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return cfg["tool"]["setuptools"]["package-data"]


def _covered(rel: str, data: dict[str, list[str]]) -> bool:
    """Is a file under src/jarvis/ matched by a package-data pattern of a package above it?"""
    inside = rel.removeprefix("src/")
    for package, patterns in data.items():
        base = package.replace(".", "/") + "/"
        if inside.startswith(base):
            sub = inside[len(base) :]
            if any(fnmatch.fnmatchcase(sub, p) for p in patterns):
                return True
    return False


# ---- package data (the deploy job installs with `pip install .`, not -e) ---------------------
def test_every_data_file_of_the_generator_is_package_data() -> None:
    tracked = Repo.from_git(ROOT).under(GEN)
    data_files = [f for f in tracked if not f.endswith(".py")]
    assert {"redact.json", "fake_secrets.txt"} <= {f.rsplit("/", 1)[1] for f in data_files}
    missing = [f for f in data_files if not _covered(f, _package_data())]
    assert missing == [], f"not shipped in the wheel: {missing}"


def test_the_loaders_read_through_importlib_resources_not_the_checkout() -> None:
    pkg = files("jarvis.buildbook.gen")
    assert str(scrub.REDACT_FILE) == str(pkg / "redact.json")
    assert str(snapshot.FAKES_FILE) == str(pkg / "fake_secrets.txt")
    assert scrub.load_redact() and snapshot.load_fakes()


def test_a_missing_data_file_is_still_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        scrub.load_redact(tmp_path / "redact.json")
    with pytest.raises(FileNotFoundError):
        snapshot.load_fakes(tmp_path / "fake_secrets.txt")


# ---- a stale book is never served as this release --------------------------------------------
def _stale(out: Path) -> None:
    out.mkdir(parents=True)
    for name in (*BOOK_FILES, ".book.json.tmp"):
        (out / name).write_bytes(b"old")


def test_a_stale_book_is_cleared_even_when_the_build_cannot_start(tmp_path: Path) -> None:
    out = tmp_path / "o"
    _stale(out)
    assert cli.main(["--repo", str(tmp_path), "--out", str(out), "--best-effort"]) == 0
    assert sorted(p.name for p in out.iterdir()) == []


def test_a_failed_build_leaves_only_its_error_release(tmp_path: Path) -> None:
    root, out = fixture_repo(tmp_path), tmp_path / "o"
    _stale(out)
    assert cli.main(["--repo", str(root), "--out", str(out)]) == 1  # no licence table: fails
    assert sorted(p.name for p in out.iterdir()) == []
    assert cli.main(["--repo", str(root), "--out", str(out), "--best-effort"]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["release.json"]


def test_clear_unlinks_only_the_book_files(tmp_path: Path) -> None:
    _stale(tmp_path / "o")
    (tmp_path / "o" / "keep.txt").write_text("x", encoding="utf-8")
    fallback.clear(tmp_path / "o")
    fallback.clear(tmp_path / "absent")  # nothing there: nothing to do, nothing created
    assert [p.name for p in (tmp_path / "o").iterdir()] == ["keep.txt"]
    assert not (tmp_path / "absent").exists()


# ---- best effort names the reason in one line ------------------------------------------------
def test_an_unexpected_error_names_the_file_and_the_place_never_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, out = fixture_repo(tmp_path), tmp_path / "o"
    monkeypatch.setattr(scrub, "REDACT_FILE", tmp_path / "gone" / "redact.json")
    scrub.default_scrubber.cache_clear()
    try:
        assert cli.main(["--repo", str(root), "--out", str(out), "--best-effort"]) == 0
    finally:
        scrub.default_scrubber.cache_clear()
    error = Release.model_validate_json((out / "release.json").read_bytes()).error or ""
    assert error.startswith("unexpected FileNotFoundError (redact.json) at buildbook/gen/")
    assert str(tmp_path) not in error and "\n" not in error
    err = capsys.readouterr().err
    assert error in err and str(tmp_path) not in err


def test_a_git_failure_says_what_git_said_without_the_path(tmp_path: Path) -> None:
    with pytest.raises(GenError) as caught:
        Repo.from_git(tmp_path)
    msg = str(caught.value)
    assert "not a git repository" in msg and str(tmp_path) not in msg


def test_without_its_packages_best_effort_still_writes_an_error_release(tmp_path: Path) -> None:
    root, out = fixture_repo(tmp_path), tmp_path / "o"
    _stale(out)
    code = (
        "import sys; sys.modules['pydantic'] = None\n"
        "from jarvis.buildbook.gen import __main__ as m\n"
        f"sys.exit(m.main(['--repo', {str(root)!r}, '--out', {str(out)!r}, '--best-effort']))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in out.iterdir()) == ["release.json"]
    raw = (out / "release.json").read_bytes()
    rel = Release.model_validate_json(raw)
    assert rel.error and "pydantic" in rel.error and rel.label == "R2.1"
    assert rel.sha == Repo.from_git(root).sha and rel.committed_at
    assert raw == write.release_bytes(rel)  # the same bytes the full generator writes
    assert "pydantic" in done.stderr


def test_without_its_packages_a_plain_run_fails(tmp_path: Path) -> None:
    code = (
        "import sys; sys.modules['pydantic'] = None\n"
        "from jarvis.buildbook.gen import __main__ as m\n"
        f"sys.exit(m.main(['--repo', {str(tmp_path)!r}, '--check']))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 1 and "pydantic" in done.stderr


def test_the_fallback_imports_the_standard_library_only() -> None:
    src = (ROOT / GEN / "fallback.py").read_text(encoding="utf-8")
    imports = [ln.split()[1] for ln in src.splitlines() if ln.startswith(("import ", "from "))]
    assert all(m.split(".")[0] in sys.stdlib_module_names or m == "__future__" for m in imports)


# ---- a dirty checkout is never written as its commit -----------------------------------------
def test_a_checkout_knows_when_tracked_files_changed(tmp_path: Path) -> None:
    root = fixture_repo(tmp_path)
    assert Repo.from_git(root).dirty is False
    (root / "untracked.txt").write_text("x", encoding="utf-8")
    assert Repo.from_git(root).dirty is False  # untracked files are never read
    (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    assert Repo.from_git(root).dirty is True
    commit_all(root, "edit")
    assert Repo.from_git(root).dirty is False
    (root / "staged.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "staged.txt"], cwd=root, check=True)
    assert Repo.from_git(root).dirty is True


def test_a_dirty_checkout_is_refused_when_writing(tmp_path: Path) -> None:
    root, out = fixture_repo(tmp_path), tmp_path / "o"
    (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    assert cli.main(["--repo", str(root), "--out", str(out), "--best-effort"]) == 0
    rel = json.loads((out / "release.json").read_text(encoding="utf-8"))
    assert "uncommitted" in rel["error"] and not (out / "book.json").exists()


# ---- the deploy job and hand deploys ---------------------------------------------------------
def _deploy_steps() -> list[dict[str, object]]:
    import yaml

    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps: list[dict[str, object]] = ci["jobs"]["deploy"]["steps"]
    return steps


def test_the_book_is_built_before_the_deploy_job_holds_google_credentials() -> None:
    steps = _deploy_steps()
    auth = next(
        i for i, s in enumerate(steps) if "google-github-actions/auth" in str(s.get("uses"))
    )
    book = [i for i, s in enumerate(steps) if "buildbook" in str(s.get("run", ""))]
    installs = [i for i, s in enumerate(steps) if "requirements.lock" in str(s.get("run", ""))]
    assert book and installs and max(book + installs) < auth


def test_the_deploy_runs_the_generator_from_the_checkout_and_never_fails_on_it() -> None:
    steps = _deploy_steps()
    gen = next(s for s in steps if "jarvis.buildbook.gen" in str(s.get("run", "")))
    assert "PYTHONPATH=src" in str(gen["run"]) and "--best-effort" in str(gen["run"])
    assert gen.get("continue-on-error") is True
    for s in steps:
        if "requirements.lock" in str(s.get("run", "")):
            assert s.get("continue-on-error") is True
