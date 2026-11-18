# tests/test_r131_port.py -- R13.1 I0 seam 5 (docs/plans/r13-1-try-on.md D10, D13, D15, D19; plan
# review H1, L4): the try-on provider port in `jarvis.llm` (the model-agnostic rule: the wardrobe
# asks for "the try-on provider", never a model id), its price table and estimates in the plan's
# own ₹ figures, the billed-or-not errors, the lazy factory, and I0's one-garment fake, which
# proves that a provider taking one garment a call chains inside itself.
from __future__ import annotations

import math
import re
from typing import Any

import pytest
from r131_fake_tryon import JPEG, PNG, ScriptedTryOn, Step

from jarvis.billing.spend import with_tax
from jarvis.config import Settings
from jarvis.llm import tryon as port

RATE = 95.24  # the console's fallback rate (config.py usd_inr_rate)


def _inr(usd: float) -> float:
    return with_tax(usd * RATE, 18)


# ---- the records -------------------------------------------------------------------------------
def test_the_records_are_frozen_and_plural() -> None:
    ask = port.TryOnAsk(
        person=JPEG, garments=(port.Garment(JPEG, "a navy shirt"),), timeout_s=120.0
    )
    with pytest.raises(AttributeError):
        ask.person = b""  # type: ignore[misc]
    assert isinstance(ask.garments, tuple) and ask.garments[0].words == "a navy shirt"
    res = port.TryOnResult(picture=PNG, mime="image/png", usage=None, blocked=None)
    assert res.made and not port.TryOnResult(None, None, None, "SAFETY").made


def test_the_errors_say_whether_google_billed() -> None:
    assert issubclass(port.TryOnNotBilled, port.TryOnError)
    assert issubclass(port.TryOnMaybeBilled, port.TryOnError)
    assert port.TryOnNotBilled("x").billed is False and port.TryOnMaybeBilled("x").billed is True


# ---- prices and estimates (G4, at ₹95.24 a dollar, 18 % GST) ----------------------------------
def test_every_priced_model_is_one_the_settings_accept_and_the_default_is_priced() -> None:
    s = Settings(_env_file=None)
    assert (s.tryon_model, s.tryon_location) in port.TRYON_PRICES
    for model, location in port.TRYON_PRICES:
        Settings(_env_file=None, tryon_model=model, tryon_location=location)  # never refused
        assert model in port.MODEL_WORDS and location in port.LOCATION_WORDS
    assert ("virtual-try-on-001", "us") not in port.TRYON_PRICES  # not built (D19)


def test_the_typical_picture_is_about_nine_rupees_and_the_hold_about_eleven() -> None:
    price = port.price_of("gemini-3.1-flash-image", "us")
    bare = port.typical_usd(price, garments=2, thinking=0)
    assert math.isclose(bare, 0.0759, abs_tol=0.00005)  # top + trousers, no thinking tokens
    assert _inr(bare) == 8.52  # the plan's "₹7.22, ₹8.52 with GST"
    assert 8.85 <= _inr(port.typical_usd(price, garments=2)) <= 8.95  # ~1,000 thinking: ₹8.9
    assert _inr(port.typical_usd(price, garments=3, thinking=0)) == 8.59  # with the jacket
    assert _inr(port.worst_usd(price, garments=3)) == 11.22  # the hold (8,192 tokens out)
    assert 33 * 8.52 + 11.22 <= 300 < 34 * 8.52 + 11.22  # the cap: the 34th fits, the 35th not


def test_the_cost_of_an_answer_comes_from_its_usage() -> None:
    price = port.price_of("gemini-3.1-flash-image", "us")
    usage = port.TryOnUsage(input_tokens=3510, image_tokens=1120, text_tokens=0)
    assert math.isclose(port.cost_usd(price, usage), 0.0759, abs_tol=0.00005)
    more = port.TryOnUsage(input_tokens=3510, image_tokens=1120, text_tokens=1000)
    assert port.cost_usd(price, more) > port.cost_usd(price, usage)


def test_an_unpriced_model_or_location_has_no_price() -> None:
    with pytest.raises(KeyError):
        port.price_of("gemini-3.1-flash-image", "asia-south1")
    with pytest.raises(KeyError):
        port.price_of("gemini-9-ultra-image", "us")


# ---- the one-garment fake chains inside itself (H1) --------------------------------------------
async def test_a_one_garment_provider_chains_and_the_caller_sees_one_result() -> None:
    fake = ScriptedTryOn(max_garments=1)
    garments = tuple(port.Garment(JPEG, w) for w in ("a navy shirt", "charcoal trousers"))
    got = await fake.make(port.TryOnAsk(person=JPEG, garments=garments, timeout_s=120.0))
    assert got.made and got.mime == "image/png"
    assert [c.garments for c in fake.calls] == [("a navy shirt",), ("charcoal trousers",)]
    assert fake.calls[0].person == JPEG and fake.calls[1].person == PNG  # the first's picture
    assert fake.describe().max_garments == 1
    typical, worst = fake.estimate(2)
    assert typical == 2 * fake.estimate(1)[0] and worst >= typical


async def test_the_fake_follows_its_script_billed_or_not() -> None:
    fake = ScriptedTryOn(
        max_garments=3,
        script=[Step(error=port.TryOnNotBilled("503")), Step(blocked="SAFETY"), Step()],
    )
    ask = port.TryOnAsk(person=JPEG, garments=(port.Garment(JPEG, "a kurta"),), timeout_s=1.0)
    with pytest.raises(port.TryOnNotBilled):
        await fake.make(ask)
    blocked = await fake.make(ask)
    assert not blocked.made and blocked.blocked == "SAFETY" and blocked.usage is not None
    assert (await fake.make(ask)).made and len(fake.calls) == 3


def test_the_description_names_what_the_consent_names() -> None:
    d = ScriptedTryOn(max_garments=3).describe()
    want = {"provider", "model", "model_words", "location", "location_words", "max_garments"}
    assert want | {"retires_on"} == set(d.as_dict())
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.retires_on)
    assert "United States" in port.LOCATION_WORDS["us"]


def test_the_fake_is_a_try_on_provider() -> None:
    assert isinstance(ScriptedTryOn(max_garments=1), port.TryOnProvider)


# ---- the lazy factory ---------------------------------------------------------------------------
class _Tokens:
    async def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer fake-token"}

    def invalidate(self) -> None: ...

    def close(self) -> None: ...


async def _project() -> str | None:
    return "fake-project"


@pytest.mark.parametrize(
    "over",
    [{"tryon_pictures": False}, {"tryon_pictures": True, "tryon_location": "global"}],
)
def test_no_provider_while_pictures_are_off_or_unpriced(over: dict[str, Any]) -> None:
    s = Settings(_env_file=None, **over)
    assert port.build_tryon(s, tokens=_Tokens(), project=_project) is None


def test_no_provider_while_the_adapter_is_not_built(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(port.ADAPTERS, "gemini", "jarvis.llm.tryon_not_there")
    s = Settings(_env_file=None, tryon_pictures=True)
    assert port.build_tryon(s, tokens=_Tokens(), project=_project) is None


def test_the_factory_builds_the_familys_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    built: list[Any] = []
    fake = types.ModuleType("r131_adapter_probe")

    def build(s: Settings, *, tokens: Any, project: Any) -> Any:
        built.append((s.tryon_model, tokens, project))
        return ScriptedTryOn(max_garments=3)

    fake.build = build  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "r131_adapter_probe", fake)
    monkeypatch.setitem(port.ADAPTERS, "gemini", "r131_adapter_probe")
    tokens = _Tokens()
    got = port.build_tryon(Settings(_env_file=None, tryon_pictures=True), tokens=tokens,
                           project=_project)  # fmt: skip
    assert isinstance(got, ScriptedTryOn)
    assert built == [("gemini-3.1-flash-image", tokens, _project)]
