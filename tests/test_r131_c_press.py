# tests/test_r131_c_press.py -- R13.1 Part C: the press, from the ₹ shown to the picture
# (docs/plans/r13-1-try-on.md D13.4-D13.7, D10, D14; BRIEF-C "The press", "Pictures"). The gates in
# order, each refusing before any spend; ONE make; settle from usage, at the hold without it,
# released on "not billed", kept on "maybe billed" and a blocked 200; a repeated request id answers
# its outcome; the picture kept as returned. Fakes only: no call reaches Google. Written first.
from __future__ import annotations

from datetime import timedelta

import pytest
from r131_fake_gemini import (
    INSTRUCTION,
    PNG_OUT,
    FakeGoogle,
    FakeTokens,
    picture_answer,
    project_of,
)
from r131_fake_tryon import Step
from r131_fakes import NOW, UID, T, ist
from r131_fakes_c import NEW_SHIRT, PERSON, FakeBilling, OffMode, ask, ready_world, shown_version
from r131_fakes_c import StrictTryOn as ScriptedTryOn  # the adapter's own pre-send check too

from jarvis.llm.tryon import TryOnMaybeBilled, TryOnNotBilled
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.seeme.vault import clean_jpeg
from jarvis.wardrobe.tryon import model as m


def gemini(script: list | None = None):  # type: ignore[no-untyped-def,type-arg]
    from jarvis.llm.tryon_gemini import GeminiTryOn

    google = FakeGoogle(script or [picture_answer()])
    adapter = GeminiTryOn(model="gemini-3.1-flash-image", location="us", tokens=FakeTokens(),
                          project=project_of(), http=google.client())  # fmt: skip
    return adapter, google


async def _shown(svc, garment: str, pieces: tuple[str, ...] = ()) -> float:  # type: ignore[no-untyped-def]
    return (await svc.estimate(UID, garment, list(pieces))).typical_inr


async def _refused(coro) -> SeeMeRefused:  # type: ignore[no-untyped-def]
    with pytest.raises(SeeMeRefused) as err:
        await coro
    return err.value


# ---- a picture -----------------------------------------------------------------------------------
async def test_a_picture_settles_from_usage_and_is_kept_as_google_returned_it() -> None:
    adapter, google = gemini()
    billing = FakeBilling()
    sw, svc, g = await ready_world(provider=adapter, billing=billing)
    shown = await _shown(svc, g.id, (T.trousers,))
    assert shown == 8.9
    pic = await svc.press(UID, ask(g.id, (T.trousers,), inr=shown))
    assert pic.id.startswith("tp_") and pic.made_at == NOW and pic.inr == 8.52
    assert pic.garment.id == g.id and pic.garment.words == "a new navy shirt, not in your wardrobe"
    assert [(p.piece, p.words) for p in pic.sent] == [(T.trousers, "charcoal trousers")]
    assert pic.label == m.GENERATED and pic.credentials == m.CREDENTIALS
    assert pic.mime == "image/png" and pic.until == NOW + timedelta(days=30) and not pic.kept
    assert await svc.picture(UID, pic.id) == (PNG_OUT, "image/png")  # never re-encoded
    month = await svc.kit.cap.month(UID)
    assert (month.spent_inr, month.held_inr, month.pictures) == (8.52, 0.0, 1)
    assert billing.recorded == [(UID, "tryon", pytest.approx(0.0758505))]  # Vitals: "Try-on"
    assert len(google.seen) == 1  # ONE make


async def test_what_reaches_the_provider_is_his_photo_the_garment_and_his_crop_only() -> None:
    fake = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image")
    sw, svc, g = await ready_world(provider=fake)
    await svc.press(UID, ask(g.id, (T.trousers,), inr=await _shown(svc, g.id, (T.trousers,))))
    [call] = fake.calls
    assert call.person == clean_jpeg(PERSON, max_kb=700)
    assert call.garments == ("a new navy shirt", "charcoal trousers")  # fixed words only


async def test_the_one_garment_fake_chains_inside_itself_and_answers_one_picture() -> None:
    fake = ScriptedTryOn(max_garments=1)  # I0's: n garments, n requests, one result
    sw, svc, g = await ready_world(provider=fake)
    pic = await svc.press(UID, ask(g.id, (T.trousers,), inr=await _shown(svc, g.id, (T.trousers,))))
    assert len(fake.calls) == 2 and pic.id.startswith("tp_")
    month = await svc.kit.cap.month(UID)
    assert month.spent_inr == month.held_inr + month.spent_inr  # settled (no hold left)
    assert month.held_inr == 0.0 and month.spent_inr > 0  # unpriced model: at the hold


async def test_a_new_garment_alone_is_one_picture_too() -> None:
    sw, svc, g = await ready_world()
    pic = await svc.press(UID, ask(g.id, (), inr=await _shown(svc, g.id)))
    assert pic.sent == () and pic.garment.id == g.id


# ---- the gates, in order, each before any spend --------------------------------------------------
async def test_the_gates_refuse_in_their_order_and_nothing_is_called() -> None:
    fake = ScriptedTryOn(max_garments=1)
    sw, svc, g = await ready_world(provider=fake, mode=OffMode(), consent=False,
                                   billing=FakeBilling(limit=100, used_inr=99.0))  # fmt: skip
    body = ask(g.id, (T.vest,), inr=0.0, confirm=False)
    seen = [(await _refused(svc.press(UID, body))).code]  # no_ai first
    sw.state["brain_mode"] = None  # can't tell: fail closed
    assert (await _refused(svc.press(UID, body))).code == "no_ai"
    from r131_fakes_c import OnMode

    sw.state["brain_mode"] = OnMode()
    seen.append((await _refused(svc.press(UID, body))).code)  # consent
    await svc.give_consent(UID, "YES", shown_version(svc))
    await svc.delete_garment(UID, g.id)
    photo_less = await svc.delete_photo(UID)  # his YES goes with his photo
    assert photo_less is True
    await svc.give_consent(UID, "YES", shown_version(svc))
    seen.append((await _refused(svc.press(UID, body))).code)  # his photo
    await svc.save_photo(UID, PERSON)
    seen.append((await _refused(svc.press(UID, body))).code)  # the garment's photo
    g2 = await svc.add_garment(UID, "shirt", "navy", NEW_SHIRT)
    body = ask(g2.id, (T.vest,), inr=0.0, confirm=False)
    seen.append((await _refused(svc.press(UID, body))).code)  # a private piece
    body = ask(g2.id, (T.trousers,), inr=0.0, confirm=False)
    seen.append((await _refused(svc.press(UID, body))).code)  # confirm_cost
    body = ask(g2.id, (T.trousers,), inr=0.0)
    seen.append((await _refused(svc.press(UID, body))).code)  # the ₹ shown
    shown = await _shown(svc, g2.id, (T.trousers,))
    body = ask(g2.id, (T.trousers,), inr=shown)
    seen.append((await _refused(svc.press(UID, body))).code)  # his overall limit
    assert seen == ["no_ai", "consent_needed", "no_photo", "no_garment", "private_piece",
                    "confirm_cost", "price_changed", "budget_reached"]  # fmt: skip
    assert fake.calls == [] and (await svc.kit.cap.month(UID)).holds == {}


async def test_pictures_off_or_no_provider_is_not_configured() -> None:
    sw, svc, g = await ready_world()
    sw.state["provider"] = None
    err = await _refused(svc.press(UID, ask(g.id)))
    assert (err.status, err.code) == (503, "not_configured")


async def test_a_private_piece_is_refused_from_the_record_whatever_the_console_says() -> None:
    fake = ScriptedTryOn(max_garments=1)
    sw, svc, g = await ready_world(provider=fake)
    shown = await _shown(svc, g.id, (T.trousers,))
    await sw.w.edit(T.trousers, private=True)  # made private after the estimate
    err = await _refused(svc.press(UID, ask(g.id, (T.trousers,), inr=shown)))
    assert (err.status, err.code) == (422, "private_piece") and fake.calls == []


async def test_a_piece_without_a_front_crop_or_not_a_garment_is_refused_before_any_call() -> None:
    fake = ScriptedTryOn(max_garments=1)
    sw, svc, g = await ready_world(provider=fake)
    for piece, code in ((T.shirt, "not_a_garment"), (T.watch, "not_a_garment"),
                        (T.kurta, "not_a_garment")):  # fmt: skip  # a top beside a new top
        assert (await _refused(svc.press(UID, ask(g.id, (piece,), inr=9.0)))).code == code
    trousers = await svc.add_garment(UID, "trousers", "khaki", NEW_SHIRT)
    err = await _refused(svc.press(UID, ask(trousers.id, (T.shirt,), inr=9.0)))
    assert err.code == "no_photo" and fake.calls == []


async def test_the_cap_and_busy_are_the_last_gates() -> None:
    sw, svc, g = await ready_world()
    await svc.settings(UID, cap_inr=5, keep_days=None, on=None, confirm_cost=False)
    err = await _refused(svc.press(UID, ask(g.id, (), inr=await _shown(svc, g.id))))
    assert (err.status, err.code) == (402, "cap_reached")


async def test_past_the_models_end_date_it_is_retired_and_said_before() -> None:
    for at, retired, notice in ((ist(2027, 4, 27, 23, 30), False, False),
                                (ist(2027, 4, 28, 0, 30), False, True),
                                (ist(2027, 5, 27, 23, 30), False, True),
                                (ist(2027, 5, 28, 0, 30), True, True)):  # fmt: skip
        sw, svc, g = await ready_world(at=at)
        view = await svc.overview(UID)
        assert (view.notice == "Google may retire this image model on 28 May 2027.") is notice
        assert view.provider is not None and view.provider.ends_soon is notice
        if retired:
            err = await _refused(svc.press(UID, ask(g.id)))
            assert (err.status, err.code) == (503, "retired") and not view.on
        else:
            assert view.on, at


# ---- billed or not -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("step", "status", "code", "spent"),
    [
        (Step(error=TryOnNotBilled("status_500")), 503, "provider_unavailable", 0.0),
        (Step(error=TryOnNotBilled("not_sent")), 503, "provider_unavailable", 0.0),
        (Step(error=TryOnMaybeBilled("timeout")), 503, "provider_unavailable", 11.22),
        (Step(blocked="safety"), 502, "blocked", 11.22),
    ],
)
async def test_released_when_not_billed_and_kept_at_the_hold_otherwise(
    step: Step, status: int, code: str, spent: float
) -> None:
    fake = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image", script=[step])
    sw, svc, g = await ready_world(provider=fake)
    shown = await _shown(svc, g.id, (T.trousers,))
    err = await _refused(svc.press(UID, ask(g.id, (T.trousers,), inr=shown)))
    assert (err.status, err.code) == (status, code)
    month = await svc.kit.cap.month(UID)
    assert (month.spent_inr, month.held_inr) == (spent, 0.0)
    if code == "blocked":
        assert month.blocked == 1 and "It may still be charged (about ₹" in err.words
    assert "$" not in err.words


async def test_googles_429_says_busy_and_nothing_was_charged() -> None:
    adapter, _ = gemini([429])
    sw, svc, g = await ready_world(provider=adapter)
    err = await _refused(svc.press(UID, ask(g.id, (), inr=await _shown(svc, g.id))))
    assert err.code == "provider_unavailable" and "busy" in err.words and "Nothing" in err.words


async def test_after_googles_429_press_again_asks_google_again_and_pays_once() -> None:
    # integrated security review finding 2: the not-billed refusal was kept in `done`, so the
    # console's retry (the same request id, "press See it on me again") replayed it forever
    adapter, google = gemini([429, picture_answer()])
    billing = FakeBilling()
    sw, svc, g = await ready_world(provider=adapter, billing=billing)
    body = ask(g.id, (), inr=await _shown(svc, g.id))
    first = await _refused(svc.press(UID, body))
    assert first.code == "provider_unavailable" and "Nothing was charged" in first.words
    pic = await svc.press(UID, body)  # the same request id: Google is asked again
    assert pic.id.startswith("tp_") and len(google.seen) == 2
    again = await svc.press(UID, body)  # a lost reply's retry now: the same picture, not paid
    assert again.id == pic.id and len(google.seen) == 2
    month = await svc.kit.cap.month(UID)
    assert (month.pictures, month.held_inr) == (1, 0.0) and month.spent_inr == pic.inr
    assert len(billing.recorded) == 1


async def test_no_usage_in_the_answer_is_settled_at_the_hold() -> None:
    adapter, _ = gemini([picture_answer(usage=None)])
    sw, svc, g = await ready_world(provider=adapter)
    pic = await svc.press(UID, ask(g.id, (T.trousers,), inr=await _shown(svc, g.id, (T.trousers,))))
    assert pic.inr == 11.22 and (await svc.kit.cap.month(UID)).spent_inr == 11.22


async def test_a_text_part_in_googles_answer_is_kept_nowhere() -> None:
    adapter, _ = gemini([picture_answer(text=INSTRUCTION)])
    sw, svc, g = await ready_world(provider=adapter)
    pic = await svc.press(UID, ask(g.id, (), inr=await _shown(svc, g.id)))
    assert INSTRUCTION not in pic.model_dump_json()
    for path, doc in sw.docs._data.items():  # noqa: SLF001 - every document, sealed or not
        assert INSTRUCTION not in str(doc), path


async def test_a_repeated_request_id_answers_the_same_picture_once_charged() -> None:
    fake = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image")
    sw, svc, g = await ready_world(provider=fake)
    body = ask(g.id, (T.trousers,), inr=await _shown(svc, g.id, (T.trousers,)))
    first = await svc.press(UID, body)
    again = await svc.press(UID, body)
    assert again.id == first.id and len(fake.calls) == 1
    assert (await svc.kit.cap.month(UID)).spent_inr == 8.52


async def test_a_repeated_failed_request_id_answers_the_same_refusal() -> None:
    down = Step(error=TryOnNotBilled("status_500"))
    fake = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image",
                         script=[down, down])  # fmt: skip
    sw, svc, g = await ready_world(provider=fake)
    body = ask(g.id, (), inr=await _shown(svc, g.id))
    assert (await _refused(svc.press(UID, body))).code == "provider_unavailable"
    assert (await _refused(svc.press(UID, body))).code == "provider_unavailable"
    assert len(fake.calls) == 2  # not billed: asked again, never replayed (I1 security, 2)
    assert (await svc.kit.cap.month(UID)).spent_inr == 0.0


async def test_a_picture_over_700_kb_is_shown_once_and_not_kept() -> None:
    big = PNG_OUT + b"\x00" * (700 * 1024)
    fake = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image",
                         script=[Step(picture=big)])  # fmt: skip
    sw, svc, g = await ready_world(provider=fake)
    pic = await svc.press(UID, ask(g.id, (), inr=await _shown(svc, g.id)))
    assert pic.until is None and not pic.kept
    assert await svc.picture(UID, pic.id) == (big, "image/png")  # shown once
    assert await svc.picture(UID, pic.id) is None  # and not kept
    assert all(not p.startswith("jarvis_tryon_picture/") for p in sw.docs._data)  # noqa: SLF001


# ---- pictures: keep, list, delete ----------------------------------------------------------------
async def test_keep_lifts_the_30_days_at_most_24_and_delete_takes_one() -> None:
    sw, svc, g = await ready_world()
    pic = await svc.press(UID, ask(g.id, (), inr=await _shown(svc, g.id)))
    kept = await svc.keep(UID, pic.id, True)
    assert kept.kept and kept.until is None
    back = await svc.keep(UID, pic.id, False)
    assert back.until == NOW + timedelta(days=30)
    listed = (await svc.overview(UID)).pictures
    assert [p.id for p in listed] == [pic.id]
    assert await svc.delete_picture(UID, pic.id) is True
    assert await svc.picture(UID, pic.id) is None and await svc.delete_picture(UID, pic.id) is False


async def test_the_25th_kept_picture_is_refused() -> None:
    from jarvis.storage.docs import Set

    sw, svc, g = await ready_world()
    prefix = sw.ctx.s.firestore_prefix
    rows = [Set(f"{prefix}tryon_picture/{UID}_tp_{n:012x}",
                {"owner": UID, "kept": True, "at": NOW.isoformat(), "garment": g.id})
            for n in range(m.KEPT_MAX)]  # fmt: skip
    await sw.docs.write(rows)
    pic = await svc.press(UID, ask(g.id, (), inr=await _shown(svc, g.id), n=2))
    err = await _refused(svc.keep(UID, pic.id, True))
    assert (err.status, err.code) == (409, "too_many")


async def test_the_garment_is_never_his_after_upload_pairing_picture_and_delete() -> None:
    sw, svc, g = await ready_world()
    before = await sw.rev()
    await svc.pair(UID, g.id)
    await svc.estimate(UID, g.id, [T.jeans])
    await svc.press(UID, ask(g.id, (T.jeans,), inr=await _shown(svc, g.id, (T.jeans,))))
    await svc.delete_garment(UID, g.id)
    assert await sw.rev() == before  # R13's rev and every piece unchanged
    assert all("tg_" not in k for k in before[1])


async def test_a_made_picture_is_kept_and_settled_when_the_rest_of_the_look_cant_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image")
    sw, svc, g = await ready_world(provider=fake)
    shown = await _shown(svc, g.id, (T.trousers,))

    async def blip(*args: object, **kw: object) -> None:
        raise RuntimeError("storage blip")  # after Google made (and billed) the picture

    monkeypatch.setattr(svc.kit.pairer, "from_look", blip)
    pic = await svc.press(UID, ask(g.id, (T.trousers,), inr=shown))
    assert [p.piece for p in pic.sent] == [T.trousers] and pic.not_sent == ()
    assert await svc.picture(UID, pic.id) is not None  # kept, not lost
    month = await svc.kit.cap.month(UID)
    assert (month.spent_inr, month.held_inr, month.pictures) == (8.52, 0.0, 1)


async def test_a_repeated_maybe_billed_request_id_answers_the_same_code() -> None:
    from jarvis.wardrobe.tryon.http import SEEME_ERRORS

    fake = ScriptedTryOn(max_garments=3, model="gemini-3.1-flash-image",
                         script=[Step(error=TryOnMaybeBilled("timeout"))])  # fmt: skip
    sw, svc, g = await ready_world(provider=fake)
    body = ask(g.id, (), inr=await _shown(svc, g.id))
    first = await _refused(svc.press(UID, body))
    again = await _refused(svc.press(UID, body))
    assert (first.status, first.code) == (again.status, again.code) == (503, "provider_unavailable")
    assert "may still be charged" in again.words and len(fake.calls) == 1
    cut = ask(g.id, (), inr=9.0, n=2)  # a press cut off between its reserve and its answer
    await svc.kit.cap.reserve(UID, cut.request_id, 11.22, 300)
    sw.w.clock.set(sw.w.clock() + timedelta(hours=2))
    assert await svc.kit.cap.settle_old(UID) == 1  # the daily job: settled at its hold
    late = await _refused(svc.press(UID, cut))
    assert (late.status, late.code) == (503, "provider_unavailable") and late.code in SEEME_ERRORS
    assert len(fake.calls) == 1


async def test_an_id_with_a_trailing_newline_never_reaches_a_path() -> None:
    sw, svc, g = await ready_world()
    pic = await svc.press(UID, ask(g.id, (), inr=await _shown(svc, g.id)))
    real, read = sw.docs.get, []

    async def spy(path: str) -> object:
        read.append(path)
        return await real(path)

    sw.docs.get = spy  # type: ignore[method-assign]
    assert await svc.garment_photo(UID, g.id + "\n") is None
    assert await svc.delete_garment(UID, g.id + "\n") is False
    assert await svc.picture(UID, pic.id + "\n") is None
    assert await svc.delete_picture(UID, pic.id + "\n") is False
    assert not any("\n" in p for p in read), read


async def test_a_provider_that_never_answers_is_cut_at_the_deadline_and_kept_at_the_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from jarvis.wardrobe.seeme import make as makemod

    class Hangs(ScriptedTryOn):
        async def make(self, ask):  # type: ignore[no-untyped-def,override]
            await asyncio.sleep(60)

    monkeypatch.setattr(makemod, "CALL_DEADLINE_S", 0.01)
    monkeypatch.setattr(makemod, "DEADLINE_SLACK_S", 0.0)
    sw, svc, g = await ready_world(provider=Hangs(max_garments=3, model="gemini-3.1-flash-image"))
    err = await _refused(svc.press(UID, ask(g.id, (), inr=await _shown(svc, g.id))))
    assert err.code == "provider_unavailable" and "may still be charged" in err.words
    month = await svc.kit.cap.month(UID)
    assert month.held_inr == 0.0 and month.spent_inr > 0  # maybe billed: kept at the hold
