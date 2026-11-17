# tests/test_r131_a_bodies.py -- R13.1 Part A, review A-1 F7 and F8: the bodies A's routes read.
# Every body is capped at 16 KB and refused 413 before it is read as JSON; a measurement must be
# sent as a whole number ("172", 172.0, 172.5 and true are refused in words); "Use these
# measurements" is bound to the draft he saw (`?at=`), so a newer one typed on another screen is
# never made current unseen.
from __future__ import annotations

from typing import Any

import pytest
from r131_fakes_a import T, a_world

from jarvis.api import tryon as routes
from jarvis.wardrobe.tryon.http import ROUTES, Refusal, TryonView


def _refusal(r: Any, status: int, code: str) -> Refusal:
    assert r.status_code == status, (r.status_code, r.text)
    got = Refusal.model_validate(r.json())
    assert got.error == code and r.headers["cache-control"] == "no-store", got
    return got


async def test_every_body_is_capped_at_16_kb_before_it_is_read_as_json() -> None:
    a = await a_world()
    big = b'{"height": 172, "x": "' + b"a" * routes.BODY_MAX + b'"}'
    bodied = [(meth, path.replace("{piece}", T.shirt)) for meth, path, part, req, *_ in ROUTES
              if part == "tryon" and req is not None]  # fmt: skip
    assert len(bodied) == 4
    async with a.client() as c:
        for meth, url in bodied:
            got = _refusal(await c.request(meth, url, content=big), 413, "too_large")
            assert got.detail == routes.TOO_LARGE
        ok = await c.put("/v1/tryon/body", content=b'{"height": 172}')
        assert ok.status_code == 200
    for meth, path, part, req, _, errors, _ in ROUTES:
        if part == "tryon" and req is not None:
            assert 413 in errors, (meth, path)  # the contract's rows say so


async def test_use_these_measurements_is_bound_to_the_draft_he_saw() -> None:
    a = await a_world()
    async with a.client() as c:
        laptop = (await c.put("/v1/tryon/body", json={"height": 172})).json()["draft"]["at"]
        a.clock.advance(minutes=3)
        phone = (await c.put("/v1/tryon/body", json={"height": 178})).json()["draft"]["at"]
        stale = await c.post("/v1/tryon/body/use", params={"at": laptop})  # the laptop's press
        assert _refusal(stale, 409, "changed").detail == routes.versions.CHANGED
        kept = TryonView.model_validate((await c.get("/v1/tryon")).json()).body
        assert kept.current is None and kept.draft.height == 178  # type: ignore[union-attr]
        _refusal(await c.post("/v1/tryon/body/use", params={"at": "yesterday"}), 422,
                 "bad_request")  # fmt: skip
        used = await c.post("/v1/tryon/body/use", params={"at": phone})  # the draft he saw
        assert used.status_code == 200 and used.json()["current"]["height"] == 178
    row = next(e for m_, p, _, _, _, e, _ in ROUTES if (m_, p) == ("POST", "/v1/tryon/body/use"))
    assert {409, 422} <= set(row)


@pytest.mark.parametrize("value", ["172", 172.0, 172.5, True])
async def test_a_measurement_not_typed_as_whole_centimetres_is_refused_in_words(value: Any) -> None:
    a = await a_world()
    async with a.client() as c:
        got = _refusal(await c.put("/v1/tryon/body", json={"height": value}), 422, "not_whole")
    assert got.detail == "Type each measurement in whole centimetres, for example 172."
