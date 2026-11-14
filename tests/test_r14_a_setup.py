# tests/test_r14_a_setup.py -- R14 Part A (docs/plans/r14-hardening.md D3, D4, owner steps 3-5,
# review A4, A5): `deploy/backup_setup.sh`, run against a fake `gcloud` that records every call.
# The set-up shows the rupee lines and changes NOTHING unless he types YES; then the daily
# schedule kept 7 days (once), delete protection on `(default)`, and the drill's three grants for
# jarvis-run: `restoreAdmin`, `backupSchedulesViewer`, and the custom role `jarvisDrillCleanup`
# (get, getMetadata, update, delete) ONLY on `jarvis-drill`, never `datastore.owner`. `--status`
# only reads and always exits 0, whatever gcloud does.
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "backup_setup.sh"
PROJECT = "proj-example"
SA = f"serviceAccount:jarvis-run@{PROJECT}.iam.gserviceaccount.com"
FAKE = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
[ -n "${FAKE_FAIL:-}" ] && exit 1
case "$*" in
  "config get-value project"*) echo "${FAKE_PROJECT:-}" ;;
  *"backups schedules list"*) printf '%s' "${FAKE_SCHEDULES:-}" ;;
  *"databases describe"*) echo '{"deleteProtectionState": "'"${FAKE_PROTECTION:-}"'"}' ;;
  *"get-iam-policy"*) printf '%b' "${FAKE_GRANTS:-}" ;;
  *"roles describe"*) [ -n "${FAKE_ROLE:-}" ] || exit 1 ;;
esac
exit 0
"""
GRANTED = (
    "roles/datastore.restoreAdmin\\t\\n"
    "roles/datastore.backupSchedulesViewer\\t\\n"
    f'projects/{PROJECT}/roles/jarvisDrillCleanup\\tresource.name=="projects/{PROJECT}/databases/'
    'jarvis-drill"\\n'
)


def _run(tmp_path: Path, args: list[str], *, answer: str = "", **env: str) -> tuple[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gcloud = bin_dir / "gcloud"
    gcloud.write_text(FAKE, encoding="utf-8")
    gcloud.chmod(gcloud.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    full = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_LOG": str(log),
        "FAKE_PROJECT": PROJECT,
        "BIND_SLEEP": "0",
        **env,
    }
    done = subprocess.run(
        ["bash", str(SCRIPT), *args], input=answer, capture_output=True, text=True, env=full,
        check=False, timeout=60,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return done.stdout, log.read_text(encoding="utf-8") if log.exists() else ""


@pytest.mark.parametrize("answer", ["", "no\n", "yes\n", "YES please\n", " YES\n"])
def test_nothing_changes_without_a_typed_yes(tmp_path: Path, answer: str) -> None:
    out, calls = _run(tmp_path, [], answer=answer)
    assert "₹5" in out and "₹40" in out and "₹2" in out and "₹100" in out
    assert "Nothing was changed" in out
    for verb in ("create", "update", "add-iam-policy-binding"):
        assert verb not in calls, verb


def test_yes_turns_backups_on_with_the_least_access(tmp_path: Path) -> None:
    out, calls = _run(tmp_path, [], answer="YES\n", FAKE_GRANTS=GRANTED)
    lines = calls.splitlines()
    schedule = [c for c in lines if "backups schedules create" in c]
    assert len(schedule) == 1
    assert "--database=(default)" in schedule[0] and "--recurrence=daily" in schedule[0]
    assert "--retention=7d" in schedule[0]
    protect = [c for c in lines if "databases update" in c]
    assert len(protect) == 1 and "--delete-protection" in protect[0]
    role = next(c for c in lines if "iam roles create jarvisDrillCleanup" in c)
    perms = role.split("--permissions=")[1].split()[0].split(",")
    assert sorted(perms) == sorted(
        "datastore.databases." + p for p in ("get", "getMetadata", "update", "delete")
    )
    binds = [c for c in lines if "add-iam-policy-binding" in c]
    assert all(SA in c for c in binds) and len(binds) == 3
    by_role = {c.split("--role=")[1].split()[0]: c for c in binds}
    assert set(by_role) == {
        "roles/datastore.restoreAdmin",
        "roles/datastore.backupSchedulesViewer",
        f"projects/{PROJECT}/roles/jarvisDrillCleanup",
    }
    cleanup = by_role[f"projects/{PROJECT}/roles/jarvisDrillCleanup"]
    assert f'resource.name=="projects/{PROJECT}/databases/jarvis-drill"' in cleanup
    assert "--condition=None" in by_role["roles/datastore.restoreAdmin"]
    assert "datastore.owner" not in calls and "(default)" not in cleanup
    assert "Backups: on, kept 7 days · Delete protection: on · Drill access: on" in out


def test_a_schedule_already_there_is_kept(tmp_path: Path) -> None:
    sched = f"projects/{PROJECT}/databases/(default)/backupSchedules/s1"
    _, calls = _run(tmp_path, [], answer="YES\n", FAKE_SCHEDULES=sched, FAKE_GRANTS=GRANTED)
    assert "backups schedules create" not in calls


def test_a_step_google_refuses_says_could_not_and_changes_nothing_else(tmp_path: Path) -> None:
    out, _ = _run(tmp_path, [], answer="YES\n", FAKE_GRANTS="")
    assert "Drill access: could not" in out


def test_status_only_reads_and_says_what_is_on(tmp_path: Path) -> None:
    sched = f"projects/{PROJECT}/databases/(default)/backupSchedules/s1"
    out, calls = _run(
        tmp_path,
        ["--status"],
        FAKE_SCHEDULES=sched,
        FAKE_PROTECTION="DELETE_PROTECTION_ENABLED",
        FAKE_GRANTS=GRANTED,
    )
    assert "Backups: on, kept 7 days" in out and "Delete protection: on" in out
    assert "Drill access: on" in out
    for verb in ("create", "update", "delete", "add-iam-policy-binding", "remove-iam-policy"):
        assert verb not in calls, verb


@pytest.mark.parametrize("env", [{}, {"FAKE_FAIL": "1"}, {"FAKE_PROJECT": ""}])
def test_status_before_the_set_up_or_when_gcloud_fails_still_exits_zero(
    tmp_path: Path, env: dict[str, str]
) -> None:
    out, calls = _run(tmp_path, ["--status"], **env)
    assert "Backups:" in out and "Backups: on" not in out
    for verb in ("create", "update", "delete", "add-iam-policy-binding"):
        assert verb not in calls, verb


def test_an_unknown_argument_is_refused(tmp_path: Path) -> None:
    done = subprocess.run(
        ["bash", str(SCRIPT), "--yes"], capture_output=True, text=True, check=False, timeout=30
    )
    assert done.returncode == 2 and "usage" in done.stderr
