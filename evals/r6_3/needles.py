# evals/r6_3/needles.py
"""R6.3 eval, I1's `needles` suite (BUILT; docs/plans/r6-3-book-content.md "Tests and evals",
plan review H6 and M8): private words planted around the writer, and the sinks they must never
reach. One world, on in-memory fakes and the scripted brains (no model is ever called):

Planted: the creator name (Book settings), his e-mail (the owner's e-mail AND in a cited file), a
vault document's text, a memory fact and a mail subject (in their own collections, which the
writer never reads), a fake secret (secret-shaped, in a cited file), the owner's handle inside a
tracked path (H6), and a stand-in for each hashed private word (a locality, an employer, a
workplace: M8; the real ones are hashes in gen/redact.json, so the scrubber here also knows the
stand-ins' hashes, made by scripts/redact_add.py's own rule). The first draft of every page is
the worst case: the brain repeats its whole prompt (refused: it repeats the reference marker).

Sinks: every page's pack, every prompt sent (the reference marker, the canary, is allowed only
there), every page in the reader, every kept draft and trial page (opened), facts.json (part A's
pack of this repository, built with the same scrubber), every log record, the audit, every notice
and the Privacy export. A positive control per sink: a made-up marker the world puts in on
purpose ("Plumtwist": in a cited file's docstring, in the example of every good draft, in a
tracked path) must be found in it, and a record planted through the log, the audit and the
notifier must be found, else the sink is not really read.

Negative control (the plan's): the pack builder reading Book settings (the creator name added to
every pack): the creator-name needle is found.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import io
import json
import logging
import sys
import tempfile
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from r63_fake_brains import (  # noqa: E402
    CLAUDE_TIERS,
    GOOD_DRAFT,
    ScriptedWriter,
    Step,
    gemini_like,
    provider_of,
    registry,
)
from r63_fakes import FIXTURE_FILES, GUIDE, RELEASE, FakeSource, source_zip, writer_context  # noqa: E402
from r63_fakes_a import DEMO, repo_of  # noqa: E402
from r63_fakes_b import TRIAL_EXTRA, pick, run_first, seal_r6, steps  # noqa: E402

from jarvis.buildbook.facts_model import FactPack, canonical_facts  # noqa: E402
from jarvis.buildbook.gen import facts, pages_index  # noqa: E402
from jarvis.buildbook.gen import scrub as scrub_mod  # noqa: E402
from jarvis.buildbook.writer import packs, part  # noqa: E402
from jarvis.buildbook.writer.http import TrialIn  # noqa: E402
from jarvis.llm.base import ChatMessage  # noqa: E402
from jarvis.llm.brains import BrainSpec  # noqa: E402
from jarvis.storage.docs import MemoryDocs, Set  # noqa: E402

PART = "needles"
BUILT = True
ROUTER = "src/jarvis/demo/router.py"
HANDLE = "vexmorrin"  # a stand-in for the owner's handle (H6)
ANDROID = f"android/app/src/main/java/com/{HANDLE}/jarvis/Main.kt"
MARKER = "Plumtwist"  # a made-up word put in ON PURPOSE (the positive controls)
STAND_INS = {
    "locality": "Zorblaxton",
    "employer": "Quimbledorf Works",
    "workplace": "Brillowan Labs",
}
SECRET = "gsk_" + "Q7" * 14  # secret-shaped (groq), made at run time so no file holds the shape
NEEDLES = {
    "creator": "Florizel Ambergast",
    "email": "florizel.owner@example.com",
    "vault": "mangrove ledger seventy",
    "memory": "the tangerine bicycle",
    "mail": "quarterly saffron invoice",
    "secret": SECRET,
    "handle": HANDLE,
    **STAND_INS,
}
SINKS = ("pack", "prompt", "page", "draft", "trial", "facts", "log", "audit", "notice", "export")
MARKED = ("pack", "prompt", "page", "draft", "trial", "facts")  # the marker's own sinks


# ---- the world ---------------------------------------------------------------------------------
def scrubber() -> scrub_mod.Scrubber:
    """gen/redact.json's lists plus the stand-ins' hashes, by scripts/redact_add.py's rule."""
    spec = importlib.util.spec_from_file_location(
        "r63_redact_add", ROOT / "scripts" / "redact_add.py"
    )
    assert spec is not None and spec.loader is not None
    add = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(add)
    names, phrases, _ = add.hashes_of("\n".join([HANDLE, *STAND_INS.values()]))
    return scrub_mod.Scrubber(
        scrub_mod.load_redact() | frozenset(names),
        domains=scrub_mod.load_domains(),
        phrases=scrub_mod.load_phrases() | frozenset(phrases),
    )


def tree() -> dict[str, str]:
    doc = (
        f'"""The demo router: one tier a request. {MARKER} reads it. Made in Zorblaxton for '
        f'Quimbledorf Works at Brillowan Labs; write to {NEEDLES["email"]}; key {SECRET}."""'
    )
    out = dict(FIXTURE_FILES)
    out[ROUTER] = doc + "\n" + out[ROUTER].split("\n", 1)[1]
    out[ANDROID] = "// the app's main screen\n"
    out[f"src/jarvis/demo/{MARKER.lower()}.py"] = '"""A tracked file the index lists."""\n'
    out["docs/architecture/JARVIS-Architecture.md"] = GUIDE.replace(
        "| Where in the code | `console-demo.js` |",
        f"| Where in the code | `console-demo.js`, `{ANDROID}` |",
    )
    return out


def pack_of(files: dict[str, str], scrub: scrub_mod.Scrubber) -> FactPack:
    with tempfile.TemporaryDirectory(prefix="r63needles-") as tmp:
        repo = repo_of(Path(tmp), files)
        pack = facts.build(repo, scrub, modules=DEMO).model_copy(update={"release": RELEASE})
        pages = pages_index.build(repo, pack)
    return pack.model_copy(update={"pages": (*pages, *TRIAL_EXTRA)})


class Echo(ScriptedWriter):
    """The worst case first: a page's first draft repeats its whole prompt (refused, the reference
    marker in it); its redraft is the good draft with the marker word in the example. Not a
    @dataclass: the runner loads this file by path, outside sys.modules."""

    async def stream(
        self, *, messages: list[ChatMessage], max_tokens: int, **kw: Any
    ) -> AsyncIterator[str]:  # type: ignore[override]
        first, seen = messages[0].text(), self.__dict__["_seen"]  # shared by no_retry() copies
        text = GOOD_DRAFT.replace("Asha", MARKER) if first in seen else GOOD_DRAFT + first
        seen.add(first)
        self.steps.insert(0, Step(text=text, input_tokens=2_000, output_tokens=400))
        async for piece in super().stream(messages=messages, max_tokens=max_tokens, **kw):
            yield piece


class Audit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def append(self, **kw: Any) -> None:
        self.rows.append(kw)


class Told:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def notify(self, uid: str, signal: Any, message: str, **kw: Any) -> Any:
        self.sent.append(f"{signal.kind} {message}")
        return None


class Logs(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        extra = {k: v for k, v in record.__dict__.items() if k not in _PLAIN}
        self.lines.append(record.getMessage() + " " + json.dumps(extra, default=str))


_PLAIN = set(vars(logging.LogRecord("x", 0, "x", 0, "", None, None))) | {"message", "asctime"}


async def _plant(docs: MemoryDocs, prefix: str, uid: str) -> None:
    await docs.write([
        Set(f"{prefix}book_settings/{uid}", {"creator_name": NEEDLES["creator"], "owner": uid}),
        Set(f"{prefix}vault_docs/{uid}_d1", {"text": NEEDLES["vault"], "owner": uid}),
        Set(f"{prefix}memory/{uid}_m1", {"fact": NEEDLES["memory"], "owner": uid}),
        Set(f"{prefix}mail_cache/{uid}_1", {"subject": NEEDLES["mail"], "owner": uid}),
    ])  # fmt: skip


# ---- one run, every sink gathered --------------------------------------------------------------
async def world(*, control: bool = False) -> dict[str, Any]:
    scrub, files = scrubber(), tree()
    fact_pack = pack_of(files, scrub)
    zipped = source_zip(files)
    echo = Echo("anthropic")
    echo.__dict__["_seen"] = set()  # before any copy, so every no_retry() view shares it
    claude = BrainSpec(id="anthropic", label="Claude", provider=echo, tiers=dict(CLAUDE_TIERS))
    gemini = gemini_like()
    docs, audit, told, logs = MemoryDocs(), Audit(), Told(), Logs()
    ctx = writer_context(
        brains=registry(claude, gemini), source=FakeSource(fact_pack, zipped=zipped), docs=docs
    )
    ctx = dataclasses.replace(ctx, audit=audit, notifier=told, owner_emails=(NEEDLES["email"],))
    await _plant(docs, ctx.prefix, ctx.uid)
    saved = (part.default_scrubber, packs.build)
    part.default_scrubber = lambda: scrub  # type: ignore[assignment]
    if control:  # the pack builder reading Book settings (the plan's control)
        packs.build = _reading_settings(saved[1])  # type: ignore[assignment]
    root = logging.getLogger()
    root.addHandler(logs)
    try:
        sinks = await _run(part.build(ctx), ctx, fact_pack, zipped, scrub)
        positive = await _positive(logs, audit, told)  # through the same channels, still attached
    finally:
        root.removeHandler(logs)
        part.default_scrubber, packs.build = saved  # type: ignore[assignment]
    calls = provider_of(claude).calls + provider_of(gemini).calls
    canaries = sorted(
        {
            w
            for c in calls
            for w in c.messages[0].text().split()
            if w.startswith("cn") and len(w) == 18
        }
    )
    sinks["prompt"] = [
        _without(" ".join([c.system, *(m.text() for m in c.messages)]), canaries) for c in calls
    ]
    sinks.update(
        log=logs.lines, audit=[json.dumps(r, default=str) for r in audit.rows], notice=told.sent
    )
    return {"sinks": sinks, "canaries": canaries, "positive": positive}


def _reading_settings(build: Any) -> Any:
    def wrong(*a: Any, **k: Any) -> packs.Pack:
        got = build(*a, **k)
        return dataclasses.replace(got, body=got.body + f"\nCreated by {NEEDLES['creator']}")

    return wrong


def _without(text: str, canaries: list[str]) -> str:
    for c in canaries:
        text = text.replace(c, "")
    return text


async def _run(
    built: Any, ctx: Any, fact_pack: FactPack, zipped: bytes, scrub: Any
) -> dict[str, Any]:
    svc, uid = built.service, ctx.uid
    await seal_r6(built)
    est = await svc.estimate(uid, "trial")
    await svc.start_trial(uid, TrialIn(typed="YES", estimate_id=est.id))
    await steps(built)
    await pick(built)
    store, drafts = svc.store, []
    keep = store.put_draft

    async def kept(uid_: str, rid_: str, draft: Any) -> None:  # every draft as it is kept, opened
        drafts.append(store.open(uid_, rid_, draft.fid, draft.blob).decode() if draft.blob else "")
        await keep(uid_, rid_, draft)

    store.put_draft = kept
    await run_first(built)
    await steps(built, 60)
    with zipfile.ZipFile(io.BytesIO(zipped)) as zf:
        text = {n: zf.read(n).decode("utf-8", "replace") for n in zf.namelist()}
    rows = (await svc.trial_rows(uid)).rows
    export = [json.dumps(await s.export(uid), default=str) for s in built.privacy]
    return {
        "pack": [packs.build(ip, fact_pack, text, scrub).body for ip in fact_pack.pages],
        "page": [(await svc.page(uid, ip.id, None)).model_dump_json() for ip in fact_pack.pages],
        "draft": drafts,
        "trial": [(await svc.trial_page(uid, r.nn)).model_dump_json() for r in rows],
        "facts": [canonical_facts(fact_pack).decode("utf-8")],
        "export": export,
    }


async def _positive(logs: Logs, audit: Audit, told: Told) -> dict[str, bool]:
    """Each channel sink records what is sent through it (a needle planted on purpose)."""
    probe = "probe-" + MARKER
    logging.getLogger("jarvis.buildbook.writer.job").error("planted", extra={"count": probe})
    await audit.append(agent="book", args={"x": probe})
    await told.notify("u", type("S", (), {"kind": "book_sealed"})(), probe)
    return {
        "log": any(probe in x for x in logs.lines),
        "audit": any(probe in json.dumps(r) for r in audit.rows),
        "notice": any(probe in x for x in told.sent),
    }


# ---- the cases ---------------------------------------------------------------------------------
def found(needle: str, texts: list[str]) -> bool:
    low = needle.casefold()
    return any(low in t.casefold() for t in texts)


def judge(w: dict[str, Any]) -> list[dict[str, Any]]:
    sinks: dict[str, list[str]] = w["sinks"]
    out = []
    for name, needle in NEEDLES.items():
        hits = [s for s in SINKS if found(needle, sinks.get(s, []))]
        out.append(
            {"id": f"{PART}:{name}", "passed": not hits, "failures": [f"in {s}" for s in hits]}
        )
    canary_hits = [
        s for s in SINKS if s != "prompt" for c in w["canaries"] if found(c, sinks.get(s, []))
    ]
    no_canary = [] if w["canaries"] else ["no canary was sent: the prompts were not read"]
    out.append({"id": f"{PART}:canary", "passed": not (canary_hits or no_canary),
                "failures": no_canary + [f"in {s}" for s in sorted(set(canary_hits))]})  # fmt: skip
    missing = [s for s in MARKED if not found(MARKER, sinks.get(s, []))]
    missing += [s for s, ok in w["positive"].items() if not ok]
    missing += (
        [] if sinks.get("export") and all(t != "null" for t in sinks["export"]) else ["export"]
    )
    out.append(
        {
            "id": f"{PART}:positive_per_sink",
            "passed": not missing,
            "failures": [f"not read: {s}" for s in missing],
        }
    )
    planted = [
        n
        for n, needle in NEEDLES.items()
        if n in ("email", "secret", "handle", *STAND_INS)
        and not found(needle, list(tree().values()))
    ]
    out.append({"id": f"{PART}:planted_all", "passed": not planted, "failures": planted})
    return out


async def cases() -> list[dict[str, Any]]:
    try:
        return judge(await world())
    except Exception as exc:  # noqa: BLE001 - an eval reports, it never crashes the runner
        return [
            {
                "id": f"{PART}:world",
                "passed": False,
                "failures": [f"{type(exc).__name__}: {str(exc)[:200]}"],
            }
        ]


async def control() -> dict[str, Any]:
    got = judge(await world(control=True))
    creator = next(c for c in got if c["id"] == f"{PART}:creator")
    return {
        "name": "I1: the pack builder reading Book settings (the creator name in every pack)",
        "suite_failed": not creator["passed"],
        "failed_cases": [f"{c['id']} {c['failures'][:3]}" for c in got if not c["passed"]],
    }
