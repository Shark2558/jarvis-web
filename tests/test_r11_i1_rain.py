# tests/test_r11_i1_rain.py -- R11 I1, rain across parts (plan D12, INTEGRATION-C "Needs I1" 2):
# Part B exposes `services["rain"]` (`helpers.house.rain.RainHint`, read from his sealed weather
# summary: rain likely from HH:MM today; unknown when his place isn't set, the summary is stale
# or from another day), the wiring hands it to Part C late as `HelperContext.rain`, and C's
# free-time pick then avoids an outdoor idea when rain is likely in the gap.
from __future__ import annotations

import base64
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from r11_fakes import UID, Clock, ctx
from r11_fakes_b import PLACE, house_ctx

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.helpers.house import part as house_part
from jarvis.helpers.house.models import Place, WeatherSummary
from jarvis.helpers.house.rain import STALE_AFTER, RainHint
from jarvis.helpers.house.store import OutsideStore
from jarvis.helpers.nudges import part as nudges_part
from jarvis.helpers.nudges.freetime import pick
from jarvis.helpers.nudges.models import Idea
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

NOON = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)  # 12:00 in Asia/Kolkata
IST = timedelta(hours=5, minutes=30)


def _ist(h: int, m: int = 0) -> datetime:
    return datetime(2026, 11, 10, h, m, tzinfo=UTC) - IST


async def _hint(summary: WeatherSummary | None, clock: Clock) -> RainHint:
    hc, _, docs, _ = house_ctx(clock=clock)
    outside = OutsideStore(docs, hc.keyring, prefix=hc.prefix)

    def put(o: Any) -> Any:
        weather = o.weather.model_copy(update={"summary": summary})
        return o.model_copy(update={"weather": weather, "place": Place(**PLACE)})

    await outside.change(UID, put)
    return RainHint(outside, tz=hc.tz, now=clock)


def _summary(rain_from: str | None, at: datetime = NOON) -> WeatherSummary:
    return WeatherSummary(day="2026-11-10", t_max=31.0, rain_from=rain_from, at=at.isoformat())


async def test_rain_from_three_oclock_makes_an_afternoon_gap_rainy_and_a_noon_one_dry() -> None:
    clock = Clock(NOON)
    hint = await _hint(_summary("15:00"), clock)
    assert await hint.rain_likely(UID, _ist(14), _ist(16)) is True
    assert await hint.rain_likely(UID, _ist(12), _ist(13)) is False
    dry = await _hint(_summary(None), clock)
    assert await dry.rain_likely(UID, _ist(12), _ist(18)) is False


async def test_no_place_a_stale_or_another_days_summary_or_no_keyring_is_unknown() -> None:
    clock = Clock(NOON)
    assert await (await _hint(None, clock)).rain_likely(UID, _ist(12), _ist(13)) is None
    old = _summary("15:00", at=NOON - STALE_AFTER - timedelta(minutes=1))
    assert await (await _hint(old, clock)).rain_likely(UID, _ist(14), _ist(16)) is None
    hint = await _hint(_summary("15:00"), clock)
    tomorrow = _ist(14) + timedelta(days=1)
    assert await hint.rain_likely(UID, tomorrow, tomorrow + timedelta(hours=2)) is None
    hc, _, docs, _ = house_ctx(clock=clock, keyring_on=False)
    off = RainHint(OutsideStore(docs, None, prefix=hc.prefix), tz=hc.tz, now=clock)
    assert await off.rain_likely(UID, _ist(14), _ist(16)) is None


def test_part_b_exposes_the_hint_as_its_rain_service() -> None:
    hc, _, _, _ = house_ctx()
    part = house_part.build(hc)
    assert isinstance(part.services["rain"], RainHint) and "house" in part.services


async def test_c_s_free_time_pick_avoids_an_outdoor_idea_when_b_says_rain() -> None:
    clock = Clock(_ist(14))
    hint = await _hint(_summary("15:00", at=_ist(13, 30)), clock)
    c, _, _, _ = ctx("nudges", clock=clock)
    svc = nudges_part.service(replace(c, rain=lambda: hint))
    ideas = (
        Idea(id="0000000a", text="Walk by the lake", minutes=45, place="outdoor"),
        Idea(id="0000000b", text="Read a chapter", minutes=40, place="indoor"),
    )
    rain = await svc.rain_likely(UID, _ist(14), _ist(15, 30))
    assert rain is True
    for day in range(7):  # whichever idea the day would pick, never the outdoor one in rain
        got = pick(ideas, 60, rain, NOON.date() + timedelta(days=day))
        assert got is not None and got.place == "indoor"
    dry = await svc.rain_likely(UID, _ist(14), _ist(14, 45))
    assert dry is False
    assert {pick(ideas, 60, dry, NOON.date() + timedelta(days=d)).id for d in range(2)} == {  # type: ignore[union-attr]
        "0000000a",
        "0000000b",
    }


async def test_the_wiring_hands_part_bs_rain_to_part_c_late() -> None:
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    s = Settings(_env_file=None, llm_backend="mock", session_backend="memory", token_key=key)  # type: ignore[call-arg]
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        parts = app.state.r11_parts
        rain = parts["house"].services["rain"]
        nudges = parts["nudges"].services["service"]
        assert nudges._rain() is rain  # noqa: SLF001 - C reads B's hint through ctx.rain
        assert await nudges.rain_likely(UID, _ist(14), _ist(16)) is None  # no place set yet


async def test_a_malformed_summary_is_unknown_never_an_error() -> None:
    """Integrated review L3/L4: a bad "rain from" or a time with no zone is None (no rain rule)."""
    clock = Clock(NOON)
    for rain_from in ("rain", "25", "15:xx", "15:00:00:00", "99:99"):
        hint = await _hint(_summary(rain_from), clock)
        assert await hint.rain_likely(UID, _ist(14), _ist(16)) is None, rain_from
    naive = _summary("15:00", at=NOON.replace(tzinfo=None))
    hint = await _hint(naive, clock)
    assert await hint.rain_likely(UID, _ist(14), _ist(16)) is None
