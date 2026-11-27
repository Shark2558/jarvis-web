"""R18 C: the hearing and speaking threads with fake blocking devices: frames reach the event loop,
playback goes frame by frame, `cut` silences JARVIS within a frame and drops its markers, and a
device error ends the thread with a message instead of hanging the call."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from jarvis.calldesk.audio import FRAME_BYTES
from jarvis.calldesk.ports import AudioDeviceError
from jarvis.calldesk.sound import MAX_QUEUED_FRAMES, Hearing, Speaking


class FakeCapture:
    def __init__(self, frames: list[bytes], fail_after: int | None = None) -> None:
        self.frames = list(frames)
        self.fail_after = fail_after
        self.reads = 0
        self.closed = threading.Event()

    def read(self) -> bytes:
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise AudioDeviceError("the recording device went away")
        time.sleep(0.002)
        return self.frames.pop(0) if self.frames else b"\x00" * FRAME_BYTES

    def close(self) -> None:
        self.closed.set()


class FakePlayer:
    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.written: list[bytes] = []
        self.delay = delay
        self.fail = fail
        self.closed = threading.Event()
        self.gate = threading.Event()
        self.gate.set()

    def write(self, pcm: bytes) -> None:
        if self.fail:
            raise AudioDeviceError("CABLE Input went away")
        self.gate.wait(2)
        time.sleep(self.delay)
        self.written.append(pcm)

    def close(self) -> None:
        self.closed.set()


class FakeDevices:
    def __init__(self, capture: FakeCapture | None = None, player: FakePlayer | None = None):
        self.capture = capture or FakeCapture([])
        self.player = player or FakePlayer()

    def open_loopback(self) -> FakeCapture:
        return self.capture

    def open_cable_player(self) -> FakePlayer:
        return self.player


async def _until(cond: object, timeout: float = 2.0) -> None:
    end = time.monotonic() + timeout
    while not cond():  # type: ignore[operator]
        if time.monotonic() > end:
            raise AssertionError("timed out")
        await asyncio.sleep(0.005)


async def test_hearing_hands_frames_to_the_loop_and_closes_on_stop() -> None:
    frames = [bytes([i]) * FRAME_BYTES for i in range(1, 6)]
    devices = FakeDevices(capture=FakeCapture(frames))
    got: list[bytes] = []
    hearing = Hearing(devices, asyncio.get_running_loop(), got.append, lambda m: None)
    hearing.start()
    hearing.start()  # a second start is a no-op
    await _until(lambda: len(got) >= 5)
    hearing.stop()
    assert got[:5] == frames and not hearing.running
    assert devices.capture.closed.is_set()


async def test_hearing_reports_a_device_error() -> None:
    devices = FakeDevices(capture=FakeCapture([], fail_after=2))
    errors: list[str] = []
    hearing = Hearing(devices, asyncio.get_running_loop(), lambda f: None, errors.append)
    hearing.start()
    await _until(lambda: errors)
    assert errors == ["the recording device went away"] and devices.capture.closed.is_set()
    hearing.stop()


async def test_hearing_refuses_a_broken_frame() -> None:
    devices = FakeDevices(capture=FakeCapture([b"\x00" * 10]))
    errors: list[str] = []
    hearing = Hearing(devices, asyncio.get_running_loop(), lambda f: None, errors.append)
    hearing.start()
    await _until(lambda: errors)
    hearing.stop()
    assert "broken frame" in errors[0]


async def test_speaking_plays_frame_by_frame_then_fires_the_marker() -> None:
    devices = FakeDevices()
    played: list[str] = []
    speaking = Speaking(devices, asyncio.get_running_loop(), played.append, lambda m: None)
    speaking.start()
    assert speaking.play(b"\x01" * (FRAME_BYTES * 3 + 10))
    speaking.mark("u1")
    await _until(lambda: played)
    assert played == ["u1"] and len(devices.player.written) == 4
    assert all(len(f) == FRAME_BYTES for f in devices.player.written)
    await _until(lambda: not speaking.busy)
    speaking.stop()
    assert devices.player.closed.is_set() and not speaking.running


async def test_cut_silences_within_a_frame_and_drops_the_marker() -> None:
    player = FakePlayer()
    player.gate.clear()  # hold the first frame "in the device"
    devices = FakeDevices(player=player)
    played: list[str] = []
    speaking = Speaking(devices, asyncio.get_running_loop(), played.append, lambda m: None)
    speaking.start()
    speaking.play(b"\x02" * FRAME_BYTES * 50)
    speaking.mark("u1")
    await _until(lambda: speaking.busy)
    assert speaking.cut() is True
    player.gate.set()
    await _until(lambda: not speaking.busy)
    await asyncio.sleep(0.05)
    assert len(player.written) <= 1 and played == []
    assert speaking.cut() is False  # nothing left to cut
    speaking.mark("u2")  # a marker after the cut still fires
    await _until(lambda: played == ["u2"])
    speaking.stop()


async def test_speaking_queue_is_bounded() -> None:
    speaking = Speaking(FakeDevices(), asyncio.get_running_loop(), lambda t: None, lambda m: None)
    assert speaking.play(b"\x00" * FRAME_BYTES * MAX_QUEUED_FRAMES)
    assert speaking.play(b"\x00" * FRAME_BYTES) is False
    speaking.cut()
    assert speaking.play(b"\x00" * FRAME_BYTES)


async def test_speaking_reports_a_device_error() -> None:
    devices = FakeDevices(player=FakePlayer(fail=True))
    errors: list[str] = []
    speaking = Speaking(devices, asyncio.get_running_loop(), lambda t: None, errors.append)
    speaking.start()
    speaking.play(b"\x00" * FRAME_BYTES)
    await _until(lambda: errors)
    assert errors == ["CABLE Input went away"] and devices.player.closed.is_set()
    assert not speaking.busy
    speaking.stop()


@pytest.mark.parametrize("cls", [Hearing, Speaking])
async def test_a_closed_loop_does_not_crash_the_thread(cls: type) -> None:
    loop = asyncio.new_event_loop()
    loop.close()
    worker = cls(FakeDevices(), loop, lambda *_: None, lambda *_: None)
    worker.start()
    if isinstance(worker, Speaking):
        worker.play(b"\x00" * FRAME_BYTES)
        worker.mark("u")
    await asyncio.sleep(0.05)
    worker.stop()
