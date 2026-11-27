# src/jarvis/calldesk/app.py
"""The call desk put together (R18 C): the Windows parts, the guard, the checks, the session and
the client, and the commands `python -m jarvis.calldesk` offers.

    run         the desk itself (the watchdog starts it): restores anything a crash left, then
                stays connected to JARVIS until stop-calldesk.ps1 asks it to stop
    supervise   the watchdog (what the Start-menu shortcut and sign-in start)
    restore     puts the owner's microphone and notification sounds back now
    check       the checks before a call, in plain words (the installer's last step)
    link CODE   links the desk to JARVIS with the code the console shows (`link.py`)

The Windows parts are imported only by `windows_parts()`, so everything here is tested on Linux
with fakes.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from jarvis.calldesk.checks import Checker, DeskCheck, probe_audio
from jarvis.calldesk.client import Connector, DeskClient, ws_url
from jarvis.calldesk.config import DeskConfig
from jarvis.calldesk.credentials import CredentialStore
from jarvis.calldesk.micguard import AudioStateFile, MicGuard, Outcome
from jarvis.calldesk.ports import AudioPolicy, Processes, SoundDevices, SystemSounds
from jarvis.calldesk.session import DeskSession
from jarvis.calldesk.sound import CallAudio
from jarvis.calldesk.speech_local import LocalSpeech, NotInstalled
from jarvis.calldesk.watchdog import EXIT_ALREADY_RUNNING, EXIT_OK, Supervisor

log = logging.getLogger(__name__)

STOP_POLL_S = 1.0
LOG_BYTES = 512 * 1024
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class Parts:
    policy: AudioPolicy
    sounds: SystemSounds | None
    devices: SoundDevices
    processes: Processes
    single_instance: Callable[[str], bool]
    connector: Connector


def windows_parts() -> Parts:  # pragma: no cover - Windows only
    from jarvis.calldesk import win, wsconn

    win.init()
    from jarvis.calldesk.win.policy import WinAudioPolicy, WinSystemSounds
    from jarvis.calldesk.win.sound import WinSoundDevices
    from jarvis.calldesk.win.system import WinProcesses, single_instance

    return Parts(
        policy=WinAudioPolicy(),
        sounds=WinSystemSounds(),
        devices=WinSoundDevices(),
        processes=WinProcesses(),
        single_instance=single_instance,
        connector=wsconn.connect,
    )


class _DeskLog(RotatingFileHandler):
    """The desk's own log file handler (one at a time)."""


def setup_logging(cfg: DeskConfig) -> None:
    close_logging()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    handler = _DeskLog(cfg.log_file, maxBytes=LOG_BYTES, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def close_logging() -> None:
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, _DeskLog)]:
        root.removeHandler(handler)
        handler.close()


def guard_for(cfg: DeskConfig, parts: Parts) -> MicGuard:
    return MicGuard(parts.policy, parts.sounds, AudioStateFile(cfg.audio_state))


def checker_for(parts: Parts, guard: MicGuard) -> Checker:
    return Checker(
        parts.policy,
        parts.processes,
        lambda: probe_audio(parts.devices),
        cable_left=guard.cable_left_as_default,
    )


async def _watch_stop(path: Path, stop: asyncio.Event, every_s: float) -> None:
    while not stop.is_set():
        if path.exists():
            log.info("stop requested")
            stop.set()
            return
        await asyncio.sleep(every_s)


async def serve(
    cfg: DeskConfig,
    parts: Parts,
    *,
    local: LocalSpeech | None = None,
    stop: asyncio.Event | None = None,
    stop_poll_s: float = STOP_POLL_S,
) -> int:
    loop = asyncio.get_running_loop()
    guard = guard_for(cfg, parts)
    client = DeskClient(ws_url(cfg.jarvis_url), CredentialStore(cfg.secret).load, parts.connector)
    session = DeskSession(
        client,
        guard,
        checker_for(parts, guard),
        CallAudio(parts.devices, loop),
        local or NotInstalled(),
    )
    stop = stop or asyncio.Event()
    watcher = asyncio.ensure_future(_watch_stop(cfg.stop_request, stop, stop_poll_s))
    try:
        await client.run(session, stop)
    finally:
        watcher.cancel()
        await session.shutdown()
        log.info("call desk stopped; the laptop's audio is as the owner left it")
    return EXIT_OK


def run_desk(cfg: DeskConfig, parts: Parts) -> int:
    if not parts.single_instance("desk"):
        return EXIT_ALREADY_RUNNING
    left = guard_for(cfg, parts).restore_left_over()
    if left is not None:
        log.info("restored the audio a previous run left", extra={"ok": left.ok})
    return asyncio.run(serve(cfg, parts))


def run_watchdog(cfg: DeskConfig, parts: Parts, child: Sequence[str]) -> int:
    if not parts.single_instance("watchdog"):
        return EXIT_ALREADY_RUNNING
    guard = guard_for(cfg, parts)

    def start() -> subprocess.Popen[bytes]:
        flags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
        return subprocess.Popen(list(child), creationflags=flags)

    code = Supervisor(start, guard.restore_left_over, cfg.stop_request.exists).run()
    cfg.stop_request.unlink(missing_ok=True)
    return code


def restore_now(cfg: DeskConfig, parts: Parts) -> Outcome:
    return guard_for(cfg, parts).restore()


def check_now(cfg: DeskConfig, parts: Parts) -> DeskCheck:
    guard = guard_for(cfg, parts)
    return checker_for(parts, guard).run(probe_audio=True)


def child_command() -> list[str]:
    """The desk, isolated (-I: no PYTHON* variables, no user site, not the current folder)."""
    return [sys.executable, "-I", "-m", "jarvis.calldesk", "run"]


__all__ = [
    "Parts",
    "check_now",
    "child_command",
    "close_logging",
    "guard_for",
    "restore_now",
    "run_desk",
    "run_watchdog",
    "serve",
    "setup_logging",
    "windows_parts",
]
