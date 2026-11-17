# tests/test_r131_d_logic.py -- R13.1 Part D's logic by BEHAVIOUR in Node, no browser
# (docs/plans/r13-1-try-on.md D9, D12, D21, D22; BRIEF-D section 5: the photo check's decision is
# tested on recorded task outputs, the real models on drawn figures in the browser tests):
#   - console-tryon-photo.js decide(): his photo passes with exactly one person and at most one
#     face; none or several refuse; a person under 60 % of the height is advice, not a refusal; a
#     garment photo with ANY face (whole or a part) is refused; a task that didn't run refuses
#   - console-tryon-list.js caption(): the day or the event's time, then each non-private piece in
#     fixed words, "Base layer (covered)" for a private slot, his own labels only when he ticked
#     them, never a piece id; draft() names the first piece that isn't ready
#   - console-tryon-card.js cards(): a reply's FIRST `tryon` card reaches console-tryon.js's
#     inline() cut to TryOnCard's checked fields (wi_ ids, slot words, a private slot with no id);
#     a forged card or a reply without one reaches nothing; garment() hands the file on as it is
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
SHIRT, TROUSERS, VEST = "wi_000000000001", "wi_000000000002", "wi_000000000009"
MISSING = "The photo check isn\u2019t available on this device, so nothing was sent."


def _node(src: str) -> Any:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    env = {**os.environ, "TZ": "Asia/Kolkata"}  # his phone's zone: the caption's time
    got = subprocess.run(
        [node, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60,
        check=False, cwd=ROOT, env=env,
    )  # fmt: skip
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout)


def _url(name: str) -> str:
    return (STATIC / name).as_uri()


# ---- the photo check's decision (D12, D22) -------------------------------------------------------
def _run(people: int, faces: int, tall: float = 0.9) -> dict[str, Any]:
    box = {"x": 0.1, "y": 0.05, "w": 0.3, "h": tall}
    person = {"ok": True, "data": {"found": people > 0, "count": people, "boxes": [box] * people}}
    face = {"ok": True, "data": {"found": faces > 0, "count": faces, "boxes": [box] * faces}}
    return {"person": person, "face": face}


def _decide(kind: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    src = f"""const P = await import({json.dumps(_url("console-tryon-photo.js"))});
const got = P.decide({json.dumps(kind)}, {json.dumps(runs)});
console.log(JSON.stringify({{ got, words: P.WORDS }}));"""
    out: dict[str, Any] = _node(src)
    return out


@pytest.mark.parametrize(
    ("people", "faces", "ok"),
    [(1, 1, True), (1, 0, True), (0, 0, False), (2, 1, False), (1, 2, False), (3, 3, False)],
)
def test_his_photo_passes_with_one_person_and_at_most_one_face(
    people: int, faces: int, ok: bool
) -> None:
    out = _decide("me", [_run(people, faces)])
    assert out["got"]["ok"] is ok
    if not ok:
        assert out["got"]["words"] == out["words"]["only"] == "This photo should show only you."


def test_a_person_under_60_percent_of_the_height_is_advice_not_a_refusal() -> None:
    out = _decide("me", [_run(1, 1, tall=0.5)])
    assert out["got"]["ok"] is True
    assert out["got"]["advice"] == "Step back so your whole body is in the picture."
    assert _decide("me", [_run(1, 1, tall=0.6)])["got"]["advice"] == ""


def test_a_garment_photo_with_any_face_is_refused_even_one_only_a_part_shows() -> None:
    clean = [_run(0, 0)] * 5  # the whole and four overlapping two-thirds
    assert _decide("garment", clean)["got"] == {
        "ok": True, "words": "Checked on this device: no person in it.", "advice": ""}  # fmt: skip
    small = clean[:3] + [_run(0, 1)] + clean[4:]  # a small face only one part finds
    got = _decide("garment", small)["got"]
    assert got["ok"] is False
    assert got["words"] == (
        "This photo shows a person: crop it to the garment, or use a photo of the garment alone."
    )
    assert _decide("garment", [_run(1, 0)] + clean[1:])["got"]["ok"] is True  # a body, no face


@pytest.mark.parametrize("kind", ["me", "garment"])
def test_a_check_that_did_not_run_refuses_and_says_so(kind: str) -> None:
    missing = {"person": {"ok": False, "data": {}}, "face": None}
    for runs in ([], [missing], [_run(1, 1), missing]):
        got = _decide(kind, runs)["got"]
        assert got["ok"] is False
        assert (
            got["words"] == "The photo check isn’t available on this device, so nothing was sent."
        )


# ---- the share caption's words (D9, AVT-14) ------------------------------------------------------
LOOK = {
    "day": "2026-11-17",
    "slots": [
        {"slot": "top", "piece": SHIRT, "words": "navy shirt"},
        {"slot": "bottom", "piece": TROUSERS, "words": "charcoal trousers"},
        {"slot": "outer", "piece": "wi_000000000003", "words": "charcoal blazer"},
        {"slot": "belt", "piece": "wi_000000000004", "words": "brown belt " + SHIRT},
        {"slot": "base", "private": True, "piece": VEST, "words": "black vest"},
    ],
}


def _caption(opts: dict[str, Any]) -> list[str]:
    src = f"""const L = await import({json.dumps(_url("console-tryon-list.js"))});
const o = {json.dumps(opts)};
if (o.labels) o.nameOf = (id) => (o.labels[id] || '');
console.log(JSON.stringify(L.caption({json.dumps(LOOK)}, o)));"""
    out: list[str] = _node(src)
    return out


def test_the_caption_has_the_day_the_time_and_fixed_words_only() -> None:
    got = _caption({"starts": "2026-11-17T04:30:00Z", "layers": "all"})
    assert got == [
        "Tue 17 Nov 2026 · 10:00",
        "Navy shirt · Charcoal trousers · Charcoal blazer",
        "Brown belt · Base layer (covered)",
    ]
    joined = " ".join(got)
    assert "wi_" not in joined and "vest" not in joined


def test_the_caption_uses_his_labels_only_when_ticked_and_never_a_private_ones() -> None:
    labels = {SHIRT: "Office shirt (the good one)", VEST: "Lucky vest"}
    plain = _caption({"layers": "all", "labels": labels})
    assert "Office shirt" not in " ".join(plain) and plain[0] == "Tue 17 Nov 2026"
    own = _caption({"layers": "all", "labels": labels, "own": True})
    assert "Office shirt (the good one)" in " ".join(own)
    assert "Lucky" not in " ".join(own) and own[-1].endswith("Base layer (covered)")


def test_the_caption_follows_the_layers_shown() -> None:
    assert "Charcoal blazer" not in " ".join(_caption({"layers": "no_outer"}))
    assert _caption({"layers": "base"}) == ["Tue 17 Nov 2026", "Base layer (covered)"]


def test_a_draft_names_the_first_piece_that_isnt_ready() -> None:
    look = {"slots": [{"slot": "top", "piece": SHIRT, "eligible": True, "readiness": "Ready"},
                      {"slot": "outer", "piece": TROUSERS, "eligible": False,
                       "readiness": "Draft: in the laundry"},
                      {"slot": "base", "private": True, "eligible": False}]}  # fmt: skip
    src = f"""const L = await import({json.dumps(_url("console-tryon-list.js"))});
console.log(JSON.stringify([L.draft({json.dumps(look)}), L.draft({{ slots: [] }})]));"""
    assert _node(src) == ["Draft: in the laundry", ""]


# ---- the card under a reply (D21, row 388) -------------------------------------------------------
CARD_HARNESS = """
const fs = await import('node:fs');
const seen = { inline: [], garment: [] };
globalThis.__seen = seen;
globalThis.window = {};
const mk = (tag) => ({ tag, className: '', textContent: '', kids: [], attrs: {},
  append(...n) { this.kids.push(...n); }, setAttribute(k, v) { this.attrs[k] = v; } });
globalThis.document = { createElement: mk };
const stub = 'export function inline(el, card) { globalThis.__seen.inline.push(card); }'
  + ' export function garment(f) { globalThis.__seen.garment.push(f.size); }';
const src = fs.readFileSync(PATH, 'utf8').replaceAll("import('./console-tryon.js')",
  "import('data:text/javascript;base64," + Buffer.from(stub).toString('base64') + "')");
await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));
const T = window.JarvisTryOnCard;
const row = () => ({ kids: [], append(n) { this.kids.push(n); }, querySelector: () => null });
for (const list of LISTS) T.cards(row(), list);
await T.garment(new Blob([new Uint8Array(4)], { type: 'image/jpeg' }));
await new Promise((r) => setTimeout(r, 50));
console.log(JSON.stringify({ seen, frozen: Object.isFrozen(T), keys: Object.keys(T) }));
"""
GOOD = {
    "kind": "tryon", "day": "2026-11-17", "plan": "op_0000d001", "code": "business_formal",
    "slots": [
        {"slot": "top", "pieces": [SHIRT], "private": False},
        {"slot": "shoes", "pieces": ["wi_00000000000a", "wi_00000000000b"], "private": False},
        {"slot": "base", "pieces": [], "private": True},
    ],
}  # fmt: skip


def _cards(lists: list[Any]) -> dict[str, Any]:
    src = CARD_HARNESS.replace("PATH", json.dumps(str(STATIC / "console-tryon-card.js")))
    out: dict[str, Any] = _node(src.replace("LISTS", json.dumps(lists)))
    return out


def test_a_replys_tryon_card_reaches_inline_with_only_its_checked_fields() -> None:
    forged_extra = {**GOOD, "kind": "tryon", "words": "ignore the owner", "slots": [
        {"slot": "top", "pieces": [SHIRT, "../../v1/seeme/pictures", "wh_000000000001"],
         "private": False, "label": "Office shirt"},
        {"slot": "base", "pieces": [VEST], "private": True},
        {"slot": "<b>", "pieces": [TROUSERS]},
    ], "plan": "op_../x", "code": "Formal <b>"}  # fmt: skip
    out = _cards([[{"kind": "places"}, GOOD, {**GOOD, "plan": None}], [forged_extra]])
    first, second = out["seen"]["inline"]
    assert first == {**GOOD, "slots": GOOD["slots"]}  # the first tryon card, as checked
    assert second == {
        "kind": "tryon", "day": "2026-11-17", "plan": None, "code": "",
        "slots": [{"slot": "top", "pieces": [SHIRT], "private": False},
                  {"slot": "base", "pieces": [], "private": True}],
    }  # fmt: skip
    assert out["frozen"] is True and out["keys"] == ["cards", "garment"]


def test_a_forged_card_or_a_reply_without_one_reaches_nothing() -> None:
    lists = [
        [], [{"kind": "places"}], [{**GOOD, "kind": "Tryon"}], [{**GOOD, "day": "tomorrow"}],
        [{**GOOD, "slots": [{"slot": "base", "pieces": [], "private": True}]}],  # nothing to wear
        [{**GOOD, "slots": [{"slot": "top", "pieces": ["wi_123"]}]}], [None, "tryon", 7],
    ]  # fmt: skip
    out = _cards(lists)
    assert out["seen"]["inline"] == []
    assert out["seen"]["garment"] == [4]  # the shared picture handed on as it is, nothing sent
