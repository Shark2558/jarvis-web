# src/jarvis/buildbook/writer/estimate.py
"""R6.3 D8 (L4, L6): what writing costs, in rupees, before anything is spent.

From the real packs' sizes (UTF-8 bytes) under three assumptions: low / mid / high = bytes / 4,
/ 3, / 2.5 a token in; 2,200 / 3,000 / 3,500 tokens out a page; 15 / 25 / 30 % of pages redrafted,
each redraft sending about 3,000 tokens more (the failed draft and its failures). The fixed system
prompt counts at the cache-write price. Prices only through `jarvis.llm.write` (the Book reads no
model id or price); the day's rate from billing. Shown as "about Rs <mid> (Rs <low>-<high>)":
"about" is the mid rounded by `model.about_inr`, the same rule everywhere. The hold (one call's
upper bound): `worst_usd` of the bytes sent / 2.5, the system prompt and `MAX_TOKENS` out.
The estimate's id is bound to every input, the release included (M5: a YES never carries).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import jarvis.llm.write as write
from jarvis.buildbook.writer import carry, texts
from jarvis.buildbook.writer.caps import CapRefused, money
from jarvis.buildbook.writer.http import Estimate
from jarvis.buildbook.writer.model import (
    BYTES_PER_TOKEN_WORST,
    GST_NOTE,
    MAX_TOKENS,
    SYSTEM_TOKENS,
    TRIAL_PAGES,
    Caps,
    PagesFile,
    RunKind,
    WriterDoc,
    about_inr,
)
from jarvis.buildbook.writer.ports import WriterContext
from jarvis.buildbook.writer.store import WriterStore
from jarvis.llm.brains import BrainSpec
from jarvis.llm.router import ModelTier

BAL = ModelTier.BALANCED
# (bytes a token, output tokens, share redrafted): low, mid, high. R6.3 hotfix 1: one notch denser
# than 4.0/3.0/2.5, as Claude billed his first full pack (Rs 11.83: 2.2 bytes a token at 3,000 out).
ASSUME: tuple[tuple[float, int, float], ...] = (
    (3.0, 2_200, 0.15),
    (2.2, 3_000, 0.25),
    (1.8, 3_500, 0.30),
)
REDRAFT_EXTRA_TOKENS = 3_000
CALL_SECONDS = (30, 50)  # a page call on the step (Estimate; the trial measures it, D5)


def trial_brains(specs: list[BrainSpec]) -> tuple[str, ...]:
    """The trial's brains: the first paid one offered and the first free (training) one."""
    offered = [s for s in specs if write.offered(s)]
    paid = next((s.id for s in offered if write.paid(s)), None)
    free = next((s.id for s in offered if s.trains_on_content), None)
    return tuple(b for b in (paid, free) if b is not None)


def price_of(spec: BrainSpec) -> float:
    """A fingerprint of the brain's balanced price (a million of each token kind), no literal."""
    return write.estimate_usd(spec, BAL, 1_000_000, 1_000_000, system_tokens=1_000_000)


def _page_usd(spec: BrainSpec, nbytes: int, per: float, out: int, frac: float) -> float:
    one = write.estimate_usd(spec, BAL, math.ceil(nbytes / per), out, system_tokens=SYSTEM_TOKENS)
    extra = write.estimate_usd(spec, BAL, REDRAFT_EXTRA_TOKENS, 0)
    return one * (1 + frac) + extra * frac


def page_inr(spec: BrainSpec, nbytes: int, rate: float) -> float:
    per, out, frac = ASSUME[1]
    return round(_page_usd(spec, nbytes, per, out, frac) * rate, 2)


def tokens_worst(sent_bytes: int) -> int:
    return math.ceil(max(0, sent_bytes) / BYTES_PER_TOKEN_WORST)


def hold_inr(spec: BrainSpec, sent_bytes: int, rate: float) -> float:
    usd = write.worst_usd(spec, BAL, tokens_worst(sent_bytes), MAX_TOKENS, system_cap=SYSTEM_TOKENS)
    return round(usd * rate, 2)


def _id(
    run: RunKind, spec: BrainSpec, sizes: Sequence[int], rate: float, cap: int, rid: str
) -> str:
    raw = json.dumps(
        [run, spec.id, list(sizes), price_of(spec), rate, ASSUME, cap, rid], sort_keys=True
    )
    return "we_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def estimate(
    *,
    run: RunKind,
    spec: BrainSpec,
    sizes: Sequence[int],
    rate: float,
    cap: int,
    release: str,
    brains: int = 1,
    sent_to: tuple[str, ...] = (),
) -> Estimate:
    """The estimate of writing pages of these pack sizes with `spec` (rupees only)."""
    low, mid, high = (
        sum(_page_usd(spec, n, per, out, frac) for n in sizes) * rate for per, out, frac in ASSUME
    )
    calls = len(sizes) * max(1, brains)
    paid = write.paid(spec)
    return Estimate(
        id=_id(run, spec, sizes, rate, cap, release),
        run=run,
        brain=spec.id,
        pages=len(sizes),
        low=math.floor(low),
        mid=about_inr(mid),
        high=math.ceil(high),
        hold=hold_inr(spec, max(sizes, default=0), rate),
        cap=cap,
        minutes_low=math.ceil(calls * (1 + ASSUME[0][2]) * CALL_SECONDS[0] / 60),
        minutes_high=math.ceil(calls * (1 + ASSUME[2][2]) * CALL_SECONDS[1] / 60),
        gst_note=GST_NOTE.format(maker=write.maker(spec)) if paid else "",
        sent_to=sent_to,
    )


__all__ = [
    "Estimates",
    "trial_brains",
    "ASSUME",
    "CALL_SECONDS",
    "REDRAFT_EXTRA_TOKENS",
    "estimate",
    "hold_inr",
    "page_inr",
    "price_of",
    "tokens_worst",
]


class Estimates:
    """The estimates the routes show and the runs bind to (`GET .../estimate?run=`), from the
    real packs' sizes (cached a release), the day's rate and his granted caps."""

    def __init__(
        self,
        ctx: WriterContext,
        store: WriterStore,
        first_turn: Callable[..., tuple[list[Any], str]],
        pages_file: Callable[[str, str], Awaitable[PagesFile | None]],
    ) -> None:
        self.ctx, self.store, self.first_turn, self.pages_file = ctx, store, first_turn, pages_file
        self._sizes: dict[tuple[str, str], int] = {}

    async def rate(self, uid: str) -> float:
        try:
            return (await money(self.ctx.billing, uid)).rate
        except CapRefused:
            raise texts.WriterRefused("unavailable") from None

    def rid(self) -> str:
        current = self.ctx.source.current()
        if current is None:
            raise texts.WriterRefused("no_page")
        return current.id

    def size(self, rid: str, page_id: str) -> int:
        """A page's first call in UTF-8 bytes (its real pack), cached a release."""
        if (rid, page_id) not in self._sizes:
            facts = self.ctx.source.facts()
            ip = facts.page(page_id)
            msgs = self.first_turn(ip, facts, rid)[0] if ip is not None else []
            self._sizes[(rid, page_id)] = sum(len(m.text().encode("utf-8")) for m in msgs)
        return self._sizes[(rid, page_id)]

    async def sizes(self, rid: str, ids: Sequence[str]) -> list[int]:
        """The pages' first calls in UTF-8 bytes; the packs not built yet are built in a worker
        thread, so the event loop never waits on them (review M-4)."""
        missing = [i for i in ids if (rid, i) not in self._sizes]
        if missing:
            await asyncio.to_thread(lambda: [self.size(rid, i) for i in missing])
        return [self.size(rid, i) for i in ids]

    def spec(self, doc: WriterDoc) -> BrainSpec:
        chosen = doc.pick.confirmed.brain
        if chosen is not None:
            return self.ctx.brains.get(chosen)
        brains = trial_brains(self.ctx.brains.list())
        if not brains:
            raise texts.WriterRefused("no_key")
        return self.ctx.brains.get(brains[0])

    @staticmethod
    def sent_to(specs: Sequence[BrainSpec]) -> tuple[str, ...]:
        words = [texts.SENT_WORDS.format(label=s.label, maker=write.maker(s)) for s in specs]
        words += [
            texts.TRAINS_WORDS.format(label=s.label, maker=write.maker(s))
            for s in specs
            if s.trains_on_content
        ]
        return tuple(words)

    async def for_update(self, uid: str, ids: tuple[str, ...], rid: str) -> Estimate:
        doc = await self.store.doc(uid)
        spec, rate = self.spec(doc), await self.rate(uid)
        return estimate(
            run="update", spec=spec, sizes=await self.sizes(rid, ids), rate=rate,
            cap=doc.pick.confirmed.caps.release, release=rid, sent_to=self.sent_to([spec]),
        )  # fmt: skip

    async def of(self, uid: str, kind: RunKind) -> Estimate:
        doc, rid = await self.store.doc(uid), self.rid()
        if kind == "update":
            ready = doc.update_ready
            if ready is None or ready.release != rid:
                raise texts.WriterRefused("nothing_to_update")
            return await self.for_update(uid, ready.pages, rid)
        rate, facts = await self.rate(uid), self.ctx.source.facts()
        if kind == "trial":
            specs = [self.ctx.brains.get(b) for b in trial_brains(self.ctx.brains.list())]
            if not specs:
                raise texts.WriterRefused("no_key")
            ids = [p for p in TRIAL_PAGES if facts.page(p) is not None]
            return estimate(
                run="trial", spec=specs[0], sizes=await self.sizes(rid, ids), rate=rate,
                cap=Caps().trial, release=rid, brains=len(specs), sent_to=self.sent_to(specs),
            )  # fmt: skip
        spec = self.spec(doc)
        ids2 = carry.to_write(facts, await self.pages_file(uid, rid))
        cap = doc.pick.confirmed.caps.first if doc.pick.confirmed.brain else Caps().first
        return estimate(
            run="first", spec=spec, sizes=await self.sizes(rid, ids2), rate=rate, cap=cap,
            release=rid, sent_to=self.sent_to([spec]),
        )  # fmt: skip
