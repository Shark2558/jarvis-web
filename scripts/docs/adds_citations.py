#!/usr/bin/env python3
# scripts/docs/adds_citations.py
"""Every repository citation in the Architecture Design Document must exist.

    python scripts/docs/adds_citations.py [--root DIR]   exit 0 when all exist, 1 with the list

Reads `docs/architecture/design/[0-9][0-9]-*.md`. A citation is a code span (between backticks,
outside fenced code) that is a repository path, `path:Symbol` or `path:LINE`:

- a path under `src/`, `tests/`, `evals/`, `scripts/`, `deploy/`, `docs/`, `android/`, `tools/`,
  `.github/` or `.claude/`, or one of the top-level files in `TOP_FILES`;
- `*`, `?` and `[...]` are globs that must match something; `…` stands for folded folders (the
  matrix folds Kotlin package paths); a span with `<` or `{` is a pattern, not a citation;
- a path that is missing here is tried under `src/jarvis/` (chapter 05's shorthand);
- `Symbol` in a Python file is a top-level function, class or name, or `Class.member`, read from
  the file's syntax tree; in any other file it must appear in the text; `LINE` must be within it.

A missing path on a line that says "branch" or "planned" is listed as kept elsewhere (a plan on an
unmerged branch, a folder a release will add), never failed; so is a file the build writes
(`GENERATED`). Standard library only (chapter 13).
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

DESIGN = "docs/architecture/design"
ROOTS = (
    "src", "tests", "evals", "scripts", "deploy", "docs", "android", "tools", ".github", ".claude"
)
TOP_FILES = frozenset(
    {
        "Dockerfile",
        "Makefile",
        "pyproject.toml",
        "requirements.lock",
        "requirements-build.in",
        "render.yaml",
        "README.md",
        "CLAUDE.md",
        "docker-compose.yml",
        ".gitignore",
    }
)
# Files the build writes (git-ignored): cited, never in a checkout.
GENERATED = frozenset({"src/jarvis/BUILD_DATE", "src/jarvis/buildbook/_book"})
SPAN = re.compile(r"`([^`\n]+)`")
PATH = re.compile(rf"^(?:{'|'.join(re.escape(r) for r in ROOTS)})/[^\s]*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
ELSEWHERE = re.compile(r"\bbranch(es)?\b|\bplanned\b", re.IGNORECASE)
GLOB = re.compile(r"[*?\[]")


@dataclass
class Report:
    checked: int = 0
    problems: list[str] = field(default_factory=list)
    elsewhere: list[str] = field(default_factory=list)


def _lines(text: str) -> Iterator[tuple[int, str]]:
    """(line number, line) for the lines outside fenced code."""
    fence = ""
    for number, line in enumerate(text.splitlines(), 1):
        m = FENCE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = ""
        elif m:
            fence = m.group(1)
        else:
            yield number, line


def citation(span: str) -> tuple[str, str] | None:
    """(path, symbol) when the span is a repository citation, else None."""
    span = span.strip().rstrip(".,;)")
    if " " in span or "<" in span or "{" in span:
        return None
    path, _, symbol = span.partition(":")
    if path in TOP_FILES or PATH.match(path):
        return path, symbol
    return None


def _symbols(path: Path) -> set[str] | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    names: set[str] = set()

    def targets(node: ast.AST) -> list[str]:
        if isinstance(node, ast.Assign):
            found = node.targets
        elif isinstance(node, ast.AnnAssign):
            found = [node.target]
        else:
            return []
        out: list[str] = []
        for t in found:
            elements = t.elts if isinstance(t, ast.Tuple) else [t]
            out += [e.id for e in elements if isinstance(e, ast.Name)]
        return out

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            if isinstance(node, ast.ClassDef):
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        names.add(f"{node.name}.{member.name}")
                    names.update(f"{node.name}.{t}" for t in targets(member))
        names.update(targets(node))
    return names


def _resolve(root: Path, path: str) -> list[Path]:
    """The files or folders the path names (several for a glob), or none."""
    pattern = path.replace("…", "**").rstrip("/")
    for candidate in (pattern, f"src/jarvis/{pattern}"):
        if GLOB.search(candidate) or "**" in candidate:
            found = sorted(root.glob(candidate))
        else:
            found = [root / candidate] if (root / candidate).exists() else []
        if found:
            return found
    return []


def _symbol_problem(target: Path, symbol: str) -> str | None:
    if not symbol or not target.is_file():
        return None
    text = target.read_text(encoding="utf-8", errors="ignore")
    if symbol.isdigit():
        n = len(text.splitlines())
        return None if 1 <= int(symbol) <= n else f"line {symbol} is past the end ({n} lines)"
    if target.suffix == ".py":
        names = _symbols(target)
        return None if names and symbol in names else f"no symbol {symbol} in that file"
    return None if symbol in text else f"{symbol} does not appear in that file"


def check(root: Path) -> Report:
    report = Report()
    for chapter in sorted((root / DESIGN).glob("[0-9][0-9]-*.md")):
        rel = chapter.relative_to(root).as_posix()
        for number, line in _lines(chapter.read_text(encoding="utf-8")):
            for m in SPAN.finditer(line):
                cited = citation(m.group(1))
                if cited is None:
                    continue
                path, symbol = cited
                report.checked += 1
                where = f"{rel}:{number} `{m.group(1).strip()}`"
                found = _resolve(root, path)
                if not found:
                    if ELSEWHERE.search(line) or path.rstrip("/") in GENERATED:
                        report.elsewhere.append(where)
                    else:
                        report.problems.append(f"{where}: no such path")
                    continue
                problem = _symbol_problem(found[0], symbol.rstrip(".,;)"))
                if problem:
                    report.problems.append(f"{where}: {problem}")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    report = check(args.root)
    for problem in report.problems:
        print(problem)
    for item in report.elsewhere:
        print(f"kept elsewhere (a branch or a planned folder): {item}")
    print(
        f"adds_citations: {report.checked} citations, {len(report.problems)} missing, "
        f"{len(report.elsewhere)} kept elsewhere"
    )
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
