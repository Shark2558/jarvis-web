# tests/test_people_model.py
"""The model seam behind people research (R4 D-D2): admitted, metered, private brains only,
FAST tier, no tools."""

from __future__ import annotations

from jarvis.billing import BudgetPatch
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.router import ModelTier
from jarvis.people.model import BrainPeopleModel
from tests.billing_fakes import PAID_TIERS, UID, PricedMock, billing, registry


def paid_only() -> BrainRegistry:
    return BrainRegistry(
        [BrainSpec(id="anthropic", label="Claude", provider=PricedMock(per_call=0.01),
                   tiers=PAID_TIERS)],
        default_id="anthropic",
    )  # fmt: skip


async def test_complete_asks_the_fast_tier_with_no_tools_and_returns_the_cost() -> None:
    brains = paid_only()
    provider = brains.get("anthropic").provider
    model = BrainPeopleModel(brains, billing(brains))

    reply = await model.complete(UID, "system words", "prompt words", max_tokens=50)

    call = provider.calls[0]  # type: ignore[attr-defined]
    assert call.model == PAID_TIERS[ModelTier.FAST] and call.tools is None
    assert call.messages[0].text() == "prompt words" and call.system == "system words"
    assert reply.cost_usd == 0.01


async def test_record_is_one_billing_entry_for_the_whole_dossier() -> None:
    brains = paid_only()
    bill = billing(brains)
    model = BrainPeopleModel(brains, bill)

    await model.record(UID, 0.01)

    month = bill.meter.month_of(bill.clock())
    assert (await bill.meter.get(UID, month)).inr_total > 0


async def test_a_zero_cost_dossier_records_nothing() -> None:
    brains = paid_only()
    bill = billing(brains)

    await BrainPeopleModel(brains, bill).record(UID, 0.0)

    assert (await bill.meter.get(UID, bill.meter.month_of(bill.clock()))).inr_total == 0


async def test_a_budget_paused_owner_gets_no_model() -> None:
    brains = paid_only()
    bill = billing(brains)
    await bill.budgets.update(UID, BudgetPatch(monthly_limit_inr=1, confirm_raise=True))
    await bill.record(UID, "anthropic", 1.0)  # about 95 rupees: past the limit
    model = BrainPeopleModel(brains, bill)

    assert await model.available(UID) is False


async def test_an_owner_within_budget_has_a_model() -> None:
    brains = paid_only()

    assert await BrainPeopleModel(brains, billing(brains)).available(UID) is True


async def test_a_training_brain_is_never_used() -> None:
    brains = registry(default="gemini")  # default trains on content; anthropic is private
    model = BrainPeopleModel(brains, billing(brains))

    await model.complete(UID, "s", "p", max_tokens=10)

    free = brains.get("gemini").provider
    assert free.calls == []  # type: ignore[attr-defined]


async def test_no_private_brain_means_unavailable() -> None:
    only_training = BrainRegistry(
        [BrainSpec(id="gemini", label="G", provider=PricedMock(), tiers=PAID_TIERS,
                   trains_on_content=True)],
        default_id="gemini",
    )  # fmt: skip

    assert await BrainPeopleModel(only_training, billing(only_training)).available(UID) is False

