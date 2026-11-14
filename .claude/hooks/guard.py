#!/usr/bin/env python3
# .claude/hooks/guard.py -- the coding agents' safety hook (docs/plans/r14-hardening.md D18; ECC
# GateGuard; CLAUDE.md: "No `rm -rf`, force-push, or edits to lint/format configs to make errors
# disappear"). `.claude/settings.json` runs it before every Bash, Edit, Write and MultiEdit call.
"""Read the PreToolUse hook's JSON on stdin; block (exit 2, one line on stderr) only clearly
dangerous actions; let everything else pass untouched (exit 0, nothing printed).

Blocked:
- `git push` with `--force` / `-f` / `--force-with-lease` / `--mirror` or a `+refspec`; to `main`
  or `master` (a refspec, a delete, or a bare push while that branch is checked out)
- `git reset --hard` onto a remote ref (`origin/...`, `upstream/...`, `refs/remotes/...`,
  `@{u}`, `FETCH_HEAD`); `git branch -D` / `--delete` of `main` or `master`
- `rm` with both recursive and force flags on anything outside `/tmp/`, `/home/claude/wt/`,
  `.claude/worktrees/`, `build/` and `dist/` (never `/`, `~`, `src`, `tests`, `.git`, nor a path
  the hook cannot read, such as `$HOME/x`)
- writes and edits to `.env*` files, key files (`*.pem`, `*.key`, `id_ed25519`, ...) or content
  holding a private key block; a shell redirect into a `.env*` file
- edits that switch checks off in lint / type / format configs (`[tool.ruff]`, `[tool.mypy]`,
  `ruff.toml`, `.ruff.toml`, `mypy.ini`, `setup.cfg`'s mypy and flake8 sections), a new
  `ruff.toml` / `.ruff.toml` / `mypy.ini`, and a lower `scripts/coverage_floor.txt`

Bad input never blocks: unreadable JSON, a missing field or an error inside the hook is allowed
with a note on stderr, so the hook can never jam a session. Standard library only; fast.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - an older python: the config checks are skipped
    tomllib = None  # type: ignore[assignment]

RULE = "the GateGuard rule in CLAUDE.md: stop and report, never work around it"
PROTECTED_BRANCHES = frozenset({"main", "master"})
SAFE_ROOTS = ("/tmp", "/home/claude/wt")
SAFE_UNDER_CWD = ("build", "dist", ".claude/worktrees")
OPERATORS = frozenset({";", "&&", "||", "|", "&", "(", ")", "|&"})
REDIRECTS = frozenset({">", ">>", "&>", ">|"})
WRAPPERS = frozenset({"sudo", "command", "time", "nice", "nohup", "xargs", "env", "exec"})
REMOTE_PREFIXES = ("origin/", "upstream/", "refs/remotes/")
KEY_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore")
KEY_NAMES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "credentials.json")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
NEW_CONFIG_BLOCKED = frozenset({"ruff.toml", ".ruff.toml", "mypy.ini"})
INI_LINT = ("mypy", "flake8", "pycodestyle", "pydocstyle")
WEAKER_LISTS = ("ignore", "exclude", "disable_error_code", "unfixable", "per-file-ignores")
STRICTER_LISTS = ("select", "enable_error_code")
STRICT_FLAG = re.compile(
    r"^(strict.*|disallow_.*|check_untyped_defs|warn_.*|no_implicit_.*|extra_checks)$"
)
IGNORE_FLAG = re.compile(r"^(ignore_errors|ignore_missing_imports|follow_imports_for_stubs)$")


class Blocked(Exception):
    """A dangerous action; the message is the one line shown."""


# ---- shell commands ---------------------------------------------------------------------------


def _strip_heredocs(command: str) -> str:
    """A heredoc's body is data (a commit message, a file), never a command."""
    out: list[str] = []
    lines = command.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        tags = [m.group(2) for m in HEREDOC.finditer(line)]
        i += 1
        for tag in tags:
            while i < len(lines) and lines[i].strip() != tag:
                i += 1
            i += 1
    return "\n".join(out)


def _segments(command: str) -> Iterator[list[str]]:
    """Each simple command's words, split at ; && || | & and new lines (quotes respected)."""
    text = _strip_heredocs(command).replace("\n", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    words: list[str] = []
    for token in lexer:
        if token in OPERATORS:
            if words:
                yield words
            words = []
        else:
            words.append(token)
    if words:
        yield words


def _skip_env(words: list[str]) -> list[str]:
    i = 0
    while i < len(words) and (
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[i]) or words[i] in WRAPPERS
    ):
        i += 1
    return words[i:]


def _resolve(path: str, cwd: str) -> str:
    joined = path if path.startswith("/") else os.path.join(cwd, path)
    return os.path.normpath(joined)


def _strictly_under(path: str, root: str) -> bool:
    root = os.path.normpath(root)
    return path != root and path.startswith(root.rstrip("/") + "/")


def _rm_target_ok(raw: str, cwd: str) -> bool:
    if raw in ("~",) or raw.startswith("~/") or raw.startswith("~"):
        return False
    if ("$" in raw or "`" in raw) and not raw.startswith("/tmp/"):
        return False
    path = _resolve(raw, cwd)
    if path == "/":
        return False
    if any(_strictly_under(path, root) for root in SAFE_ROOTS):
        return True
    if any(_strictly_under(path, os.path.join(cwd, sub)) for sub in SAFE_UNDER_CWD):
        return True
    marker = "/.claude/worktrees/"
    return marker in path and bool(path.split(marker, 1)[1].strip("/"))


def _check_rm(words: list[str], cwd: str) -> None:
    at = next((i for i, w in enumerate(words) if PurePosixPath(w).name == "rm"), None)
    if at is None:
        return
    args = words[at + 1 :]
    recursive = force = False
    targets: list[str] = []
    options = True
    for a in args:
        if options and a == "--":
            options = False
        elif options and a.startswith("--"):
            recursive |= a == "--recursive"
            force |= a == "--force"
        elif options and a.startswith("-") and len(a) > 1:
            recursive |= "r" in a or "R" in a
            force |= "f" in a
        else:
            targets.append(a)
    if not (recursive and force):
        return
    for t in targets:
        if not _rm_target_ok(t, cwd):
            raise Blocked(
                f"guard: blocked `rm -rf {t}` (outside /tmp, worktrees, build, dist); {RULE}"
            )


def _git_parts(words: list[str]) -> tuple[str | None, str | None, list[str]]:
    """(the `-C` dir, the subcommand, its arguments) of a git command, else (None, None, [])."""
    if not words or PurePosixPath(words[0]).name != "git":
        return None, None, []
    i, where = 1, None
    while i < len(words) and words[i].startswith("-"):
        if words[i] in ("-c", "-C"):
            if words[i] == "-C" and i + 1 < len(words):
                where = words[i + 1]
            i += 2
        else:
            i += 1
    if i >= len(words):
        return where, None, []
    return where, words[i], words[i + 1 :]


def _branch_of(directory: str) -> str | None:
    try:
        got = subprocess.run(
            ["git", "-C", directory, "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True, text=True, timeout=2, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return got.stdout.strip() or None


def _protected(ref: str) -> bool:
    name = ref.removeprefix("refs/heads/")
    return name in PROTECTED_BRANCHES


def _check_push(args: list[str], cwd: str) -> None:
    deleting = False
    positional: list[str] = []
    for a in args:
        if a in ("--force", "--mirror", "--force-if-includes") or a.startswith(
            "--force-with-lease"
        ):
            raise Blocked(f"guard: blocked a force push ({a}); {RULE}")
        if a == "--delete":
            deleting = True
        elif a.startswith("-") and not a.startswith("--") and len(a) > 1:
            if "f" in a:
                raise Blocked(f"guard: blocked a force push ({a}); {RULE}")
            deleting |= "d" in a
        elif not a.startswith("-"):
            positional.append(a)
    refspecs = positional[1:]
    for spec in refspecs:
        if spec.startswith("+"):
            raise Blocked(f"guard: blocked a force push ({spec}); {RULE}")
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        if _protected(dst) or (deleting and _protected(spec)):
            raise Blocked(f"guard: blocked a push to {dst or spec}; {RULE}")
    if not refspecs and _protected(_branch_of(cwd) or ""):
        raise Blocked(f"guard: blocked a push from {_branch_of(cwd)}; {RULE}")


def _remote_ref(ref: str) -> bool:
    return ref.startswith(REMOTE_PREFIXES) or "@{u" in ref or "@{push" in ref or ref == "FETCH_HEAD"


def _check_git(words: list[str], cwd: str) -> None:
    where, sub, args = _git_parts(words)
    if sub is None:
        return
    here = _resolve(where, cwd) if where else cwd
    if sub == "push":
        _check_push(args, here)
    elif sub == "reset" and "--hard" in args:
        for a in args:
            if not a.startswith("-") and _remote_ref(a):
                raise Blocked(f"guard: blocked `git reset --hard {a}`; {RULE}")
    elif sub == "branch":
        deleting = any(
            a == "--delete" or (a.startswith("-") and not a.startswith("--") and "d" in a.lower())
            for a in args
        )
        if deleting and any(_protected(a) for a in args if not a.startswith("-")):
            raise Blocked(f"guard: blocked deleting a protected branch; {RULE}")


def _check_redirects(words: list[str]) -> None:
    for i, w in enumerate(words[:-1]):
        if w in REDIRECTS or (w == "tee" and i + 1 < len(words)):
            target = PurePosixPath(words[i + 1]).name
            if target.startswith(".env"):
                raise Blocked(f"guard: blocked writing {target}; {RULE}")


def check_bash(command: str, cwd: str) -> None:
    for words in _segments(command):
        words = _skip_env(words)
        if not words:
            continue
        if words[0] == "cd" and len(words) > 1:
            cwd = _resolve(words[1], cwd)
            continue
        _check_redirects(words)
        _check_rm(words, cwd)
        _check_git(words, cwd)


# ---- file edits -------------------------------------------------------------------------------


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def _apply(before: str, edits: Sequence[Mapping[str, Any]]) -> str:
    text = before
    for e in edits:
        old, new = str(e.get("old_string", "")), str(e.get("new_string", ""))
        if not old:
            continue
        text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
    return text


def _flat(node: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(node, list) and node and all(isinstance(x, dict) for x in node):
        for i, x in enumerate(node):
            for k, v in _flat(x).items():
                out[f"{prefix}[{_label(x, i)}].{k}"] = v
    else:
        out[prefix] = node
    return out


def _label(item: Mapping[str, Any], index: int) -> str:
    module = item.get("module")
    return ",".join(module) if isinstance(module, list) else str(module or index)


def _items(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {f"{k}={x}" for k, v in value.items() for x in _items(v)}
    if isinstance(value, list | tuple | set):
        return {str(x) for x in value}
    if isinstance(value, str):
        return {x.strip() for x in value.split(",") if x.strip()}
    return {str(value)}


def _truthy(value: Any) -> bool:
    return value is True or (
        isinstance(value, str) and value.strip().lower() in ("true", "1", "yes", "on")
    )


def _weaker(before: Mapping[str, Any], after: Mapping[str, Any]) -> str | None:
    for key in sorted(set(before) | set(after)):
        leaf = key.rsplit(".", 1)[-1]
        old, new = before.get(key), after.get(key)
        if any(w in key for w in WEAKER_LISTS) and not _items(new or []) <= _items(old or []):
            return key
        if leaf in STRICTER_LISTS and key in before and not _items(old) <= _items(new or []):
            return key
        if IGNORE_FLAG.match(leaf) and _truthy(new) and not _truthy(old):
            return key
        if STRICT_FLAG.match(leaf) and _truthy(old) and not _truthy(new):
            return key
    return None


def _lint_config(name: str, text: str) -> dict[str, Any] | None:
    """The lint / type sections of a config file, flattened; None when it is not one."""
    if name in ("pyproject.toml", "ruff.toml", ".ruff.toml"):
        if tomllib is None:
            return None
        data = tomllib.loads(text)
        if name == "pyproject.toml":
            tool = data.get("tool", {})
            return {
                k: v for sec in ("ruff", "mypy") for k, v in _flat(tool.get(sec, {}), sec).items()
            } | {f"section:{sec}": True for sec in ("ruff", "mypy") if sec in tool}
        return _flat(data)
    if name in ("mypy.ini", "setup.cfg", "tox.ini", ".flake8"):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
        return {
            f"{sec}.{k}": v
            for sec in parser.sections()
            if sec.split("-", 1)[0].split(":", 1)[-1] in INI_LINT
            for k, v in parser[sec].items()
        } | {
            f"section:{sec}": True for sec in parser.sections() if sec.split("-", 1)[0] in INI_LINT
        }
    return None


def _check_config(path: str, before: str | None, after: str) -> None:
    name = PurePosixPath(path).name
    if before is None and name in NEW_CONFIG_BLOCKED:
        raise Blocked(f"guard: blocked a new {name} (it would replace pyproject's checks); {RULE}")
    if before is None:
        return
    try:
        old, new = _lint_config(name, before), _lint_config(name, after)
    except (ValueError, configparser.Error):
        return  # an unreadable config fails loudly in the tools themselves
    if old is None or new is None:
        return
    dropped = [k for k in old if k.startswith("section:") and k not in new]
    weaker = dropped[0] if dropped else _weaker(old, new)
    if weaker:
        raise Blocked(f"guard: blocked switching a check off in {name} ({weaker}); {RULE}")


def _floor(text: str | None) -> float | None:
    try:
        return float((text or "").strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def _check_file(path: str, before: str | None, after: str, added: str) -> None:
    name = PurePosixPath(path).name
    if name.startswith(".env"):
        raise Blocked(f"guard: blocked writing {name}; {RULE}")
    if name.endswith(KEY_SUFFIXES) or name.startswith(KEY_NAMES):
        raise Blocked(f"guard: blocked writing a key file ({name}); {RULE}")
    if PRIVATE_KEY.search(added):
        raise Blocked(f"guard: blocked writing a private key block into {name}; {RULE}")
    if name == "coverage_floor.txt":
        old, new = _floor(before), _floor(after)
        if new is None or (old is not None and new < old):
            raise Blocked(f"guard: blocked lowering the coverage floor ({old} -> {new}); {RULE}")
    _check_config(path, before, after)


def check_edit(tool: str, data: Mapping[str, Any]) -> None:
    path = data.get("file_path")
    if not isinstance(path, str) or not path:
        return
    before = _read(path)
    if tool == "Write":
        content = str(data.get("content", ""))
        _check_file(path, before, content, content)
        return
    edits = data.get("edits") if tool == "MultiEdit" else [data]
    if not isinstance(edits, list):
        return
    added = "\n".join(str(e.get("new_string", "")) for e in edits if isinstance(e, Mapping))
    after = _apply(before or "", [e for e in edits if isinstance(e, Mapping)])
    _check_file(path, before, after, added)


# ---- the hook ---------------------------------------------------------------------------------


def decide(payload: Any) -> str | None:
    """The one-line reason to block, or None to allow."""
    if not isinstance(payload, dict):
        return None
    tool, data = payload.get("tool_name"), payload.get("tool_input")
    if not isinstance(data, dict):
        return None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    try:
        if tool == "Bash" and isinstance(data.get("command"), str):
            check_bash(data["command"], cwd)
        elif tool in ("Edit", "Write", "MultiEdit"):
            check_edit(str(tool), data)
    except Blocked as exc:
        return str(exc)
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "null")
    except (ValueError, OSError):
        print("guard: unreadable hook input; allowed", file=sys.stderr)
        return 0
    try:
        reason = decide(payload)
    except Exception as exc:  # noqa: BLE001 - the hook never crashes closed
        print(f"guard: could not check ({type(exc).__name__}); allowed", file=sys.stderr)
        return 0
    if reason:
        print(reason.replace("\n", " "), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
