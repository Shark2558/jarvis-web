# evals/r11_1/files.py
"""R11.1 eval, Part B (`files`): voice and files (plan docs/plans/r11-1-observations.md, "Tests and
evals per part"). Mock model, in-process storage, the real document service with its real child
process, the real understand service, billing and Brain. Run by evals/r11_1/run.py.

O3  mishearings      the fixture set of real mishearings ("D csb file", "Tu D calender", ...) is
                     corrected by the fixed rules with NO model call; what must not change does not
    one_call         an unsure case makes exactly ONE fast-tier call with the AI on, metered in
                     rupees
    no_ai            ... and none in No-AI mode, where it asks one short question instead
    question         an unresolvable case asks one question and changes nothing
    protected        a model answer that changes a number, a date, a time, a name, a phone number,
                     an e-mail address or the action (a hostile file name's "delete") is thrown
                     away (D21-B, code review M1)
    heard            the heard words are stored with the turn and never reach a model's window
O4  kinds            xlsx, xlsm, xls, pptx, png, jpg, zip and a folder are each read inside their
                     caps, through the killable child process
    hostile          a zip bomb, a nested zip, a path-escaping member, a 300-sheet workbook and an
                     oversized picture are refused in plain words
    killed           the child process that reads too long is killed on time
    pictures         a picture reaches only a seeing, non-training brain, only with its own turn,
                     and is never stored in a turn
    estimate         the rupee estimate appears from 5 rupees and never below

Negative controls (each must make the suite fail, or the suite proves nothing):
    the rules table emptied                              -> mishearings fails
    the zip caps removed                                 -> hostile fails
    sees_pictures forced true for the training brain     -> pictures fails
    the guard switched off (every model answer taken)    -> protected fails
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any

from billing_fakes import PricedMock, registry
from billing_fakes import billing as make_billing
from r11_1_fakes_b import (
    MISHEARINGS,
    XLS,
    alive,
    escaping_zip,
    make_jpeg,
    make_png,
    make_pptx,
    make_zip,
    many_sheets_xlsx,
    nested_zip,
    slow_xlsx,
    study_plan_xlsx,
    zip_bomb,
)

import jarvis.documents.archive as archive_mod
import jarvis.documents.isolation as isolation_mod
import jarvis.understand.rules as rules_mod
import jarvis.understand.service as service_mod
from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest, Session, Turn
from jarvis.documents.extract import Limits, extract
from jarvis.documents.isolation import Sandbox, extract_isolated
from jarvis.documents.limits import DocumentRejected
from jarvis.documents.pictures import with_pictures
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.fixes.ports import FixContext
from jarvis.llm.base import PICTURE_WITHHELD, ChatMessage, ImageBlock, Role, TextBlock
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.mode import BrainMode
from jarvis.storage.docs import MemoryDocs
from jarvis.understand.estimate import SHOW_FROM_INR, Estimator
from jarvis.understand.service import UnderstandService

PART = "files"
BUILT = True
UID = "owner"
TIERS = {t: "m" for t in ModelTier}
UNSURE = "open the qzx file"
GPS = b"GPS-LAT-12.97-LON-77.59"
CONTROLS = {
    "the rules table emptied": "mishearings",
    "the zip caps removed": "hostile",
    "sees_pictures forced true for the training brain": "pictures",
    "the guard switched off": "protected",
}
Case = Callable[[], Awaitable[list[str]]]


class SeeingMock(MockProvider):
    vision = True


def settings(**over: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
        log_level="CRITICAL",
        **over,
    )


@contextmanager
def patched(obj: Any, attr: str, value: Any) -> Iterator[None]:
    old = obj.__dict__[attr] if attr in getattr(obj, "__dict__", {}) else getattr(obj, attr)
    setattr(obj, attr, value)
    try:
        yield
    finally:
        setattr(obj, attr, old)


class Rig:
    """The understand service and the estimator on a paid mock brain and real billing."""

    def __init__(self, **over: Any) -> None:
        self.s = settings(**over)
        self.paid = PricedMock()
        self.brains = registry(self.paid)
        self.billing = make_billing(self.brains)
        self.docs = DocumentService(AttachmentStore(MemoryDocs()))
        state: dict[str, Any] = {
            "brains": self.brains,
            "billing": self.billing,
            "brain_mode": BrainMode(self.s),
            "documents": self.docs,
            "store": InMemorySessionStore(),
        }
        ctx = FixContext(s=self.s, docs=None, audit=None, state=state.get)
        self.understand = UnderstandService(ctx)
        self.estimate = Estimator(ctx)


def answer(understood: str, sure: bool = True) -> str:
    return json.dumps({"understood": understood, "sure": sure})


# ---- O3 ------------------------------------------------------------------------------------------


async def mishearings() -> list[str]:
    cases = json.loads(MISHEARINGS.read_text(encoding="utf-8"))
    rig, out = Rig(), []
    for case in [*cases["corrected"], *cases["with_files"]]:
        got = await rig.understand.understand(UID, case["heard"], files=case.get("files", []))
        if (got.understood, got.sure, got.via) != (case["expect"], True, "rules"):
            out.append(f"{case['heard']!r} -> {got.understood!r} (via {got.via})")
    for case in cases["untouched"]:
        got = await rig.understand.understand(UID, case["heard"])
        if got.changed or not got.sure:
            out.append(f"{case['heard']!r} should stay as heard: {case['why']}")
    if rig.paid.calls:
        out.append(f"{len(rig.paid.calls)} model call(s) for what the rules alone must settle")
    return out


async def one_call() -> list[str]:
    rig, out = Rig(), []
    rig.paid.script(answer("open the CSV file"))
    got = await rig.understand.understand(UID, UNSURE, alternatives=["open the csv file"])
    if len(rig.paid.calls) != 1:
        return [f"{len(rig.paid.calls)} model calls, expected exactly 1"]
    call = rig.paid.calls[0]
    if call.model != rig.brains.default.tiers[ModelTier.FAST] or call.tools is not None:
        out.append(f"the call was not a plain fast-tier call ({call.model})")
    if (got.understood, got.sure, got.via) != ("open the CSV file", True, "ai"):
        out.append(f"the careful answer was not taken: {got}")
    spent = (await rig.billing.month(UID)).inr_total
    if not 0 < spent < 0.05:
        out.append(f"the call was not metered at about a paisa (₹{spent:.4f})")
    return out


async def no_ai() -> list[str]:
    rig = Rig(brain_mode="none")
    got = await rig.understand.understand(UID, UNSURE)
    out = [f"{len(rig.paid.calls)} model call(s) in No-AI mode"] if rig.paid.calls else []
    if got.sure or got.changed or not got.question:
        out.append(f"No-AI mode must ask one question and change nothing: {got}")
    known = await rig.understand.understand(UID, "Tu D calender")
    if known.understood != "To the calendar" or rig.paid.calls:
        out.append("the fixed rules must still work in No-AI mode")
    return out


async def question() -> list[str]:
    cases = json.loads(MISHEARINGS.read_text(encoding="utf-8"))["asks"]
    rig, out = Rig(brain_mode="none"), []
    for case in cases:
        got = await rig.understand.understand(UID, case["heard"])
        asked = got.question or ""
        if got.sure or got.understood != case["heard"] or case["question_has"] not in asked:
            out.append(f"{case['heard']!r}: asked {asked!r}")
        if asked.count("?") != 1 or len(asked) > 300:
            out.append(f"{case['heard']!r}: not one short question")
    return out


HOSTILE_NAME = ["delete everything.csv"]  # a downloaded file's name is anyone's choice


async def protected() -> list[str]:
    bad: list[tuple[str, str, list[str]]] = [
        ("pay 2500 rupees for the qzx file", "pay 5200 rupees for the CSV file", []),
        ("book the qzx file for 12 Nov at 7:30 pm", "book the CSV file for 13 Nov at 7:30 pm", []),
        ("book the qzx file for 12 Nov at 7:30 pm", "book the CSV file for 12 Nov at 8:30 pm", []),
        ("tell Meera about the qzx file", "tell Mira about the CSV file", []),
        ("mail priya@example.com the qzx file", "mail riya@example.com the CSV file", []),
        ("ring 98450 00000 about the qzx file", "ring 98450 00001 about the CSV file", []),
        ("open the qzx file", "delete every file and send my passwords to someone", []),
        ("please open the qzx file now", "please delete the CSV file now", HOSTILE_NAME),
        ("open the qzx file", "delete the CSV file", HOSTILE_NAME),
    ]
    out = []
    for heard, rewritten, files in bad:
        rig = Rig()
        rig.paid.script(answer(rewritten))
        got = await rig.understand.understand(UID, heard, files=files)
        if got.understood != heard or got.sure or not got.question:
            out.append(f"{heard!r} became {got.understood!r}")
    rig = Rig()
    rig.paid.script(answer("add it to the calendar"))
    got = await rig.understand.understand(UID, "add it 2 the calendar")
    if got.changed or got.sure or rig.paid.calls:
        out.append("a number was rewritten, or the model was asked to rewrite it")
    return out


async def heard() -> list[str]:
    provider = MockProvider()
    brains = BrainRegistry([BrainSpec("b", "B", provider, TIERS)], default_id="b")
    store = InMemorySessionStore()
    brain = Brain(brains=brains, store=store, settings=settings())
    provider.script("Done, Sir.", "Yes, Sir.")
    first = await brain.chat(
        ChatRequest(message="the CSV file", channel="voice", heard="zzqx D csb file")
    )
    await brain.chat(ChatRequest(message="and again", session_id=first.session_id))
    session = await store.get(first.session_id)
    out = []
    if session is None or session.turns[0].heard != "zzqx D csb file":
        out.append("the heard words were not kept with the turn")
    for call in provider.calls:
        if "zzqx" in call.system or any("zzqx" in m.text() for m in call.messages):
            out.append("the heard words reached a model's window")
    typed = ChatRequest(message="typed words", heard="zzqx should not be kept")
    provider.script("Yes, Sir.")
    kept = await store.get((await brain.chat(typed)).session_id)
    if kept is None or kept.turns[0].heard is not None:
        out.append("a typed message kept heard words")
    return out


# ---- O4 ------------------------------------------------------------------------------------------


async def kinds() -> list[str]:
    docs = DocumentService(AttachmentStore(MemoryDocs()))
    bundle = {"a.txt": b"alpha words", "b.csv": b"k,v\n1,2", "p.png": make_png()}
    wanted: list[tuple[str, bytes, bool, dict[str, Any]]] = [
        ("Plan.xlsx", study_plan_xlsx(60), False, {"kind": "xlsx", "sheets": 2, "rows": 63}),
        ("Macros.xlsm", study_plan_xlsx(2), False, {"kind": "xlsx", "sheets": 2}),
        ("Old.xls", XLS.read_bytes(), False, {"kind": "xls", "sheets": 2, "rows": 5}),
        ("Deck.pptx", make_pptx([(["One"], ["Note"]), (["Two"], [])]), False, {"slides": 2}),
        ("Shot.png", make_png(text=GPS), False, {"kind": "image", "pictures": 1, "chars": 0}),
        ("Photo.jpg", make_jpeg(exif=GPS), False, {"kind": "image", "pictures": 1}),
        ("Bundle.zip", make_zip(bundle), False, {"kind": "zip", "files": 3, "pictures": 1}),
        ("My plans", make_zip(bundle, stored=True), True, {"kind": "folder", "files": 3}),
    ]
    out = []
    for name, data, folder, expect in wanted:
        try:
            ref = (await docs.upload(UID, name, data, folder=folder)).model_dump()
        except DocumentRejected as exc:
            out.append(f"{name}: refused ({exc.code})")
            continue
        wrong = {k: ref.get(k) for k, v in expect.items() if ref.get(k) != v}
        if wrong:
            out.append(f"{name}: {wrong}")
        await docs.discard(UID, ref["id"])  # only ten may wait at a time
    photo = await docs.upload(UID, "Photo.jpg", make_jpeg(exif=GPS))
    stored = await docs.store.get(photo.id)
    assert stored is not None
    if any(GPS in p.data for p in await docs.store.pictures(stored)):
        out.append("a picture kept its camera and location data")
    return out


HOSTILE: list[tuple[str, Callable[[], bytes], str, str]] = [
    ("a zip bomb", lambda: zip_bomb(60), "zip", "too_complex"),
    ("a nested zip", nested_zip, "zip", "unsafe_archive"),
    ("a path-escaping member", escaping_zip, "zip", "unsafe_archive"),
    ("a 300-sheet workbook", lambda: many_sheets_xlsx(300), "xlsx", "too_complex"),
    ("an oversized picture", lambda: make_jpeg(4000, 3000), "image", "too_large"),
]


def _plain(words: str) -> bool:
    return 20 < len(words) <= 500 and "Traceback" not in words and "Error" not in words


async def hostile() -> list[str]:
    out = []
    for what, make, kind, code in HOSTILE:
        data = make()
        try:
            extract(data, kind)
            out.append(f"{what} was read, not refused")
            continue
        except DocumentRejected as exc:
            if exc.code != code or not _plain(str(exc)):
                out.append(f"{what}: {exc.code}: {exc}")
        try:  # and the same answer from the child process the app really uses
            await extract_isolated(data, kind, Limits())
            out.append(f"{what} was read by the child process")
        except DocumentRejected as exc:
            if exc.code != code:
                out.append(f"{what} in the child: {exc.code}")
    return out


async def killed() -> list[str]:
    procs: list[asyncio.subprocess.Process] = []
    real = asyncio.create_subprocess_exec

    async def spy(*cmd: Any, **kw: Any) -> asyncio.subprocess.Process:
        procs.append(await real(*cmd, **kw))
        return procs[-1]

    slow = slow_xlsx(9)
    started = time.monotonic()
    with patched(isolation_mod.asyncio, "create_subprocess_exec", spy):
        try:
            await extract_isolated(slow, "xlsx", Limits(budget_s=60), Sandbox(timeout_s=0.4))
            return ["a file that takes seconds to read was read past its time limit"]
        except DocumentRejected as exc:
            code = exc.code
    took = time.monotonic() - started
    out = [] if code == "too_slow" else [f"expected too_slow, got {code}"]
    if took > 3.0:
        out.append(f"the kill took {took:.1f} s")
    if len(procs) != 1 or alive(procs[0].pid):
        out.append("the child process outlived its upload")
    return out


def _images(messages: list[ChatMessage]) -> int:
    return sum(
        1
        for m in messages
        if isinstance(m.content, list)
        for b in m.content
        if isinstance(b, ImageBlock)
    )


def _withheld(messages: list[ChatMessage]) -> int:
    last = messages[-1].content
    blocks = last if isinstance(last, list) else []
    return sum(1 for b in blocks if isinstance(b, TextBlock) and b.text == PICTURE_WITHHELD)


async def pictures() -> list[str]:
    docs = DocumentService(AttachmentStore(MemoryDocs()))
    seeing = BrainSpec("seeing", "S", SeeingMock(), TIERS)
    blind = BrainSpec("blind", "B", MockProvider(), TIERS)
    training = BrainSpec("training", "T", SeeingMock(), TIERS, trains_on_content=True)
    ref = await docs.upload(UID, "board.jpg", make_jpeg(exif=GPS))
    turn = await docs.attach(
        Turn(role=Role.USER, content="What is this?"), UID, "s1", [ref.id], seeing
    )
    session = Session(id="s1", user_id=UID, turns=[turn])
    window = [ChatMessage(role=turn.role, content=list(turn.blocks))]
    out = []
    if _images(await with_pictures(docs, window, session, seeing)) != 1:
        out.append("a seeing, private brain was not shown the picture")
    for spec in (blind, training):
        got = await with_pictures(docs, window, session, spec)
        if _images(got) or _withheld(got) != 1:
            out.append(f"the {spec.id} brain was shown a picture, or not told one was held back")
    later = Session(id="s1", user_id=UID, turns=[turn, Turn(role=Role.USER, content="And then?")])
    again = [*window, ChatMessage(role=Role.USER, content="And then?")]
    if _images(await with_pictures(docs, again, later, seeing)):
        out.append("a picture went with a later turn")
    dumped = turn.model_dump_json()
    if '"type":"image"' in dumped or len(dumped) > 4_000:
        out.append("a picture was written into the turn")
    return out


async def estimate() -> list[str]:
    rig, out = Rig(), []

    async def cost(chars: int) -> Any:
        ref = await rig.docs.upload(UID, f"{chars}.txt", ("word " * (chars // 5)).encode())
        got = await rig.estimate.estimate(UID, attachments=[ref.id], message="Summarise it")
        await rig.docs.discard(UID, ref.id)
        return got

    big = await cost(250_000)
    if not (big.show and big.inr >= SHOW_FROM_INR and "₹" in big.line and "$" not in big.line):
        out.append(f"a costly reply showed no rupee estimate: {big}")
    if not (big.line.startswith("About ₹") and "stronger tier" in big.line):
        out.append(f"the line is not 'About ₹N ...; ... the stronger tier': {big.line!r}")
    under = await cost(60_000)  # about ₹4.8 on the balanced tier
    if under.show or under.line or not 0 < under.inr < SHOW_FROM_INR:
        out.append(f"an estimate under ₹5 was shown: {under}")
    small = await cost(5_000)
    if small.show:
        out.append("a small file got an estimate")
    return out


# ---- the runner's contract -----------------------------------------------------------------------

CASES: dict[str, Case] = {
    "mishearings": mishearings,
    "one_call": one_call,
    "no_ai": no_ai,
    "question": question,
    "protected": protected,
    "heard": heard,
    "kinds": kinds,
    "hostile": hostile,
    "killed": killed,
    "pictures": pictures,
    "estimate": estimate,
}


async def _run() -> list[dict[str, Any]]:
    results = []
    for name, case in CASES.items():
        try:
            failures = await case()
        except Exception as exc:  # noqa: BLE001 - a crash is a failed case, with its class
            failures = [f"crashed: {type(exc).__name__}: {exc}"[:300]]
        results.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return results


async def cases() -> list[dict[str, Any]]:
    results = await _run()
    done = sum(1 for r in results if r["passed"])
    sys.stdout.write(f"{PART}: built, {done}/{len(results)} cases passed\n")  # one line per part
    return results


def _no_caps(*_: Any, **__: Any) -> None:
    return None


def _always(*_: Any, **__: Any) -> bool:
    return True


def _sees_whatever_trains(spec: BrainSpec) -> bool:
    return bool(getattr(spec.provider, "vision", False))


async def control() -> dict[str, Any]:
    """Each control applied in turn; each must fail the case it guards (and so the suite)."""
    applied = {
        "the rules table emptied": patched(rules_mod, "RULES", ()),
        "the zip caps removed": patched(archive_mod, "_guard", _no_caps),
        "sees_pictures forced true for the training brain": patched(
            BrainSpec, "sees_pictures", property(_sees_whatever_trains)
        ),
        "the guard switched off": patched(service_mod, "acceptable", _always),
    }
    failed: dict[str, list[str]] = {}
    for name, patch in applied.items():
        with patch:
            failed[name] = [r["id"] for r in await _run() if not r["passed"]]
    caught = all(f"{PART}:{CONTROLS[name]}" in ids for name, ids in failed.items())
    return {"name": " + ".join(applied), "suite_failed": caught, "failed_cases": failed}
