# tests/test_r14_i1_noai_real.py -- R14 I1 (INTEGRATION-D "Needs I1" 7): with the AI off, D12's
# phrases reach the REAL tools (each built from its own module on its own release's fakes, never
# a stand-in that returns `message`) and every answer reads as a sentence: no JSON, no
# EXTERNAL CONTENT fence markers, no words meant for the model ("Tell the owner", "Do not say").
# D's eval and app tests run on fakes, so they could not see what the real results look like.
from __future__ import annotations

import datetime as dt
import re
from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import test_packages_tool as parcels
import test_r11_1_a_inbox as inbox_rig
from belongings_fakes import UID as THINGS_UID
from belongings_fakes import things
from camera_fakes import rig as camera_rig
from home_fakes import UID as HOME_UID
from home_fakes import World, build
from memory_fakes import UID as MEMORY_UID
from memory_fakes import rig as memory_rig
from r1d_fakes import OWNER, GmailFake, GroceryTasks, connector
from r11_1_fakes_a import UID as INBOX_UID
from vault_fakes import PDF, make
from vault_fakes import UID as VAULT_UID

from jarvis.belongings.tools import NOT_NOTED, belongings_tools
from jarvis.camera.tools import camera_tools
from jarvis.core.guardrails import ConfirmationGate
from jarvis.groceries.service import GroceryClient, GroceryService
from jarvis.groceries.store import GroceryStore
from jarvis.groceries.tools import grocery_tools
from jarvis.home.tools import HomeStatusReader, home_tools
from jarvis.offline import phrases_r14 as p14
from jarvis.offline.no_ai import NoAIResult, run_no_ai
from jarvis.recall.tools import memory_tools
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import AuditLog, Gateway, Policy, Tool, ToolRegistry
from jarvis.tools.task_marks import OutsideTasks
from jarvis.undo.tools import undo_tools
from jarvis.vault.tools import vault_tools

NOW = datetime(2026, 11, 14, 16, 5, tzinfo=ZoneInfo("Asia/Kolkata"))
# what must never reach him as an answer: a JSON object or list, a fence's markers, the model's
# instructions written into a tool's words
NOT_A_SENTENCE = re.compile(
    r'^\s*[\[{]|"\w+": |<<EXTERNAL CONTENT|<<END [0-9a-f]{6}>>|the owner|Do not say', re.I
)


def _gw(tools: Iterable[Tool]) -> Gateway:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


async def _say(gw: Gateway, uid: str, text: str, tool: str) -> str:
    out: NoAIResult = await run_no_ai(gw, text, NOW, scope=f"{uid}:s1", extra=p14.ROUTERS)
    assert [c.name for c in out.calls] == [tool], text
    assert not NOT_A_SENTENCE.search(out.reply), out.reply
    return out.reply


async def test_the_grocery_list_is_said_in_words() -> None:
    conn = await connector(GroceryTasks().client(), tasks=True)
    svc = GroceryService(
        GroceryClient(conn), GroceryStore(MemoryDocs()), OutsideTasks(MemoryDocs())
    )
    gw = _gw(grocery_tools(svc))
    none = await _say(gw, OWNER, "what's on my shopping list?", "grocery_list")
    assert "no Groceries list yet" in none
    added = await _say(gw, OWNER, "add milk and eggs to my grocery list", "grocery_add")
    assert "milk" in added and "eggs" in added and "added" in added.lower()
    rice = await _say(gw, OWNER, "add 2 kg rice to my grocery list", "grocery_add")
    assert "rice (2 kg)" in rice
    shown = await _say(gw, OWNER, "what's on my shopping list?", "grocery_list")
    assert "milk, eggs, rice (2 kg)" in shown
    gone = await _say(gw, OWNER, "remove milk from my grocery list", "grocery_remove")
    assert "ticked off milk" in gone.lower()
    missing = await _say(gw, OWNER, "remove bananas from my grocery list", "grocery_remove")
    assert "bananas" in missing and "isn't on" in missing


async def test_what_expires_in_the_vault_is_said_in_words() -> None:
    svc, _, _ = make()
    gw = _gw(vault_tools(svc))
    none = await _say(gw, VAULT_UID, "what's expiring in my vault", "vault_expiring")
    assert "Nothing in your vault expires in the next 90 days" in none
    item = (await svc.add_file(VAULT_UID, PDF, type_hint="passport")).item
    ends = (NOW.date() + dt.timedelta(days=40)).isoformat()
    await svc.update(VAULT_UID, item.id, {"last4": "4821", "confirm": True, "expires_on": ends})
    one = await _say(gw, VAULT_UID, "which documents expire soon?", "vault_expiring")
    assert "1 document expires within 90 days" in one and "your Passport" in one
    assert "days left" in one and "4821" not in one


async def test_where_a_thing_is_and_where_he_put_it_are_said_in_words() -> None:
    box = things()
    gw = _gw(belongings_tools(box.svc))
    none = await _say(gw, THINGS_UID, "where did I put my passport", "belongings_where")
    assert none == NOT_NOTED
    put = await _say(gw, THINGS_UID, "I kept the keys in the drawer", "belongings_put")
    assert put == "Noted, Sir. Your keys: the drawer."
    moved = await _say(gw, THINGS_UID, "I've put my keys under the blue file.", "belongings_put")
    assert moved == "Noted, Sir. Your keys: under the blue file (before: the drawer)."
    where = await _say(gw, THINGS_UID, "where are my keys?", "belongings_where")
    assert where.startswith("Your keys: under the blue file (noted on 2026-")


async def test_the_parcels_are_said_in_words() -> None:
    gw = await parcels.gateway(parcels.inbox())
    some = await _say(gw, OWNER, "where's my parcel", "gmail_track_packages")
    assert "Flipkart" in some and "shipped" in some and "Ekart" in some
    gw = await parcels.gateway(GmailFake([]))
    none = await _say(gw, OWNER, "where are my orders?", "gmail_track_packages")
    assert "No order or shipping emails found" in none


async def test_the_inbox_summary_is_said_in_words() -> None:
    rig = await inbox_rig._rig()
    some = await _say(rig.gw, INBOX_UID, "check my email", "gmail_inbox_summary")
    assert some.startswith("132 unread in your inbox, Sir") and "People" in some
    assert "Priya Menon" in some and "Budget review on Friday" in some
    rig = await inbox_rig._rig([])
    none = await _say(rig.gw, INBOX_UID, "any new mail?", "gmail_inbox_summary")
    assert none.startswith("132 unread in your inbox, Sir")


async def test_recently_deleted_is_said_in_words() -> None:
    box = things()
    gw = _gw([*undo_tools(box.undo), *belongings_tools(box.svc)])
    none = await _say(gw, THINGS_UID, "what did I delete", "deleted_list")
    assert none == "Nothing was deleted in the last 30 days, Sir."
    await box.svc.put(THINGS_UID, "umbrella", "the hall stand", origin="typed")
    await box.svc.remove(THINGS_UID, "umbrella")
    one = await _say(gw, THINGS_UID, "show recently deleted", "deleted_list")
    # a thing's bin entry has a generic title by design (R2 D8): its words stay in its own store
    assert one == "Recently deleted, kept 30 days, Sir: thing “A thing you noted”, 2026-11-14."


async def test_what_jarvis_remembers_is_said_in_words() -> None:
    m = memory_rig()
    gw = _gw(memory_tools(m.svc))
    none = await _say(gw, MEMORY_UID, "what do you remember about Lekha", "memory_search")
    assert none == "I have nothing saved about that, Sir."
    await m.svc.add_fact(MEMORY_UID, "Lekha is my sister; her birthday is 3 March", "people")
    one = await _say(gw, MEMORY_UID, "what do you remember about Lekha", "memory_search")
    assert one == "From your memory, Sir: Lekha is my sister; her birthday is 3 March."


async def test_arming_is_said_to_him_not_to_the_model() -> None:
    r = await camera_rig()
    gw = _gw(camera_tools(r.alarm, r.gate, r.history, confirm_wait_s=0.0))
    said = await _say(gw, "u_owner", "arm the alarm", "home_arm")
    assert said.startswith("Arming, Sir: waiting for your laptop.")


@pytest.fixture
async def home(tmp_path: Path) -> AsyncIterator[World]:
    world = build(tmp_path)
    await world.link_up()
    yield world
    await world.aclose()


async def test_the_home_status_says_the_laptop_and_the_alarm(home: World) -> None:
    from test_home_webhook import hb, post

    reader = HomeStatusReader(home.store, clock=home.clock, offline_after_s=720, arm=home.arm)
    gw = _gw(home_tools(home.devices, reader))
    home.arm.armed = True
    off = await _say(gw, HOME_UID, "is the house armed", "home_status")
    assert "off or asleep" in off and off.endswith("The alarm: armed.")  # what he asked
    await post(home, hb())
    on: Any = await _say(gw, HOME_UID, "home status", "home_status")
    assert on.startswith("Your home laptop is online, Sir")
    assert "The alarm: armed." in on and "1 of 1 camera online" in on
