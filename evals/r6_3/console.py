# evals/r6_3/console.py
"""R6.3 eval, part C's `console` suite (BUILT at I1; docs/plans/r6-3-book-content.md "Tests and
evals": "`console` (C, browser)"). C left I0's stub (INTEGRATION-C 5.2); I1 built it as C
suggested: C's browser tests, by name, are its cases, run in a real Chromium against C's fake
server (tests/r63_fakes_c.py over I0's): the trial (estimate, what is sent, the YES box refusing
"yes", progress with "Step while I watch", the side by side), the pick (the caps' defaults, each
grant's ₹ words and YES box, "Keep" sends nothing, lowering saves at once), the first write's YES,
Update's YES and Stop, the Full book (a written page, "Not written by AI yet", references, an
older release, continue), 44 px targets, 360 x 800 and 1280 x 800, day and night, the panel with
the writer off laid out as without R6.3's boxes.

They need a Python with Playwright and Chromium: `JARVIS_BROWSER_PYTHON`, else this Python when it
has Playwright. Without one the suite FAILS with that reason (a browser suite never passes unseen).

Negative control (the plan's): the YES box sending "yes" whatever was typed (C's fake server
serves a changed COPY of console-book-writer.js when R63C_CONTROL=yes_box_sends_yes; the file on
disk is never touched): the trial's YES case must fail while the estimate's case (no YES sent)
still passes, so the run itself did not just break.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PART = "console"
BUILT = True
FILES = ("test_r63_c_trial.py", "test_r63_c_pick.py", "test_r63_c_pages.py", "test_r63_c_look.py")
YES_CASE = "test_r63_c_trial_yes_starts_it_and_steps_while_i_watch"
NO_YES_CASE = "test_r63_c_trial_the_estimate_what_is_sent_and_to_whom_come_first"
TIMEOUT_S = 2_400


def browser_python() -> str | None:
    named = os.environ.get("JARVIS_BROWSER_PYTHON")
    if named:
        return named
    return sys.executable if importlib.util.find_spec("playwright") is not None else None


def run(files: tuple[str, ...], *, control: str = "") -> list[dict[str, Any]]:
    py = browser_python()
    if py is None:
        why = "needs a Python with Playwright and Chromium (set JARVIS_BROWSER_PYTHON)"
        return [{"id": f"{PART}:browser", "passed": False, "failures": [why]}]
    with tempfile.TemporaryDirectory(prefix="r63c-") as tmp:
        report = Path(tmp) / "browser.xml"
        args = [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "browser",
                f"--junitxml={report}", *(f"tests/browser/{f}" for f in files)]  # fmt: skip
        env = {**os.environ, "JARVIS_BROWSER_TESTS": "1", "PYTHONPATH": str(ROOT / "src")}
        env.pop("R63C_SHOTS", None)  # no pictures from the eval
        if control:
            env["R63C_CONTROL"] = control
        subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
                       cwd=ROOT, env=env)  # fmt: skip
        return junit(report)


def junit(report: Path) -> list[dict[str, Any]]:
    if not report.is_file():
        return [{"id": f"{PART}:browser", "passed": False, "failures": ["the browser run failed"]}]
    out = []
    for tc in ET.parse(report).getroot().iter("testcase"):
        bad = [x.get("message", "")[:300] for x in tc if x.tag in ("failure", "error", "skipped")]
        out.append({"id": f"{PART}:{tc.get('name')}", "passed": not bad, "failures": bad})
    return out or [{"id": f"{PART}:browser", "passed": False, "failures": ["no test ran"]}]


async def cases() -> list[dict[str, Any]]:
    return await asyncio.to_thread(run, FILES)


async def control() -> dict[str, Any]:
    got = {c["id"]: c for c in await asyncio.to_thread(run, FILES[:1], control="yes_box_sends_yes")}
    yes, no_yes = got.get(f"{PART}:{YES_CASE}"), got.get(f"{PART}:{NO_YES_CASE}")
    turned = yes is not None and not yes["passed"] and no_yes is not None and no_yes["passed"]
    return {
        "name": 'C: the YES box sending "yes" whatever was typed (a changed copy served)',
        "suite_failed": turned,
        "failed_cases": [f"{i} {c['failures'][:1]}" for i, c in got.items() if not c["passed"]],
    }
