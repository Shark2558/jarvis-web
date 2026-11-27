# tests/test_r18_review_privacy.py -- R18 combined review (BOOK-LIST 3.2, I1-NOTES): the Privacy
# panel had no row for calls, so a call could be seen and deleted only in Calls (or by the 30-day
# job) and never exported. Four rows now, the way other skills do it (`jarvis.calls.privacy`):
# calls (records, their sealed parts, cards, numbers called before), call settings, the call desk's
# link, and the language check's results. Each shows a count, exports safe fields (a number only
# masked, never a seed or a key) and deletes what it lists; the limits' counters stay.
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from calls_a1_fakes import NUMBER, UID, api, known, rig

from jarvis.calls.hub import DeskDoorService, DeskStore
from jarvis.calls.limits import ist_day, ist_month
from jarvis.calls.models import CallRecord, Direction, LanguageResult, SpeechOption
from jarvis.calls.privacy import (
    SECTION,
    CallDeskPrivacy,
    CallSettingsPrivacy,
    CallsPrivacy,
    LanguageCheckPrivacy,
    calls_privacy_sources,
)
from jarvis.calls.records import CallSummary, Transcript, TranscriptLine
from jarvis.keyring import Keyring

AT = datetime(2026, 11, 27, 6, 30, tzinfo=UTC)
IDS = ["calls", "call_settings", "call_desk", "call_lang_check"]


class _Hub:
    def __init__(self) -> None:
        self.dropped: list[str] = []

    async def drop_desk(self, uid: str) -> None:
        self.dropped.append(uid)


async def _call(r: Any, keeper: Any, call_id: str = "call_00000000000a") -> CallRecord:
    rec = CallRecord(
        id=call_id,
        card_id="cc_00000000000a",
        direction=Direction.OUTGOING,
        number_e164=NUMBER,
        started_at=AT,
    )
    await r.store.put_record(UID, rec)
    await keeper.save_audio(UID, call_id, b"RIFF" + bytes(64), "audio/wav")
    line = TranscriptLine(who="them", lang="en-IN", text="Pickup at ten is fine.", english="")
    await keeper.save_transcript(UID, call_id, Transcript(lines=(line,)))
    await keeper.save_summary(UID, call_id, CallSummary(english="Pickup booked for 10:00."))
    return rec


async def test_review_the_calls_row_counts_exports_and_deletes_every_call() -> None:
    r = await rig()
    await known(r.store)  # a number called before (its keyed hash) and a day's counter
    keeper = api(r).keeper
    await _call(r, keeper)
    card = await r.service.builder.build(UID, _draft())
    await r.store.put_card(UID, card)
    await r.store.add_spend(UID, ist_month(AT), 1.5)
    row = CallsPrivacy(r.store, keeper)
    view = await row.describe(UID)
    assert (view.id, view.section, view.count, view.unit) == ("calls", SECTION, 1, "calls")
    assert view.encrypted_by_jarvis and view.export and view.delete == "passkey"
    assert "30 days" in view.retention and view.rev
    out = await row.export(UID)
    text = json.dumps(out, ensure_ascii=False)
    assert NUMBER not in text and "9000000001" not in text and "…0001" in text
    [one] = out["calls"]  # type: ignore[index]
    assert one["summary"]["english"] == "Pickup booked for 10:00."
    assert one["transcript"][0]["text"] == "Pickup at ten is fine."
    assert "audio" in out and "seed" not in text and "sealed" not in text  # type: ignore[operator]
    assert await row.delete(UID) == 1
    assert (await row.describe(UID)).count == 0 and (await row.describe(UID)).delete == "none"
    assert await r.store.get_card(UID, card.id) is None
    assert not await r.store.known_number(UID, NUMBER)  # "called before" goes too
    leftover = [p for p in r.store.docs._data if "/sealed" in p or "/records/" in p]
    assert leftover == []  # every sealed part (header and chunks) and the record
    assert await r.store.month_spend(UID, ist_month(AT)) == 1.5  # the cap's counter stays


async def test_review_the_settings_row_puts_the_defaults_back() -> None:
    r = await rig()  # the rig saved his first name
    row = CallSettingsPrivacy(r.store)
    view = await row.describe(UID)
    assert (view.count, view.delete, view.export) == (1, "simple", True)
    assert "defaults" in view.note
    out = await row.export(UID)
    assert out is not None and out["settings"]["owner_first_name"] == "Sam"
    assert await row.delete(UID) == 1
    assert (await r.store.settings(UID)).owner_first_name == ""
    assert (await row.describe(UID)).count == 0
    assert await row.delete(UID) == 0


async def test_review_the_desk_row_shows_the_link_and_unlinks_it() -> None:
    r = await rig()
    ring = Keyring(bytes(range(32)))
    desks = DeskStore(r.store.docs, ring.cipher("calls"), prefix="test_")
    hub = _Hub()
    door = DeskDoorService(desks, hub)  # type: ignore[arg-type]
    row = CallDeskPrivacy(desks, door)
    assert (await row.describe(UID)).count == 0
    await desks.link(UID, "h_0000000a", bytes(32), "18.0.0")
    await door.code(UID)  # a link code he asked for and didn't use
    view = await row.describe(UID)
    assert (view.count, view.delete, view.export) == (1, "simple", True)
    out = await row.export(UID)
    assert out is not None and out["desk"]["desk_id"] == "h_0000000a"
    assert "seed" not in json.dumps(out) and "code" not in json.dumps(out)
    assert await row.delete(UID) == 1 and hub.dropped == [UID]
    assert await desks.load(UID) is None and (await row.describe(UID)).count == 0
    assert [p for p in r.store.docs._data if "call_desk" in p] == []  # the code went too


async def test_review_the_language_check_row_exports_and_deletes_the_results() -> None:
    r = await rig(languages=("en-IN", "ml-IN"))
    row = LanguageCheckPrivacy(r.store)
    view = await row.describe(UID)
    assert (view.count, view.delete, view.unit) == (2, "confirm", "results")
    assert "English" in view.note
    out = await row.export(UID)
    assert out is not None and {x["lang"] for x in out["results"]} == {"en-IN", "ml-IN"}
    assert await row.delete(UID) == 2
    assert await r.store.language_results() == []


async def test_review_the_four_rows_are_built_in_order() -> None:
    r = await rig()
    ring = Keyring(bytes(range(32)))
    desks = DeskStore(r.store.docs, ring.cipher("calls"), prefix="test_")
    rows = calls_privacy_sources(
        r.store,
        api(r).keeper,
        desks,
        DeskDoorService(desks, _Hub()),  # type: ignore[arg-type]
    )
    assert [x.id for x in rows] == IDS and {x.section for x in rows} == {SECTION}


def _draft() -> Any:
    from jarvis.calls.tools import PlaceArgs

    return PlaceArgs(number=NUMBER, purpose="Book a pickup", languages=("en-IN",))


def test_review_the_day_helpers_are_ist() -> None:
    assert ist_day(AT).isoformat() == "2026-11-27"


async def test_review_a_wired_app_lists_the_calls_rows(settings: Any) -> None:
    import base64

    from pydantic import SecretStr

    from jarvis.api import create_app
    from jarvis.api.identity import primary_user_id
    from jarvis.llm.mock_provider import MockProvider
    from jarvis.memory.inmemory import InMemorySessionStore

    key = SecretStr(base64.b64encode(bytes(range(1, 33))).decode())
    s = settings.model_copy(update={"token_key": key, "tools_enabled": True})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        ids = app.state.privacy.registry.ids()
        assert [i for i in ids if i in IDS] == IDS
        views = await app.state.privacy.registry.describe_all(primary_user_id(s))
        shown = {v.id: v for v in views}
        assert all(shown[i].available for i in IDS)


__all__ = ["LanguageResult", "SpeechOption"]
