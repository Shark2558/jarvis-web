# evals/r13_1/console.py
"""R13.1 eval, Part D (`console`): the console and phone of Try-on in a real Chromium
(docs/plans/r13-1-try-on.md "Tests and evals", BRIEF-D section 4), on D's fake server
(tests/r131_fakes_d.py over I0's) and a fake engine that keeps B's contract
(tests/fixtures/r13_1/d_engine.mjs), with the page clock pinned. Each case IS the named browser
test of the same name in tests/browser/test_r131_d_*.py, run here as a function:

- row 388: the card opens under a typed and a spoken "what should I wear?" with no tap, dressed
  in exactly the card's pieces (a private slot covered); with no WebGL2 the checklist shows the
  same pieces; a reply without the card draws nothing; on a phone too;
- AVT-15: with no WebGL2, a lost context, a file that fails its check, a 10 s first render and
  I0's engine stub that throws, the checklist changes a piece and "Wearing it" confirms through
  R13's tools;
- every row's UI half (AVT-02 ... AVT-14, OPS-05, D22): the controls, the form, the cards, the
  swap and its thumbnail, undo and the draft, the toggles, compare with both lists' readiness, the
  share caption passed to snapshot(), his YES and the rupee confirm (Cancel sends nothing), the
  new garment's type and colour from lists and the face refusal, the Privacy delete;
- the look: 44 px targets, the stage at 1280 x 800 and 360 x 800 by night and day, and with
  Try-on off the Wardrobe tab laid out as R13's.

Negative control (the part's own, BRIEF-D section 4): I0's engine stub that throws, with the
checklist hook removed (`toList` no longer draws the list): AVT-15's case must fail. And the rows'
own controls (the plan's M8 table) that are D's, each a case of the control run: AVT-06 the
slot's thumbnail stays W1's after the swap; AVT-11 the second figure's readiness words dropped;
row 388 the card left out of the reply. A control is applied by serving a changed copy of D's own
file (or the reply without its card) to the page: the code on disk is never touched.

The browser needs Playwright and Chromium: the cases run in a child process with this Python when
it has Playwright, else with $JARVIS_BROWSER_PYTHON. Without either the part FAILS and says why
(a browser suite that didn't run never reads as green). No real Google call; nothing is spent.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

PART = "console"
BUILT = True
ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
TOKEN = "browser-test-token-not-a-secret"  # the browser tests' own made-up token
MARK = "R131D-CONSOLE-EVAL "
CHILD_TIMEOUT_S = 1800
AVT15 = "test_avt15_a_failed_render_leaves_a_checklist_that_can_change_a_piece_and_confirm"
STAGE_SIZE = "test_the_stage_is_480px_on_a_laptop_and_56_percent_on_a_phone_by_night_and_day"
OPS05 = "test_ops05_button_deletes_through_privacy_empties_the_viewer_and_keeps_the_catalog"
AVT12 = "test_avt12_card_the_picture_is_a_labelled_2d_preview_of_a_new_garment_with_his_pieces"
Case = tuple[str, str, dict[str, Any]]  # (test module, test function, its parameters)
TMP: dict[str, Any] = {"tmp_path": None}  # a fresh folder for the drawn pictures it saves

CASES: tuple[Case, ...] = (
    ("card", "test_row388_asking_what_to_wear_opens_the_card_dressed_in_the_chosen_look", {}),
    ("card", "test_row388_a_spoken_reply_opens_the_same_card", {}),
    ("card", "test_row388_a_reply_without_the_card_draws_nothing", {}),
    ("card", "test_row388_with_no_webgl_the_card_shows_the_same_pieces_as_a_checklist", {}),
    ("look", "test_row388_on_a_phone_the_card_opens_by_itself_under_the_reply", {}),
    *(("card", AVT15, {"how": how}) for how in ("no-webgl2", "lost", "asset", "timeout", "stub")),
    ("section", "test_the_section_opens_dressed_in_the_first_plans_look_by_itself", {}),
    ("section", "test_avt02_controls_front_side_back_turn_closer_and_zoom", {}),
    ("section", "test_avt03_form_correcting_height_redraws_and_keeps_every_piece", {}),
    ("section", "test_avt04_cards_a_kurta_shows_front_and_back_and_a_shirt_asks_for_its_back", {}),
    ("section", "test_avt05_card_a_patterned_shirt_is_approximate_and_can_be_its_photo_only", {}),
    ("section", "test_avt06_swap_the_watch_changes_its_wrist_piece_and_its_thumbnail", {}),
    ("section", "test_avt08_front_to_back_keeps_the_pieces_the_styling_and_the_figure", {}),
    ("section", "test_avt09_swap_undo_a_jacket_in_the_laundry_is_a_draft_the_server_refuses", {}),
    ("section", "test_avt10_toggles_close_the_jacket_untuck_and_a_kurta_says_it_is_worn_out", {}),
    (
        "section",
        "test_avt11_lists_a_formal_and_a_festive_look_with_both_lists_and_their_readiness",
        {},
    ),
    ("section", "test_avt14_share_the_caption_has_fixed_words_and_never_a_private_label_or_id", {}),
    ("section", OPS05, {}),
    ("seeme", AVT12, TMP),
    (
        "seeme",
        "test_avt12_card_lists_his_pieces_sent_and_not_in_the_picture_with_their_thumbnails",
        {},
    ),
    ("seeme", "test_d22_garment_type_and_colour_come_from_lists_and_a_face_is_refused", TMP),
    (
        "seeme",
        "test_d22_garment_a_shared_picture_waits_for_his_words_and_that_press_sends_nothing",
        {},
    ),
    ("seeme", "test_seeme_his_photo_one_person_passes_and_two_are_refused", TMP),
    ("stage", "test_his_checklist_names_a_private_basic_only_behind_show_private_basics", {}),
    *(
        ("look", "test_every_target_is_44px_in_try_it_on_and_in_the_card", {"size": s})
        for s in ("laptop", "phone")
    ),
    *(
        ("look", STAGE_SIZE, {"size": size, "surface": surface})
        for size in ("laptop", "phone")
        for surface in ("night", "day")
    ),
    ("look", "test_with_try_on_off_the_wardrobe_tab_is_laid_out_as_r13s", {}),
)


def key_of(case: Case) -> str:
    mod, name, kw = case
    return f"{mod}:{name}" + "".join(f":{v}" for k, v in kw.items() if k != "tmp_path")


def case_id(case: Case) -> str:
    _, name, kw = case
    params = ",".join(str(v) for k, v in kw.items() if k != "tmp_path")
    return f"{PART}:{name.removeprefix('test_')}" + (f"[{params}]" if params else "")


# ---- the controls: a changed copy of D's own file served to the page (never written to disk) --
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
CONTROLS: dict[str, tuple[str, ...]] = {  # control -> the cases it must turn red
    "avt15": (f"card:{AVT15}:stub",),
    "avt06": ("section:test_avt06_swap_the_watch_changes_its_wrist_piece_and_its_thumbnail",),
    "avt11": (
        "section:test_avt11_lists_a_formal_and_a_festive_look_with_both_lists_and_their_readiness",
    ),
    "row388": ("card:test_row388_asking_what_to_wear_opens_the_card_dressed_in_the_chosen_look",),
}


def changed(control: str) -> tuple[str, str]:
    """The file and the text the page gets under that control (the swap must apply)."""
    name, was, now = SWAPS[control]
    text = (STATIC / name).read_text(encoding="utf-8")
    if text.count(was) != 1:
        raise AssertionError(f"control {control}: its line moved in {name}")
    if control == "avt06":
        text = "const STALE = {};\n" + text
    return name, text.replace(was, now)


def _route_control(page: Any, control: str) -> None:
    if control == "row388":

        def no_card(route: Any) -> None:  # the reply as it would be without the card
            r = route.fetch()
            route.fulfill(response=r, json={**r.json(), "cards": []})

        page.route("**/v1/chat", no_card)
        return
    name, text = changed(control)
    page.route(f"**/static/{name}*", lambda r: r.fulfill(body=text, content_type="text/javascript"))


# ---- the child: Playwright, D's fake server, each case as its test function --------------------
def _modules() -> dict[str, Any]:
    for p in (ROOT / "tests" / "browser", ROOT / "tests", ROOT / "src"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import test_r131_d_card as card  # noqa: PLC0415  (the test modules ARE the cases)
    import test_r131_d_look as look  # noqa: PLC0415
    import test_r131_d_section as section  # noqa: PLC0415
    import test_r131_d_seeme as seeme  # noqa: PLC0415
    import test_r131_d_stage as stage  # noqa: PLC0415

    return {"card": card, "look": look, "section": section, "seeme": seeme, "stage": stage}


def _with_control(mods: dict[str, Any], control: str | None) -> None:
    if control is None:
        return
    page_cls = mods["card"].Page
    plain = page_cls.__init__

    def init(self: Any, *a: Any, **kw: Any) -> None:
        plain(self, *a, **kw)
        _route_control(self.page, control)

    page_cls.__init__ = init  # every module's Page is this one class


def _one(fn: Callable[..., None], kw: dict[str, Any], browser: Any, url: str) -> list[str]:
    args = dict(kw)
    if "tmp_path" in args:
        args["tmp_path"] = Path(tempfile.mkdtemp(prefix="r131d-"))
    try:
        fn(browser=browser, d_url=url, token=TOKEN, **args)
    except BaseException as e:  # noqa: BLE001  (an assertion, a timeout or a crash: its words)
        words = str(e).splitlines()[0][:300] if str(e) else ""
        at = traceback.extract_tb(e.__traceback__)[-1]  # which check of the test went red
        return [f"{type(e).__name__}: {words} ({Path(at.filename).name}:{at.lineno}: {at.line})"]
    return []


def child(control: str | None, only: tuple[str, ...]) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    from r131_fakes_d import serve_d  # noqa: PLC0415

    mods = _modules()
    _with_control(mods, control)
    url, stop = serve_d(TOKEN)
    out: list[dict[str, Any]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for case in (c for c in CASES if not only or key_of(c) in only):
                failures = _one(getattr(mods[case[0]], case[1]), case[2], browser, url)
                out.append(
                    {
                        "id": case_id(case),
                        "key": key_of(case),
                        "passed": not failures,
                        "failures": failures,
                    }
                )
            browser.close()
    finally:
        stop()
    return out


# ---- the parent: which Python drives the browser ------------------------------------------------
def browser_python() -> str | None:
    if importlib.util.find_spec("playwright") is not None:
        return sys.executable
    named = os.environ.get("JARVIS_BROWSER_PYTHON", "")
    return named if named and Path(named).is_file() else None


def _broken(words: str) -> list[dict[str, Any]]:
    return [{"id": f"{PART}:browser", "key": "", "passed": False, "failures": [words]}]


def _spawn(control: str | None, only: tuple[str, ...]) -> list[dict[str, Any]]:
    py = browser_python()
    if py is None:
        return _broken("no Playwright for this Python: set JARVIS_BROWSER_PYTHON to one with it")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests")))}
    args = [py, str(Path(__file__).resolve()), "--child", json.dumps([control, list(only)])]
    try:
        got = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=CHILD_TIMEOUT_S,
            check=False,
            cwd=ROOT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return _broken(f"the browser run took over {CHILD_TIMEOUT_S} s")
    lines = [x for x in got.stdout.splitlines() if x.startswith(MARK)]
    if got.returncode != 0 or not lines:
        return _broken((got.stderr or got.stdout)[-600:])
    results: list[dict[str, Any]] = json.loads(lines[-1][len(MARK) :])
    return results


async def cases() -> list[dict[str, Any]]:
    got = await asyncio.to_thread(_spawn, None, ())
    return [{k: r[k] for k in ("id", "passed", "failures")} for r in got]


async def control() -> dict[str, Any]:
    failed: list[str] = []
    turned: dict[str, bool] = {}
    for name, must in CONTROLS.items():
        got = await asyncio.to_thread(_spawn, name, must)
        red = [r["id"] for r in got if not r["passed"] and r["key"] in must]
        turned[name] = len(red) == len(must)
        failed.extend(f"{name}: {x}" for x in red)
    return {
        "name": "D: the engine stub with the checklist hook removed (AVT-15); the rows' own: "
        "AVT-06 the thumbnail stays W1's, AVT-11 the second list's readiness dropped, row 388 "
        "the card left out of the reply",
        "suite_failed": all(turned.values()),
        "turned_red": turned,
        "failed_cases": failed,
    }


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--child":
    ctl, keys = json.loads(sys.argv[2])
    print(MARK + json.dumps(child(ctl, tuple(keys))), flush=True)
