# evals/r11_1/look.py
"""R11.1 eval, Part D (`look`): People, pictures and Vitals (plan D16 to D19, D21-D). Mock only:
the real tool, guard, gateway, people research, Vitals board and GitHub client on the fakes of
tests/r11_1_fakes_d.py (drawn pictures, eyes that read their pixels, a recorded search vendor).

    O8   console-people.js run in Node on a small DOM: each "Open next" press follows exactly ONE
         card's own link and window.open is never called (by behaviour, not by its spelling)
    O9   a product, a landmark, a label and a logo are researched with sources; the cases about
         PEOPLE (never named from a face, on the tool's path and on the main brain's) are in
         evals/r11_1/look_names.py
    R4   every row of tests/test_people_gate_eval.py still passes; people/gate.py is unchanged
    O10  each failing part of the home laptop has its own row text and fix steps; no device name
    O11  a connected token with no stored facts: ONE /rate_limit read in 6 hours, then its limits

Five negative controls; each must fail its own cases (a suite that cannot fail proves nothing):
    guard_off        the picture guard disabled   -> a name gets through, a person is searched
    turn_guard_off   the turn guard lets all pass -> the main brain researches a face's name
    fault_map_empty  vitals.words.HOME_FAULTS {}  -> the home row is vague again
    six_hours_off    FACTS_EVERY_S = 0            -> GitHub is asked on every refresh
    open_all_back    R4's "Open all" put back     -> one press opens every profile, by window.open
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

from r11_1_fakes_d import UID, GithubRig, HomeRig, picture, run_people_dom
from test_people_gate_eval import CASES as GATE_CASES
from test_people_gate_eval import Case as GateCase
from test_people_gate_eval import run_case as run_gate_case

from jarvis.core import prompts
from jarvis.integrations import github as gh
from jarvis.picture.eyes import NO_AI, CantLook
from jarvis.picture.guard import NO_IDENTIFY
from jarvis.vitals import words


def _sibling(name: str) -> ModuleType:
    """A module beside this one, loaded once by path (the runner and the tests load this file by
    path under their own names, so a plain import would not find it)."""
    full = f"r11_1_{name}"
    if full not in sys.modules:
        spec = importlib.util.spec_from_file_location(full, Path(__file__).with_name(f"{name}.py"))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[full] = module
        spec.loader.exec_module(module)
    return sys.modules[full]


names = _sibling("look_names")

PART = "look"
BUILT = True
ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
GATE_SHA256 = "b3ff32f47cbdf9827b5e652d6830b17a9642327ec7b93429122855672c945f2d"
SESSION = "sess_1"
CONTROLS = ("guard_off", "turn_guard_off", "fault_map_empty", "six_hours_off", "open_all_back")
OPEN_NEXT = "if (next) next.a.click();"
OPEN_ALL = "S.links.forEach((l) => window.open(l.url, '_blank', 'noopener,noreferrer'));"  # R4's
_active: set[str] = names.ACTIVE  # the negative controls applied to this run (none: the real one)
Case = Callable[[], Awaitable[list[str]]]
LINKS = [
    "https://www.linkedin.com/in/example-person-0001",
    "https://en.wikipedia.org/wiki/Lekha_Examplekar",
    "https://x.com/example_person_0001",
]
DOSSIER: dict[str, Any] = {
    "name": "Lekha Examplekar",
    "profiles": [{"platform": p, "url": u, "title": "A profile"} for p, u in
                 zip(("linkedin", "wikipedia", "x"), LINKS, strict=True)],
    "findings": [], "summary": "A made-up minister.", "spoken": "", "note": "",
    "ambiguous": False, "no_ai": False,
}  # fmt: skip


def _flat(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=lambda o: getattr(o, "__dict__", str(o)))


# ---- O8: profile cards, by what a press does ----------------------------------------------------
async def profile_cards() -> list[str]:
    """console-people.js on a small DOM (tests/fixtures/r11_1/d_dom.js), "Open next" pressed once
    per card: each press must follow one card's own link, in order, and never call window.open.
    The `open_all_back` control puts R4's line back; it fails by what it does."""
    js = (STATIC / "console-people.js").read_text(encoding="utf-8")
    if OPEN_NEXT not in js:
        return ['"Open next" is not the one-link press this case changes for its control']
    if "open_all_back" in _active:
        js = js.replace(OPEN_NEXT, OPEN_ALL)
    got = run_people_dom(js, DOSSIER, presses=len(LINKS))
    bad = []
    if any((a["target"], a["rel"]) != ("_blank", "noopener noreferrer") for a in got["links"]):
        bad.append("a profile card has no real link of its own that opens without its opener")
    if got["opens"]:
        bad.append(f"window.open was called {got['opens']} times")
    if [p["followed"] for p in got["presses"]] != [[u] for u in LINKS]:
        bad.append(f'"Open next" does not open exactly one card a press: {got["presses"]}')
    return bad


# ---- O9: a thing is researched -----------------------------------------------------------------
def _thing(kind: str, name: str, *lines: str) -> Case:
    async def case() -> list[str]:
        rig = names.rig()
        pic = picture(*lines, blocks=[((60, 60, 220, 170), (200, 40, 40))])
        rig.eyes.knows(pic, scene="An object on a table.", subjects=[(kind, name)])
        rig.turn.attach(SESSION, pic)
        out = (await rig.research()).result
        bad = []
        if rig.vendor.queries != [name]:
            bad.append(f"searched {rig.vendor.queries}, wanted [{name!r}]")
        if len(out.get("results", [])) < 2 or "[n]" not in out.get("note", ""):
            bad.append("no sources to cite")
        if out.get("person") or "say" in out:
            bad.append("a thing was treated as a person")
        return bad

    return case


# ---- R4: a typed name still meets the unchanged gate -------------------------------------------
def _fresh(case: GateCase) -> GateCase:
    """The same row with a model nobody has called yet (the unit tests share these rows)."""
    model = None if case.model is None else replace(case.model, calls=[], records=[])
    return replace(case, model=model)


async def typed_names_meet_the_gate() -> list[str]:
    bad = []
    text = (ROOT / "src" / "jarvis" / "people" / "gate.py").read_text(encoding="utf-8")
    if hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest() != GATE_SHA256:
        bad.append("people/gate.py is not the file R4 shipped")
    for case in map(_fresh, GATE_CASES):
        try:
            await run_gate_case(case)
        except AssertionError as exc:
            bad.append(f"gate eval row {case.id}: {exc}")
    return bad


# ---- the persona's rule is there, and it says why when it can't look ---------------------------
async def persona_rule() -> list[str]:
    rule = " ".join(prompts.build_system_prompt(honorific="Sir").split())
    wanted = (
        "Never identify a person from a picture",
        f'say once: "{NO_IDENTIFY}"',
        "never search the web with a description of the person",
        "A name may come only from words visible in the picture",
    )
    return [f"the persona lacks: {w}" for w in wanted if w not in rule]


async def says_why_in_no_ai_mode() -> list[str]:
    rig, pic = names.rig(), picture(person=True)
    rig.turn.attach(SESSION, pic)
    rig.eyes.cant = CantLook("no_ai", NO_AI)
    out = (await rig.research()).result
    bad = [] if out == {"status": "no_ai", "message": NO_AI, "spoken": NO_AI} else ["wrong words"]
    if rig.vendor.queries or rig.docs.sets or pic.b64()[:40] in names.said(rig, out):
        bad.append("something was searched, stored or kept")
    return bad


# ---- O10: the home row names the part ----------------------------------------------------------
WATCHER, MESSENGER = "the camera watcher (Frigate)", "the camera's messenger (MQTT)"
KIT, FRIGATE, MOSQUITTO = "start-home.ps1", "jarvis-home-frigate-1", "jarvis-home-mosquitto-1"


def _home(wanted: tuple[str, ...], fix: tuple[str, ...], **down: bool) -> Case:
    async def case() -> list[str]:
        home = HomeRig()
        await home.link()
        faults = {} if "fault_map_empty" in _active else words.HOME_FAULTS
        with patch.object(words, "HOME_FAULTS", faults):
            parts = {"frigate": True, "mqtt": True, **down}
            await home.beat(**parts, cameras=[{"id": "gate_cam_x9", "online": False}])
            row = await home.row()
            board = _flat((await home.rig.svc.board(UID)).to_json())
        bad = [f"the row does not say: {w}" for w in wanted if w not in row.reason]
        bad += [f"the fix steps lack: {w}" for w in fix if w not in row.fix]
        if row.status != "amber" or "gate_cam_x9" in board:
            bad.append("wrong status, or a device's name reached the board")
        return bad

    return case


# ---- O11: the GitHub token is read once --------------------------------------------------------
async def github_read_once() -> list[str]:
    every = 0.0 if "six_hours_off" in _active else gh.FACTS_EVERY_S
    with patch.object(gh, "FACTS_EVERY_S", every):
        rig = GithubRig()
        await rig.connected_without_facts()
        rig.answers(503)  # GitHub is down for the first read
        first = await rig.row()
        for _ in range(5):  # five more refreshes inside the six hours, each after a restart
            rig.clock.advance(hours=1)
            rig.restart()
            await rig.row()
        bad = [] if rig.api.reads() == 1 else [f"{rig.api.reads()} reads in 6 hours, wanted 1"]
        if "hasn't been used" in first.reason + first.provider.note:
            bad.append('the row still says "hasn\'t been used"')
        rig.clock.advance(hours=1, seconds=5)  # the six hours are over
        rig.answers(used=40)
        after = await rig.row()
    if (after.status, after.provider.used, after.provider.limit) != ("ok", 40, 5000):
        bad.append("the limits are not shown after the next read")
    return bad


async def github_refused() -> list[str]:
    rig = GithubRig()
    await rig.connected_without_facts()
    rig.answers(401)
    row = await rig.row()
    ok = (row.status, row.reason) == ("red", "the token was refused") and rig.api.reads() == 1
    return [] if ok else ["a refused token is not shown as refused after one read"]


CASES: dict[str, Case] = {
    "profile_cards_open_one_tab_a_click": profile_cards,
    "product_researched": _thing("product", "Parle-G biscuit packet", "PARLE-G"),
    "landmark_researched": _thing("landmark", "Charminar monument"),
    "label_researched": _thing("label", "Examplekar Estate tea label", "EXAMPLEKAR ESTATE"),
    "logo_researched": _thing("logo", "Examplekar Motors logo", "EXAMPLEKAR MOTORS"),
    **names.CASES,
    "typed_names_meet_the_unchanged_gate": typed_names_meet_the_gate,
    "persona_rule_present": persona_rule,
    "no_ai_mode_says_why": says_why_in_no_ai_mode,
    "home_camera_watcher": _home(
        (f"{WATCHER} is not answering",), (KIT, f"docker restart {FRIGATE}"), frigate=False
    ),
    "home_messenger": _home(
        (f"{MESSENGER} is not connected", "burglar alerts can't arrive"),
        (KIT, MOSQUITTO),
        mqtt=False,
    ),
    "home_both_parts": _home(
        (WATCHER, MESSENGER), (KIT, FRIGATE, MOSQUITTO), frigate=False, mqtt=False
    ),
    "github_one_read_in_six_hours": github_read_once,
    "github_refused_token": github_refused,
}
EXPECTED = {  # what each control must break
    **names.EXPECTED,
    "fault_map_empty": {"home_camera_watcher", "home_messenger", "home_both_parts"},
    "six_hours_off": {"github_one_read_in_six_hours"},
    "open_all_back": {"profile_cards_open_one_tab_a_click"},
}


async def _run() -> list[dict[str, Any]]:
    out, before = [], logging.root.manager.disable
    logging.disable(logging.WARNING)  # the parts under test log every refusal; here cases speak
    try:
        for name, case in CASES.items():
            try:
                failures = await case()
            except Exception as exc:  # noqa: BLE001 - a crash is a failed case, with its class
                failures = [f"crashed: {type(exc).__name__}: {exc}"]
            out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    finally:
        logging.disable(before)
    return out


async def cases() -> list[dict[str, Any]]:
    _active.clear()
    results = await _run()
    print(f"{PART}: {len(results)} cases; negative controls: {', '.join(CONTROLS)}")
    return results


async def control() -> dict[str, Any]:
    """Each control on its own: the suite fails only when EVERY one broke all it must break."""
    failed: dict[str, list[str]] = {}
    for name in CONTROLS:
        _active.clear()
        _active.add(name)
        try:
            got = await _run()
        finally:
            _active.clear()
        failed[name] = [r["id"] for r in got if not r["passed"]]
    caught = all({f"{PART}:{c}" for c in EXPECTED[name]} <= set(failed[name]) for name in CONTROLS)
    return {"name": " + ".join(CONTROLS), "suite_failed": caught, "failed_cases": failed}


__all__ = ["BUILT", "CASES", "CONTROLS", "EXPECTED", "PART", "cases", "control"]
