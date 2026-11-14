# tests/test_r14_d_upi.py -- R14 D13 (6): the prepared-payment cap is ONE figure, the deploy-time
# setting `bill_pay_cap_inr` (default ₹1,00,000, bounds 1 to 1,00,000: he can only lower it), read
# by every user of the two old constants (`helpers/sources.py` `MAX_UPI_AMOUNT_PAISE`,
# `helpers/today/models.py` `PAY_CAP_PAISE`, which are now the ceiling only). Before R14 the
# setting existed but nothing read it: a lowered cap still let ₹1,00,000 through.
from __future__ import annotations

from collections.abc import Iterator

import pytest
from annotated_types import Le

from jarvis.config import Settings, get_settings
from jarvis.helpers import sources
from jarvis.helpers.today import models, upi
from jarvis.helpers.today.models import BillRefused, inr, pay_cap_paise
from jarvis.helpers.today.tools import _check_prepare

ENV = "JARVIS_BILL_PAY_CAP_INR"


@pytest.fixture
def lowered(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    monkeypatch.setenv(ENV, "5000")
    get_settings.cache_clear()
    yield 5000 * 100
    monkeypatch.delenv(ENV)
    get_settings.cache_clear()


def test_the_two_constants_are_one_ceiling_and_the_settings_bound() -> None:
    assert models.PAY_CAP_PAISE == sources.MAX_UPI_AMOUNT_PAISE == 1_00_000 * 100
    bound = next(m for m in Settings.model_fields["bill_pay_cap_inr"].metadata if isinstance(m, Le))
    assert bound.le * 100 == sources.MAX_UPI_AMOUNT_PAISE


def test_by_default_the_cap_is_the_ceiling() -> None:
    assert pay_cap_paise(Settings(_env_file=None)) == models.PAY_CAP_PAISE
    assert upi.amount_text(models.PAY_CAP_PAISE) == "100000.00"


def test_a_lowered_cap_is_read_by_the_link_and_the_card_check(lowered: int) -> None:
    assert pay_cap_paise() == lowered
    assert upi.amount_text(lowered) == "5000.00"
    with pytest.raises(BillRefused) as over:
        upi.amount_text(lowered + 1)
    assert inr(lowered) in str(over.value) and "1,00,000" not in str(over.value)
    with pytest.raises(BillRefused):
        upi.upi_link(pa="test@okfake", pn="Power Co", paise=lowered + 100, tn="x")
    with pytest.raises(BillRefused):
        _check_prepare({"amount": "5000.01"})  # the tool refuses before any card
    _check_prepare({"amount": "5000"})


def test_the_cap_never_rises_above_the_ceiling() -> None:
    s = Settings(_env_file=None).model_copy(update={"bill_pay_cap_inr": 10**7})  # past the bound
    assert pay_cap_paise(s) == models.PAY_CAP_PAISE


def test_the_cap_is_one_rupee_at_the_least() -> None:
    s = Settings(_env_file=None, bill_pay_cap_inr=1)
    assert pay_cap_paise(s) == 100
    with pytest.raises(BillRefused):
        upi.amount_text(101, cap=pay_cap_paise(s))
