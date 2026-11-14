# tests/test_claude_guard.py -- the coding agents' safety hook (docs/plans/r14-hardening.md D18;
# ECC GateGuard; CLAUDE.md "No `rm -rf`, force-push, or edits to lint/format configs to make
# errors disappear"). `.claude/settings.json` runs `.claude/hooks/guard.py` before every Bash,
# Edit, Write and MultiEdit call: it reads the hook's JSON on stdin and blocks (exit 2, one line
# on stderr) only clearly dangerous actions; everything else passes untouched, and bad input is
# allowed with a note, so the hook can never jam a session.
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / ".claude" / "hooks" / "guard.py"
PRIVATE = "-----BEGIN " + "PRIVATE KEY-----"  # never written whole in this file


def _run(payload: object, *, raw: str | None = None) -> subprocess.CompletedProcess[str]:
    text = raw if raw is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(GUARD)], input=text, capture_output=True, text=True, timeout=10
    )


def _bash(command: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return _run({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})


ALLOWED = [
    "git status",
    "git -c push.negotiate=true push",
    "git -c push.negotiate=true push -u origin r14-a",
    "git push origin r14-i0",
    "git worktree add /home/claude/wt/r14-a -b r14-a origin/r14-i0",
    "git worktree remove /home/claude/wt/r14-a",
    "git worktree add .claude/worktrees/r14-b -b r14-b origin/r14-i0",
    "git worktree remove --force .claude/worktrees/r14-b",
    "rm -rf /tmp/r18/x",
    "rm -rf .claude/worktrees/r14-a",
    "rm -rf /home/claude/wt/r14-a",
    "rm -rf build/lib dist/jarvis-14.0.0",
    "cd /tmp && rm -rf scratch",
    "rm -r docs/old.md",  # not forced and recursive together: not this hook's business
    "rm -f notes.txt",
    "git reset --hard HEAD~1",
    "git reset --soft origin/main",
    "git branch -D r14-old",
    "git push origin --delete r14-old",
    "pytest -q tests/test_r14_seams.py && ruff check src tests",
    "echo 'git push --force' > /tmp/notes.txt",  # a word in a quoted string is not a command
    "PYTHONPATH=$PWD/src /tmp/venv-b/bin/python evals/run_all_mock.py",
]

BLOCKED = [
    "git push --force",
    "git push -f origin r14-a",
    "git push --force-with-lease origin r14-a",
    "git push --force-with-lease=r14-a origin r14-a",
    "git -c push.negotiate=true push origin main",
    "git push origin HEAD:main",
    "git push origin r14-a:refs/heads/master",
    "git push origin +r14-a",
    "git push origin --delete main",
    "git push origin :main",
    "git branch -D main",
    "git branch --delete --force master",
    "git reset --hard origin/main",
    "git reset --hard @{u}",
    "git fetch && git reset --hard upstream/r14-i0",
    "rm -rf /",
    "rm -rf ~",
    "rm -rf ~/jarvis-web",
    "rm -rf src",
    "rm -rf tests",
    "rm -rf .git",
    "rm -fr /home/claude/jarvis-web",
    "rm -r -f docs",
    "rm -Rf docs/plans",
    "rm --recursive --force evals",
    "rm -rf /tmp",
    "rm -rf .claude/worktrees",
    "rm -rf /tmp/ok src",
    "sudo rm -rf /var/lib/x",
    "rm -rf $HOME/x",
    "ls; rm -rf ../jarvis-web",
    "echo SECRET=1 > .env",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_the_workshops_normal_commands_pass(command: str) -> None:
    got = _bash(command)
    assert got.returncode == 0, got.stderr


@pytest.mark.parametrize("command", BLOCKED)
def test_dangerous_commands_are_blocked_with_one_line(command: str) -> None:
    got = _bash(command, cwd=MAIN)  # the main checkout's own place (it need not exist here)
    assert got.returncode == 2, command
    assert got.stderr.strip() and len(got.stderr.strip().splitlines()) == 1


# R14 I1 (builder A's finding): the Workshop's worktrees live under /home/claude/wt/ (and in a
# checkout's .claude/worktrees/), so a relative `rm -rf src` there resolved under an allowed root
# and passed. Inside a worktree only the worktree itself and its scratch folders may go, never
# its tracked content, and never the worktree the command stands in.
MAIN = Path("/home/claude/jarvis-web")
WORKTREE = Path("/home/claude/wt/r14-x")
NESTED = MAIN / ".claude" / "worktrees" / "r14-y"
IN_A_CHECKOUT = [
    "rm -rf src",
    "rm -rf tests",
    "rm -rf .git",
    "rm -r -f docs",
    "rm -Rf docs/plans",
    "rm --recursive --force evals",
    "rm -rf .claude/worktrees",
    "rm -rf /tmp/ok src",
    "ls; rm -rf ../{self}",  # the checkout it stands in, by a parent path
    "cd src && rm -rf ../tests",
    "rm -rf {self}/src",
    "rm -rf build/../src",  # normalised before it is judged
    "rm -rf .",
    "rm -rf *",
]


@pytest.mark.parametrize("where", [MAIN, WORKTREE, NESTED, ROOT], ids=str)
@pytest.mark.parametrize("command", IN_A_CHECKOUT)
def test_a_checkouts_own_content_is_never_removed_from_inside_it(where: Path, command: str) -> None:
    line = command.format(self=where.name if "../" in command else where)
    got = _bash(line, cwd=where)
    assert got.returncode == 2, (line, str(where))
    assert len(got.stderr.strip().splitlines()) == 1


@pytest.mark.parametrize(
    ("where", "command"),
    [
        (WORKTREE, "rm -rf build"),
        (WORKTREE, "rm -rf build/lib dist/jarvis-14.0.0"),
        (WORKTREE, "rm -rf tmp/run1 .tmp"),
        (WORKTREE, "cd src && rm -rf build"),
        (WORKTREE, "rm -rf /home/claude/wt/r14-z"),  # another worktree, the whole of it
        (WORKTREE, "cd .. && rm -rf r14-z"),
        (WORKTREE, "rm -rf .claude/worktrees/inner"),  # a worktree inside it, the whole of it
        (WORKTREE, "rm -rf /tmp/r14-logs/wheel"),
        (NESTED, "rm -rf dist"),
        (NESTED, "rm -rf ../r14-z"),
        (MAIN, "rm -rf build"),
        (MAIN, "rm -rf .claude/worktrees/r14-y"),
        (MAIN, "rm -rf /home/claude/wt/r14-x"),
    ],
    ids=str,
)
def test_a_worktree_itself_and_its_scratch_can_still_be_removed(where: Path, command: str) -> None:
    got = _bash(command, cwd=where)
    assert got.returncode == 0, (command, got.stderr)


def _git(base: Path, branch: str) -> Path:
    repo = base / f"repo-{branch}"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(repo)], check=True)
    return repo


def test_a_bare_push_from_main_is_blocked_and_from_a_branch_passes(tmp_path: Path) -> None:
    on_main, feature = _git(tmp_path, "main"), _git(tmp_path, "r14-a")
    assert _bash("git -c push.negotiate=true push", cwd=on_main).returncode == 2
    assert _bash(f"git -C {on_main} push", cwd=feature).returncode == 2
    assert _bash("git -c push.negotiate=true push", cwd=feature).returncode == 0
    assert _bash(f"cd {feature} && git push", cwd=on_main).returncode == 0


def _edit(path: Path, old: str, new: str) -> subprocess.CompletedProcess[str]:
    return _run(
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(path), "old_string": old, "new_string": new},
        }
    )


def _write(path: Path, content: str) -> subprocess.CompletedProcess[str]:
    return _run({"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}})


PYPROJECT = """[project]
name = "x"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "B"]
ignore = ["E501"]

[tool.mypy]
strict = true
"""


@pytest.fixture
def pyproject(tmp_path: Path) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(PYPROJECT, encoding="utf-8")
    return path


def test_a_dependency_edit_in_pyproject_passes(pyproject: Path) -> None:
    got = _edit(pyproject, 'dev = ["pytest>=8"]', 'dev = ["pytest>=8", "pytest-cov>=7"]')
    assert got.returncode == 0, got.stderr


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('ignore = ["E501"]', 'ignore = ["E501", "B008"]'),
        ('select = ["E", "F", "B"]', 'select = ["E", "F"]'),
        ("strict = true", "strict = false"),
        ("strict = true", "strict = true\nignore_errors = true"),
        ("[tool.mypy]\nstrict = true\n", ""),
        ('ignore = ["E501"]', 'ignore = ["E501"]\nper-file-ignores = {"src/x.py" = ["F401"]}'),
        ('select = ["E", "F", "B"]', 'select = ["E", "F", "B"]\nexclude = ["src/jarvis/core"]'),
    ],
)
def test_an_edit_that_switches_a_check_off_is_blocked(pyproject: Path, old: str, new: str) -> None:
    assert _edit(pyproject, old, new).returncode == 2


def test_a_check_turned_on_passes(pyproject: Path) -> None:
    assert (
        _edit(pyproject, 'select = ["E", "F", "B"]', 'select = ["E", "F", "B", "UP"]').returncode
        == 0
    )
    assert _edit(pyproject, 'ignore = ["E501"]', "ignore = []").returncode == 0


def test_a_new_lint_config_file_beside_pyproject_is_blocked(tmp_path: Path) -> None:
    for name in ("ruff.toml", ".ruff.toml", "mypy.ini"):
        assert _write(tmp_path / name, "[lint]\nignore = ['E']\n").returncode == 2, name


def test_a_mypy_ini_edit_that_ignores_errors_is_blocked(tmp_path: Path) -> None:
    ini = tmp_path / "setup.cfg"
    ini.write_text("[mypy]\nstrict = True\n", encoding="utf-8")
    assert _edit(ini, "strict = True", "strict = True\nignore_errors = True").returncode == 2
    assert _edit(ini, "strict = True", "strict = False").returncode == 2


def test_the_coverage_floor_only_goes_up(tmp_path: Path) -> None:
    floor = tmp_path / "scripts" / "coverage_floor.txt"
    floor.parent.mkdir()
    floor.write_text("63\n", encoding="utf-8")
    assert _edit(floor, "63", "60").returncode == 2
    assert _write(floor, "62\n").returncode == 2
    assert _write(floor, "nonsense\n").returncode == 2
    assert _edit(floor, "63", "65").returncode == 0
    assert _write(floor, "63\n").returncode == 0


@pytest.mark.parametrize("name", [".env", ".env.local", ".env.prod"])
def test_env_files_are_never_written(tmp_path: Path, name: str) -> None:
    assert _write(tmp_path / name, "X=1\n").returncode == 2
    assert _edit(tmp_path / name, "X=1", "X=2").returncode == 2


@pytest.mark.parametrize("name", ["server.pem", "deploy.key", "id_ed25519", "keystore.jks"])
def test_key_files_are_never_written(tmp_path: Path, name: str) -> None:
    assert _write(tmp_path / name, "x").returncode == 2


def test_content_holding_a_private_key_is_never_written(tmp_path: Path) -> None:
    body = f"KEY = '''{PRIVATE}\nMIIB\n'''\n"
    assert _write(tmp_path / "src.py", body).returncode == 2
    assert _write(tmp_path / "src.py", "print('ok')\n").returncode == 0


def test_a_multi_edit_is_checked_as_a_whole(pyproject: Path) -> None:
    got = _run(
        {
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": str(pyproject),
                "edits": [
                    {"old_string": "line-length = 100", "new_string": "line-length = 100"},
                    {"old_string": 'ignore = ["E501"]', "new_string": 'ignore = ["E501", "F"]'},
                ],
            },
        }
    )
    assert got.returncode == 2


@pytest.mark.parametrize(
    "raw",
    ["", "not json", "[]", '{"tool_name": "Bash"}', '{"tool_name": "Bash", "tool_input": 3}'],
)
def test_bad_input_is_allowed_with_a_note(raw: str) -> None:
    got = _run(None, raw=raw)
    assert got.returncode == 0


def test_other_tools_pass_untouched() -> None:
    assert _run({"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}}).returncode == 0


def test_the_hook_is_fast() -> None:
    t0 = time.perf_counter()
    for _ in range(5):
        _bash("git -c push.negotiate=true push -u origin r14-a")
    assert (time.perf_counter() - t0) / 5 < 1.0


def test_the_settings_run_the_guard_before_every_bash_and_edit() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]["PreToolUse"]
    matchers = {m for h in hooks for m in h["matcher"].split("|")}
    assert {"Bash", "Edit", "Write", "MultiEdit"} <= matchers
    commands = [c["command"] for h in hooks for c in h["hooks"]]
    assert any(".claude/hooks/guard.py" in c for c in commands)
    assert "guard.py" in (ROOT / "CLAUDE.md").read_text(encoding="utf-8")


def test_the_guard_uses_the_standard_library_only() -> None:
    import ast

    tree = ast.parse(GUARD.read_text(encoding="utf-8"))
    names = {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    names |= {
        (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    }
    assert names <= set(sys.stdlib_module_names) | {"__future__", ""}
