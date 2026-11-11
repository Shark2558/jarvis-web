# tests/test_markdy_export.py — R6.1 D2: scripts/markdy_export.py's own logic, the CLI stubbed.
"""File discovery, the privacy rule, lint / verify reporting, the export manifest, staleness,
orphans and exit codes. The Markdy CLI and the browser are fakes (tests/markdy_fakes.py): these
tests never need Node or Chromium. The real CLI runs in CI's `docs` job."""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from markdy_fakes import GOOD_SOURCE, ExplodingRenderer, FakeCli, FakeRenderer

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "markdy_export", ROOT / "scripts" / "markdy_export.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["markdy_export"] = module
    spec.loader.exec_module(module)
    return module


mx = _load()


def _write(folder: Path, stem: str, text: str = GOOD_SOURCE) -> Path:
    path = folder / f"{stem}.markdy"
    path.write_text(text, encoding="utf-8")
    return path


def _run(
    folder: Path, *args: str, cli: FakeCli | None = None, renderer: FakeRenderer | None = None
) -> int:
    return int(
        mx.run(
            mx.parse_args([*args]),
            cli=cli or FakeCli(),
            renderer=renderer or FakeRenderer(),
            folder=folder,
        )
    )


def _manifest(folder: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads((folder / mx.MANIFEST_NAME).read_text(encoding="utf-8"))
    return data


# ---- discovery -----------------------------------------------------------------------------------
def test_discover_finds_only_markdy_files_in_name_order(tmp_path: Path) -> None:
    _write(tmp_path, "02-b")
    _write(tmp_path, "01-a")
    (tmp_path / "01-a.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    _write(tmp_path / "sub", "03-c")

    found = mx.discover(tmp_path)

    assert [p.name for p in found] == ["01-a.markdy", "02-b.markdy"]


def test_discover_empty_folder_is_empty(tmp_path: Path) -> None:
    assert mx.discover(tmp_path) == ()


def test_discover_by_name_keeps_only_those_and_refuses_an_unknown_one(tmp_path: Path) -> None:
    _write(tmp_path, "01-a")
    _write(tmp_path, "02-b")

    assert [p.stem for p in mx.discover(tmp_path, ["02-b.markdy"])] == ["02-b"]
    with pytest.raises(mx.SetupError, match="no diagram named 09-x"):
        mx.discover(tmp_path, ["09-x"])


def test_missing_folder_is_a_setup_error(tmp_path: Path) -> None:
    with pytest.raises(mx.SetupError, match="no diagram folder"):
        mx.discover(tmp_path / "nope")


# ---- the privacy rule (plan decision 5) ----------------------------------------------------------
def test_a_good_source_passes_the_privacy_rule(tmp_path: Path) -> None:
    assert mx.privacy_problems(_write(tmp_path, "01-a")) == []


@pytest.mark.parametrize(
    ("text", "words"),
    [
        (GOOD_SOURCE.replace("badge false", "badge true"), "badge false"),
        (GOOD_SOURCE.split("player:")[0], "badge false"),
        (GOOD_SOURCE + "    share true\n", "share"),
        (GOOD_SOURCE.replace('"A"', '"mail owner@example.com"'), "e-mail"),
        (GOOD_SOURCE.replace('"A"', '"see https://example.org/x"'), "web address"),
    ],
)
def test_the_privacy_rule_names_what_is_wrong(tmp_path: Path, text: str, words: str) -> None:
    problems = mx.privacy_problems(_write(tmp_path, "01-a", text))

    assert problems and all(p.diagram == "01-a" and p.step == "privacy" for p in problems)
    assert any(words in p.detail for p in problems)


# ---- lint and verify -----------------------------------------------------------------------------
def test_lint_and_verify_are_called_with_the_pinned_flags(tmp_path: Path) -> None:
    path = _write(tmp_path, "01-a")
    cli = FakeCli()

    assert mx.check_source(path, cli) == []
    assert cli.calls == [
        ("lint", str(path), "--strict"),
        ("verify", str(path), "--quality", "showcase", "--json"),
    ]


def test_a_lint_failure_names_the_diagram_and_the_cli_words(tmp_path: Path) -> None:
    path = _write(tmp_path, "01-a")
    cli = FakeCli(lint_fail={"01-a": "ERR  line 4: unknown node kind 'sevice'\nmarkdy lint: FAIL"})

    problems = mx.check_source(path, cli)

    assert [(p.diagram, p.step) for p in problems] == [("01-a", "lint")]
    assert "line 4: unknown node kind" in problems[0].detail


def test_a_failed_quality_gate_names_the_failed_checks(tmp_path: Path) -> None:
    path = _write(tmp_path, "01-a")
    cli = FakeCli(verify_fail={"01-a": ("node_overlap_free", "label_legibility")})

    problems = mx.check_source(path, cli)

    assert [(p.diagram, p.step) for p in problems] == [("01-a", "verify")]
    assert "node_overlap_free" in problems[0].detail and "label_legibility" in problems[0].detail


def test_a_verify_answer_that_is_not_json_is_a_problem_not_a_crash(tmp_path: Path) -> None:
    path = _write(tmp_path, "01-a")
    cli = FakeCli(verify_raw={"01-a": "Error: cannot read file"})

    problems = mx.check_source(path, cli)

    assert [(p.step, p.diagram) for p in problems] == [("verify", "01-a")]
    assert "not a report" in problems[0].detail


def test_verify_warnings_fail_the_showcase_gate(tmp_path: Path) -> None:
    path = _write(tmp_path, "01-a")
    report = json.dumps({"passed": True, "errorCount": 0, "warningCount": 2, "checks": []})
    cli = FakeCli(verify_raw={"01-a": report})

    problems = mx.check_source(path, cli)

    assert problems and "2 warning" in problems[0].detail


def test_lint_is_skipped_when_the_privacy_rule_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, "01-a", GOOD_SOURCE.replace("badge false", "badge true"))
    cli = FakeCli()

    problems = mx.check_source(path, cli)

    assert [p.step for p in problems] == ["privacy"]
    assert cli.calls == []


# ---- export --------------------------------------------------------------------------------------
def test_export_writes_svg_png_and_the_manifest(tmp_path: Path) -> None:
    _write(tmp_path, "01-a")
    _write(tmp_path, "02-b", GOOD_SOURCE.replace('"A"', '"Other"'))
    renderer = FakeRenderer()

    assert _run(tmp_path, renderer=renderer) == 0

    assert renderer.calls == 2 and renderer.entered == 1  # one browser for all diagrams
    for stem in ("01-a", "02-b"):
        assert (tmp_path / f"{stem}.svg").read_text(encoding="utf-8").startswith("<svg")
        assert (tmp_path / f"{stem}.png").read_bytes().startswith(b"\x89PNG")
    manifest = _manifest(tmp_path)
    assert manifest["cli"] == mx.CLI_VERSION
    entry = manifest["diagrams"]["01-a"]  # type: ignore[index]
    assert entry["source"] == mx.digest((tmp_path / "01-a.markdy").read_bytes())
    assert entry["png"] == mx.digest((tmp_path / "01-a.png").read_bytes())


def test_export_twice_gives_the_same_bytes(tmp_path: Path) -> None:
    _write(tmp_path, "01-a")
    assert _run(tmp_path) == 0
    first = (tmp_path / mx.MANIFEST_NAME).read_bytes()

    assert _run(tmp_path) == 0

    assert (tmp_path / mx.MANIFEST_NAME).read_bytes() == first


def test_a_diagram_that_fails_lint_is_not_exported(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(tmp_path, "01-a")
    _write(tmp_path, "02-b")
    cli = FakeCli(lint_fail={"02-b": "ERR  line 2: bad layout"})

    with caplog.at_level(logging.ERROR, logger="markdy_export"):
        assert _run(tmp_path, cli=cli) == 1

    assert (tmp_path / "01-a.png").exists() and not (tmp_path / "02-b.png").exists()
    assert "02-b: lint:" in caplog.text
    assert set(_manifest(tmp_path)["diagrams"]) == {"01-a"}  # type: ignore[arg-type]


def test_export_of_one_diagram_keeps_the_others_in_the_manifest(tmp_path: Path) -> None:
    _write(tmp_path, "01-a")
    _write(tmp_path, "02-b")
    assert _run(tmp_path) == 0
    _write(tmp_path, "02-b", GOOD_SOURCE.replace('"B"', '"Bee"'))

    assert _run(tmp_path, "02-b") == 0

    assert set(_manifest(tmp_path)["diagrams"]) == {"01-a", "02-b"}  # type: ignore[arg-type]
    assert _run(tmp_path, "--check") == 0


def test_an_svg_that_carries_a_share_link_is_refused(tmp_path: Path) -> None:
    _write(tmp_path, "01-a")
    renderer = FakeRenderer(svg_extra='<a href="https://markdy.com/playground/#code=abc">x</a>')

    assert _run(tmp_path, renderer=renderer) == 1

    assert not (tmp_path / "01-a.svg").exists()


def test_a_render_failure_is_reported_for_that_diagram(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(tmp_path, "01-a")

    class Broken(FakeRenderer):
        def __call__(self, source: str) -> tuple[str, bytes]:
            raise mx.ExportError("page error: boom")

    with caplog.at_level(logging.ERROR, logger="markdy_export"):
        assert _run(tmp_path, renderer=Broken()) == 1
    assert "01-a: export: page error: boom" in caplog.text


# ---- --check: missing or stale exports -----------------------------------------------------------
def test_check_passes_right_after_an_export_and_never_renders(tmp_path: Path) -> None:
    _write(tmp_path, "01-a")
    assert _run(tmp_path) == 0

    assert _run(tmp_path, "--check", renderer=ExplodingRenderer()) == 0


def test_check_fails_when_an_export_is_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(tmp_path, "01-a")
    assert _run(tmp_path) == 0
    (tmp_path / "01-a.png").unlink()

    with caplog.at_level(logging.ERROR, logger="markdy_export"):
        assert _run(tmp_path, "--check", renderer=ExplodingRenderer()) == 1
    assert "01-a: fresh: 01-a.png is missing" in caplog.text


def test_check_fails_when_the_source_changed_after_the_export(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(tmp_path, "01-a")
    assert _run(tmp_path) == 0
    _write(tmp_path, "01-a", GOOD_SOURCE.replace('"B"', '"Changed"'))

    with caplog.at_level(logging.ERROR, logger="markdy_export"):
        assert _run(tmp_path, "--check") == 1
    assert "01-a: fresh: the source changed since its export" in caplog.text


def test_check_fails_when_an_export_was_edited_by_hand(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(tmp_path, "01-a")
    assert _run(tmp_path) == 0
    (tmp_path / "01-a.png").write_bytes(b"\x89PNG edited")

    with caplog.at_level(logging.ERROR, logger="markdy_export"):
        assert _run(tmp_path, "--check") == 1
    assert "01-a.png is not the one the export wrote" in caplog.text


def test_check_fails_when_a_diagram_was_never_exported(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(tmp_path, "01-a")

    with caplog.at_level(logging.ERROR, logger="markdy_export"):
        assert _run(tmp_path, "--check") == 1
    assert "01-a: fresh: never exported" in caplog.text


def test_check_fails_when_exported_with_another_markdy_version(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(tmp_path, "01-a")
    assert _run(tmp_path) == 0
    data = _manifest(tmp_path)
    data["cli"] = "1.4.0"
    (tmp_path / mx.MANIFEST_NAME).write_text(json.dumps(data), encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="markdy_export"):
        assert _run(tmp_path, "--check") == 1
    assert "exported with Markdy 1.4.0" in caplog.text


def test_an_unreadable_manifest_is_a_problem(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(tmp_path, "01-a")
    assert _run(tmp_path) == 0
    (tmp_path / mx.MANIFEST_NAME).write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="markdy_export"):
        assert _run(tmp_path, "--check") == 1
    assert f"{mx.MANIFEST_NAME} can't be read" in caplog.text


def test_check_reports_exports_and_entries_without_a_source(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(tmp_path, "01-a")
    _write(tmp_path, "02-b")
    assert _run(tmp_path) == 0
    (tmp_path / "02-b.markdy").unlink()

    with caplog.at_level(logging.ERROR, logger="markdy_export"):
        assert _run(tmp_path, "--check") == 1
    assert "02-b: orphan: 02-b.png has no 02-b.markdy" in caplog.text
    assert f"02-b: orphan: {mx.MANIFEST_NAME} lists it but there is no 02-b.markdy" in caplog.text


def test_check_also_lints_and_verifies(tmp_path: Path) -> None:
    _write(tmp_path, "01-a")
    assert _run(tmp_path) == 0

    assert _run(tmp_path, "--check", cli=FakeCli(verify_fail={"01-a": ("theme_contrast",)})) == 1


# ---- --lint-only and the exit codes --------------------------------------------------------------
def test_lint_only_ignores_exports_and_never_renders(tmp_path: Path) -> None:
    _write(tmp_path, "01-a")  # never exported

    assert _run(tmp_path, "--lint-only", renderer=ExplodingRenderer()) == 0
    assert not (tmp_path / mx.MANIFEST_NAME).exists()


def test_lint_only_fails_on_a_lint_problem(tmp_path: Path) -> None:
    _write(tmp_path, "01-a")

    assert _run(tmp_path, "--lint-only", cli=FakeCli(lint_fail={"01-a": "ERR"})) == 1


def test_no_diagrams_at_all_is_a_failure(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="markdy_export"):
        assert _run(tmp_path, "--check") == 1
    assert "no .markdy diagrams" in caplog.text


def test_check_and_lint_only_cannot_be_combined() -> None:
    with pytest.raises(SystemExit):
        mx.parse_args(["--check", "--lint-only"])


def test_main_answers_2_when_the_cli_is_not_installed(tmp_path: Path) -> None:
    folder = tmp_path / "diagrams"
    folder.mkdir()
    _write(folder, "01-a")

    code = mx.main(
        ["--lint-only", "--diagrams", str(folder), "--tools", str(tmp_path / "no-tools")]
    )

    assert code == 2


def test_node_cli_refuses_a_markdy_version_other_than_the_pinned_one(tmp_path: Path) -> None:
    pkg = tmp_path / "node_modules" / "@markdy" / "cli"
    (pkg / "dist").mkdir(parents=True)
    (pkg / "dist" / "index.js").write_text("", encoding="utf-8")
    (pkg / "package.json").write_text(json.dumps({"version": "1.4.0"}), encoding="utf-8")

    with pytest.raises(mx.SetupError, match="1.4.0.*1.5.7"):
        mx.NodeCli(tmp_path)


def test_node_cli_refuses_an_unreadable_package_file(tmp_path: Path) -> None:
    pkg = tmp_path / "node_modules" / "@markdy" / "cli"
    (pkg / "dist").mkdir(parents=True)
    (pkg / "dist" / "index.js").write_text("", encoding="utf-8")
    (pkg / "package.json").write_text("{", encoding="utf-8")

    with pytest.raises(mx.SetupError, match="can't be read"):
        mx.NodeCli(tmp_path)


def test_the_pinned_version_matches_the_dev_tool_lock() -> None:
    package = json.loads((ROOT / "tools" / "markdy" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "tools" / "markdy" / "package-lock.json").read_text(encoding="utf-8"))

    assert package["devDependencies"] == {"@markdy/cli": mx.CLI_VERSION}
    assert package["private"] is True
    assert lock["packages"]["node_modules/@markdy/cli"]["version"] == mx.CLI_VERSION


# ---- dev-only: never in the app image, the console or the build book (plan decision 5) -----------
TEXT_SUFFIXES = (".py", ".js", ".mjs", ".css", ".html", ".json", ".md", ".txt", ".toml", ".yaml")


def test_nothing_the_app_ships_mentions_markdy() -> None:
    """The console and the build book never load Markdy (esm.sh would break the CSP)."""
    hits = []
    for path in sorted((ROOT / "src").rglob("*")):
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            if "markdy" in text or "esm.sh" in text:
                hits.append(path.relative_to(ROOT).as_posix())
    assert hits == []


def test_the_markdy_tool_never_enters_the_app_image() -> None:
    ignore = [
        ln.strip() for ln in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    ]
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "tools" in ignore and "**/node_modules" in ignore
    assert "!tools" not in " ".join(ignore)
    assert "tools/" not in dockerfile and "npm" not in dockerfile and "node " not in dockerfile


def test_the_build_book_licence_list_does_not_gain_markdy() -> None:
    """The book's Libraries section is requirements.lock + requirements.licences.json (Python) and
    the console's vendored files; the dev-only Node tool is in neither."""
    table = json.loads((ROOT / "requirements.licences.json").read_text(encoding="utf-8"))
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8").lower()

    assert not [name for name in table["dists"] if "markdy" in name.lower()]
    assert "markdy" not in lock and "html2canvas" not in lock


# ---- CI: the `docs` job ------------------------------------------------------------------------
def _ci() -> dict[str, Any]:
    import yaml

    data: dict[str, Any] = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    return data


def test_the_docs_job_runs_on_pull_requests_only_and_never_gates_a_deploy() -> None:
    jobs = _ci()["jobs"]
    docs = jobs["docs"]

    assert docs["if"] == "github.event_name == 'pull_request'"
    assert "docs" not in jobs["deploy"]["needs"]
    assert "needs" not in docs and "permissions" not in docs  # the read-only default token


def test_the_docs_job_lints_always_and_checks_exports_when_architecture_changes() -> None:
    steps = _ci()["jobs"]["docs"]["steps"]
    runs = [(str(s.get("if", "")), str(s.get("run", ""))) for s in steps]
    changed = next(s for s in steps if s.get("id") == "changed")

    assert "npm ci --prefix tools/markdy --ignore-scripts" in " ".join(r for _, r in runs)
    assert "-- docs/architecture" in changed["run"] and "BASE_REF" in changed["env"]
    assert "${{" not in changed["run"]  # no expression pasted into the shell
    check = [cond for cond, run in runs if run == "python scripts/markdy_export.py --check"]
    lint = [cond for cond, run in runs if run == "python scripts/markdy_export.py --lint-only"]
    assert check == ["steps.changed.outputs.architecture == 'yes'"]
    assert lint == ["steps.changed.outputs.architecture != 'yes'"]
    assert not any("playwright" in run for _, run in runs)  # the check needs no browser
