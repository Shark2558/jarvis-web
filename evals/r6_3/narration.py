# evals/r6_3/narration.py
"""R6.4 eval (docs/plans/r6-4-book-look.md D6, "Tests and evals"): "the narration scripts compile
and pass the checks". No model, no network, no owner step.

    fixture     a tiny committed repository (tests/r631_i0_fakes.py): a stamped chapter script
                compiles NARRATED with the pages, its facts filled (a count cue's target too), its
                minutes and who wrote it; a script with a typed number is listed without its
                lines; the bytes are the same twice
    checks      the good script is ok, and each broken line is named by its own check (numbers,
                cues, spoken, personal, shape), an unstamped one by `stale:`
    checkout    THIS checkout's 26 scripts (the fact pack cached in build/book-cache/): none fails
                a check, and every chapter whose pages are all written is compiled narrated

Control: the line checks switched off (`narration_check.cue_problems` and `spoken_problems`
answering no problem) -> the script with a typed number compiles narrated and a broken line is
named by nothing, so the `fixture` and `checks` cases fail.
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from r631_i0_fakes import (  # noqa: E402
    PACK,
    hashes_of,
    make_repo,
    page_text,
    write_flow,
    write_page,
)
from test_r64_i0_narration import GOOD_LINES, script, write_script  # noqa: E402

from jarvis.buildbook.book import authored  # noqa: E402
from jarvis.buildbook.book import chapters as ch  # noqa: E402
from jarvis.buildbook.book import narration_check as nc  # noqa: E402
from jarvis.buildbook.book.files import stamped  # noqa: E402
from jarvis.buildbook.book.narration import script_path  # noqa: E402
from jarvis.buildbook.gen import compile_pages, facts_cache  # noqa: E402
from jarvis.buildbook.gen.repo import Repo  # noqa: E402
from jarvis.buildbook.gen.scrub import default_scrubber  # noqa: E402
from jarvis.buildbook.writer import pages  # noqa: E402

PART = "narration"
BUILT = True
DEMO, STORY = "module_demo", "story_example"
TYPED = "[show:title] The running example costs 42 rupees a month."  # a typed number
BROKEN = {  # check word -> the line that breaks the good script for it (as its second line)
    "numbers": "[show:overview] It tries 3 times before it gives up.",
    "cues": "[node:nowhere] A box that isn't in the flowchart.",
    "spoken": "[show:overview] It reads the file `router.py` aloud.",
    "personal": "[show:overview] It mails someone@example.org every morning.",
    "shape": "[show:overview] " + "A very long spoken line that goes on and on. " * 7,
}
Check = Callable[[], list[str]]


def _need(ok: bool, why: str) -> list[str]:
    return [] if ok else [why]


def _guarded(check: Check) -> list[str]:
    try:
        return check()
    except Exception as exc:  # a case that breaks is a failed case, never a crashed eval
        return [f"{type(exc).__name__}: {str(exc)[:160]}"]


def _repo(tmp: str) -> Path:
    root = make_repo(Path(tmp))
    for page in PACK.pages:
        write_page(root, page.id, page_text(page.id, hashes_of(root, page.refs)))
    for pid in ("pg_chapter_example", "pg_module_demo"):
        write_flow(root, pid)
    return root


def _plan(chapter: str) -> ch.ChapterPlan:
    plan = ch.find(ch.chapters(PACK.pages), chapter)
    assert plan is not None, chapter
    return plan


def _write(root: Path, lines: list[str], chapter: str = DEMO, *, stamp: bool = True) -> None:
    write_script(root, script(lines, chapter=chapter), name=chapter)
    if stamp:
        path = script_path(root, chapter)
        now = nc.stamps(root, _plan(chapter))
        path.write_text(stamped(path.read_text(encoding="utf-8"), now, "pages"), encoding="utf-8")


def _env(root: Path) -> authored.Env:
    return authored.Env(facts=PACK, scrub=default_scrubber(), repo=Repo.from_git(root))


def fixture() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = _repo(tmp)
        _write(root, GOOD_LINES)
        _write(root, [TYPED], STORY)
        one = compile_pages.compile_pages(Repo.from_git(root), PACK, scrub=default_scrubber())
        two = compile_pages.compile_pages(Repo.from_git(root), PACK, scrub=default_scrubber())
    f = pages.decode_file(one.pages)
    told = {c.id: c for c in (f.narration.chapters if f.narration is not None else ())}
    demo, story = told.get(DEMO), told.get(STORY)
    out = _need(demo is not None and demo.narrated, "the good script isn't compiled narrated")
    lines = demo.lines if demo is not None else ()
    out += _need(len(lines) == len(GOOD_LINES), "the narrated chapter lost a line")
    texts = [ln.text for ln in lines] + [c.target for ln in lines for c in ln.cues]
    out += _need(bool(texts) and all("{{" not in t for t in texts), "a fact isn't filled")
    out += _need(demo is not None and demo.minutes >= 1 and demo.written is not None, "the meta")
    out += _need(story is not None and not story.narrated, "a script with a typed number is told")
    out += _need(one.counts.get("narrated") == 1, "the narrated count")
    return out + _need((one.pages, one.flows) == (two.pages, two.flows), "two compiles differ")


def checks() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = _repo(tmp)
        env, plan = _env(root), _plan(DEMO)
        _write(root, GOOD_LINES)
        good = nc.judge_script(root, plan, env)
        out = _need(good.status == "ok", f"the good script is {good.status}: {good.problems[:2]}")
        for word, line in BROKEN.items():
            _write(root, [GOOD_LINES[0], line, *GOOD_LINES[2:]])
            said = nc.judge_script(root, plan, env).problems
            out += _need(any(p.startswith(f"{word}:") for p in said), f"{word} not named")
        _write(root, GOOD_LINES, stamp=False)
        said = nc.judge_script(root, plan, env).problems
        out += _need(any(p.startswith(nc.STALE) for p in said), "an unstamped script not stale")
    return out


def checkout() -> list[str]:
    repo = Repo.from_git(ROOT)
    pack, _ = facts_cache.facts_for(repo, facts_cache.build_pack)
    env = authored.Env(facts=pack, scrub=default_scrubber(), repo=repo)
    plans = ch.chapters(pack.pages)
    verdicts = {p.id: nc.judge_script(repo.root, p, env).status for p in plans}
    out = [f"{cid}: {s}" for cid, s in verdicts.items() if s in ("failing", "missing")][:10]
    got = compile_pages.compile_pages(repo, pack, scrub=default_scrubber())
    f = pages.decode_file(got.pages)
    written = {p.id for p in f.pages if p.meta is not None}
    whole = [p.id for p in plans if all(pid in written for pid in p.pages)]
    told = {c.id for c in (f.narration.chapters if f.narration is not None else ()) if c.narrated}
    out += _need(len(plans) == 27, f"{len(plans)} chapters, not 27")  # R18: module_calls
    return out + _need(set(whole) <= told, f"not narrated: {sorted(set(whole) - told)[:5]}")


CASES: dict[str, Check] = {"fixture": fixture, "checks": checks, "checkout": checkout}


async def cases() -> list[dict[str, Any]]:
    got = {name: _guarded(check) for name, check in CASES.items()}
    return [{"id": f"{PART}:{n}", "passed": not f, "failures": f} for n, f in got.items()]


def _no_checks() -> dict[str, Check]:
    def off(check: Check) -> Check:
        def run() -> list[str]:
            with (
                mock.patch.object(nc, "cue_problems", lambda *_a, **_k: []),
                mock.patch.object(nc, "spoken_problems", lambda *_a, **_k: []),
            ):
                return check()

        return run

    return {"fixture": off(fixture), "checks": off(checks)}


async def control() -> dict[str, Any]:
    controls = _no_checks()
    still_green = [n for n, check in controls.items() if not _guarded(check)]
    return {
        "name": "the narration line checks switched off (a typed number is told)",
        "suite_failed": not still_green,
        "failed_cases": [f"{PART}:{n}" for n in controls if n not in still_green],
        "still_green": still_green,
    }
