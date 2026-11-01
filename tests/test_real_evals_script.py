# tests/test_real_evals_script.py — slice 10 A1: deploy/run-real-evals.sh asks before it spends,
# reads the Claude key only after a typed YES, keeps it in memory, and talks rupees only.
# The behaviour tests run the real script with a stub `gcloud` and a stub Python on PATH.
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "run-real-evals.sh"
CLOUDRUN = ROOT / "deploy" / "cloudrun.sh"
KEY = "sk-ant-test-SECRET-0123456789"

GCLOUD = """#!/usr/bin/env bash
printf '%s\\n' "gcloud $*" >> "$STUB_LOG"
case "$*" in
  "config get-value project") echo demo-project ;;
  "secrets versions access"*) printf '%s' "$STUB_KEY" ;;
  *) exit 0 ;;
esac
"""
PYTHON = """#!/usr/bin/env bash
# stands in for the evals Python: records which step ran and whether it could see the key
printf '%s key=%s\\n' "$2" "${JARVIS_ANTHROPIC_API_KEY:+present}" >> "$STUB_LOG"
case "$2" in
  estimate) echo "  1. Everyday conversation (the Phase 0 check) — about ₹6.75" ;;
  amount) echo "₹7" ;;
  run) echo "Spent: about ₹4.10 (estimate ₹7, safety stop ₹10.50)."; exit "${STUB_RC:-0}" ;;
esac
"""


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_script_is_valid_bash_and_executable() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    assert os.access(SCRIPT, os.X_OK)


def _shellcheck() -> str | None:
    found = shutil.which("shellcheck")
    if found:
        return found
    beside = Path(sys.executable).with_name("shellcheck")  # shellcheck-py in this venv
    return str(beside) if beside.exists() else None


@pytest.mark.skipif(_shellcheck() is None, reason="shellcheck not installed")
def test_script_passes_shellcheck() -> None:
    subprocess.run([str(_shellcheck()), "-S", "warning", str(SCRIPT)], check=True)


def test_reads_the_same_secret_cloudrun_stores_the_claude_key_in(script: str) -> None:
    stored = re.search(r"JARVIS_ANTHROPIC_API_KEY=([a-z0-9-]+):latest", CLOUDRUN.read_text())
    assert stored is not None
    assert f'SECRET="{stored.group(1)}"' in script
    assert "gcloud secrets versions access latest" in script


def test_the_key_is_read_only_after_the_typed_yes(script: str) -> None:
    yes = script.index('if [ "$ANSWER" != "YES" ]; then')
    assert script.index("secrets versions access") > yes
    assert "read -r -p" in script and "Type YES" in script


def test_the_key_is_never_traced_echoed_exported_or_saved(script: str) -> None:
    assert "set +x" in script and "set -x" not in script
    lines = [
        ln for ln in script.splitlines() if "CLAUDE_KEY" in ln and not ln.lstrip().startswith("#")
    ]
    assert len(lines) >= 4
    for ln in lines:
        assert not re.search(r"\b(echo|printf|cat|tee|export)\b", ln), ln
        assert not re.search(r">\s*(?!/dev/null)\S", ln), ln  # no redirection but to /dev/null
    # handed to the one command that needs it, as that command's environment only
    assert 'JARVIS_ANTHROPIC_API_KEY="$CLAUDE_KEY" "$PY" evals/run_real.py run' in script
    assert "unset CLAUDE_KEY" in script


def test_makes_its_private_python_in_the_home_folder(script: str) -> None:
    assert "$HOME/.jarvis-evals" in script and "-m venv" in script
    assert "umask 077" in script


def _run(
    tmp_path: Path, answer: str, *args: str, rc: int = 0
) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("gcloud", GCLOUD), ("fakepy", PYTHON)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "STUB_LOG": str(log),
        "STUB_KEY": KEY,
        "STUB_RC": str(rc),
        "JARVIS_EVALS_PYTHON": str(bin_dir / "fakepy"),
    }
    (tmp_path / "home").mkdir(exist_ok=True)
    r = subprocess.run(
        ["bash", str(SCRIPT), *args],
        input=answer,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    return r, log.read_text()


def test_anything_but_yes_cancels_and_never_touches_the_key(tmp_path: Path) -> None:
    for answer in ("no\n", "yes\n", "\n", ""):
        r, calls = _run(tmp_path, answer)
        assert r.returncode == 0, r.stderr
        assert "Nothing was spent" in r.stdout
        assert "secrets versions access" not in calls and "run key" not in calls
        assert "estimate key=\n" in calls  # the estimate never has the key


def test_yes_reads_the_key_into_the_run_only_and_never_prints_or_saves_it(tmp_path: Path) -> None:
    r, calls = _run(tmp_path, "YES\n", "--all")
    assert r.returncode == 0, r.stdout + r.stderr
    assert calls.index("secrets versions access") > calls.index("amount")
    assert "run key=present" in calls and "estimate key=\n" in calls
    assert KEY not in r.stdout and KEY not in r.stderr
    for f in (tmp_path / "home").rglob("*"):
        if f.is_file():
            assert KEY not in f.read_text(errors="ignore"), f
    assert "press Enter to spend about ₹7." in r.stdout  # (read -p shows its prompt on a tty)


def test_all_is_passed_to_the_estimate(tmp_path: Path) -> None:
    script_text = SCRIPT.read_text()
    assert "--all" in script_text
    r, _ = _run(tmp_path, "no\n", "--bogus")
    assert r.returncode == 2 and "Unknown option" in r.stderr


def test_output_is_rupees_only_and_numbered_where_the_owner_acts(tmp_path: Path) -> None:
    r, _ = _run(tmp_path, "YES\n", rc=1)
    out = r.stdout + r.stderr
    assert r.returncode == 1
    assert not re.search(r"\$\s?\d|US\$|USD", out)
    assert "1. " in out and "2. " in out  # the YES step and what to do next are numbered


def test_a_safety_stop_is_explained(tmp_path: Path) -> None:
    r, _ = _run(tmp_path, "YES\n", rc=3)
    assert r.returncode == 3 and "safety stop" in r.stdout.lower()
