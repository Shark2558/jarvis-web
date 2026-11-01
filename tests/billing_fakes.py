# tests/billing_fakes.py — slice 7b helpers: a mock brain that costs money, a paid + a free brain
# registry, and Docs that fail on purpose. A plain module (not conftest) so test files import it.
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from jarvis.billing import Billing, BudgetStore, FxRates, UsageMeter
from jarvis.llm.base import Completion
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.pricing import cost_usd
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import Doc, Docs, DocTx, MemoryDocs, Op, Query, T

PAID_TIERS = {
    ModelTier.FAST: "claude-haiku-5-5",
    ModelTier.BALANCED: "claude-sonnet-5-5",
    ModelTier.STRONG: "claude-opus-5-5",
}
FREE_TIERS = {
    ModelTier.FAST: "gemini-3.5-flash-lite",
    ModelTier.BALANCED: "gemini-3.8-flash",
    ModelTier.STRONG: "gemini-3.8-flash",
}
UNPRICED_TIERS = {t: "llama-local-70b" for t in ModelTier}  # a custom brain: cost unknown
RATE = 95.24  # the default rate; the fx client never fetches in these tests
UID = "u_owner"
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)  # 11:30 IST, mid-November


@dataclass
class PricedMock(MockProvider):
    """MockProvider whose completions cost money: a fixed amount per call when `per_call` is
    set, else the price table's cost of the mock's own token estimate."""

    per_call: float | None = None
    name: str = "priced-mock"

    async def complete(self, **kw: object) -> Completion:  # type: ignore[override]
        c = await super().complete(**kw)  # type: ignore[arg-type]
        cost = self.per_call if self.per_call is not None else cost_usd(c.model, c.usage)
        return c.model_copy(update={"cost_usd": cost})


class Clock:
    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def registry(
    paid: MockProvider | None = None,
    free: MockProvider | None = None,
    *,
    default: str = "anthropic",
) -> BrainRegistry:
    specs = [
        BrainSpec(id="anthropic", label="Claude", provider=paid or PricedMock(), tiers=PAID_TIERS),
        BrainSpec(
            id="gemini",
            label="Gemini (free)",
            provider=free or PricedMock(),
            tiers=FREE_TIERS,
            trains_on_content=True,
        ),
        BrainSpec(id="custom", label="Local", provider=PricedMock(), tiers=UNPRICED_TIERS),
    ]
    return BrainRegistry(specs, default_id=default)


def billing(
    brains: BrainRegistry,
    *,
    docs: Docs | None = None,
    clock: Callable[[], datetime] | None = None,
    tz: str = "Asia/Kolkata",
) -> Billing:
    d = docs if docs is not None else MemoryDocs()
    clk = clock or Clock()
    return Billing(
        fx=FxRates(docs=None, default_rate=RATE, http=None, clock=clk),
        meter=UsageMeter(d, tz=tz),
        budgets=BudgetStore(d),
        brains=brains,
        clock=clk,
    )


class BrokenDocs(MemoryDocs):
    """MemoryDocs whose reads, transactions or both raise (a Firestore outage)."""

    def __init__(self, *, fail_reads: bool = False, fail_tx: bool = False) -> None:
        super().__init__()
        self.fail_reads = fail_reads
        self.fail_tx = fail_tx
        self.tx_calls = 0

    async def get(self, path: str) -> Doc | None:
        if self.fail_reads:
            raise RuntimeError("firestore unavailable")
        return await super().get(path)

    async def query(self, q: Query) -> list[tuple[str, Doc]]:
        if self.fail_reads:
            raise RuntimeError("firestore unavailable")
        return await super().query(q)

    async def write(self, ops: Sequence[Op]) -> None:
        await super().write(ops)

    async def transaction(self, fn: Callable[[DocTx], Awaitable[T]]) -> T:
        self.tx_calls += 1
        if self.fail_tx:
            raise RuntimeError("firestore transaction aborted")
        return await super().transaction(fn)
