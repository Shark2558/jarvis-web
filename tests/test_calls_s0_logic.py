"""R18 S0 (docs/plans/r18-calls.md, section 10): the laptop test's pure helpers.

The test itself runs only on the owner's Windows laptop; these cases pin the judgments it makes
(heard or not, narrowband or wideband, the key tones, the report) before he runs it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "deploy" / "calls-s0"
RATE = 48000


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, KIT / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lg = _load("s0_logic")


def _noise(seconds: float, level: float, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(RATE * seconds)) * level).astype(np.float32)


def _speechlike(seconds: float, freqs: tuple[float, ...], on_share: float = 0.6) -> np.ndarray:
    """Bursts of tones (speech-like on and off) over faint noise."""
    t = np.arange(int(RATE * seconds)) / RATE
    signal = sum(0.2 * np.sin(2 * np.pi * f * t) for f in freqs)
    gate = ((t % 1.0) < on_share).astype(np.float64)
    return (signal * gate).astype(np.float32) + _noise(seconds, 0.0005)


def test_silence_is_not_heard() -> None:
    levels = lg.analyse(np.zeros(RATE * 2, dtype=np.float32), RATE)
    assert not levels.heard
    assert levels.active_fraction == 0.0
    assert levels.band == "unknown (nothing heard)"


def test_faint_hiss_is_not_heard() -> None:
    assert not lg.analyse(_noise(3, 0.001), RATE).heard


def test_speechlike_bursts_are_heard() -> None:
    levels = lg.analyse(_speechlike(4, (300.0, 1200.0, 2500.0)), RATE)
    assert levels.heard
    assert 0.4 < levels.active_fraction < 0.8
    assert levels.peak_dbfs > -20


def test_quiet_bursts_below_the_peak_bar_are_not_heard() -> None:
    quiet = _speechlike(3, (500.0,)) * 0.002
    assert not lg.analyse(quiet, RATE).heard


def test_narrowband_call_is_recognised() -> None:
    levels = lg.analyse(_speechlike(3, (400.0, 1500.0, 3200.0)), RATE)
    assert levels.band.startswith("narrowband")


def test_wideband_call_is_recognised() -> None:
    levels = lg.analyse(_speechlike(3, (400.0, 1500.0, 5200.0, 6500.0)), RATE)
    assert levels.band.startswith("wideband")


def test_stereo_and_integer_input_become_mono_floats() -> None:
    stereo = np.array([[32767, -32767], [16384, 16384]], dtype=np.int16)
    mono = lg.to_mono(stereo)
    assert mono.dtype == np.float32
    assert mono.shape == (2,)
    assert mono[0] == pytest.approx(0.0, abs=1e-4)
    assert mono[1] == pytest.approx(0.5, abs=1e-3)


def test_three_dimensional_input_is_refused() -> None:
    with pytest.raises(ValueError):
        lg.to_mono(np.zeros((2, 2, 2), dtype=np.float32))


def test_frame_levels_need_a_positive_rate() -> None:
    with pytest.raises(ValueError):
        lg.frame_dbfs(np.zeros(10, dtype=np.float32), 0)


def test_a_clip_shorter_than_one_frame_reads_as_silence() -> None:
    assert lg.frame_dbfs(np.ones(5, dtype=np.float32), RATE).tolist() == [lg.FLOOR_DBFS]


@pytest.mark.parametrize("digit", sorted(lg.DTMF_HZ))
def test_each_key_tone_carries_its_two_frequencies(digit: str) -> None:
    tone = lg.dtmf_tone(digit, RATE, tone_s=0.25, gap_s=0.0)
    spectrum = np.abs(np.fft.rfft(tone))
    freqs = np.fft.rfftfreq(len(tone), d=1.0 / RATE)
    top_two = sorted(freqs[np.argsort(spectrum)[-2:]])
    low, high = lg.DTMF_HZ[digit]
    assert top_two[0] == pytest.approx(low, abs=6)
    assert top_two[1] == pytest.approx(high, abs=6)
    assert float(np.max(np.abs(tone))) <= 0.8 + 1e-6


def test_key_tone_has_its_gap_and_length() -> None:
    tone = lg.dtmf_tone("5", 8000, tone_s=0.2, gap_s=0.1)
    assert len(tone) == 1600 + 800
    assert not tone[-800:].any()


@pytest.mark.parametrize("bad", ["", "A", "12", "+"])
def test_unknown_keys_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        lg.dtmf_tone(bad, RATE)


def test_key_tone_refuses_a_loud_amplitude() -> None:
    with pytest.raises(ValueError):
        lg.dtmf_tone("1", RATE, amplitude=0.9)


def test_find_device_ignores_case_and_returns_the_first_match() -> None:
    names = ["Speakers (Realtek)", "CABLE Input (VB-Audio Virtual Cable)", "cable input 2"]
    assert lg.find_device(names, "cable input") == "CABLE Input (VB-Audio Virtual Cable)"
    assert lg.find_device(names, "CABLE Output") is None


def test_report_has_every_result_and_no_digits_beyond_its_own() -> None:
    report = lg.Report(
        windows="Windows 11",
        python="3.12.10",
        speakers=["Speakers (Realtek)", "CABLE Input (VB-Audio Virtual Cable)"],
        microphones=["Microphone (Realtek)", "CABLE Output (VB-Audio Virtual Cable)"],
        default_speaker="Speakers (Realtek)",
        default_microphone="Microphone (Realtek)",
        cable_found=True,
        test_a=lg.analyse(_speechlike(2, (400.0, 1500.0)), RATE),
        test_a_carrier="Speakers (Realtek)",
        test_b="PASS (heard clearly)",
        test_c="skipped",
        mic_restored="yes",
    )
    text = report.text("25 Nov 2026, 23:59")
    assert "Test A - JARVIS hears the call: PASS" in text
    assert "Test B - JARVIS speaks into the call: PASS (heard clearly)" in text
    assert "Test C - a phone menu reacts to key tones: skipped" in text
    assert "Hands-free (phone) devices: none" in text
    assert "VB-CABLE found: yes" in text


def test_report_before_test_a_says_not_run() -> None:
    report = lg.Report(notes=["stopped: VB-CABLE missing"])
    text = report.text("now")
    assert "Test A - JARVIS hears the call: NOT RUN" in text
    assert "VB-CABLE found: NO" in text
    assert "Note: stopped: VB-CABLE missing" in text


def test_check_script_refuses_to_run_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(KIT))
    check = _load("s0_check")
    monkeypatch.setattr(check.platform, "system", lambda: "Linux")
    assert check.main() == 2


def test_requirements_are_pinned_and_hash_checked() -> None:
    text = (KIT / "requirements-s0.txt").read_text(encoding="utf-8")
    pins = [line for line in text.splitlines() if "==" in line]
    assert len(pins) == 4
    assert text.count("--hash=sha256:") == 4


def test_wav_round_trip_keeps_the_sound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(KIT))
    check = _load("s0_check")
    sound = _speechlike(1, (440.0,))
    path = tmp_path / "clip.wav"
    check.save_wav(path, sound, RATE)
    back, rate = check.load_wav(path)
    assert rate == RATE
    assert back.shape == sound.shape
    assert float(np.max(np.abs(back - np.clip(sound, -1, 1)))) < 1e-3
