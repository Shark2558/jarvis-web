# tests/test_r131_c_consent.py -- R13.1 Part C: his typed YES (docs/plans/r13-1-try-on.md D11;
# plan review M3; review C-1 finding 2): exactly YES (letters only, trimmed); a SHA-256 over a
# FIXED template (its version, provider, model, location and location words, the cache setting
# and every line he is shown), never the day's ₹ or the cap: a moved rate keeps consent current;
# a model, a location, the cache or an edited line asks again. The version he is shown and sends
# back is "c2-" and 12 hex of that hash. Written first and run red.
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

import pytest
from r131_fake_tryon import ScriptedTryOn
from r131_fakes import NOW, RING, UID, FixedClock

from jarvis.storage.docs import MemoryDocs
from jarvis.wardrobe.seeme import consent as cmod
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.seeme.consent import Consent
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.seeme.vault import Sealer

PREFIX = "jarvis_"


def _consent(docs: MemoryDocs | None = None) -> Consent:
    return Consent(docs or MemoryDocs(), PREFIX, Sealer(RING), now=FixedClock(NOW))


DESC = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image").describe()
SHOWN = cmod.shown_version(DESC, cache=False)


async def test_exactly_yes_trimmed_is_consent_and_it_is_current() -> None:
    c = _consent()
    view = await c.give(UID, " YES ", SHOWN, DESC, cache=False)
    assert view.given and view.current and view.at == NOW and view.version == SHOWN
    assert await c.current(UID, DESC, cache=False)


@pytest.mark.parametrize("typed", ["yes", "Yes", "YES!", "Y E S", "YESS", "", "ＹＥＳ", "YES."])
async def test_anything_else_changes_nothing(typed: str) -> None:
    docs = MemoryDocs()
    c = _consent(docs)
    with pytest.raises(SeeMeRefused) as err:
        await c.give(UID, typed, SHOWN, DESC, cache=False)
    assert (err.value.status, err.value.code) == (422, "not_yes")
    assert docs.log == [] and not await c.current(UID, DESC, cache=False)


def test_the_version_shown_is_c2_and_12_hex_of_what_he_reads() -> None:
    assert re.fullmatch(r"c2-[0-9a-f]{12}", SHOWN) and len(SHOWN) <= 20  # ConsentIn's 20
    assert SHOWN == "c2-" + cmod.digest(DESC, cache=False)[:12]
    assert cmod.shown_version(DESC, cache=False) == SHOWN  # the same inputs: the same version
    text = cmod.template_text(DESC, cache=False)
    for line in cmod.words(DESC, cache=False):
        assert line in text  # every line he is shown is in what the hash covers


@pytest.mark.parametrize("old", ["c1", "c2", "c2-000000000000", ""])
async def test_a_yes_for_words_he_was_not_shown_asks_again(old: str) -> None:
    docs = MemoryDocs()
    with pytest.raises(SeeMeRefused) as err:
        await _consent(docs).give(UID, "YES", old, DESC, cache=False)
    assert (err.value.status, err.value.code) == (422, "consent_needed") and docs.log == []


CHANGES: dict[str, Any] = {
    "provider": {"desc": replace(DESC, provider="Another Cloud")},
    "model": {"desc": replace(DESC, model="gemini-nano-banana-2.1")},
    "model_words": {"desc": replace(DESC, model_words="Another image model")},
    "location": {"desc": replace(DESC, location="eu")},
    "location_words": {"desc": replace(DESC, location_words="processed in the European Union")},
    "end_date": {"desc": replace(DESC, retires_on="2027-11-30")},
    "cache": {"cache": True},
    "template_version": {"attr": (cmod, "VERSION", "c3")},
    "an_edited_line": {"attr": (texts, "SENT_LINE", texts.SENT_LINE + " And one more thing.")},
    "the_cache_line": {"attr": (texts, "CACHE_OFF_LINE", "Google's cache is off.")},
}  # fmt: skip


@pytest.mark.parametrize("change", list(CHANGES))
async def test_a_change_to_anything_he_agreed_to_asks_for_his_yes_again(
    change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _consent()
    await c.give(UID, "YES", SHOWN, DESC, cache=False)
    kw = CHANGES[change]
    if "attr" in kw:
        monkeypatch.setattr(*kw["attr"])
    desc, cache = kw.get("desc", DESC), kw.get("cache", False)
    assert not await c.current(UID, desc, cache=cache), change
    view = await c.view(UID, desc, cache=cache)
    assert view.given and not view.current and view.version != SHOWN, change
    with pytest.raises(SeeMeRefused) as err:
        await c.give(UID, "YES", SHOWN, desc, cache=cache)  # the old words' version
    assert err.value.code == "consent_needed", change
    again = await c.give(UID, "YES", view.version, desc, cache=cache)  # what he is shown now
    assert again.current and await c.current(UID, desc, cache=cache), change


async def test_a_moved_rate_keeps_consent_and_the_same_inputs_dont_ask_again() -> None:
    c = _consent()
    await c.give(UID, "YES", SHOWN, DESC, cache=False)
    text = cmod.template_text(DESC, cache=False)
    assert "95.24" not in text and "96.1" not in text and "300" not in text and "₹" not in text
    assert await c.current(UID, DESC, cache=False)  # nothing about the day's ₹ is in the hash
    same = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image").describe()
    assert await c.current(UID, same, cache=False)
    assert (await c.view(UID, same, cache=False)).version == SHOWN


async def test_the_record_is_sealed_and_holds_no_words() -> None:
    docs = MemoryDocs()
    await _consent(docs).give(UID, "YES", SHOWN, DESC, cache=False)
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
    cached = await _consent().view(UID, DESC, cache=True)
    assert "up to 24 hours" in " ".join(cached.words) and "switched off" not in " ".join(
        cached.words
    )
    assert cached.version == cmod.shown_version(DESC, cache=True) != SHOWN
    assert not view.given and not view.current and view.version == SHOWN
    assert "$" not in words and "₹" not in words  # no figure in the consent at all


async def test_a_record_that_wont_open_is_not_consent() -> None:
    from jarvis.storage.docs import Set

    docs = MemoryDocs()
    await docs.write([Set(f"{PREFIX}tryon_consent/{UID}", {"owner": UID, "blob": "x", "v": 1})])
    assert not await _consent(docs).current(UID, DESC, cache=False)
