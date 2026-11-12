# tests/test_r11_b_outside_run.py -- R11 Part B, code review H1 (docs/plans/r11-free-helpers.md
# D3, D12, D13): SACHET and weather each have their own slot of Part B's share of the shared 20 s
# clock run, and take their turns one after the other. A SACHET outage or backlog spends only
# SACHET's slot, so weather is still fetched whenever it is due (the reviewer's 12-tick outage).
from __future__ import annotations

from datetime import timedelta

from r11_fakes import UID
from r11_fakes_b import PLACE, FakeFetcher, fixture, house_ctx, sachet_fetcher

from jarvis.helpers.house import fetch, sachet, weather
from jarvis.helpers.house.fetch import OutsideClock
from jarvis.helpers.house.models import Place
from jarvis.helpers.house.store import HouseStore, OutsideStore
from jarvis.helpers.sources import OPEN_METEO_FORECAST_URL, SACHET_CAP_URL


async def _pair(fs: object, fw: object, mono: object = None, **over: object) -> tuple[object, ...]:
    hc, notifier, docs, clock = house_ctx(**over)  # type: ignore[arg-type]
    outside = OutsideStore(docs, hc.keyring, prefix=hc.prefix)
    await outside.change(UID, lambda o: o.model_copy(update={"place": Place(**PLACE)}))
    store = HouseStore(docs, prefix=hc.prefix)
    oc = OutsideClock(mono or (lambda: clock.at.timestamp()))  # type: ignore[arg-type]
    dj = sachet.DisasterJob(hc, outside, store, fs, clock=oc)  # type: ignore[arg-type]
    wj = weather.WeatherJob(hc, outside, store, fw, clock=oc)  # type: ignore[arg-type]
    return notifier, clock, outside, dj, wj


async def test_weather_is_fetched_when_due_through_a_12_tick_sachet_outage() -> None:
    fs = sachet_fetcher(fail=True)
    fw = FakeFetcher({OPEN_METEO_FORECAST_URL: fixture("b_open_meteo_heavy.json")})
    _, clock, outside, dj, wj = await _pair(fs, fw, weather_poll_minutes=15)
    fetched: list[int] = []
    for tick in range(12):  # an hour of 5-minute runs with SACHET down
        assert (await dj.run(()))["unreachable"] == 1  # type: ignore[attr-defined]
        before = len(fw.calls)
        got = await wj.run(())  # type: ignore[attr-defined]
        assert got.get("deferred", 0) == 0
        if len(fw.calls) > before:
            fetched.append(tick)
        clock.at += timedelta(minutes=5)  # type: ignore[attr-defined]
    assert fetched == [0, 3, 6, 9]  # every 15 minutes, exactly when due
    assert (await outside.read(UID)).sachet.fail_since is not None  # type: ignore[attr-defined]


async def test_a_sachet_backlog_spends_only_sachets_slot() -> None:
    now = [1000.0]
    timeouts: list[tuple[str, float]] = []

    def slow(inner: FakeFetcher) -> object:
        real = inner.get

        async def get(url: str, **kw: object) -> object:
            timeouts.append((url, float(kw["timeout_s"])))  # type: ignore[arg-type]
            now[0] += 3.0  # every outside read takes 3 s
            return await real(url, **kw)  # type: ignore[arg-type]

        inner.get = get  # type: ignore[method-assign]
        return inner

    fs = slow(sachet_fetcher())
    fw = slow(FakeFetcher({OPEN_METEO_FORECAST_URL: fixture("b_open_meteo_heavy.json")}))
    _, _, outside, dj, wj = await _pair(fs, fw, mono=lambda: now[0])
    await dj.run(())  # type: ignore[attr-defined]
    sachet_reads = [t for u, t in timeouts if u != OPEN_METEO_FORECAST_URL]
    assert len(sachet_reads) < 6 and all(t <= fetch.SACHET_SLOT_S for t in sachet_reads)
    assert (await outside.read(UID)).sachet.queue  # type: ignore[attr-defined]  # the rest waits
    assert (await wj.run(()))["sent"] == 3  # type: ignore[attr-defined]  # same run, its own slot
    (wx,) = [t for u, t in timeouts if u == OPEN_METEO_FORECAST_URL]
    assert fetch.MIN_LEFT_S <= wx <= fetch.WEATHER_SLOT_S
    assert any(u == SACHET_CAP_URL for u, _ in timeouts)


def test_the_slots_fit_part_bs_share_of_the_shared_clock_run() -> None:
    t = [0.0]
    oc = OutsideClock(lambda: t[0])
    assert oc.deadline("sachet") == fetch.SACHET_SLOT_S
    t[0] = 6.5  # SACHET used most of its slot; weather starts its own
    assert oc.deadline("weather") == min(6.5 + fetch.WEATHER_SLOT_S, fetch.SHARE_S)
    assert fetch.SACHET_SLOT_S + fetch.WEATHER_SLOT_S <= fetch.SHARE_S < 19.0
    t[0] = 300.0  # the next 5-minute run starts over
    assert oc.deadline("weather") == 300.0 + fetch.WEATHER_SLOT_S
    assert sachet.DisasterJob.budget_s <= fetch.SACHET_SLOT_S + 1
    assert weather.WeatherJob.budget_s <= fetch.WEATHER_SLOT_S + 1
