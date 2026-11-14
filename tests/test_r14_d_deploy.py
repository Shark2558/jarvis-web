# tests/test_r14_d_deploy.py -- R14 D13's deploy lines (Part D): `deploy/cloudrun.sh` stops making
# the Vitals composite index (R5.1 D2 removed the need; the one already made stays, deleting it is
# optional and free), calls ONLY `deploy/backup_setup.sh --status` (read only: nothing spends money
# before the owner types YES in his own step, D4) and never fails a deploy on it; no TTL policy is
# set (TTL deletes are billed and `expires_at` is a float), and the people cache says so.
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import jarvis.people.cache as people_cache

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "cloudrun.sh"


def _script() -> str:
    return DEPLOY.read_text(encoding="utf-8")


def _code(text: str) -> str:
    """The script without its comment lines (a comment may name what it no longer does)."""
    return "\n".join(x for x in text.splitlines() if not x.lstrip().startswith("#"))


def test_the_vitals_index_is_no_longer_created() -> None:
    code = _code(_script())
    assert "jarvis_vitals_providers" not in code
    assert code.count("indexes composite create") == 1  # the conversation list's, still made
    assert "--collection-group=jarvis_sessions" in code


def test_the_deploy_runs_only_the_read_only_backup_status() -> None:
    code = _code(_script())
    calls = re.findall(r"backup_setup\.sh[^\n]*", code)
    assert calls and all("--status" in c for c in calls), calls
    assert len(calls) == 1


def _status_block() -> str:
    text = _script()
    start = text.index("backup_status_note() {")
    return text[start : text.index("\n}\n", start) + 3]


def _run_block(tmp_path: Path, exit_code: int) -> subprocess.CompletedProcess[str]:
    (tmp_path / "deploy").mkdir()
    fake = tmp_path / "deploy" / "backup_setup.sh"
    fake.write_text(
        '#!/usr/bin/env bash\n[ "${1:-}" = --status ] || { echo SETUP-RAN; exit 9; }\n'
        f'echo "Backups: not set up"\nexit {exit_code}\n',
        encoding="utf-8",
    )
    body = f"set -euo pipefail\n{_status_block()}\nbackup_status_note\necho DEPLOY-GOES-ON\n"
    return subprocess.run(
        ["bash", "-c", body], cwd=tmp_path, capture_output=True, text=True, check=False,
        env={**os.environ},
    )  # fmt: skip


def test_the_status_line_is_shown(tmp_path: Path) -> None:
    run = _run_block(tmp_path, 0)
    assert run.returncode == 0, run.stderr
    assert "Backups: not set up" in run.stdout and "DEPLOY-GOES-ON" in run.stdout
    assert "SETUP-RAN" not in run.stdout


def test_a_failing_status_never_stops_the_deploy(tmp_path: Path) -> None:
    run = _run_block(tmp_path, 3)
    assert run.returncode == 0, run.stderr
    assert "DEPLOY-GOES-ON" in run.stdout and "could not" in run.stdout


def test_no_ttl_policy_is_set_and_the_people_cache_says_so() -> None:
    assert "ttls" not in _code(_script())
    doc = people_cache.__doc__ or ""
    assert "deploy sets a Firestore TTL policy" not in doc
    assert "no TTL policy" in doc
