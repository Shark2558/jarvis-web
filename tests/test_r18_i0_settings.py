# tests/test_r18_i0_settings.py -- R18 I0: the owner's call settings (defaults from the deployment's
# caps, a bad stored field reads as its default, changes checked first and saved in a transaction),
# the config keys (speech keys optional and secret, Sarvam off) and the speech prices in ₹.
from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from jarvis.calls import settings as cs
from jarvis.calls.models import AnswerPolicy, CallSettings, SpeechOption
from jarvis.calls.prices import PriceUnknown, speech_prices
from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs

UID = "u_0123456789abcdef"


def test_config_keys_and_their_defaults(settings: Settings) -> None:
    assert settings.calls_enabled is True
    assert settings.azure_speech_key is None and settings.sarvam_api_key is None
    assert settings.bhashini_api_key is None and settings.sarvam_enabled is False
    assert settings.calls_retention_days == 30
    assert (settings.calls_month_cap_inr, settings.calls_call_cap_inr) == (200, 20)
    assert settings.calls_max_minutes == 6
    keyed = settings.model_copy(update={"azure_speech_key": SecretStr("not-a-real-key")})
    assert "not-a-real-key" not in repr(keyed) and "not-a-real-key" not in str(keyed)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, calls_retention_days=31)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, voice_price_azure_f0_inr_per_hour=1.0)  # F0 cannot bill
    with pytest.raises(ValidationError):
        Settings(_env_file=None, voice_price_sarvam_inr_per_hour=0)  # paid is never ₹0


def test_the_speech_prices_in_rupees(settings: Settings) -> None:
    p = speech_prices(settings, 95.24)
    assert set(p) == set(SpeechOption)
    assert p[SpeechOption.AZURE].inr_per_minute() == 0 and not p[SpeechOption.AZURE].can_bill
    assert p[SpeechOption.AZURE].hear_free_seconds == 5 * 3600
    assert p[SpeechOption.SARVAM].inr_per_minute() == 0.5 and p[SpeechOption.SARVAM].paid
    assert p[SpeechOption.SARVAM].inr_per_chars(10_000) == pytest.approx(30.0)
    assert p[SpeechOption.GOOGLE].inr_per_minute() == pytest.approx(0.024 * 95.24, abs=1e-3)
    assert p[SpeechOption.LAPTOP].inr_per_minute() == 0
    with pytest.raises(PriceUnknown):
        p[SpeechOption.BHASHINI].inr_per_minute()  # unknown is never ₹0
    with pytest.raises(PriceUnknown):
        p[SpeechOption.BHASHINI].inr_per_chars(100)
    with pytest.raises(ValueError):
        speech_prices(settings, 0)


def test_defaults_take_the_deployments_caps(settings: Settings) -> None:
    assert cs.defaults() == CallSettings()
    lower = settings.model_copy(update={"calls_month_cap_inr": 100, "calls_retention_days": 7})
    d = cs.defaults(lower)
    assert (d.month_cap_inr, d.retention_days, d.call_cap_inr) == (100, 7, 20)


def test_a_bad_stored_field_reads_as_its_default_field_by_field() -> None:
    base = CallSettings()
    got = cs.read({"answering_on": "maybe", "answer_after_rings": 4, "call_cap_inr": 999}, base)
    assert got.answering_on is False and got.answer_after_rings == 4 and got.call_cap_inr == 20
    assert cs.read(None, base) == base


def test_apply_refuses_unknown_and_bad_values_without_echoing_them() -> None:
    base = CallSettings()
    assert cs.apply(base, {"answer_policy": "contacts"}).answer_policy is AnswerPolicy.CONTACTS
    with pytest.raises(cs.CallSettingsRejected, match="Unknown call setting: nope"):
        cs.apply(base, {"nope": 1})
    with pytest.raises(cs.CallSettingsRejected) as err:
        cs.apply(base, {"month_cap_inr": 987654})
    assert "987654" not in str(err.value) and "month_cap_inr" in str(err.value)
    with pytest.raises(cs.CallSettingsRejected):
        cs.apply(base, {"updated_at": "2026-11-27T00:00:00Z"})  # not his to set


async def test_the_store_saves_in_a_transaction_and_stamps_the_time() -> None:
    docs = MemoryDocs()
    store = cs.CallSettingsStore(docs, prefix="t_")
    assert await store.get(UID) == CallSettings()
    saved = await store.save(UID, {"answering_on": True, "owner_first_name": "Asha"})
    assert saved.answering_on and saved.updated_at is not None
    assert (await store.get(UID)).owner_first_name == "Asha"
    assert docs.tx_sizes == [1]
    with pytest.raises(cs.CallSettingsRejected):
        await store.save(UID, {"answer_after_rings": 99})
    assert (await store.get(UID)).answer_after_rings == 5  # nothing written
    with pytest.raises(ValueError):
        await store.get("../x")
