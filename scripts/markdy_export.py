# scripts/markdy_export.py — check and export the architecture diagrams (R6.1 D2).
"""Every `docs/architecture/diagrams/*.markdy` must pass the privacy rule (plan decision 5:
`player: chrome: badge false`, no share switch, no web address or e-mail in the source), Markdy's
`lint --strict` and `verify --quality showcase`, and have a still SVG + PNG beside it made from its
current source.

    python scripts/markdy_export.py               check, then export SVG + PNG for every diagram
    python scripts/markdy_export.py 04-chat-turn  the same for the named diagram(s) only
    python scripts/markdy_export.py --check       check, and fail when an export is missing or stale
    python scripts/markdy_export.py --lint-only   privacy rule, lint and verify only

Staleness is decided by `exports.json` beside the diagrams: the pinned Markdy version and the
SHA-256 of each source and of the SVG and PNG the export wrote. File times are not used (a git
checkout sets them all to "now"). The export writes every file through a temporary file and
`os.replace`, and rewrites the manifest after EACH diagram, so a run cut short (Chromium dies,
Ctrl-C) leaves hashes that match what is on disk: the finished diagrams pass `--check`, the rest
are reported stale. `--check` and `--lint-only` need Node and the dev-only tool
(`npm ci --prefix tools/markdy`) but no browser. Exporting also needs Python Playwright with its
Chromium (never `playwright install` in the sandbox: it is pre-installed there).

What `--check` proves, and what it does not: that each SVG and PNG is byte for byte the file whose
hash the export wrote for the current source and Markdy version. It does not render again (CI has
no browser), so it trusts `exports.json`: hashes typed in by hand would pass. The export is the
only writer of that file; review a diff to it like code, and re-export + look at the PNG locally.

The Markdy CLI is `@markdy/cli@1.5.7` (MIT), pinned in `tools/markdy/package-lock.json` and used
only here and in CI's `docs` job: never in the app image, the console or the build book. The
browser fetches nothing from the network: the page and the pinned packages are served from disk
and any other request is blocked and reported.

Exit status: 0 all good, 1 a diagram has a problem (each one is logged as "<diagram>: <step>:
<what>"), 2 the tools can't run (Markdy not installed, Node or Playwright missing).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("markdy_export")

ROOT = Path(__file__).resolve().parents[1]
DIAGRAM_DIR = ROOT / "docs" / "architecture" / "diagrams"
TOOL_DIR = ROOT / "tools" / "markdy"
CLI_VERSION = "1.5.7"
CLI_PACKAGE = Path("node_modules") / "@markdy" / "cli"
MANIFEST_NAME = "exports.json"
SOURCE_SUFFIX = ".markdy"
OUTPUT_SUFFIXES = (".svg", ".png")
QUALITY = "showcase"
CLI_TIMEOUT_S = 120
CLI_WORDS_KEPT = 6  # last lines of CLI output quoted in a problem
SHARE_HOST = "markdy.com"

_BADGE_OFF = re.compile(
    r"^player:\s*\n(?:[ \t]+.*\n)*?[ \t]+chrome:\s*\n(?:[ \t]{4,}.*\n)*?[ \t]{4,}badge\s+false\s*$",
    re.M,
)
# Markdy 1.5.7 (core: CONTROLS, parseBooleanToken) switches the share control on with `share`,
# `shareLink` or `share_link` alone or set to true/on/yes/1 (after a space, `:` or `=`), and with
# `controls` alone or switched on (every control); `controls:` alone only opens the group. So any
# of these keys counts as ON unless it is explicitly off, at the start of a line or as key=value.
_SHARE_LINE = re.compile(
    r"^[ \t]*(share|shareLink|share_link|controls)\b(?![ \t]*:[ \t]*$)[ \t]*[:=]?[ \t]*(\S*)", re.M
)
_SHARE_PAIR = re.compile(r"\b(share|shareLink|share_link|controls)[ \t]*=[ \t]*(\S*)")
_OFF = frozenset({"false", "off", "no", "0"})
_URL = re.compile(r"\bhttps?://|\bwww\.|\bmarkdy\.com\b", re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


class SetupError(RuntimeError):
    """The tools can't run (exit 2)."""


class ExportError(RuntimeError):
    """One diagram could not be rendered (a problem for that diagram, exit 1)."""


@dataclass(frozen=True)
class CliResult:
    code: int
    out: str  # stdout only: `verify --json` writes its report here
    err: str = ""  # stderr (Node warnings, errors): quoted in a problem, never parsed


@dataclass(frozen=True)
class Problem:
    diagram: str
    step: str  # privacy | lint | verify | export | fresh | orphan | setup
    detail: str

    def line(self) -> str:
        return f"{self.diagram}: {self.step}: {self.detail}"


class CliAnswer(Protocol):
    @property
    def code(self) -> int: ...
    @property
    def out(self) -> str: ...
    @property
    def err(self) -> str: ...


class Cli(Protocol):
    def __call__(self, args: Sequence[str]) -> CliAnswer: ...


class Renderer(Protocol):
    def __call__(self, source: str) -> tuple[str, bytes]: ...


RendererFactory = AbstractContextManager[Renderer]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    """Write `data` so a reader sees the old file or the new one, never half of one; a failed write
    keeps the old file and leaves no temporary file behind."""
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ---- discovery and the privacy rule --------------------------------------------------------------
def discover(folder: Path, names: Sequence[str] = ()) -> tuple[Path, ...]:
    """The folder's own `*.markdy` files, in name order; with `names`, only those (must exist)."""
    if not folder.is_dir():
        raise SetupError(f"no diagram folder at {folder}")
    found = tuple(sorted(p for p in folder.glob(f"*{SOURCE_SUFFIX}") if p.is_file()))
    if not names:
        return found
    by_stem = {p.stem: p for p in found}
    wanted = [Path(n).name.removesuffix(SOURCE_SUFFIX) for n in names]
    unknown = [w for w in wanted if w not in by_stem]
    if unknown:
        raise SetupError(f"no diagram named {', '.join(unknown)}")
    return tuple(by_stem[w] for w in dict.fromkeys(wanted))


def _shares(text: str) -> bool:
    found = [*_SHARE_LINE.finditer(text), *_SHARE_PAIR.finditer(text)]
    return any(m.group(2).strip("\"'").lower() not in _OFF for m in found)


def privacy_problems(path: Path) -> list[Problem]:
    text = path.read_text(encoding="utf-8")
    text = text if text.endswith("\n") else text + "\n"
    rules = (
        (_BADGE_OFF.search(text) is None, "needs `player: chrome: badge false` (no share link)"),
        (_shares(text), "must not switch the share control on"),
        (_URL.search(text) is not None, "must not hold a web address"),
        (_EMAIL.search(text) is not None, "must not hold an e-mail address"),
    )
    return [Problem(path.stem, "privacy", words) for broken, words in rules if broken]


# ---- lint and verify -----------------------------------------------------------------------------
def _tail(out: str) -> str:
    lines = [ln.strip() for ln in str(out).splitlines() if ln.strip()]
    return " | ".join(lines[-CLI_WORDS_KEPT:]) or "no output"


def _said(result: CliAnswer) -> str:
    return _tail(f"{result.out}\n{result.err}")


def _verify_problem(stem: str, result: CliAnswer) -> Problem | None:
    try:
        report = json.loads(result.out)
        passed, warnings = bool(report["passed"]), int(report.get("warningCount", 0))
        checks = report.get("checks", [])
    except (ValueError, KeyError, TypeError):
        return Problem(stem, "verify", f"the answer is not a report: {_said(result)}")
    failed = [f"{c.get('id')} ({c.get('message')})" for c in checks if c.get("status") != "pass"]
    if passed and not warnings and not failed and result.code == 0:
        return None
    words = "; ".join(failed) if failed else f"{warnings} warning(s)"
    if warnings and failed:
        words += f"; {warnings} warning(s)"
    return Problem(stem, "verify", f"the {QUALITY} quality gate failed: {words}")


def check_source(path: Path, cli: Cli) -> list[Problem]:
    """Privacy rule, then lint --strict, then verify --quality showcase (stops at the first that
    fails: a source that breaks the privacy rule is never handed to any tool)."""
    problems = privacy_problems(path)
    if problems:
        return problems
    linted = cli(["lint", str(path), "--strict"])
    if linted.code != 0:
        return [Problem(path.stem, "lint", _said(linted))]
    verified = _verify_problem(
        path.stem, cli(["verify", str(path), "--quality", QUALITY, "--json"])
    )
    return [verified] if verified else []


# ---- the manifest, staleness and orphans ---------------------------------------------------------
def load_manifest(folder: Path) -> tuple[dict[str, Any], list[Problem]]:
    path = folder / MANIFEST_NAME
    if not path.exists():
        return {"cli": CLI_VERSION, "diagrams": {}}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("diagrams"), dict):
            raise ValueError("no diagrams table")
    except ValueError:
        return {"cli": CLI_VERSION, "diagrams": {}}, [
            Problem("(all)", "fresh", f"{MANIFEST_NAME} can't be read: export again")
        ]
    return data, []


def manifest_bytes(diagrams: dict[str, dict[str, str]]) -> bytes:
    doc = {"cli": CLI_VERSION, "diagrams": dict(sorted(diagrams.items()))}
    return (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8")


def _freshness(path: Path, manifest: dict[str, Any]) -> list[Problem]:
    stem, folder = path.stem, path.parent
    entry = manifest["diagrams"].get(stem)
    if not isinstance(entry, dict):
        return [Problem(stem, "fresh", f"never exported: run scripts/markdy_export.py {stem}")]
    if manifest.get("cli") != CLI_VERSION:
        return [
            Problem(
                stem,
                "fresh",
                f"exported with Markdy {manifest.get('cli')}, pinned is {CLI_VERSION}",
            )
        ]
    out = []
    if entry.get("source") != digest(path.read_bytes()):
        out.append(Problem(stem, "fresh", "the source changed since its export: export again"))
    for suffix in OUTPUT_SUFFIXES:
        made = folder / f"{stem}{suffix}"
        if not made.exists():
            out.append(Problem(stem, "fresh", f"{made.name} is missing"))
        elif entry.get(suffix[1:]) != digest(made.read_bytes()):
            out.append(Problem(stem, "fresh", f"{made.name} is not the one the export wrote"))
    return out


def orphan_problems(folder: Path, manifest: dict[str, Any]) -> list[Problem]:
    sources = {p.stem for p in folder.glob(f"*{SOURCE_SUFFIX}")}
    out = []
    for suffix in OUTPUT_SUFFIXES:
        for made in sorted(folder.glob(f"*{suffix}")):
            if made.stem not in sources:
                out.append(
                    Problem(made.stem, "orphan", f"{made.name} has no {made.stem}{SOURCE_SUFFIX}")
                )
    for stem in sorted(set(manifest["diagrams"]) - sources):
        out.append(
            Problem(
                stem, "orphan", f"{MANIFEST_NAME} lists it but there is no {stem}{SOURCE_SUFFIX}"
            )
        )
    return out


# ---- export --------------------------------------------------------------------------------------
def export_one(path: Path, render: Renderer) -> dict[str, str]:
    """Render, refuse an SVG that carries a share link, write both files, return the entry."""
    source = path.read_bytes()
    svg, png = render(source.decode("utf-8"))
    if SHARE_HOST in svg:
        raise ExportError(f"the SVG links to {SHARE_HOST} (a share link): not written")
    if not png.startswith(b"\x89PNG"):
        raise ExportError("the PNG export is not a PNG")
    svg_bytes = svg.encode("utf-8")
    for name, data in ((f"{path.stem}.svg", svg_bytes), (f"{path.stem}.png", png)):
        try:
            write_atomic(path.parent / name, data)
        except OSError as exc:
            raise ExportError(f"can't write {name}: {exc.strerror or exc}") from exc
    return {"source": digest(source), "svg": digest(svg_bytes), "png": digest(png)}


def _export_all(
    paths: Sequence[Path], renderer: RendererFactory, manifest: dict[str, Any]
) -> list[Problem]:
    """Export each diagram and rewrite the manifest after each one, so a run cut short by an
    exception (a dead browser, Ctrl-C) never leaves new files listed under old hashes. Entries
    made by another Markdy version are dropped: those diagrams stay stale until exported again."""
    same_cli = manifest.get("cli") == CLI_VERSION
    entries: dict[str, dict[str, str]] = dict(manifest["diagrams"]) if same_cli else {}
    folder = paths[0].parent
    problems: list[Problem] = []
    with renderer as render:
        for path in paths:
            try:
                entries[path.stem] = export_one(path, render)
            except ExportError as exc:
                problems.append(Problem(path.stem, "export", str(exc)))
                continue
            write_atomic(folder / MANIFEST_NAME, manifest_bytes(entries))
            log.info("%s: exported %s.svg and %s.png", path.stem, path.stem, path.stem)
    return problems


# ---- the run -------------------------------------------------------------------------------------
def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Check and export the Markdy architecture diagrams.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="fail when an export is missing or stale"
    )
    mode.add_argument("--lint-only", action="store_true", help="privacy rule, lint and verify only")
    ap.add_argument("names", nargs="*", help="diagram names (default: all)")
    ap.add_argument("--diagrams", type=Path, default=DIAGRAM_DIR, help=argparse.SUPPRESS)
    ap.add_argument("--tools", type=Path, default=TOOL_DIR, help=argparse.SUPPRESS)
    return ap.parse_args(list(argv))


def run(args: argparse.Namespace, *, cli: Cli, renderer: RendererFactory, folder: Path) -> int:
    paths = discover(folder, args.names)
    if not paths:
        log.error("no .markdy diagrams in %s", folder)
        return 1
    problems: list[Problem] = []
    passed: list[Path] = []
    for path in paths:
        found = check_source(path, cli)
        problems.extend(found)
        if not found:
            passed.append(path)
    manifest, unreadable = load_manifest(folder)
    if args.check:
        problems.extend(unreadable)
        problems.extend(p for path in paths for p in _freshness(path, manifest))
        problems.extend(orphan_problems(folder, manifest))
    elif not args.lint_only and passed:
        problems.extend(_export_all(passed, renderer, manifest))
    for problem in problems:
        log.error("%s", problem.line())
    log.info("%d diagram(s) checked, %d problem(s)", len(paths), len(problems))
    return 1 if problems else 0


class NodeCli:
    """The pinned Markdy CLI, run as `node <tools>/node_modules/@markdy/cli/dist/index.js` (its npm
    `.bin` link can exit 0 and print nothing)."""

    def __init__(self, tool_dir: Path) -> None:
        package = tool_dir / CLI_PACKAGE
        self._script = package / "dist" / "index.js"
        if not self._script.is_file():
            raise SetupError(f"Markdy is not installed: run npm ci --prefix {tool_dir}")
        try:
            version = json.loads((package / "package.json").read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError, TypeError):
            raise SetupError("the Markdy CLI's package.json can't be read") from None
        if version != CLI_VERSION:
            raise SetupError(f"Markdy {version} is installed; {CLI_VERSION} is pinned: run npm ci")
        self._cwd = tool_dir

    def __call__(self, args: Sequence[str]) -> CliResult:
        try:
            done = subprocess.run(
                ["node", str(self._script), *args],
                cwd=self._cwd,
                capture_output=True,
                text=True,
                timeout=CLI_TIMEOUT_S,
                check=False,
            )
        except FileNotFoundError:
            raise SetupError("node is not installed (Markdy needs Node.js)") from None
        except subprocess.TimeoutExpired:
            return CliResult(124, "", f"timed out after {CLI_TIMEOUT_S} s")
        return CliResult(done.returncode, done.stdout, done.stderr)


def _chromium(tool_dir: Path) -> RendererFactory:
    """`markdy_render.ChromiumRenderer`, loaded from beside this file (any sys.path); it starts a
    browser only when entered, which only the export mode does."""
    path = Path(__file__).with_name("markdy_render.py")
    spec = importlib.util.spec_from_file_location("markdy_render", path)
    if spec is None or spec.loader is None:
        raise SetupError(f"{path.name} is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    renderer: RendererFactory = module.ChromiumRenderer(
        tool_dir, setup_error=SetupError, export_error=ExportError
    )
    return renderer


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        cli = NodeCli(args.tools)
        return run(args, cli=cli, renderer=_chromium(args.tools), folder=args.diagrams)
    except SetupError as exc:
        log.error("setup: %s", exc)
        return 2
    except OSError as exc:  # a source or exports.json that can't be read or written
        log.error("setup: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "CLI_VERSION",
    "MANIFEST_NAME",
    "CliAnswer",
    "CliResult",
    "ExportError",
    "NodeCli",
    "Problem",
    "SetupError",
    "check_source",
    "digest",
    "discover",
    "export_one",
    "load_manifest",
    "main",
    "manifest_bytes",
    "orphan_problems",
    "parse_args",
    "privacy_problems",
    "run",
    "write_atomic",
]
