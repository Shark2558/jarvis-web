# evals/r7/needles.py
"""R7 eval, I1 (`needles`, BUILT): after a day of every part on fakes, nothing private is written
down where it must not be (docs/plans/r7-mobile.md "Tests and evals per part", the needles row).

The day runs through the REAL app (`create_app`, Part C's door, Parts A, B and D's routes and
services, the real wiring) on in-memory fakes: the owner signs in with Google, links a phone, sets
up two SOS contacts who join; the phone says hello, sends a day of watch data (heart rate 43, 87,
179) and a test SOS with its place; the console sends a test SOS with its place, keeps a camera
result (text read off a label), and a picture is shared into the share target with no worker;
the brief is made; the R7 tools answer (`watch_today`, `sleep_last_night`, `sos_status`,
`vision_results`). Then every document (and its address), log line, request address (the fake
Cloud Run request log, and every Telegram call's address), audit entry, Activity row, alert text
(what the owner gets on Telegram and in his browser), the brief and every tool result outside its
fence is scanned for:

    coordinates   the SOS place in every form a pair is written (micro-degrees, degrees, a link)
    heart         a heart-rate value beside its name ("min": 43, 87 average, ...)
    numbers       an SOS contact's phone number
    read_text     the words read off the label
    pixels        the shared picture's planted pixel pattern

Allowed, by design, and not scanned: the request BODIES sent to Telegram for the contacts (the map
link and the pin), the reply to the owner's own requests (his SOS's SMS text, the phone's hello
with the numbers for its offline SMS screen, his kept results) and `watch_today`'s own answer of
his heart rate to him (its job; never on Telegram without his switch). The `day` case proves each
step really happened (a scan of nothing proves nothing).

Negative controls (each must make the suite fail):
  seal_off                 a kept camera day and a watch day are written in the clear
                           (`VisionStore._seal`, `WatchStore._seal`)
  fence_off                `vision_results` hands read text to the model unfenced
  coordinate_in_address    the console's SOS also carries its place in the request's address
"""

from __future__ import annotations

import base64
import json
import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "src", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import httpx  # noqa: E402
import r7_fakes_d as D  # noqa: E402
from pydantic import SecretStr  # noqa: E402
from r7_fakes_b import LABEL_TEXT, text_result  # noqa: E402
from r7_fakes_c import CSRF, HELLO, browser, door, linked_phone, owner_uid, phone_app  # noqa: E402

import jarvis.vision.tools as vision_tools  # noqa: E402
import jarvis.watch.store as watch_store  # noqa: E402
from jarvis.config import LLMBackend, SessionBackend, Settings  # noqa: E402
from jarvis.llm.base import ToolCall  # noqa: E402
from jarvis.tools.external import FENCE_PREFIX  # noqa: E402
from jarvis.vision.store import VisionStore  # noqa: E402
from jarvis.watch.store import StoredDay, WatchStore  # noqa: E402

PART = "needles"
BUILT = True
CONTROLS = ("seal_off", "fence_off", "coordinate_in_address")
KINDS = ("coordinates", "heart", "numbers", "read_text", "pixels")
KEY = SecretStr(base64.urlsafe_b64encode(bytes(range(201, 233))).decode())  # for this eval only
HEART = {"min": 43, "avg": 87, "max": 179}
HEART_RE = re.compile(
    r'"(?:min|avg|max)"\s*:\s*(?:43|87|179)\b|\b(?:43|87|179)\s*(?:bpm|lowest|average|highest)\b',
    re.I,
)
NUMBERS = [D.ASHA[1], D.RAVI[1], D.ASHA[1].lstrip("+"), D.RAVI[1].lstrip("+")]
READ = ["NET WT 500 g", "BEST BEFORE 12 2027", "MRP Rs 125.00"]
PIXELS = b"PIXEL-PATTERN-R7-NEEDLE-\x13\x37\xc0\xff\xee"
PIXEL_NEEDLES = ["PIXEL-PATTERN-R7-NEEDLE", base64.b64encode(PIXELS).decode()[:24]]
FENCED = re.compile(re.escape(FENCE_PREFIX) + r".*?<<END [0-9a-f]+>>", re.S)
IST = "+05:30"
_STD = set(vars(logging.LogRecord("x", 0, "", 0, "", None, None)))


class Seen:
    """What the day wrote down, by where it was written (a plain class: run.py loads this file
    under its own name, outside sys.modules, where a dataclass can't resolve its annotations)."""

    def __init__(self) -> None:
        self.channels: dict[str, list[str]] = {}
        self.steps: dict[str, bool] = {}

    def add(self, where: str, *texts: Any) -> None:
        self.channels.setdefault(where, []).extend(
            t if isinstance(t, str) else json.dumps(t, default=str, ensure_ascii=False)
            for t in texts
        )

    def text(self, *, skip: tuple[str, ...] = ()) -> str:
        return "\n".join(t for k, v in self.channels.items() if k not in skip for t in v)


class _Logs(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.rows: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        extra = {k: v for k, v in vars(record).items() if k not in _STD}
        self.rows.append(f"{record.getMessage()} {json.dumps(extra, default=str)}")


@contextmanager
def _recording(seen: Seen) -> Iterator[_Logs]:
    """Every log record and every request address (the app's and Telegram's) of the day."""
    logs, root, real = _Logs(), logging.getLogger(), httpx.AsyncClient.send

    async def send(self: httpx.AsyncClient, request: httpx.Request, **kw: Any) -> httpx.Response:
        seen.add("addresses", str(request.url))
        return await real(self, request, **kw)

    root.addHandler(logs)
    httpx.AsyncClient.send = send  # type: ignore[method-assign]
    try:
        yield logs
    finally:
        httpx.AsyncClient.send = real  # type: ignore[method-assign]
        root.removeHandler(logs)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
        user_timezone="Asia/Kolkata",
    )


def _place() -> dict[str, int]:
    return {"lat_e6": D.LAT_E6, "lon_e6": D.LON_E6, "accuracy_m": 20, "age_s": 0}


def _health() -> dict[str, Any]:
    day = {
        "date": "2026-11-13",
        "steps": {"count": 6012, "writer": "com.noisefit"},
        "heart": {**HEART, "writer": "com.noisefit"},
        "sleep": [
            {
                "start": f"2026-11-12T23:40:00{IST}",
                "end": f"2026-11-13T06:20:00{IST}",
                "writer": "com.noisefit",
                "stages": None,
            }
        ],
    }
    return {"v": 1, "days": [day]}


def _clear_seal(self: VisionStore, uid: str, day: str, items: list[dict[str, Any]]) -> str:
    return json.dumps({"day": day, "items": items})  # the control: a kept day in the clear


def _clear_open(self: VisionStore, uid: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = json.loads(doc["blob"])["items"]
    return loaded


def _watch_clear_seal(self: WatchStore, uid: str, d: date, day: StoredDay) -> dict[str, Any]:
    plain = day.model_dump_json(exclude_none=False)  # the control: a watch day in the clear
    head = {"uid": uid, "date": d.isoformat(), "v": watch_store.VERSION, "kid": watch_store.KEY_ID}
    return {
        **head,
        "clear": json.loads(plain),
        "blob": plain,
        "updated_at": self._now().isoformat(),
    }


def _watch_clear_open(self: WatchStore, uid: str, d: date, doc: dict[str, Any]) -> StoredDay:
    return StoredDay.model_validate_json(str(doc["blob"]))


@contextmanager
def _controls(active: frozenset[str]) -> Iterator[None]:
    swaps: list[tuple[Any, str, Any]] = []
    if "seal_off" in active:
        swaps += [(VisionStore, "_seal", _clear_seal), (VisionStore, "_open", _clear_open)]
        swaps += [
            (WatchStore, "_seal", _watch_clear_seal),
            (WatchStore, "_open", _watch_clear_open),
        ]
    if "fence_off" in active:
        swaps.append((vision_tools, "wrap_external", lambda text, source="": text))
    saved = [(owner, name, getattr(owner, name)) for owner, name, _ in swaps]
    for owner, name, value in swaps:
        setattr(owner, name, value)
    try:
        yield
    finally:
        for owner, name, value in saved:
            setattr(owner, name, value)


async def _contacts(app: Any, c: httpx.AsyncClient, bot: D.PinBot, seen: Seen) -> None:
    sos = app.state.r7_parts["body"].services["sos"]
    sos._telegram = lambda: bot.client()  # noqa: SLF001 - the contacts' Telegram, faked
    r = await c.put("/v1/sos/label", json={"label": "Kiran Example"}, headers=CSRF)
    joined = r.status_code == 200
    for label, phone, tg in (D.ASHA, D.RAVI):
        r = await c.post("/v1/sos/contacts", json={"label": label, "phone": phone}, headers=CSRF)
        cid = r.json()["contact"]["id"]
        link = (await c.post(f"/v1/sos/contacts/{cid}/link", json={}, headers=CSRF)).json()
        word = str(link["link"]).split("start=", 1)[1]
        joined = joined and await sos.join(word, tg_user_id=tg, chat_id=tg) is not None
    seen.steps["two contacts joined"] = joined


async def _phone(app: Any, c: httpx.AsyncClient, seen: Seen) -> None:
    device, key = await linked_phone(app, c)
    hello = await door(app, key, device, "hello", HELLO)
    seen.steps["hello carried the numbers"] = D.ASHA[1] in hello.text  # the reply: allowed
    health = await door(app, key, device, "health", _health())
    seen.steps["the watch day was kept"] = health.status_code == 200
    app.state.phone_clock.advance(2)
    at = int(app.state.phone_clock())
    sos = {"v": 1, "kind": "test", "at": at, "location": _place()}
    r = await door(app, key, device, "sos", sos)
    seen.steps["the phone's test SOS was sent"] = r.status_code == 200 and r.json()["sent"]


async def _console(app: Any, c: httpx.AsyncClient, active: frozenset[str], seen: Seen) -> None:
    lat, lon = D.LAT_E6 / 1e6, D.LON_E6 / 1e6
    where = f"?lat={lat:.6f}&lon={lon:.6f}" if "coordinate_in_address" in active else ""
    body = {"kind": "test", "location": _place()}
    r = await c.post("/v1/sos/send" + where, json=body, headers=CSRF)
    seen.steps["the console's test SOS was sent"] = r.status_code == 200 and r.json()["sent"]
    seen.steps["its reply carried the SMS text"] = "maps.google.com" in r.text  # allowed
    r = await c.post("/v1/vision/results", json=text_result(), headers=CSRF)
    seen.steps["a camera result was kept"] = r.status_code in (200, 201)
    files = {"files": ("shelf.jpg", b"\xff\xd8\xff\xe0" + PIXELS + b"\xff\xd9", "image/jpeg")}
    r = await c.post("/app/share/in", files=files, data={"title": "", "text": ""})
    seen.steps["the share target took no picture"] = r.status_code < 500
    r = await c.post("/v1/brief/generate", json={"force": True}, headers=CSRF)
    today = (await c.get("/v1/brief/today")).json()
    seen.steps["the brief was made"] = r.status_code == 200 and bool(today.get("brief"))
    seen.add("brief", (today.get("brief") or {}).get("text", ""), today.get("brief") or {})


async def _tools(app: Any, seen: Seen) -> None:
    """The R7 reads, each through the gateway (its policy, its audit line, its Activity row)."""
    parts, gw = app.state.r7_parts, app.state.gateway
    for tool in (*parts["body"].tools, *parts["vision"].tools):
        if gw.registry.get(tool.name) is None:
            gw.registry.register(tool)
    ran = []
    for name in ("watch_today", "sleep_last_night", "sos_status", "vision_results"):
        call = ToolCall(id=f"call_{name}", name=name, arguments={})
        got = await gw.execute(call, scope=owner_uid())
        ran.append(got.outcome.value == "executed")
        text = json.dumps(got.result, default=str, ensure_ascii=False)
        if name == "vision_results":
            seen.steps["the tool fenced the read text"] = LABEL_TEXT[:12] in text
        seen.add("watch_today" if name == "watch_today" else "tools", FENCED.sub("", text))
    seen.steps["the four R7 reads ran through the gateway"] = all(ran)


def _documents(app: Any, seen: Seen) -> None:
    docs = app.state.r7_parts["phone"].services["phone"].store.docs._data  # noqa: SLF001
    for path, doc in docs.items():
        seen.add("documents", path, doc)
        seen.add("documents_plain", {k: v for k, v in doc.items() if k != "blob"})


async def day(active: frozenset[str] = frozenset()) -> Seen:
    seen = Seen()
    bot = D.PinBot()
    with _controls(active), _recording(seen) as logs:
        async with phone_app(_settings(), token_key=KEY) as app:
            logging.getLogger().addHandler(logs)  # the app's start set the root handlers afresh
            async with browser(app) as c:
                await _contacts(app, c, bot, seen)
                await _phone(app, c, seen)
                await _console(app, c, active, seen)
                await _tools(app, seen)
                rows = (await c.get("/v1/activity")).json()
                seen.add("activity", rows)
                seen.steps["Activity has the day's rows"] = len(rows.get("items") or []) >= 4
            _documents(app, seen)
            seen.add("audit", *(e.model_dump_json() for e in app.state.gateway.audit._entries))
            alerts = [m for _, _, m in app.state.notify.sent]
            seen.add("alerts", *alerts)
            seen.steps["the owner was told of each SOS"] = sum("SOS" in a for a in alerts) >= 2
    seen.add("logs", *logs.rows)
    said = "\n".join(logs.rows)
    seen.steps["the day's log lines were read"] = "SOS finished" in said and "watch days" in said
    contacts = {D.ASHA[2], D.RAVI[2]}
    pins = [p for p in bot.of("sendLocation") if p.get("chat_id") in contacts]
    seen.steps["the contacts got their pin on Telegram"] = len(pins) >= 4  # allowed: bodies
    return seen


def _found(seen: Seen) -> dict[str, list[str]]:
    everything = seen.text(skip=("documents_plain", "watch_today"))
    no_blobs = seen.text(skip=("documents", "watch_today"))
    found = {
        "coordinates": [n for n in D.needles() if n in everything],
        "heart": sorted(set(HEART_RE.findall(no_blobs))),
        "numbers": [n for n in NUMBERS if n in everything],
        "read_text": [n for n in READ if n in everything],
        "pixels": [n for n in PIXEL_NEEDLES if n in everything],
    }
    watch_answer = seen.text(skip=tuple(k for k in seen.channels if k != "watch_today"))
    found["coordinates"] += [f"{n} in watch_today" for n in D.needles() if n in watch_answer]
    return found


def _where(seen: Seen, needle: str) -> list[str]:
    return [k for k, v in seen.channels.items() if any(needle in t for t in v)]


async def _cases(active: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    seen = await day(active)
    missing = [step for step, ok in seen.steps.items() if not ok]
    out = [{"id": f"{PART}:day", "passed": not missing, "failures": missing}]
    for kind, hits in _found(seen).items():
        failures = [f"{h} written in {', '.join(_where(seen, h)) or 'a record'}" for h in hits]
        out.append({"id": f"{PART}:{kind}", "passed": not hits, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    got = await _cases()
    print(f"{PART}: {len(got)} cases; negative controls: {', '.join(CONTROLS)}")
    return got


async def control() -> dict[str, Any]:
    failed: dict[str, list[str]] = {}
    for name in CONTROLS:
        failed[name] = [c["id"] for c in await _cases(frozenset({name})) if not c["passed"]]
    return {
        "name": f"{PART}: " + " + ".join(CONTROLS),
        "suite_failed": all(failed.values()),
        "failed_cases": failed,
    }
