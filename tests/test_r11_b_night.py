# tests/test_r11_b_night.py -- R11 Part B, security review M3 (docs/plans/r11-free-helpers.md D13):
# night rings stay bounded even when SACHET's identifiers mutate. A warning is told once per
# content key (kind, the fixed event word, his district, the onset day) whatever its identifier;
# at night at most 3 distinct `disaster_alert`s ring, any further ones fold into ONE held morning
# summary plus at most one "more alerts, open the SACHET app" ring an hour. By day the existing
# rules stand. The reviewer's probe: 60 RSS items, the landslide CAP under 60 identifiers.
from __future__ import annotations

import re
from datetime import date, timedelta

from r11_fakes import NOON_IST, TWO_AM_IST, UID, Clock
from r11_fakes_b import PLACE, fixture, house_ctx, sachet_fetcher

from jarvis.helpers.house import night, sachet, words
from jarvis.helpers.house.models import Place
from jarvis.helpers.house.store import HouseStore, OutsideStore
from jarvis.helpers.sources import SACHET_RSS_URL
from jarvis.notify.models import NotifySettings
from jarvis.notify.policy import decide

ONSET = "2026-11-10T01:30:00+05:30"


def _flood(count: int, *, mutate_onset: bool) -> object:
    f = sachet_fetcher()
    base = fixture("b_cap_geo_landslide.xml").decode()
    rss = fixture("b_sachet_rss.xml").decode()
    items = "".join(
        f'<item><title>t</title><category>Geo</category><guid isPermaLink="false">{1000000 + i}'
        "</guid><pubDate>Mon, 09 Nov 2026 20:30:00 GMT</pubDate></item>"
        for i in range(count)
    )
    rss = re.sub(r"<item>.*</item>", "", rss, flags=re.S).replace(
        "</channel>", items + "</channel>"
    )
    f.answers[SACHET_RSS_URL.format(feed="kerala")] = rss.encode()
    ident = re.search(r"<cap:identifier>([^<]+)</cap:identifier>", base).group(1)  # type: ignore[union-attr]
    for i in range(count):
        cap = base.replace(ident, f"MUT-{i}")
        if mutate_onset:  # a new onset day each time: a new content key each time
            day = (date(2026, 11, 11) + timedelta(days=i)).isoformat()
            cap = cap.replace(f"<cap:onset>{ONSET}", f"<cap:onset>{day}T01:30:00+05:30")
        f.caps[str(1000000 + i)] = cap.encode()
    return f


async def _runs(at: object, fetcher: object, runs: int) -> tuple[list[str], list[tuple[str, str]]]:
    clock = Clock(at)  # type: ignore[arg-type]
    hc, notifier, docs, clock = house_ctx(clock=clock, policy=True)
    outside = OutsideStore(docs, hc.keyring, prefix=hc.prefix)
    await outside.change(UID, lambda o: o.model_copy(update={"place": Place(**PLACE)}))
    job = sachet.DisasterJob(hc, outside, HouseStore(docs, prefix=hc.prefix), fetcher)  # type: ignore[arg-type]
    actions: list[str] = []
    for _ in range(runs):
        before = len(notifier.signals)
        await job.run(())
        actions += [decide(s, NotifySettings(), clock.at).action for s in notifier.signals[before:]]
        clock.at += timedelta(minutes=5)
    return actions, [(k, t) for _, k, t, _ in notifier.calls]


async def test_the_reviewers_60_mutated_identifiers_ring_once() -> None:
    actions, sent = await _runs(TWO_AM_IST, _flood(60, mutate_onset=False), 10)
    assert actions.count("ring") == 1 and len(sent) == 1
    assert sent[0][0] == "disaster_alert" and "Landslide" in sent[0][1]


async def test_mutated_content_rings_at_most_three_then_folds_into_one_summary() -> None:
    actions, sent = await _runs(TWO_AM_IST, _flood(60, mutate_onset=True), 10)  # 02:00-02:45
    rings = [t for (k, t), a in zip(sent, actions, strict=True) if a == "ring"]
    assert len(rings) == night.MAX_NIGHT_RINGS + 1  # three warnings and one "more alerts"
    assert rings[-1] == words.night_more(PLACE["district"])
    held = [t for (k, t), a in zip(sent, actions, strict=True) if a == "hold"]
    assert held == [words.night_summary(PLACE["district"])]  # one morning summary
    assert night.MAX_NIGHT_RINGS == 3


async def test_the_more_alerts_ring_is_at_most_once_an_hour() -> None:
    actions, sent = await _runs(TWO_AM_IST, _flood(150, mutate_onset=True), 24)  # 02:00-03:55
    more = [t for (k, t) in sent if t == words.night_more(PLACE["district"])]
    assert len(more) == 2 and actions.count("ring") == night.MAX_NIGHT_RINGS + 2
    assert [t for (k, t) in sent].count(words.night_summary(PLACE["district"])) == 1


async def test_by_day_the_existing_rules_stand() -> None:
    _, sent = await _runs(NOON_IST, _flood(5, mutate_onset=True), 2)
    assert len([k for k, _ in sent if k == "disaster_alert"]) == 5  # no night cap by day
    _, same = await _runs(NOON_IST, _flood(8, mutate_onset=False), 3)
    assert len(same) == 1  # but the same warning under new identifiers is still told once


def test_the_night_and_the_content_key() -> None:
    assert night.night_of(TWO_AM_IST, "Asia/Kolkata") == "2026-11-09"  # 02:00 belongs to the 9th
    assert night.night_of(NOON_IST, "Asia/Kolkata") is None
    assert night.night_of(TWO_AM_IST + timedelta(hours=-3), "Asia/Kolkata") == "2026-11-09"  # 23:00
    k = night.content_key("disaster_alert", "Landslide", "Ernakulam", "2026-11-10")
    assert k == night.content_key("disaster_alert", "Landslide", " ernakulam ", "2026-11-10")
    assert k != night.content_key("weather_warning", "Landslide", "Ernakulam", "2026-11-10")
