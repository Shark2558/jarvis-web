# tests/test_r13_d_scan.py -- R13 Part D, Camera -> Wardrobe by BEHAVIOUR (docs/plans/
# r13-wardrobe.md D4.1, D5, D7, D9, D10, OPS-01, LND-01-04, LND-10, INV-05, INV-07, INV-10):
# console-wardrobe-scan.js runs in Node (tests/fixtures/r13/d_dom.js) with a fake camera whose
# frames are drawn scenes, fake vision answers per task, and spies on every request and every call
# of the one picture door.
#   OPS-01  a person or a face on the photo keeps and sends nothing (no photo, fingerprint or tag)
#           while a label read still makes its event; a clean photo then one with a face saves
#           nothing from the second; the check not installed: saving is off, taps still work; the
#           checks and the crop are the SAME canvas; a saved crop is at most 512 px; Stop ends the
#           camera and the label reader and keeps unsent scans
#   D10     a private piece never gets a photo, a fingerprint or a tag; a private-by-default kind
#           asks "Make it private?"
#   D7      candidates come from his saved fingerprints (his tap decides), identical copies are
#           said, a code that is not his label is ignored and never sent; AI tagging only with his
#           setting on and the AI on, its rupees shown before the press
#   LND     "Put in laundry" sends deposits (ids only); Cancel sends nothing; "Not sure which"
#           sends both unverified; "Back clean" sends returns with the place or needs-prep
#   D4.1    an unsent scan waits in memory ("Not sent yet: keep this page open") and goes on
#           "Send now", its `sent` stamped then; before sign-in nothing is asked
#   INV-10  a label's size, fabric and care words are offered unverified; the raw text never leaves
from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from r13_fake_server import fake_state, wardrobe_view
from r13_fakes import PILOT

from jarvis.wardrobe.model import CARE_WORDS, FABRICS, PRIVATE_BY_DEFAULT

ROOT = Path(__file__).resolve().parents[1]
DOM = ROOT / "tests" / "fixtures" / "r13" / "d_dom.js"
SCAN = ROOT / "src" / "jarvis" / "api" / "static" / "console-wardrobe-scan.js"
P = [p.id for p in PILOT]
SHIRT, WHITE, NAVY, VEST1, VEST2, SNEAKER_L, SNEAKER_R = P[0], P[1], P[2], P[8], P[9], P[17], P[18]
PERSON = (
    "This picture shows a person. Lay the piece on a surface or hang it, and take the photo again."
)
NO_CHECK = "Saving a photo is off on this phone: the check for a person or a face is not installed."
SAVE = "Save this photo with the piece (sealed; only you)"
TAG = "Ask the AI to tag this piece (about ₹0.30 at most)"


def _vec(seed: int) -> str:
    return base64.b64encode(
        bytes((seed * 31 + i * 7 + (i % seed if seed else 0)) % 256 for i in range(1280))
    ).decode()


def _view(**settings: Any) -> dict[str, Any]:
    async def build() -> dict[str, Any]:
        store, _ = await fake_state()
        v = wardrobe_view(await store.view("owner-w"), show_private=True).model_dump(mode="json")
        v["labels"] = [
            {"code": "abcdefgh", "number": 1, "piece": NAVY},
            {"code": "qrstuvwx", "number": 2, "piece": VEST1},
        ]
        v["settings"] = {**v["settings"], **settings}
        return v

    return asyncio.run(build())


VIEW = _view()
PRINTS = [
    {"piece": SHIRT, "view": "front", "v": _vec(3)},
    {"piece": WHITE, "view": "front", "v": _vec(5)},
    {"piece": NAVY, "view": "front", "v": _vec(11)},
]


def scan(steps: list[dict[str, Any]], **payload: Any) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    payload.setdefault("view", VIEW)
    payload.setdefault("prints", PRINTS)
    run = subprocess.run(
        [node, str(DOM)],
        input=json.dumps({**payload, "steps": steps}),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    out: dict[str, Any] = json.loads(run.stdout or "{}")
    assert "error" not in out and run.returncode == 0, out.get("error") or run.stderr[-2000:]
    return out


def press(label: str, **kw: Any) -> dict[str, Any]:
    return {"op": "press", "label": label, **kw}


START, TAKE = press("Start the camera"), press("Take a photo")
PHOTO = [START, TAKE]


def posts(out: dict[str, Any], path: str) -> list[dict[str, Any]]:
    return [
        json.loads(n["body"]) for n in out["net"] if n["method"] == "POST" and n["path"] == path
    ]


def kept_or_sent(out: dict[str, Any]) -> list[str]:
    """Every photo, fingerprint or tag that left the phone."""
    sent = [d["fn"] for d in out["door"]]
    sent += ["fingerprint" for _ in posts(out, "/v1/wardrobe/fingerprints")]
    return sent


# ---- OPS-01: the check gates what is kept or sent -----------------------------------------------
@pytest.mark.parametrize("who", ["person", "face"])
def test_ops_01_a_person_or_a_face_keeps_and_sends_nothing(who: str) -> None:
    out = scan(
        [*PHOTO, press(f"This one: {VIEW_NAME[NAVY]} (likely this one)")],
        vision={who: True, "embed": _vec(11)},
    )
    assert PERSON in out["final"]
    assert SAVE not in out["final"] and "Remember how it looks" not in out["final"]
    assert kept_or_sent(out) == []


VIEW_NAME = {p["id"]: p["label"] for p in VIEW["pieces"]}


def test_ops_01_a_label_read_still_makes_its_event_with_a_person_in_view() -> None:
    out = scan(
        [*PHOTO, press(f"This one: {VIEW_NAME[NAVY]} (label read)")],
        vision={"person": True, "codes": ["jw1:abcdefgh"]},
    )
    [scan_post] = posts(out, "/v1/wardrobe/scan")
    [event] = scan_post["events"]
    assert event["piece"] == NAVY and event["kind"] == "seen" and event["how"] == "qr"
    assert event["source"] == "phone" and event["verified"] is True
    assert kept_or_sent(out) == [] and PERSON in out["final"]


def test_ops_01_a_clean_photo_then_one_with_a_face_saves_nothing_from_the_second() -> None:
    pick = press(f"This one: {VIEW_NAME[NAVY]} (likely this one)")
    out = scan(
        [*PHOTO, pick, press(SAVE), {"op": "vision", "vision": {"face": True}}, *PHOTO, pick],
        vision={"embed": _vec(11)},
    )
    assert [d["fn"] for d in out["door"]] == ["wardrobe"]  # the first photo's only
    assert SAVE not in out["final"] and PERSON in out["final"]


def test_ops_01_the_checks_and_the_crop_use_one_bitmap_and_the_crop_is_at_most_512() -> None:
    out = scan(
        [*PHOTO, press(f"This one: {VIEW_NAME[NAVY]} (likely this one)"), press(SAVE)],
        vision={"embed": _vec(11)},
    )
    checked = {r["src"] for r in out["runs"] if r["task"] in ("person", "face")}
    assert len(checked) == 1  # both checks on one canvas
    [photo] = checked
    crops = [c for c in out["crops"] if c["from"] == photo]
    assert crops and all(max(c["w"], c["h"]) <= 512 for c in crops)
    [sent] = out["door"]
    assert sent["piece"] == NAVY and sent["view"] == "front" and max(sent["w"], sent["h"]) <= 512
    assert (sent["w"], sent["h"]) != (1280, 720)  # the box, never the whole frame
    embedded = {r["src"] for r in out["runs"] if r["task"] == "embed"}
    assert sent["from"] in embedded  # the crop that was compared is the crop that was saved


def test_ops_01_without_the_check_saving_is_off_and_taps_still_work() -> None:
    out = scan(
        [*PHOTO, press(f"This one: {VIEW_NAME[NAVY]} (likely this one)")],
        vision={"embed": _vec(11)},
        missing=["person"],
    )
    assert NO_CHECK in out["final"] and SAVE not in out["final"]
    assert kept_or_sent(out) == [] and len(posts(out, "/v1/wardrobe/scan")) == 1


def test_ops_01_stop_ends_the_camera_and_the_label_reader_and_keeps_unsent_scans() -> None:
    out = scan(
        [
            press("To laundry"),
            START,
            {"op": "wait", "ms": 80},
            press("Put in laundry"),
            {"op": "stop"},
        ],
        vision={"codes": ["jw1:abcdefgh"]},
        offline=True,
    )
    assert out["camera"]["live"] is False and out["camera"]["stops"] >= 1
    assert out["streams"] == 1 and out["streamStops"] == 1
    assert "Not sent yet: keep this page open. (1)" in out["final"]


# ---- D10: private pieces ------------------------------------------------------------------------
def test_d10_a_private_piece_never_gets_a_photo_a_fingerprint_or_a_tag() -> None:
    out = scan(
        [*PHOTO, press("This one: A private basic (No. 2) (label read)")],
        vision={"codes": ["jw1:qrstuvwx"], "embed": _vec(11)},
        view=_view(ai_tagging=True),
    )
    assert "A private piece keeps no photo and no fingerprint." in out["final"]
    for words in (SAVE, "Remember how it looks", TAG):
        assert words not in out["final"]
    assert kept_or_sent(out) == []


def test_d10_a_private_by_default_kind_asks_make_it_private() -> None:
    out = scan([*PHOTO, press("Vest")], vision={})
    assert "Make it private?" in out["final"]
    out = scan([*PHOTO, press("Vest"), press("Make it private"), press("Save as a new piece")])
    [call] = [n for n in out["net"] if n["path"] == "/v1/wardrobe/tools/wardrobe_add"]
    assert json.loads(call["body"]) == {
        "arguments": {"type": "vest", "private": True, "colour": "navy"}
    }
    assert set(re.findall(r"'(\w+)'", _region("PRIVATE_TYPES = [", "];"))) == PRIVATE_BY_DEFAULT


def _region(start: str, end: str) -> str:
    js = SCAN.read_text(encoding="utf-8")
    i = js.index(start)
    return js[i : js.index(end, i)]


# ---- D7: candidates, twins, foreign codes, the AI tag -------------------------------------------
def test_inv_05_a_piece_seen_before_is_offered_and_his_tap_keeps_its_id() -> None:
    out = scan([*PHOTO], vision={"embed": _vec(11)})
    assert f"This one: {VIEW_NAME[NAVY]} (likely this one)" in out["steps"][-1]["buttons"]
    assert posts(out, "/v1/wardrobe/scan") == []  # nothing decided without his tap
    assert posts(out, "/v1/wardrobe/tools/wardrobe_add") == []


def test_identical_copies_are_said_and_not_sure_which_holds_both() -> None:
    prints = [*PRINTS, {"piece": SNEAKER_L, "view": "front", "v": _vec(17)}]
    prints.append({"piece": SNEAKER_R, "view": "front", "v": _vec(17)})
    out = scan(
        [press("To laundry"), *PHOTO, press("Not sure which"), press("Put in laundry")],
        vision={"embed": _vec(17)},
        prints=prints,
    )
    assert any("Identical copies" in s["text"] for s in out["steps"])
    [body] = posts(out, "/v1/wardrobe/scan")
    got = sorted((e["piece"], e["kind"], e["verified"]) for e in body["events"])
    assert got == [(SNEAKER_L, "deposited", False), (SNEAKER_R, "deposited", False)]


def test_a_code_that_is_not_his_label_is_ignored_and_never_sent() -> None:
    foreign = "https://example.com/shirt-brand-tag-9182"
    out = scan(
        [press("To laundry"), *PHOTO, press("Put in laundry")],
        vision={"codes": [foreign, "jw1:zzzzzzzz", "jw1:abcdefgh"]},
    )
    assert any("not a JARVIS label" in s["text"] for s in out["steps"])
    [body] = posts(out, "/v1/wardrobe/scan")
    assert [e["piece"] for e in body["events"]] == [NAVY]
    blob = json.dumps(out["net"])
    assert "example.com" not in blob and "zzzzzzzz" not in blob and foreign not in out["final"]


def test_the_ai_tag_needs_his_setting_and_the_ai_and_says_its_rupees_first() -> None:
    pick = press(f"This one: {VIEW_NAME[NAVY]} (likely this one)")
    on = _view(ai_tagging=True, tag_month_inr=0.02, tag_cap_inr=30)
    out = scan([*PHOTO, pick], vision={"embed": _vec(11)}, view=on)
    assert TAG in out["final"] and "AI tagging this month: ₹0.02 of ₹30." in out["final"]
    assert kept_or_sent(out) == []  # the rupees are said before anything is sent
    out = scan([*PHOTO, pick, press(TAG)], vision={"embed": _vec(11)}, view=on)
    assert [(d["fn"], d["piece"]) for d in out["door"]] == [("tag", NAVY)]
    assert "The AI suggests: shirt, navy." in out["final"]
    for kw in ({"view": _view()}, {"view": on, "noAi": True}):
        assert TAG not in scan([*PHOTO, pick], vision={"embed": _vec(11)}, **kw)["final"]
    full = _view(ai_tagging=True, tag_month_inr=29.9, tag_cap_inr=30)
    out = scan([*PHOTO, pick], vision={"embed": _vec(11)}, view=full)
    assert TAG not in out["final"] and "limit" in out["final"]
    out = scan([*PHOTO, pick], vision={"embed": _vec(11), "face": True}, view=on)
    assert TAG not in out["final"]  # the check refused this photo


# ---- the laundry checkpoints --------------------------------------------------------------------
def test_lnd_01_put_in_laundry_sends_deposits_with_ids_only() -> None:
    out = scan(
        [press("To laundry"), *PHOTO, press("Put in laundry")], vision={"codes": ["jw1:abcdefgh"]}
    )
    [body] = posts(out, "/v1/wardrobe/scan")
    [e] = body["events"]
    assert (e["piece"], e["kind"], e["how"], e["verified"]) == (NAVY, "deposited", "qr", True)
    assert body["rev_seen"] == VIEW["rev"] and e["via"].startswith("ph-")
    assert set(e) <= {"client_id", "piece", "kind", "at", "sent", "source", "via", "how"} | {
        "score",
        "verified",
        "place",
    }


def test_lnd_02_a_scan_he_cancels_sends_nothing() -> None:
    out = scan([press("To laundry"), *PHOTO, press("Cancel")], vision={"codes": ["jw1:abcdefgh"]})
    assert posts(out, "/v1/wardrobe/scan") == [] and "Nothing was sent." in out["final"]


def test_lnd_03_more_i_couldnt_show_is_a_pending_deposit_with_no_id() -> None:
    out = scan(
        [
            press("To laundry"),
            *PHOTO,
            {"op": "select", "label": "And more I couldn’t show", "value": "2"},
            {"op": "select", "label": "What kind", "value": "tops"},
            press("Put in laundry"),
        ],
        vision={"codes": ["jw1:abcdefgh"]},
    )
    [call] = [n for n in out["net"] if n["path"] == "/v1/wardrobe/tools/laundry_move"]
    assert json.loads(call["body"]) == {
        "arguments": {"step": "basket", "unseen": 2, "category": "tops"}
    }


@pytest.mark.parametrize(("dry", "kind"), [(True, "returned"), (False, "needs_prep")])
def test_lnd_10_back_clean_sends_returns_with_the_place_or_needs_pressing(
    dry: bool, kind: str
) -> None:
    place = VIEW["places"][1]["id"]
    steps = [
        press("Back clean"),
        *PHOTO,
        {"op": "select", "label": "Where it goes", "value": place},
    ]
    if not dry:
        steps.append(press("Needs pressing"))
    out = scan([*steps, press("Put away clean")], vision={"codes": ["jw1:abcdefgh"]})
    [body] = posts(out, "/v1/wardrobe/scan")
    [e] = body["events"]
    assert e["kind"] == kind and e["piece"] == NAVY
    assert e.get("place") == (place if dry else None)


# ---- D4.1: unsent scans, sign-in, Checking... ---------------------------------------------------
def test_an_unsent_scan_waits_in_memory_and_goes_on_send_now() -> None:
    out = scan(
        [
            press("To laundry"),
            *PHOTO,
            press("Put in laundry"),
            {"op": "online"},
            press("Send now"),
        ],
        vision={"codes": ["jw1:abcdefgh"]},
        offline=True,
    )
    tries = posts(out, "/v1/wardrobe/scan")
    assert (
        len(tries) == 2 and tries[0]["events"][0]["client_id"] == tries[1]["events"][0]["client_id"]
    )
    e = tries[1]["events"][0]
    assert e["sent"] >= e["at"] and "Not sent yet" not in out["final"]
    assert any("Not sent yet: keep this page open. (1)" in s["text"] for s in out["steps"])


def test_before_sign_in_a_photo_asks_the_server_nothing() -> None:
    out = scan([*PHOTO], signedIn=False, vision={"embed": _vec(11)})
    assert out["net"] == [] and "Sign in first." in out["final"]


def test_checking_shows_while_the_three_models_run() -> None:
    out = scan([START, press("Take a photo", now=True)], vision={"delay_ms": 60})
    assert "Checking…" in out["steps"][-1]["text"]


# ---- INV-10: a care label -----------------------------------------------------------------------
def test_inv_10_label_words_are_offered_unverified_and_the_raw_text_never_leaves() -> None:
    raw = "BRANDNAME LTD\nSIZE M\n60% COTTON 40% POLYESTER\nMACHINE WASH COLD\nDO NOT BLEACH"
    raw += "\nMADE IN X"
    out = scan(
        [press("Read a label"), *PHOTO, press("Confirm"), press("Keep these (unverified)")],
        vision={"text": raw},
    )
    text = out["steps"][2]["text"]
    for words in ("Size M", "60% cotton", "40% polyester", "machine wash", "cold wash"):
        assert words in text, words
    assert "do not bleach" in text and "Unverified: read from the label" in text
    edits = [json.loads(n["body"])["arguments"] for n in out["net"] if "wardrobe_edit" in n["path"]]
    assert edits[0]["value"] == {"v": "M", "ok": True} and edits[0]["label_field"] == "size"
    assert all(e["value"]["ok"] is False for e in edits[1:]) and len(edits) == 7
    blob = json.dumps(out["net"])
    assert "BRANDNAME" not in blob and "MADE IN" not in blob and "MACHINE WASH" not in blob


def test_the_label_words_are_the_servers_fixed_lists() -> None:
    fabrics = set(re.findall(r"'(\w+)'", _region("FABRICS13 = [", "];")))
    assert fabrics <= set(FABRICS)
    care = set(re.findall(r"'([a-z_]+)'", _region("CARE13 = [", "];\n")))
    assert care <= set(CARE_WORDS) and len(care) == 15


# ---- the panel's rules --------------------------------------------------------------------------
def test_the_scan_module_keeps_its_house_rules() -> None:
    js = SCAN.read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*|/\*.*?\*/", "", js, flags=re.S)
    assert js.isascii() and len(js.splitlines()) <= 600
    for bad in ("innerHTML", "eval(", "new Function", "console.log", "document.cookie"):
        assert bad not in code, bad
    assert "'/v1/wardrobe?private=1'" in code  # his own list, his own console (D10)
    assert code.count("door.wardrobe(") == 1 and code.count("door.tag(") == 1
    for fn in ("savePhoto", "remember", "tag"):
        body = code[code.index(f"async function {fn}(") :]
        assert body.index("if (!allowed(card)") < 120, fn  # the gate first, every time


SPLIT_JS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const region = src.slice(src.indexOf('/*SCAN-PURE-BEGIN*/'), src.indexOf('/*SCAN-PURE-END*/'));
const { boxesOf } = new Function(region + '\nreturn { boxesOf };')();
const W = 64, H = 48;
function scene(rects) {
  const d = new Uint8ClampedArray(W * H * 4);
  for (let y = 0; y < H; y += 1) for (let x = 0; x < W; x += 1) {
    const hit = rects.find((r) => x >= r[0] && x < r[0] + r[2] && y >= r[1] && y < r[1] + r[3]);
    d.set([...(hit ? hit[4](x) : [232, 228, 220]), 255], (y * W + x) * 4);
  }
  return d;
}
const navy = () => [28, 36, 78], stripes = (x) => (x % 3 === 0 ? [240, 240, 236] : [28, 36, 78]);
console.log(JSON.stringify({
  striped: boxesOf(scene([[20, 10, 16, 30, stripes]]), W, H).length,
  apart: boxesOf(scene([[4, 8, 12, 30, navy], [40, 8, 14, 20, navy]]), W, H)
    .map((b) => Math.round(b.x * 64)),
  bare: boxesOf(scene([]), W, H),
  speck: boxesOf(scene([[30, 20, 1, 1, navy]]), W, H).length,
}));
"""


def test_the_split_finds_one_box_a_piece_and_the_whole_frame_when_bare() -> None:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    run = subprocess.run(
        [node, "-e", SPLIT_JS, str(SCAN)], capture_output=True, text=True, timeout=30, check=False
    )
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["striped"] == 1  # light stripes are closed over: one shirt, one box
    # two laid apart: two boxes, left first; a bare surface: the whole frame; a speck: no piece
    assert len(got["apart"]) == 2 and got["apart"][0] < got["apart"][1]
    assert got["bare"] == [{"x": 0, "y": 0, "w": 1, "h": 1}] and got["speck"] == 1
