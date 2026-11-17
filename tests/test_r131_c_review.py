# tests/test_r131_c_review.py -- R13.1 Part C: the fixes of review C-1 that are not their own file
# (docs/plans/r13-1-integration/REVIEW-C-1.md): his T-shirt sent in fixed words and words JARVIS
# can't send refused before the reserve (finding 1); Google's cache turned on after his YES
# (finding 2); one source for the model's end date (finding 6); the rest of the LOWs. Fixed
# clocks only; nothing reaches Google. Each written first and run red.
from __future__ import annotations

import pytest
from r131_fake_gemini import FakeGoogle, FakeTokens, picture_answer, project_of
from r131_fakes import UID, T, ist
from r131_fakes_c import NEW_SHIRT, StrictTryOn, add_front, ask, ready_world

from jarvis.llm.tryon_gemini import GeminiTryOn
from jarvis.wardrobe.seeme.texts import SeeMeRefused

ScriptedTryOn = StrictTryOn  # the adapter's own pre-send check too


def gemini(model: str = "gemini-3.1-flash-image", location: str = "us"):  # type: ignore[no-untyped-def]
    google = FakeGoogle([picture_answer()])
    adapter = GeminiTryOn(model=model, location=location, tokens=FakeTokens(),
                          project=project_of(), http=google.client())  # fmt: skip
    return adapter, google


async def _shown(svc, garment: str, pieces: tuple[str, ...] = ()) -> float:  # type: ignore[no-untyped-def]
    return (await svc.estimate(UID, garment, list(pieces))).typical_inr


async def _refused(coro) -> SeeMeRefused:  # type: ignore[no-untyped-def]
    with pytest.raises(SeeMeRefused) as err:
        await coro
    return err.value


# ---- finding 1: the words sent ------------------------------------------------------------------
TEE_FRONT = "wh_00000000c003"


@pytest.mark.parametrize("on", ["gemini", "fake1"])
async def test_his_t_shirt_goes_in_a_picture_in_fixed_words(on: str) -> None:
    adapter, google = gemini()
    fake = ScriptedTryOn(max_garments=1)
    sw, svc, g = await ready_world(provider=adapter if on == "gemini" else fake)
    await add_front(sw, T.tee, TEE_FRONT)
    trousers = await svc.add_garment(UID, "trousers", "khaki", NEW_SHIRT)
    shown = await _shown(svc, trousers.id, (T.tee,))
    pic = await svc.press(UID, ask(trousers.id, (T.tee,), inr=shown))
    assert [(p.piece, p.words) for p in pic.sent] == [(T.tee, "grey T-shirt")]  # what he reads
    if on == "gemini":
        text = google.body()["contents"][0]["parts"][-1]["text"]
        assert "(new khaki trousers)" in text and "grey t shirt (image 3)" in text
        assert len(google.seen) == 1
    else:
        assert [c.garments for c in fake.calls] == [("new khaki trousers",), ("grey t shirt",)]


async def test_words_jarvis_cant_send_are_refused_before_the_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.wardrobe.seeme import pair as pairmod

    fake = ScriptedTryOn(max_garments=1)
    sw, svc, g = await ready_world(provider=fake)
    monkeypatch.setattr(pairmod, "prompt_words", lambda p: "Charcoal-Trousers")
    err = await _refused(svc.press(UID, ask(g.id, (T.trousers,), inr=9.0)))
    assert (err.status, err.code) == (422, "not_a_garment") and "Google" not in err.words
    assert fake.calls == [] and (await svc.kit.cap.month(UID)).holds == {}


# ---- finding 2: what Google keeps is part of what he agreed to ----------------------------------
async def test_googles_cache_turned_on_after_his_yes_asks_for_it_again_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = ScriptedTryOn(max_garments=1)
    sw, svc, g = await ready_world(provider=fake)  # his YES under "the cache is switched off"
    monkeypatch.setattr(sw.ctx.s, "tryon_cache", True)  # a later deploy: "up to 24 hours"
    view = await svc.overview(UID)
    assert view.consent is not None and view.consent.given and not view.consent.current
    err = await _refused(svc.press(UID, ask(g.id, (), inr=9.0)))
    assert (err.status, err.code) == (409, "consent_needed") and fake.calls == []
    await svc.give_consent(UID, "YES", view.consent.version)  # what he is shown now
    assert (await svc.overview(UID)).consent.current  # type: ignore[union-attr]


# ---- finding 6: one source for the model's end date ---------------------------------------------
async def test_the_other_priced_model_is_not_retired_on_the_first_models_date() -> None:
    adapter, _ = gemini("gemini-nano-banana-2.1", "global")  # a setting (D18): no end date known
    sw, svc, g = await ready_world(provider=adapter, at=ist(2027, 5, 28, 0, 30))
    view = await svc.overview(UID)
    assert view.on and view.notice == "" and view.provider is not None
    assert (view.provider.retires_on, view.provider.ends_soon) == ("", False)
    assert view.consent is not None and not any("28 May 2027" in w for w in view.consent.words)
    pic = await svc.press(UID, ask(g.id, (), inr=await _shown(svc, g.id)))
    assert pic.id.startswith("tp_")


async def test_the_gate_the_notice_and_the_panel_read_the_models_own_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _ = gemini()  # gemini-3.1-flash-image: "May 28, 2027 or later" (G9)
    sw, svc, g = await ready_world(provider=adapter, at=ist(2027, 5, 27, 23, 30))
    monkeypatch.setattr(sw.ctx.s, "tryon_model_retires", "2030-01-01")  # never a second source
    view = await svc.overview(UID)
    assert view.provider is not None and view.provider.retires_on == "2027-05-28"
    assert view.notice == "Google may retire this image model on 28 May 2027." and view.on
    sw.w.clock.set(ist(2027, 5, 28, 0, 30))
    err = await _refused(svc.press(UID, ask(g.id, (), inr=9.0)))
    assert (err.status, err.code) == (503, "retired")


# ---- finding 11: the words of a refused piece ---------------------------------------------------
async def test_a_piece_in_a_taken_slot_or_not_his_is_refused_in_its_own_words() -> None:
    from jarvis.wardrobe.seeme import texts

    fake = ScriptedTryOn(max_garments=1)
    sw, svc, g = await ready_world(provider=fake)  # g: a new navy shirt, a top
    cases = (((T.kurta,), texts.SAME_SLOT),  # one of his tops beside a new top: it IS a top
             ((T.trousers, T.jeans), texts.SAME_SLOT),  # two bottoms of his
             ((T.watch,), texts.NOT_SENDABLE),  # not a garment
             (("wi_00000000ffff",), texts.NOT_HIS))  # fmt: skip
    for n, (pieces, words) in enumerate(cases, start=1):
        err = await _refused(svc.press(UID, ask(g.id, pieces, inr=9.0, n=n)))
        assert (err.status, err.code, err.words) == (422, "not_a_garment", words), pieces
    assert fake.calls == []
