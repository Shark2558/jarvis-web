# evals/r13_1/console.py
"""R13.1 eval, Part D (`console`, BUILT): the console and phone of Try-on BY BEHAVIOUR
(docs/plans/r13-1-try-on.md "Tests and evals", BRIEF-D section 4). Part D's REAL modules
(console-tryon*.js) run in Node over a small DOM (tests/fixtures/r13_1/d_dom.mjs, as R13's phone
part did) against D's fake server (tests/r131_fakes_d.py over I0's) over HTTP, with the
contract-keeping fake engine (tests/fixtures/r13_1/d_engine.mjs) in place of B's file. No
browser is needed, so CI's plain pytest (tests/test_r131_seams.py runs this runner) can run it:

- row 388: the reply's `tryon` card opens by itself, dressed in exactly its pieces (by ids, a
  private slot covered); a reply without the card draws and asks for nothing; with no WebGL2 the
  card is the checklist of the same pieces;
- AVT-15: with no WebGL2, a lost context, a file that fails its check, a 10 s first render and
  I0's engine stub that throws, the checklist shows each piece's readiness and image card,
  "Change" swaps a piece and "Wearing it" confirms first, then R13's `wear_log`;
- AVT-06 the watch swap and its thumbnail; AVT-09 the laundry jacket a draft the server refuses,
  and undo; AVT-11 one show() with two figures and both lists' readiness; AVT-14 the caption's
  fixed words passed to snapshot(); See it on me: "yes" refused, the rupees shown, Cancel sends
  NOTHING, then exactly PictureIn's five fields.

Negative control (BRIEF-D section 4): I0's engine stub that throws, with the checklist hook
removed (`toList` no longer draws the list): AVT-15 must fail. The rows' own controls (the plan's
M8 table) that are D's: AVT-06 the slot's thumbnail stays W1's after the swap; AVT-11 the second
figure's readiness words dropped; row 388 the card left out of the reply. A control runs on a
changed COPY of D's file: the code on disk is never touched.

The look itself (44 px targets, 1280 x 800 and 360 x 800 by night and day, Try-on off laid out
as R13's) needs a real browser: those are the browser tests (tests/browser/test_r131_d_*.py, CI's
browser job). With JARVIS_R131_CONSOLE_BROWSER=1 and a Python with Playwright (this one or
$JARVIS_BROWSER_PYTHON), this part also runs them, by name, as cases. No Google call; nothing is
spent.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from r131_fakes import T, jpeg  # noqa: E402
from r131_fakes_d import CARD, PLAN, WATCH2_PHOTO, WATCH_PHOTO, serve_d  # noqa: E402

from jarvis.wardrobe.tryon.model import COVERED, GENERATED  # noqa: E402

PART = "console"
BUILT = True
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
FIXTURES = ROOT / "tests" / "fixtures" / "r13_1"
DOM = FIXTURES / "d_dom.mjs"
TOKEN = "browser-test-token-not-a-secret"  # the browser tests' own made-up token
MARK = "R131D-DOM "
D_FILES = (
    "console-tryon.js", "console-tryon-list.js", "console-tryon-me.js", "console-tryon-photo.js",
    "console-tryon-card.js",
)  # fmt: skip
# I0's engine stub as it was at I0: B's engine replaces the file at I1, and this case stays
I0_STUB = "\n".join(
    (
        "const NOT_BUILT = 'The 3D view is not built yet.';",
        "const mount = () => { throw new Error(NOT_BUILT); };",
        "const engine = Object.freeze({ supported: () => true, mount });",
        "window.JarvisTryOn3D = engine;",
        "export { mount };",
        "export const supported = engine.supported;",
        "export default engine;",
    )
)
CAPTION = [
    "Tue 17 Nov 2026 · 10:00",
    "Navy shirt · Charcoal trousers · Charcoal blazer",
    "Brown dress shoe · Black belt · Grey watch",
    "Base layer (covered)",
]
Case = tuple[str, str]  # (scenario, how)
CASES: tuple[Case, ...] = (
    ("row388", ""), ("row388_none", ""), ("row388_nogl", "no-webgl2"),
    *(("avt15", how) for how in ("no-webgl2", "lost", "asset", "timeout", "stub")),
    ("avt06", ""), ("avt09", ""), ("avt11", ""), ("avt14", ""), ("seeme", ""),
)  # fmt: skip
NAMES = {
    "row388": "row388_asking_what_to_wear_opens_the_card_dressed_in_the_chosen_look",
    "row388_none": "row388_a_reply_without_the_card_draws_nothing",
    "row388_nogl": "row388_with_no_webgl_the_card_shows_the_same_pieces_as_a_checklist",
    "avt15": "avt15_a_failed_render_leaves_a_checklist_that_can_change_a_piece_and_confirm",
    "avt06": "avt06_swap_the_watch_changes_its_wrist_piece_and_its_thumbnail",
    "avt09": "avt09_swap_undo_a_jacket_in_the_laundry_is_a_draft_the_server_refuses",
    "avt11": "avt11_lists_a_formal_and_a_festive_look_with_both_lists_and_their_readiness",
    "avt14": "avt14_share_the_caption_has_fixed_words_and_never_a_private_label_or_id",
    "seeme": "avt12_card_his_yes_the_rupees_and_cancel_sends_nothing",
}


def case_id(case: Case) -> str:
    scenario, how = case
    return f"{PART}:{NAMES[scenario]}" + (f"[{how}]" if scenario == "avt15" else "")


# ---- the controls: a changed COPY of D's own file ----------------------------------------------
CHECKLIST_HOOK = (
    "function toList(v, why) { dispose(v); v.mode = 'list'; v.why = why || 'list'; draw(v); }"
)
THUMB_LINE = "const ids = s.piece && typeof o.photosOf === 'function' ? o.photosOf(s.piece) : [];"
COMPARED = "v.choosing = null; v.comparing = true;"
SWAPS: dict[str, tuple[str, str, str]] = {  # control -> (file, what it was, what it becomes)
    "avt15": ("console-tryon.js", CHECKLIST_HOOK, "function toList(v, why) { dispose(v); }"),
    "avt06": (
        "console-tryon-list.js",
        THUMB_LINE,
        "const ids = STALE[s.slot] || (STALE[s.slot] = s.piece && typeof o.photosOf === "
        "'function' ? o.photosOf(s.piece) : []);",
    ),
    "avt11": (
        "console-tryon.js",
        COMPARED,
        "v.second = Object.assign({}, v.second, { slots: (v.second.slots || []).map((s) => "
        "Object.assign({}, s, { readiness: '' })) }); " + COMPARED,
    ),
}
CONTROLS: dict[str, Case] = {  # control -> the case it must turn red
    "avt15": ("avt15", "stub"),
    "avt06": ("avt06", ""),
    "avt11": ("avt11", ""),
    "row388": ("row388", ""),  # the card left out of the reply (d_dom.mjs passes the reply bare)
}
MUST_FAIL: dict[str, set[str]] = {  # control -> its case's OWN checks it must turn red (L10)
    "avt15": {"checklist", "why"},
    "avt06": {"thumbnail_w2"},
    "avt11": {"each_readiness"},
    "row388": {"opened", "pieces", "covered"},
}


def turned_red(control: str, result: dict[str, Any]) -> bool:
    """Its own checks failed, and the run itself did not crash (a crash, or Node missing, proves
    nothing about the row: review D-1 L10)."""
    return not result.get("error") and MUST_FAIL[control] <= set(result.get("failures", ()))


def modules(into: Path, control: str | None, how: str) -> None:
    """D's modules (one changed under a control) and the engine the case runs against."""
    for name in D_FILES:
        text = (STATIC / name).read_text(encoding="utf-8")
        if control in SWAPS and SWAPS[control][0] == name:
            _, was, now = SWAPS[control]
            if text.count(was) != 1:
                raise AssertionError(f"control {control}: its line moved in {name}")
            text = ("const STALE = {};\n" if control == "avt06" else "") + text.replace(was, now)
        (into / name).write_text(text, encoding="utf-8")
    engine = I0_STUB if how == "stub" else (FIXTURES / "d_engine.mjs").read_text(encoding="utf-8")
    (into / "console-tryon-3d.js").write_text(engine, encoding="utf-8")


# ---- one case: a fresh fake server state, the modules, Node -----------------------------------
def _http(
    url: str, path: str, body: Any = None, *, raw: bytes | None = None, method: str = ""
) -> Any:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(
        url + path, data=data, method=method or ("POST" if data else "GET")
    )
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "image/jpeg" if raw is not None else "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"null")


def fresh(url: str, scenario: str) -> None:
    """The figure, no saved looks, no photo, YES, garments or pictures; See it on me's own needs."""
    _http(url, "/v1/test/r131-d/reset", {"figure": True})
    _http(url, "/v1/seeme/photo", method="DELETE")
    for g in _http(url, "/v1/seeme/garments")["garments"]:
        _http(url, f"/v1/seeme/garments/{g['id']}", method="DELETE")
    for p in _http(url, "/v1/seeme")["pictures"]:
        _http(url, f"/v1/seeme/pictures/{p['id']}", method="DELETE")
    if scenario == "seeme":  # his photo kept (checked on an earlier day) and one new garment
        _http(url, "/v1/seeme/photo", raw=jpeg(600, 1200))
        _http(url, "/v1/seeme/garments?type=shirt&colour=navy", raw=jpeg(512, 512))


def _spec(url: str, case: Case, control: str | None, folder: Path) -> dict[str, Any]:
    t = {"striped": T.striped, "kurta": T.kurta, "blazer": T.blazer, "watch2": T.watch2,
         "rain_jacket": T.rain_jacket}  # fmt: skip
    return {
        "dir": str(folder), "base": url, "token": TOKEN, "scenario": case[0], "how": case[1],
        "control": control, "card": CARD.model_dump(mode="json"), "plan": PLAN, "t": t,
        "covered": COVERED, "caption": CAPTION, "generated": GENERATED,
        "photos": {"w1": WATCH_PHOTO, "w2": WATCH2_PHOTO},
    }  # fmt: skip


def run_case(url: str, case: Case, control: str | None = None) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        lost = "node is not installed"
        return {"id": case_id(case), "passed": False, "failures": [lost], "error": lost}
    fresh(url, case[0])
    with tempfile.TemporaryDirectory(prefix="r131d-") as tmp:
        modules(Path(tmp), control, case[1])
        spec = json.dumps(_spec(url, case, control, Path(tmp)))
        got = subprocess.run(
            [node, str(DOM), spec], capture_output=True, text=True, timeout=120, check=False,
            cwd=ROOT, env={**os.environ, "TZ": "Asia/Kolkata"},
        )  # fmt: skip
    lines = [x for x in got.stdout.splitlines() if x.startswith(MARK)]
    if not lines:
        why = got.stderr[-600:] or "no out"
        return {"id": case_id(case), "passed": False, "failures": [why], "error": why}
    out = json.loads(lines[-1][len(MARK) :])
    failures = [k for k, ok in out["checks"].items() if ok is not True]
    if "error" in out:
        failures.append(out["error"])
    error = str(out.get("error") or "")
    return {"id": case_id(case), "passed": not failures, "failures": failures, "error": error}


def _all(runs: list[tuple[Case, str | None]]) -> list[dict[str, Any]]:
    url, stop = serve_d(TOKEN)
    try:
        return [run_case(url, case, control) for case, control in runs]
    finally:
        stop()


# ---- the look in a real browser (opt in) --------------------------------------------------------
BROWSER_CASES = (
    "test_r131_d_look.py", "test_r131_d_card.py::test_row388_a_spoken_reply_opens_the_same_card",
)  # fmt: skip


def browser_cases() -> list[dict[str, Any]]:
    """With JARVIS_R131_CONSOLE_BROWSER=1: the look's browser tests, each a case by its name."""
    if os.environ.get("JARVIS_R131_CONSOLE_BROWSER") != "1":
        return []
    py = os.environ.get("JARVIS_BROWSER_PYTHON") or sys.executable
    with tempfile.TemporaryDirectory(prefix="r131d-") as tmp:
        report = Path(tmp) / "browser.xml"
        args = [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "browser",
                f"--junitxml={report}", *(f"tests/browser/{c}" for c in BROWSER_CASES)]  # fmt: skip
        env = {**os.environ, "JARVIS_BROWSER_TESTS": "1", "PYTHONPATH": str(ROOT / "src")}
        subprocess.run(args, capture_output=True, text=True, timeout=1800, check=False, cwd=ROOT,
                       env=env)  # fmt: skip
        return _junit(report)


def _junit(report: Path) -> list[dict[str, Any]]:
    import xml.etree.ElementTree as ET  # noqa: PLC0415  (only when the browser half runs)

    if not report.is_file():
        return [{"id": f"{PART}:browser", "passed": False, "failures": ["the browser run failed"]}]
    out = []
    for tc in ET.parse(report).getroot().iter("testcase"):
        bad = [x.get("message", "")[:300] for x in tc if x.tag in ("failure", "error", "skipped")]
        out.append({"id": f"{PART}:browser:{tc.get('name')}", "passed": not bad, "failures": bad})
    return out


async def cases() -> list[dict[str, Any]]:
    got = await asyncio.to_thread(_all, [(c, None) for c in CASES])
    return got + await asyncio.to_thread(browser_cases)


async def control() -> dict[str, Any]:
    runs = [(case, name) for name, case in CONTROLS.items()]
    got = await asyncio.to_thread(_all, runs)
    turned = {name: turned_red(name, r) for (_, name), r in zip(runs, got, strict=True)}
    return {
        "name": "D: I0's engine stub with the checklist hook removed (AVT-15); the rows' own: "
        "AVT-06 the thumbnail stays W1's, AVT-11 the second list's readiness dropped, row 388 "
        "the card left out of the reply",
        "suite_failed": all(turned.values()),
        "turned_red": turned,
        "failed_cases": [
            f"{name}: {r['id']} {r['failures'][:3]}"
            for (_, name), r in zip(runs, got, strict=True)
            if not r["passed"]
        ],
    }
