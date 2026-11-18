# tests/test_r131_c_inflight.py -- R13.1 Part C: a press already in flight never outlives OPS-05,
# his withdrawal or a Privacy delete (docs/plans/r13-1-try-on.md D11, D16; review C-1, finding 3).
# The provider is held at a gate while the delete runs. Afterwards no picture is kept (not in the
# store, not in page memory), the hold is closed at what Google made (it may be billed), his usage
# month hears it, and a repeat of the request id answers the same words. Fixed clocks only;
# nothing reaches Google. Written first and run red.
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from r131_fake_tryon import PNG, Step
from r131_fakes import UID
from r131_fakes_c import FakeBilling, GatedProvider, StrictTryOn, ask, ready_world

from jarvis.wardrobe.seeme.privacy import rows
from jarvis.wardrobe.seeme.texts import SeeMeRefused

BIG = PNG + b"\x00" * (700 * 1024)  # over 700 KB: shown once from page memory, never stored


def _row(svc: Any, rid: str) -> Any:
    return {r.id: r for r in rows(svc)}[rid]


DELETES: dict[str, Callable[[Any], Awaitable[Any]]] = {
    "ops05_erase": lambda svc: svc.erase(UID),
    "his_withdrawal": lambda svc: svc.delete_photo(UID),
    "the_photo_row": lambda svc: _row(svc, "tryon_photo").delete(UID),
    "the_pictures_row": lambda svc: _row(svc, "tryon_pictures").delete(UID),
}


def _pictures(sw: Any) -> list[str]:
    return [p for p in sw.docs._data if "tryon_picture/" in p]  # noqa: SLF001


async def _refused(coro: Awaitable[Any]) -> SeeMeRefused:
    with pytest.raises(SeeMeRefused) as err:
        await coro
    return err.value


async def _during_a_press(delete: Callable[[Any], Awaitable[Any]], picture: bytes = PNG) -> Any:
    script = [Step(picture=picture)]
    gated = GatedProvider(
        StrictTryOn(max_garments=3, model="gemini-3.1-flash-image", script=script)
    )
    billing = FakeBilling()
    sw, svc, g = await ready_world(provider=gated, billing=billing)
    body = ask(g.id, (), inr=(await svc.estimate(UID, g.id, [])).typical_inr)
    press = asyncio.create_task(svc.press(UID, body))
    await gated.entered.wait()  # Google is making it
    await delete(svc)
    gated.gate.set()  # ... and now it answers
    return sw, svc, body, billing, await _refused(press)


@pytest.mark.parametrize("delete", list(DELETES))
async def test_a_press_in_flight_keeps_no_picture_after_a_delete(delete: str) -> None:
    sw, svc, body, billing, err = await _during_a_press(DELETES[delete])
    assert (err.status, err.code) == (422, "no_photo"), delete
    assert "isn't kept" in err.words and "It may still be charged (about ₹" in err.words
    assert _pictures(sw) == [], delete
    month = await svc.kit.cap.month(UID)
    assert (month.held_inr, month.holds) == (0.0, {}) and month.spent_inr > 0  # closed, billed
    assert [(u, label) for u, label, _ in billing.recorded] == [(UID, "tryon")]  # his month
    again = await _refused(svc.press(UID, body))  # a repeat says the same, and makes nothing
    assert (again.status, again.code) == (422, "no_photo") and len(billing.recorded) == 1


@pytest.mark.parametrize("delete", ["ops05_erase", "his_withdrawal", "the_photo_row"])
async def test_a_big_picture_in_flight_is_not_shown_once_after_a_delete(delete: str) -> None:
    sw, svc, body, billing, err = await _during_a_press(DELETES[delete], picture=BIG)
    assert err.code == "no_photo"
    assert svc.kit.pictures.once._items == {}  # noqa: SLF001 - page memory holds nothing of it


@pytest.mark.parametrize("delete", ["his_withdrawal", "the_photo_row"])
async def test_his_withdrawal_clears_a_shown_once_picture(delete: str) -> None:
    fake = StrictTryOn(max_garments=3, model="gemini-3.1-flash-image", script=[Step(picture=BIG)])
    sw, svc, g = await ready_world(provider=fake)
    pic = await svc.press(UID, ask(g.id, (), inr=(await svc.estimate(UID, g.id, [])).typical_inr))
    await DELETES[delete](svc)
    assert await svc.picture(UID, pic.id) is None  # not for 10 more minutes


async def test_ops05_erase_also_takes_a_picture_saved_between_its_list_and_its_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sw, svc, g = await ready_world()
    shown = (await svc.estimate(UID, g.id, [])).typical_inr
    real, listed = svc.kit.pictures.rows, []

    async def late(uid: str) -> Any:
        found = await real(uid)
        if not listed:  # a press saves its picture just after erase has listed the pictures
            listed.append(await svc.press(UID, ask(g.id, (), inr=shown)))
        return found

    monkeypatch.setattr(svc.kit.pictures, "rows", late)
    await svc.erase(UID)
    assert listed and _pictures(sw) == []
