"""R18 C: the desk's message handling (the "Desk <-> cloud" contract) with fake Windows parts.

Pinned here: prepare checks first and never switches the microphone when the laptop isn't ready;
a failed switch leaves his microphone; audio goes out only while the other person speaks;
barge-in cuts JARVIS at once; takeover gives his microphone back and keeps the recording; release
restores everything; a lost link or an overlong call restores without the cloud.
"""

from __future__ import annotations

import asyncio
import math
import struct
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from jarvis.calldesk import DESK_VERSION, checks, dtmf
from jarvis.calldesk.micguard import Outcome
from jarvis.calldesk.session import AUDIO_FAILED, LAPTOP_SPEECH_OFF, DeskSession
from jarvis.calldesk.speech_local import LocalHeard, LocalStatus, NotInstalled
from jarvis.calls import protocol as p

CALL = "call_0000000000a1"
OTHER = "call_0000000000b2"
GOOD = checks.DeskCheck(True, (), False, True, True, True)
FRAME = p.FRAME_BYTES


def _speech_frames(ms: int, level: float = 0.3) -> list[bytes]:
    n = 16 * ms
    vals = [
        int(
            32767
            * level
            * 0.5
            * sum(math.sin(2 * math.pi * 140 * k * i / 16000) / k for k in (1, 2, 3))
        )
        for i in range(n)
    ]
    return p.split_frames(struct.pack(f"<{n}h", *vals))


SILENCE = b"\x00" * FRAME


class Out:
    def __init__(self) -> None:
        self.msgs: list[Any] = []
        self.audio: list[bytes] = []

    def send(self, msg: Any) -> None:
        self.msgs.append(msg)

    def send_audio(self, message: bytes) -> None:
        self.audio.append(message)

    def of(self, cls: type) -> list[Any]:
        return [m for m in self.msgs if isinstance(m, cls)]

    def types(self) -> list[str]:
        return [m.type for m in self.msgs]


class Guard:
    def __init__(self) -> None:
        self.on_cable = False
        self.sounds_off = False
        self.switch_ok = True
        self.restore_ok = True
        self.log: list[str] = []

    def switch_to_cable(self, call_id: str) -> Outcome:
        self.log.append("switch")
        if not self.switch_ok:
            return Outcome(False, ("Windows did not make CABLE Output the microphone.",))
        self.on_cable = True
        return Outcome(True, changed=True)

    def restore(self, *, sounds: bool = True) -> Outcome:
        self.log.append("restore" if sounds else "restore_mic")
        if not self.restore_ok:
            return Outcome(False, ("Your microphone could not be switched back.",))
        self.on_cable = False
        if sounds:
            self.sounds_off = False
        return Outcome(True, changed=True)

    def mute_sounds(self) -> bool:
        self.sounds_off = True
        return True


class Checks:
    def __init__(self, result: checks.DeskCheck = GOOD) -> None:
        self.result = result
        self.probes: list[bool] = []

    def run(self, *, probe_audio: bool = True) -> checks.DeskCheck:
        self.probes.append(probe_audio)
        return self.result


class Audio:
    def __init__(self) -> None:
        self.started = False
        self.speaking_on = False
        self.played: list[bytes] = []
        self.marks: list[str] = []
        self.cuts = 0
        self.fail_start = False
        self.on_frame: Callable[[bytes], None] | None = None
        self.on_marker: Callable[[str], None] | None = None
        self.on_error: Callable[[str], None] | None = None

    def start(
        self,
        on_frame: Callable[[bytes], None],
        on_marker: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        if self.fail_start:
            raise RuntimeError("CABLE Input busy")
        self.started = self.speaking_on = True
        self.on_frame, self.on_marker, self.on_error = on_frame, on_marker, on_error

    def stop(self) -> None:
        self.started = self.speaking_on = False

    def stop_speaking(self) -> None:
        self.speaking_on = False

    def play(self, pcm: bytes) -> bool:
        self.played.append(pcm)
        return True

    def mark(self, token: str) -> None:
        self.marks.append(token)

    def cut(self) -> bool:
        was = bool(self.played)
        self.played.clear()
        self.cuts += 1
        return was

    @property
    def busy(self) -> bool:
        return bool(self.played)

    def finish_playing(self) -> None:
        self.played.clear()
        for token in self.marks:
            assert self.on_marker is not None
            self.on_marker(token)
        self.marks.clear()

    def feed(self, frames: Sequence[bytes]) -> None:
        assert self.on_frame is not None
        for f in frames:
            self.on_frame(f)


class Laptop:
    def status(self) -> LocalStatus:
        return LocalStatus(True, ("en-IN", "hi-IN"))

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> LocalHeard:
        return LocalHeard("hi-IN", f"heard {len(pcm16k)} bytes", 1.7)

    async def speak(self, text: str, lang: str) -> bytes:
        return b"\x01\x00" * 500


async def _direct(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


class Rig:
    def __init__(self, check: checks.DeskCheck = GOOD, local: Any = None, **kw: Any) -> None:
        self.out, self.guard, self.checks, self.audio = Out(), Guard(), Checks(check), Audio()
        self.session = DeskSession(
            self.out,
            self.guard,
            self.checks,
            self.audio,
            local or NotInstalled(),
            blocking=_direct,
            **kw,
        )

    async def prepare(self, mode: str = "cloud", call_id: str = CALL) -> None:
        await self.session.handle(
            p.parse_cloud_to_desk(
                {"type": "prepare", "call_id": call_id, "mode": mode, "languages": ["en-IN"]}
            )
        )

    async def send(self, raw: dict[str, Any]) -> None:
        await self.session.handle(p.parse_cloud_to_desk(raw))


@pytest.fixture
def rig() -> Rig:
    return Rig()


async def test_hello_then_a_probed_state_on_connect(rig: Rig) -> None:
    await rig.session.connected()
    hello, state = rig.out.msgs
    assert isinstance(hello, p.Hello) and hello.desk_version == DESK_VERSION
    assert [m.value for m in hello.speech_modes] == ["cloud"] and hello.local_languages == ()
    assert isinstance(state, p.DeskState) and state.ready and rig.checks.probes == [True]
    for msg in rig.out.msgs:  # every message we send is one the cloud's parser accepts
        assert p.parse_desk(p.dump(msg)) == msg


async def test_ping_answers_with_the_cached_state(rig: Rig) -> None:
    await rig.session.connected()
    await rig.send({"type": "ping"})
    assert rig.out.types()[-1] == "state" and rig.checks.probes == [True]


async def test_prepare_switches_mutes_and_listens(rig: Rig) -> None:
    await rig.prepare()
    assert rig.guard.on_cable and rig.guard.sounds_off and rig.audio.started
    assert rig.out.types() == ["state", "mic"]
    assert rig.out.msgs[-1] == p.Mic(call_id=CALL, owner_mic=False)
    assert rig.checks.probes == [True]  # the audio path is proved before every call


async def test_not_ready_means_no_switch_and_an_error() -> None:
    bad = checks.DeskCheck(False, (checks.BT_HEADSET,), True, True, True, True)
    rig = Rig(bad)
    await rig.prepare()
    assert rig.guard.log == [] and not rig.audio.started
    state, error = rig.out.msgs
    assert isinstance(state, p.DeskState) and not state.ready and state.bt_headset
    assert isinstance(error, p.DeskError) and error.code == "not_ready" and error.call_id == CALL
    assert error.message == checks.BT_HEADSET[:200]


async def test_a_failed_switch_keeps_his_microphone_and_reports_it(rig: Rig) -> None:
    rig.guard.switch_ok = False
    await rig.prepare()
    assert not rig.guard.on_cable and not rig.audio.started
    state = rig.out.of(p.DeskState)[-1]
    assert not state.ready and any("CABLE Output" in x for x in state.problems)
    assert rig.out.of(p.DeskError)[-1].code == "mic_switch_failed"


async def test_audio_that_cannot_start_restores_everything(rig: Rig) -> None:
    rig.audio.fail_start = True
    await rig.prepare()
    assert not rig.guard.on_cable and rig.guard.log == ["switch", "restore"]
    assert rig.out.of(p.DeskError)[-1].code == "audio_failed"
    assert rig.session.call_id is None


async def test_an_unexpected_failure_after_the_switch_restores_everything(rig: Rig) -> None:
    def broken() -> bool:
        raise AttributeError("a COM wrapper changed")

    rig.guard.mute_sounds = broken  # type: ignore[method-assign]
    await rig.prepare()
    assert not rig.guard.on_cable and rig.session.call_id is None
    assert rig.out.of(p.DeskError)[-1].code == "audio_failed"


async def test_laptop_mode_without_laptop_speech_is_refused(rig: Rig) -> None:
    await rig.prepare(mode="laptop")
    assert rig.guard.log == []
    assert LAPTOP_SPEECH_OFF in rig.out.of(p.DeskState)[-1].problems
    assert rig.out.of(p.DeskError)[-1].code == "laptop_speech_not_installed"


async def test_a_second_call_is_refused_and_the_same_one_is_answered_again(rig: Rig) -> None:
    await rig.prepare()
    await rig.prepare(call_id=OTHER)
    assert rig.out.of(p.DeskError)[-1].code == "desk_busy" and rig.guard.log == ["switch"]
    await rig.prepare()
    assert rig.out.msgs[-1] == p.Mic(call_id=CALL, owner_mic=False) and rig.guard.log == ["switch"]


async def test_only_their_speech_is_sent(rig: Rig) -> None:
    await rig.prepare()
    rig.out.msgs.clear()
    rig.audio.feed([SILENCE] * 50)
    assert rig.out.audio == [] and rig.out.msgs == []
    rig.audio.feed(_speech_frames(400))
    rig.audio.feed([SILENCE] * 30)
    assert [m.speaking for m in rig.out.of(p.Vad)] == [True, False]
    frames = [f for m in rig.out.audio for f in p.split_frames(p.unpack_audio(m)[1])]
    assert all(p.unpack_audio(m)[0] is p.AudioKind.THEM for m in rig.out.audio)
    assert 20 <= len(frames) <= 20 + 10 + 20  # their turn, its pre-roll and its hangover


async def test_jarvis_voice_is_played_and_barge_in_cuts_it(rig: Rig) -> None:
    await rig.prepare()
    rig.session.jarvis_audio(b"\x01" * FRAME * 10)
    assert rig.audio.busy
    rig.audio.feed([SILENCE] * 20 + _speech_frames(300))
    assert rig.audio.cuts == 1 and not rig.audio.busy
    assert rig.out.of(p.Vad)[0].speaking is True


async def test_stop_speaking_cuts_playback(rig: Rig) -> None:
    await rig.prepare()
    rig.session.jarvis_audio(b"\x01" * FRAME)
    await rig.send({"type": "stop_speaking", "call_id": CALL})
    assert rig.audio.cuts == 1 and not rig.audio.busy
    await rig.send({"type": "stop_speaking", "call_id": OTHER})  # not this call: ignored
    assert rig.audio.cuts == 1


async def test_dtmf_plays_the_tone_then_reports_it(rig: Rig) -> None:
    await rig.prepare()
    await rig.send({"type": "dtmf", "call_id": CALL, "digit": "#"})
    assert rig.audio.played == [dtmf.tone("#")]
    assert rig.out.of(p.DtmfDone) == []
    rig.audio.finish_playing()
    assert rig.out.of(p.DtmfDone) == [p.DtmfDone(call_id=CALL, digit="#")]


async def test_takeover_gives_his_microphone_back_and_keeps_listening(rig: Rig) -> None:
    await rig.prepare()
    rig.session.jarvis_audio(b"\x01" * FRAME)
    await rig.send({"type": "takeover", "call_id": CALL})
    assert rig.guard.log[-1] == "restore_mic" and not rig.guard.on_cable and rig.guard.sounds_off
    assert rig.out.msgs[-1] == p.Mic(call_id=CALL, owner_mic=True)
    assert rig.audio.started and not rig.audio.speaking_on
    rig.session.jarvis_audio(b"\x01" * FRAME)  # JARVIS stays quiet after a takeover
    assert rig.audio.played == []
    await rig.send({"type": "dtmf", "call_id": CALL, "digit": "1"})
    assert rig.audio.played == []
    rig.audio.feed(_speech_frames(300) + [SILENCE] * 30)
    assert rig.out.audio  # the recording carries on


async def test_takeover_that_cannot_restore_says_so(rig: Rig) -> None:
    await rig.prepare()
    rig.guard.restore_ok = False
    await rig.send({"type": "takeover", "call_id": CALL})
    assert p.Mic(call_id=CALL, owner_mic=False) in rig.out.msgs
    assert rig.out.of(p.DeskError)[-1].code == "mic_restore_failed"


async def test_release_restores_everything(rig: Rig) -> None:
    await rig.prepare()
    await rig.send({"type": "release", "call_id": CALL})
    assert not rig.guard.on_cable and not rig.guard.sounds_off and not rig.audio.started
    assert rig.out.types()[-2:] == ["mic", "state"]
    assert rig.out.msgs[-2] == p.Mic(call_id=CALL, owner_mic=True)
    assert rig.session.call_id is None
    rig.session.jarvis_audio(b"\x01" * FRAME)
    assert rig.audio.played == []


async def test_a_late_release_for_another_call_changes_nothing(rig: Rig) -> None:
    await rig.prepare()
    await rig.send({"type": "release", "call_id": OTHER})
    assert rig.guard.on_cable and rig.session.call_id == CALL


async def test_an_audio_failure_mid_call_is_reported(rig: Rig) -> None:
    await rig.prepare()
    assert rig.audio.on_error is not None
    rig.audio.on_error("device went away")
    assert rig.out.of(p.DeskError)[-1].code == "audio_failed"
    assert AUDIO_FAILED in rig.out.of(p.DeskState)[-1].problems


async def test_a_lost_link_releases_after_the_grace() -> None:
    rig = Rig(grace_s=0.01)
    await rig.prepare()
    rig.session.disconnected()
    await asyncio.sleep(0.05)
    assert not rig.guard.on_cable and rig.session.call_id is None


async def test_a_quick_reconnect_keeps_the_call_and_resyncs(rig: Rig) -> None:
    await rig.prepare()
    rig.session.disconnected()
    rig.out.msgs.clear()
    await rig.session.connected()
    await asyncio.sleep(0)
    assert rig.guard.on_cable and rig.session.call_id == CALL
    assert rig.out.types() == ["hello", "state", "mic"]
    assert rig.checks.probes == [True]  # no new probe mid-call


async def test_an_overlong_call_is_released_by_the_desk() -> None:
    rig = Rig(max_call_s=0.01)
    await rig.prepare()
    await asyncio.sleep(0.05)
    assert not rig.guard.on_cable and rig.session.call_id is None
    assert p.Mic(call_id=CALL, owner_mic=True) in rig.out.msgs


async def test_shutdown_restores_with_or_without_a_call(rig: Rig) -> None:
    await rig.session.shutdown()
    assert rig.guard.log == ["restore"]
    await rig.prepare()
    await rig.session.shutdown()
    assert not rig.guard.on_cable and rig.session.call_id is None


async def test_light_check_sends_only_changes(rig: Rig) -> None:
    await rig.session.light_check()
    await rig.session.light_check()
    assert rig.out.types() == ["state"]
    rig.checks.result = checks.DeskCheck(False, (checks.NO_PHONE_LINK,), False, True, False, True)
    await rig.session.light_check()
    assert rig.out.types() == ["state", "state"] and rig.checks.probes == [False] * 3


async def test_laptop_mode_hears_and_speaks_on_the_laptop() -> None:
    rig = Rig(local=Laptop())
    await rig.session.connected()
    hello = rig.out.of(p.Hello)[0]
    assert [m.value for m in hello.speech_modes] == ["cloud", "laptop"]
    await rig.prepare(mode="laptop")
    rig.audio.feed(_speech_frames(400) + [SILENCE] * 30)
    await rig.session.settle()
    assert rig.out.audio == []  # no audio leaves the laptop in laptop mode
    heard = rig.out.of(p.HeardText)[-1]
    assert heard.lang == "hi-IN" and heard.confidence == 1.0 and heard.call_id == CALL
    await rig.send(
        {
            "type": "say_text",
            "call_id": CALL,
            "utterance_id": "u1",
            "lang": "hi-IN",
            "text": "Namaste",
        }
    )
    await rig.session.settle()
    assert rig.audio.played == [b"\x01\x00" * 500]
    rig.audio.finish_playing()
    assert rig.out.of(p.Played) == [p.Played(call_id=CALL, utterance_id="u1")]


async def test_say_text_in_cloud_mode_is_an_error(rig: Rig) -> None:
    await rig.prepare()
    await rig.send(
        {"type": "say_text", "call_id": CALL, "utterance_id": "u1", "lang": "en-IN", "text": "Hi"}
    )
    assert rig.out.of(p.DeskError)[-1].code == "wrong_mode"


async def test_every_problem_fits_the_contract() -> None:
    long = checks.DeskCheck(False, tuple("x" * 300 for _ in range(15)), False, False, False, False)
    rig = Rig(long)
    await rig.prepare()
    state = rig.out.of(p.DeskState)[-1]
    assert len(state.problems) == 10 and all(len(x) == 200 for x in state.problems)
    for msg in rig.out.msgs:
        assert p.parse_desk(p.dump(msg)) == msg
