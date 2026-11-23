# evals/r6_3/tour.py
# ruff: noqa: E501 -- the Node harness is JavaScript
"""R6.3 eval, part D's `tour` suite (evals/r6_3/run.py; docs/plans/r6-3-book-content.md "Tests and
evals", D9, H1, M6), BUILT, on this branch's filled tour (`gen/tour.build` over the plan's values,
`tests/r63_fakes_d.py`, until A's fact pack joins) and 47ee8fc's real show. No model is called.

Cases (each the eval case of a named test in tests/test_r63_d_*.py):
- `bands`: the owner's tour 780-870 s, a guest's 760-850 s, both inside 600-900 s;
- `seven` (row 380's own): the highlights are his seven, in his order;
- `example`: both running-example lines ("Add a dentist appointment on Friday at 5 pm",
  "Cancel it");
- `words`: every spoken line byte-identical to the plan's approved script once filled, no doubled
  word (L1);
- `guest_no_rupee`: a guest's tour has no T16, no owner-only line and no Rs, lines AND pictures;
- `guest_speak_404`: through the real route, a guest's speak of every owner-only tour id is 404
  `unknown_line` and every line of the guest's tour speaks (H1);
- `old_book`: an older book (no tour) serves today's 11 scenes, `kind: "show"`;
- `what_else`: T14 lists the 11 other modules from the module map;
- `pictures` (M6): every scene's picture data has what its `visual` reads, for both audiences;
- `player`: the show's own script reader and the tour's hooks (console-book-script.js,
  console-book-tour.js, under Node) read all 17 scenes (16 for a guest), Questions and Closing as
  pictures 12 and 13, each scene as its own `visual` with its own facts, and continue's place.
  With JARVIS_R63_TOUR_BROWSER=1 the browser file (2D, 3D, Motion Off) runs too, a case a test.

Controls (each must turn its case red): T13's owner line left in the guest's tour
(`guest_no_rupee`); `tour_line_text` ignoring the audience (`guest_speak_404`); Wardrobe & Try-on
dropped (`seven`, row 380's own); the pace at 290 words a minute (`bands`); T12's picture facts
without a group (`pictures`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from book_app_fakes import book, book_app, open_book, register_passkey, sign_in  # noqa: E402
from book_show_fakes import Clock, FixtureSource  # noqa: E402
from r63_fakes_d import OLD_BOOK, PLAN_VALUES, TourSource, approved, built, fill  # noqa: E402

from jarvis.buildbook import tour_model, tour_serve  # noqa: E402
from jarvis.buildbook.gen import modules  # noqa: E402
from jarvis.buildbook.gen import tour as gen_tour  # noqa: E402
from jarvis.buildbook.gen.repo import GenError  # noqa: E402
from jarvis.buildbook.lines import CLOSING, render  # noqa: E402
from jarvis.buildbook.tour_model import AIMED_S, HARD_BAND_S, HIGHLIGHTS, Tour, TourScript  # noqa: E402
from jarvis.config import LLMBackend, SessionBackend, Settings  # noqa: E402

PART = "tour"
BUILT = True
RUPEE = re.compile("₹|\\bRs\\b|rupee", re.IGNORECASE)
DOUBLED = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
EXAMPLE = ('"Add a dentist appointment on Friday at 5 pm', '"Cancel it')
WORDS = {"h": "Sir", "his": "his", "by": "the Workshop, my owner"}
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
MARK = "R63TOUR "


class World:
    """What a case runs on; a control replaces one part of it (no dataclass: run.py loads this file
    by path without a sys.modules entry)."""

    def __init__(
        self,
        script: TourScript | None = None,  # None: gen/tour.json
        tweak: Callable[[Tour], Tour] | None = None,
        patch: Callable[[], AbstractContextManager[Any]] = nullcontext,
    ) -> None:
        self.script, self.tweak, self.patch = script, tweak, patch

    def tour(self) -> Tour:
        got = built(script=self.script)
        if got is None:
            raise GenError("no tour was built")
        return got if self.tweak is None else self.tweak(got)


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
    )


def _lines(aud: tour_model.AudienceTour) -> list[str]:
    return [b.text for s in aud.scenes for b in s.beats]


# ---- the cases ---------------------------------------------------------------------------------
async def _bands(w: World) -> list[str]:
    t, out = w.tour(), []
    for who, aud in (("owner", t.owner), ("guest", t.guest)):
        low, high = AIMED_S[who]
        if not (low <= aud.seconds <= high and HARD_BAND_S[0] <= aud.seconds <= HARD_BAND_S[1]):
            out.append(f"the {who}'s tour times {aud.seconds} s")
    return out


async def _seven(w: World) -> list[str]:
    t = w.tour()
    return [
        f"the {who}'s highlights are {got}"
        for who, aud in (("owner", t.owner), ("guest", t.guest))
        if (got := tuple(s.id for s in aud.scenes if s.title.startswith("Highlight ")))
        != HIGHLIGHTS
    ]


async def _example(w: World) -> list[str]:
    t = w.tour()
    return [
        f"the {who}'s tour lacks {line}"
        for who, aud in (("owner", t.owner), ("guest", t.guest))
        for line in EXAMPLE
        if line not in " ".join(_lines(aud))
    ]


async def _words(w: World) -> list[str]:
    t, plan, out = w.tour(), {b.id: b.text for s in approved() for b in s.beats}, []
    for aud, minutes in ((t.owner, 14), (t.guest, 13)):
        values = {**PLAN_VALUES, "tour.minutes": minutes}
        for s in aud.scenes:
            for b in s.beats:
                if b.text != fill(plan[b.id], values) or DOUBLED.search(b.text):
                    out.append(f"{b.id} is not the approved line")
    return out


async def _guest_no_rupee(w: World) -> list[str]:
    guest, out = w.tour().guest, []
    if any(s.n == 16 for s in guest.scenes):
        out.append("a guest's tour has T16")
    if any(b.audience == "owner" for s in guest.scenes for b in s.beats):
        out.append("a guest's tour has an owner-only line")
    if RUPEE.search(" ".join(_lines(guest))):
        out.append("a guest's line names rupees")
    if RUPEE.search(json.dumps([f.model_dump() for s in guest.scenes for f in s.picture.facts])):
        out.append("a guest's picture names rupees")
    return out


async def _speak(audience: str, lines: list[str], w: World) -> dict[str, Any]:
    got: dict[str, Any] = {}
    async for app in book_app(_settings(), source=TourSource(w.tour())):
        async with sign_in(app) as c:
            app.state.book_clock = Clock()
            auth = await register_passkey(c)
            h = book((await open_book(c, auth, audience))["token"])
            for line in lines:
                r = await c.post("/v1/book/show/speak", json={"line_id": line}, headers=h)
                got[line] = (r.status_code, r.json().get("error"))
    return got


async def _guest_speak_404(w: World) -> list[str]:
    t = w.tour()
    owner_only = [
        b.id for s in t.owner.scenes for b in s.beats if "owner" in (s.audience, b.audience)
    ]
    guest_ids = [b.id for s in t.guest.scenes for b in s.beats]
    got = await _speak("guest", [*owner_only, *guest_ids], w)
    out = [
        f"a guest's speak of {i} answered {got[i]}"
        for i in owner_only
        if got[i] != (404, "unknown_line")
    ]
    out += [f"a guest's {i} did not speak" for i in guest_ids if got[i][0] == 404]
    return out + ([] if owner_only == ["t13b03", "t16b01"] else [f"owner-only ids {owner_only}"])


async def _old_book(w: World) -> list[str]:
    out = (
        []
        if tour_serve.tour_lines(OLD_BOOK, "owner", WORDS) is None
        else ["an old book has a tour"]
    )
    async for app in book_app(_settings(), source=FixtureSource()):
        async with sign_in(app) as c:
            app.state.book_clock = Clock()
            auth = await register_passkey(c)
            h = book((await open_book(c, auth, "owner"))["token"])
            got = (await c.get("/v1/book/show/script", headers=h)).json()
    if got.get("kind") != "show" or [s["n"] for s in got["scenes"]] != list(range(1, 12)):
        out.append("an older book does not serve today's 11 scenes")
    return out


async def _what_else(w: World) -> list[str]:
    titles = {m.id: m.title for m in modules.MODULES}
    want = [titles[m] for m in modules.others()]
    got = [f.label for f in w.tour().guest.scenes[13].picture.facts]
    return [] if got == want and len(want) == 11 else [f"T14 lists {got}"]


async def _pictures(w: World) -> list[str]:
    t = w.tour()
    return [
        f"{who} T{s.n:02d}: {p}"
        for who, aud in (("owner", t.owner), ("guest", t.guest))
        for s in aud.scenes
        for p in gen_tour.picture_problems(s.picture.visual, s.picture.facts)
    ]


CASES: dict[str, Callable[[World], Awaitable[list[str]]]] = {
    "bands": _bands,
    "seven": _seven,
    "example": _example,
    "words": _words,
    "guest_no_rupee": _guest_no_rupee,
    "guest_speak_404": _guest_speak_404,
    "old_book": _old_book,
    "what_else": _what_else,
    "pictures": _pictures,
}


async def run_case(name: str, w: World) -> dict[str, Any]:
    try:
        with w.patch():
            failures = await CASES[name](w)
    except GenError as exc:
        failures = [f"GenError: {exc}"]
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures}


# ---- the player: the show's own script reader and the tour's hooks, under Node ------------------
PLAYER_JS = r"""
const fs = require('fs'), vm = require('vm');
const spec = JSON.parse(fs.readFileSync(process.argv[1], 'utf8')), out = {};
function load(store) {
  const ls = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } };
  const ctx = vm.createContext({ window: {}, localStorage: ls });
  spec.files.forEach((f) => vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f }));
  return ctx.window;
}
for (const [who, raw] of Object.entries(spec.scripts)) {
  const store = {}, w = load(store), SC = w.JarvisBookScript, T = w.JarvisBookTour;
  const sc = SC.normalScript(raw, raw.audience), tl = SC.timeline(sc);
  const r = { kind: sc.kind, scenes: sc.scenes.map((s) => s.n), qn: sc.qn, cn: sc.cn, timeline: tl.length,
    pictures: sc.scenes.map((s) => { const p = SC.picture(sc, s.n, tl); return [p.n, p.facts.length, p.id]; }),
    q: SC.picture(sc, sc.qn, tl).n, c: SC.picture(sc, sc.cn, tl).n };
  if (sc.kind === 'tour') {
    r.first = T.start(sc, tl);
    T.seen(sc, tl.find((b) => b.scene === 7 && b.i === 1));
    r.stored = store.jarvis_book_place_v1 ? JSON.parse(store.jarvis_book_place_v1) : null;
    const again = load(store).JarvisBookTour, sc2 = SC.normalScript(raw, raw.audience);
    r.resume = again.start(sc2, SC.timeline(sc2));
    r.scene7 = tl.findIndex((b) => b.scene === 7 && b.i === 0);
    r.labels = sc.scenes.map((s) => T.label(sc, s.n, s.title));
  }
  out[who] = r;
}
console.log('R63TOUR ' + JSON.stringify(out));
"""


def _raw(audience: str, scenes: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    def said(i: str) -> dict[str, str]:
        return {"id": i, "text": render(i, **WORDS)}

    return {
        "kind": kind, "scenes": scenes, "audience": audience, "costs": {}, "talk": {"on": True},
        "release": {"id": "3f2a1c9", "label": "R6.3", "version": "v6.3.0"},
        "lines": {k: said(k) for k in ("ask", "anything_else", "ai_off")},
        "closing": [said(i) for i in CLOSING[audience]], "until": "2099-01-01T00:00:00+00:00",
    }  # fmt: skip


def _player_run(t: Tour) -> dict[str, Any] | str:
    node = shutil.which("node")
    if node is None:
        return "node is not installed"
    book_ = OLD_BOOK.model_copy(update={"tour": t})
    scripts = {
        who: _raw(who, tour_serve.tour_lines(book_, who, WORDS)["scenes"], "tour")  # type: ignore[index]
        for who in ("owner", "guest")
    }
    scripts["old"] = _raw(
        "owner", [s.model_dump(mode="json") for s in OLD_BOOK.show.scenes], "show"
    )
    files = [str(STATIC / n) for n in ("console-book-script.js", "console-book-tour.js")]
    with tempfile.TemporaryDirectory(prefix="r63d-") as tmp:
        spec = Path(tmp) / "spec.json"
        spec.write_text(json.dumps({"files": files, "scripts": scripts}), encoding="utf-8")
        got = subprocess.run(
            [node, "-e", PLAYER_JS, str(spec)], capture_output=True, text=True, timeout=60,
            check=False, cwd=ROOT,
        )  # fmt: skip
    lines = [x for x in got.stdout.splitlines() if x.startswith(MARK)]
    return json.loads(lines[-1][len(MARK) :]) if lines else (got.stderr[-400:] or "no output")


def _player_checks(t: Tour, got: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for who, aud in (("owner", t.owner), ("guest", t.guest)):
        r, beats = got[who], sum(len(s.beats) for s in aud.scenes)
        want = [[s.picture.visual, len(s.picture.facts), s.id] for s in aud.scenes]
        if r["kind"] != "tour" or r["scenes"] != [s.n for s in aud.scenes]:
            out.append(f"the {who}'s player reads scenes {r['scenes']}")
        if (r["qn"], r["cn"], r["q"], r["c"]) != (18, 19, 12, 13):
            out.append(f"the {who}'s Questions and Closing are {r['qn']}, {r['cn']}")
        if r["timeline"] != beats + 1 + len(CLOSING[who]) or r["pictures"] != want:
            out.append(f"the {who}'s timeline or pictures differ ({r['timeline']} lines)")
    o, g = got["owner"], got["guest"]
    if o["stored"] != {"release": "3f2a1c9", "scene": 7} or o["resume"] != o["scene7"]:
        out.append(f"continue keeps {o['stored']} and resumes at {o['resume']}")
    if g["stored"] is not None or g["resume"] != 0 or g["first"] != 0:
        out.append("a guest's place was kept")
    if got["old"]["kind"] != "show" or got["old"]["scenes"] != list(range(1, 12)):
        out.append("an older book's show is not today's 11 scenes")
    return out


async def _player(w: World) -> list[str]:
    t = w.tour()
    got = _player_run(t)
    return [got] if isinstance(got, str) else _player_checks(t, got)


CASES["player"] = _player


# ---- the browser half (opt in: JARVIS_R63_TOUR_BROWSER=1) ---------------------------------------
def browser_cases() -> list[dict[str, Any]]:
    if os.environ.get("JARVIS_R63_TOUR_BROWSER") != "1":
        return []
    import xml.etree.ElementTree as ET  # noqa: PLC0415 - only when the browser half runs

    py = os.environ.get("JARVIS_BROWSER_PYTHON") or sys.executable
    with tempfile.TemporaryDirectory(prefix="r63d-") as tmp:
        report = Path(tmp) / "browser.xml"
        args = [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "browser",
                f"--junitxml={report}", "tests/browser/test_r63_d_tour.py"]  # fmt: skip
        env = {**os.environ, "JARVIS_BROWSER_TESTS": "1", "PYTHONPATH": str(ROOT / "src")}
        subprocess.run(args, capture_output=True, text=True, timeout=1800, check=False, cwd=ROOT,
                       env=env)  # fmt: skip
        if not report.is_file():
            return [{"id": f"{PART}:browser", "passed": False, "failures": ["no browser run"]}]
        out = []
        for tc in ET.parse(report).getroot().iter("testcase"):
            bad = [
                x.get("message", "")[:300]
                for x in tc
                if x.tag in ("failure", "error")
                or (x.tag == "skipped" and x.get("type") != "pytest.xfail")
            ]
            out.append(
                {"id": f"{PART}:browser:{tc.get('name')}", "passed": not bad, "failures": bad}
            )
        return out


async def cases() -> list[dict[str, Any]]:
    w = World()
    return [await run_case(name, w) for name in CASES] + browser_cases()


# ---- the controls --------------------------------------------------------------------------------
def _owner_line_in_the_guests(t: Tour) -> Tour:
    guest = [t.owner.scenes[12] if s.n == 13 else s for s in t.guest.scenes]
    return t.model_construct(
        owner=t.owner, guest=t.guest.model_construct(**{**t.guest.__dict__, "scenes": tuple(guest)})
    )


def _no_wardrobe(t: Tour) -> Tour:
    def drop(a: tour_model.AudienceTour) -> tour_model.AudienceTour:
        return a.model_construct(
            **{**a.__dict__, "scenes": tuple(s for s in a.scenes if s.n != 13)}
        )

    return t.model_construct(owner=drop(t.owner), guest=drop(t.guest))


_LINE_TEXT = tour_serve.tour_line_text  # the real one, before any control patches it


def _deaf(book_: Any, line_id: str, audience: str, words: Any = None) -> str | None:
    """The control: the owner's tour read for whoever asks (the audience ignored)."""
    return _LINE_TEXT(book_, line_id, "owner", words)


def _ungrouped_t12() -> TourScript:
    doc = json.loads(gen_tour.SCRIPT_FILE.read_bytes())
    for f in doc["scenes"][11]["picture"]["facts"]:
        f["group"] = ""
    return TourScript.model_validate(doc)


def _fast() -> AbstractContextManager[Any]:
    return mock.patch.object(tour_model, "PACE_WPM", 290)


def _deaf_patch() -> AbstractContextManager[Any]:
    return mock.patch.object(tour_serve, "tour_line_text", _deaf)


CONTROLS: tuple[tuple[str, str, Callable[[], World]], ...] = (
    ("T13's owner line in a guest's tour", "guest_no_rupee",
     lambda: World(tweak=_owner_line_in_the_guests)),
    ("tour_line_text ignoring the audience", "guest_speak_404", lambda: World(patch=_deaf_patch)),
    ("Wardrobe & Try-on dropped (row 380)", "seven", lambda: World(tweak=_no_wardrobe)),
    ("the pace at 290 words a minute", "bands", lambda: World(patch=_fast)),
    ("T12's picture facts without a group", "pictures", lambda: World(script=_ungrouped_t12())),
)  # fmt: skip


async def control() -> dict[str, Any]:
    turned = []
    for _, case, make in CONTROLS:
        got = await run_case(case, make())
        turned.append((case, not got["passed"]))
    return {
        "name": "; ".join(name for name, _, _ in CONTROLS),
        "suite_failed": all(red for _, red in turned),
        "failed_cases": [f"{PART}:{case}" for case, red in turned if red],
    }
