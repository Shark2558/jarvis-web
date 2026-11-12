# tests/test_r11_b_weather.py -- R11 Part B item 4 (docs/plans/r11-free-helpers.md D12): weather
# from Open-Meteo for his place. Written before helpers/house/weather.py: the exact request (his
# rounded point, never his district), the forecast parsed and bounded, one `weather_warning` per
# kind per day over his thresholds, fetched only when due (and never in the same run as SACHET),
# an outage kept and shown, held at 02:00 by the alert policy, OFF with no place or no keyring.
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from r11_fakes import NOON_IST, TWO_AM_IST, UID
from r11_fakes_b import PLACE, FakeFetcher, Rules, fixture, house_ctx

from jarvis.helpers.house import weather
from jarvis.helpers.house.models import Place, Thresholds
from jarvis.helpers.house.store import HouseStore, OutsideStore
from jarvis.helpers.sources import OPEN_METEO_FORECAST_URL

TZ = "Asia/Kolkata"


def _fc(name: str = "b_open_meteo_heavy.json") -> weather.Forecast:
    return weather.parse_forecast(fixture(name), TZ)


def test_the_request_names_his_rounded_point_and_the_fields_only() -> None:
    params = weather.request_params((9.98123, 76.2849), TZ)
    assert params == {
        "latitude": "9.98",
        "longitude": "76.28",
        "hourly": "temperature_2m,apparent_temperature,precipitation,"
        "precipitation_probability,wind_gusts_10m",
        "daily": "temperature_2m_max,apparent_temperature_max,precipitation_sum",
        "timezone": TZ,
        "forecast_days": "2",
    }


def test_the_forecast_is_parsed_and_bad_values_are_left_out() -> None:
    fc = _fc()
    assert len(fc.hours) == 48 and fc.hours[15].precip == pytest.approx(22.4)
    assert fc.hours[0].at.isoformat() == "2026-11-10T00:00:00+05:30"
    raw = json.loads(fixture("b_open_meteo_heavy.json"))
    raw["hourly"]["precipitation"][15] = 9e9  # out of any plausible range
    raw["hourly"]["wind_gusts_10m"][16] = "lots"
    bad = weather.parse_forecast(json.dumps(raw).encode(), TZ)
    assert bad.hours[15].precip is None and bad.hours[16].gust is None
    for broken in (b"[]", b"{not json", json.dumps({"hourly": {"time": "x"}}).encode()):
        with pytest.raises(ValueError):
            weather.parse_forecast(broken, TZ)


def test_hits_over_his_thresholds_in_the_next_24_hours() -> None:
    got = weather.hits(_fc(), Thresholds(), NOON_IST)
    assert [(h.kind, h.at.strftime("%d %H:%M"), round(h.value)) for h in got] == [
        ("rain_hour", "10 15:00", 22),
        ("rain_day", "10 00:00", 70),
        ("gust", "10 15:00", 56),
    ]
    assert weather.hits(_fc("b_open_meteo_calm.json"), Thresholds(), NOON_IST) == []
    hot = Thresholds(feels_c=34.0)
    assert [h.kind for h in weather.hits(_fc("b_open_meteo_calm.json"), hot, NOON_IST)] == ["heat"]


def test_the_summary_for_the_brief() -> None:
    s = weather.summarize(_fc(), NOON_IST)
    assert (s.day, s.t_max, s.rain_from) == ("2026-11-10", 31.0, "14:00")
    calm = weather.summarize(_fc("b_open_meteo_calm.json"), NOON_IST)
    assert calm.rain_from is None


async def _setup(**over: object) -> tuple[object, ...]:
    hc, notifier, docs, clock = house_ctx(**over)  # type: ignore[arg-type]
    outside = OutsideStore(docs, hc.keyring, prefix=hc.prefix)
    if hc.keyring is not None:
        await outside.change(UID, lambda o: o.model_copy(update={"place": Place(**PLACE)}))
    fetcher = FakeFetcher({OPEN_METEO_FORECAST_URL: fixture("b_open_meteo_heavy.json")})
    job = weather.WeatherJob(hc, outside, HouseStore(docs, prefix=hc.prefix), fetcher)
    return hc, notifier, docs, clock, outside, fetcher, job


async def test_one_warning_a_kind_a_day_and_only_when_due() -> None:
    hc, notifier, docs, clock, outside, fetcher, job = await _setup()
    first = await job.run(())
    assert first["sent"] == 3 and len(fetcher.calls) == 1
    assert {k for _, k, _, _ in notifier.calls} == {"weather_warning"}
    assert notifier.calls[0][2] == (
        "Heavy rain likely around 15:00 today: about 22 mm in an hour. "
        "Weather data by Open-Meteo.com."
    )
    clock.at += timedelta(minutes=5)
    await job.run(())
    assert len(fetcher.calls) == 1  # not due: no second call within the hour
    clock.at += timedelta(minutes=60)
    again = await job.run(())
    assert len(fetcher.calls) == 2 and again["sent"] == 0 and len(notifier.calls) == 3
    url, params, _ = fetcher.calls[0]
    assert url == OPEN_METEO_FORECAST_URL and "Ernakulam" not in str(params)
    stored = await outside.read(UID)
    assert stored.weather.summary is not None and stored.weather.ok_at is not None


async def test_an_outage_is_kept_and_nothing_is_sent() -> None:
    _, notifier, _, clock, outside, fetcher, job = await _setup()
    fetcher.fail = True
    got = await job.run(())
    assert got["unreachable"] == 1 and got["failed"] == 0 and notifier.calls == []
    state = (await outside.read(UID)).weather
    assert state.fail_since == clock.at.isoformat()
    fetcher.fail = False
    clock.at += timedelta(minutes=15)  # an outage is tried again sooner than the hour
    await job.run(())
    assert (await outside.read(UID)).weather.fail_since is None


async def test_an_unreadable_answer_counts_as_an_outage() -> None:
    _, notifier, _, _, outside, fetcher, job = await _setup()
    fetcher.answers[OPEN_METEO_FORECAST_URL] = b"<html>busy</html>"
    assert (await job.run(()))["unreachable"] == 1 and notifier.calls == []


async def test_held_at_night_by_the_alert_policy() -> None:
    from r11_fakes import Clock

    _, notifier, _, _, _, _, job = await _setup(clock=Clock(TWO_AM_IST), policy=True)
    await job.run(())
    outcomes = [s.kind for s in notifier.signals]
    assert outcomes and set(outcomes) == {"weather_warning"}
    from jarvis.notify.models import NotifySettings
    from jarvis.notify.policy import decide

    assert {decide(s, NotifySettings(), TWO_AM_IST).action for s in notifier.signals} == {"hold"}


async def test_off_without_a_place_a_keyring_or_his_row() -> None:
    hc, _, docs, _, outside, fetcher, job = await _setup()
    await outside.change(UID, lambda o: o.model_copy(update={"place": None}))
    assert (await job.run(()))["no_place"] == 1 and fetcher.calls == []
    _, _, _, _, _, fetcher2, job2 = await _setup(keyring_on=False)
    assert (await job2.run(()))["off"] == 1 and fetcher2.calls == []
    _, _, _, _, _, fetcher3, job3 = await _setup(rules=Rules(("weather_*",)))
    assert (await job3.run(()))["skipped"] == 1 and fetcher3.calls == []


async def test_weather_no_longer_waits_for_a_sachet_read_in_the_same_run() -> None:
    _, _, _, clock, outside, fetcher, job = await _setup()
    now = clock.at.isoformat()
    await outside.change(
        UID,
        lambda o: o.model_copy(update={"sachet": o.sachet.model_copy(update={"checked_at": now})}),
    )
    assert (await job.run(()))["sent"] == 3 and len(fetcher.calls) == 1  # code review H1


async def test_a_district_with_no_known_centre_and_no_coordinates_has_no_weather() -> None:
    _, _, _, _, outside, fetcher, job = await _setup()
    far = Place(district="Example Nagar", state="Odisha")
    await outside.change(UID, lambda o: o.model_copy(update={"place": far}))
    assert (await job.run(()))["no_point"] == 1 and fetcher.calls == []


async def test_weather_waits_only_when_its_own_slot_is_spent() -> None:
    from jarvis.helpers.house.fetch import WEATHER_SLOT_S, OutsideClock

    hc, _, docs, _, outside, fetcher, _ = await _setup()
    t = [0.0]
    slots = OutsideClock(lambda: t[0])
    job = weather.WeatherJob(hc, outside, HouseStore(docs, prefix=hc.prefix), fetcher, clock=slots)
    slots.deadline("weather")  # weather's slot began at 0 s in this run
    t[0] = WEATHER_SLOT_S - 0.5  # half a second of it left: too little to start a fetch
    assert (await job.run(()))["no_time"] == 1 and fetcher.calls == []
    t[0] = 300.0  # the next run: a fresh slot
    assert (await job.run(()))["sent"] == 3
