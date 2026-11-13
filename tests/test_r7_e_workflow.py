# tests/test_r7_e_workflow.py -- R7 D23 (Part E): the Android workflow proves the app without a
# secret: it resolves every pin, runs core's JVM tests against the shared vectors, builds
# `personal` against the placeholder address, checks the built app with scripts/apk_check.py
# (cross-checked with Gradle's merged manifest), lints it, keeps the result 7 days as "not for
# installing", and breaks `core` on purpose to show its tests catch each negative control.
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "android.yml"
CORE = ROOT / "android" / "core" / "src" / "main" / "kotlin" / "io" / "github" / "shark2558"


def _wf() -> dict[str, Any]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _runs(job: str) -> str:
    return "\n".join(s.get("run", "") for s in _wf()["jobs"][job]["steps"])


def test_the_workflow_uses_no_secret_and_reads_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text and "${{ github.token }}" not in text
    assert _wf()["permissions"] == {"contents": "read"}


def test_every_action_is_pinned_by_its_full_commit() -> None:
    uses = re.findall(r"uses:\s*(\S+)", WORKFLOW.read_text(encoding="utf-8"))
    assert uses
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), ref


def test_the_build_job_runs_every_proof_in_order() -> None:
    runs = _runs("build")
    order = [
        "resolveDependencies",
        ":core:jvmTests",
        ":app:assemblePersonal",
        "scripts/apk_check.py android/app/build/outputs/apk/personal --merged",
        ":app:lintPersonal",
    ]
    positions = [runs.index(step) for step in order]
    assert positions == sorted(positions)
    assert "-Pjarvis.host=jarvis.invalid" in runs
    assert re.search(
        r"GRADLE: \./gradlew --no-daemon -Pjarvis\.host=jarvis\.invalid", WORKFLOW.read_text()
    )


def test_one_run_reports_every_problem() -> None:
    steps = _wf()["jobs"]["build"]["steps"]
    later = [s for s in steps if "run" in s and "resolveDependencies" not in s["run"]]
    named = [s for s in later if "curl" not in s["run"]]
    assert named and all(s.get("if") == "${{ !cancelled() }}" for s in named)
    upload = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert len(upload) == 1 and "if" not in upload[0]  # only a fully green run keeps an app
    assert upload[0]["with"]["name"].endswith("not-for-installing")
    assert upload[0]["with"]["retention-days"] == 7


def test_the_controls_job_breaks_core_four_ways_and_needs_each_to_fail() -> None:
    runs = _runs("controls")
    controls = re.findall(r"^control (\w+) (\S+) ('[^']*'|\"[^\"]*\") ", runs, re.M)
    assert {c[0] for c in controls} == {
        "dedupe_off",
        "cancel_ignored",
        "json_form",
        "launch_words_open",
    }
    for _name, file, needle in controls:
        text = (CORE / "jarvis" / "core" / file).read_text(encoding="utf-8")
        assert text.count(needle[1:-1]) == 1, (file, needle)  # each needle is really there, once
    assert "did not make core's tests fail" in runs and "^FAIL " in runs


def test_the_workflow_runs_when_the_shared_vectors_change() -> None:
    on = _wf().get("on") or _wf().get(True)
    assert isinstance(on, dict)
    for event in ("push", "pull_request"):
        paths = on[event]["paths"]
        assert "android/**" in paths and "tests/fixtures/r7/phone_vectors.json" in paths
        assert "scripts/apk_check.py" in paths
