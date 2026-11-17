# tests/test_r131_c_consent.py -- R13.1 Part C: his typed YES (docs/plans/r13-1-try-on.md D11;
# plan review M3): exactly YES (letters only, trimmed); a SHA-256 over a FIXED template (its
# version, provider, model, location and location words), never the day's ₹ or the cap: a moved
# rate keeps consent current, a model or location change asks again. Written first and run red.
from __future__ import annotations

import pytest
from r131_fake_tryon import ScriptedTryOn
from r131_fakes import NOW, RING, UID, FixedClock

from jarvis.storage.docs import MemoryDocs
from jarvis.wardrobe.seeme import consent as cmod
from jarvis.wardrobe.seeme.consent import Consent
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.seeme.vault import Sealer

PREFIX = "jarvis_"


def _consent(docs: MemoryDocs | None = None) -> Consent:
    return Consent(docs or MemoryDocs(), PREFIX, Sealer(RING), now=FixedClock(NOW))


DESC = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image").describe()


async def test_exactly_yes_trimmed_is_consent_and_it_is_current() -> None:
    c = _consent()
    view = await c.give(UID, " YES ", cmod.VERSION, DESC, cache=False)
    assert view.given and view.current and view.at == NOW and view.version == cmod.VERSION
    assert await c.current(UID, DESC)


@pytest.mark.parametrize("typed", ["yes", "Yes", "YES!", "Y E S", "YESS", "", "ＹＥＳ", "YES."])
async def test_anything_else_changes_nothing(typed: str) -> None:
    docs = MemoryDocs()
    c = _consent(docs)
    with pytest.raises(SeeMeRefused) as err:
        await c.give(UID, typed, cmod.VERSION, DESC, cache=False)
    assert (err.value.status, err.value.code) == (422, "not_yes")
    assert docs.log == [] and not await c.current(UID, DESC)


async def test_an_old_template_version_asks_again() -> None:
    c = _consent()
    with pytest.raises(SeeMeRefused) as err:
        await c.give(UID, "YES", "c1", DESC, cache=False)
    assert (err.value.status, err.value.code) == (422, "consent_needed")


async def test_a_moved_rate_keeps_consent_and_a_model_or_place_change_asks_again() -> None:
    c = _consent()
    await c.give(UID, "YES", cmod.VERSION, DESC, cache=False)
    assert "95.24" not in cmod.template_text(DESC) and "300" not in cmod.template_text(DESC)
    assert await c.current(UID, DESC)  # nothing about the day's ₹ is in the hash
    other_model = ScriptedTryOn(max_garments=3, model="gemini-nano-banana-2.1").describe()
    other_place = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image", location="eu")
    assert not await c.current(UID, other_model)
    assert not await c.current(UID, other_place.describe())
    assert (await c.view(UID, other_model, cache=False)).given is True  # given, but not current


async def test_the_record_is_sealed_and_holds_no_words() -> None:
    docs = MemoryDocs()
    await _consent(docs).give(UID, "YES", cmod.VERSION, DESC, cache=False)
    doc = await docs.get(f"{PREFIX}tryon_consent/{UID}")
    assert doc is not None and doc["owner"] == UID and set(doc) == {
        "v", "kid", "owner", "blob", "updated_at",
    }  # fmt: skip
    assert "Gemini" not in str(doc) and "YES" not in str(doc)


async def test_the_words_name_what_is_sent_to_whom_what_google_keeps_and_the_way_out() -> None:
    view = await _consent().view(UID, DESC, cache=False)
    words = " ".join(view.words)
    for needle in ("your photo", "a garment you are thinking of buying", "up to two of your own",
                   "Never a private piece", "Google Cloud's Agent Platform",
                   "processed in the United States", "train", "abuse", "switched off",
                   "rupees, with GST", "Content Credentials", "28 May 2027",
                   "withdraw"):  # fmt: skip
        assert needle in words, needle
    cached = " ".join((await _consent().view(UID, DESC, cache=True)).words)
    assert "up to 24 hours" in cached and "switched off" not in cached
    assert not view.given and not view.current and view.version == cmod.VERSION
    assert "$" not in words and "₹" not in words  # no figure in the consent at all


async def test_a_record_that_wont_open_is_not_consent() -> None:
    from jarvis.storage.docs import Set

    docs = MemoryDocs()
    await docs.write([Set(f"{PREFIX}tryon_consent/{UID}", {"owner": UID, "blob": "x", "v": 1})])
    assert not await _consent(docs).current(UID, DESC)
