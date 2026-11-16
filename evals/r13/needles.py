# evals/r13/needles.py
"""R13 eval, I1's suite (`needles`, BUILT): one simulated week of the four parts through the REAL
app (`wired.py`), then every sink searched for every needle class (docs/plans/r13-wardrobe.md
"Needles").

Needle classes: a private piece's label, his free-text label, a laundry shop's label, a planted
phone number, raw OCR text, a foreign QR payload, photo bytes, a fingerprint. (A calendar title
needs a Google read and is held by Part C's own tests, `test_r13_c_calendar`; the backup's
plaintext is searched as the file's own sink.) Each needle is searched raw, lower-cased,
URL-encoded, hex and base64.

Sinks: every document the app stores (unsealed fields and sealed blobs alike), every log record,
the audit chain, alerts (what Telegram and Web Push both send), the approval cards' words and
their stored arguments, the conversation a panel card waits in, every tool result the model sees,
and the backup file. A positive control per sink proves the search finds a marker planted there.

The ONE allowed place (D10): a card's stored arguments from a `query` he typed (R2's precedent for
Things' put); his own words in tool results are fenced and allowed for his free and shop labels.
Control: `redact.py`'s model view swapped for the panel view: exactly the private-label case
(its tool-results sink) fails.
"""

from __future__ import annotations

import base64
import json
import sys
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
from r13_fakes_a import fp, jpeg  # noqa: E402
from wired import World, running, want  # noqa: E402

PART = "needles"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]

PRIVATE = "QXPRIVLABELAA"
FREE = "QXFREELABELBB"
SHOP = "QXSHOPLABELCC"
PHONE = "9876501234"
OCR = "QXOCRTEXTDD"
FOREIGN = "QXFORE12"
PHOTO = b"QXPHOTOBYTESEE"
PRINT = fp(7)
MARKER = "QXMARKERZZ"
# class -> the needle texts; allowed sinks per class (D10's one place and his own fenced words)
NEEDLES: dict[str, tuple[str, ...]] = {
    "private_label": (PRIVATE,),
    "free_label": (FREE,),
    "shop_label": (SHOP,),
    "phone": (PHONE,),
    "ocr_text": (OCR,),
    "foreign_qr": (FOREIGN,),
    "photo_bytes": (PHOTO.decode(),),
    "fingerprint": (PRINT,),
}
ALLOWED: dict[str, frozenset[str]] = {
    "free_label": frozenset({"tool_results", "approval_args"}),  # fenced; D10's query
    "shop_label": frozenset({"tool_results"}),
}
SINKS = ("documents", "logs", "audit", "alerts", "approval_words", "approval_args", "sessions",
         "tool_results", "backup")  # fmt: skip


def _forms(needle: str) -> set[str]:
    raw = needle.encode()
    return {
        needle,
        needle.lower(),
        quote(needle, safe=""),
        raw.hex(),
        base64.b64encode(raw).decode().rstrip("="),
        base64.urlsafe_b64encode(raw).decode().rstrip("="),
    }


def found(text: str, needle: str) -> bool:
    low = text.lower()
    return any(f in text or f.lower() in low for f in _forms(needle))


async def _week(w: World) -> dict[str, str]:
    """One simulated week; every sink as text."""
    priv, shirt, spare = await _pieces(w)
    await _scans(w, priv, shirt)
    await _laundry(w, priv, shirt)
    await _styling(w, shirt, spare)
    await _cards(w, priv, shirt)
    return await _sinks(w)


async def _pieces(w: World) -> list[str]:
    made = await w.ok(
        "wardrobe_add",
        pieces=[
            {"type": "underpants", "label": PRIVATE},
            {"type": "shirt", "label": FREE, "colour": "white"},
            {"type": "trousers", "label": "Grey trousers"},
        ],
    )
    return list(made["ids"])


async def _scans(w: World, priv: str, shirt: str) -> None:
    head = {"Content-Type": "image/jpeg"}
    await w.send("POST", f"/v1/wardrobe/photos?piece={shirt}&view=front",
                 content=jpeg(extra=PHOTO), headers=head)  # fmt: skip
    sent = {"piece": shirt, "view": "front", "model": "mnv2-int8-1", "v": PRINT}
    await w.send("POST", "/v1/wardrobe/fingerprints", json=sent)
    w.clock.advance(hours=1)
    note = f"label reads {OCR} call {PHONE}"[:120]
    body = {"events": [{"client_id": "needle-0001", "piece": shirt, "kind": "seen", "note": note}]}
    await w.send("POST", "/v1/wardrobe/scan", json=body)
    await w.send("POST", "/v1/wardrobe/labels", json={"code": f"jw1:{FOREIGN}", "piece": shirt})
    await w.send("GET", "/v1/wardrobe/labels.svg?sheet=1")


async def _laundry(w: World, priv: str, shirt: str) -> None:
    w.clock.advance(days=1)
    await w.ok("laundry_move", step="basket", pieces=[priv, shirt])
    due = (w.clock() - timedelta(days=2)).date().isoformat()
    await w.call("laundry_send_out", action="send", pieces=[shirt], shop=f"{SHOP} {PHONE}",
                 due=due)  # refused: a shop's label can't hold a phone number  # fmt: skip
    await w.ok("laundry_send_out", action="send", pieces=[shirt], shop=SHOP, due=due)
    await w.ok("laundry_status")
    await w.get("/v1/laundry")
    await w.get("/v1/laundry/review")
    laundry = w.app.state.r13_parts["laundry"]
    for job in laundry.daily_jobs:
        await job.run([w.uid])


async def _styling(w: World, shirt: str, spare: str) -> None:
    w.clock.advance(days=1)
    await w.ok("outfit_suggest", day="tomorrow")
    await w.ok("outfit_plan", action="save", day="tomorrow", occasion="meeting", start="10:00",
               end="12:00")  # fmt: skip
    await w.ok("laundry_move", step="basket", pieces=[spare])
    w.clock.advance(minutes=6)
    await w.get("/v1/outfits")
    for job in w.app.state.r13_parts["styling"].clock_jobs:
        await job.run([w.uid])


async def _cards(w: World, priv: str, shirt: str) -> None:
    w.clock.advance(days=1)
    await w.ok("wardrobe_retire", piece=priv, action="archive")
    other = (await w.ok("wardrobe_add", pieces=[{"type": "shirt", "label": f"{FREE} twin"}]))["ids"]
    await w.call("wardrobe_merge", keep=shirt, merge=other[0])  # a card left waiting
    await w.ok("wardrobe_remove", piece=other[0])  # the bin: a fixed title
    await w.call("laundry_move", spoken=True, step="basket", query=FREE)  # D10's one place
    twin = (await w.ok("wardrobe_add", pieces=[{"type": "shirt", "label": FREE}]))["ids"][0]
    await w.send(
        "POST",
        "/v1/wardrobe/tools/wardrobe_merge",
        json={"arguments": {"keep": shirt, "merge": twin}},
    )  # waits in a conversation
    await w.ok("wardrobe_find", query="trousers")


async def _sinks(w: World) -> dict[str, str]:
    gw = w.app.state.gateway
    docs = [json.dumps(d, default=str) for d in w.docs._data.values()]
    entries = (await gw.audit.tail(100_000)).entries
    cards = await gw.gate.pending()
    store = w.app.state.store
    sessions = []
    for summary in await store.list_for_user(w.uid, 100):
        got = await store.get(summary.id)
        sessions.append(got.model_dump_json() if got is not None else "")
    backup = await w.send("GET", "/v1/wardrobe/backup")
    return {
        "documents": "\n".join(docs),
        "logs": "\n".join(w.log.lines),
        "audit": "\n".join(e.model_dump_json() for e in entries),
        "alerts": "\n".join(f"{k} {m}" for k, m in w.alerts.sent),
        "approval_words": "\n".join(f"{c.summary} {c.tool}" for c in cards),
        "approval_args": "\n".join(json.dumps(c.arguments, default=str) for c in cards),
        "sessions": "\n".join(sessions),
        "tool_results": "\n".join(json.dumps(r, default=str) for r in w.results),
        "backup": backup.content.decode("latin-1"),
    }


_EVIDENCE: list[dict[str, str]] = []  # one week per run (`_run` clears it)


async def _evidence() -> dict[str, str]:
    if not _EVIDENCE:
        async with running() as w:
            _EVIDENCE.append(await _week(w))
    return _EVIDENCE[0]


def _class_case(name: str) -> Case:
    async def case() -> list[str]:
        sinks = await _evidence()
        out = []
        for sink, text in sinks.items():
            if sink in ALLOWED.get(name, frozenset()):
                continue
            out += [f"{name} found in {sink}" for n in NEEDLES[name] if found(text, n)]
        return out

    return case


def _sink_case(sink: str) -> Case:
    async def case() -> list[str]:  # a positive control: the search finds a marker planted here
        sinks = await _evidence()
        text = sinks[sink] + "\n" + MARKER
        return want(
            bool(sinks[sink].strip()), f"the {sink} sink is empty: nothing was looked at"
        ) + want(
            found(text, MARKER) and found(quote(MARKER), MARKER), f"the {sink} search is blind"
        )

    return case


CASES: dict[str, Case] = {f"needle_{c}": _class_case(c) for c in NEEDLES}
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


def _panel_view() -> Any:
    """`redact.py`'s model view swapped for the panel view (the piece's whole record)."""
    panel = lambda piece, place_label=None: piece.to_json()  # noqa: E731
    stack = ExitStack()
    for target in (
        "jarvis.wardrobe.catalog.tools.model_view",
        "jarvis.wardrobe.laundry.cards.model_view",
        "jarvis.wardrobe.laundry.history.model_view",
    ):
        stack.enter_context(mock.patch(target, panel))
    return stack


async def control() -> dict[str, Any]:
    with _panel_view():
        got = await _run()
    failed = [r["id"] for r in got if not r["passed"]]
    want_failed = {f"{PART}:needle_private_label"}
    return {
        "name": "the model's view swapped for the panel view",
        "suite_failed": set(failed) == want_failed,
        "failed_cases": failed,
    }


__all__ = ["BUILT", "CASES", "PART", "cases", "control"]
