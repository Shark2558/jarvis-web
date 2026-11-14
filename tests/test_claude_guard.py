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


# R14 integrated review (security M1, code M1): the hook does not expand globs, so `../*` read as
# "a whole worktree named *" and the shell then removed every worktree. A glob, `?`, `[...]` or
# `{a,b}` in an rm target is refused unless the folder above it is below /tmp or a scratch folder.
SRC = WORKTREE / "src"
GLOBS_BLOCKED = [
    (WORKTREE, "rm -rf ../*"),
    (WORKTREE, "cd .. && rm -rf *"),
    (WORKTREE, "rm -rf /home/claude/wt/*"),
    (WORKTREE, "rm -rf /home/claude/wt/r14-?"),
    (WORKTREE, "rm -rf /home/claude/wt/r14-*"),
    (WORKTREE, "rm -rf ../../wt/*"),
    (WORKTREE, "rm -rf ../r14-?"),
    (WORKTREE, "rm -rf ../r14-[a-z]"),
    (WORKTREE, "rm -rf ../{r14-x,r14-z}"),
    (WORKTREE, "rm -rf .claude/worktrees/*"),
    (WORKTREE, "rm -rf b*"),
    (WORKTREE, "rm -rf build/*/../../src"),
    (WORKTREE, "rm -rf build/{lib,../src}"),
    (WORKTREE, "rm -rf /tmp/*"),  # every builder's logs and venvs at once
    (WORKTREE, "rm -rf /tmp/../home/claude/wt/*"),
    (SRC, "rm -rf ../*"),
    (SRC, "rm -rf ../../*"),
    (SRC, "rm -rf ../../r14-?"),
    (MAIN, "rm -rf /home/claude/wt/*"),
    (MAIN, "rm -rf .claude/worktrees/*"),
    (Path("/tmp"), "rm -rf /home/claude/wt/r14-*"),
]
GLOBS_ALLOWED = [
    (WORKTREE, "rm -rf /tmp/r14-logs/book*"),
    (WORKTREE, "rm -rf /tmp/r14-logs/i1-shots-?"),
    (WORKTREE, "rm -rf build/*"),
    (WORKTREE, "rm -rf dist/*.whl build/lib*"),
    (WORKTREE, "rm -rf /home/claude/wt/r14-z/build/*"),
    (SRC, "rm -rf build/*"),
    (Path("/tmp/r14-logs"), "rm -rf scratch/*"),
]


@pytest.mark.parametrize(("where", "command"), GLOBS_BLOCKED, ids=str)
def test_a_glob_never_reaches_past_tmp_or_a_scratch_folder(where: Path, command: str) -> None:
    got = _bash(command, cwd=where)
    assert got.returncode == 2, (command, str(where))
    assert len(got.stderr.strip().splitlines()) == 1


@pytest.mark.parametrize(("where", "command"), GLOBS_ALLOWED, ids=str)
def test_a_glob_below_tmp_or_inside_a_scratch_folder_passes(where: Path, command: str) -> None:
    got = _bash(command, cwd=where)
    assert got.returncode == 0, (command, got.stderr)


# Security M2: the ordinary wrappers. The text a shell would run (`bash -c`, `sh -c`, `eval`), rm
# fed by xargs, find's own deleting, `git clean` of untracked or ignored files, `pushd` and `cd`'s
# spellings (`~`, `$HOME`, `-P`, `-`), and a `cd` inside `( )` that does not leak out.
TMP = Path("/tmp")
WRAPPERS_BLOCKED = [
    (WORKTREE, "bash -c 'rm -rf src'"),
    (WORKTREE, 'sh -c "rm -rf src"'),
    (WORKTREE, "zsh -c 'rm -rf tests'"),
    (WORKTREE, "dash -c 'rm -rf .git'"),
    (WORKTREE, "/bin/bash -lc 'cd .. && rm -rf *'"),
    (WORKTREE, "bash -e -c 'rm -rf src'"),
    (WORKTREE, "bash -o pipefail -c 'rm -rf src'"),
    (WORKTREE, "bash --norc -c 'rm -rf src'"),
    (WORKTREE, "env FOO=1 bash -c 'rm -rf src'"),
    (WORKTREE, "timeout 60 bash -c 'rm -rf src'"),
    (WORKTREE, "sudo sh -c 'rm -rf /'"),
    (WORKTREE, "bash -c \"bash -c 'rm -rf src'\""),
    (WORKTREE, "ls && bash -c 'git push --force'"),
    (WORKTREE, "eval 'rm -rf src'"),
    (WORKTREE, "eval rm -rf src"),
    (WORKTREE, 'eval "cd .. && rm -rf r14-?"'),
    (WORKTREE, "echo src | xargs rm -rf"),
    (WORKTREE, "ls | xargs -0 rm -rf"),
    (WORKTREE, "find . -name x -print0 | xargs -0 rm -rf --"),
    (WORKTREE, "xargs -I{} rm -rf {} < list.txt"),
    (TMP, "echo /tmp/a | xargs rm -rf"),  # the targets come from stdin: the hook can't read them
    (WORKTREE, "find src -delete"),
    (WORKTREE, "find . -name '*.py' -delete"),
    (WORKTREE, "find -delete"),
    (WORKTREE, "find -L src -type f -delete"),
    (WORKTREE, r"find . \( -name '*.py' -o -name '*.md' \) -delete"),
    (WORKTREE, "find . -name __pycache__ -exec rm -rf {} +"),
    (WORKTREE, r"find src -type f -exec rm {} \;"),
    (WORKTREE, "find /home/claude/wt -maxdepth 1 -execdir rm -rf {} +"),
    (WORKTREE, "find src -exec /bin/rm -f {} +"),
    (TMP, "find /home/claude/wt/r14-x -delete"),
    (WORKTREE, "git clean -fdx"),
    (WORKTREE, "git clean -fdxq ."),
    (WORKTREE, "git clean -f -d"),
    (WORKTREE, "git clean -fx"),
    (WORKTREE, "git clean -fX"),
    (WORKTREE, "git clean --force -d -x"),
    (WORKTREE, "git clean -fd src"),
    (TMP, "git -C /home/claude/wt/r14-x clean -fdx"),
    (MAIN, "git clean -fdx"),
    (WORKTREE, "pushd src; rm -rf ../src"),
    (WORKTREE, "pushd src && rm -rf ../tests"),
    (TMP, "pushd /home/claude/wt/r14-x >/dev/null && rm -rf src"),
    (WORKTREE, "pushd /tmp && popd && rm -rf src"),  # popd comes back to the worktree
    (WORKTREE, "(cd /tmp) && rm -rf src"),
    (WORKTREE, "(cd /tmp && ls) | rm -rf src"),
    (WORKTREE, "(cd /tmp); rm -rf src"),
    (WORKTREE, "echo $(cd /tmp); rm -rf src"),
    (WORKTREE, "(cd ..); rm -rf r14-x"),
    (WORKTREE, "rm -rf src find"),
    (WORKTREE, "`rm -rf src`"),
    (WORKTREE, "echo `cd /tmp` && rm -rf src"),
    (TMP, "cd `git rev-parse --show-toplevel` && rm -rf src"),
    (TMP, "cd /tmp && { cd /home/claude/wt/r14-x; rm -rf src; }"),
    (TMP, "if cd /home/claude/wt/r14-x; then rm -rf src; fi"),
    (TMP, "find /tmp/x -exec sh -c 'rm -rf \"$1\"' _ {} \\;"),
    (WORKTREE, "bash -c 'cd /tmp'; rm -rf src"),
    (TMP, "cd ~ && rm -rf jarvis-web"),
    (TMP, "cd && rm -rf jarvis-web"),
    (TMP, "cd $HOME && rm -rf jarvis-web"),
    (TMP, "cd ${HOME}/jarvis-web && rm -rf src"),
    (TMP, "cd -P /home/claude/wt/r14-x && rm -rf src"),
    (TMP, "cd -L -- /home/claude/wt/r14-x && rm -rf src"),
    (TMP, 'cd "$WT" && rm -rf src'),
    (TMP, "cd - && rm -rf src"),
    (TMP, "cd ~someone && rm -rf src"),
    (TMP, "cd $(git rev-parse --show-toplevel) && rm -rf src"),
]
WRAPPERS_ALLOWED = [
    (WORKTREE, "bash -c 'rm -rf /tmp/r14-x'"),
    (WORKTREE, "bash -lc 'cd /tmp && rm -rf scratch'"),
    (WORKTREE, 'sh -c "pytest -q tests"'),
    (WORKTREE, "bash scripts/run.sh"),
    (WORKTREE, 'eval "$(ssh-agent -s)"'),
    (WORKTREE, "find /tmp/r14-logs -name '*.log' -delete"),
    (WORKTREE, "find build -name '*.pyc' -delete"),
    (WORKTREE, "find /tmp/x -exec rm -rf {} +"),
    (WORKTREE, "find . -name '*.py' | xargs grep -n foo"),
    (WORKTREE, "find src -name '*.py' -newer pyproject.toml"),
    (WORKTREE, r"find . \( -name a -o -name b \) -print"),
    (WORKTREE, "find . -name __pycache__ -print"),
    (WORKTREE, "git clean -n -dx"),
    (WORKTREE, "git clean -ndx"),
    (WORKTREE, "git clean --dry-run -d -x"),
    (WORKTREE, "git clean -f"),
    (WORKTREE, "git clean -fdx build dist"),
    (WORKTREE, "git clean -f -e .venv"),
    (WORKTREE, "git -C /tmp/r14-logs/export clean -fdx"),
    (WORKTREE, "cd /tmp/r14-logs/export && git clean -fdx"),
    (WORKTREE, "pushd /tmp && rm -rf scratch && popd"),
    (WORKTREE, "cd -P /tmp && rm -rf scratch"),
    (WORKTREE, "cd ~ && ls"),
    (WORKTREE, "(cd /tmp && rm -rf scratch)"),
    (WORKTREE, "bash -c 'cd /tmp'; ls"),
    (WORKTREE, "echo 'rm -rf src' > /tmp/notes.txt"),
    (WORKTREE, "printf '%s\\n' 'bash -c \"rm -rf src\"' > /tmp/x"),
    (WORKTREE, "xargs -a list.txt grep foo"),
    (WORKTREE, "ls | xargs rm -f"),  # not recursive and forced together: not this rule's business
    (WORKTREE, "git commit -q -F - <<'EOF'\nfix: eval rm -rf src in bash -c\nEOF"),
    (WORKTREE, "git commit -q -m 'docs: `rm -rf build` is allowed'"),
    (WORKTREE, "git clean -fd -- build"),
]


@pytest.mark.parametrize(("where", "command"), WRAPPERS_BLOCKED, ids=str)
def test_the_usual_wrappers_are_judged_like_a_bare_command(where: Path, command: str) -> None:
    got = _bash(command, cwd=where)
    assert got.returncode == 2, (command, str(where))
    assert len(got.stderr.strip().splitlines()) == 1


@pytest.mark.parametrize(("where", "command"), WRAPPERS_ALLOWED, ids=str)
def test_harmless_uses_of_the_wrappers_pass(where: Path, command: str) -> None:
    got = _bash(command, cwd=where)
    assert got.returncode == 0, (command, got.stderr)


@pytest.mark.parametrize(
    "command",
    [
        ")",
        "((",
        "( cd /tmp",
        "cd",
        "cd -P",
        "pushd",
        "popd",
        "popd; popd; ls",
        "bash -c",
        'bash -c "\'"',
        "sh -c 'echo \"'",
        "eval",
        "find",
        "find -name x",
        "git clean",
        "xargs",
        "rm -rf",
        "bash -c " + '"bash -c ' * 10 + "ls" + '"' * 10,
    ],
)
def test_odd_spellings_never_jam_the_hook(command: str) -> None:
    got = _bash(command, cwd=WORKTREE)
    assert got.returncode == 0, (command, got.stderr)
    assert "Traceback" not in got.stderr


# The briefs' own commands always pass (BRIEF-COMMON's code blocks read from the file; the
# Workshop's sandbox brief lives outside the repository, so its commands are written here).
WORKSHOP_BRIEF = [
    "git -c push.negotiate=true push",
    "git ls-remote origin refs/heads/r14-i1",
    "/tmp/venv-12/bin/pytest -q -p no:cacheprovider tests/test_r14_i1_said.py tests/test_x.py",
    "flock /tmp/r14-logs/heavy.lock /tmp/venv-12/bin/pytest -q -p no:cacheprovider"
    " tests/test_r14_seams.py tests/test_r14_wiring.py tests/test_claude_guard.py"
    " tests/test_arch_coverage.py tests/test_telegram_tool_guard.py",
    "/tmp/venv-12/bin/ruff check src tests evals scripts"
    " && /tmp/venv-12/bin/ruff format --check src tests evals scripts",
    "flock /tmp/r14-logs/heavy.lock /tmp/venv-12/bin/mypy src",
    "PYTHONPATH=$PWD/src /tmp/venv-12/bin/python evals/r14/run.py --mock --part needles",
    "PYTHONPATH=$PWD/src /tmp/venv-12/bin/python scripts/arch_coverage.py"
    " && /tmp/venv-12/bin/python scripts/check_doc_versions.py",
    "/tmp/venv-c/bin/python -m pytest -q -p no:cacheprovider tests/browser/test_ui_audit.py",
    "/tmp/venv-b/bin/pytest -q -p no:cacheprovider tests/test_claude_guard.py",
    "flock /tmp/r14-logs/heavy.lock make test",
    "rm -rf /tmp/r14-logs/book1 /tmp/r14-logs/book2",
]


def _brief_commands() -> list[str]:
    brief = ROOT / "docs" / "plans" / "r14-integration" / "BRIEF-COMMON.md"
    text = brief.read_text(encoding="utf-8").replace("\\\n", " ")
    blocks = text.split("\n```")[1::2]
    lines = [ln.strip() for b in blocks for ln in b.splitlines()[1:]]
    found = [
        ln for ln in lines if ln.startswith(("pytest ", "ruff ", "mypy ", "PYTHONPATH=", "git "))
    ]
    assert len(found) >= 5, found  # the brief's test commands were read
    return found


@pytest.mark.parametrize("where", [WORKTREE, MAIN, ROOT], ids=str)
def test_every_command_in_the_briefs_passes(where: Path) -> None:
    for command in _brief_commands() + WORKSHOP_BRIEF:
        got = _bash(command, cwd=where)
        assert got.returncode == 0, (command, got.stderr)


def test_the_docstring_says_it_is_a_guard_rail_not_a_sandbox() -> None:
    text = GUARD.read_text(encoding="utf-8")
    assert "guard rail for agents, not a sandbox" in " ".join(text.split())


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
