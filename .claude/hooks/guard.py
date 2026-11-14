#!/usr/bin/env python3
# .claude/hooks/guard.py -- the coding agents' safety hook (docs/plans/r14-hardening.md D18; ECC
# GateGuard; CLAUDE.md: "No `rm -rf`, force-push, or edits to lint/format configs to make errors
# disappear"). `.claude/settings.json` runs it before every Bash, Edit, Write and MultiEdit call.
"""Read the PreToolUse hook's JSON on stdin; block (exit 2, one line on stderr) only clearly
dangerous actions; let everything else pass untouched (exit 0, nothing printed).

This is a guard rail for agents, not a sandbox. It reads the command's text the way a careful
reader would and stops the mistakes the GateGuard rule names; it never runs the shell, expands a
variable or a glob, follows a symlink or opens a script. What it can't read is out of its reach:
`python -c` / `perl -e`, a script file, text piped into `sh` or a heredoc fed to a shell, a path
held in a variable, a symlink planted at `build`. The rule in CLAUDE.md ("a blocked action means
stop and report; never work around it"), not this file, is what binds an agent.

Blocked:
- `git push` with `--force` / `-f` / `--force-with-lease` / `--mirror` or a `+refspec`; to `main`
  or `master` (a refspec, a delete, or a bare push while that branch is checked out)
- `git reset --hard` onto a remote ref (`origin/...`, `upstream/...`, `refs/remotes/...`,
  `@{u}`, `FETCH_HEAD`); `git branch -D` / `--delete` of `main` or `master`
- `rm` with both recursive and force flags on anything but what is below `/tmp/`, a whole
  worktree (`/home/claude/wt/<name>` or a checkout's `.claude/worktrees/<name>`) or a scratch
  folder (`build`, `dist`, `tmp`, `.tmp`) of the current folder or of a worktree; never a
  worktree's own content (`src`, `tests`, `.git`, ...), never the worktree the command stands in,
  never `/`, `~`, nor a path the hook cannot read, such as `$HOME/x` (R14 I1: a relative
  `rm -rf src` inside a worktree resolved under an allowed root and passed); a glob (`*`, `?`,
  `[...]`, `{a,b}`) only where the folder above it is below `/tmp` or a scratch folder (R14
  review: `rm -rf ../*` read as "a worktree named *" and removed every worktree); and never an
  `rm -rf` fed by `xargs` / `parallel` (its targets come from stdin)
- the same rules through the usual wrappers: the text handed to `bash|sh|zsh|dash|ksh|su -c` or
  `eval` is judged as a command; `find ... -delete` / `-exec rm` / `-execdir rm` only below
  `/tmp` or a scratch folder; `git clean` with `-d`, `-x` or `-X` only in a checkout below `/tmp`
  or on scratch folders; the folder is followed through `cd` (its `-P`, `-L`, `--`, `~`, `$HOME`
  spellings), `pushd` and `popd`, and a `cd` inside `( )` or `$( )` stays there; a `cd` the hook
  can't follow (`cd -`, `cd "$X"`) makes every later relative target unknown, so refused
- writes and edits to `.env*` files, key files (`*.pem`, `*.key`, `id_ed25519`, ...) or content
  holding a private key block; a shell redirect into a `.env*` file
- edits that switch checks off in lint / type / format configs (`[tool.ruff]`, `[tool.mypy]`,
  `ruff.toml`, `.ruff.toml`, `mypy.ini`, `setup.cfg`'s mypy and flake8 sections), a new
  `ruff.toml` / `.ruff.toml` / `mypy.ini`, and a lower `scripts/coverage_floor.txt`

Bad input never blocks: unreadable JSON, a missing field, text the shell itself would refuse (an
unbalanced quote) or an error inside the hook is allowed with a note on stderr, so the hook can
never jam a session. Standard library only; fast.
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
SCRATCH_ROOT = "/tmp"  # anything below it may go
WORKTREES = "/home/claude/wt"  # the Workshop's worktrees: each one whole, or its scratch
WORKTREE_MARKER = "/.claude/worktrees/"  # a checkout's own worktrees: the same
SCRATCH = frozenset({"build", "dist", "tmp", ".tmp"})  # folders no checkout tracks
PUNCT = ";&|()<>"
PAIRS = frozenset({"&&", "||", "|&", ";;", ">>", "&>", ">|", "<<", "<&", ">&", "<>"})
OPERATORS = frozenset({";", "&&", "||", "|", "&", "(", ")", "|&", ";;"})
GROUPS = frozenset({"(", ")"})
REDIRECTS = frozenset({">", ">>", "&>", ">|"})
WRAPPERS = frozenset({"sudo", "command", "time", "nice", "nohup", "xargs", "env", "exec"})
KEYWORDS = frozenset({"{", "}", "!", "if", "then", "else", "elif", "fi", "do", "done", "while"})
DIR_CHANGERS = frozenset({"cd", "pushd", "popd"})
CD_OPTION = re.compile(r"-[LPe@]+")
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "su"})
SHELL_ARG_OPTIONS = frozenset({"-o", "+o", "-O", "+O"})
MAX_DEPTH = 4  # `bash -c "bash -c '...'"`: deeper than this is not read
FEEDERS = frozenset({"xargs", "parallel"})
FIND_OPTIONS = frozenset({"-H", "-L", "-P"})
EXECS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
GLOB = re.compile(r"[*?\[{]")
CLEAN_LONG = {"--force": "f", "--dry-run": "n", "--quiet": "q", "--interactive": "i"}
CLEAN_WIDE = frozenset({"d", "x", "X"})  # untracked folders, ignored files
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

Dirs = tuple[str | None, ...]  # pushd's stack; None is a folder the hook can't tell


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


def _name(word: str) -> str:
    return PurePosixPath(word).name


def _split_ops(token: str) -> list[str]:
    """A run of shell punctuation (`);`, `&&(`, `)|`) as its operators; any other token whole."""
    if not token or any(c not in PUNCT for c in token):
        return [token]
    out: list[str] = []
    i = 0
    while i < len(token):
        step = 2 if token[i : i + 2] in PAIRS else 1
        out.append(token[i : i + step])
        i += step
    return out


def _parts(command: str) -> Iterator[list[str] | str]:
    """Each simple command's words, split at ; && || | & and new lines (quotes respected), with
    "(" and ")" yielded between them so a group's `cd` stays inside it; inside a `find`
    command the parentheses are its own words."""
    text = _strip_heredocs(command).replace("\n", " ; ")
    pieces = text.split("`")  # `x` is $(x): odd pieces are inside one
    text = "".join(p if i % 2 == 0 else f" $( {p} ) " for i, p in enumerate(pieces))
    lexer = shlex.shlex(text, posix=True, punctuation_chars=PUNCT)
    lexer.whitespace_split = True
    lexer.commenters = ""
    words: list[str] = []
    for token in lexer:
        for piece in _split_ops(token):
            if piece in GROUPS and any(_name(w) == "find" for w in words):
                words.append(piece)
            elif piece in OPERATORS:
                if words:
                    yield words
                words = []
                if piece in GROUPS:
                    yield piece
            else:
                words.append(piece)
    if words:
        yield words


def _skip_env(words: list[str]) -> list[str]:
    i = 0
    while i < len(words) and (
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[i])
        or words[i] in WRAPPERS
        or words[i] in KEYWORDS
    ):
        i += 1
    return words[i:]


def _resolve(path: str, cwd: str | None) -> str | None:
    """`path` made absolute and normalised; None for a relative path in an unknown folder."""
    if path.startswith("/"):
        return os.path.normpath(path)
    return None if cwd is None else os.path.normpath(os.path.join(cwd, path))


def _strictly_under(path: str, root: str) -> bool:
    root = os.path.normpath(root)
    return path != root and path.startswith(root.rstrip("/") + "/")


def _at_or_under(path: str, root: str) -> bool:
    return path == os.path.normpath(root) or _strictly_under(path, root)


def _worktree_of(path: str) -> tuple[str, list[str]] | None:
    """(the innermost worktree holding `path`, the parts of `path` below it), or None."""
    head, marker, tail = path.rpartition(WORKTREE_MARKER)
    if marker and tail:
        name, *rest = tail.split("/")
        return head + marker + name, rest
    if _strictly_under(path, WORKTREES):
        name, *rest = path[len(WORKTREES) + 1 :].split("/")
        return f"{WORKTREES}/{name}", rest
    return None


def _unreadable(raw: str) -> bool:
    return raw.startswith("~") or (("$" in raw or "`" in raw) and not raw.startswith("/tmp/"))


def _in_scratch(raw: str, cwd: str | None) -> bool:
    """Below /tmp, or at or below a scratch folder of the current folder or of a worktree."""
    path = None if _unreadable(raw) else _resolve(raw, cwd)
    if path is None:
        return False
    if _strictly_under(path, SCRATCH_ROOT):
        return True
    if cwd is not None and any(_at_or_under(path, os.path.join(cwd, s)) for s in SCRATCH):
        return True
    tree = _worktree_of(path)
    return tree is not None and bool(tree[1]) and tree[1][0] in SCRATCH


def _glob_ok(raw: str, cwd: str | None) -> bool:
    """A glob may only choose among what is below /tmp or inside a scratch folder: the folder
    above its first wild part must be one, with no `..` after it (the hook never expands it)."""
    parts = raw.split("/")
    first = next(i for i, p in enumerate(parts) if GLOB.search(p))
    if any(".." in p for p in parts[first:]):
        return False
    base = "/".join(parts[:first]) or ("/" if raw.startswith("/") else ".")
    return _in_scratch(base, cwd) and _in_scratch(raw, cwd)


def _rm_target_ok(raw: str, cwd: str | None) -> bool:
    if GLOB.search(raw):
        return _glob_ok(raw, cwd)
    if _in_scratch(raw, cwd):
        return True
    path = None if raw.startswith("~") or "$" in raw or "`" in raw else _resolve(raw, cwd)
    tree = _worktree_of(path) if path else None
    if tree is None or tree[1] or cwd is None:
        return False
    return not _at_or_under(os.path.normpath(cwd), tree[0])  # a whole worktree, not this one


def _rm_args(args: list[str]) -> tuple[bool, bool, list[str]]:
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
    return recursive, force, targets


def _check_rm(words: list[str], cwd: str | None) -> None:
    at = next((i for i, w in enumerate(words) if _name(w) == "rm"), None)
    if at is None:
        return
    recursive, force, targets = _rm_args(words[at + 1 :])
    if not (recursive and force):
        return
    feeder = next((_name(w) for w in words[:at] if _name(w) in FEEDERS), None)
    if feeder:
        raise Blocked(f"guard: blocked `{feeder} rm -rf` (its targets come from stdin); {RULE}")
    for t in targets:
        if not _rm_target_ok(t, cwd):
            raise Blocked(
                f"guard: blocked `rm -rf {t}` (only /tmp, a whole worktree or build, dist, tmp);"
                f" {RULE}"
            )


def _find_parts(args: list[str]) -> tuple[list[str], list[str]]:
    """(find's start folders, its expression)."""
    i = 0
    while i < len(args) and (args[i] in FIND_OPTIONS or args[i] == "-D" or args[i][:2] == "-O"):
        i += 2 if args[i] == "-D" else 1
    starts: list[str] = []
    while i < len(args) and not args[i].startswith(("-", "(", ")", "!")):
        starts.append(args[i])
        i += 1
    return starts or ["."], args[i:]


def _check_find(words: list[str], cwd: str | None) -> bool:
    """True when the command is a `find` (its `-exec rm` is its own); blocks its deleting
    anywhere but below /tmp or a scratch folder."""
    at = next((i for i, w in enumerate(words) if _name(w) == "find"), None)
    rm_at = next((i for i, w in enumerate(words) if _name(w) == "rm"), None)
    if at is None or (rm_at is not None and rm_at < at):
        return False
    starts, expr = _find_parts(words[at + 1 :])
    deleting = "-delete" in expr or any(
        e in EXECS and _name(n) == "rm" for e, n in zip(expr, expr[1:], strict=False)
    )
    for start in starts if deleting else []:
        if not _in_scratch(start, cwd):
            raise Blocked(
                f"guard: blocked `find {start}` deleting (only below /tmp, build, dist, tmp);"
                f" {RULE}"
            )
    return True


def _shell_text(args: list[str]) -> str | None:
    """The text after a shell's `-c` (`bash -lc 'x'`, `sh -e -c "x"`), else None."""
    i, has_c = 0, False
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if a in SHELL_ARG_OPTIONS:
            i += 2
        elif a.startswith("--"):
            i += 1
        elif len(a) > 1 and a[0] in "-+":
            has_c |= "c" in a[1:]
            i += 1
        else:
            break
    return args[i] if has_c and i < len(args) else None


def _inner_texts(words: list[str]) -> Iterator[str]:
    """The text `eval` or a shell's `-c` would run, anywhere in the command (after `timeout`,
    `sudo -u x`, `env -i` alike)."""
    for i, w in enumerate(words):
        if w == "eval" and i + 1 < len(words):
            yield " ".join(words[i + 1 :])
        elif _name(w) in SHELLS:
            text = _shell_text(words[i + 1 :])
            if text is not None:
                yield text


def _check_inner(words: list[str], cwd: str | None, depth: int) -> None:
    if depth >= MAX_DEPTH:
        return
    for text in _inner_texts(words):
        try:
            check_bash(text, cwd, depth + 1)
        except ValueError:
            continue  # text the shell itself would refuse (an unbalanced quote)


def _home() -> str | None:
    home = os.path.expanduser("~")
    return home if home.startswith("/") else None


def _cd_target(raw: str, cwd: str | None) -> str | None:
    """Where `cd raw` goes, or None when the hook can't tell (`-`, `~user`, a variable)."""
    for prefix in ("~", "$HOME", "${HOME}"):
        if raw == prefix or raw.startswith(prefix + "/"):
            home = _home()
            return None if home is None else os.path.normpath(home + raw[len(prefix) :])
    if raw == "-" or raw.startswith("~") or "$" in raw or "`" in raw:
        return None
    return _resolve(raw, cwd)


def _change_dir(words: list[str], cwd: str | None, dirs: Dirs) -> tuple[str | None, Dirs]:
    """(the folder after `cd`, `pushd` or `popd`, pushd's stack after it)."""
    args: list[str] = []
    for w in words[1:]:
        if set(w) <= set("<>&|"):
            break  # a redirect: `pushd x >/dev/null`
        args.append(w)
    if words[0] == "popd":
        return (dirs[-1], dirs[:-1]) if dirs and not args else (None, dirs[:-1])
    if words[0] == "pushd":
        if any(a[:1] in "+-" for a in args):
            return None, (*dirs, cwd)  # a rotation or -n: not followed
        if not args:
            return (dirs[-1], (*dirs[:-1], cwd)) if dirs else (None, dirs)
        return _cd_target(args[0], cwd), (*dirs, cwd)
    i = 0
    while i < len(args) and (CD_OPTION.fullmatch(args[i]) or args[i] == "--"):
        i += 1
        if args[i - 1] == "--":
            break
    return (_cd_target(args[i], cwd) if i < len(args) else _home()), dirs


def _git_parts(words: list[str]) -> tuple[str | None, str | None, list[str]]:
    """(the `-C` dir, the subcommand, its arguments) of a git command, else (None, None, [])."""
    if not words or _name(words[0]) != "git":
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


def _check_push(args: list[str], cwd: str | None) -> None:
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
    if not refspecs and cwd is not None and _protected(_branch_of(cwd) or ""):
        raise Blocked(f"guard: blocked a push from {_branch_of(cwd)}; {RULE}")


def _clean_args(args: list[str]) -> tuple[set[str], list[str]]:
    """(`git clean`'s one-letter flags, its paths)."""
    flags: set[str] = set()
    paths: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            paths += args[i:]
            break
        if a.startswith("--"):
            flags.add(CLEAN_LONG.get(a.split("=", 1)[0], ""))
            i += a == "--exclude"  # `--exclude <pattern>`
        elif a.startswith("-") and len(a) > 1:
            letters, e, pattern = a[1:].partition("e")
            flags |= set(letters)
            i += bool(e) and not pattern  # `-e <pattern>`
        else:
            paths.append(a)
    return flags, paths


def _check_clean(args: list[str], here: str | None) -> None:
    flags, paths = _clean_args(args)
    if flags & {"n", "i"} or not flags & CLEAN_WIDE:
        return
    if here is not None and all(_in_scratch(p, here) for p in paths or ["."]):
        return  # a checkout below /tmp, or only its scratch folders
    raise Blocked(
        f"guard: blocked `git clean -{''.join(sorted(flags & CLEAN_WIDE))}` (untracked folders or"
        f" ignored files outside /tmp); {RULE}"
    )


def _remote_ref(ref: str) -> bool:
    return ref.startswith(REMOTE_PREFIXES) or "@{u" in ref or "@{push" in ref or ref == "FETCH_HEAD"


def _check_git(words: list[str], cwd: str | None) -> None:
    where, sub, args = _git_parts(words)
    if sub is None:
        return
    here = _resolve(where, cwd) if where else cwd
    if sub == "push":
        _check_push(args, here)
    elif sub == "clean":
        _check_clean(args, here)
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


def check_bash(command: str, cwd: str | None, depth: int = 0) -> None:
    """Judge each simple command in order, following the folder it runs in (`cd`, `pushd`,
    `popd`; a `( )` group keeps its `cd` to itself) and the text a shell is handed."""
    here, dirs = cwd, ()
    groups: list[tuple[str | None, Dirs]] = []
    for part in _parts(command):
        if isinstance(part, str):
            if part == "(":
                groups.append((here, dirs))
            elif groups:
                here, dirs = groups.pop()
            continue
        words = _skip_env(part)
        if not words:
            continue
        if words[0] in DIR_CHANGERS:
            here, dirs = _change_dir(words, here, dirs)
            continue
        _check_redirects(words)
        _check_inner(part, here, depth)
        if not _check_find(part, here):
            _check_rm(part, here)
        _check_git(words, here)


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
