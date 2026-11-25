# tests/test_r64_i1_unpriced.py -- R6.4 I1 (docs/plans/r6-4-book-look.md D9; C2's gap 4): a
# background call on a brain whose price JARVIS doesn't know is never ₹0. The background callers
# (recipes, the brief, understood-as, the eyes, the Book's talk, people research, memory learning)
# pass `record` a cost only, no reply: on a brain with no known price that cost is 0, and it used
# to stop there. Now it counts as "price unknown" the way a chat reply does: its tokens when the
# caller passed them, otherwise one call at `pricing.UNREPORTED_CALL` (the dearest known price, an
# upper estimate); the month's `unpriced_*` counts and the limit's `counted_inr` include it. A brain
# priced at ₹0, a paid one with nothing spent, a provider that calls no vendor and a label that
# names no brain are not counted. The CLI says "price unknown" for such a reply, never ₹0.00.
from __future__ import annotations

from dataclasses import dataclass

import pytest
from billing_fakes import RATE, UID, PricedMock, billing, registry
from memory_fakes import extraction, rig, session_with
from research_fakes import FakeModel, FakeSearcher, fixed_mode

from jarvis.billing import BudgetPatch, BudgetReached
from jarvis.cli import reply_meta
from jarvis.core.models import ChatResponse
from jarvis.llm.base import Usage
from jarvis.llm.pricing import UNREPORTED_CALL, dearest, priced_at
from jarvis.people.model import BrainPeopleModel
from jarvis.people.research import PeopleService, ScopeRefused
from jarvis.recall.learning import LearnStatus
from jarvis.recall.models import SettingsPatch

ONE_CALL_INR = priced_at(dearest(), UNREPORTED_CALL) * RATE


@dataclass(frozen=True)
class _Used:
    model: str
    usage: Usage | None
    provider: str = ""
    offline: bool = False


async def _month(bill):  # type: ignore[no-untyped-def]
    return await bill.meter.get(UID, bill.meter.month_of(bill.clock()))


def test_the_unreported_call_is_an_upper_estimate_never_nothing() -> None:
    assert UNREPORTED_CALL.input_tokens >= 3_000 and UNREPORTED_CALL.output_tokens >= 700
    assert ONE_CALL_INR > 1.0  # a few rupees a call at the dearest known price


async def test_a_background_call_on_an_unpriced_brain_counts_one_call_at_the_estimate() -> None:
    bill = billing(registry())
    assert await bill.record(UID, "custom", 0.0) == 0.0  # the call itself has no price
    m = await _month(bill)
    assert m.calls == 0 and m.inr_total == 0.0
    assert m.unpriced_calls == 1 and m.unpriced_tokens == 0  # no tokens were reported
    assert m.unpriced_inr == pytest.approx(ONE_CALL_INR) and m.counted_inr == pytest.approx(
        ONE_CALL_INR
    )
    view = await bill.usage(UID)
    assert view.unpriced_calls == 1 and view.unpriced_inr == pytest.approx(round(ONE_CALL_INR, 2))


async def test_a_reply_without_usage_or_tokens_counts_one_call_at_the_estimate() -> None:
    bill = billing(registry())
    await bill.record(UID, "custom", 0.0, used=_Used("llama-local-70b", None))
    await bill.record(UID, "custom", 0.0, used=_Used("llama-local-70b", Usage()))
    m = await _month(bill)
    assert m.unpriced_calls == 2 and m.unpriced_tokens == 0
    assert m.unpriced_inr == pytest.approx(2 * ONE_CALL_INR)


async def test_reported_tokens_are_still_counted_as_tokens() -> None:
    bill = billing(registry())
    usage = Usage(input_tokens=1_000, output_tokens=100)
    await bill.record(UID, "custom", 0.0, used=_Used("llama-local-70b", usage))
    m = await _month(bill)
    assert m.unpriced_calls == 1 and m.unpriced_tokens == 1_100
    assert m.unpriced_inr == pytest.approx(priced_at(dearest(), usage) * RATE)


@pytest.mark.parametrize("brain", ["gemini", "anthropic", "memory", "nobody"])
async def test_free_paid_and_unknown_labels_are_not_counted_as_unpriced(brain: str) -> None:
    bill = billing(registry())
    await bill.record(UID, brain, 0.0)  # free tier; paid with nothing spent; not a brain id
    m = await _month(bill)
    assert m.unpriced_calls == 0 and m.calls == 0 and m.counted_inr == 0.0


async def test_the_free_providers_and_the_laptops_answer_are_still_never_counted() -> None:
    bill = billing(registry())
    await bill.record(UID, "custom", 0.0, used=_Used("qwen2.5:3b", None, "local_brain"))
    await bill.record(UID, "custom", 0.0, used=_Used("qwen2.5:3b", None, "x", offline=True))
    assert (await _month(bill)).unpriced_calls == 0


async def test_background_unpriced_use_counts_towards_the_limit() -> None:
    bill = billing(registry())
    await bill.budgets.update(UID, BudgetPatch(monthly_limit_inr=1))
    await bill.ensure_allowed(UID, bill.brains.get("custom"))  # nothing counted yet
    await bill.record(UID, "custom", 0.0)  # one background call, ≈ ₹5 at the estimate
    with pytest.raises(BudgetReached):
        await bill.ensure_allowed(UID, bill.brains.get("custom"))
    with pytest.raises(BudgetReached):  # one limit: the paid brain stops too
        await bill.ensure_allowed(UID, bill.brains.get("anthropic"))
    assert (await bill.usage(UID)).reached


async def test_a_learning_run_on_an_unpriced_brain_is_counted_as_price_unknown() -> None:
    r = rig(private=PricedMock(per_call=0.0))  # a vendor JARVIS has no price for ("mock-fast")
    await r.svc.update_settings(UID, SettingsPatch(learn=True, confirm_spend=True))
    r.private.script(extraction([{"text": "Lives in Kochi", "category": "places"}]))
    res = await r.svc.learn(UID, session_with("I live in Kochi", "My son is 6", "Be brief"), r.spec)
    assert res.status is LearnStatus.DONE and res.cost_usd == 0.0
    m = await _month(r.billing)
    assert m.calls == 0 and m.unpriced_calls == 1 and m.unpriced_inr == pytest.approx(ONE_CALL_INR)


async def test_a_learning_run_on_a_free_provider_is_not_counted() -> None:
    r = rig()  # the mock provider calls no vendor
    await r.svc.update_settings(UID, SettingsPatch(learn=True, confirm_spend=True))
    r.private.script(extraction([{"text": "Lives in Kochi", "category": "places"}]))
    await r.svc.learn(UID, session_with("I live in Kochi", "My son is 6", "Be brief"), r.spec)
    assert (await _month(r.billing)).unpriced_calls == 0


async def test_a_dossier_on_an_unpriced_brain_is_one_price_unknown_entry() -> None:
    brains = registry(default="custom")
    bill = billing(brains)
    await BrainPeopleModel(brains, bill).record(UID, 0.0)
    m = await _month(bill)
    assert m.unpriced_calls == 1 and m.unpriced_inr == pytest.approx(ONE_CALL_INR)


async def test_research_that_asked_the_model_records_its_dossier_even_at_zero() -> None:
    model = FakeModel(cost=0.0)  # the brain behind it has no known price: its replies cost "0"
    svc = PeopleService(FakeSearcher(), model, mode=fixed_mode("ai"))
    await svc.research(UID, "Satya Nadella", "Microsoft")
    assert len(model.classifier_calls) == 1 and model.records == [(UID, 0.0)]


@pytest.mark.parametrize(("label", "cost"), [("private", 0.002), ("unclear", 0.0)])
async def test_a_classifier_that_refuses_is_still_billed_once(label: str, cost: float) -> None:
    """R6.4 review M-2: the classifier's call was made (and charged) even when it refuses: its
    cost, or a ₹0 entry billing judges as "price unknown", is recorded before the refusal."""
    model = FakeModel(label=label, cost=cost)
    svc = PeopleService(FakeSearcher(), model, mode=fixed_mode("ai"))
    with pytest.raises(ScopeRefused):
        await svc.research(UID, "Satya Nadella", "Microsoft")
    assert len(model.classifier_calls) == 1 and model.composer_calls == []
    assert model.records == [(UID, pytest.approx(cost))]


async def test_a_classifier_that_fails_records_nothing() -> None:
    model = FakeModel(classifier_raises=True)  # no reply came back: nothing to bill
    svc = PeopleService(FakeSearcher(), model, mode=fixed_mode("ai"))
    with pytest.raises(ScopeRefused):
        await svc.research(UID, "Satya Nadella", "Microsoft")
    assert model.records == []


async def test_research_with_no_model_call_records_nothing() -> None:
    model = FakeModel(cost=0.0)
    svc = PeopleService(FakeSearcher(), model, mode=fixed_mode("none"))
    await svc.research(UID, "Satya Nadella", "Microsoft")
    assert model.calls == [] and model.records == []


# ---- the CLI (`jarvis chat`): "price unknown", never ≈ ₹0.00 ------------------------------------
def _resp(**kw: object) -> ChatResponse:
    base: dict[str, object] = {
        "session_id": "s1", "reply": "Hello, Sir.", "model": "llama-local-70b", "brain": "custom",
        "usage": Usage(input_tokens=10, output_tokens=5), "cost_usd": 0.0, "cost_inr": 0.0,
        "latency_ms": 12, "trace_id": "t1", "turn_count": 2,
    }  # fmt: skip
    return ChatResponse.model_validate({**base, **kw})


def test_the_cli_says_price_unknown_for_an_unpriced_reply() -> None:
    line = reply_meta(_resp(unpriced=True))
    assert line == "[llama-local-70b · 15 tok · price unknown · 12 ms]"
    assert "₹" not in line


def test_the_cli_prices_a_priced_reply_in_rupees() -> None:
    line = reply_meta(_resp(model="claude-haiku-5-5", cost_usd=0.01, cost_inr=0.95))
    assert line == "[claude-haiku-5-5 · 15 tok · ≈ ₹0.95 · 12 ms]"
