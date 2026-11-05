# evals/r2_needles/run.py
"""R2 I1 eval -- the cross-cutting needle scan (plan docs/plans/r2-memory-vault.md "Evals ->
r2_needles"). Nothing R2 keeps may leak through a side door.

    python evals/r2_needles/run.py --mock

One world over ONE in-memory Docs port with the real keyring, the real vault (its PDF text read by
the app's sandboxed `DocumentService.extract`), notes, things, Recently deleted, the gateway as the
app builds it (Activity recorder, Telegram rules), and a Brain with a private brain and a training
brain (scripted mock models). Seeded with marked needles: a full driving-licence number inside a
vault PDF, a marker inside the PDF's bytes, a place where something is kept, a note.

22 scripted conversations: typed (7, one the positive control: the place IS in that model request,
so the scan can see), voice (5, one a spoken note that waits as a card), Telegram with the switch
off (4), a training brain on a session that read the place (2), offline (1: no R2 tool is ever
offered), a brief day (3: the reminder alert, the Documents section and the brief's Gmail copy).
Then the scans: every Firestore document, every log record, every audit entry, every Activity row
and every stored conversation turn.

Asserted: the full number never appears in any document, log record, audit entry or model request;
the file bytes never in a model request or any document (the chunks are encrypted); no needle in a
training-brain request, a Telegram turn with the switch off, an Activity row, an alert, the brief
section or its Gmail copy. Negative control (must make the suite FAIL): `Tool.activity_words`
ignored (the cards' own text reaches Activity).

Documented limit (plan D13, review S4): the gateway keeps waiting approval cards the way the app
does (`DocApprovalStore`, Firestore documents under `jarvis_approvals/`), and a card keeps its
arguments as written, not JARVIS-encrypted, until the owner decides (he must see what he
approves). Those card documents are the ONLY ones allowed to hold a note's or a place's words
(never the full number or the file bytes); every other document stays needle-free.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import dataclasses
import datetime as dt
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import SecretStr

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from r1d_common import TIERS, finish  # noqa: E402

from jarvis.activity.store import ActivityStore  # noqa: E402
from jarvis.alerts import AlertKind, AlertResult  # noqa: E402
from jarvis.belongings.service import BelongingsService  # noqa: E402
from jarvis.belongings.store import BelongingsStore  # noqa: E402
from jarvis.brief.models import BriefData  # noqa: E402
from jarvis.brief.render import inbox_text, render_text  # noqa: E402
from jarvis.brief.vault_due import VaultDueBrief  # noqa: E402
from jarvis.config import LLMBackend, get_settings  # noqa: E402
from jarvis.core.brain import Brain  # noqa: E402
from jarvis.core.channel import telegram_turn  # noqa: E402
from jarvis.core.models import ChatRequest  # noqa: E402
from jarvis.documents.service import DocumentService  # noqa: E402
from jarvis.documents.store import AttachmentStore  # noqa: E402
from jarvis.kb.service import NotesService  # noqa: E402
from jarvis.kb.store import NotesStore  # noqa: E402
from jarvis.keyring import Keyring  # noqa: E402
from jarvis.llm.base import ToolCall  # noqa: E402
from jarvis.llm.brains import BrainRegistry, BrainSpec  # noqa: E402
from jarvis.llm.fallback import OFFLINE_TOOLS  # noqa: E402
from jarvis.llm.mock_provider import MockProvider  # noqa: E402
from jarvis.logging import configure_logging  # noqa: E402
from jarvis.memory.inmemory import InMemorySessionStore  # noqa: E402
from jarvis.storage.approvals import DocApprovalStore  # noqa: E402
from jarvis.storage.docs import MemoryDocs  # noqa: E402
from jarvis.telegram.rules import wrap_rules  # noqa: E402
from jarvis.telegram.store import TelegramStore  # noqa: E402
from jarvis.tools.gateway import Gateway  # noqa: E402
from jarvis.tools.setup import attach_activity, build_gateway  # noqa: E402
from jarvis.undo.service import UndoBin  # noqa: E402
from jarvis.undo.store import DeletedStore  # noqa: E402
from jarvis.vault.build import VaultStack, build_vault  # noqa: E402

UID = "owner"
ROOT_KEY = bytes(range(1, 33))
NOW = dt.datetime(2026, 11, 5, 5, 0, tzinfo=dt.UTC)  # 10:30 IST, after the 09:00 reminder time
FULL_ID = "KL0120110098765"  # a full driving-licence number (state code + 13 digits)
FILE_MARK = "FILEBYTES-NEEDLE-7a91c3"  # inside the PDF's bytes (a comment), never its text
PLACE = "behind the teak almirah zq7"
PLACE_2 = "in the steel trunk qx4"
NOTE = "the plumber Ravi zq-note-55 comes on Tuesdays"
VOICE_NOTE = "the gas man Suresh zq-voice-77 reads the meter"  # a spoken note: a waiting card
NEEDLES = (FULL_ID, FILE_MARK, PLACE, PLACE_2, NOTE, VOICE_NOTE)
# Review S4 / plan D13 (documented limit): a waiting card keeps its arguments as written (not
# JARVIS-encrypted) until the owner decides, so these documents alone may hold a note's words.
APPROVALS = "jarvis_approvals/"
R2_TOOLS = (
    "vault_list",
    "vault_expiring",
    "vault_set_dates",
    "kb_search",
    "kb_read",
    "kb_add_note",
    "kb_save_link",
    "kb_update",
    "kb_remove",
    "belongings_where",
    "belongings_list",
    "belongings_history",
    "belongings_put",
    "belongings_remove",
)
Check = Callable[["World"], Awaitable[list[str]]]


def pdf_with_text(lines: list[str], comment: str) -> bytes:
    """A one-page text PDF written by hand (no dependency), with a comment line in its bytes."""

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    body = "BT /F1 11 Tf 40 800 Td 14 TL\n" + "\n".join(f"({esc(x)}) '" for x in lines) + "\nET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(body)} >>\nstream\n{body}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n%" + comment.encode() + b"\n"
    offsets = []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class Alerts:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, uid: str, text: str, *, kind: AlertKind) -> AlertResult:
        self.sent.append((kind, text))
        return AlertResult(True)


class Logs(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(json.dumps(record.__dict__, default=str))


@dataclasses.dataclass
class World:
    docs: MemoryDocs
    vault: VaultStack
    notes: NotesService
    things: BelongingsService
    gateway: Gateway
    brain: Brain
    private: MockProvider
    training: MockProvider
    sessions: InMemorySessionStore
    alerts: Alerts
    logs: Logs
    tg: TelegramStore
    item_id: str = ""
    note_id: str = ""
    marks: dict[str, str] = dataclasses.field(default_factory=dict)
    offered: set[str] = dataclasses.field(default_factory=set)


def _settings() -> Any:
    key = SecretStr(base64.b64encode(ROOT_KEY).decode())
    return get_settings().model_copy(
        update={"llm_backend": LLMBackend.MOCK, "tools_enabled": True, "token_key": key}
    )


async def build_world(*, ignore_activity_words: bool = False) -> World:
    s = _settings()
    docs, ring, alerts = MemoryDocs(), Keyring(ROOT_KEY), Alerts()
    undo = UndoBin(DeletedStore(docs), clock=lambda: NOW)
    documents = DocumentService(AttachmentStore(docs))
    vault = build_vault(
        s, docs, extract=documents.extract, undo=undo, alerts=alerts, clock=lambda: NOW
    )
    assert vault is not None
    notes = NotesService(NotesStore(docs, ring), web=None, undo=undo)
    things = BelongingsService(BelongingsStore(docs, ring), undo)
    gw = build_gateway(
        s,
        approvals=DocApprovalStore(docs),  # review S4: cards in Firestore, as the app keeps them
        undo=undo,
        docs=docs,
        vault=vault.service,
        notes=notes,
        belongings=things,
    )
    if ignore_activity_words:  # the negative control
        for name in R2_TOOLS:
            tool = gw.registry.get(name)
            if tool is not None:
                gw.registry._tools[name] = dataclasses.replace(tool, activity_words=None)  # type: ignore[attr-defined]
    tg = TelegramStore(docs)
    code, _ = await tg.start_pairing(UID)
    await tg.finish_pairing(code, tg_user_id=111, chat_id=222)
    gw.rules = wrap_rules(None, tg)  # both Telegram switches off
    attach_activity(gw, ActivityStore(docs), s)
    private, training = MockProvider(), MockProvider()
    brains = BrainRegistry(
        [
            BrainSpec("private", "Claude", private, TIERS),
            BrainSpec("training", "Gemini (free)", training, TIERS, trains_on_content=True),
        ],
        default_id="private",
    )
    sessions = InMemorySessionStore()
    brain = Brain(brains=brains, store=sessions, settings=s, gateway=gw)
    logs = Logs()
    logging.getLogger().addHandler(logs)
    logging.getLogger("jarvis").setLevel(logging.DEBUG)
    w = World(docs, vault, notes, things, gw, brain, private, training, sessions, alerts, logs, tg)
    await _seed(w)
    return w


async def _seed(w: World) -> None:
    pdf = pdf_with_text(
        [
            "Union of India  Driving Licence",
            f"DL No: {FULL_ID}",
            "Date of Issue: 12/03/2011",
            "Valid Till: 25/11/2026",
        ],
        FILE_MARK,
    )
    got = await w.vault.service.intake(UID, pdf, source="upload")
    assert got.item_id is not None, got
    w.item_id = got.item_id
    await w.vault.service.update(
        UID,
        w.item_id,
        {"type": "driving_licence", "last4": "8765", "expires_on": "2026-11-25", "confirm": True},
    )
    n = await w.notes.add(UID, kind="note", text=NOTE, origin="typed")
    w.note_id = n.id
    await w.things.put(UID, "passport", PLACE, origin="typed")


def _request_text(w: World, p: MockProvider, start: int) -> str:
    """Everything the turn's model requests carried; the tool names offered go to `w.offered`."""
    out, w.offered = [], set()
    for c in p.calls[start:]:
        out.append(c.system)
        out += [json.dumps(m.model_dump(mode="json"), default=str) for m in c.messages]
        w.offered |= {t.name for t in c.tools or []}
    return "\n".join(out)


async def _turn(
    w: World,
    text: str,
    calls: list[dict[str, Any]],
    reply: str,
    *,
    channel: str = "text",
    brain: str | None = None,
    session_id: str | None = None,
) -> tuple[str, Any]:
    """One conversation turn; returns (what every model request of the turn contained, reply)."""
    p = w.training if brain == "training" else w.private
    p.scripted.clear()  # a turn that failed early never shifts the next one's script
    start = len(p.calls)
    calls = [  # "@note": the seeded note's id, known only once seeded
        {**c, "arguments": {k: w.note_id if v == "@note" else v for k, v in c["arguments"].items()}}
        for c in calls
    ]
    if calls:
        p.script_tool_calls([ToolCall(id=f"c{start}_{i}", **c) for i, c in enumerate(calls)], reply)
    else:
        p.script(reply)
    req = ChatRequest(
        message=text,
        user_id=UID,
        channel=channel,  # type: ignore[arg-type]
        brain=brain,
        session_id=session_id,
    )
    if channel == "telegram":
        with telegram_turn():
            res = await w.brain.chat(req)
    else:
        res = await w.brain.chat(req)
    return _request_text(w, p, start), res


def _absent(where: str, text: str, needles: tuple[str, ...]) -> list[str]:
    return [f"{n!r} in {where}" for n in needles if n in text]


CASES: list[tuple[str, Check]] = []


def case(name: str) -> Callable[[Check], Check]:
    def deco(fn: Check) -> Check:
        CASES.append((name, fn))
        return fn

    return deco


def _typed(name: str, tool: str, args: dict[str, Any]) -> None:
    @case(f"typed_{name}")
    async def run(w: World) -> list[str]:
        seen, _ = await _turn(w, f"{name}?", [{"name": tool, "arguments": args}], "Done, Sir.")
        return _absent("a typed turn's model request", seen, (FULL_ID, FILE_MARK))


for _name, _tool, _args in (
    ("vault_list", "vault_list", {}),
    ("vault_expiring", "vault_expiring", {"within_days": 90}),
    ("kb_search", "kb_search", {"query": "plumber"}),
    ("kb_read", "kb_read", {"id": "@note"}),
    ("belongings_list", "belongings_list", {}),
):
    _typed(_name, _tool, _args)


@case("typed_note_saved")
async def typed_note(w: World) -> list[str]:
    seen, _ = await _turn(
        w, "take a note", [{"name": "kb_add_note", "arguments": {"text": NOTE}}], "Saved."
    )
    return _absent("a typed turn's model request", seen, (FULL_ID, FILE_MARK))


@case("typed_where_positive_control")
async def typed_where(w: World) -> list[str]:
    """The scan can see: a typed look-up's request DOES carry the place (the model needs it)."""
    seen, res = await _turn(
        w,
        "where is my passport?",
        [{"name": "belongings_where", "arguments": {"item": "passport"}}],
        f"It is {PLACE}, Sir.",
    )
    w.marks["train_session"] = res.session_id
    out = _absent("a typed turn's model request", seen, (FULL_ID, FILE_MARK))
    if PLACE not in seen:
        out.append("the positive control did not see the place: the scan is blind")
    return out


def _voice(name: str, tool: str, args: dict[str, Any]) -> None:
    @case(f"voice_{name}")
    async def run(w: World) -> list[str]:
        seen, _ = await _turn(
            w, f"{name}?", [{"name": tool, "arguments": args}], "Done.", channel="voice"
        )
        return _absent("a spoken turn's model request", seen, (FULL_ID, FILE_MARK))


for _name, _tool, _args in (
    ("vault_list", "vault_list", {}),
    ("belongings_where", "belongings_where", {"item": "passport"}),
    ("kb_search", "kb_search", {"query": "plumber"}),
    ("belongings_put", "belongings_put", {"item": "spare keys", "place": PLACE_2}),
):
    _voice(_name, _tool, _args)


def approval_cards(w: World) -> dict[str, Any]:
    """The waiting approval cards, as Firestore documents (DocApprovalStore, the app's store)."""
    return {k: v for k, v in w.docs._data.items() if k.startswith(APPROVALS)}  # type: ignore[attr-defined]


@case("voice_kb_add_note_card")
async def voice_note_card(w: World) -> list[str]:
    """Review S4: a spoken note waits as a card (plan D10), and its words sit in that card's
    document until the owner decides (D13). The scan below allows exactly those documents."""
    seen, _ = await _turn(
        w,
        "take a note",
        [{"name": "kb_add_note", "arguments": {"text": VOICE_NOTE}}],
        "That waits for your tap.",
        channel="voice",
    )
    out = _absent("a spoken turn's model request", seen, (FULL_ID, FILE_MARK))
    if not any(VOICE_NOTE in json.dumps(v, default=str) for v in approval_cards(w).values()):
        out.append("the spoken note did not wait as a stored card: the approvals case is blind")
    return out


def _telegram(name: str, tool: str, args: dict[str, Any]) -> None:
    @case(f"telegram_off_{name}")
    async def run(w: World) -> list[str]:
        seen, _ = await _turn(
            w, f"{name}?", [{"name": tool, "arguments": args}], "Not here.", channel="telegram"
        )
        return _absent("a Telegram turn (switch off)", seen, NEEDLES)


for _name, _tool, _args in (
    ("vault_list", "vault_list", {}),
    ("kb_search", "kb_search", {"query": "plumber"}),
    ("kb_read", "kb_read", {"id": "@note"}),
    ("belongings_where", "belongings_where", {"item": "passport"}),
):
    _telegram(_name, _tool, _args)


@case("training_brain_same_session")
async def training_same(w: World) -> list[str]:
    seen, _ = await _turn(
        w,
        "and what else?",
        [],
        "I can't see that here.",
        brain="training",
        session_id=w.marks.get("train_session"),
    )
    out = _absent("a training-brain request", seen, NEEDLES)
    if w.offered & set(R2_TOOLS):
        out.append("an R2 tool was offered to a training brain")
    return out


@case("training_brain_asks_directly")
async def training_direct(w: World) -> list[str]:
    seen, _ = await _turn(w, "where is my passport?", [], "I don't know.", brain="training")
    out = _absent("a training-brain request", seen, NEEDLES)
    if w.offered & set(R2_TOOLS):
        out.append("an R2 tool was offered to a training brain")
    return out


@case("offline_never_offers_r2")
async def offline(w: World) -> list[str]:
    return [f"{n} is an offline tool" for n in R2_TOOLS if n in OFFLINE_TOOLS]


@case("brief_day_reminder_alert")
async def brief_alert(w: World) -> list[str]:
    counts = await w.vault.reminders.run([UID])
    out = [] if w.alerts.sent else [f"no reminder alert was sent ({counts})"]
    for kind, text in w.alerts.sent:
        out += _absent(f"a {kind} alert", text, (*NEEDLES, "8765"))
    return out


@case("brief_day_documents_section")
async def brief_section(w: World) -> list[str]:
    day = NOW.astimezone(ZoneInfo("Asia/Kolkata")).date()
    sec = await VaultDueBrief(w.vault.service).section(UID, ZoneInfo("Asia/Kolkata"), day)
    if sec is None or not sec.items:
        return ["the Documents section is empty"]
    return _absent("the brief's Documents section", sec.model_dump_json(), (*NEEDLES, "8765"))


@case("brief_day_inbox_copy")
async def brief_inbox_copy(w: World) -> list[str]:
    """Review S4: the brief's Gmail copy says only how many documents need attention while the
    owner's inbox_copy switch is off (D5); the console's brief has the lines (the control)."""
    zone = ZoneInfo("Asia/Kolkata")
    day = NOW.astimezone(zone).date()
    sec = await VaultDueBrief(w.vault.service).section(UID, zone, day)
    if sec is None or not sec.items or sec.inbox_copy:
        return ["the Documents section is empty or its inbox copy is on"]
    data = BriefData(date=day.isoformat(), tz="Asia/Kolkata", vault=sec)
    full = render_text(data)
    copy = inbox_text(full, data)
    label = sec.items[0].type_label
    out = [] if label in full else ["the console brief has no document line: the case is blind"]
    if label in copy or "need" not in copy:
        out.append("the inbox copy carries the document lines with inbox_copy off")
    return out + _absent("the brief's inbox copy", copy, (*NEEDLES, "8765"))


# ---- the scans (after every conversation) -------------------------------------------------------


async def scan_documents(w: World) -> list[str]:
    """Every Firestore document is needle-free, except the waiting approval cards (D13, the
    documented limit): those may hold a note's words, never the full number or the file bytes."""
    data = w.docs._data  # type: ignore[attr-defined]
    cards = approval_cards(w)
    rest = {k: v for k, v in data.items() if k not in cards}
    out = _absent("a Firestore document", json.dumps(rest, default=str), NEEDLES)
    return out + _absent("an approval card", json.dumps(cards, default=str), (FULL_ID, FILE_MARK))


async def scan_logs(w: World) -> list[str]:
    return _absent("a log record", "\n".join(w.logs.records), NEEDLES)


async def scan_audit(w: World) -> list[str]:
    tail = await w.gateway.audit.tail(1000)
    return _absent(
        "an audit entry", json.dumps([e.model_dump(mode="json") for e in tail.entries]), NEEDLES
    )


async def scan_activity(w: World) -> list[str]:
    rows = {k: v for k, v in w.docs._data.items() if "activity" in k}  # type: ignore[attr-defined]
    out = [] if rows else ["no Activity row was written"]
    return out + _absent("an Activity row", json.dumps(rows, default=str), NEEDLES)


async def scan_sessions(w: World) -> list[str]:
    """Conversation turns are Google-encrypted only (D13): tools never put the full number or the
    file bytes there."""
    blob = json.dumps(
        {k: s.model_dump(mode="json") for k, s in w.sessions._data.items()},  # type: ignore[attr-defined]
        default=str,
    )
    return _absent("a stored conversation", blob, (FULL_ID, FILE_MARK))


SCANS: list[tuple[str, Check]] = [
    ("scan_firestore_documents", scan_documents),
    ("scan_log_records", scan_logs),
    ("scan_audit_entries", scan_audit),
    ("scan_activity_rows", scan_activity),
    ("scan_conversations", scan_sessions),
]


async def run_all(*, ignore_activity_words: bool = False) -> list[dict[str, Any]]:
    w = await build_world(ignore_activity_words=ignore_activity_words)
    results: list[dict[str, Any]] = []
    try:
        for name, fn in [*CASES, *SCANS]:
            try:
                failures = await fn(w)
            except Exception as exc:  # noqa: BLE001 - a crash is a failed case, not a crash
                failures = [f"raised {type(exc).__name__}: {exc}"]
            results.append({"id": name, "passed": not failures, "failures": failures})
    finally:
        logging.getLogger().removeHandler(w.logs)
    return results


async def controls() -> dict[str, Any]:
    bad = await run_all(ignore_activity_words=True)
    failed = [r["id"] for r in bad if not r["passed"]]
    return {"suite_failed": "scan_activity_rows" in failed, "failed_cases": failed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.parse_args()
    configure_logging()
    results = asyncio.run(run_all())
    return finish(HERE, "r2_needles", results, asyncio.run(controls()))


if __name__ == "__main__":
    sys.exit(main())
