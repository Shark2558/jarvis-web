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
WORDS = ROOT / "src" / "jarvis" / "api" / "static" / "console-wardrobe-words.js"
P = [p.id for p in PILOT]
SHIRT, WHITE, NAVY, VEST1, VEST2, SNEAKER_L, SNEAKER_R = P[0], P[1], P[2], P[8], P[9], P[17], P[18]
PERSON = (
    "This picture shows a person. Lay the piece on a surface or hang it, and take the photo again."
)
NO_CHECK = "Saving a photo is off on this phone: the check for a person or a face is not installed."
SAVE = "Save this photo with the piece (sealed; only you)"
TAG = "Send this photo to the AI to tag it (about ₹0.01–₹0.51, depending on the brain)"


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
    checked = [r["src"] for r in out["runs"] if r["task"] in ("person", "face")]
    photo, sent = checked[0], out["door"][0]["from"]  # the photo the crops are cut from, the crop
    assert checked[:4] == [photo, photo, sent, sent] and len(checked) == 12  # + its 4 parts (H2)
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


# ---- H1: a live session keeps his list after a send (REVIEW-D-1) --------------------------------
def test_h1_after_a_live_send_his_next_label_is_read_and_his_names_stay() -> None:
    out = scan(
        [
            press("To laundry"),
            START,
            {"op": "wait", "ms": 80},
            press("Put in laundry"),  # the contract's reply carries no view (ScanReply.view)
            {"op": "vision", "vision": {"codes": ["jw1:qrstuvwx"]}},
            {"op": "wait", "ms": 80},
            press("Put in laundry"),
        ],
        vision={"codes": ["jw1:abcdefgh"]},
    )
    assert not any("not a JARVIS label" in s["text"] for s in out["steps"])
    assert "A private basic (No. 2)" in out["steps"][5]["text"]  # his second label, his words
    first, second = posts(out, "/v1/wardrobe/scan")
    assert VEST1 in [e["piece"] for e in second["events"]]  # read as his (M1 drops the repeat)
    assert first["rev_seen"] == second["rev_seen"] == VIEW["rev"]  # never null after a send


# ---- H2: the crop that would leave is checked itself (REVIEW-D-1) --------------------------------
@pytest.mark.parametrize("what", [SAVE, "Remember how it looks", TAG])
def test_h2_a_face_only_the_crop_shows_keeps_and_sends_nothing(what: str) -> None:
    pick = press(f"This one: {VIEW_NAME[NAVY]} (likely this one)")
    on = _view(ai_tagging=True, tag_month_inr=0.02, tag_cap_inr=30)
    out = scan([*PHOTO, pick, press(what)], vision={"embed": _vec(11), "crop_face": True}, view=on)
    assert out["steps"][3]["found"] is True  # the whole frame passed: the button was offered
    assert kept_or_sent(out) == [] and PERSON in out["final"]
    for words in (SAVE, "Remember how it looks", TAG):
        assert words not in out["final"]
    faces = [r["src"] for r in out["runs"] if r["task"] == "face"]
    [crop] = [r["src"] for r in out["runs"] if r["task"] == "embed"]
    assert len(faces) == 2 and faces[0] != crop and faces[1] == crop  # the photo, then the crop


def test_h2_the_crop_is_checked_once_and_a_clean_crop_still_saves() -> None:
    pick = press(f"This one: {VIEW_NAME[NAVY]} (likely this one)")
    out = scan(
        [*PHOTO, pick, press(SAVE), press("Remember how it looks")], vision={"embed": _vec(11)}
    )
    assert [d["fn"] for d in out["door"]] == ["wardrobe"] and len(posts(out, FP)) == 1
    faces = [r["src"] for r in out["runs"] if r["task"] == "face"]
    assert faces[1] == out["door"][0]["from"]  # the saved bytes were checked, once, then
    assert len(faces) == 6 and len(set(faces[2:])) == 4  # four overlapping parts of them (H2)
    parts = [c for c in out["crops"] if c["from"] == faces[1]]
    assert len(parts) == 4 and all(c["w"] < 512 for c in parts)  # each two-thirds of the crop


FP = "/v1/wardrobe/fingerprints"


# ---- M1: the camera and its label reader across a step change, a send and Cancel ---------------
def test_m1_a_step_change_ends_the_camera_and_the_label_reader() -> None:
    steps = [press("To laundry"), START, {"op": "wait", "ms": 60}, press("Add pieces")]
    out = scan([*steps, {"op": "wait", "ms": 80}], vision={"codes": ["jw1:abcdefgh"]})
    assert out["streams"] == out["streamStops"] == 1 and out["camera"]["live"] is False
    assert out["camera"]["starts"] == out["camera"]["stops"] == 1
    assert out["steps"][-1]["videos"] == 0 and "Its label was read" not in out["final"]


@pytest.mark.parametrize("end", ["Put in laundry", "Cancel"])
def test_m1_a_live_send_or_cancel_keeps_the_view_and_never_offers_that_label_again(
    end: str,
) -> None:
    steps = [press("To laundry"), START, {"op": "wait", "ms": 80}, press(end)]
    out = scan(
        [*steps, {"op": "wait", "ms": 120}, press("Put in laundry")], vision={"codes": [LBL]}
    )
    assert len(posts(out, "/v1/wardrobe/scan")) == (1 if end == "Put in laundry" else 0)
    assert out["steps"][-1]["found"] is False  # nothing left to send: no duplicate deposit
    assert out["steps"][-1]["videos"] == 1 and out["camera"]["live"] is True  # the view stays
    assert out["streams"] == 1 and out.get("streamStops", 0) == 0  # the reader keeps reading
    assert "Its label was read" not in out["final"]


LBL = "jw1:abcdefgh"


# ---- M2: a "crop" that is the whole photo is never kept or sent; the crop is shown first -------
BARE = {"bg": [230, 228, 220], "rects": []}  # a white shirt on a white sheet: no edges to find
WIDE = {
    "x": 0.04,
    "y": 0.06,
    "w": 0.92,
    "h": 0.88,
    "rgb": [28, 36, 78],
}  # its box: 88 % of the photo
SCENES = [BARE, {"bg": [230, 228, 220], "rects": [WIDE]}]
WHOLE = (
    "JARVIS couldn’t find the piece’s edges: lay it on a plain surface of another colour so the "
    "photo can be cropped to it."
)


@pytest.mark.parametrize("scene", SCENES, ids=["bare", "wide"])
def test_m2_a_whole_frame_box_offers_taps_only_and_sends_nothing(scene: dict[str, Any]) -> None:
    pick = press(f"This one: {VIEW_NAME[NAVY]} (likely this one)")
    on = _view(ai_tagging=True, tag_month_inr=0.02, tag_cap_inr=30)
    out = scan([*PHOTO, pick], vision={"embed": _vec(11)}, view=on, scene=scene)
    assert WHOLE in out["final"] and out["steps"][-1]["shown"] == []
    for words in (SAVE, "Remember how it looks", TAG):
        assert words not in out["final"]
    assert kept_or_sent(out) == [] and len(posts(out, "/v1/wardrobe/scan")) == 1  # the tap


def test_m2_the_card_shows_the_exact_crop_before_anything_is_sent() -> None:
    pick = press(f"This one: {VIEW_NAME[NAVY]} (likely this one)")
    out = scan([*PHOTO, pick, press(SAVE)], vision={"embed": _vec(11)})
    [shown] = out["steps"][2]["shown"]  # drawn on the card, above Save, before any press
    assert out["door"][0]["from"] == shown and "Save keeps exactly this crop:" in out["final"]


# ---- M3: the rupees for one AI tag are true ------------------------------------------------------
def test_m3_the_tag_range_is_the_price_tables_cheapest_and_dearest_brain() -> None:
    from jarvis.config import Settings
    from jarvis.llm.pricing import PRICES

    tokens_in, tokens_out = 750, 120  # one crop and its answer (docs/plans/r13-wardrobe.md D7)
    rate = Settings.model_fields["usd_inr_rate"].default
    each = sorted(
        (tokens_in * p.input_per_mtok + tokens_out * p.output_per_mtok) / 1e6 * rate
        for name, p in PRICES.items()
        if name.startswith("claude-")  # the seeing, non-training brains
    )
    assert rate == 95.24 and (round(each[0], 2), round(each[-1], 2)) == (0.01, 0.51)
    js = SCAN.read_text(encoding="utf-8")
    assert "const TAG_MOST = 0.51, TAG_RANGE = '\\u20b90.01\\u2013\\u20b90.51," in js


def test_m3_the_brains_own_estimate_is_said_and_used_for_the_limit_when_the_view_has_it() -> None:
    pick = press(f"This one: {VIEW_NAME[NAVY]} (likely this one)")
    own = _view(ai_tagging=True, tag_month_inr=0.02, tag_cap_inr=30, tag_estimate_inr=0.26)
    out = scan([*PHOTO, pick], vision={"embed": _vec(11)}, view=own)
    assert "Send this photo to the AI to tag it (about ₹0.26)" in out["final"]
    near = _view(ai_tagging=True, tag_month_inr=29.6, tag_cap_inr=30)  # 29.6 + 0.51 passes 30
    out = scan([*PHOTO, pick], vision={"embed": _vec(11)}, view=near)
    assert TAG not in out["final"] and "limit" in out["final"]


def test_l10_the_tag_checks_no_ai_again_at_the_press() -> None:
    pick = press(f"This one: {VIEW_NAME[NAVY]} (likely this one)")
    on = _view(ai_tagging=True, tag_month_inr=0.02, tag_cap_inr=30)
    steps = [*PHOTO, pick, {"op": "noai", "on": True}, press(TAG)]
    out = scan(steps, vision={"embed": _vec(11)}, view=on)
    assert out["steps"][-1]["found"] is True and out["door"] == []


# ---- M5: the bands say nothing they can't back ------------------------------------------------
BANDS_JS = r"""
const P = await import('data:text/javascript;base64,' + Buffer.from(require('fs')
  .readFileSync(process.argv[1], 'utf8')).toString('base64'));
const v = (seed, n = 64) => Uint8Array.from({ length: n }, (_, i) => (seed * 31 + i * 7 + (i % (seed || 1))) % 256);
const type = () => 'shirt';
const gallery = [1, 2, 3, 4, 5].map((s) => ({ piece: 'p' + s, v: v(s) }));
const near = Uint8Array.from(v(3), (x, i) => (i % 9 ? x : 255 - x)); // piece 3, seen at another angle
console.log(JSON.stringify({
  banded: P.candidates(near, gallery, type).top,
  one: P.candidates(v(9), [{ piece: 'p1', v: v(1) }], type),
  two: P.candidates(v(9), gallery.slice(0, 2), type),
}));
"""


def _bands() -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    src = "(async () => {" + BANDS_JS + "})();"
    run = subprocess.run(
        [node, "-e", src, str(WORDS)], capture_output=True, text=True, timeout=30, check=False
    )
    assert run.returncode == 0, run.stderr
    out: dict[str, Any] = json.loads(run.stdout)
    return out


def test_m5_no_candidate_is_ever_called_new_and_few_prints_say_no_band() -> None:
    got = _bands()
    assert all(c["band"] in ("likely", "maybe", "weak") for c in got["banded"])
    assert got["one"]["top"][0]["band"] is None and got["two"]["top"][0]["band"] is None
    assert got["one"]["twins"] is False and got["two"]["twins"] is False
    js = WORDS.read_text(encoding="utf-8") + SCAN.read_text(encoding="utf-8")
    shown = re.sub(r"//[^\n]*|/\*.*?\*/", "", js, flags=re.S)  # what a card can say
    assert "new?" not in shown and "LIFT = 0.25, BANDED = 3" in js


def test_m5_a_single_print_offers_its_piece_with_no_band_words() -> None:
    out = scan(PHOTO, vision={"embed": _vec(11)}, prints=PRINTS[2:])
    assert f"This one: {VIEW_NAME[NAVY]}" in out["steps"][-1]["buttons"]  # just his tap to make


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


def _region(start: str, end: str, path: Path = WORDS) -> str:
    js = path.read_text(encoding="utf-8")
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


def test_the_words_are_their_own_module_imported_on_his_first_press() -> None:
    code = re.sub(r"//[^\n]*|/\*.*?\*/", "", WORDS.read_text(encoding="utf-8"), flags=re.S)
    banned = ("document", "window", "fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket")
    banned += ("localStorage", "sessionStorage", "indexedDB", "drawImage", "getImageData", "toBlob")
    banned += ("createImageBitmap", "JarvisChat", ".raw(", "FormData", ".api(", "import(", "Date")
    for bad in banned:
        assert bad not in code, bad
    assert WORDS.read_text(encoding="utf-8").isascii() and len(code.splitlines()) <= 200
    scan_code = re.sub(r"//[^\n]*|/\*.*?\*/", "", SCAN.read_text(encoding="utf-8"), flags=re.S)
    assert scan_code.count("import('./console-wardrobe-words.js')") == 1
    assert "function labelPiece(" not in scan_code and "function boxesOf(" in scan_code
    assert scan([])["imported"] == []  # the page's start waits for nothing
    assert scan(PHOTO, vision={"embed": _vec(11)})["imported"] == ["./console-wardrobe-words.js"]


def test_words_that_cannot_load_say_so_and_ask_and_send_nothing() -> None:
    out = scan([START, TAKE, press("Choose a photo")], noWords=True)
    assert "This part couldn’t load. Reload the page to try again." in out["final"]
    assert out["net"] == [] and out["door"] == [] and out["camera"]["live"] is False


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
