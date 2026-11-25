"""R18 S0 (docs/plans/r18-calls.md, section 10): the laptop test, run by s0.ps1 on Windows.

It proves the audio path the calls feature needs, before anything is built:
  Test A  recording what the laptop's speaker plays hears a Phone Link call;
  Test B  VB-CABLE as the default microphone carries a spoken sentence into the call;
  Test C  (optional) a phone menu reacts to a key tone sent as sound.
It talks to the owner in plain words, sends nothing anywhere, and writes s0-report.txt (device
names and results only). The one short recording of Test A stays in this folder and is deleted
at the end unless the owner keeps it. Console output is the interface here, so it uses print().
"""

from __future__ import annotations

import datetime as dt
import os
import platform
import sys
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np
import s0_logic as lg

HERE = Path(__file__).resolve().parent
RATE = 48000
TEST_A_SECONDS = 15
SWEEP_SECONDS = 4
CALL_CLIP = HERE / "call-hear.wav"
PHRASE = HERE / "phrase.wav"
REPORT = HERE / "s0-report.txt"
LINE = "-" * 72


def say(text: str = "") -> None:
    print(text, flush=True)


def ask(prompt: str, choices: tuple[str, ...]) -> str:
    """Ask until one of `choices` is typed (case ignored); returns it in lower case."""
    allowed = {c.lower() for c in choices}
    while True:
        answer = input(f"{prompt} [{'/'.join(choices)}]: ").strip().lower()
        if answer in allowed:
            return answer
        say(f"Please type one of: {', '.join(choices)}")


def wait(prompt: str = "Press Enter when ready") -> None:
    input(f"{prompt}... ")


def save_wav(path: Path, mono: np.ndarray[Any, Any], rate: int) -> None:
    pcm = (np.clip(mono, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())


def load_wav(path: Path) -> tuple[np.ndarray[Any, Any], int]:
    with wave.open(str(path), "rb") as src:
        if src.getsampwidth() != 2:
            raise ValueError("the test sentence must be 16-bit audio")
        rate = src.getframerate()
        channels = src.getnchannels()
        frames = np.frombuffer(src.readframes(src.getnframes()), dtype="<i2")
    data: np.ndarray[Any, Any] = frames.reshape(-1, channels) if channels > 1 else frames
    return lg.to_mono(data), rate


def record_speaker(sc: Any, speaker: Any, seconds: int) -> np.ndarray[Any, Any]:
    """Record what `speaker` plays (Windows loopback)."""
    mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
    data = mic.record(numframes=RATE * seconds, samplerate=RATE)
    return lg.to_mono(data)


def environment(sc: Any, report: lg.Report) -> None:
    report.windows = f"{platform.system()} {platform.release()} ({platform.version()})"
    report.python = sys.version.split()[0]
    report.speakers = [s.name for s in sc.all_speakers()]
    report.microphones = [m.name for m in sc.all_microphones()]
    report.default_speaker = sc.default_speaker().name
    report.default_microphone = sc.default_microphone().name
    report.cable_found = bool(
        lg.find_device(report.speakers, lg.CABLE_PLAYBACK)
        and lg.find_device(report.microphones, lg.CABLE_RECORDING)
    )
    report.hands_free = [
        n for n in report.speakers + report.microphones if "hands-free" in n.casefold()
    ]


def test_a(sc: Any, report: lg.Report) -> None:
    say(LINE)
    say("TEST A - can JARVIS hear a call?")
    say("1. Make sure the laptop's sound is on and not muted.")
    say("2. In Phone Link on this laptop, call a friend or family member (or your mobile")
    say("   operator's customer care number, whose recorded voice is enough for this test).")
    say("3. When you can hear them talking from the laptop, come back here.")
    wait("Press Enter while you can hear them on the laptop")
    say(f"Listening for {TEST_A_SECONDS} seconds... keep the call going.")
    clip = record_speaker(sc, sc.default_speaker(), TEST_A_SECONDS)
    report.test_a = lg.analyse(clip, RATE)
    save_wav(CALL_CLIP, clip, RATE)
    if report.test_a.heard:
        report.test_a_carrier = sc.default_speaker().name
        say(f"Test A: PASS. {report.test_a.line()}")
        return
    say("Test A: nothing heard on the main speaker. Trying each of the laptop's speakers...")
    for speaker in sc.all_speakers():
        levels = lg.analyse(record_speaker(sc, speaker, SWEEP_SECONDS), RATE)
        if levels.heard:
            report.test_a_carrier = speaker.name
            report.notes.append(f"the call was heard on '{speaker.name}', not the main speaker")
            say(f"  Heard on: {speaker.name}")
            return
    report.notes.append("the call was not heard on any speaker")
    say("  Not heard on any speaker. The report will say so; carry on with Test B.")


def cable_is_default_mic(sc: Any) -> bool:
    return lg.CABLE_RECORDING.casefold() in sc.default_microphone().name.casefold()


def open_recording_settings() -> None:
    os.system("control mmsys.cpl,,1")  # Windows' Sound settings, Recording tab


def test_b(sc: Any, report: lg.Report) -> None:
    say(LINE)
    say("TEST B - can JARVIS speak into the call?  (keep the same call going)")
    say("1. The Sound window opens on its Recording tab.")
    say("2. Right-click 'CABLE Output' -> 'Set as Default Device'.")
    say("3. Right-click 'CABLE Output' again -> 'Set as Default Communication Device'.")
    say("4. Click OK. (Your laptop's own microphone is now off for calls; Test B's end")
    say("   switches it back.)")
    open_recording_settings()
    wait("Press Enter when CABLE Output is the default")
    if not cable_is_default_mic(sc):
        say("CABLE Output is not the default yet. Please repeat steps 2-4.")
        wait("Press Enter when done")
    if not cable_is_default_mic(sc):
        report.notes.append("CABLE Output could not be made the default microphone")
    speaker = sc.get_speaker(lg.CABLE_PLAYBACK)
    sentence, rate = load_wav(PHRASE)
    say("Ask the other person to listen. Playing the test sentence twice...")
    for _ in range(2):
        speaker.play(sentence, samplerate=rate)
        time.sleep(1.0)
    answer = ask(
        "What did they hear? 1 = the sentence clearly, 2 = heard it but unclear, 3 = nothing",
        ("1", "2", "3"),
    )
    report.test_b = {
        "1": "PASS (heard clearly)",
        "2": "PARTLY (heard but unclear)",
        "3": "FAIL (heard nothing)",
    }[answer]


def test_c(sc: Any, report: lg.Report) -> None:
    say(LINE)
    say("TEST C (optional, about 3 minutes) - does a phone menu react to key tones?")
    if ask("Do Test C now?", ("y", "n")) == "n":
        report.test_c = "skipped"
        return
    say("1. End the call with your friend.")
    say("2. In Phone Link, call your mobile operator's customer care number (for example")
    say("   198 or 199 for Jio, 121 for Airtel, 199 for Vi). These calls are free.")
    say("3. When the recorded menu asks you to press a key, type that key here and press")
    say("   Enter. JARVIS plays the key's tone into the call. Type 'done' to stop.")
    speaker = sc.get_speaker(lg.CABLE_PLAYBACK)
    while True:
        key = input("Key to press (0-9, * or #), or 'done': ").strip().lower()
        if key == "done":
            break
        if key not in lg.DTMF_HZ:
            say("Please type one key: 0-9, * or #.")
            continue
        speaker.play(lg.dtmf_tone(key, RATE), samplerate=RATE)
    answer = ask(
        "Did the menu move on after the tones? y = yes, n = no, u = not sure", ("y", "n", "u")
    )
    report.test_c = {
        "y": "PASS (the menu reacted)",
        "n": "FAIL (no reaction)",
        "u": "unclear",
    }[answer]


def restore_microphone(sc: Any, report: lg.Report) -> None:
    say(LINE)
    say("SWITCH YOUR MICROPHONE BACK (important)")
    say("1. End any call that is still on.")
    say("2. In the Sound window's Recording tab, right-click your usual microphone ->")
    say("   'Set as Default Device', then -> 'Set as Default Communication Device'. OK.")
    open_recording_settings()
    wait("Press Enter when your usual microphone is the default again")
    if cable_is_default_mic(sc):
        report.mic_restored = "NO - CABLE Output is still the default microphone"
        say("CABLE Output is still the default microphone. Please switch it back as above,")
        say("or your calls and meetings will not hear you.")
    else:
        report.mic_restored = "yes"


def finish(report: lg.Report) -> None:
    text = report.text(dt.datetime.now().strftime("%d %b %Y, %H:%M"))
    REPORT.write_text(text + "\n", encoding="utf-8")
    say(LINE)
    say("Copy everything between the two lines below and paste it into the chat with Claude.")
    say("=" * 72)
    say(text)
    say("=" * 72)
    say(f"(Also saved as {REPORT})")
    if CALL_CLIP.exists():
        keep = ask(
            "Keep the 15-second recording from Test A on this laptop? It is never sent anywhere",
            ("y", "n"),
        )
        if keep == "n":
            CALL_CLIP.unlink()
            say("Deleted.")


def main() -> int:
    if platform.system() != "Windows":
        say("This test runs on Windows only.")
        return 2
    import soundcard as sc  # Windows audio (WASAPI); imported here so tests can import this file

    report = lg.Report()
    say("JARVIS calls - laptop test (S0). Nothing is sent anywhere and nothing is spent.")
    environment(sc, report)
    if not report.cable_found:
        say("VB-CABLE is not installed yet. Please do step 2 of README.txt, restart the laptop,")
        say("and run this test again.")
        report.notes.append("stopped: VB-CABLE missing")
        finish(report)
        return 1
    try:
        test_a(sc, report)
        test_b(sc, report)
        test_c(sc, report)
    except KeyboardInterrupt:
        report.notes.append("stopped early by the owner")
    except Exception as exc:  # noqa: BLE001 - the owner pastes this back; it must not be lost
        report.notes.append(f"error: {type(exc).__name__}: {exc}")
        say(f"Something went wrong: {type(exc).__name__}: {exc}")
    finally:
        restore_microphone(sc, report)
        finish(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
