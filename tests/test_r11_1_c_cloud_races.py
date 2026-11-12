# tests/test_r11_1_c_cloud_races.py -- the cloud's copy of the laptop's groups when things happen at
# once (review C-code M3) and a name that could not be applied (C-code M7). An ask made while the
# laptop was being called is never overwritten by an answer read before it; a name given while the
# laptop slept whose group had gone there is told to the owner, never dropped in silence.
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from r11_1_fakes_c import build_cloud, consent

from jarvis.facegroups.service import LOST_ONE
from jarvis.photos.edge import EdgeOffline

UID = "u_owner"


class Gate:
    """Holds the laptop's groups answer until the test lets it through."""

    def __init__(self, real: Any) -> None:
        self.real, self.entered, self.release = real, asyncio.Event(), asyncio.Event()

    async def __call__(self, uid: str) -> Any:
        answer = await self.real(uid)  # what the laptop says NOW ...
        self.entered.set()
        await self.release.wait()  # ... arrives later
        return answer


async def test_a_forget_asked_while_the_list_was_being_read_is_not_lost(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    one = await c.group_of(1)
    edge = c.photos.edge
    gate = Gate(edge.groups)
    edge.groups = gate  # type: ignore[method-assign]
    reading = asyncio.create_task(c.groups.view(UID))  # the panel's refresh, in flight
    await gate.entered.wait()

    async def away(uid: str, groups: Any) -> Any:
        raise EdgeOffline()

    real_forget = edge.forget
    edge.forget = away  # type: ignore[method-assign]
    waiting = await c.groups.forget(UID, one)  # the owner's Forget: the laptop just dozed off
    assert waiting.done is False
    gate.release.set()
    await reading  # the refresh lands with an answer read BEFORE the forget
    doc = await c.groups.store.get(UID)
    assert doc.forget == (one,), "the owner's ask was overwritten by a stale copy"
    view = await c.groups.view(UID)
    assert view.forgets_waiting == 1 and one not in [g.id for g in view.groups]
    edge.forget = real_forget  # type: ignore[method-assign]
    assert (await c.groups.poll(UID))["forgotten"] == 1
    assert (await c.groups.store.get(UID)).forget == ()
    await c.home.aclose()


async def test_a_forget_all_asked_while_the_list_was_being_read_is_not_lost(
    tmp_path: Path,
) -> None:
    c = await build_cloud(tmp_path)
    await c.group_of(1)
    edge = c.photos.edge
    gate = Gate(edge.groups)
    edge.groups = gate  # type: ignore[method-assign]
    reading = asyncio.create_task(c.groups.view(UID))
    await gate.entered.wait()

    async def away(uid: str, groups: Any) -> Any:
        raise EdgeOffline()

    edge.forget = away  # type: ignore[method-assign]
    assert (await c.groups.forget_all(UID)).done is False
    gate.release.set()
    await reading
    assert (await c.groups.store.get(UID)).forget_all is True
    await c.home.aclose()


async def test_a_name_whose_group_went_while_the_laptop_slept_is_told_not_dropped(
    tmp_path: Path,
) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    c.home.online = False
    done = await c.groups.name(UID, gid, **consent())  # registered; the laptop will be told
    assert done.at_home is False
    await c.home.groups.forget([gid])  # meanwhile the group goes on the laptop (expired, say)
    c.home.online = True
    before = len(c.home.notes.sent)
    out = await c.groups.poll(UID)
    assert out["named"] == 0 and out["lost"] == 1
    texts = [t for _, _, t in c.home.notes.sent[before:]]
    assert LOST_ONE in texts and len(LOST_ONE) <= 300
    assert "Anjali" not in " ".join(texts)  # a count and a fixed sentence, never a name
    assert (await c.groups.poll(UID))["lost"] == 0  # told once
    assert (await c.photos.pending(UID)) == ()
    await c.home.aclose()


async def test_without_a_way_to_tell_the_lost_name_stays_on_the_panel(tmp_path: Path) -> None:
    c = await build_cloud(tmp_path)
    gid = await c.group_of(1)
    c.home.online = False
    await c.groups.name(UID, gid, **consent())
    await c.home.groups.forget([gid])
    c.home.online = True
    c.groups._notifier = lambda: None  # noqa: SLF001 - alerts are off on this server
    assert (await c.groups.poll(UID))["lost"] == 0
    assert (await c.groups.view(UID)).names_lost == 1
    await c.home.aclose()
