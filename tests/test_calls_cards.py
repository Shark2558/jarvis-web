# tests/test_calls_cards.py — R18 A1: call cards from a draft (calls.cards): the number, a saved
# contact, the language gate, the limits, "never called before", the ₹ estimate, the card's text,
# the round trip to the tool's arguments, and the fast tier's reading of free text.
from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

import pytest

from jarvis.calls.cards import (
    CardBuilder,
    CardParser,
    CardRefused,
    Estimator,
    GoogleContactNumbers,
    NumberRefused,
    TokenRate,
    card_args,
    card_text,
    offered,
    read_draft,
    typed_calls,
)
from jarvis.calls.models import Booking, CallSettings, LanguageResult, SpeechOption, TimeWindow
from jarvis.calls.prices import SpeechPrice
from jarvis.calls.store import MemoryCallStore
from jarvis.calls.tools import PlaceArgs

UID = "u_0123456789abcdef"
NUMBER = "+919000000001"
AT = datetime(2026, 11, 27, 5, 0, tzinfo=UTC)
PRICES = {
    SpeechOption.GOOGLE: SpeechPrice(SpeechOption.GOOGLE, 2.0, 2.5, 3600, 1_000_000),
    SpeechOption.AZURE: SpeechPrice(SpeechOption.AZURE, 0.0, 0.0, 18_000, 500_000, can_bill=False),
    SpeechOption.SARVAM: SpeechPrice(SpeechOption.SARVAM, 0.5, 3.0, paid=True),
    SpeechOption.BHASHINI: SpeechPrice(SpeechOption.BHASHINI, None, None),
}
RATE = TokenRate(input_inr=8.8, output_inr=44.0, cache_read_inr=0.88)  # Haiku at ₹88 a dollar


def _result(lang: str, option: SpeechOption, inr: float | None = 0.0, **kw: Any) -> LanguageResult:
    return LanguageResult(
        lang=lang, option=option, checked_at=AT, passed=True, inr_per_minute=inr, **kw
    )


async def _store(*results: LanguageResult) -> MemoryCallStore:
    store = MemoryCallStore()
    await store.save_settings(UID, {"owner_first_name": "Sam"})
    for r in results or (
        _result("en-IN", SpeechOption.GOOGLE),
        _result("ml-IN", SpeechOption.AZURE),
    ):
        await store.put_language_result(r)
    return store


class _Left:
    def __init__(self, left: tuple[float, float] | None) -> None:
        self.value = left

    async def left(self, option: SpeechOption) -> tuple[float, float] | None:
        return self.value


def _builder(store: MemoryCallStore, contacts: Any = None, left: Any = None) -> CardBuilder:
    est = Estimator(PRICES, RATE, allowance=_Left(left) if left is not None else None)
    return CardBuilder(store, est, contacts=contacts, is_template=lambda n: n == "laundry_pickup")


def _draft(**kw: Any) -> PlaceArgs:
    base: dict[str, Any] = {"number": NUMBER, "purpose": "Book a laundry pickup"}
    return PlaceArgs.model_validate(base | kw)


async def test_a_draft_becomes_a_card_with_his_limits_and_an_estimate() -> None:
    store = await _store()
    card = await _builder(store, left=(10_000.0, 1e6)).build(
        UID, _draft(may_agree=["pickup 10-12"])
    )
    assert card.number_e164 == NUMBER and card.languages == ("en-IN",)
    assert card.limits.max_minutes == 6 and card.limits.max_inr == 20
    assert card.new_number is True
    assert card.estimate_inr is not None and 0 < card.estimate_inr < 1  # speech free; brain only
    assert card.may_agree == ("pickup 10-12",)


async def test_a_number_called_before_is_not_new() -> None:
    store = await _store()
    await store.count_call(UID, date(2026, 11, 20), NUMBER)
    card = await _builder(store).build(UID, _draft())
    assert card.new_number is False


async def test_the_minutes_never_exceed_his_setting() -> None:
    store = await _store()
    await store.save_settings(UID, {"call_max_minutes": 4})
    card = await _builder(store).build(UID, _draft(max_minutes=20))
    assert card.limits.max_minutes == 4


@pytest.mark.parametrize("number", ["+9119001234567", "+442079460958", "+911400000001"])
async def test_refused_numbers_never_become_cards(number: str) -> None:
    store = await _store()
    with pytest.raises(NumberRefused):
        await _builder(store).build(UID, _draft(number=number))


async def test_a_language_that_did_not_pass_is_refused() -> None:
    store = await _store(_result("en-IN", SpeechOption.GOOGLE))
    with pytest.raises(CardRefused) as err:
        await _builder(store).build(UID, _draft(languages=["en-IN", "ta-IN"]))
    assert err.value.code == "language" and "Tamil" in err.value.words


async def test_sarvam_and_balanced_only_with_his_yes() -> None:
    results = [
        _result("hi-IN", SpeechOption.SARVAM, 0.5),
        _result("ta-IN", SpeechOption.GOOGLE, 1.0, needs_balanced=True),
    ]
    # I1 (the Workshop's decision): English, never checked yet, is offered "not yet checked"
    assert set(offered(results, CallSettings())) == {"en-IN"}
    yes = CallSettings(sarvam_on=True, allow_balanced=True)
    assert set(offered(results, yes)) == {"hi-IN", "ta-IN", "en-IN"}


def test_the_cheapest_passing_option_is_used() -> None:
    results = [
        _result("ml-IN", SpeechOption.GOOGLE, 1.2),
        _result("ml-IN", SpeechOption.AZURE, 0.0),
        _result("ml-IN", SpeechOption.BHASHINI, None),
    ]
    assert offered(results, CallSettings())["ml-IN"].option is SpeechOption.AZURE


class _LeftFor:
    """The free allowance left, per option (the real `BillingAllowance` meters Google only)."""

    def __init__(self, **left: tuple[float, float]) -> None:
        self.by = {SpeechOption(k): v for k, v in left.items()}

    async def left(self, option: SpeechOption) -> tuple[float, float] | None:
        return self.by.get(option)


def test_review_free_first_beats_a_cheaper_paid_option_while_the_allowance_lasts() -> None:
    # R18 review HIGH (the owner's "free first" rule): Sarvam at about ₹0.70 a call minute is
    # cheaper than Google past its free allowance, but while Google's allowance covers the call
    # Google costs ₹0 and comes first
    results = [
        _result("hi-IN", SpeechOption.SARVAM, 0.70),
        _result("hi-IN", SpeechOption.GOOGLE, 1.57),
    ]
    yes = CallSettings(sarvam_on=True)
    assert offered(results, yes, free={SpeechOption.GOOGLE})["hi-IN"].option is SpeechOption.GOOGLE
    assert offered(results, yes)["hi-IN"].option is SpeechOption.SARVAM  # no allowance left


async def test_review_the_estimator_names_the_options_a_call_costs_nothing_on() -> None:
    est = Estimator(PRICES, RATE, allowance=_LeftFor(google=(1e6, 1e7)))
    assert await est.free_options(6) == {SpeechOption.GOOGLE, SpeechOption.AZURE}
    spent = Estimator(PRICES, RATE, allowance=_LeftFor(google=(10.0, 10.0)))
    assert await spent.free_options(6) == {SpeechOption.AZURE}  # Azure F0 can't bill
    assert await Estimator(PRICES, RATE).free_options(6) == {SpeechOption.AZURE}


async def test_review_a_card_speaks_free_first_and_its_estimate_says_so() -> None:
    store = await _store(
        _result("en-IN", SpeechOption.GOOGLE, 1.57),
        _result("hi-IN", SpeechOption.SARVAM, 0.70),
        _result("hi-IN", SpeechOption.GOOGLE, 1.57),
    )
    await store.save_settings(UID, {"sarvam_on": True})
    plenty = CardBuilder(store, Estimator(PRICES, RATE, allowance=_LeftFor(google=(1e6, 1e7))))
    card, estimate = await plenty.estimate_for(UID, _draft(languages=["hi-IN", "en-IN"]))
    assert estimate.speech_free and estimate.speech_inr == 0
    spent = CardBuilder(store, Estimator(PRICES, RATE, allowance=_LeftFor(google=(1.0, 1.0))))
    _, priced = await spent.estimate_for(UID, _draft(languages=["hi-IN", "en-IN"]))
    assert not priced.speech_free and priced.speech_inr == pytest.approx(0.5 * 3 + 0.003 * 2700)


async def test_an_unknown_template_is_refused() -> None:
    store = await _store()
    with pytest.raises(CardRefused) as err:
        await _builder(store).build(UID, _draft(template="pizza_order"))
    assert err.value.code == "template"
    card = await _builder(store).build(UID, _draft(template="laundry_pickup"))
    assert card.template == "laundry_pickup"


async def test_speech_is_priced_once_past_the_free_allowance() -> None:
    est = Estimator(PRICES, RATE, allowance=_Left((10.0, 10.0)))
    over = await est.estimate(6, SpeechOption.GOOGLE)
    assert not over.speech_free and over.speech_inr == pytest.approx(6.0 + 6.75)
    free = await Estimator(PRICES, RATE, allowance=_Left((1e6, 1e7))).estimate(
        6, SpeechOption.GOOGLE
    )
    assert free.speech_free and free.speech_inr == 0
    assert (await est.estimate(6, SpeechOption.AZURE)).speech_inr == 0  # it can't bill


async def test_an_unknown_price_makes_the_estimate_unknown() -> None:
    est = Estimator(PRICES, RATE)
    assert (await est.estimate(6, SpeechOption.BHASHINI)).total_inr is None
    assert (await Estimator(PRICES, None).estimate(6, SpeechOption.AZURE)).total_inr is None


class _Found:
    def __init__(self, contacts: list[Any]) -> None:
        self.contacts = contacts


class _C:
    def __init__(self, name: str, phones: tuple[str, ...]) -> None:
        self.name, self.phones = name, phones


class _Client:
    def __init__(self, contacts: list[_C], fail: bool = False) -> None:
        self.contacts, self.fail = contacts, fail

    async def require(self, uid: str) -> None:
        if self.fail:
            raise RuntimeError("not granted")

    async def search(self, uid: str, name: str) -> _Found:
        return _Found(self.contacts)


async def test_a_saved_contact_with_one_number_is_used() -> None:
    store = await _store()
    contacts = GoogleContactNumbers(_Client([_C("Laundry Shop", (NUMBER,))]))
    card = await _builder(store, contacts).build(UID, _draft(number=None, contact="laundry"))
    assert card.number_e164 == NUMBER and card.contact_name == "Laundry Shop"


@pytest.mark.parametrize(
    ("people", "fail", "code"),
    [
        ([], False, "no_contact"),
        ([_C("A", (NUMBER,)), _C("B", ("+919000000002",))], False, "many_contacts"),
        ([_C("A", (NUMBER, "+919000000002"))], False, "many_contacts"),
        ([_C("A", (NUMBER,))], True, "contacts_down"),
    ],
)
async def test_a_contact_must_match_exactly_one_number(
    people: list[_C], fail: bool, code: str
) -> None:
    store = await _store()
    contacts = GoogleContactNumbers(_Client(people, fail))
    with pytest.raises(CardRefused) as err:
        await _builder(store, contacts).build(UID, _draft(number=None, contact="laundry"))
    assert err.value.code == code


async def test_card_text_shows_only_the_last_four_digits() -> None:
    store = await _store()
    card = await _builder(store).build(UID, _draft(languages=["en-IN", "ml-IN"]))
    text = card_text(card)
    assert "0001" in text and "9000000001" not in text
    assert "English, Malayalam" in text and "passkey" in text and "₹" in text


async def test_a_card_round_trips_through_the_tool_arguments() -> None:
    store = await _store()
    booking = Booking(
        windows=(TimeWindow(day=date(2026, 11, 28), start=time(10), end=time(12)),),
        give_name="A. Owner",
        reason="Laundry pickup",
    )
    builder = _builder(store)
    card = await builder.build(UID, _draft(booking=booking.model_dump(mode="json"), contact="Shop"))
    again = await builder.build(UID, read_draft(card_args(card)), card_id=card.id)
    assert again.digest() == card.digest() and again.id == card.id


async def test_a_card_needs_his_first_name_for_the_opening_line() -> None:
    store = await _store()
    await store.save_settings(UID, {"owner_first_name": ""})
    with pytest.raises(CardRefused) as err:
        await _builder(store).build(UID, _draft())
    assert err.value.code == "no_name"


def test_a_bad_draft_is_refused_in_plain_words() -> None:
    with pytest.raises(CardRefused) as err:
        read_draft({"purpose": "x"})
    assert err.value.code == "invalid"


class _Model:
    def __init__(self, reply: str | None) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def complete(self, uid: str, *, system: str, prompt: str, max_tokens: int) -> str | None:
        self.prompts.append(prompt)
        return self.reply


async def test_free_text_is_read_by_the_fast_tier_as_data() -> None:
    reply = (
        '{"number": "90000 00001", "contact": null, "purpose": "Book a pickup",'
        ' "may_say": ["the address on file"], "may_agree": ["pickup tomorrow 10-12"],'
        ' "languages": ["ml-IN", "en-IN"]}'
    )
    model = _Model(reply)
    draft = await CardParser(model).parse(UID, "Call the laundry on 90000 00001 for a pickup")
    assert draft.number == NUMBER and draft.languages == ("ml-IN", "en-IN")
    assert "EXTERNAL CONTENT" in model.prompts[0]


async def test_a_number_he_did_not_type_is_never_taken() -> None:
    reply = '{"number": "+919000000002", "purpose": "Book a pickup"}'
    with pytest.raises(CardRefused):
        await CardParser(_Model(reply)).parse(UID, "Call the laundry on 90000 00001")


@pytest.mark.parametrize("reply", [None, "no json", "[1, 2]", '{"purpose": ""}'])
async def test_an_unusable_reply_asks_for_the_fields(reply: str | None) -> None:
    with pytest.raises(CardRefused) as err:
        await CardParser(_Model(reply)).parse(UID, "Call the laundry for a pickup")
    assert err.value.code == "unparsed"


def test_typed_calls_reads_only_numbers_jarvis_may_call() -> None:
    assert typed_calls("ring 90000 00001 or 112 or +44 20 7946 0958") == frozenset({NUMBER})


# ---- the helpers I1 wires -------------------------------------------------------------------
class _Use:
    def __init__(self, units: dict[str, float]) -> None:
        self.units = units

    def used(self, key: str) -> float:
        return self.units.get(key, 0.0)


class _AllowanceBilling:
    def __init__(self, units: dict[str, float]) -> None:
        self.units = units

    async def allowance(self, keys: Any) -> _Use:
        return _Use(self.units)


async def test_the_google_allowance_left_is_read_from_billing() -> None:
    from jarvis.calls.cards import GOOGLE_KEYS, BillingAllowance

    left = BillingAllowance(
        _AllowanceBilling({GOOGLE_KEYS[0]: 600.0, GOOGLE_KEYS[1]: 1000}), PRICES
    )
    assert await left.left(SpeechOption.GOOGLE) == (3000.0, 999_000)
    assert await left.left(SpeechOption.AZURE) is None


def test_token_rate_prices_the_model_in_rupees() -> None:
    from jarvis.calls.cards import token_rate

    rate = token_rate("claude-haiku-5-5", 88.0)
    assert rate is not None and rate.input_inr == pytest.approx(8.8)
    assert token_rate("no-such-model", 88.0) is None


class _Spec:
    id, tools_allowed = "b1", True


class _Registry:
    default = _Spec()

    def list(self) -> list[_Spec]:
        return [self.default]

    def __init__(self, router: Any) -> None:
        self.router = router

    def router_for(self, brain_id: str) -> Any:
        return self.router


class _Done:
    text, cost_usd, model = '{"purpose": "x"}', 0.0001, "claude-haiku-5-5"
    usage = None


class _Router:
    def __init__(self, blocked: bool = False) -> None:
        self.blocked, self.calls = blocked, 0

    async def blocked_now(self) -> bool:
        return self.blocked

    async def complete(self, **kw: Any) -> _Done:
        self.calls += 1
        assert kw["tier"].value == "fast" and kw["tools"] is None
        return _Done()


class _Meter:
    def __init__(self, over: bool = False) -> None:
        self.over, self.recorded = over, 0.0

    async def ensure_allowed(self, uid: str, spec: Any) -> None:
        if self.over:
            raise RuntimeError("limit reached")

    async def record(self, uid: str, brain_id: str, cost_usd: float) -> float:
        self.recorded += cost_usd
        return cost_usd


async def test_the_router_fast_text_is_admitted_and_metered() -> None:
    from jarvis.calls.cards import RouterFastText

    router, meter = _Router(), _Meter()
    fast = RouterFastText(_Registry(router), meter)
    assert await fast.complete(UID, system="s", prompt="p", max_tokens=10) == '{"purpose": "x"}'
    assert meter.recorded == pytest.approx(0.0001)
    assert (
        await RouterFastText(_Registry(_Router(True)), _Meter()).complete(
            UID, system="s", prompt="p", max_tokens=10
        )
        is None
    )
    assert (
        await RouterFastText(_Registry(router), _Meter(over=True)).complete(
            UID, system="s", prompt="p", max_tokens=10
        )
        is None
    )

    async def off(uid: str) -> bool:
        return True

    assert (
        await RouterFastText(_Registry(router), meter, ai_off=off).complete(
            UID, system="s", prompt="p", max_tokens=10
        )
        is None
    )
    assert router.calls == 1
