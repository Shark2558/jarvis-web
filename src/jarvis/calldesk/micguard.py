# src/jarvis/calldesk/micguard.py
"""The default-microphone switch and its restore (R18 build brief "Speaking"; plan section 8).

For a JARVIS call only, VB-CABLE's "CABLE Output" becomes Windows' default microphone in all three
roles (console and multimedia, which Sound settings calls "Default Device", and communications,
"Default Communication Device"), so Phone Link sends JARVIS's voice into the call. The owner is
never left without his microphone:

- the previous default of each role is written to `audio-state.json` BEFORE anything changes; if
  that file can't be written, nothing is switched;
- after switching, each role is read back; a switch Windows doesn't confirm is undone at once;
- `restore` puts back only roles that still point at the cable (a role he changed himself during
  the call is left alone), falls back to another microphone when the saved one is gone, and keeps
  the state file when it fails, so the next try (the watchdog, the next start) can finish;
- an unreadable state file means "switched, originals unknown": any role on the cable goes back to
  his best microphone. No state file means hands off: a cable he chose himself is only reported.

Notification sounds (the default speaker's "System sounds" session) are muted for the call when
possible, so they don't reach the loopback recording, and unmuted on release, never if he had
muted them himself. Windows' Focus assist / Do not disturb has no public API to switch it from a
program (only the undocumented WNF state, which changes between builds), so the desk does not
touch it; banners without sound don't reach the recording.

The state file holds device ids (Windows' endpoint ids, not names) and flags only.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from jarvis.calldesk.ports import ROLES, AudioPolicy, Endpoint, PolicyError, Role, SystemSounds

log = logging.getLogger(__name__)

CABLE_MIC = "CABLE Output"  # VB-CABLE's recording side: Phone Link sends it into the call
STATE_VERSION = 1

NO_CABLE = (
    "VB-CABLE's microphone (CABLE Output) is missing: install VB-CABLE (README step 2) and "
    "restart the laptop."
)
NOT_SAVED = "The call desk could not save your microphone settings, so it did not switch them."
NOT_SWITCHED = (
    "Windows did not make CABLE Output the microphone for calls; your own microphone is kept."
)
NOT_RESTORED = (
    "Your microphone could not be switched back. Open Settings > System > Sound > Input and "
    "choose your microphone; the call desk will try again when it next starts."
)
NO_OTHER_MIC = "No microphone other than CABLE Output was found to switch back to."
SOUNDS_NOT_RESTORED = "Notification sounds could not be switched back on (Volume mixer)."
CABLE_LEFT = (
    "CABLE Output is your default microphone, and the call desk did not set it: choose your own "
    "microphone in Settings > System > Sound > Input."
)


@dataclass(frozen=True)
class SavedAudio:
    """What the desk changed and what it must put back."""

    cable_id: str
    previous: Mapping[Role, str] = field(default_factory=dict)
    mic_switched: bool = True
    sounds_muted_by_desk: bool = False
    call_id: str | None = None
    at: float = 0.0

    @property
    def pending(self) -> bool:
        return self.mic_switched or self.sounds_muted_by_desk


UNKNOWN = SavedAudio(cable_id="", previous={}, mic_switched=True)


@dataclass(frozen=True)
class Outcome:
    ok: bool
    problems: tuple[str, ...] = ()
    changed: bool = False


class AudioStateFile:
    """`audio-state.json`, written atomically. `load` returns None when there is no file and
    `UNKNOWN` when there is one it can't read (fail safe: restore what sits on the cable)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> SavedAudio | None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return UNKNOWN
        try:
            return _parse(json.loads(text))
        except (ValueError, KeyError, TypeError):
            log.warning("the audio state file was unreadable; restoring from what Windows shows")
            return UNKNOWN

    def save(self, state: SavedAudio) -> None:
        """Raises OSError when it can't be written."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "v": STATE_VERSION,
            "cable_id": state.cable_id,
            "previous": dict(state.previous),
            "mic_switched": state.mic_switched,
            "sounds_muted_by_desk": state.sounds_muted_by_desk,
            "call_id": state.call_id,
            "at": state.at,
        }
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def _parse(raw: object) -> SavedAudio:
    if not isinstance(raw, dict) or raw.get("v") != STATE_VERSION:
        raise ValueError("unknown audio state")
    previous = raw["previous"]
    if not isinstance(previous, dict):
        raise TypeError("previous")
    roles: dict[Role, str] = {
        r: str(previous[r]) for r in ROLES if isinstance(previous.get(r), str)
    }
    call_id = raw.get("call_id")
    return SavedAudio(
        cable_id=str(raw["cable_id"]),
        previous=roles,
        mic_switched=bool(raw["mic_switched"]),
        sounds_muted_by_desk=bool(raw["sounds_muted_by_desk"]),
        call_id=call_id if isinstance(call_id, str) else None,
        at=float(raw.get("at", 0.0)),
    )


class MicGuard:
    def __init__(
        self,
        policy: AudioPolicy,
        sounds: SystemSounds | None,
        store: AudioStateFile,
        *,
        clock: Callable[[], float] = time.time,
        cable_name: str = CABLE_MIC,
    ) -> None:
        self._policy = policy
        self._sounds = sounds
        self._store = store
        self._clock = clock
        self._cable_name = cable_name.casefold()

    # ---- what Windows has ----------------------------------------------------------------------

    def _captures(self) -> Sequence[Endpoint]:
        return self._policy.endpoints("capture")

    def _is_cable(self, endpoint: Endpoint) -> bool:
        return self._cable_name in endpoint.name.casefold()

    def cable(self) -> Endpoint | None:
        return next((e for e in self._captures() if self._is_cable(e)), None)

    def _owner_mics(self) -> list[Endpoint]:
        mics = [e for e in self._captures() if not self._is_cable(e)]
        return sorted(mics, key=lambda e: e.bluetooth)  # the laptop's own before Bluetooth ones

    def _defaults(self) -> dict[Role, str | None]:
        return {role: self._policy.default_id("capture", role) for role in ROLES}

    def cable_left_as_default(self) -> bool:
        """The cable is a default microphone although the desk has nothing to restore."""
        if self._store.load() is not None:
            return False
        cable = self.cable()
        return cable is not None and cable.id in self._defaults().values()

    # ---- switching -----------------------------------------------------------------------------

    def switch_to_cable(self, call_id: str) -> Outcome:
        try:
            cable = self.cable()
            if cable is None:
                return Outcome(False, (NO_CABLE,))
            earlier = self._store.load()
            previous = self._previous(cable, earlier)
        except PolicyError:
            log.warning("reading the audio devices failed")
            return Outcome(False, (NOT_SWITCHED,))
        state = SavedAudio(
            cable_id=cable.id,
            previous=previous,
            mic_switched=True,
            sounds_muted_by_desk=earlier.sounds_muted_by_desk if earlier else False,
            call_id=call_id,
            at=self._clock(),
        )
        try:
            self._store.save(state)
        except OSError:
            log.warning("the audio state file could not be written; nothing switched")
            return Outcome(False, (NOT_SAVED,))
        if self._set_all(cable.id) and self._all_point_at({cable.id}):
            log.info("the default microphone is CABLE Output for this call")
            return Outcome(True, (), changed=True)
        log.warning("Windows did not confirm the microphone switch; undoing it")
        undo = self.restore(sounds=False)
        return Outcome(False, (NOT_SWITCHED, *undo.problems), changed=undo.changed)

    def _previous(self, cable: Endpoint, earlier: SavedAudio | None) -> dict[Role, str]:
        if earlier is not None and earlier.mic_switched and earlier.previous:
            return dict(earlier.previous)  # switched already: keep the true originals
        fallback = next(iter(self._owner_mics()), None)
        previous: dict[Role, str] = {}
        for role, current in self._defaults().items():
            if current is not None and current != cable.id:
                previous[role] = current
            elif fallback is not None:
                previous[role] = fallback.id
        return previous

    def _set_all(self, device_id: str) -> bool:
        ok = True
        for role in ROLES:
            try:
                self._policy.set_default(device_id, role)
            except PolicyError:
                log.warning("setting a default microphone role failed", extra={"role": role})
                ok = False
        return ok

    def _all_point_at(self, ids: set[str]) -> bool:
        try:
            return all(current in ids for current in self._defaults().values())
        except PolicyError:
            return False

    # ---- restoring -----------------------------------------------------------------------------

    def restore_left_over(self) -> Outcome | None:
        """At start and from the watchdog: finish a restore a crash interrupted (None: nothing)."""
        saved = self._store.load()
        if saved is None:
            return None
        return self.restore()

    def restore(self, *, sounds: bool = True) -> Outcome:
        """His microphone back (and the notification sounds, unless `sounds` is False: a takeover
        keeps them off while the recording runs on)."""
        saved = self._store.load()
        if saved is None:
            return Outcome(True)
        problems: list[str] = []
        changed = False
        mic_done = not saved.mic_switched
        if saved.mic_switched:
            mic_done, changed, mic_problems = self._restore_mic(saved)
            problems += mic_problems
        sounds_done = not saved.sounds_muted_by_desk
        if sounds and saved.sounds_muted_by_desk:
            sounds_done = self._unmute()
            changed = changed or sounds_done
            if not sounds_done:
                problems.append(SOUNDS_NOT_RESTORED)
        self._remember(saved, mic_done=mic_done, sounds_done=sounds_done)
        return Outcome(mic_done and (sounds_done or not sounds), tuple(problems), changed)

    def _restore_mic(self, saved: SavedAudio) -> tuple[bool, bool, list[str]]:
        try:
            captures = self._captures()
            cable_ids = {e.id for e in captures if self._is_cable(e)}
            if saved.cable_id:
                cable_ids.add(saved.cable_id)
            mics = self._owner_mics()
            defaults = self._defaults()
        except PolicyError:
            log.warning("reading the audio devices failed during a restore")
            return False, False, [NOT_RESTORED]
        if not mics:
            return False, False, [NO_OTHER_MIC]
        live = {e.id for e in mics}
        changed = False
        for role, current in defaults.items():
            if current is not None and current not in cable_ids:
                continue  # already his (or he chose another one himself)
            target = self._target(saved, role, live, mics)
            try:
                self._policy.set_default(target, role)
                changed = True
            except PolicyError:
                log.warning("restoring a default microphone role failed", extra={"role": role})
        try:
            after = self._defaults()
        except PolicyError:
            return False, changed, [NOT_RESTORED]
        if any(current is None or current in cable_ids for current in after.values()):
            return False, changed, [NOT_RESTORED]
        log.info("the owner's microphone is back")
        return True, changed, []

    @staticmethod
    def _target(saved: SavedAudio, role: Role, live: set[str], mics: list[Endpoint]) -> str:
        wanted = saved.previous.get(role)
        if wanted in live:
            return str(wanted)
        for other in (saved.previous.get(r) for r in ROLES):
            if other in live:
                return str(other)
        return mics[0].id

    def _remember(self, saved: SavedAudio, *, mic_done: bool, sounds_done: bool) -> None:
        self._write(
            replace(
                saved,
                mic_switched=saved.mic_switched and not mic_done,
                sounds_muted_by_desk=saved.sounds_muted_by_desk and not sounds_done,
            )
        )

    def _write(self, state: SavedAudio) -> None:
        try:
            if state.pending:
                self._store.save(state)
            else:
                self._store.clear()
        except OSError:
            log.warning("the audio state file could not be updated")

    # ---- notification sounds -------------------------------------------------------------------

    def mute_sounds(self) -> bool:
        """Mute the "System sounds" session for the call. True when they are off now."""
        if self._sounds is None:
            return False
        try:
            current = self._sounds.muted()
        except PolicyError:
            return False
        if current is None:
            return False
        if current:
            return True  # he muted them himself: never unmuted by the desk
        saved = self._store.load() or SavedAudio(cable_id="", mic_switched=False)
        try:
            self._store.save(replace(saved, sounds_muted_by_desk=True))
        except OSError:
            return False
        try:
            self._sounds.set_muted(True)
            if self._sounds.muted():
                return True
        except PolicyError:
            pass
        log.warning("notification sounds could not be muted")
        self._write(replace(saved, sounds_muted_by_desk=False))
        return False

    def _unmute(self) -> bool:
        if self._sounds is None:
            return False
        try:
            self._sounds.set_muted(False)
            return self._sounds.muted() is False
        except PolicyError:
            return False


__all__ = [
    "CABLE_MIC",
    "UNKNOWN",
    "AudioStateFile",
    "MicGuard",
    "Outcome",
    "SavedAudio",
]
