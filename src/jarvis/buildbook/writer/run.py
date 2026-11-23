# src/jarvis/buildbook/writer/run.py
"""R6.3 D5-D8, D10 (plan review H7, M1, M5, L10): one writing step of an approved run.

A step takes the writer's lease, closes what earlier steps left (`close_later`, `settle_old`), and
writes the run's pages one call at a time while a call fits the time left: on a clock only while
`ticks.time_left()` >= the brain's p90 seconds + 5 over its last 20 calls (none measured: no clock
call at all, so the trial runs on the console step), at most `CLOCK_CALLS` a run; on the console
step within its own `STEP_BUDGET_S`, each call's `timeout_s` at most `STEP_CALL_TIMEOUT_S`.

Each call: its hold reserved first (caps.py; a refusal stops the run before anything is sent),
then `jarvis.llm.write.write_text` at BALANCED with no tools; nothing received -> the hold
released and the page waits; else settled (a cut call at its usage plus a 10 % margin, never above
its hold) and recorded in billing (Vitals "Book writer"); a settle above its hold stops the run.
The reply is untrusted: refused as it is when its tier isn't BALANCED, its model isn't the
registry's, it is empty or incomplete; else parsed and checked (checks.py), redrafted once with
the failures, then kept (sealed) or refused (the page keeps its previous text). A run is bound to
its release: when the current release changes the next step stops it (M5).
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jarvis.llm.write as write
from jarvis import ticks
from jarvis.buildbook.facts_model import FactPack, IndexedPage
from jarvis.buildbook.gen.scrub import Scrubber
from jarvis.buildbook.writer import caps as caps_mod
from jarvis.buildbook.writer import checks, estimate, packs, prompts
from jarvis.buildbook.writer.estimate import trial_brains
from jarvis.buildbook.writer.model import (
    JOB_BUDGET_S,
    MAX_TOKENS,
    SECONDS_KEPT,
    STEP_BUDGET_S,
    STEP_CALL_TIMEOUT_S,
    TRIAL_PAGES,
    Caps,
    CheckCode,
    Run,
    SectionId,
    WriterDoc,
)
from jarvis.buildbook.writer.ports import WriterContext
from jarvis.buildbook.writer.store import WriterStore
from jarvis.llm.brains import BrainSpec
from jarvis.llm.router import ModelTier

BAL = ModelTier.BALANCED
ACTIVE = ("queued", "running", "paused")
CLOCK_CALLS = 2  # page calls a clock run starts at most (one after another)
SPARE_S, TIMEOUT_SPARE_S, LEASE_EXTRA_S = 5.0, 3.0, 30.0
OVER_EPS_INR = 0.01  # rounding: a settle this much above its hold is still "at" it
MARGIN_SHARE, MARGIN_MIN = 0.10, 200  # a cut call's margin on the output received (H7)
OFFLINE = "offline"  # the laptop brain's provider name: never a page's writer (D1)
PRE_CHECKS: tuple[CheckCode, ...] = ("tier", "model")  # a wrong brain: no redraft


class Busy(Exception):
    """Another step holds the lease."""


@dataclass(frozen=True)
class Item:
    page: IndexedPage
    brain: str
    nn: int | None = None  # a trial page's number


@dataclass
class Out:
    """What one page's calls gave: kept (codes ()), refused (codes), or stopped / waiting."""

    calls: int = 0
    inr: float = 0.0
    seconds: float = 0.0
    attempt: int = 1
    codes: tuple[CheckCode, ...] = ()
    first: tuple[CheckCode, ...] = ()
    sections: dict[SectionId, str] = field(default_factory=dict)
    written: write.Written | None = None
    stop: str | None = None
    wait: str | None = None


def run_key(run: Run) -> str:
    if run.kind == "trial":
        return f"trial_{run.estimate_id}"
    return "first" if run.kind == "first" else f"update_{run.release}"


def cap_of(run: Run, doc: WriterDoc) -> int:
    granted = doc.pick.confirmed.caps
    return {"trial": Caps().trial, "first": granted.first, "update": granted.release}[run.kind]


def p90(seconds: tuple[float, ...]) -> float:
    ordered = sorted(seconds)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def bill(spec: BrainSpec, w: write.Written, hold_inr: float, rate: float) -> float:
    """What a call settles at (D8, H7): its usage; a cut one plus a margin, never above its hold
    and never below what was received."""
    got = w.cost_usd * rate
    if w.complete:
        return round(got, 4)
    tokens = max(MARGIN_MIN, math.ceil(MARGIN_SHARE * w.usage.output_tokens))
    margin = write.estimate_usd(spec, BAL, 0, tokens) * rate
    return round(max(got, min(hold_inr, got + margin)), 4)


def judge(
    w: write.Written, spec: BrainSpec, ctx: checks.Context
) -> tuple[tuple[CheckCode, ...], dict[SectionId, str]]:
    """The reply's refusals before the checks (D1, L10), then the six checks (D10)."""
    if w.tier != BAL:
        return ("tier",), {}
    if w.model != write.model_of(spec) or w.provider == OFFLINE:
        return ("model",), {}
    if not w.text.strip():
        return ("empty",), {}
    if not w.complete:
        return ("incomplete",), {}
    sections = checks.parse(w.text)
    if sections is None:
        return ("shape",), {}
    return checks.check(sections, ctx), sections


class Runner:
    def __init__(
        self,
        ctx: WriterContext,
        store: WriterStore,
        ledger: caps_mod.WriterCaps,
        scrub: Scrubber,
        *,
        timer: Callable[[], float] | None = None,
    ) -> None:
        self.ctx, self.store, self.ledger, self.scrub = ctx, store, ledger, scrub
        self._timer = timer
        self._trees: dict[str, dict[str, str]] = {}
        self._packs: dict[tuple[str, str], packs.Pack] = {}  # this release's packs, built once

    def now_s(self) -> float:
        return self._timer() if self._timer is not None else asyncio.get_running_loop().time()

    def tree(self, rid: str) -> dict[str, str]:
        """The current release's readable source files (cached by release)."""
        if rid not in self._trees:
            self._trees = {rid: packs.read_source(self.ctx.source.read("source"))}
            self._packs = {}
        return self._trees[rid]

    def left(self, start: float, budget: float, on_clock: bool) -> float:
        tl = ticks.time_left() if on_clock else None
        return tl if tl is not None else budget - (self.now_s() - start)

    @staticmethod
    def need(seconds: tuple[float, ...], on_clock: bool) -> float | None:
        if seconds:
            return p90(seconds) + SPARE_S
        return None if on_clock else STEP_CALL_TIMEOUT_S

    async def lease(self, uid: str, on_clock: bool) -> str:
        budget = JOB_BUDGET_S if on_clock else STEP_BUDGET_S
        holder = await self.store.lease(uid, budget + LEASE_EXTRA_S)
        if holder is None:
            raise Busy()
        return holder

    def context(self, ip: IndexedPage, facts: FactPack, canary: str) -> checks.Context:
        emails = self.ctx.owner_emails
        return checks.Context(page=ip, facts=facts, scrub=self.scrub, emails=emails, canary=canary)

    def first_turn(self, ip: IndexedPage, facts: FactPack, rid: str) -> tuple[list[Any], str]:
        canary = "cn" + hashlib.sha256(f"{rid}:{ip.id}".encode()).hexdigest()[:16]
        reserve = len(prompts.head(ip, canary).encode("utf-8"))
        tree = self.tree(rid)
        if (rid, ip.id) not in self._packs:
            self._packs[(rid, ip.id)] = packs.build(ip, facts, tree, self.scrub, reserve=reserve)
        return prompts.first(ip, self._packs[(rid, ip.id)], canary), canary

    async def page(
        self, uid: str, run: Run, doc: WriterDoc, item: Item, facts: FactPack,
        left: Callable[[], float], need: float,
    ) -> Out:  # fmt: skip
        """One page: its first draft and at most one redraft (D10), each call within the time
        left; a redraft that doesn't fit is not made (the page keeps its previous text)."""
        spec, router = self.ctx.brains.get(item.brain), self.ctx.brains.router_for(item.brain)
        if await router.blocked_now():
            return Out(stop="no_ai")
        msgs, canary = self.first_turn(item.page, facts, run.release)
        out = Out()
        for attempt in (1, 2):
            if attempt == 2 and left() < need:
                return out
            timeout = min(STEP_CALL_TIMEOUT_S, left() - TIMEOUT_SPARE_S)
            got = await self.call(uid, run, doc, spec, router, item, msgs, timeout)
            out.calls, out.inr = out.calls + got.calls, out.inr + got.inr
            out.seconds += got.seconds
            if got.stop or got.wait or got.written is None:
                return Out(**{**out.__dict__, "stop": got.stop, "wait": got.wait})
            codes, sections = judge(got.written, spec, self.context(item.page, facts, canary))
            out.attempt, out.written, out.codes, out.sections = (
                attempt,
                got.written,
                codes,
                sections,
            )
            if not codes or attempt == 2 or set(codes) & set(PRE_CHECKS):
                return out
            out.first = codes
            msgs = prompts.redraft(msgs, got.written.text, codes)
        return out

    async def call(
        self, uid: str, run: Run, doc: WriterDoc, spec: BrainSpec, router: Any, item: Item,
        msgs: list[Any], timeout: float,
    ) -> Out:  # fmt: skip
        """One call: hold, write, settle (D8). A refused hold stops the run before it is sent."""
        try:
            m = await caps_mod.money(self.ctx.billing, uid)
            hold = (
                estimate.hold_inr(spec, prompts.sent_bytes(msgs), m.rate)
                if write.paid(spec)
                else 0.0
            )
            pct = (
                doc.pick.confirmed.caps.limit_pct if doc.pick.confirmed.brain else Caps().limit_pct
            )
            month = doc.pick.confirmed.caps.month if run.kind == "update" else None
            held = await self.ledger.reserve(
                uid, call_id=f"wc_{secrets.token_hex(8)}", page=item.page.id, run=run.kind,
                key=run_key(run), hold_inr=hold, cap_inr=cap_of(run, doc), month_cap=month,
                gate=caps_mod.Gate(used_inr=m.used_inr, limit_inr=m.limit_inr, pct=pct),
            )  # fmt: skip
        except caps_mod.CapRefused as no:
            return Out(wait="busy") if no.code == "busy" else Out(stop=no.code)
        try:
            w = await write.write_text(
                router, tier=BAL, system=prompts.SYSTEM, system_dynamic=None, messages=msgs,
                max_tokens=MAX_TOKENS, timeout_s=timeout,
            )  # fmt: skip
        except Exception:  # noqa: BLE001 - WriterUnavailable, BrainOff: nothing was received
            await self.ledger.release(held)
            return Out(stop="no_ai") if await router.blocked_now() else Out(wait="unavailable")
        inr = bill(spec, w, held.inr, m.rate)
        await self.ledger.settle(held, inr)
        if inr > 0:
            await self.ctx.billing.record(uid, "book", inr / m.rate)
        await self.seconds(uid, spec.id, w.seconds)
        over = write.paid(spec) and inr > held.inr + OVER_EPS_INR
        return Out(
            calls=1, inr=inr, seconds=w.seconds, written=w, stop="over_hold" if over else None
        )

    async def seconds(self, uid: str, brain: str, took: float) -> None:
        def add(doc: WriterDoc) -> tuple[WriterDoc, None]:
            kept = (*doc.seconds.get(brain, ()), round(took, 2))[-SECONDS_KEPT:]
            return doc.model_copy(update={"seconds": {**doc.seconds, brain: kept}}), None

        await self.store.change(uid, add)


def trial_items(facts: FactPack, brains: tuple[str, ...], have: set[int]) -> list[Item]:
    """The trial's pages, page by page, each brain in turn (nn: brain-major, 1-5 then 6-10)."""
    out: list[Item] = []
    for p_i, pid in enumerate(TRIAL_PAGES):
        ip = facts.page(pid)
        for b_i, brain in enumerate(brains):
            nn = b_i * len(TRIAL_PAGES) + p_i + 1
            if ip is not None and nn not in have:
                out.append(Item(ip, brain, nn))
    return out


__all__ = [
    "ACTIVE",
    "CLOCK_CALLS",
    "Busy",
    "Item",
    "Out",
    "Runner",
    "bill",
    "cap_of",
    "judge",
    "p90",
    "run_key",
    "trial_brains",
    "trial_items",
]
