# evals/r6_3/authored.py
"""R6.3.1 eval (docs/plans/r6-3-1-book-at-build.md D4-D9): "the authored pages compile and pass
the checks", the one suite that replaces the runtime writer's (writer, console, needles, e2e and
contract went with the writer, D8). No model, no network, no owner step.

    fixture     a tiny committed repository (tests/r631_i0_fakes.py): a stamped module page with
                its flowchart compiles WRITTEN, filled from the fact pack, with its meta and its
                chart (`from` by its alias); a page with a typed number and a missing page are
                the generator's text; the bytes are the same twice
    checks      each broken page is named by its own check (numbers, refs, personal, planned,
                flow, stale) and a good one passes
    checkout    THIS checkout's written pages, compiled with its own fact pack (cached in
                build/book-cache/): no page fails a check, and every one is served written
                (pages not written yet are allowed: the writers' branches join at I1; CI's
                `pages --check` is the strict gate)

Control: the checks switched off (`authored.check_page` answering no problem) -> the page with a
typed number compiles as written and the `fixture` and `checks` cases fail.
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
    GOOD_BODY,
    PACK,
    hashes_of,
    make_repo,
    page_text,
    write_flow,
    write_page,
)

from jarvis.buildbook.book import authored  # noqa: E402
from jarvis.buildbook.gen import compile_pages, facts_cache  # noqa: E402
from jarvis.buildbook.gen.repo import Repo  # noqa: E402
from jarvis.buildbook.gen.scrub import default_scrubber  # noqa: E402
from jarvis.buildbook.writer import pages  # noqa: E402

PART = "authored"
BUILT = True
MODULE, CARD = "pg_module_demo", "pg_card_c02"
TYPED = GOOD_BODY.replace("Nothing: it runs", "It costs 42 rupees; it runs")
BROKEN = {  # check word -> how the good page is broken for it
    "numbers": TYPED,
    "refs": GOOD_BODY.replace("`pick`", "`src/jarvis/nowhere.py`"),
    "personal": GOOD_BODY.replace("calls nothing else", "mails someone@example.org"),
    "planned": GOOD_BODY.replace("Nothing: it runs", "Nothing yet; soon it runs"),
}
Check = Callable[[], list[str]]


def _need(ok: bool, why: str) -> list[str]:
    return [] if ok else [why]


def _guarded(check: Check) -> list[str]:
    try:
        return check()
    except Exception as exc:  # a case that breaks is a failed case, never a crashed eval
        return [f"{type(exc).__name__}: {str(exc)[:160]}"]


def _stamped(root: Path, pid: str, body: str = GOOD_BODY) -> None:
    refs = next(p for p in PACK.pages if p.id == pid).refs
    write_page(root, pid, page_text(pid, hashes_of(root, refs), body))


def _compile(root: Path) -> compile_pages.Compiled:
    return compile_pages.compile_pages(Repo.from_git(root), PACK, scrub=default_scrubber())


def fixture() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(Path(tmp))
        _stamped(root, MODULE)
        write_flow(root, MODULE)
        _stamped(root, CARD, TYPED)
        one, two = _compile(root), _compile(root)
    f, flows = pages.decode_file(one.pages), pages.decode_flows(one.flows)
    module, card = pages.page_for(MODULE, f), pages.page_for(CARD, f)
    how = next((s.text for s in module.sections if s.id == "how"), "") if module else ""
    out = _need(module is not None and module.meta is not None, "the module page isn't written")
    out += _need("{{fact:" not in how and "3 times" in how, "the module page isn't filled")
    out += _need(card is not None and card.meta is None, "a page with a typed number is served")
    out += _need(set(flows) == {MODULE} and "from" in flows[MODULE]["edges"][0], "the charts")
    counts = {"written": 1, "generator": len(PACK.pages) - 1, "narrated": 0}  # R6.4: no script
    out += _need(one.counts == counts, "the counts")
    return out + _need((one.pages, one.flows) == (two.pages, two.flows), "two compiles differ")


def checks() -> list[str]:
    out: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(Path(tmp))
        repo = Repo.from_git(root)
        env = authored.Env(facts=PACK, scrub=default_scrubber(), repo=repo)
        ip = next(p for p in PACK.pages if p.id == MODULE)
        write_flow(root, MODULE)
        _stamped(root, MODULE)
        out += _need(authored.judge(root, ip, env).status == "ok", "the good page isn't ok")
        for word, body in BROKEN.items():
            _stamped(root, MODULE, body)
            said = authored.judge(root, ip, env).problems
            out += _need(any(p.startswith(f"{word}:") for p in said), f"{word} not named")
        write_page(root, MODULE, page_text(MODULE))  # never stamped
        said = authored.judge(root, ip, env).problems
        out += _need(any(p.startswith("stale:") for p in said), "stale not named")
        (root / authored.BOOK_DIR / "flows" / f"{MODULE}.json").unlink()
        said = authored.judge(root, ip, env).problems
        out += _need(any(p.startswith("flow:") for p in said), "a missing chart not named")
    return out


def checkout() -> list[str]:
    repo = Repo.from_git(ROOT)
    pack, _ = facts_cache.facts_for(repo, facts_cache.build_pack)
    env = authored.Env(facts=pack, scrub=default_scrubber(), repo=repo)
    failing = [ip.id for ip in pack.pages
               if authored.judge(repo.root, ip, env).status == "failing"]  # fmt: skip
    got = compile_pages.compile_pages(repo, pack, scrub=default_scrubber())
    f = pages.decode_file(got.pages)
    written = set(authored.all_pages(repo.root).items)
    served = {p.id for p in f.pages if p.meta is not None}
    out = [f"{pid} fails its checks" for pid in failing[:10]]
    out += _need(written - set(failing) <= served, "a written page isn't served written")
    return out + _need([p.id for p in f.pages] == [ip.id for ip in pack.pages], "the index")


CASES: dict[str, Check] = {"fixture": fixture, "checks": checks, "checkout": checkout}


async def cases() -> list[dict[str, Any]]:
    got = {name: _guarded(check) for name, check in CASES.items()}
    return [{"id": f"{PART}:{n}", "passed": not f, "failures": f} for n, f in got.items()]


def _no_checks() -> dict[str, Check]:
    def off(check: Check) -> Check:
        def run() -> list[str]:
            with mock.patch.object(authored, "page_problems", lambda *_a, **_k: []):
                return check()

        return run

    return {"fixture": off(fixture), "checks": off(checks)}


async def control() -> dict[str, Any]:
    controls = _no_checks()
    still_green = [n for n, check in controls.items() if not _guarded(check)]
    return {
        "name": "the six checks switched off (a page with a typed number compiles as written)",
        "suite_failed": not still_green,
        "failed_cases": [f"{PART}:{n}" for n in controls if n not in still_green],
        "still_green": still_green,
    }
