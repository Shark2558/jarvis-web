# src/jarvis/calldesk/watchdog.py
"""The watchdog (plan section 8: "the call desk restores your audio devices on exit, on a crash
(a watchdog) and at the next start").

`python -m jarvis.calldesk supervise` runs the desk as a child process and waits for it. Whenever
the child ends, for any reason (a Python error, a crash in a sound driver, Task Manager), the
watchdog restores the owner's microphone and notification sounds from `audio-state.json` before
anything else, then starts the desk again after a pause that grows while it keeps failing (2, 5,
15, 30, 60 s; back to 2 s after five quiet minutes). A stop request (`stop.request`, written by
stop-calldesk.ps1) or a final exit code (not linked, already running) ends it. A reboot or a
killed watchdog is covered by the restore at the desk's next start.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CONFIG = 2  # the kit is incomplete or its settings are wrong: restarting won't help
EXIT_NOT_LINKED = 3
EXIT_ALREADY_RUNNING = 4
FINAL_CODES = frozenset({EXIT_CONFIG, EXIT_NOT_LINKED, EXIT_ALREADY_RUNNING})
RESTART_DELAYS_S = (2.0, 5.0, 15.0, 30.0, 60.0)
STABLE_S = 300.0
_POLL_S = 1.0


class Child(Protocol):
    def wait(self) -> int: ...


@dataclass
class Supervisor:
    start_child: Callable[[], Child]
    restore: Callable[[], object]
    stop_requested: Callable[[], bool]
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def run(self) -> int:
        self._restore()  # a reboot or a killed watchdog may have left the cable in place
        failures = 0
        while not self.stop_requested():
            started = self.clock()
            try:
                code = self.start_child().wait()
            except OSError:
                log.warning("the call desk could not be started")
                code = -1
            self._restore()
            if self.stop_requested() or code == EXIT_OK:
                return EXIT_OK
            if code in FINAL_CODES:
                return code
            failures = 1 if self.clock() - started >= STABLE_S else failures + 1
            delay = RESTART_DELAYS_S[min(failures, len(RESTART_DELAYS_S)) - 1]
            log.warning("the call desk stopped; starting it again", extra={"in_s": delay})
            if self._pause(delay):
                return EXIT_OK
        return EXIT_OK

    def _restore(self) -> None:
        try:
            self.restore()
        except Exception:  # noqa: BLE001 - the watchdog must outlive any restore failure
            log.exception("restoring the audio devices failed")

    def _pause(self, seconds: float) -> bool:
        """Sleep, waking each second for a stop request (True: stop)."""
        end = self.clock() + seconds
        while self.clock() < end:
            if self.stop_requested():
                return True
            self.sleep(min(_POLL_S, max(0.0, end - self.clock())))
        return self.stop_requested()


__all__ = [
    "EXIT_ALREADY_RUNNING",
    "EXIT_CONFIG",
    "EXIT_NOT_LINKED",
    "EXIT_OK",
    "FINAL_CODES",
    "RESTART_DELAYS_S",
    "STABLE_S",
    "Supervisor",
]
