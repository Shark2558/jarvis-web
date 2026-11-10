# tests/test_book_gen_costs.py
"""R6 D2: the Subscriptions & costs section (`gen.costs`): the model price table, the voice and
speech prices and free allowances (Settings defaults), the web-search credits, Google's Maps and
YouTube allowances and the free-tier table, every amount in ₹ at billing.fx's DEFAULT_RATE with
its date. Read from the code as ASTs (nothing imported), so the book says what the code says."""

from __future__ import annotations

from pathlib import Path

import pytest
from book_gen_fakes import ROOT, fixture_repo

from jarvis.buildbook.gen import code, costs
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.sections import Costs


@pytest.fixture(scope="module")
def real() -> Repo:
    return Repo.from_git(ROOT)


def test_the_rate_and_its_date_come_from_billing_fx(real: Repo) -> None:
    from jarvis.billing import fx

    assert costs.rate(real) == (fx.DEFAULT_RATE, fx.DEFAULT_AS_OF)


def test_model_prices_are_read_from_the_price_table(real: Repo) -> None:
    from jarvis.llm.pricing import PRICES

    got = costs.model_prices(real)
    assert got == {m: (p.input_per_mtok, p.output_per_mtok) for m, p in PRICES.items()}


def test_every_item_is_in_rupees_at_the_rate(real: Repo) -> None:
    from jarvis.billing import fx
    from jarvis.llm.pricing import PRICES

    book = costs.costs(real)
    assert isinstance(book, Costs) and book.usd_inr == fx.DEFAULT_RATE
    items = {i.id: i for i in book.items}
    sonnet = PRICES["claude-sonnet-5-5"]
    assert items["claude_sonnet_5_5_in"].inr == round(sonnet.input_per_mtok * fx.DEFAULT_RATE, 2)
    assert items["claude_sonnet_5_5_out"].label == "Claude Sonnet 5.5, output"
    assert items["claude_sonnet_5_5_out"].unit == "1M output tokens"
    assert "mock" not in items and items["gemini_3_8_flash"].inr == 0
    assert items["gemini_3_8_flash"].free
    assert not any("$" in f"{i.label}{i.unit}{i.free}" for i in book.items)  # ₹ only


def test_voice_and_speech_use_the_settings_defaults(real: Repo) -> None:
    from jarvis.config import Settings

    s, rate = Settings.model_fields, costs.rate(real)[0]
    items = {i.id: i for i in costs.costs(real).items}
    chirp = items["voice_chirp3_hd"]
    assert chirp.kind == "voice" and chirp.unit == "1M characters"
    assert chirp.inr == round(s["voice_price_chirp3_hd_usd_per_m"].default * rate, 2)
    assert chirp.free == "900,000 characters a month"
    assert items["speech_to_text"].free == "54 minutes a month"


def test_search_maps_and_the_free_tier(real: Repo) -> None:
    from jarvis.web.allowance import MONTHLY_CREDITS

    items = {i.id: i for i in costs.costs(real).items}
    assert (
        items["web_search"].free == f"{MONTHLY_CREDITS:,} credits a month"
        and items["web_search"].inr == 0
    )
    assert (
        items["maps_search"].kind == "maps"
        and items["maps_search"].free == "5,000 searches a month"
    )
    assert items["youtube_search"].free == "100 searches a day"
    for cid in ("cloud_run", "firestore", "secret_manager", "cloud_scheduler", "github_actions"):
        assert items[cid].kind == "cloud" and items[cid].inr == 0 and items[cid].free
    assert items["firestore"].free.startswith("1 GiB")


def test_settings_defaults_are_literal_values(real: Repo) -> None:
    from jarvis.config import Settings

    got = code.settings_defaults(real)
    for name in ("voice_tts_free_chars", "book_max_total_mb", "voice_price_stt_usd_per_min"):
        assert got[name] == Settings.model_fields[name].default


def test_the_fixture_has_only_the_free_tier_at_the_fallback_rate(tmp_path: Path) -> None:
    book = costs.costs(Repo.from_git(fixture_repo(tmp_path)))
    assert (book.usd_inr, book.rate_date) == costs.FALLBACK_RATE
    assert {i.kind for i in book.items} == {"cloud"}


@pytest.mark.parametrize(
    ("model", "label"),
    [
        ("claude-opus-5-5", "Claude Opus 5.5"),
        ("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite"),
        ("claude-haiku-5-5", "Claude Haiku 5.5"),
    ],
)
def test_model_labels(model: str, label: str) -> None:
    assert costs.model_label(model) == label
