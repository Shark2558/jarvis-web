"""R18 A2: live listeners of a call (BUILD-BRIEF row A2 item 2; docs/plans/r18-calls.md 4.7).

Captions and state always reach a listener in order; audio is droppable (a slow listener loses
the oldest frames, never the call); a listener too far behind on captions, or whose socket
stalls, is closed. The mixer sums both sides' 20 ms frames into one.
"""

from __future__ import annotations

import asyncio
import json
import struct

import pytest

from jarvis.calls.live import (
    AUDIO_BACKLOG_FRAMES,
    FRAME_BYTES,
    LIVE_AUDIO,
    TEXT_BACKLOG,
    WS_TOO_SLOW,
    LiveListener,
    LiveRoom,
    Mixer,
    mix,
)


class Sink:
    def __init__(self, *, stall: bool = False) -> None:
        self.texts: list[dict[str, object]] = []
        self.binary: list[bytes] = []
        self.closed: int | None = None
        self.stall = stall

    async def send_text(self, data: str) -> None:
        if self.stall:
            await asyncio.sleep(3600)
        self.texts.append(json.loads(data))

    async def send_bytes(self, data: bytes) -> None:
        if self.stall:
            await asyncio.sleep(3600)
        self.binary.append(data)

    async def close(self, code: int) -> None:
        self.closed = code


def _frame(value: int) -> bytes:
    return struct.pack("<320h", *([value] * 320))


def test_mix_sums_and_saturates() -> None:
    assert mix(_frame(100), _frame(-30)) == _frame(70)
    assert mix(_frame(30000), _frame(10000)) == _frame(32767)
    assert mix(_frame(-30000), _frame(-10000)) == _frame(-32768)


def test_mixer_pairs_one_frame_from_each_side_per_tick() -> None:
    m = Mixer()
    m.them(_frame(10))
    m.jarvis(_frame(5))
    m.jarvis(_frame(7))
    assert m.tick() == _frame(15)
    assert m.tick() == _frame(7)
    assert m.tick() is None


def test_mixer_drops_wrong_sized_frames_and_bounds_its_backlog() -> None:
    m = Mixer()
    m.them(b"\x00" * 10)
    assert m.tick() is None
    for i in range(50):
        m.them(_frame(i))
    assert m.backlog() <= AUDIO_BACKLOG_FRAMES
    assert m.tick() == _frame(50 - AUDIO_BACKLOG_FRAMES)  # the oldest went first


async def test_captions_go_before_audio_and_in_order() -> None:
    sink = Sink()
    listener = LiveListener(sink, audio=True, send_timeout_s=1.0)
    listener.push_audio(_frame(1))
    listener.push_json({"type": "caption", "text": "one"})
    listener.push_json({"type": "caption", "text": "two"})
    task = asyncio.create_task(listener.run())
    await asyncio.sleep(0.01)
    listener.close(1000)
    await task
    assert [t["text"] for t in sink.texts] == ["one", "two"]
    assert sink.binary == [bytes([LIVE_AUDIO]) + _frame(1)]


async def test_captions_only_listener_gets_no_audio() -> None:
    sink = Sink()
    listener = LiveListener(sink, audio=False, send_timeout_s=1.0)
    listener.push_audio(_frame(1))
    task = asyncio.create_task(listener.run())
    listener.set_audio(True)
    listener.push_audio(_frame(2))
    await asyncio.sleep(0.01)
    listener.close(1000)
    await task
    assert sink.binary == [bytes([LIVE_AUDIO]) + _frame(2)]


def test_a_slow_listener_loses_the_oldest_audio_only() -> None:
    listener = LiveListener(Sink(), audio=True)
    for i in range(AUDIO_BACKLOG_FRAMES + 10):
        listener.push_audio(_frame(i))
    assert listener.audio_backlog() == AUDIO_BACKLOG_FRAMES
    assert listener.dropped_audio == 10
    assert not listener.closed


def test_a_listener_far_behind_on_captions_is_closed() -> None:
    sink = Sink()
    listener = LiveListener(sink, audio=False)
    for i in range(TEXT_BACKLOG + 1):
        listener.push_json({"type": "caption", "text": str(i)})
    assert listener.closed
    assert listener.close_code == WS_TOO_SLOW


async def test_a_stalled_socket_is_closed_after_the_send_timeout() -> None:
    sink = Sink(stall=True)
    listener = LiveListener(sink, audio=False, send_timeout_s=0.05)
    listener.push_json({"type": "state", "state": "talking"})
    await asyncio.wait_for(listener.run(), timeout=1.0)
    assert listener.closed
    assert sink.closed == WS_TOO_SLOW


async def test_room_broadcasts_and_forgets_closed_listeners() -> None:
    room = LiveRoom()
    a, b = Sink(), Sink()
    la = LiveListener(a, audio=True, send_timeout_s=1.0)
    lb = LiveListener(b, audio=False, send_timeout_s=1.0)
    room.add(la)
    room.add(lb)
    tasks = [asyncio.create_task(la.run()), asyncio.create_task(lb.run())]
    room.send({"type": "caption", "text": "hi"})
    room.audio(_frame(3))
    assert room.wants_audio()
    await asyncio.sleep(0.01)
    lb.close(1000)
    await asyncio.sleep(0)
    room.send({"type": "state", "state": "ended"})
    assert len(room) == 1
    room.close_all(1000)
    await asyncio.gather(*tasks)
    assert [t["type"] for t in a.texts] == ["caption", "state"]
    assert [t["type"] for t in b.texts] == ["caption"]
    assert len(a.binary) == 1 and not b.binary


def test_room_without_audio_listeners_needs_no_mixing() -> None:
    room = LiveRoom()
    room.add(LiveListener(Sink(), audio=False))
    assert not room.wants_audio()


@pytest.mark.parametrize("bad", [b"", b"\x00" * 639, b"\x00" * 641])
def test_mix_refuses_wrong_sizes(bad: bytes) -> None:
    with pytest.raises(ValueError):
        mix(bad, _frame(0))
    assert len(_frame(0)) == FRAME_BYTES
