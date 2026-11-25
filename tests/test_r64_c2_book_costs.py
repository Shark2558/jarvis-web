# tests/test_r64_c2_book_costs.py — R6.4 D9 follow-up (row 393, builder C2): the Book's cost
# table read only the free tier's Gemini prices; it now shows Gemini's paid tier too, from the same
# table (`llm/pricing.py` GEMINI_PAID_PRICES), each row labelled "paid tier" with the day the prices
# were read (GEMINI_PAID_AS_OF). Listed last, so the tour's first prices and the free rows stay.
from __future__ import annotations

import re
from pathlib import Path

import pytest

from jarvis.buildbook.gen import costs
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.llm.pricing import GEMINI_PAID_AS_OF, GEMINI_PAID_PRICES, PRICES

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def real() -> Repo:
    return Repo.from_git(ROOT)


def test_the_paid_tier_is_read_from_the_same_table_with_its_date(real: Repo) -> None:
    got, when = costs.paid_tier_prices(real)
    assert got == {m: (p.input_per_mtok, p.output_per_mtok) for m, p in GEMINI_PAID_PRICES.items()}
    assert when == GEMINI_PAID_AS_OF == "2026-11-25"


def test_the_cost_table_shows_the_paid_tier_labelled_and_in_rupees(real: Repo) -> None:
    book = costs.costs(real)
    items = {i.id: i for i in book.items}
    flash = GEMINI_PAID_PRICES["gemini-3.8-flash"]
    paid_in, paid_out = items["gemini_3_8_flash_paid_in"], items["gemini_3_8_flash_paid_out"]
    assert paid_in.label == "Gemini 3.8 Flash (paid tier, prices of 2026-11-25), input"
    assert paid_in.unit == "1M input tokens" and paid_in.kind == "model" and not paid_in.free
    assert paid_in.inr == round(flash.input_per_mtok * book.usd_inr, 2)
    assert paid_out.inr == round(flash.output_per_mtok * book.usd_inr, 2)
    for model in GEMINI_PAID_PRICES:
        mid = re.sub(r"[^a-z0-9]+", "_", model)
        assert items[mid].inr == 0 and items[mid].free  # the free tier stays as it was
        assert {f"{mid}_paid_in", f"{mid}_paid_out"} <= set(items)
    assert all(len(i.label) <= 80 and "$" not in i.label for i in book.items)


def test_the_paid_tier_comes_after_everything_the_tour_already_shows(real: Repo) -> None:
    ids = [i.id for i in costs.costs(real).items]
    paid = [n for n, i in enumerate(ids) if "_paid_" in i]
    assert len(paid) == 2 * len(GEMINI_PAID_PRICES) and paid == list(
        range(len(ids) - len(paid), len(ids))
    )
    assert ids[: 2 * 3 + 4] == [
        *(
            f"{m}_{s}"
            for m in ("claude_opus_5_5", "claude_sonnet_5_5", "claude_haiku_5_5")
            for s in ("in", "out")
        ),
        *(re.sub(r"[^a-z0-9]+", "_", m) for m in PRICES if m.startswith("gemini-")),
    ]


PRICING = "src/jarvis/llm/pricing.py"
_FREE = 'PRICES = {"m-1": Price(1.0, 2.0)}\n'


def _repo(tmp_path: Path, text: str) -> Repo:
    path = tmp_path / PRICING
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return Repo.from_dir(tmp_path, sha="c" * 40, committed_at="2026-11-25T09:00:00+05:30")


def test_a_price_list_without_a_paid_tier_shows_none(tmp_path: Path) -> None:
    assert costs.paid_tier_prices(_repo(tmp_path, _FREE)) == ({}, "")
    assert not [i for i in costs.costs(_repo(tmp_path, _FREE)).items if "_paid_" in i.id]


@pytest.mark.parametrize(
    "tail",
    [
        'GEMINI_PAID_PRICES = {"g-1": Price(1.0, 2.0)}\n',  # no date
        'GEMINI_PAID_PRICES = {"g-1": Price(1.0, 2.0)}\nGEMINI_PAID_AS_OF = "25 Nov"\n',
        'GEMINI_PAID_PRICES = {"g-1": price_of("g-1")}\nGEMINI_PAID_AS_OF = "2026-11-25"\n',
        'GEMINI_PAID_PRICES = load()\nGEMINI_PAID_AS_OF = "2026-11-25"\n',
    ],
)
def test_a_paid_tier_that_is_there_but_unreadable_fails(tmp_path: Path, tail: str) -> None:
    with pytest.raises(GenError, match="llm/pricing.py"):
        costs.paid_tier_prices(_repo(tmp_path, _FREE + tail))
