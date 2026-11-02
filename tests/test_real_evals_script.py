# tests/test_real_evals_script.py — slice 10 A1: deploy/run-real-evals.sh asks before it spends,
# reads the Claude key only after a typed YES, keeps it in memory, and talks rupees only.
# The behaviour tests run the real script in a pseudo-terminal (the owner typing), with a stub
# `gcloud` and a stub Python on PATH. Review M2: input from a pipe is refused, never obeyed.
from __future__ import annotations

import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import time
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
printf 'args %s\\n' "$*" >> "$STUB_LOG"
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
    assert "< /dev/tty" in script[:yes]  # typed at the terminal, never read from a pipe
    assert "[ -t 0 ]" in script


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


def _stubs(tmp_path: Path, rc: int) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("gcloud", GCLOUD), ("fakepy", PYTHON)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "STUB_LOG": str(log),
        "STUB_KEY": KEY,
        "STUB_RC": str(rc),
        "JARVIS_EVALS_PYTHON": str(bin_dir / "fakepy"),
    }
    return env, log


def _run(tmp_path: Path, answer: str, *args: str, rc: int = 0) -> tuple[int, str, str]:
    """The script in a pseudo-terminal: `answer` is typed once the YES prompt shows
    ("" = Ctrl-D). Returns (exit status, everything shown, the stub call log)."""
    env, log = _stubs(tmp_path, rc)
    bash = shutil.which("bash") or "/bin/bash"
    pid, fd = pty.fork()
    if pid == 0:  # the child: its controlling terminal is the pty, as in Cloud Shell
        os.execve(bash, [bash, str(SCRIPT), *args], env)
    out, typed, deadline = b"", False, time.monotonic() + 60
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:  # EIO: the script has exited
            break
        if not chunk:
            break
        out += chunk
        if not typed and b"Type YES" in out:
            os.write(fd, answer.encode() if answer else b"\x04")
            typed = True
    else:
        os.kill(pid, signal.SIGKILL)
    os.close(fd)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), out.decode(errors="replace"), log.read_text()


def test_input_from_a_pipe_is_refused_before_anything_happens(tmp_path: Path) -> None:
    env, log = _stubs(tmp_path, 0)
    for args in ((), ("--all",)):
        r = subprocess.run(
            ["bash", str(SCRIPT), *args],
            input="YES\n",  # e.g. `echo YES | bash deploy/run-real-evals.sh --all`
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert r.returncode == 2 and "Nothing was spent" in r.stderr
        assert "type YES" in r.stderr
    calls = log.read_text()
    assert "secrets versions access" not in calls and "estimate" not in calls


def test_anything_but_yes_cancels_and_never_touches_the_key(tmp_path: Path) -> None:
    for answer in ("no\n", "yes\n", "\n", ""):
        code, out, calls = _run(tmp_path, answer)
        assert code == 0, out
        assert "Nothing was spent" in out
        assert "secrets versions access" not in calls and "run key" not in calls
        assert "estimate key=\n" in calls  # the estimate never has the key


def test_yes_reads_the_key_into_the_run_only_and_never_prints_or_saves_it(tmp_path: Path) -> None:
    code, out, calls = _run(tmp_path, "YES\n", "--all")
    assert code == 0, out
    assert calls.index("secrets versions access") > calls.index("amount")
    assert "run key=present" in calls and "estimate key=\n" in calls
    assert KEY not in out
    for f in (tmp_path / "home").rglob("*"):
        if f.is_file():
            assert KEY not in f.read_text(errors="ignore"), f
    assert "Type YES to spend about ₹7" in out and "press Enter to spend about ₹7." in out


def _run_args(calls: str, step: str) -> list[str]:
    (line,) = [ln for ln in calls.splitlines() if ln.startswith(f"args evals/run_real.py {step}")]
    return line.split()[1:]


def test_each_run_keeps_its_own_plan_and_spending_record(tmp_path: Path) -> None:
    """Review L4: two runs never share (or reset) one plan or one spending record."""
    folders = []
    for _ in range(2):
        _, _, calls = _run(tmp_path, "YES\n")
        run = _run_args(calls, "run")
        state, ledger = run[run.index("--state") + 1], run[run.index("--ledger") + 1]
        assert Path(state).parent == Path(ledger).parent  # one folder per run
        assert _run_args(calls, "estimate")[-1] == state  # the plan the owner said YES to
        assert str(tmp_path / "home" / ".jarvis-evals") in state
        folders.append(Path(state).parent)
    assert folders[0] != folders[1]


def test_all_is_passed_to_the_estimate(tmp_path: Path) -> None:
    _, _, calls = _run(tmp_path, "no\n", "--all")
    assert "--all" in _run_args(calls, "estimate")
    code, out, _ = _run(tmp_path, "no\n", "--bogus")
    assert code == 2 and "Unknown option" in out


def test_output_is_rupees_only_and_numbered_where_the_owner_acts(tmp_path: Path) -> None:
    code, out, _ = _run(tmp_path, "YES\n", rc=1)
    assert code == 1
    assert not re.search(r"\$\s?\d|US\$|USD", out)
    assert "1. " in out and "2. " in out  # the YES step and what to do next are numbered


def test_a_safety_stop_is_explained(tmp_path: Path) -> None:
    code, out, _ = _run(tmp_path, "YES\n", rc=3)
    assert code == 3 and "safety stop" in out.lower()
