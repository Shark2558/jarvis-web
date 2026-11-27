# tests/browser/r18_calls_stub.py -- R18 E: the Calls routes stubbed in the page (page.route and
# page.route_web_socket), as the other browser tests stub theirs (tests/browser/ui_checks.py). The
# shapes are I0's (jarvis.calls.models, jarvis.calls.protocol) and A1's views
# (jarvis.api.calls_handlers_cards: card_view, record_view, settings_view with the templates, the
# language rows, approve's needs_passkey); everything is made up: fake numbers (+91 90000 0000x),
# a "Laundry" contact, no real person. `CallsStub(page)` keeps the state the console changes
# (cards, records, settings) and every request and live message it sent, so a test can check
# what the console asked for.
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
APPROVAL_ID = "ap_test1"
SAVED = {"laundry": "+919000000001"}  # the saved contacts a card may name

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
SUMMARY = {
    "english": "The laundry will pick up tomorrow at 10:00. Nothing to pay now.",
    "agreed": ["Pickup on Sat 28 Nov at 10:00"],
    "next_steps": ["Keep the bag ready by 10:00"],
    "needs_owner": [],
    "message": None,
}
# record_view (the list) and, for get_record, the transcript and summary (A1's models, decrypted)
RECORDS: list[dict[str, Any]] = [
    {
        "id": "call_0000000000a1",
        "card_id": "cc_0000000000b1",
        "direction": "outgoing",
        "number_masked": "+91 …0001",
        "contact_name": "Laundry",
        "state": "ended",
        "end_reason": "done",
        "languages_used": ["ml-IN", "en-IN"],
        "started_at": TODAY,
        "ended_at": TODAY,
        "seconds": 192,
        "cost_inr": 1.2,
        "recorded": True,
        "objected": False,
        "has_audio": True,
        "has_transcript": True,
        "has_summary": True,
        "booking_added": True,
        "keep": False,
        "delete_after": "2026-12-27T08:35:00+00:00",
        "purpose": "Book a pickup for tomorrow morning",
        "transcript": {"lines": TRANSCRIPT},
        "summary": SUMMARY,
    },
    {
        "id": "call_0000000000a2",
        "card_id": "cc_0000000000b2",
        "direction": "outgoing",
        "number_masked": "+91 …0002",
        "contact_name": "",
        "state": "no_answer",
        "end_reason": "no_answer",
        "languages_used": ["en-IN"],
        "started_at": YESTERDAY,
        "ended_at": YESTERDAY,
        "seconds": 0,
        "cost_inr": 0,
        "recorded": True,
        "objected": False,
        "has_audio": False,
        "has_transcript": False,
        "has_summary": False,
        "booking_added": False,
        "keep": False,
        "delete_after": "2026-12-26T05:00:00+00:00",
        "purpose": "Ask about the parcel",
        "transcript": None,
        "summary": None,
    },
    {
        "id": "call_0000000000a3",
        "card_id": None,
        "direction": "incoming",
        "number_masked": "+91 …0003",
        "contact_name": "",
        "state": "ended",
        "end_reason": "hung_up",
        "languages_used": ["hi-IN"],
        "started_at": EARLIER,
        "ended_at": EARLIER,
        "seconds": 41,
        "cost_inr": 0.3,
        "recorded": False,
        "objected": True,
        "has_audio": False,
        "has_transcript": True,
        "has_summary": True,
        "booking_added": False,
        "keep": True,
        "delete_after": "2026-12-24T11:20:00+00:00",
        "purpose": "",
        "transcript": {
            "lines": [
                {
                    "who": "them",
                    "lang": "hi-IN",
                    "text": "कृपया वापस कॉल करें।",
                    "english": "Please call back.",
                }
            ]
        },
        "summary": {
            "english": "A caller left a message: please call back about the delivery.",
            "agreed": [],
            "next_steps": [],
            "needs_owner": ["Call back about the delivery"],
            "message": {"name": "Courier", "reason": "A delivery", "call_back": ""},
        },
    },
]
LIST_KEYS = ("transcript", "summary", "purpose")  # get_record only
# jarvis.calls.templates.catalogue()
TEMPLATES = [
    {
        "name": "laundry_pickup",
        "title": "Book a laundry pickup",
        "fields": [
            "contact",
            "give_name",
            "items",
            "languages",
            "max_minutes",
            "number",
            "windows",
        ],
    },
    {
        "name": "laundry_status",
        "title": "Ask about the laundry",
        "fields": [
            "contact",
            "give_name",
            "languages",
            "max_minutes",
            "number",
            "order",
            "windows",
        ],
    },
    {
        "name": "appointment",
        "title": "Book an appointment",
        "fields": [
            "contact",
            "duration_minutes",
            "give_name",
            "give_number",
            "languages",
            "max_minutes",
            "number",
            "place",
            "reason",
            "windows",
        ],
    },
]
WORDS = {
    "laundry_pickup": "Book a laundry pickup",
    "laundry_status": "Ask whether the laundry is ready and when it can be delivered",
}


def _result(lang: str, option: str, passed: bool, **kw: Any) -> dict[str, Any]:
    return {
        "lang": lang,
        "option": option,
        "checked_at": "2026-11-26T10:00:00+00:00",
        "passed": passed,
        "native_heard": kw.get("native", False),
        "needs_balanced": kw.get("balanced", False),
        "inr_per_minute": kw.get("inr", 0),
        "why_failed": kw.get("why", []),
    }


def _row(
    lang: str, name: str, offer: str | None, results: list[dict[str, Any]], inr: float | None = 0
) -> dict[str, Any]:
    return {
        "lang": lang,
        "name": name,
        "offered": offer is not None,
        "option": offer,
        "inr_per_minute": inr if offer else None,
        "results": results,
    }


# A1's languages(): every language, what is offered, and the check's results per option
LANGUAGES: dict[str, Any] = {
    "languages": [
        _row("en-IN", "English", "laptop", [_result("en-IN", "laptop", True, native=True)]),
        _row("as-IN", "Assamese", None, []),
        _row("hi-IN", "Hindi", "laptop", [_result("hi-IN", "laptop", True, native=True)]),
        _row(
            "kn-IN",
            "Kannada",
            "azure",
            [_result("kn-IN", "azure", True, balanced=True, inr=2.4)],
            2.4,
        ),
        _row(
            "ml-IN",
            "Malayalam",
            "google",
            [
                _result(
                    "ml-IN",
                    "laptop",
                    False,
                    why=["Speed: half the replies started after 2.1 s (needs 1.5 s)"],
                ),
                _result("ml-IN", "google", True),
            ],
        ),
        _row(
            "or-IN",
            "Odia",
            None,
            [
                _result(
                    "or-IN",
                    "azure",
                    False,
                    inr=None,
                    why=[
                        "Phone-line hearing: 78 % of key facts right (needs 90 %)",
                        "Character errors 21 % (needs 15 % or less)",
                    ],
                )
            ],
        ),
        _row("ta-IN", "Tamil", "google", [_result("ta-IN", "google", True, native=True)]),
    ],
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
    "updated_at": None,
}
RAISES = ("month_cap_inr", "call_cap_inr", "call_max_minutes")
# R18 review: what A1's settings_view adds beside the settings (jarvis.api.calls_handlers_cards)
LIMITS = {
    "calls_per_day": 10,
    "calls_per_number_per_day": 2,
    "new_numbers_per_day": 3,
    "no_answer_redials_per_day": 1,
    "quiet_from": "21:00",
    "quiet_until": "08:00",
    "quiet_zone": "IST",
}
CEILINGS = {
    "month_cap_inr": 3000,
    "call_cap_inr": 200,
    "call_max_minutes": 30,
    "retention_days": 30,
    "answer_rings": [2, 15],
}
PRICES = {"sarvam": {"hear_inr_per_minute": 0.5, "voice_inr_per_1k_chars": 3.0}}


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


def masked(e164: str) -> str:
    return f"+91 …{e164[-4:]}" if re.fullmatch(r"\+91[0-9]{10}", e164) else "…"


def card_view(body: dict[str, Any], cid: str, known: set[str]) -> dict[str, Any]:
    """A1's card_view for a draft: a PlaceArgs body, or {template, fields}."""
    tpl = body.get("template") if "fields" in body else None
    f = body.get("fields", body)
    number = f.get("number") or SAVED.get(str(f.get("contact", "")).lower(), "")
    booking = f.get("booking")
    if tpl and f.get("windows"):
        booking = {
            "windows": f["windows"],
            "give_name": f.get("give_name", ""),
            "give_number": f.get("give_number"),
            "reason": "Laundry pickup"
            if tpl == "laundry_pickup"
            else f.get("reason", "Laundry delivery"),
            "no_payment": True,
            "duration_minutes": f.get("duration_minutes", 30),
            "add_to_calendar": True,
        }
    return {
        "id": cid,
        "direction": "outgoing",
        "number_e164": number,
        "number": number,
        "number_masked": masked(number),
        "contact_name": f.get("contact", ""),
        "purpose": WORDS.get(tpl or "", f.get("purpose", "")),
        "may_say": [
            f"The pickup is for {f.get('give_name', '')}.",
            "The pickup address is the one the shop has on file.",
        ]
        if tpl == "laundry_pickup"
        else f.get("may_say", []),
        "may_agree": ["A pickup time inside the given windows."]
        if tpl == "laundry_pickup"
        else f.get("may_agree", []),
        "languages": f.get("languages", ["en-IN"]),
        "template": tpl or body.get("template"),
        "booking": booking,
        "limits": {"max_minutes": f.get("max_minutes", 6), "max_inr": 20},
        "estimate_inr": 1.35,
        "new_number": number not in known,
        "status": "draft",
        "created_at": TODAY,
        "language_names": [],
        "card_text": "",
        "needs_passkey": number not in known,
        "blocked": None,
        "estimate": {
            "total_inr": 1.35,
            "speech_inr": 0,
            "brain_inr": 1.2,
            "summary_inr": 0.15,
            "speech_free": True,
            "minutes": 6,
        },
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
        self.running = False
        self.templates = templates
        self.limits: dict[str, Any] | None = deepcopy(LIMITS)
        self.prices: dict[str, Any] = deepcopy(PRICES)
        self.desk_linked = True
        self.known = set(SAVED.values())
        self.cards: dict[str, dict[str, Any]] = {}
        self.sent: list[tuple[str, str, Any]] = []  # (method, path?query, body)
        self.live_in: list[Any] = []  # what the console sent on the live socket
        self.ws: Any = None
        self.ws_url = ""
        self.next_card = 1
        page.route(re.compile(r".*/v1/calls/.*"), self.handle)
        page.route(re.compile(r".*/v1/passkeys/challenge$"), self.challenge)
        page.route_web_socket(re.compile(r".*/v1/calls/call_[0-9a-f]{12}/live(\?.*)?$"), self.on_ws)

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

    def settings_view(self) -> dict[str, Any]:
        extra = {"limits": self.limits, "ceilings": CEILINGS, "prices": self.prices}
        return {**self.settings, "templates": TEMPLATES if self.templates else []} | extra

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
            return ok(self.status)
        if path == "/v1/calls/records":
            limit = int(q.get("limit", ["50"])[0])
            return ok(
                {
                    "records": [
                        {k: v for k, v in r.items() if k not in LIST_KEYS} for r in self.records
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
                        "seconds": 42,
                        "cost_inr": 0.4,
                        "transcript": None,
                        "summary": None,
                        "has_audio": False,
                        "booking_added": False,
                    }
                )
            if r is None:
                return ok({"error": "not_found", "detail": "There is no such call record."}, 404)
            if method == "DELETE" and not tail:
                self.records = [x for x in self.records if x["id"] != rid]
                return ok({"deleted": True, "id": rid})
            if tail == "/keep" and method == "PUT":
                r["keep"] = bool((body or {}).get("keep"))
                return ok({k: v for k, v in r.items() if k not in LIST_KEYS})
            if tail == "/audio":
                return route.fulfill(
                    status=200, body=wav_bytes(), headers={"content-type": "audio/wav"}
                )
            if tail == "/booking/undo" and method == "POST":
                return ok(
                    {
                        "status": "done",
                        "words": "The pickup was taken off your calendar.",
                        "approval_id": None,
                    }
                )
            return ok(r)
        if path == "/v1/calls/cards" and method == "POST":
            cid = f"cc_{self.next_card:012x}"
            self.next_card += 1
            b = {k: v for k, v in (body or {}).items() if k != "replaces"}
            if (body or {}).get("replaces") in self.cards:
                self.cards[body["replaces"]]["status"] = "cancelled"
            self.cards[cid] = card_view(b, cid, self.known)
            return ok(self.cards[cid])
        if card:
            cid, act = card.group(1), card.group(2)
            c = self.cards.get(cid) or card_view(
                {"purpose": "From the chat", "number": "+919000000004"}, cid, self.known
            )
            if act == "approve":
                b = body or {}
                if c["needs_passkey"] and "approval_id" not in b:
                    return ok(
                        {
                            "status": "needs_passkey",
                            "approval_id": APPROVAL_ID,
                            "card_text": "Call +91 …" + c["number"][-4:],
                        }
                    )
                if "approval_id" in b and not b.get("passkey"):
                    return ok(
                        {
                            "error": "invalid",
                            "detail": "Check the request: a passkey needs its approval_id",
                        },
                        422,
                    )
                self.cards[cid] = {**c, "status": "approved"}
                self.known.add(c["number"])
                self.status["active"] = {"call_id": LIVE_ID, "state": "preparing"}
                return ok({"status": "approved", "card_id": cid, "call_id": LIVE_ID})
            self.cards[cid] = {**c, "status": "cancelled"}
            return ok(self.cards[cid])
        if path == "/v1/calls/settings":
            if method == "PUT":
                b = dict(body or {})
                confirm = b.pop("confirm_raise", None) is True
                if not confirm and any(
                    k in b and int(b[k]) > int(self.settings[k]) for k in RAISES
                ):
                    return ok(
                        {
                            "error": "confirm_raise",
                            "detail": "This lets calls spend more. Confirm to change it.",
                        },
                        422,
                    )
                self.settings.update(b)
            return ok(self.settings_view())
        if path == "/v1/calls/languages":
            if self.running:
                for row in self.languages["languages"]:
                    if not row["results"]:
                        row["results"] = [{"lang": row["lang"], "option": "azure", "running": True}]
            return ok(self.languages)
        if path == "/v1/calls/languages/check":
            if (body or {}).get("confirm"):
                self.running = True
                return ok({"running": True}, 202)
            plan = {"total_inr": 0, "unknown_price": ["or-IN bhashini"], "pairs": []}
            return ok({"estimate_inr": 0, "languages": 3, "plan": plan})
        if path == "/v1/calls/languages/score" and method == "POST":  # R18 review: his scores
            b = dict(body or {})
            for row in self.languages["languages"]:
                for r in row["results"]:
                    if r["lang"] == b.get("lang") and r["option"] == b.get("option"):
                        r["native_heard"] = True
                        return ok({"result": r})
            return ok({"error": "not_checked", "detail": "Not checked yet."}, 404)
        if path == "/v1/calls/desk" and method == "DELETE":  # R18 review: Unlink
            was, self.desk_linked = self.desk_linked, False
            return ok({"unlinked": was})
        if re.fullmatch(r"/v1/calls/call_[0-9a-f]{12}/live/ticket", path) and method == "POST":
            return ok({"ticket": "lt_" + "t" * 32, "expires_in_s": 30})  # I1: the live ticket
        if path == "/v1/calls/desk/kit/info":  # I1: the call desk's kit (Settings)
            return ok({"sha256": "ab" * 32, "size": 4096, "version": "18.0.0"})
        if path == "/v1/calls/desk/code" and method == "POST":
            return ok({"code": "ABCD-EFGH", "expires_in_s": 600})
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
