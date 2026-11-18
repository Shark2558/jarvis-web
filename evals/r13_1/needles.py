# evals/r13_1/needles.py
"""R13.1 eval, I1's suite (`needles`, BUILT): a day of Try-on and See it on me through the REAL
app (`wired.py`), then every sink searched for every needle class (docs/plans/r13-1-try-on.md
"Tests and evals": needles).

Needle classes: his photo's bytes, a new garment photo's bytes, a picture's bytes (from Google),
his measurements (as numbers with their names, and in words), the consent text, a private
piece's label and colour, the fake bearer token, and the text part of Google's answer. Bytes are
searched raw, hex and base64 at every alignment; text raw, lower-cased, URL-encoded, hex and
base64.

Sinks: every document the app stores (plain fields and sealed blobs as stored), every log record,
the audit chain, alerts (what Telegram and Web Push both send), approval cards (words and stored
arguments), session turns, every tool result the model sees, R13's wardrobe backup file, the
Privacy export (every category, the unavailable list), the figure's own Privacy export, and every
request the adapter sent to Google. A positive control per sink proves the search finds a marker
planted there.

The allowed places: his photo and the garment photo in the request to Google (that is the
picture's whole point, after his YES and his ₹ confirm), his measurements in the figure's own
Privacy export (his data, his row: INTEGRATION-A 8.4, decided at review A-1), and a private
piece's label in R13's own export of his catalog (`wardrobe_pieces`, his records as R13 keeps
them). The adapter must receive exactly his photo, the garment and the chosen crop, under fixed
words.

Control (plan): the adapter logging its request body: the photo needles are found in the logs.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock
from urllib.parse import quote

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
for _p in (ROOT / "tests", ROOT / "src"):  # appended: never ahead of what is already imported
    if str(_p) not in sys.path:
        sys.path.append(str(_p))


def _wired() -> ModuleType:
    """`wired.py` by path under a unique name: no evals/r13_1 on sys.path."""
    found = sys.modules.get("r13_1_wired")
    if found is not None:
        return found
    spec = importlib.util.spec_from_file_location("r13_1_wired", HERE / "wired.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["r13_1_wired"] = module
    spec.loader.exec_module(module)
    return module


_W = _wired()
World, running, seed, want = _W.World, _W.running, _W.seed, _W.want
from r13_fakes_a import jpeg  # noqa: E402
from r131_fake_gemini import INSTRUCTION, TOKEN, picture_answer  # noqa: E402
from r131_fake_tryon import PNG  # noqa: E402

from jarvis.llm import tryon_gemini  # noqa: E402
from jarvis.llm.base import ToolCall  # noqa: E402
from jarvis.llm.tryon import FIXED_WORDS  # noqa: E402

PART = "needles"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]

HIS_PHOTO = b"QXHISPHOTOAA"
GARMENT = b"QXNEWSHIRTBB"
PICTURE = PNG + b"QXMADEPICTCC"  # what Google answers (its bytes end with the needle)
CROP = b"QXJEANSCROPDD"
PRIVATE = "QXPRIVLABELEE"
BODY = {"height": 187, "shoulders": 47, "chest": 103, "waist": 89, "hips": 107, "inseam": 83}
CONSENT = "it may log requests to check for abuse"
MARKER = "QXMARKERZZ"
TEXTS: dict[str, tuple[str, ...]] = {
    "consent_text": (CONSENT,),
    "private_label": (PRIVATE, "maroon", json.dumps([110, 30, 40])),
    "token": (TOKEN,),
    "answer_text": (INSTRUCTION,),
    "measurements": tuple(
        f for m, v in BODY.items() for f in (f'"{m}": {v}', f'"{m}":{v}', f"{m}={v}", f"{v} cm")
    ),
}
BYTES: dict[str, bytes] = {"his_photo": HIS_PHOTO, "garment_photo": GARMENT,
                           "picture": b"QXMADEPICTCC"}  # fmt: skip
ALLOWED: dict[str, frozenset[str]] = {
    "his_photo": frozenset({"google"}),
    "garment_photo": frozenset({"google"}),
    "measurements": frozenset({"privacy_export_figure"}),
    "private_label": frozenset({"privacy_export_pieces"}),  # R13's own export of his catalog
}
SINKS = ("documents", "logs", "audit", "alerts", "approval_words", "approval_args", "sessions",
         "tool_results", "backup", "privacy_export", "privacy_export_pieces",
         "privacy_export_figure", "google")  # fmt: skip


def _text_forms(needle: str) -> set[str]:
    raw = needle.encode()
    return {needle, needle.lower(), quote(needle, safe=""), raw.hex(),
            base64.b64encode(raw).decode().rstrip("=")}  # fmt: skip


def _byte_forms(raw: bytes) -> set[str]:
    """Raw (latin-1), hex, and base64 at each of the three alignments inside a longer blob."""
    out = {raw.decode("latin-1"), raw.hex(), raw.hex().upper()}
    for k in range(3):
        enc = base64.b64encode(b"\x00" * k + raw).decode()
        out.add(enc[(8 * k + 5) // 6 : -2])
        out.add(base64.urlsafe_b64encode(b"\x00" * k + raw).decode()[(8 * k + 5) // 6 : -2])
    return out


def found_text(text: str, needle: str) -> bool:
    low = text.lower()
    return any(f in text or f.lower() in low for f in _text_forms(needle))


def found_bytes(text: str, raw: bytes) -> bool:
    return any(f in text for f in _byte_forms(raw))


async def _day(w: World) -> dict[str, str]:
    """A day of Try-on and See it on me; every sink as text."""
    ids = await seed(w)
    (ids["mine"],) = await w.add({"type": "shirt", "label": PRIVATE, "colour": "maroon"})
    await w.ok("wardrobe_edit", piece=ids["mine"], private=True)  # its label kept sealed
    (ids["jeans"],) = await w.add({"type": "jeans", "label": "Blue jeans", "colour": "blue"})
    got = await w.crop(ids["jeans"], "front", jpeg(extra=CROP))
    w.planted.append(("a crop", got.status_code == 200))
    await _figure(w, ids)
    with w.signed_in():
        await _seeme(w)
    await _chat(w)
    for job in w.app.state.r13_parts["seeme"].daily_jobs:
        await job.run([w.uid])
    return await _sinks(w)


async def _figure(w: World, ids: dict[str, str]) -> None:
    got = await w.send("PUT", "/v1/tryon/body", json=BODY)
    w.planted.append(("his measurements", got.status_code == 200))
    await w.send("POST", "/v1/tryon/body/use")
    plan = (await w.ok("outfit_plan", action="save", day="tomorrow", occasion="meeting",
                       start="10:00", end="12:00"))["plan"]["id"]  # fmt: skip
    look = await w.get(f"/v1/tryon/look?plan={plan}&private=1")
    slots = [{"slot": s["slot"], "piece": s["piece"]} for s in look["slots"]
             if s.get("piece") and not s.get("private")]  # fmt: skip
    await w.send("POST", "/v1/tryon/saved", json={"looks": [{"slots": slots}]})
    await w.send("POST", "/v1/tryon/confirm", json={"plan": plan, "slots": slots})
    await w.get("/v1/tryon")
    await w.ok("outfit_suggest", day="tomorrow")
    await w.ok("laundry_move", step="basket", pieces=[ids["belt"]])  # he is told: an alert
    w.clock.advance(minutes=6)
    for job in w.app.state.r13_parts["styling"].clock_jobs:
        await job.run([w.uid])
    (twin,) = await w.add({"type": "shirt", "label": "White formal shirt", "colour": "white"})
    await w.call("wardrobe_merge", keep=ids["shirt"], merge=twin)  # a card left waiting


async def _seeme(w: World) -> None:
    head = {"Content-Type": "image/jpeg"}
    got = await w.send("POST", "/v1/seeme/photo", content=jpeg(600, 1200, extra=HIS_PHOTO),
                       headers=head)  # fmt: skip
    w.planted.append(("his photo", got.status_code == 200))
    version = (await w.get("/v1/seeme"))["consent"]["version"]
    await w.send("POST", "/v1/seeme/consent", json={"typed": "YES", "template_version": version})
    got = await w.send("POST", "/v1/seeme/garments?type=shirt&colour=navy",
                       content=jpeg(600, 800, extra=GARMENT), headers=head)  # fmt: skip
    w.planted.append(("the garment photo", got.status_code == 200))
    garment = got.json().get("id", "")
    sent = [p["piece"] for p in (await w.get(f"/v1/seeme/pair?garment={garment}"))["pieces"]]
    est = await w.get(f"/v1/seeme/estimate?garment={garment}&pieces={','.join(sent)}")
    body = {"garment": garment, "pieces": sent, "confirm_cost": True,
            "inr_shown": est["typical_inr"], "request_id": "tq_" + "2" * 16}  # fmt: skip
    got = await w.send("POST", "/v1/seeme/pictures", json=body)
    w.planted.append(("a picture made", got.status_code == 200))
    await w.send("GET", f"/v1/seeme/pictures/{got.json().get('id')}")
    await w.get("/v1/seeme")


async def _chat(w: World) -> None:
    call = ToolCall(id="n1", name="outfit_suggest", arguments={"day": "tomorrow"})
    w.brain.script_tool_calls([call], "Here is tomorrow's look.")
    await w.chat("What should I wear tomorrow?")


async def _privacy(w: World) -> tuple[str, str, str]:
    """(every category but two, R13's own catalog export, the figure's own export)."""
    svc = w.app.state.privacy
    every = await svc.export_all(w.uid, proof=None, fresh_left_s=60)
    figure = every["categories"].pop("tryon_figure", None)
    pieces = every["categories"].pop("wardrobe_pieces", None)
    one = await svc.export(w.uid, "tryon_figure", proof=None, fresh_left_s=60)
    dump = lambda v: json.dumps(v, default=str)  # noqa: E731
    return dump(every), dump(pieces), dump([figure, one])


async def _sinks(w: World) -> dict[str, str]:
    gw = w.app.state.gateway
    entries = (await gw.audit.tail(100_000)).entries
    cards = await gw.gate.pending()
    store = w.app.state.store
    sessions = []
    for summary in await store.list_for_user(w.uid, 100):
        got = await store.get(summary.id)
        sessions.append(got.model_dump_json() if got is not None else "")
    backup = await w.send("GET", "/v1/wardrobe/backup")
    rest, pieces, figure = await _privacy(w)
    return {
        "documents": "\n".join(json.dumps(d, default=str) for d in w.docs._data.values()),
        "logs": "\n".join(w.log.lines),
        "audit": "\n".join(e.model_dump_json() for e in entries),
        "alerts": "\n".join(f"{k} {m}" for k, m in w.alerts.sent),
        "approval_words": "\n".join(f"{c.summary} {c.tool}" for c in cards),
        "approval_args": "\n".join(json.dumps(c.arguments, default=str) for c in cards),
        "sessions": "\n".join(sessions),
        "tool_results": "\n".join(json.dumps(r, default=str) for r in w.results),
        "backup": backup.content.decode("latin-1"),
        "privacy_export": rest,
        "privacy_export_pieces": pieces,
        "privacy_export_figure": figure,
        "google": "\n".join(r.content.decode("latin-1") for r in w.google.seen),
    }


_EVIDENCE: list[dict[str, str]] = []  # one day per run (`_run` clears it)
_PLANTED: list[tuple[str, bool]] = []
_SENT: list[list[dict[str, Any]]] = []  # each request's parts, as the adapter sent them


async def _evidence() -> dict[str, str]:
    if not _EVIDENCE:
        async with running(answers=[picture_answer(PICTURE, text=INSTRUCTION)]) as w:
            _EVIDENCE.append(await _day(w))
            _PLANTED[:] = w.planted
            _SENT[:] = [w.google.body(n)["contents"][0]["parts"] for n in range(len(w.google.seen))]
            heads = [r.headers.get("authorization", "") for r in w.google.seen]
            _PLANTED.append(("the token reached Google only", heads == [f"Bearer {TOKEN}"]))
    return _EVIDENCE[0]


def _class_case(name: str) -> Case:
    async def case() -> list[str]:
        sinks = await _evidence()
        out = []
        for sink, text in sinks.items():
            if sink in ALLOWED.get(name, frozenset()):
                continue
            if name in BYTES:
                out += want(not found_bytes(text, BYTES[name]), f"{name} found in {sink}")
            else:
                out += [f"{name} found in {sink}" for n in TEXTS[name] if found_text(text, n)]
        return out

    return case


def _sink_case(sink: str) -> Case:
    async def case() -> list[str]:  # a positive control: the search finds a marker planted here
        sinks = await _evidence()
        text = sinks[sink] + "\n" + MARKER
        return want(bool(sinks[sink].strip()), f"the {sink} sink is empty: nothing looked at") + (
            want(found_text(text, MARKER), f"the {sink} search is blind")
        )

    return case


async def _planted_all() -> list[str]:
    """Every plant got in as meant, and each allowed needle IS where it is allowed (a needle
    that never got in would pass every class case without testing anything)."""
    sinks = await _evidence()
    out = [f"{n} was not accepted as planted" for n, ok in _PLANTED if not ok]
    out += want(found_bytes(sinks["google"], HIS_PHOTO), "his photo never reached the adapter")
    out += want(found_bytes(sinks["google"], GARMENT), "the garment never reached the adapter")
    out += want(found_text(sinks["privacy_export_figure"], '"height": 187'), "no figure export")
    return out


async def _google_got_only_what_was_sent() -> list[str]:
    await _evidence()
    out = want(len(_SENT) == 1, f"one request to Google: {len(_SENT)}")
    for parts in _SENT:
        images = [base64.b64decode(p["inlineData"]["data"]) for p in parts if "inlineData" in p]
        texts = [p["text"] for p in parts if "text" in p]
        marks = [m for img in images for m in (HIS_PHOTO, GARMENT, CROP) if m in img]
        out += want(
            marks == [HIS_PHOTO, GARMENT, CROP], f"his photo, the garment, the crop: {marks}"
        )
        out += want(len(images) == 3, f"nothing else sent: {len(images)} images")
        words = [w for t in texts for w in ("navy shirt", "blue jeans") if w in t]
        out += want(len(texts) == 1 and len(words) == 2, f"one fixed text part: {texts}")
        out += want(all("QX" not in t for t in texts), "no label in the words sent")
        out += want(FIXED_WORDS.fullmatch("navy shirt") is not None, "fixed words only")
    return out


CASES: dict[str, Case] = {f"needle_{c}": _class_case(c) for c in (*BYTES, *TEXTS)}
CASES["planted_all"] = _planted_all
CASES["google_got_only_what_was_sent"] = _google_got_only_what_was_sent
CASES |= {f"sink_{s}": _sink_case(s) for s in SINKS}


async def _run(names: list[str] | None = None) -> list[dict[str, Any]]:
    _EVIDENCE.clear()
    out = []
    for name, case in CASES.items():
        if names is not None and name not in names:
            continue
        try:
            failures = await case()
        except Exception as exc:  # noqa: BLE001 - a case that breaks is a failed case
            failures = [f"raised {type(exc).__name__}: {str(exc)[:200]}"]
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run()


def _logging_adapter() -> Any:
    """The adapter logging its request body (the plan's control)."""
    real = tryon_gemini.GeminiTryOn._post

    async def post(self: Any, url: str, body: dict[str, Any], timeout_s: float) -> Any:
        tryon_gemini.log.info("try-on: request", extra={"body": json.dumps(body)})
        return await real(self, url, body, timeout_s)

    return mock.patch.object(tryon_gemini.GeminiTryOn, "_post", post)


async def control() -> dict[str, Any]:
    with _logging_adapter():
        got = await _run()
    failed = [r["id"] for r in got if not r["passed"]]
    must = {f"{PART}:needle_his_photo", f"{PART}:needle_garment_photo"}
    return {
        "name": "the adapter logging its request body",
        "suite_failed": must <= set(failed),
        "failed_cases": failed,
    }


__all__ = ["BUILT", "CASES", "PART", "cases", "control"]
