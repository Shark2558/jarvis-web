# tests/test_r11_b_sachet.py -- R11 Part B item 5 (docs/plans/r11-free-helpers.md D13): the SACHET
# job on fixtures. At 02:00 a non-Met CAP for his district rings as `disaster_alert`, a Met
# "Severe" one is held, another district is ignored; an instruction planted in a CAP headline
# never reaches an alert; each CAP identifier is told once (a restart, the same CAP again); a
# Cancel says "lifted"; a DOCTYPE or a 300 KB CAP is refused and never fetched again; the feed is
# read only when due, with If-None-Match, never through an item's own link; an outage is kept.
from __future__ import annotations

from datetime import timedelta

from r11_fakes import NOON_IST, TWO_AM_IST, UID, Clock
from r11_fakes_b import PLACE, Rules, fixture, house_ctx, sachet_fetcher

from jarvis.helpers.house import cap, sachet
from jarvis.helpers.house.models import Place
from jarvis.helpers.house.store import HouseStore, OutsideStore
from jarvis.helpers.sources import SACHET_CAP_URL, SACHET_RSS_URL

KERALA = SACHET_RSS_URL.format(feed="kerala")


async def _setup(**over: object) -> tuple[object, ...]:
    fetcher = over.pop("fetcher", None) or sachet_fetcher()
    hc, notifier, docs, clock = house_ctx(**over)  # type: ignore[arg-type]
    outside = OutsideStore(docs, hc.keyring, prefix=hc.prefix)
    if hc.keyring is not None:
        await outside.change(UID, lambda o: o.model_copy(update={"place": Place(**PLACE)}))
    store = HouseStore(docs, prefix=hc.prefix)
    job = sachet.DisasterJob(hc, outside, store, fetcher)
    return hc, notifier, docs, clock, outside, fetcher, job, store


def _texts(notifier: object) -> list[tuple[str, str]]:
    return [(k, t) for _, k, t, _ in notifier.calls]  # type: ignore[attr-defined]


async def test_at_02_00_a_disaster_rings_met_severe_is_held_another_district_is_ignored() -> None:
    clock = Clock(TWO_AM_IST)
    _, notifier, _, _, _, fetcher, job, _ = await _setup(clock=clock, policy=True)
    got = await job.run(())
    # the advisory (info) is dropped at night by the policy: feed only, never a night message
    assert (got["sent"], got["dropped"], got["failed"]) == (3, 1, 0)
    end = "for Ernakulam until 18:00 (SACHET)"
    assert _texts(notifier) == [
        ("weather_warning", f"Thunderstorm warning {end}. Open JARVIS."),
        ("disaster_alert", f"Urgent: Landslide warning {end}. Open JARVIS."),
        ("weather_note", f"Weather advisory {end}."),
        ("disaster_alert", f"Urgent: Heavy rain warning {end}. Open JARVIS."),
    ]
    from jarvis.notify.models import NotifySettings
    from jarvis.notify.policy import decide

    actions = [decide(s, NotifySettings(), TWO_AM_IST).action for s in notifier.signals]
    assert actions == ["hold", "ring", "drop", "ring"]
    assert "Kollam" not in str(notifier.calls)
    # the item's own link was never used: every CAP URL is SACHET's fixed one plus the guid
    assert set(fetcher.urls()) == {KERALA, SACHET_CAP_URL}


async def test_a_planted_instruction_never_reaches_an_alert() -> None:
    _, notifier, docs, _, outside, _, job, _ = await _setup()
    await job.run(())
    sent = str(notifier.calls) + str([s.model_dump() for s in notifier.signals])
    assert "NEEDLE" not in sent and "attacker" not in sent and "UPI" not in sent
    assert "NEEDLE" not in str(docs._data)  # noqa: SLF001 - kept only sealed
    kept = (await outside.read(UID)).sachet.warnings
    assert any("NEEDLE-CAP" in w.headline for w in kept)  # for the panel, fenced there


async def test_each_cap_is_told_once_across_a_restart_and_a_second_poll() -> None:
    hc, notifier, docs, clock, outside, fetcher, job, _ = await _setup()
    await job.run(())
    assert len(notifier.calls) == 4
    clock.at += timedelta(minutes=10)
    await job.run(())  # due again: nothing new
    await outside.change(  # forget every item seen: the claims still hold
        UID, lambda o: o.model_copy(update={"sachet": o.sachet.model_copy(update={"seen": ()})})
    )
    clock.at += timedelta(minutes=10)
    again = sachet.DisasterJob(hc, outside, HouseStore(docs, prefix=hc.prefix), fetcher)
    await again.run(())
    assert len(notifier.calls) == 4


async def test_the_district_filter_off_rings_another_districts_alert() -> None:
    _, notifier, _, _, _, _, job, _ = await _setup()
    cap.DISTRICT_FILTER = False
    try:
        await job.run(())
    finally:
        cap.DISTRICT_FILTER = True
    assert any("Landslide" in t and k == "disaster_alert" for k, t in _texts(notifier)[1:])
    assert len(notifier.calls) == 5


async def test_a_cancel_says_lifted_and_drops_the_warning() -> None:
    _, notifier, _, clock, outside, fetcher, job, _ = await _setup()
    await job.run(())
    fetcher.answers[KERALA] = fixture("b_sachet_rss.xml").replace(
        b"1794300000000101", b"1794300000000106"
    )
    fetcher.caps["1794300000000106"] = fixture("b_cap_cancel.xml")
    clock.at += timedelta(minutes=10)
    await job.run(())
    assert _texts(notifier)[-1] == (
        "weather_note",
        "Landslide warning for Ernakulam lifted (SACHET).",
    )
    kept = (await outside.read(UID)).sachet.warnings
    assert not any(w.event == "Landslide" for w in kept)


async def test_unsafe_or_oversized_caps_are_refused_and_never_fetched_again() -> None:
    fetcher = sachet_fetcher()
    fetcher.caps["1794300000000102"] = fixture("b_cap_doctype.xml")
    fetcher.caps["1794300000000105"] = b"<a>" + b"x" * (300 * 1024) + b"</a>"
    _, notifier, _, clock, _, _, job, _ = await _setup(fetcher=fetcher)
    got = await job.run(())
    assert got["refused"] == 2 and len(notifier.calls) == 2
    caps_before = sum(1 for u in fetcher.urls() if u == SACHET_CAP_URL)
    clock.at += timedelta(minutes=10)
    await job.run(())
    assert sum(1 for u in fetcher.urls() if u == SACHET_CAP_URL) == caps_before


async def test_the_feed_is_read_when_due_with_its_etag() -> None:
    _, _, _, clock, _, fetcher, job, _ = await _setup()
    await job.run(())
    feeds = [c for c in fetcher.calls if c[0] == KERALA]
    assert len(feeds) == 1 and feeds[0][2] == {}
    clock.at += timedelta(minutes=5)
    await job.run(())
    assert len([c for c in fetcher.calls if c[0] == KERALA]) == 1  # not due yet
    fetcher.not_modified = True
    clock.at += timedelta(minutes=5)
    await job.run(())
    feeds = [c for c in fetcher.calls if c[0] == KERALA]
    assert len(feeds) == 2 and feeds[1][2] == {"If-None-Match": '"v1"'}


async def test_an_outage_is_kept_and_cleared() -> None:
    fetcher = sachet_fetcher(fail=True)
    _, notifier, _, clock, outside, _, job, _ = await _setup(fetcher=fetcher)
    got = await job.run(())
    assert got["unreachable"] == 1 and got["failed"] == 0 and notifier.calls == []
    assert (await outside.read(UID)).sachet.fail_since == NOON_IST.isoformat()
    fetcher.fail = False
    clock.at += timedelta(minutes=5)
    await job.run(())
    state = (await outside.read(UID)).sachet
    assert state.fail_since is None and state.ok_at is not None


async def test_a_send_no_channel_took_keeps_the_item_for_the_next_run() -> None:
    from jarvis.notify.ports import Delivery

    _, notifier, _, clock, outside, _, job, _ = await _setup()
    notifier.delivery = Delivery(action="ring", reason="test")
    got = await job.run(())
    assert got["retry"] == 4 and len((await outside.read(UID)).sachet.queue) == 4
    notifier.delivery = Delivery(action="ring", reason="test", telegram=True)
    clock.at += timedelta(minutes=5)
    assert (await job.run(()))["sent"] == 4


async def test_old_items_are_seen_without_fetching_and_another_state_reads_the_national_feed() -> (
    None
):
    _, _, _, _, outside, fetcher, job, _ = await _setup(clock=Clock(NOON_IST + timedelta(days=3)))
    await job.run(())
    assert fetcher.urls() == [KERALA]
    assert len((await outside.read(UID)).sachet.seen) == 5
    far = Place(district="Khordha", state="Odisha")
    assert far.feed() == "india"


async def test_off_without_a_place_a_keyring_or_his_row() -> None:
    _, _, _, _, outside, fetcher, job, _ = await _setup()
    await outside.change(UID, lambda o: o.model_copy(update={"place": None}))
    assert (await job.run(()))["no_place"] == 1 and fetcher.calls == []
    _, _, _, _, _, fetcher2, job2, _ = await _setup(keyring_on=False)
    assert (await job2.run(()))["off"] == 1 and fetcher2.calls == []
    _, _, _, _, _, fetcher3, job3, _ = await _setup(rules=Rules(("disaster_*",)))
    assert (await job3.run(()))["skipped"] == 1 and fetcher3.calls == []


async def test_the_job_stops_fetching_at_its_soft_deadline() -> None:
    ticks = iter([0.0, 0.0, 1.0, 2.0, 8.5, 9.0])
    _, notifier, _, _, outside, fetcher, _, store = await _setup()
    hc = house_ctx()[0]
    slow = sachet.DisasterJob(hc, outside, store, fetcher, clock=lambda: next(ticks, 99.0))
    await slow._owner(UID, sachet.Counts())  # noqa: SLF001
    assert sum(1 for u in fetcher.urls() if u == SACHET_CAP_URL) == 2
    assert (await outside.read(UID)).sachet.queue  # the rest waits for the next run


def _variant(name: str, ident: str, *, msg: str = "Alert", refs: str = "", **swap: str) -> bytes:
    raw = fixture(name).decode()
    old = raw.split("<cap:identifier>")[1].split("</cap:identifier>")[0]
    raw = raw.replace(old, ident).replace(
        "<cap:msgType>Alert</cap:msgType>", f"<cap:msgType>{msg}</cap:msgType>"
    )
    if refs:
        raw = raw.replace(
            "<cap:scope>Public</cap:scope>",
            "<cap:scope>Public</cap:scope>\n  "
            f"<cap:references>Example-SDMA,{refs},x</cap:references>",
        )
    for a, b in swap.items():
        raw = raw.replace(
            f"<cap:{a.split('_')[0]}>{a.split('_')[1]}<", f"<cap:{a.split('_')[0]}>{b}<"
        )
    return raw.encode()


async def _second_round(
    fetcher: object, clock: object, job: object, *caps: tuple[str, bytes]
) -> None:
    feed = fixture("b_sachet_rss.xml")
    for i, (gid, body) in enumerate(caps):
        feed = feed.replace(f"179430000000010{i + 1}".encode(), gid.encode())
        fetcher.caps[gid] = body  # type: ignore[attr-defined]
    fetcher.answers[KERALA] = feed  # type: ignore[attr-defined]
    clock.at += timedelta(minutes=10)  # type: ignore[attr-defined]
    await job.run(())  # type: ignore[attr-defined]


async def test_an_update_rings_again_only_when_it_got_worse() -> None:
    _, notifier, _, clock, outside, fetcher, job, _ = await _setup()
    await job.run(())
    before = len(notifier.calls)
    same = _variant("b_cap_geo_landslide.xml", "IN-1794300000000201_1", msg="Update",
                    refs="IN-1794300000000102_1")  # fmt: skip
    worse = _variant("b_cap_met_severe.xml", "IN-1794300000000202_1", msg="Update",
                     refs="IN-1794300000000101_1", severity_Severe="Extreme")  # fmt: skip
    await _second_round(
        fetcher, clock, job, ("1794300000000201", same), ("1794300000000202", worse)
    )
    new = _texts(notifier)[before:]
    assert new == [
        (
            "disaster_alert",
            "Urgent: Thunderstorm warning for Ernakulam until 18:00 (SACHET). Open JARVIS.",
        )
    ]
    kept = (await outside.read(UID)).sachet.warnings
    assert {w.ident for w in kept} >= {"IN-1794300000000201_1", "IN-1794300000000202_1"}


async def test_a_series_of_nowcasts_within_three_hours_is_told_once() -> None:
    _, notifier, _, clock, _, fetcher, job, _ = await _setup()
    await job.run(())
    before = len(notifier.calls)
    again = _variant("b_cap_met_severe.xml", "IN-1794300000000301_1")
    await _second_round(fetcher, clock, job, ("1794300000000301", again))
    assert len(notifier.calls) == before
    clock.at += timedelta(hours=3)
    later = _variant("b_cap_met_severe.xml", "IN-1794300000000302_1")
    await _second_round(fetcher, clock, job, ("1794300000000302", later))
    assert len(notifier.calls) == before + 1


async def test_test_or_private_messages_and_expired_ones_are_not_told() -> None:
    fetcher = sachet_fetcher()
    fetcher.caps["1794300000000101"] = _variant(
        "b_cap_met_severe.xml", "IN-1794300000000101_1"
    ).replace(b"<cap:status>Actual</cap:status>", b"<cap:status>Test</cap:status>")
    fetcher.caps["1794300000000102"] = _variant(
        "b_cap_geo_landslide.xml", "IN-1794300000000102_1"
    ).replace(b"2026-11-10T18:00:00+05:30", b"2026-11-10T10:00:00+05:30")
    _, notifier, _, _, _, _, job, _ = await _setup(fetcher=fetcher)
    got = await job.run(())
    assert got["ignored"] == 1 and got["expired"] == 1
    assert not any("Thunderstorm" in t or "Landslide" in t for _, t in _texts(notifier))
