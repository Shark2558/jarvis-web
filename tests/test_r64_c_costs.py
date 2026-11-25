# tests/test_r64_c_costs.py — R6.4 D9 (workbook row 393): Costs counts paid Gemini and unpriced
# models. With `gemini_paid_tier` off nothing changes (Gemini ₹0). With it on, Gemini replies are
# priced from Google's published paid-tier prices. A model with no known price (any vendor) is
# never ₹0: the reply is counted as "price unknown" with its tokens, the usage view says how many,
# and the monthly limit counts it at the dearest price JARVIS knows (an upper estimate), so a paid
# vendor without a price list can't run past the owner's ₹ limit.
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from billing_fakes import NOW, RATE, UID, UNPRICED_TIERS, PricedMock, billing, put_raw, registry
from pydantic import SecretStr

from jarvis.billing import Billing, BudgetPatch, BudgetReached
from jarvis.billing.ledger import counts_of
from jarvis.billing.meter import MonthUsage, UsageUnreadable, decode, encode
from jarvis.billing.service import metered_brain
from jarvis.config import LLMBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.channel import mark_offline
from jarvis.core.models import ChatRequest
from jarvis.llm.base import Completion, Usage
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.pricing import (
    GEMINI_PAID_PRICES,
    PRICES,
    Price,
    cost_usd,
    dearest,
    is_paid,
    is_priced,
    price_unknown,
    use_gemini_paid_tier,
)
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.skills.ports import LedgerCall
from jarvis.storage.docs import MemoryDocs

ROOT = Path(__file__).resolve().parents[1]
MONTH = "2026-11"
MTOK = 1_000_000


@dataclass(frozen=True)
class _Used:
    model: str
    usage: Usage | None
    provider: str = ""
    offline: bool = False


@pytest.fixture
def paid_gemini() -> Iterator[None]:
    use_gemini_paid_tier(True)
    try:
        yield
    finally:
        use_gemini_paid_tier(False)


def _brain(settings: Settings, docs: MemoryDocs | None = None) -> tuple[Brain, Billing]:
    reg = registry(PricedMock(), PricedMock())
    bill = billing(reg, docs=docs)
    store = InMemorySessionStore(ttl_s=3600)
    return Brain(brains=reg, store=store, settings=settings, billing=bill), bill


def _req(brain: str, text: str = "hello") -> ChatRequest:
    return ChatRequest(message=text, user_id=UID, brain=brain)


async def _limit(bill: Billing, inr: int) -> None:
    await bill.budgets.update(UID, BudgetPatch(monthly_limit_inr=inr))


# ---- the paid-tier price table -------------------------------------------------------------------


def test_the_paid_gemini_prices_are_googles_published_ones() -> None:
    # ai.google.dev/gemini-api/docs/pricing, Standard (paid) tier, read 2026-11-25. Flash: the
    # price from 1 January 2027 (the higher of the two published); no prompt-length bands.
    assert GEMINI_PAID_PRICES == {
        "gemini-3.8-flash": Price(1.50, 7.50, 0.15, 1.50),
        "gemini-3.6-flash": Price(1.50, 7.50, 0.15, 1.50),
        "gemini-3.5-flash-lite": Price(0.30, 2.50, 0.03, 0.30),
        "gemini-3.1-flash-lite": Price(0.25, 1.50, 0.025, 0.25),
    }
    src = (ROOT / "src/jarvis/llm/pricing.py").read_text(encoding="utf-8")
    assert "https://ai.google.dev/gemini-api/docs/pricing" in src and "2026-11-25" in src


def test_every_gemini_model_in_the_table_has_a_paid_price() -> None:
    gemini = {m for m in PRICES if m.startswith("gemini-")}
    assert gemini and gemini <= set(GEMINI_PAID_PRICES)
    s = Settings(_env_file=None, env="dev")  # type: ignore[call-arg]
    for m in (s.gemini_model_fast, s.gemini_model_balanced, s.gemini_model_strong):
        assert m in GEMINI_PAID_PRICES


def test_free_tier_gemini_stays_at_zero() -> None:
    u = Usage(input_tokens=MTOK, output_tokens=MTOK)
    assert cost_usd("gemini-3.8-flash", u) == 0.0
    assert is_priced("gemini-3.8-flash") and not is_paid("gemini-3.8-flash")


def test_paid_tier_gemini_is_priced(paid_gemini: None) -> None:
    u = Usage(input_tokens=MTOK, output_tokens=MTOK, cache_read_tokens=MTOK)
    assert cost_usd("gemini-3.8-flash", u) == pytest.approx(1.50 + 7.50 + 0.15)
    assert cost_usd("gemini-3.5-flash-lite", u) == pytest.approx(0.30 + 2.50 + 0.03)
    assert is_paid("gemini-3.8-flash")
    assert cost_usd("claude-sonnet-5-5", u) == pytest.approx(2.00 + 10.00 + 0.10)  # unchanged


def test_the_registry_sets_the_table_from_gemini_paid_tier() -> None:
    def build(paid: bool) -> BrainRegistry:
        return BrainRegistry.from_settings(
            Settings(  # type: ignore[call-arg]
                _env_file=None,
                env="dev",
                llm_backend=LLMBackend.GEMINI,
                gemini_api_key=SecretStr("test-key"),
                gemini_paid_tier=paid,
            )
        )

    try:
        assert build(True).get("gemini").label == "Gemini" and is_paid("gemini-3.8-flash")
        assert metered_brain(build(True).get("gemini"))
    finally:
        reg = build(False)
    assert reg.get("gemini").label == "Gemini (free)" and not is_paid("gemini-3.8-flash")
    assert not metered_brain(reg.get("gemini"))


def test_price_unknown_is_any_model_without_a_price_except_the_free_providers() -> None:
    assert price_unknown("llama-local-70b", "openai_compat")
    assert price_unknown("some-new-model")
    assert not price_unknown("claude-haiku-5-5", "anthropic")
    assert not price_unknown("gemini-3.8-flash", "gemini")  # ₹0, but known
    assert not price_unknown("mock-balanced", "mock")  # the test/dev provider calls nobody
    assert not price_unknown("qwen2.5:3b", "local_brain")  # the owner's laptop
    top = dearest()
    assert top.input_per_mtok == max(p.input_per_mtok for p in PRICES.values())
    assert top.output_per_mtok == max(p.output_per_mtok for p in PRICES.values())


# ---- a priced paid Gemini reply: ₹ in the month and the ledger -----------------------------------


async def test_a_paid_gemini_reply_is_counted_in_rupees(
    settings: Settings, paid_gemini: None
) -> None:
    brain, bill = _brain(settings)
    r = await brain.chat(_req("gemini"))
    assert r.brain == "gemini" and r.cost_usd > 0
    assert r.cost_inr == pytest.approx(r.cost_usd * RATE, abs=1e-4)  # shown to 4 places
    m = await bill.meter.get(UID, MONTH)
    assert m.calls == 1 and m.by_brain["gemini"] == pytest.approx(r.cost_usd)
    assert m.inr_total == pytest.approx(r.cost_usd * RATE) and m.unpriced_calls == 0
    view = await bill.usage(UID)
    assert view.used_inr == pytest.approx(round(r.cost_usd * RATE, 2))
    assert [b.brain for b in view.by_brain] == ["gemini"]


async def test_a_paid_gemini_stream_is_counted_in_rupees(
    settings: Settings, paid_gemini: None
) -> None:
    brain, bill = _brain(settings)
    text = "".join([d async for d in brain.chat_stream(_req("gemini", "stream please"))])
    assert text
    m = await bill.meter.get(UID, MONTH)
    assert m.calls == 1 and m.inr_total > 0 and m.unpriced_calls == 0


def test_the_token_ledger_prices_paid_gemini_replies(paid_gemini: None) -> None:
    usage = Usage(input_tokens=1_000, output_tokens=2_000)
    done = Completion(
        text="ok",
        model="gemini-3.8-flash",
        provider="gemini",
        usage=usage,
        latency_ms=0,
        cost_usd=cost_usd("gemini-3.8-flash", usage),
    )
    c = counts_of(LedgerCall(UID, "gemini", "rules", "", (), (), done))
    assert c.usd["replies"] == pytest.approx(2_000 * 7.50 / MTOK)
    assert sum(c.usd.values()) == pytest.approx(done.cost_usd)


async def test_paid_gemini_is_stopped_at_the_limit(settings: Settings, paid_gemini: None) -> None:
    brain, bill = _brain(settings)
    await _limit(bill, 5)
    await bill.meter.add(UID, brain_id="gemini", cost_usd=0.06, cost_inr=5.0, now=NOW)
    with pytest.raises(BudgetReached):
        await brain.chat(_req("gemini"))


async def test_free_tier_gemini_is_zero_and_never_stopped(settings: Settings) -> None:
    brain, bill = _brain(settings)
    await _limit(bill, 1)
    await bill.meter.add(UID, brain_id="anthropic", cost_usd=1.0, cost_inr=95.24, now=NOW)
    r = await brain.chat(_req("gemini"))
    assert r.reply and r.cost_usd == 0.0
    m = await bill.meter.get(UID, MONTH)
    assert m.calls == 1 and "gemini" not in m.by_brain and m.unpriced_calls == 0


# ---- a model with no known price -----------------------------------------------------------------


async def test_an_unpriced_reply_is_counted_as_price_unknown(settings: Settings) -> None:
    brain, bill = _brain(settings)
    await brain.chat(_req("custom"))
    m = await bill.meter.get(UID, MONTH)
    assert m.calls == 0 and m.inr_total == 0.0  # not in the ₹ total: its price isn't known
    assert m.unpriced_calls == 1 and m.unpriced_tokens > 0
    assert m.unpriced_inr > 0 and m.counted_inr == pytest.approx(m.unpriced_inr)
    view = await bill.usage(UID)
    assert view.used_inr == 0.0
    assert view.unpriced_calls == 1 and view.unpriced_tokens == m.unpriced_tokens
    assert view.unpriced_inr == pytest.approx(round(m.unpriced_inr, 2))


async def test_the_unpriced_count_uses_the_dearest_known_price(settings: Settings) -> None:
    _, bill = _brain(settings)
    usage = Usage(input_tokens=1_000, output_tokens=100, cache_read_tokens=500)
    got = await bill.record(UID, "custom", 0.0, used=_Used("llama-local-70b", usage))
    assert got == 0.0  # the reply itself has no price
    top = dearest()
    want = (1_000 * top.input_per_mtok + 100 * top.output_per_mtok) / MTOK
    want += 500 * top.cache_read_per_mtok / MTOK
    m = await bill.meter.get(UID, MONTH)
    assert m.unpriced_tokens == 1_600 and m.unpriced_inr == pytest.approx(want * RATE)


async def test_an_unpriced_stream_is_counted_as_price_unknown(settings: Settings) -> None:
    brain, bill = _brain(settings)
    assert "".join([d async for d in brain.chat_stream(_req("custom", "stream please"))])
    m = await bill.meter.get(UID, MONTH)
    assert m.unpriced_calls == 1 and m.unpriced_tokens > 0 and m.calls == 0


@dataclass
class _LaptopStream(PricedMock):
    """An unpriced brain whose stream the laptop answers (the fallback marks the request so)."""

    async def stream(self, **kw: object) -> AsyncIterator[str]:  # type: ignore[override]
        mark_offline()
        async for chunk in super().stream(**kw):  # type: ignore[arg-type]
            yield chunk


async def test_a_stream_the_laptop_answered_is_not_price_unknown(settings: Settings) -> None:
    """R6.4 review L-1: no vendor was called, so the stream's meter is not "price unknown" (as
    its stored reply isn't)."""
    spec = BrainSpec(id="custom", label="Local", provider=_LaptopStream(), tiers=UNPRICED_TIERS)
    reg = BrainRegistry([spec], default_id="custom")
    bill = billing(reg)
    store = InMemorySessionStore(ttl_s=3600)
    brain = Brain(brains=reg, store=store, settings=settings, billing=bill)
    assert "".join([d async for d in brain.chat_stream(_req("custom", "stream please"))])
    m = await bill.meter.get(UID, MONTH)
    assert m.unpriced_calls == 0 and m.calls == 0


async def test_the_free_providers_are_never_counted(settings: Settings) -> None:
    reg = BrainRegistry.from_settings(settings, MockProvider())
    bill = billing(reg)
    brain = Brain(brains=reg, store=InMemorySessionStore(ttl_s=60), settings=settings, billing=bill)
    await brain.chat(ChatRequest(message="hi", user_id=UID))  # mock-* models, the mock provider
    assert "".join([d async for d in brain.chat_stream(ChatRequest(message="s", user_id=UID))])
    laptop = Usage(input_tokens=500, output_tokens=50)
    await bill.record(UID, "custom", 0.0, used=_Used("qwen2.5:3b", laptop, "local_brain"))
    offline = _Used("qwen2.5:3b", laptop, "openai_compat", offline=True)  # the laptop's answer
    await bill.record(UID, "custom", 0.0, used=offline)
    m = await bill.meter.get(UID, MONTH)
    assert m.unpriced_calls == 0 and m.calls == 0


async def test_under_a_limit_an_unpriced_brain_answers_and_is_counted(settings: Settings) -> None:
    brain, bill = _brain(settings)
    await _limit(bill, 100)
    r = await brain.chat(_req("custom"))
    assert r.brain == "custom" and r.reply
    view = await bill.usage(UID)
    assert view.unpriced_calls == 1 and view.percent == pytest.approx(
        round(view.unpriced_inr / 100 * 100, 2), abs=0.01
    )


async def test_unpriced_use_counts_towards_the_limit(settings: Settings) -> None:
    brain, bill = _brain(settings)
    await _limit(bill, 10)
    await bill.meter.add_unpriced(UID, tokens=50_000, inr=12.0, now=NOW)
    with pytest.raises(BudgetReached) as ei:
        await brain.chat(_req("custom"))
    assert str(ei.value) == (
        "This month's limit of ₹10 is used up (₹0 spent, plus up to ₹12 counted for replies "
        "whose price JARVIS doesn't know). Raise it in Vitals, or switch to the free brain."
    )
    with pytest.raises(BudgetReached):  # the limit is one: the paid brain stops too
        await brain.chat(_req("anthropic"))
    assert (await brain.chat(_req("gemini"))).reply  # the free brain still answers
    view = await bill.usage(UID)
    assert view.reached and view.used_inr == 0.0 and view.remaining_inr == 0.0


async def test_an_unpriced_brain_is_stopped_once_the_limit_is_spent(settings: Settings) -> None:
    brain, bill = _brain(settings)
    await _limit(bill, 1)
    await bill.meter.add(UID, brain_id="anthropic", cost_usd=1.0, cost_inr=95.24, now=NOW)
    with pytest.raises(BudgetReached, match=r"₹95\.24 spent\)"):
        await brain.chat(_req("custom"))


async def test_with_no_limit_an_unpriced_brain_is_never_stopped(settings: Settings) -> None:
    brain, bill = _brain(settings)
    await bill.meter.add_unpriced(UID, tokens=9_000_000, inr=50_000.0, now=NOW)
    assert (await brain.chat(_req("custom"))).reply
    assert (await bill.meter.get(UID, MONTH)).unpriced_calls == 2


# ---- the stored month ----------------------------------------------------------------------------


def test_an_old_month_without_the_unpriced_fields_reads_as_none() -> None:
    m = decode({"month": MONTH, "inr_total": 3.0, "usd_total": 0.03, "calls": 2}, MONTH)
    assert (m.unpriced_calls, m.unpriced_tokens, m.unpriced_inr) == (0, 0, 0.0)
    assert m.counted_inr == 3.0


@pytest.mark.parametrize("bad", ["12", -1.0, float("nan"), True, None])
def test_an_unreadable_unpriced_total_fails_closed(bad: object) -> None:
    doc = {"month": MONTH, "inr_total": 3.0, "unpriced_inr": bad}
    if bad is None:  # stored as null: absent
        assert decode(doc, MONTH).unpriced_inr == 0.0
        return
    with pytest.raises(UsageUnreadable):
        decode(doc, MONTH)


async def test_the_unpriced_fields_survive_a_priced_write(settings: Settings) -> None:
    _, bill = _brain(settings)
    await bill.meter.add_unpriced(UID, tokens=1_000, inr=2.5, now=NOW)
    await bill.meter.add(UID, brain_id="anthropic", cost_usd=0.01, cost_inr=0.95, now=NOW)
    m = await bill.meter.get(UID, MONTH)
    assert (m.unpriced_calls, m.unpriced_tokens, m.unpriced_inr, m.calls) == (1, 1_000, 2.5, 1)
    assert m.counted_inr == pytest.approx(3.45)
    stored = encode(UID, m, NOW)
    assert stored["unpriced_inr"] == 2.5 and decode(stored, MONTH) == m


async def test_a_corrupted_unpriced_total_stops_paid_and_unpriced_calls(settings: Settings) -> None:
    docs = MemoryDocs()
    brain, bill = _brain(settings, docs)
    await _limit(bill, 100)
    await put_raw(docs, f"jarvis_usage/{UID}_{MONTH}", {"inr_total": 1.0, "unpriced_inr": "x"})
    for brain_id in ("custom", "anthropic"):
        with pytest.raises(Exception, match="spending limit"):
            await brain.chat(_req(brain_id))


def test_month_usage_plus_unpriced_is_a_new_value() -> None:
    m = MonthUsage(MONTH)
    n = m.plus_unpriced(tokens=10, inr=0.5)
    assert m.unpriced_calls == 0 and (n.unpriced_calls, n.unpriced_tokens, n.unpriced_inr) == (
        1,
        10,
        0.5,
    )


# ---- the console: "price unknown", rupees only ---------------------------------------------------


def test_the_costs_view_shows_price_unknown_in_rupees_only() -> None:
    js = (ROOT / "src/jarvis/api/static/console-usage.js").read_text(encoding="utf-8")
    for field in ("unpriced_calls", "unpriced_tokens", "unpriced_inr"):
        assert f"o.{field}" in js
    assert "Price unknown" in js and "sUnpriced" in js and "'sfine'" in js
    assert "innerHTML" not in js
    for lit in re.findall(r"'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`", js):
        assert "$" not in re.sub(r"\$\{", "", lit)
