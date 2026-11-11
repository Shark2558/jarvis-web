# tests/test_r11_b_feed.py -- R11 Part B, SACHET's feed bookkeeping after the reviews
# (docs/plans/r11-free-helpers.md D13). Security M2: an ETag is kept only when it is printable
# ASCII of at most 200 characters; a request JARVIS can't build (an odd ETag kept from before)
# clears the ETag, is not an outage and is retried without it; code L1: a 304 without an ETag
# keeps the old one. Code H2: a CAP that answers non-200 is skipped with a backoff, the next item
# is tried, and the guid ages out after a bounded number of failures or a day; code M5: a failing
# CAP endpoint is an outage, shown in the tab and the brief, and cleared by the next CAP read.
from __future__ import annotations

from datetime import timedelta

import httpx
from r11_fakes import NOON_IST, UID, Clock
from r11_fakes_b import CAP_FILES, PLACE, fixture, house_ctx, sachet_fetcher

from jarvis.helpers.house import feed, sachet
from jarvis.helpers.house.brief import OutsideBrief
from jarvis.helpers.house.fetch import HttpFetcher
from jarvis.helpers.house.models import Place
from jarvis.helpers.house.service import HouseService
from jarvis.helpers.house.store import HouseStore, OutsideStore
from jarvis.helpers.sources import SACHET_RSS_URL

KERALA = SACHET_RSS_URL.format(feed="kerala")
POISON = "1794300000000101"  # the Met Severe CAP: its URL answers 404 in these tests


async def _setup(fetcher: object, **over: object) -> tuple[object, ...]:
    hc, notifier, docs, clock = house_ctx(**over)  # type: ignore[arg-type]
    outside = OutsideStore(docs, hc.keyring, prefix=hc.prefix)
    await outside.change(UID, lambda o: o.model_copy(update={"place": Place(**PLACE)}))
    store = HouseStore(docs, prefix=hc.prefix)
    job = sachet.DisasterJob(hc, outside, store, fetcher)  # type: ignore[arg-type]
    return hc, notifier, clock, outside, job, store


def _sachet_site(etag: bytes, seen: list[httpx.Request]) -> HttpFetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith(".xml"):
            return httpx.Response(200, content=fixture("b_sachet_rss.xml"), headers={"ETag": etag})
        name = CAP_FILES[request.url.params["identifier"]]
        return httpx.Response(200, content=fixture(name))

    return HttpFetcher(httpx.MockTransport(handler))


def test_an_etag_is_kept_only_when_printable_ascii_and_short() -> None:
    assert feed.safe_etag('"v1"') == '"v1"' and feed.safe_etag('W/"a-1"') == 'W/"a-1"'
    assert feed.safe_etag('"' + "a" * 198 + '"') is not None  # 200 characters
    for bad in ('W/"caf\xe9"', '"' + "a" * 199 + '"', "a\x01b", "a\nb", "", None):
        assert feed.safe_etag(bad) is None


async def test_a_non_ascii_etag_never_blocks_the_feed() -> None:
    seen: list[httpx.Request] = []
    _, notifier, clock, outside, job, _ = await _setup(_sachet_site(b'W/"caf\xe9"', seen))
    await job.run(())  # type: ignore[attr-defined]
    state = (await outside.read(UID)).sachet  # type: ignore[attr-defined]
    assert state.etag is None and len(notifier.calls) == 4  # type: ignore[attr-defined]
    clock.at += timedelta(minutes=10)  # type: ignore[attr-defined]
    got = await job.run(())  # type: ignore[attr-defined]
    feeds = [r for r in seen if r.url.path.endswith(".xml")]
    assert len(feeds) == 2 and "if-none-match" not in feeds[1].headers
    assert got["unreachable"] == 0 and (await outside.read(UID)).sachet.fail_since is None  # type: ignore[attr-defined]


async def test_a_request_that_cant_be_built_clears_the_etag_and_is_not_an_outage() -> None:
    seen: list[httpx.Request] = []
    _, notifier, clock, outside, job, _ = await _setup(_sachet_site(b'"v2"', seen))
    odd = 'W/"caf\xe9"'  # an ETag kept before this fix
    await outside.change(  # type: ignore[attr-defined]
        UID,
        lambda o: o.model_copy(
            update={"sachet": o.sachet.model_copy(update={"etag": odd, "feed": "kerala"})}
        ),
    )
    got = await job.run(())  # type: ignore[attr-defined]
    state = (await outside.read(UID)).sachet  # type: ignore[attr-defined]
    assert (got["local_error"], got["unreachable"]) == (1, 0) and seen == []
    assert state.etag is None and state.fail_since is None and state.feed == "kerala"
    clock.at += timedelta(minutes=5)  # type: ignore[attr-defined]
    await job.run(())  # type: ignore[attr-defined]  # the next run reads it without the ETag
    assert [r.url.path.endswith(".xml") for r in seen][:1] == [True]
    assert "if-none-match" not in seen[0].headers and len(notifier.calls) == 4  # type: ignore[attr-defined]
    assert (await outside.read(UID)).sachet.etag == '"v2"'  # type: ignore[attr-defined]


async def test_a_304_without_an_etag_keeps_the_old_one() -> None:
    fetcher = sachet_fetcher()
    _, _, clock, outside, job, _ = await _setup(fetcher)
    await job.run(())  # type: ignore[attr-defined]
    fetcher.not_modified, fetcher.bare_304 = True, True
    clock.at += timedelta(minutes=10)  # type: ignore[attr-defined]
    await job.run(())  # type: ignore[attr-defined]
    assert fetcher.calls[-1][2] == {"If-None-Match": '"v1"'}
    assert (await outside.read(UID)).sachet.etag == '"v1"'  # type: ignore[attr-defined]


# ---- code review H2 and M5 --------------------------------------------------------------------
async def test_a_cap_answering_404_is_skipped_and_the_queue_goes_on() -> None:
    fetcher = sachet_fetcher()
    del fetcher.caps[POISON]  # its URL now answers 404 (the reviewer's poison CAP)
    _, notifier, clock, outside, job, _ = await _setup(fetcher)
    got = await job.run(())  # type: ignore[attr-defined]
    assert got["sent"] == 3 and got["cap_refused"] == 1  # the items behind it were read
    state = (await outside.read(UID)).sachet  # type: ignore[attr-defined]
    assert state.queue == (POISON,) and state.backoff[0].fails == 1
    tries = []
    for _ in range(4):  # 5, 10, 15 and 20 minutes later: its backoff doubles (5, then 10)
        clock.at += timedelta(minutes=5)  # type: ignore[attr-defined]
        await job.run(())  # type: ignore[attr-defined]
        tries.append(sum(1 for _, p, _ in fetcher.calls if p.get("identifier") == POISON))
    assert tries == [2, 2, 3, 3]


async def test_a_failing_guid_ages_out_after_a_bounded_number_of_failures() -> None:
    fetcher = sachet_fetcher()
    del fetcher.caps[POISON]
    _, _, clock, outside, job, _ = await _setup(fetcher)
    aged = 0
    for _ in range(40):  # 40 runs, 5 minutes apart (3 h 20 min)
        aged += (await job.run(()))["aged"]  # type: ignore[attr-defined]
        clock.at += timedelta(minutes=5)  # type: ignore[attr-defined]
    state = (await outside.read(UID)).sachet  # type: ignore[attr-defined]
    tries = sum(1 for _, p, _ in fetcher.calls if p.get("identifier") == POISON)
    assert aged == 1 and tries == feed.MAX_CAP_FAILS and POISON in state.seen
    assert state.queue == () and state.backoff == ()


async def test_a_guid_failing_for_a_day_ages_out_however_few_its_failures() -> None:
    fetcher = sachet_fetcher()
    _, _, clock, outside, job, _ = await _setup(fetcher)
    since = (NOON_IST - timedelta(hours=25)).isoformat()
    old = feed.Backoff(guid=POISON, since=since, fails=1, next_at=since)
    await outside.change(  # type: ignore[attr-defined]
        UID,
        lambda o: o.model_copy(
            update={
                "sachet": o.sachet.model_copy(
                    update={"queue": (POISON,), "backoff": (old,), "feed": "kerala"}
                )
            }
        ),
    )
    fetcher.answers[KERALA] = fixture("b_sachet_rss.xml").replace(POISON.encode(), b"1794300009")
    got = await job.run(())  # type: ignore[attr-defined]
    assert got["aged"] == 1 and POISON in (await outside.read(UID)).sachet.seen  # type: ignore[attr-defined]


async def test_a_host_that_doesnt_answer_stops_the_run_and_is_an_outage_until_a_cap_reads() -> None:
    fetcher = sachet_fetcher()
    hc, _, clock, outside, job, store = await _setup(fetcher)
    real = fetcher.get
    down = {"on": True}

    async def flaky(url: str, **kw: object) -> object:
        if down["on"] and "identifier" in (kw.get("params") or {}):  # type: ignore[operator]
            from jarvis.helpers.house.fetch import FetchError

            raise FetchError("took too long")  # no status: the host, not this CAP
        return await real(url, **kw)  # type: ignore[arg-type]

    fetcher.get = flaky  # type: ignore[method-assign]
    got = await job.run(())  # type: ignore[attr-defined]
    state = (await outside.read(UID)).sachet  # type: ignore[attr-defined]
    assert got["unreachable"] == 1 and len(state.queue) == 5 and state.backoff == ()
    assert state.cap_fail_since == NOON_IST.isoformat() and state.fail_since is None
    svc = HouseService(hc, store, outside)  # type: ignore[arg-type]
    view = await svc.view(UID)
    assert view["outside"]["sachet"]["cap_fail_since"] == NOON_IST.isoformat()
    from jarvis.helpers.house.tools import HouseTools
    from jarvis.tools.context import tool_context

    with tool_context(f"{UID}:s1"):
        tool_view = await HouseTools(svc).disaster_status({})
    assert tool_view["unavailable_since"] == NOON_IST.isoformat()
    lines = await OutsideBrief(svc).lines(UID, Clock().at.tzinfo, NOON_IST.date())  # type: ignore[arg-type]
    assert any("Can't reach SACHET since" in line for line in lines)
    down["on"] = False
    clock.at += timedelta(minutes=5)  # type: ignore[attr-defined]
    await job.run(())  # type: ignore[attr-defined]
    assert (await outside.read(UID)).sachet.cap_fail_since is None  # type: ignore[attr-defined]


# ---- security L4 and code L2 --------------------------------------------------------------------
async def test_a_warning_without_expires_lapses_after_a_day() -> None:
    import re

    fetcher = sachet_fetcher()
    raw = fixture("b_cap_geo_landslide.xml").decode()
    fetcher.caps["1794300000000102"] = re.sub(
        r"\s*<cap:expires>[^<]*</cap:expires>", "", raw
    ).encode()
    hc, _, clock, outside, job, store = await _setup(fetcher)
    await job.run(())  # type: ignore[attr-defined]
    kept = (await outside.read(UID)).sachet.warnings  # type: ignore[attr-defined]
    assert any(w.event == "Landslide" and w.until is None for w in kept)
    brief = OutsideBrief(HouseService(hc, store, outside))  # type: ignore[arg-type]
    day = NOON_IST.date()
    assert any("Landslide" in x for x in await brief.lines(UID, NOON_IST.tzinfo, day))  # type: ignore[arg-type]
    clock.at += feed.NO_EXPIRY + timedelta(minutes=5)  # type: ignore[attr-defined]
    later = clock.at.date()  # type: ignore[attr-defined]
    assert not any("Landslide" in x for x in await brief.lines(UID, NOON_IST.tzinfo, later))  # type: ignore[arg-type]
    await job.run(())  # type: ignore[attr-defined]
    kept = (await outside.read(UID)).sachet.warnings  # type: ignore[attr-defined]
    assert not any(w.event == "Landslide" for w in kept)
    assert feed.NO_EXPIRY == timedelta(hours=24)


async def test_a_cancel_without_an_info_block_still_lifts_the_warning() -> None:
    import re

    fetcher = sachet_fetcher()
    _, notifier, clock, outside, job, _ = await _setup(fetcher)
    await job.run(())  # type: ignore[attr-defined]
    bare = re.sub(r"<cap:info>.*?</cap:info>", "", fixture("b_cap_cancel.xml").decode(), flags=re.S)
    fetcher.answers[KERALA] = fixture("b_sachet_rss.xml").replace(
        POISON.encode(), b"1794300000000106"
    )
    fetcher.caps["1794300000000106"] = bare.encode()
    clock.at += timedelta(minutes=10)  # type: ignore[attr-defined]
    await job.run(())  # type: ignore[attr-defined]
    assert notifier.calls[-1][2] == "Landslide warning for Ernakulam lifted (SACHET)."  # type: ignore[attr-defined]
    kept = (await outside.read(UID)).sachet.warnings  # type: ignore[attr-defined]
    assert not any(w.event == "Landslide" for w in kept)
