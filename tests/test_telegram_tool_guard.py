# tests/test_telegram_tool_guard.py -- review slice 1 M1 / slice 3 #6: every READ tool the real,
# fully linked gateway registers is classified for Telegram. Either the private-reads patterns
# cover it (denied on Telegram unless the owner allows private reads), or it is named below as
# safe to answer on Telegram. A new tool therefore fails this test until someone decides.
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from drive_fakes import FakeDrive, StaticTokens
from media_fakes import KEY, FakeGoogleKeyAPIs
from memory_fakes import rig as memory_rig
from people_fakes import FakePeople, people_connector
from photos_fakes import rig as photos_rig
from pydantic import SecretStr
from r3_fakes import R3_READS, R3_SAFE, home_parts
from research_fakes import FakeModel, FakeSearcher, fixed_mode
from telegram_fakes import UID, Clock
from vitals_fakes import Rig as VitalsRig
from web_fakes import FakeTavily

from jarvis.api.r4_wiring import R4Parts
from jarvis.belongings.service import BelongingsService
from jarvis.belongings.store import BelongingsStore
from jarvis.config import get_settings
from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ActionRisk
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.drive.client import DriveClient
from jarvis.drive.roots import RootsStore
from jarvis.drive.service import DriveService
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.integrations.github import GithubClient, GithubStore
from jarvis.integrations.google_key import GoogleKeyClient
from jarvis.integrations.youtube import YouTubeOwn
from jarvis.kb.service import NotesService
from jarvis.kb.store import NotesStore
from jarvis.keyring import Keyring
from jarvis.llm.base import ToolCall
from jarvis.media.service import MediaServices, YouTubeService
from jarvis.people.research import PeopleService
from jarvis.photos.tools import ConnectorDeps
from jarvis.places.service import MapsService
from jarvis.places.store import MapsPlaces
from jarvis.quota.ledger import QuotaLedger
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.rules import HOME_PATTERNS, PRIVATE_PATTERNS, ChannelRules, wrap_rules
from jarvis.telegram.store import TelegramStore
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect
from jarvis.tools.setup import build_gateway
from jarvis.undo.service import UndoBin
from jarvis.undo.store import DeletedStore
from jarvis.vault.crypto import VaultCrypto
from jarvis.vault.service import VaultService
from jarvis.vault.store import VaultStore
from jarvis.web.allowance import WebAllowance
from jarvis.web.service import WebService
from jarvis.web.tavily import TavilyProvider

R1 = ActionRisk.READ_ONLY

# Reads that are safe to answer on Telegram: the owner's own lists and facts, public look-ups, or
# an answer shaped to carry no titles / locations / subjects.
TELEGRAM_SAFE = frozenset(
    {
        "calendar_free_slots",  # times only
        "calendar_list_events",  # the owner's own calendar
        "family_free_slots",  # member names and times only: no titles, no locations
        "gmail_track_packages",  # shaped: status only unless private reads are on
        "grocery_list",  # the owner's own list
        "list_tasks",
        "tasks_list",
        "reminders_list",
        "memory_search",  # the owner's own memory
        "whatsapp_draft",  # a draft of the owner's own words
        "maps_search",
        "maps_route",
        "youtube_search",
        "youtube_my_playlists",
        "youtube_playlist",
        "web_read",  # public pages
        "web_search",
        # R3 D15: armed or not and whether the laptop is online (what the alerts already say);
        # home_disarm only answers "use the Home panel with your passkey" (it never disarms)
        *R3_SAFE,
        # R11 I1: the helpers' reads that are his own lists and public warnings. Amounts stay
        # off Telegram: bill_list and spend_month are private, and focus_now / pending_list
        # drop a bill's amount on a Telegram turn; the nudges keep the water / stand-up counts
        # out of a Telegram reply (Part C); a to-do's title never reaches `message`.
        "focus_now",
        "pending_list",
        "chore_list",
        "maint_list",
        "maint_starters",
        "weather_now",
        "disaster_status",  # SACHET's public warnings for his district (fenced as outside text)
        "nudge_status",
        # R7 D19 (Part D): the brain's one SOS tool: counts and times only, never a name or a
        # number, and how he sends an SOS himself (it can never send one)
        "sos_status",
        "freetime_list",
        "freetime_suggest",
        "pantry_list",
        "recipe_list",
        "recipe_suggest",
        "nutrition_of",
        # R11.1 I1: his followed plans: counts, numbers, times and his own typed plan name only
        # (never a title). Not `series_*` as a pattern: that would also refuse the R2 check-in
        # answer ("session done") on Telegram, where the check-in alert can arrive.
        "series_list",
        # R4, listed since R11.1 I1 built the R4 families into this registry too (they were
        # always answered on Telegram; nothing changes): his own system's health and keys, his
        # own GitHub and YouTube, and public-figure research behind its unchanged gate
        "vitals_show",
        "systems_check",
        "connect_github",
        "github_profile",
        "github_repos",
        "github_activity",
        "connect_youtube",
        "youtube_own_channel",
        "research_person",
        "people_open_profiles",
    }
)
# R11 I1: the helpers' reads that stay off Telegram (telegram.rules.PRIVATE_PATTERNS): amounts and
# UPI IDs, grocery spend, breach notices about his accounts, and his contacts' birthdays
R11_PRIVATE = ("bill_list", "spend_month", "breach_status", "contacts_birthdays")
# R11.1 I1 (GATE INTEGRATION-A 3.12): the observation parts' reads of private data: A the whole
# inbox (senders, subjects, first lines); D a picture he attached (what it shows, its text)
R111_PRIVATE = ("gmail_inbox_summary", "picture_research")
# The home switch's tools are NOT a hand list any more (I1 security review H2: the hand list named
# `photos_import_status` while the real `photos_import` stayed open). They are read off the built
# registry below: every tool, of any risk, whose name says face, home, photo or camera.
HOME_WORDS = ("face", "home", "photo", "camera")
# The only home tools Telegram keeps without the home switch, each decided in R3 D8 / D15: armed or
# not and the laptop online (what the alerts already say), arming, an Everyday device, and the
# disarm answer that only points to the console (it never disarms). Every R3 call waits there.
HOME_KEPT_ON_TELEGRAM = frozenset({"home_status", "home_arm", "home_control", "home_disarm"})


class DriveTokens(StaticTokens):
    async def email(self) -> str:
        return "jarvis-run@proj-123.iam.gserviceaccount.com"


async def linked_gateway(undo: UndoBin | None = None) -> Gateway:
    google = await people_connector(FakePeople())
    docs = MemoryDocs()
    files = DocumentService(AttachmentStore(MemoryDocs()))
    drive = DriveService(
        DriveClient(DriveTokens(), http=FakeDrive().client()),
        RootsStore(MemoryDocs()),
        extract=files.extract,
    )
    client = GoogleKeyClient(SecretStr(KEY), http=FakeGoogleKeyAPIs().client())
    ledger = QuotaLedger(docs)
    media = MediaServices(
        client=client,
        ledger=ledger,
        maps=MapsService(client, ledger, MapsPlaces(docs)),
        youtube=YouTubeService(client, ledger, google=google),
    )
    web = WebService(
        TavilyProvider(SecretStr("tvly-k"), http=FakeTavily().client()),
        WebAllowance(MemoryDocs(), now=lambda: datetime(2026, 11, 15, tzinfo=UTC)),
    )
    ring = Keyring(bytes(range(1, 33)))
    undo = undo if undo is not None else UndoBin(DeletedStore(MemoryDocs()))
    crypto = VaultCrypto(ring)
    return build_gateway(
        get_settings(),
        google=google,
        memory=memory_rig().svc,
        web=web,
        documents=files,
        undo=undo,
        drive=drive,
        media=media,
        docs=docs,
        # R2 I1: the vault list, notes and things (the second private group, D12)
        vault=VaultService(VaultStore(docs, crypto), crypto, undo=undo),
        notes=NotesService(NotesStore(docs, ring), web=web, undo=undo),
        belongings=BelongingsService(BelongingsStore(docs, ring), undo),
        home=home_parts(docs, ring),  # R3 I1: home, camera and faces tools (the third group)
        r4=r4_parts(google, docs, ring),  # R4: vitals, systems check, connectors (Photos), people
        r11=r11_parts(google, ring),  # R11 I1: every helper part's tools
        r111=r111_tools(google, docs),  # R11.1 I1: every observation part's tools
        r7=r7_tools(google, docs),  # R7 I0 seam 21: every mobile part's tools, as the app builds
    )


def r4_parts(google: Any, docs: Any, ring: Keyring) -> R4Parts:
    """Every R4 family on, as the app wires it with the Google link, Faces and the home kit: so
    `photos_import` (the import that answers faces found and the people recognised) is listed."""
    github = GithubClient(GithubStore(docs, ring), http=httpx.AsyncClient())
    return R4Parts(
        settings=get_settings(),
        vitals=VitalsRig().svc,
        health=HealthService([], HealthStore(MemoryDocs(), prefix="jarvis_")),
        connectors=ConnectorDeps(
            github=github, youtube=YouTubeOwn(google, QuotaLedger(docs)), photos=photos_rig().svc
        ),
        people=PeopleService(FakeSearcher([]), FakeModel(), mode=fixed_mode("ai")),
    )


def r7_tools(google: Any, docs: Any) -> tuple[Any, ...]:
    """The four R7 server parts built through the real wiring on fakes (none has a tool at I0;
    Part B's `vision_*` and Part D's `watch_*` / `sleep_*` / `sos_status` arrive here)."""
    from jarvis.api.r7_wiring import build_parts, mobile_tools
    from jarvis.mobile.ports import MobileContext
    from jarvis.tools.audit import AuditLog

    state = {"google": google}
    ctx = MobileContext(
        s=get_settings(), docs=docs, audit=AuditLog(), state=state.get, notifier=lambda: None
    )
    return mobile_tools(build_parts(ctx))


def r111_tools(google: Any, docs: Any) -> tuple[Any, ...]:
    """The four R11.1 parts built on fakes, as the app builds them, so each of their reads must
    pick a side here too (security review A HIGH-1: gmail_inbox_summary was not covered)."""
    from jarvis.api.r11_1_wiring import build_parts, fix_tools
    from jarvis.fixes.ports import FixContext
    from jarvis.tools.audit import AuditLog

    state = {"google": google}
    ctx = FixContext(
        s=get_settings(), docs=docs, audit=AuditLog(), state=state.get, notifier=lambda: None
    )
    return fix_tools(build_parts(ctx))


def r11_parts(google: Any, ring: Keyring) -> dict[str, Any]:
    """The four R11 parts on fakes, linked and sealed, so every one of their reads is listed."""
    from r11_fakes import ctx

    from jarvis.api.r11_wiring import BUILDERS

    out = {}
    for name, build in BUILDERS.items():
        c, _, _, _ = ctx(name)
        out[name] = build(replace(c, keyring=ring, google=google))
    return out


def read_tools(gw: Gateway) -> list[str]:
    out = []
    for spec in gw.registry.specs():
        tool = gw.registry.get(spec.name)
        if tool is not None and tool.risk is R1:
            out.append(spec.name)
    return sorted(out)


async def denied_on_telegram(
    names: list[str], risks: dict[str, ActionRisk] | None = None
) -> set[str]:
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=Clock())
    rules = ChannelRules(None, store)  # nothing paired: private reads are off
    with telegram_turn():
        got = await rules.rules_for(UID)
    return _denied(names, got, risks or {})


def _denied(names: list[str], got: list[Any], risks: dict[str, ActionRisk]) -> set[str]:
    return {
        n
        for n in names
        if any(r.effect is Effect.DENY and r.matches(n, {}, risks.get(n, R1)) for r in got)
    }


def every_tool(gw: Gateway) -> dict[str, ActionRisk]:
    """Every tool of the built registry, of any risk (not a hand list)."""
    out: dict[str, ActionRisk] = {}
    for spec in gw.registry.specs():
        tool = gw.registry.get(spec.name)
        if tool is not None:
            out[spec.name] = tool.risk
    return out


def home_tools(gw: Gateway) -> dict[str, ActionRisk]:
    return {n: r for n, r in every_tool(gw).items() if any(w in n for w in HOME_WORDS)}


async def test_every_read_tool_is_either_private_or_named_safe_for_telegram() -> None:
    reads = read_tools(await linked_gateway())
    assert len(reads) > 20  # the linked gateway really is whole
    private = await denied_on_telegram(reads)
    unclassified = [n for n in reads if n not in private and n not in TELEGRAM_SAFE]
    assert unclassified == [], (
        "classify these read tools for Telegram: add a pattern to telegram.rules.PRIVATE_PATTERNS "
        f"or name them in TELEGRAM_SAFE: {unclassified}"
    )


async def test_the_safe_list_has_no_stale_or_doubly_classified_names() -> None:
    reads = read_tools(await linked_gateway())
    private = await denied_on_telegram(reads)
    assert TELEGRAM_SAFE <= set(reads), sorted(TELEGRAM_SAFE - set(reads))
    assert not TELEGRAM_SAFE & private, sorted(TELEGRAM_SAFE & private)


@pytest.mark.parametrize(
    "tool",
    [
        "family_calendar_events",
        "deleted_list",
        "gmail_search",
        "drive_read",
        "doc_read",
        *R11_PRIVATE,
        *R111_PRIVATE,
    ],
)
async def test_private_titles_are_denied_on_telegram_by_default(tool: str) -> None:
    assert await denied_on_telegram([tool]) == {tool}


def test_the_patterns_are_not_a_catch_all() -> None:
    assert "*" not in PRIVATE_PATTERNS


R2_READS = (
    "vault_list",
    "vault_expiring",
    "kb_search",
    "kb_read",
    "belongings_where",
    "belongings_list",
    "belongings_history",
)


async def test_every_r2_read_is_registered_and_private_on_telegram() -> None:
    reads = read_tools(await linked_gateway())
    assert set(R2_READS) <= set(reads)
    assert await denied_on_telegram(list(R2_READS)) == set(R2_READS)


@pytest.mark.parametrize("tool", R2_READS)
async def test_gate_with_defaults_an_r2_read_is_refused_on_a_telegram_turn(tool: str) -> None:
    """R2 D12 gate: through the real gateway with the wired Telegram rules, nothing paired or
    switched on: the call is refused and audited as denied; nothing is read."""
    gw = await linked_gateway()
    gw.rules = wrap_rules(gw.rules, TelegramStore(MemoryDocs(), prefix="t_", clock=Clock()))
    args = {"item": "passport"} if tool in ("belongings_where", "belongings_history") else {}
    if tool == "kb_search":
        args = {"query": "plumber"}
    elif tool == "kb_read":
        args = {"id": "n_000000000000"}
    with telegram_turn():
        out = await gw.execute(ToolCall(id="t1", name=tool, arguments=args), scope=f"{UID}:tg")
    assert out.outcome is GatewayOutcome.DENIED, (tool, out.error)
    assert "Telegram" in (out.error or "")


async def test_every_r3_read_is_registered_and_private_on_telegram() -> None:
    reads = read_tools(await linked_gateway())
    assert set(R3_READS) | set(R3_SAFE) <= set(reads)
    assert await denied_on_telegram(list(R3_READS)) == set(R3_READS)
    assert await denied_on_telegram(list(R3_SAFE)) == set()


R3_ARGS: dict[str, dict[str, object]] = {
    "home_devices": {},
    "camera_history": {"start": "2026-11-04T00:00:00+05:30", "end": "2026-11-05T00:00:00+05:30"},
    "faces_list": {},
}


@pytest.mark.parametrize("tool", R3_READS)
async def test_gate_with_defaults_an_r3_read_is_refused_on_a_telegram_turn(tool: str) -> None:
    """R3 D15 gate: the third switch is off by default, so home devices, camera history and the
    people JARVIS recognises are refused on Telegram; the other two switches never open it."""
    gw = await linked_gateway()
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=Clock())
    code, _ = await store.start_pairing(UID)
    await store.finish_pairing(code, tg_user_id=1, chat_id=2)
    await store.set_settings(UID, allow_private_reads=True, allow_personal_reads=True)
    gw.rules = wrap_rules(gw.rules, store)
    call = ToolCall(id="t1", name=tool, arguments=R3_ARGS[tool])
    with telegram_turn():
        out = await gw.execute(call, scope=f"{UID}:tg")
    assert out.outcome is GatewayOutcome.DENIED, (tool, out.error)
    assert "home devices" in (out.error or "")
    await store.set_settings(UID, allow_home_reads=True)
    with telegram_turn():
        out = await gw.execute(call, scope=f"{UID}:tg")
    assert out.outcome is not GatewayOutcome.DENIED, (tool, out.error)


async def test_home_disarm_on_telegram_never_disarms_and_points_to_the_console() -> None:
    gw = await linked_gateway()
    gw.rules = wrap_rules(gw.rules, TelegramStore(MemoryDocs(), prefix="t_", clock=Clock()))
    with telegram_turn():
        out = await gw.execute(
            ToolCall(id="t1", name="home_disarm", arguments={}), scope=f"{UID}:tg"
        )
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert out.result["status"] == "refused" and "Home panel" in out.result["message"]


# ---- Recently deleted on Telegram (R2 integrated review H1 / S1) --------------------------------
# deleted_list needs the first switch, and shows vault documents, notes and things only when the
# second is on too; deleted_restore (any kind) needs both. Through the real gateway.
SWITCHES = [(False, False), (True, False), (False, True), (True, True)]
EVERY_KIND = (
    ("event", "Dentist"),
    ("task", "Pay the bill"),
    ("vault_item", "A document"),
    ("note", "A note from 4 Nov"),
    ("thing", "A thing you noted"),
)


async def _switched(gw: Gateway, *, private: bool, personal: bool) -> None:
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=Clock())
    code, _ = await store.start_pairing(UID)
    await store.finish_pairing(code, tg_user_id=1, chat_id=2)
    await store.set_settings(UID, allow_private_reads=private, allow_personal_reads=personal)
    gw.rules = wrap_rules(gw.rules, store)


async def _bin_with_every_kind(undo: UndoBin) -> dict[str, str]:
    ids: dict[str, str] = {}
    for kind, title in EVERY_KIND:
        item = await undo.keep(UID, kind, title, {"ref": "x"}, owner_authored=True)  # type: ignore[arg-type]
        ids[kind] = item.id
    return ids


@pytest.mark.parametrize(("private", "personal"), SWITCHES)
async def test_gate_deleted_list_shows_r2_entries_only_with_both_switches(
    private: bool, personal: bool
) -> None:
    undo = UndoBin(DeletedStore(MemoryDocs()))
    gw = await linked_gateway(undo)
    await _switched(gw, private=private, personal=personal)
    await _bin_with_every_kind(undo)
    call = ToolCall(id="t1", name="deleted_list", arguments={})
    with telegram_turn():
        out = await gw.execute(call, scope=f"{UID}:tg")
    if not private:
        assert out.outcome is GatewayOutcome.DENIED and "Telegram" in (out.error or "")
        return
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    kinds = {i["kind"] for i in out.result["items"]}
    if personal:
        assert kinds == {"event", "to-do", "vault document", "note", "thing"}
        assert "note" not in out.result
    else:
        assert kinds == {"event", "to-do"}
        assert "Telegram" in out.result["note"] and "3" not in out.result["note"]
        blob = str(out.result)
        assert "A document" not in blob and "A note from" not in blob and "A thing" not in blob


async def test_off_telegram_deleted_list_shows_every_kind() -> None:
    undo = UndoBin(DeletedStore(MemoryDocs()))
    gw = await linked_gateway(undo)
    await _switched(gw, private=False, personal=False)
    await _bin_with_every_kind(undo)
    out = await gw.execute(ToolCall(id="t1", name="deleted_list", arguments={}), scope=f"{UID}:s")
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert len(out.result["items"]) == len(EVERY_KIND) and "note" not in out.result


@pytest.mark.parametrize(("private", "personal"), SWITCHES)
@pytest.mark.parametrize("kind", ["event", "note", "vault_item", "thing"])
async def test_gate_deleted_restore_needs_both_switches_on_telegram(
    private: bool, personal: bool, kind: str
) -> None:
    undo = UndoBin(DeletedStore(MemoryDocs()))
    gw = await linked_gateway(undo)
    await _switched(gw, private=private, personal=personal)
    ids = await _bin_with_every_kind(undo)
    call = ToolCall(id="t2", name="deleted_restore", arguments={"undo_id": ids[kind]})
    with telegram_turn():
        out = await gw.execute(call, scope=f"{UID}:tg")
    if private and personal:
        assert out.outcome is not GatewayOutcome.DENIED, out.error
        return
    assert out.outcome is GatewayOutcome.DENIED, (kind, out.outcome)
    assert "Telegram" in (out.error or "") and "both" in (out.error or "")
    item = await undo.get(UID, ids[kind])
    assert item is not None and not item.restored and item.restoring_since is None


async def test_every_r111_part_read_is_registered_and_classified() -> None:
    """R11.1 I1 gate (INTEGRATION-A 3.12): the parts' tools are in the linked gateway, and every
    read of private data among them is denied on Telegram by default (A: gmail_inbox_summary;
    D: picture_research; C's face counts under the home switch, read off the registry)."""
    gw = await linked_gateway()
    reads = read_tools(gw)
    r111 = {t.name for t in r111_tools(None, MemoryDocs()) if t.risk is R1}
    homes = set(home_tools(gw))
    assert r111 - homes == {*R111_PRIVATE, "series_list"}, sorted(r111)
    assert r111 <= set(reads)  # every part is really there, as the app builds it
    assert await denied_on_telegram(list(R111_PRIVATE)) == set(R111_PRIVATE)
    assert await denied_on_telegram(sorted(r111 & homes)) == r111 & homes
    assert await denied_on_telegram(["series_list", "series_checkin"]) == set()


# R7 (docs/plans/r7-mobile.md D18, I0 seam 21): the watch, sleep and kept camera results are his
# own health numbers and what his camera read: private on Telegram. The brain's one SOS tool,
# `sos_status`, names no contact and no place, so it stays answerable there.
R7_PLANNED_PRIVATE = (
    "sleep_last_night",
    "sleep_week",
    "watch_today",
    "sleep_note",
    "vision_results",
)


async def test_every_r7_part_read_is_registered_and_private_on_telegram() -> None:
    """The list comes from the BUILT registry (R11.1's integrated security review H2), so a part
    that adds a read the patterns miss turns this red; the planned names are checked too."""
    gw = await linked_gateway()
    tools = every_tool(gw)
    r7 = {t.name: t.risk for t in r7_tools(None, MemoryDocs())}
    assert set(r7) <= set(tools)  # every part's tools are really there, as the app builds them
    private = {n for n in r7 if n != "sos_status"}
    assert await denied_on_telegram(sorted(private), r7) == private
    assert await denied_on_telegram(list(R7_PLANNED_PRIVATE)) == set(R7_PLANNED_PRIVATE)
    assert await denied_on_telegram(["sos_status"]) == set()
    every_r7_read = {n for n, r in tools.items() if n.startswith(("watch_", "sleep_", "vision_"))}
    assert await denied_on_telegram(sorted(every_r7_read), tools) == every_r7_read


async def test_every_face_home_or_photo_tool_of_the_built_registry_waits_for_the_home_switch() -> (
    None
):
    """I1 security review H2: the list comes from the BUILT registry, every risk, not a hand
    list. With the home switch off (the other two on), every tool whose name says face, home,
    photo or camera is refused on Telegram except R3 D8's four; with it on, none is. A new tool
    with a name the patterns miss (`photos_import` beside `photos_import_*`) fails here."""
    gw = await linked_gateway()
    homes = home_tools(gw)
    assert {"photos_import", "photos_import_status", "faces_groups", "faces_list"} <= set(homes)
    assert HOME_KEPT_ON_TELEGRAM <= set(homes), sorted(HOME_KEPT_ON_TELEGRAM - set(homes))
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=Clock())
    code, _ = await store.start_pairing(UID)
    await store.finish_pairing(code, tg_user_id=1, chat_id=2)
    await store.set_settings(UID, allow_private_reads=True, allow_personal_reads=True)
    rules = ChannelRules(None, store)
    with telegram_turn():
        off = _denied(sorted(homes), await rules.rules_for(UID), homes)
    assert off == set(homes) - HOME_KEPT_ON_TELEGRAM, sorted(set(homes) - off)
    await store.set_settings(UID, allow_home_reads=True)
    with telegram_turn():
        on = _denied(sorted(homes), await rules.rules_for(UID), homes)
    assert on == set(), sorted(on)


async def test_the_home_patterns_name_the_real_photo_import_tool() -> None:
    """`photos_import` itself (R2: it answers faces found and the people recognised by name), not
    only `photos_import_*`; checked on the registry's own risk for it."""
    gw = await linked_gateway()
    risks = every_tool(gw)
    assert risks["photos_import"] is ActionRisk.REVERSIBLE
    assert await denied_on_telegram(["photos_import"], risks) == {"photos_import"}
    assert any(p == "photos_import" for p in HOME_PATTERNS)


async def test_with_private_reads_on_the_inbox_summary_answers_but_the_home_ones_still_wait() -> (
    None
):
    """The two switches stay separate: private reads open A's and D's reads, never C's."""
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=Clock())
    code, _ = await store.start_pairing(UID)
    await store.finish_pairing(code, tg_user_id=1, chat_id=2)
    await store.set_settings(UID, allow_private_reads=True)
    rules = ChannelRules(None, store)
    with telegram_turn():
        got = await rules.rules_for(UID)
    homes = home_tools(await linked_gateway())
    r111_home = sorted(n for n in homes if n.startswith(("faces_groups", "photos_import")))
    denied = _denied([*R111_PRIVATE, *r111_home], got, homes)
    assert denied == set(r111_home)
