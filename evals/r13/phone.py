# evals/r13/phone.py
"""R13 eval, Part D's suite (`phone`): the phone and the panel (docs/plans/r13-wardrobe.md OPS-01,
D6, D10, D20; "Tests and evals").

- `sentences`: every D20 sentence runs as a whole No-AI turn (`offline.no_ai.run_no_ai`) against a
  recording gateway and makes exactly its tool calls; the path holds no provider, so no model is
  ever called;
- `r14`: every R14 phrase routes as before with R13's routers installed first;
- `views`: D10's words: a private piece is "a private basic" for alerts and cards and its slot
  for the AI, never his label; the Privacy rows' words name no piece;
- `ops01`: Camera -> Wardrobe by behaviour (tests/fixtures/r13/d_dom.js, Node): a photo with a
  person, or with a face, keeps and sends nothing; so does a face that only the crop shows (the crop
  is checked itself at Save, REVIEW-D-1 H2); a clean photo saves exactly one crop of at most 512 px;
  a label read still makes its event with a person in view.

Negative control: the person check off (the scan module's `check()` ignores the person task):
the person case must then fail, so this part cannot pass whatever the scan module does.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from jarvis.offline import phrases_r13 as p13  # noqa: E402
from jarvis.offline import phrases_r14 as p14  # noqa: E402
from jarvis.offline.no_ai import run_no_ai  # noqa: E402
from jarvis.offline.rules import route_no_ai  # noqa: E402
from jarvis.tools.gateway import GatewayOutcome  # noqa: E402
from jarvis.wardrobe import redact  # noqa: E402
from jarvis.wardrobe.model import Piece  # noqa: E402
from jarvis.wardrobe.phone.privacy import privacy_rows  # noqa: E402

PART = "phone"
BUILT = True
NOW = datetime(2026, 11, 16, 23, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
DOM = ROOT / "tests" / "fixtures" / "r13" / "d_dom.js"
SCAN = ROOT / "src" / "jarvis" / "api" / "static" / "console-wardrobe-scan.js"
PERSON_CHECK = "person.data.found || "  # what the control takes away
NAVY, VEST = "wi_000000000003", "wi_000000000009"
SENTENCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("what should I wear tomorrow", ("outfit_suggest",)),
    ("where is my black belt", ("wardrobe_find", "belongings_where")),
    ("I put my watch in the travel bag", ("wardrobe_find", "wardrobe_edit")),
    ("my navy shirt is in the laundry", ("laundry_move",)),
    ("the white shirt is back", ("laundry_move",)),
    ("what's in the laundry", ("laundry_status",)),
    ("I'm wearing the blue shirt", ("wear_log",)),
    ("done for today", ("wear_log",)),
    ("how many socks are ready", ("wardrobe_count",)),
)


class RecordingGateway:
    """Runs nothing: records each call and answers 'executed' with a fixed line."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, call: Any, *, scope: str) -> Any:
        self.calls.append(call.name)
        return SimpleNamespace(
            outcome=GatewayOutcome.EXECUTED, result={"message": "ok"}, error=None, pending=None
        )


def _case(cid: str, failures: list[str]) -> dict[str, Any]:
    return {"id": f"{PART}:{cid}", "passed": not failures, "failures": failures}


async def _sentences() -> list[dict[str, Any]]:
    out = []
    for text, tools in SENTENCES:
        gw = RecordingGateway()
        got = await run_no_ai(gw, text, NOW, scope="owner:s1", extra=p13.ROUTERS)  # type: ignore[arg-type]
        bad = [] if tuple(gw.calls) == tools else [f"{text!r}: {gw.calls} != {list(tools)}"]
        if got.tool_calls != len(tools):
            bad.append(f"{text!r}: {got.tool_calls} calls")
        out.append(_case("sentence:" + text.replace(" ", "_")[:40], bad))
    return out


def _r14() -> dict[str, Any]:
    texts = [
        "where did I put my passport",
        "I kept the keys in the drawer",
        "where are my car keys",
        "where is my wife's watch",
        "where is my bag",
        "add milk to my grocery list",
        "what's on my shopping list",
        "is the house armed",
        "what time is it",
        "book a plumber for tomorrow morning",
    ]
    both = (*p13.ROUTERS, *p14.ROUTERS)
    bad = [t for t in texts if route_no_ai(t, NOW, both) != route_no_ai(t, NOW, p14.ROUTERS)]
    return _case("r14_phrases_unchanged", bad)


async def _views() -> dict[str, Any]:
    secret = "Grandpa's lucky vest"
    vest = Piece.model_validate(
        {"id": VEST, "category": "base", "type": "vest", "label": secret, "private": True}
    )
    bad = []
    if redact.alert_words(vest) != "a private basic" or secret in redact.card_words(vest, 7):
        bad.append("a private piece's alert or card words")
    if secret in json.dumps(redact.model_view(vest)):
        bad.append("a private piece's label reached the AI's view")
    rows = privacy_rows(lambda: ())
    words = " ".join([(await r.describe("owner-w")).what for r in rows])
    if secret in words or "Navy" in words:
        bad.append("the Privacy rows name a piece")
    return _case("d10_views", bad)


def _view() -> dict[str, Any]:
    from jarvis.wardrobe.http import Counts, LabelView, PieceView, WardrobeView

    navy = PieceView(
        id=NAVY, category="tops", type="shirt", label="Navy striped shirt", colour="navy",
        state="ready", state_words="Ready", eligible=True, label_code="abcdefgh",
    )  # fmt: skip
    vest = PieceView(
        id=VEST, category="base", type="vest", label="", colour="black", private=True,
        state="ready", state_words="Ready", eligible=True, label_code="qrstuvwx",
    )  # fmt: skip
    view = WardrobeView(
        ready="eval", rev=3, pieces=(navy, vest), counts=Counts(owned=2, ready=2, review=0,
        pairs_complete=0, pairs=0, sets_complete=0, sets=0),
        labels=(LabelView(code="abcdefgh", number=1, piece=NAVY),
                LabelView(code="qrstuvwx", number=2, piece=VEST)),
    )  # fmt: skip
    return view.model_dump(mode="json")


def _scan(steps: list[dict[str, Any]], source: str | None, **payload: Any) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        return {"error": "node is not installed"}
    body = {"view": _view(), "prints": [], "steps": steps, **payload}
    if source is not None:
        body["source"] = source
    run = subprocess.run(
        [node, str(DOM)], input=json.dumps(body), capture_output=True, text=True, timeout=60
    )
    try:
        out: dict[str, Any] = json.loads(run.stdout or "{}")
    except ValueError:
        return {"error": run.stderr[-500:]}
    return out


def _press(label: str) -> dict[str, str]:
    return {"op": "press", "label": label}


PHOTO = [_press("Start the camera"), _press("Take a photo")]
SAVE = "Save this photo with the piece (sealed; only you)"


def _sent(out: dict[str, Any]) -> list[str]:
    prints = [n for n in out.get("net", []) if n["path"] == "/v1/wardrobe/fingerprints"]
    return [d["fn"] for d in out.get("door", [])] + ["fingerprint" for n in prints if n["body"]]


def _ops01(source: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pick = _press("This one: Navy striped shirt (label read)")
    for who in ("person", "face"):
        got = _scan(
            [*PHOTO, pick, _press(SAVE)], source, vision={who: True, "codes": ["jw1:abcdefgh"]}
        )
        bad = [got["error"]] if "error" in got else [f"sent: {_sent(got)}"] if _sent(got) else []
        out.append(_case(f"ops01:{who}_keeps_and_sends_nothing", bad))
    got = _scan(
        [*PHOTO, pick, _press(SAVE)], source, vision={"crop_face": True, "codes": ["jw1:abcdefgh"]}
    )
    bad = [got["error"]] if "error" in got else [f"sent: {_sent(got)}"] if _sent(got) else []
    out.append(_case("ops01:a_face_only_the_crop_shows_keeps_and_sends_nothing", bad))
    got = _scan([*PHOTO, pick, _press(SAVE)], source, vision={"codes": ["jw1:abcdefgh"]})
    door = got.get("door", [])
    ok = len(door) == 1 and max(door[0]["w"], door[0]["h"]) <= 512
    out.append(_case("ops01:a_clean_photo_saves_one_crop", [] if ok else [f"door: {door}"]))
    got = _scan([*PHOTO, pick], source, vision={"person": True, "codes": ["jw1:abcdefgh"]})
    scans = [n for n in got.get("net", []) if n["path"] == "/v1/wardrobe/scan"]
    out.append(_case("ops01:a_label_read_still_makes_its_event", [] if scans else ["no event"]))
    return out


async def cases() -> list[dict[str, Any]]:
    return [*await _sentences(), _r14(), await _views(), *_ops01(None)]


async def control() -> dict[str, Any]:
    source = SCAN.read_text(encoding="utf-8")
    off = source.replace(PERSON_CHECK, "", 1)  # the person check off: only the face still refuses
    got = [*await _sentences(), _r14(), await _views(), *_ops01(off)]
    failed = [c["id"] for c in got if not c["passed"]]
    return {
        "name": "the person check off",
        "suite_failed": PERSON_CHECK in source
        and f"{PART}:ops01:person_keeps_and_sends_nothing" in failed,
        "failed_cases": failed,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(cases()), indent=1))
