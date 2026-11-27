"""R18 C: the call desk put together, end to end on Linux with fake Windows parts and a fake
JARVIS: a call is prepared (CABLE Output becomes the default microphone, the speaker recording
runs), JARVIS's voice is played, the other person's speech goes out, the call is released (his
microphone back), and a stop request ends the desk with everything restored. Plus the commands."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import struct
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.calldesk import __main__ as cli
from jarvis.calldesk import app, config
from jarvis.calldesk.client import LinkClosed, Refused
from jarvis.calldesk.micguard import AudioStateFile, SavedAudio
from jarvis.calldesk.ports import ROLES, Endpoint, Flow, Role
from jarvis.calldesk.watchdog import EXIT_ALREADY_RUNNING, EXIT_OK
from jarvis.calls import protocol as p

CALL = "call_00000000c0de"
OWN = Endpoint("{own}", "Microphone Array (Realtek(R) Audio)", "capture")
CABLE_OUT = Endpoint("{cout}", "CABLE Output (VB-Audio Virtual Cable)", "capture")
SPEAKER = Endpoint("{spk}", "Speakers (Realtek(R) Audio)", "render")
CABLE_IN = Endpoint("{cin}", "CABLE Input (VB-Audio Virtual Cable)", "render")
SEED = bytes(range(32))


class Policy:
    def __init__(self) -> None:
        self.defaults: dict[Role, str | None] = dict.fromkeys(ROLES, OWN.id)

    def endpoints(self, flow: Flow) -> Sequence[Endpoint]:
        return [SPEAKER, CABLE_IN] if flow == "render" else [OWN, CABLE_OUT]

    def default_id(self, flow: Flow, role: Role) -> str | None:
        return self.defaults[role]

    def set_default(self, device_id: str, role: Role) -> None:
        self.defaults[role] = device_id


class Sounds:
    def __init__(self) -> None:
        self.state = False

    def muted(self) -> bool | None:
        return self.state

    def set_muted(self, muted: bool) -> None:
        self.state = muted


def _speech(ms: int) -> bytes:
    n = 16 * ms
    vals = [int(9000 * math.sin(2 * math.pi * 150 * i / 16000)) for i in range(n)]
    return struct.pack(f"<{n}h", *vals)


class Capture:
    """Silence, then the other person speaking for 400 ms, then silence."""

    def __init__(self) -> None:
        self.frames = p.split_frames(b"\x00" * 640 * 30 + _speech(400) + b"\x00" * 640 * 40)

    def read(self) -> bytes:
        time.sleep(0.001)
        return self.frames.pop(0) if self.frames else b"\x00" * 640

    def close(self) -> None:
        pass


class Player:
    def __init__(self, sink: list[bytes]) -> None:
        self.sink = sink

    def write(self, pcm: bytes) -> None:
        self.sink.append(pcm)

    def close(self) -> None:
        pass


class Devices:
    def __init__(self) -> None:
        self.played: list[bytes] = []

    def open_loopback(self) -> Capture:
        return Capture()

    def open_cable_player(self) -> Player:
        return Player(self.played)


class Procs:
    def running(self) -> frozenset[str]:
        return frozenset({"phoneexperiencehost.exe"})


class FakeJarvis:
    """A connection that drives one call and then waits for the desk to be stopped."""

    def __init__(self, policy: Policy, stop_file: Path) -> None:
        self.policy = policy
        self.stop_file = stop_file
        self.sent: list[Any] = []
        self.headers: list[dict[str, str]] = []
        self.inbox: asyncio.Queue[Any] = asyncio.Queue()
        self.seen_cable = False

    async def connect(self, url: str, headers: dict[str, str]) -> FakeJarvis:
        self.headers.append(headers)
        assert url == "wss://jarvis.example/v1/calls/desk/ws"
        if len(self.headers) > 1:
            raise Refused(503)
        asyncio.ensure_future(self._script())
        return self

    async def _script(self) -> None:
        await self._until(lambda: any(isinstance(m, p.DeskState) for m in self.sent))
        prepare = {"type": "prepare", "call_id": CALL, "mode": "cloud", "languages": ["en-IN"]}
        self.inbox.put_nowait(json.dumps(prepare))
        await self._until(lambda: any(isinstance(m, p.Mic) for m in self.sent))
        self.seen_cable = set(self.policy.defaults.values()) == {CABLE_OUT.id}
        self.inbox.put_nowait(p.pack_audio(p.AudioKind.JARVIS, b"\x01\x00" * 320 * 5))
        await self._until(lambda: any(isinstance(m, bytes) for m in self.sent), timeout=3)
        await self._until(lambda: sum(isinstance(m, p.Vad) for m in self.sent) >= 2, timeout=3)
        self.inbox.put_nowait(json.dumps({"type": "release", "call_id": CALL}))
        await self._until(lambda: sum(isinstance(m, p.Mic) for m in self.sent) >= 2)
        self.stop_file.write_text("stop")

    async def _until(self, cond: Any, timeout: float = 2.0) -> None:
        end = time.monotonic() + timeout
        while not cond():
            if time.monotonic() > end:
                raise AssertionError("the desk did not answer in time")
            await asyncio.sleep(0.005)

    async def send(self, data: str | bytes) -> None:
        self.sent.append(p.parse_desk(data) if isinstance(data, str) else data)

    async def recv(self) -> str | bytes:
        item = await self.inbox.get()
        if isinstance(item, LinkClosed):
            raise item
        return item  # type: ignore[no-any-return]

    async def close(self) -> None:
        pass


def _cfg(tmp_path: Path) -> config.DeskConfig:
    cfg = config.DeskConfig("https://jarvis.example", tmp_path / "data", tmp_path)
    cfg.data_dir.mkdir()
    secret = {"home_id": "h_0123abcd", "seed": base64.b64encode(SEED).decode()}
    cfg.secret.write_text(json.dumps(secret), encoding="utf-8")
    return cfg


def _parts(policy: Policy, devices: Devices, connector: Any, single: bool = True) -> app.Parts:
    return app.Parts(policy, Sounds(), devices, Procs(), lambda role: single, connector)


async def test_one_call_end_to_end_then_stop(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    policy, devices = Policy(), Devices()
    jarvis = FakeJarvis(policy, cfg.stop_request)
    parts = _parts(policy, devices, jarvis.connect)
    code = await asyncio.wait_for(app.serve(cfg, parts, stop_poll_s=0.01), 10)
    assert code == EXIT_OK and jarvis.seen_cable
    assert policy.defaults == dict.fromkeys(ROLES, OWN.id)  # his microphone back
    kinds = [type(m).__name__ for m in jarvis.sent if not isinstance(m, bytes)]
    assert kinds[:3] == ["Hello", "DeskState", "DeskState"] and "Mic" in kinds
    audio = [m for m in jarvis.sent if isinstance(m, bytes)]
    assert all(p.unpack_audio(m)[0] is p.AudioKind.THEM for m in audio)
    assert b"\x01\x00" * 320 in b"".join(devices.played)  # JARVIS spoke into CABLE Input
    assert AudioStateFile(cfg.audio_state).load() is None


async def test_shutdown_restores_a_switch_left_mid_call(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    policy = Policy()
    stop = asyncio.Event()

    async def connect(url: str, headers: dict[str, str]) -> Any:
        guard = app.guard_for(cfg, parts)
        assert (await asyncio.to_thread(guard.switch_to_cable, CALL)).ok
        stop.set()
        raise Refused(503)

    parts = _parts(policy, Devices(), connect)
    await asyncio.wait_for(app.serve(cfg, parts, stop=stop), 5)
    assert policy.defaults == dict.fromkeys(ROLES, OWN.id)


def test_run_desk_restores_what_a_crash_left_and_refuses_a_second_desk(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    policy = Policy()
    policy.defaults = dict.fromkeys(ROLES, CABLE_OUT.id)
    state = SavedAudio(cable_id=CABLE_OUT.id, previous=dict.fromkeys(ROLES, OWN.id))
    AudioStateFile(cfg.audio_state).save(state)
    assert app.run_desk(cfg, _parts(policy, Devices(), None, single=False)) == EXIT_ALREADY_RUNNING
    cfg.stop_request.write_text("stop")

    async def never(url: str, headers: dict[str, str]) -> Any:
        raise Refused(503)

    assert app.run_desk(cfg, _parts(policy, Devices(), never)) == EXIT_OK
    assert policy.defaults == dict.fromkeys(ROLES, OWN.id)


def test_watchdog_runs_the_child_and_stops_on_request(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    child = [sys.executable, "-c", f"open(r'{cfg.stop_request}', 'w').write('x')"]
    parts = _parts(Policy(), Devices(), None)
    assert app.run_watchdog(cfg, parts, child) == EXIT_OK
    assert not cfg.stop_request.exists()
    assert app.run_watchdog(cfg, _parts(Policy(), Devices(), None, single=False), child) == 4


def test_check_and_restore_now(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    parts = _parts(Policy(), Devices(), None)
    assert app.check_now(cfg, parts).ready
    assert app.restore_now(cfg, parts).ok
    assert app.child_command()[1:] == ["-m", "jarvis.calldesk", "run"]


# ---- the commands ------------------------------------------------------------------------------


@pytest.fixture
def kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "desk.env").write_text("JARVIS_URL=https://jarvis.example\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_DESK_KIT", str(tmp_path))
    monkeypatch.setenv("JARVIS_DESK_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("JARVIS_URL", raising=False)
    return tmp_path


def test_usage_and_a_broken_kit(
    kit: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cli.main(["dance"]) == 2 and "usage" in capsys.readouterr().out
    monkeypatch.setenv("JARVIS_URL", "http://nope")
    assert cli.main(["check"]) == 2 and "JARVIS_URL" in capsys.readouterr().out


class Answer:
    def __init__(self, status: int, body: bytes) -> None:
        self.status, self.body = status, body

    def __enter__(self) -> Answer:
        return self

    def __exit__(self, *exc: Any) -> None:
        pass

    def read(self, n: int) -> bytes:
        return self.body[:n]


def test_link_with_the_code_from_the_console(kit: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sent: list[Any] = []

    def opener(req: Any, timeout: float) -> Answer:
        sent.append(req)
        seed = base64.urlsafe_b64encode(SEED).decode().rstrip("=")
        return Answer(201, json.dumps({"desk_id": "h_0123abcd", "seed": seed}).encode())

    assert cli.main(["link", "abcd-2345"], opener=opener) == 0
    assert "linked to JARVIS" in capsys.readouterr().out
    assert sent[0].full_url == "https://jarvis.example/v1/calls/desk/link"
    assert json.loads(sent[0].data) == {"code": "ABCD2345", "desk_version": "18.0.0"}
    assert (kit / "data" / "secret.json").exists()


def test_link_refusals_speak_plainly(kit: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import urllib.error

    def refused(req: Any, timeout: float) -> Answer:
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)  # type: ignore[arg-type]

    assert cli.main(["link", "ABCD2345"], opener=refused) == 3
    assert "wrong, used or out of time" in capsys.readouterr().out
    assert cli.main(["link", "??"], opener=refused) == 3
    assert "does not look like a link code" in capsys.readouterr().out
    assert not (kit / "data" / "secret.json").exists()


def test_check_and_restore_commands_speak_plainly(
    kit: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parts = _parts(Policy(), Devices(), None)
    assert cli.main(["check"], parts) == 0
    out = capsys.readouterr().out
    assert "ready for calls" in out and "Not linked yet" in out
    assert cli.main(["restore"], parts) == 0
    assert "as you had them" in capsys.readouterr().out
    assert cli.kit_dir() == kit


def test_the_log_never_holds_audio_or_secrets(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    app.setup_logging(cfg)
    try:
        policy, devices = Policy(), Devices()
        jarvis = FakeJarvis(policy, cfg.stop_request)
        asyncio.run(
            asyncio.wait_for(
                app.serve(cfg, _parts(policy, devices, jarvis.connect), stop_poll_s=0.01), 10
            )
        )
    finally:
        import logging

        for handler in logging.getLogger().handlers:
            handler.flush()
    text = cfg.log_file.read_text(encoding="utf-8")
    assert "connected to JARVIS" in text
    assert base64.b64encode(SEED).decode() not in text and "v1;h=" not in text


def test_threads_are_gone_after_the_desk_stops(tmp_path: Path) -> None:
    before = {t.name for t in threading.enumerate()}
    cfg = _cfg(tmp_path)
    policy = Policy()
    jarvis = FakeJarvis(policy, cfg.stop_request)
    asyncio.run(
        asyncio.wait_for(
            app.serve(cfg, _parts(policy, Devices(), jarvis.connect), stop_poll_s=0.01), 10
        )
    )
    after = {t.name for t in threading.enumerate() if t.is_alive()}
    assert not {"calldesk-hearing", "calldesk-speaking"} & (after - before)
