# tests/markdy_fakes.py — R6.1 D2: a stand-in Markdy CLI and renderer for scripts/markdy_export.py.
"""`FakeCli` answers `lint` / `verify` the way `@markdy/cli@1.5.7` does (lint: exit code and text;
verify --json: a report with `passed`, counts and checks, on stdout), with per-diagram failures set
by the test. `FakeRenderer` turns a source into deterministic SVG text and PNG bytes and counts its
calls, so a test can prove the check mode never renders. `FakeRoute` and `FakeBrowser` stand in for
Playwright's route and browser in `markdy_render.ChromiumRenderer`'s own tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
GOOD_SOURCE = (
    'scene "A diagram" theme=paper\nlayout LR\n\nservice A "A"\nservice B "B"\n\n'
    'beat one "One":\n  A -> B "call"\n\nplayer:\n  chrome:\n    badge false\n'
)


@dataclass(frozen=True)
class Answer:
    code: int
    out: str
    err: str = ""


def verify_report(failed: Sequence[str] = (), warnings: int = 0) -> str:
    checks: list[dict[str, Any]] = [
        {"id": cid, "status": "fail", "message": f"{cid} is not met"} for cid in failed
    ]
    checks.append({"id": "syntax_validity", "status": "pass", "message": "ok"})
    report = {
        "passed": not failed and not warnings,
        "qualityProfile": "showcase",
        "errorCount": len(failed),
        "warningCount": warnings,
        "checks": checks,
    }
    return json.dumps(report)


@dataclass
class FakeCli:
    lint_fail: dict[str, str] = field(default_factory=dict)  # stem -> output
    verify_fail: dict[str, tuple[str, ...]] = field(default_factory=dict)  # stem -> check ids
    verify_raw: dict[str, str] = field(default_factory=dict)  # stem -> raw stdout
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(self, args: Sequence[str]) -> Answer:
        self.calls.append(tuple(args))
        command, target = args[0], Path(args[1]).stem
        if command == "lint":
            if target in self.lint_fail:
                return Answer(1, self.lint_fail[target])
            return Answer(0, f"OK   {args[1]}\nmarkdy lint: PASS — 1 file(s), 0 warning(s).")
        if command == "verify":
            if target in self.verify_raw:
                return Answer(1, self.verify_raw[target])
            failed = self.verify_fail.get(target, ())
            return Answer(1 if failed else 0, verify_report(failed))
        return Answer(2, f"unknown command {command}")


@dataclass
class FakeRenderer:
    svg_extra: str = ""
    calls: int = 0
    entered: int = 0

    def __enter__(self) -> FakeRenderer:
        self.entered += 1
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def __call__(self, source: str) -> tuple[str, bytes]:
        self.calls += 1
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg"><!-- {len(source)} -->{self.svg_extra}</svg>'
        )
        return svg, PNG_MAGIC + source.encode("utf-8")


class ExplodingRenderer(FakeRenderer):
    """A renderer the check and lint-only modes must never use."""

    def __enter__(self) -> FakeRenderer:
        raise AssertionError("this mode must not start a browser")


@dataclass
class FakeRequest:
    url: str


@dataclass
class FakeRoute:
    """Playwright's `Route` as `ChromiumRenderer._serve` uses it: a request URL, abort, fulfill."""

    url: str
    aborted: bool = False
    answer: dict[str, Any] | None = None

    @property
    def request(self) -> FakeRequest:
        return FakeRequest(self.url)

    def abort(self) -> None:
        self.aborted = True

    def fulfill(self, **answer: Any) -> None:
        self.answer = answer


@dataclass
class FakePage:
    """A page whose first navigation raises `failure` (a browser that dies or times out)."""

    failure: BaseException
    closed: bool = False

    def on(self, event: str, handler: Any) -> None:
        return None

    def route(self, pattern: str, handler: Any) -> None:
        return None

    def goto(self, url: str) -> None:
        raise self.failure

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeBrowser:
    failure: BaseException
    pages: list[FakePage] = field(default_factory=list)

    def new_page(self, **options: Any) -> FakePage:
        page = FakePage(self.failure)
        self.pages.append(page)
        return page


__all__ = [
    "GOOD_SOURCE",
    "PNG_MAGIC",
    "Answer",
    "ExplodingRenderer",
    "FakeBrowser",
    "FakeCli",
    "FakePage",
    "FakeRenderer",
    "FakeRequest",
    "FakeRoute",
    "verify_report",
]
