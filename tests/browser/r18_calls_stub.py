# tests/browser/r18_calls_stub.py -- R18 E: the Calls routes stubbed in the page (page.route and
# page.route_web_socket), as the other browser tests stub theirs (tests/browser/ui_checks.py). The
# shapes are I0's (jarvis.calls.models, jarvis.calls.protocol); everything is made up: fake numbers
# (+91 90000 0000x), a "Laundry" contact, no real person. `CallsStub(page)` keeps the state the
# console changes (cards, records, settings) and every request and live message it sent, so a test
# can check what the console asked for.
# ruff: noqa: E501 -- the stubbed views, one record or result a line
from __future__ import annotations

import io
import json
import math
import re
import struct
import wave
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qs, urlsplit

TODAY = "2026-11-27T08:35:00+00:00"  # 14:05 IST
YESTERDAY = "2026-11-26T05:00:00+00:00"
EARLIER = "2026-11-24T11:20:00+00:00"
LIVE_ID = "call_0000000000c1"
CARD_ID = "cc_0000000000d1"

STATUS: dict[str, Any] = {
    "desk": {
        "connected": True,
        "ready": True,
        "problems": [],
        "bt_headset": False,
        "cable": True,
        "phone_link": True,
    },
    "phone": {"linked": True},
    "month": {"used_inr": 12.4, "cap_inr": 200},
    "today": {"calls": 1, "max": 10},
    "active": None,
}
TRANSCRIPT = [
    {
        "who": "jarvis",
        "lang": "ml-IN",
        "text": "നമസ്കാരം, ഇത് JARVIS ആണ്.",
        "english": "Hello, this is JARVIS, an AI assistant calling on behalf of Arun. This call is recorded.",
    },
    {
        "who": "them",
        "lang": "ml-IN",
        "text": "നാളെ പത്തു മണിക്ക് വരാം.",
        "english": "We can come tomorrow at ten.",
    },
    {
        "who": "jarvis",
        "lang": "ml-IN",
        "text": "ശരി, നാളെ പത്തു മണി.",
        "english": "Right: tomorrow at ten.",
    },
]
RECORDS: list[dict[str, Any]] = [
    {
        "id": "call_0000000000a1",
        "card_id": "cc_0000000000b1",
        "direction": "outgoing",
        "number_last4": "0001",
        "contact_name": "Laundry",
        "state": "ended",
        "end_reason": "done",
        "languages_used": ["ml-IN", "en-IN"],
        "started_at": TODAY,
        "seconds": 192,
        "cost_inr": 1.2,
        "purpose": "Book a pickup for tomorrow morning",
        "summary": "The laundry will pick up tomorrow at 10:00. Nothing to pay now.",
        "transcript": TRANSCRIPT,
        "recorded": True,
        "objected": False,
        "has_audio": True,
        "keep": False,
        "delete_after": "2026-12-27T08:35:00+00:00",
        "booking_event": {"title": "Laundry pickup", "when": "Sat 28 Nov, 10:00", "undone": False},
    },
    {
        "id": "call_0000000000a2",
        "card_id": "cc_0000000000b2",
        "direction": "outgoing",
        "number_last4": "0002",
        "contact_name": "",
        "state": "no_answer",
        "end_reason": "no_answer",
        "languages_used": ["en-IN"],
        "started_at": YESTERDAY,
        "seconds": 0,
        "cost_inr": 0,
        "purpose": "Ask about the parcel",
        "summary": "",
        "transcript": [],
        "recorded": True,
        "objected": False,
        "has_audio": False,
        "keep": False,
        "delete_after": "2026-12-26T05:00:00+00:00",
    },
    {
        "id": "call_0000000000a3",
        "card_id": None,
        "direction": "incoming",
        "number_last4": "0003",
        "contact_name": "",
        "state": "ended",
        "end_reason": "hung_up",
        "languages_used": ["hi-IN"],
        "started_at": EARLIER,
        "seconds": 41,
        "cost_inr": 0.3,
        "purpose": "",
        "summary": "A caller left a message: please call back about the delivery.",
        "transcript": [
            {
                "who": "them",
                "lang": "hi-IN",
                "text": "कृपया वापस कॉल करें।",
                "english": "Please call back.",
            }
        ],
        "recorded": False,
        "objected": True,
        "has_audio": False,
        "keep": True,
        "delete_after": "",
    },
]
TEMPLATES = [
    {
        "id": "laundry_pickup",
        "title": "Laundry: book a pickup",
        "contact_name": "Laundry",
        "number_last4": "0001",
        "purpose": "Book a laundry pickup",
        "may_say": ["The pickup address on file"],
        "may_agree": ["A pickup inside the times below"],
        "languages": ["ml-IN", "en-IN"],
        "booking": {
            "windows": [{"day": "2026-11-28", "start": "10:00", "end": "12:00"}],
            "give_name": "Arun",
            "reason": "Laundry pickup",
            "duration_minutes": 30,
            "add_to_calendar": True,
        },
        "limits": {"max_minutes": 5},
    },
    {
        "id": "laundry_ready",
        "title": "Laundry: is it ready?",
        "contact_name": "Laundry",
        "number_last4": "0001",
        "purpose": "Ask whether the laundry is ready",
        "may_say": [],
        "may_agree": [],
        "languages": ["ml-IN", "en-IN"],
        "limits": {"max_minutes": 3},
    },
    {
        "id": "laundry_deliver",
        "title": "Laundry: deliver it back",
        "contact_name": "Laundry",
        "number_last4": "0001",
        "purpose": "Ask them to deliver the clean laundry",
        "may_say": ["The delivery address on file"],
        "may_agree": ["A delivery inside the times below"],
        "languages": ["ml-IN", "en-IN"],
        "booking": {
            "windows": [{"day": "2026-11-29", "start": "17:00", "end": "19:00"}],
            "give_name": "Arun",
            "reason": "Laundry delivery",
            "duration_minutes": 15,
            "add_to_calendar": True,
        },
        "limits": {"max_minutes": 4},
    },
]
LANGUAGES: dict[str, Any] = {
    "results": [
        {
            "lang": "en-IN",
            "option": "laptop",
            "checked_at": "2026-11-26T10:00:00+00:00",
            "passed": True,
            "native_heard": True,
            "inr_per_minute": 0,
        },
        {
            "lang": "ml-IN",
            "option": "laptop",
            "checked_at": "2026-11-26T10:00:00+00:00",
            "passed": False,
            "why_failed": ["Speed: half the replies started after 2.1 s (needs 1.5 s)"],
            "inr_per_minute": 0,
        },
        {
            "lang": "ml-IN",
            "option": "google",
            "checked_at": "2026-11-26T10:05:00+00:00",
            "passed": True,
            "native_heard": False,
            "inr_per_minute": 0,
        },
        {
            "lang": "hi-IN",
            "option": "laptop",
            "checked_at": "2026-11-26T10:10:00+00:00",
            "passed": True,
            "native_heard": True,
            "inr_per_minute": 0,
        },
        {
            "lang": "ta-IN",
            "option": "google",
            "checked_at": "2026-11-26T10:15:00+00:00",
            "passed": True,
            "native_heard": True,
            "inr_per_minute": 0,
        },
        {
            "lang": "kn-IN",
            "option": "azure",
            "checked_at": "2026-11-26T10:20:00+00:00",
            "passed": True,
            "native_heard": False,
            "needs_balanced": True,
            "inr_per_minute": 2.4,
        },
        {
            "lang": "or-IN",
            "option": "azure",
            "checked_at": "2026-11-26T10:25:00+00:00",
            "passed": False,
            "why_failed": [
                "Phone-line hearing: 78 % of key facts right (needs 90 %)",
                "Character errors 21 % (needs 15 % or less)",
            ],
        },
    ],
    "check": {"running": False},
}
SETTINGS: dict[str, Any] = {
    "month_cap_inr": 200,
    "call_cap_inr": 20,
    "call_max_minutes": 6,
    "default_languages": ["en-IN", "ml-IN"],
    "answering_on": False,
    "answer_after_rings": 5,
    "answer_policy": "all",
    "retention_days": 30,
    "record_audio": True,
    "allow_balanced": False,
    "sarvam_on": False,
    "owner_first_name": "Arun",
    "azure_status": "not_set",
}


def wav_bytes(seconds: float = 2.0, rate: int = 16000) -> bytes:
    """A quiet 440 Hz tone as a 16 kHz mono WAV (a stand-in recording)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        w.writeframes(
            b"".join(
                struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / rate)))
                for i in range(n)
            )
        )
    return buf.getvalue()


def pcm_message(frames: int = 5) -> bytes:
    """One live audio message: 0x03 and `frames` 20 ms frames of PCM16 (640 bytes each)."""
    return b"\x03" + b"\x10\x00" * (320 * frames)


def card_from(body: dict[str, Any], cid: str, known: bool) -> dict[str, Any]:
    number = str(body.get("number") or "")
    last4 = re.sub(r"\D", "", number)[-4:] or "0001"
    tpl = next((t for t in TEMPLATES if t["id"] == body.get("template")), None)
    return {
        "id": cid,
        "status": "draft",
        "number_last4": last4,
        "contact_name": body.get("contact_name") or (tpl or {}).get("contact_name", ""),
        "purpose": body.get("purpose", ""),
        "may_say": body.get("may_say", []),
        "may_agree": body.get("may_agree", []),
        "languages": body.get("languages", ["en-IN"]),
        "template": body.get("template"),
        "booking": body.get("booking"),
        "limits": {"max_minutes": (body.get("limits") or {}).get("max_minutes", 6), "max_inr": 20},
        "estimate_inr": 1.35,
        "new_number": not known,
        "ready": {"ok": True, "problems": []},
    }


class CallsStub:
    """The Calls routes for one page: state, a request log, and the live socket."""

    def __init__(
        self, page: Any, *, status: dict[str, Any] | None = None, templates: bool = True
    ) -> None:
        self.status = deepcopy(status or STATUS)
        self.records = deepcopy(RECORDS)
        self.settings = deepcopy(SETTINGS)
        self.languages = deepcopy(LANGUAGES)
        self.templates = templates
        self.cards: dict[str, dict[str, Any]] = {}
        self.sent: list[tuple[str, str, Any]] = []  # (method, path?query, body)
        self.live_in: list[Any] = []  # what the console sent on the live socket
        self.ws: Any = None
        self.ws_url = ""
        self.next_card = 1
        page.route(re.compile(r".*/v1/calls/.*"), self.handle)
        page.route(re.compile(r".*/v1/passkeys/challenge$"), self.challenge)
        page.route_web_socket(re.compile(r".*/v1/calls/call_[0-9a-f]{12}/live$"), self.on_ws)

    # ---- REST -------------------------------------------------------------------------------
    def challenge(self, route: Any) -> None:
        self.sent.append((route.request.method, "/v1/passkeys/challenge", self._body(route)))
        route.fulfill(
            json={
                "challenge_id": "pc_test1",
                "public_key": {
                    "challenge": "AAAA",
                    "rpId": "127.0.0.1",
                    "timeout": 60000,
                    "allowCredentials": [],
                },
            }
        )

    @staticmethod
    def _body(route: Any) -> Any:
        raw = route.request.post_data
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    def calls(self, method: str, part: str) -> list[tuple[str, str, Any]]:
        return [s for s in self.sent if s[0] == method and part in s[1]]

    def handle(self, route: Any) -> None:  # noqa: C901 -- one switch over the stubbed routes
        req = route.request
        u = urlsplit(req.url)
        path, method, body = u.path, req.method, self._body(route)
        self.sent.append((method, path + ("?" + u.query if u.query else ""), body))
        q = parse_qs(u.query)

        def ok(data: Any, status: int = 200) -> None:
            route.fulfill(status=status, json=data)

        rec = re.fullmatch(r"/v1/calls/records/(call_[0-9a-f]{12})(/[a-z/-]+)?", path)
        card = re.fullmatch(r"/v1/calls/cards/(cc_[0-9a-f]{12})/(approve|cancel)", path)
        if path == "/v1/calls/status":
            return ok({**self.status, "templates": TEMPLATES if self.templates else []})
        if path == "/v1/calls/records":
            limit = int(q.get("limit", ["50"])[0])
            return ok(
                {
                    "records": [
                        {k: v for k, v in r.items() if k != "transcript"} for r in self.records
                    ][:limit]
                }
            )
        if rec:
            rid, tail = rec.group(1), rec.group(2) or ""
            r = next((x for x in self.records if x["id"] == rid), None)
            if r is None and rid == LIVE_ID and not tail:  # the call that is on: its record so far
                return ok(
                    {
                        **RECORDS[0],
                        "id": LIVE_ID,
                        "state": "talking",
                        "end_reason": None,
                        "started_at": "2026-11-27T08:59:00+00:00",
                        "seconds": 42,
                        "cost_inr": 0.4,
                        "summary": "",
                        "transcript": [],
                        "has_audio": False,
                    }
                )
            if r is None:
                return ok({"error": "not_found", "detail": "No such call."}, 404)
            if method == "DELETE" and not tail:
                self.records = [x for x in self.records if x["id"] != rid]
                return ok({"deleted": True})
            if tail == "/keep" and method == "PUT":
                r["keep"] = bool((body or {}).get("keep"))
                return ok(r)
            if tail == "/audio":
                return route.fulfill(
                    status=200, body=wav_bytes(), headers={"content-type": "audio/wav"}
                )
            if tail == "/booking/undo" and method == "POST":
                r["booking_event"]["undone"] = True
                return ok({"undone": True})
            return ok(r)
        if path == "/v1/calls/cards" and method == "POST":
            cid = f"cc_{self.next_card:012x}"
            self.next_card += 1
            known = not (body or {}).get("number")  # a template's saved number: called before
            self.cards[cid] = card_from(body or {}, cid, known)
            return ok({"card": self.cards[cid]})
        if card:
            cid, act = card.group(1), card.group(2)
            c = self.cards.get(cid) or {**card_from({"purpose": "From the chat"}, cid, True)}
            if act == "approve":
                if c.get("new_number") and not (body or {}).get("passkey"):
                    return ok(
                        {"error": "passkey_required", "detail": "This number needs your passkey."},
                        403,
                    )
                c = {**c, "status": "approved", "call_id": LIVE_ID}
                self.cards[cid] = c
                self.status["active"] = {"call_id": LIVE_ID, "state": "preparing"}
                return ok({"card": c, "call_id": LIVE_ID})
            c = {**c, "status": "cancelled"}
            self.cards[cid] = c
            return ok({"card": c})
        if path == "/v1/calls/settings":
            if method == "PUT":
                self.settings.update(body or {})
            return ok(self.settings)
        if path == "/v1/calls/languages":
            return ok(self.languages)
        if path == "/v1/calls/languages/check":
            if (body or {}).get("confirm"):
                self.languages["check"]["running"] = True
                return ok({"running": True}, 202)
            return ok({"estimate_inr": 0, "languages": 3})
        return ok({"error": "not_found", "detail": "Not Found"}, 404)

    # ---- the live socket --------------------------------------------------------------------
    def on_ws(self, ws: Any) -> None:
        self.ws, self.ws_url = ws, ws.url
        ws.on_message(lambda m: self.live_in.append(json.loads(m) if isinstance(m, str) else m))
        self.state("talking", lang="ml-IN", seconds=42, cost=0.4)
        for line in TRANSCRIPT[:2]:
            self.caption(**line)

    def state(self, state: str, **kw: Any) -> None:
        msg = {
            "type": "state",
            "call_id": LIVE_ID,
            "state": state,
            "lang": kw.get("lang"),
            "seconds": kw.get("seconds", 0),
            "cost_inr": kw.get("cost", 0),
            "listening": kw.get("listening", False),
            "taken_over": kw.get("taken", False),
            "recording": kw.get("recording", True),
            "end_reason": kw.get("end"),
        }
        self.ws.send(json.dumps(msg))

    def caption(self, who: str, lang: str, text: str, english: str) -> None:
        self.ws.send(
            json.dumps(
                {"type": "caption", "who": who, "lang": lang, "text": text, "english": english}
            )
        )

    def audio(self, n: int = 3) -> None:
        for _ in range(n):
            self.ws.send(pcm_message())

    def types_in(self) -> list[str]:
        return [m.get("type", "") for m in self.live_in if isinstance(m, dict)]
