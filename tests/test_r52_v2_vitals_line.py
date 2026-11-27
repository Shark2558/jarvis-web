# tests/test_r52_v2_vitals_line.py -- R5.2 V2: Vitals' engine line (plan 3.2: "Vitals shows which
# engine served and ₹0 for the laptop"). One automatic item, "Laptop speech kit", shown only when
# the kit is set up: ok while it is ready, amber (with Google's speech used meanwhile) while it is
# slow, old or away; its note says which engine heard and spoke last and that the laptop costs ₹0.
# A laptop asleep is normal and voice falls back by itself, so the item never alerts.
from __future__ import annotations

from pydantic import SecretStr
from r51b_fakes import OwnRig, with_keys

from jarvis.localspeech import protocol as p
from jarvis.localspeech.memory import MemoryKit
from jarvis.vitals.own import LABELS, OwnSources
from jarvis.vitals.words import voice_note, words_for
from jarvis.voice.laptop import LaptopVoice

UID = "u_owner"
ONE_SECOND = b"\x01\x00" * p.SAMPLE_RATE
URL = "https://my-laptop.tail1234.ts.net:8443"
KEY = "k" * 40


async def board_item(laptop: LaptopVoice | None, **settings: object):  # type: ignore[no-untyped-def]
    rig = OwnRig(OwnSources(voice=laptop), settings=with_keys(**settings))
    board = await rig.svc.board(UID)
    return next((v for v in board.items if v.provider.id == "voice_laptop"), None), rig


async def test_a_ready_kit_says_which_engine_served_at_no_cost() -> None:
    laptop = LaptopVoice(MemoryKit(), health_s=30)
    await laptop.stt.recognize(ONE_SECOND, sample_rate=16_000, language="en-IN", phrases=())
    laptop.note_served(p.Kind.TTS, "google")
    item, _ = await board_item(laptop)
    assert item is not None and item.status == "ok"
    assert item.provider.label == LABELS["voice_laptop"] == "Laptop speech kit"
    assert item.provider.note == (
        "Last heard by the laptop (Whisper small). Last spoken by Google. "
        "The laptop costs ₹0 a minute."
    )
    assert item.provider.source == "auto" and item.group == "keys"


async def test_a_kit_away_is_amber_with_fixed_words_and_never_alerts() -> None:
    kit = MemoryKit()
    kit.down = "offline"
    item, rig = await board_item(LaptopVoice(kit, health_s=30))
    assert item is not None and item.status == "amber"
    assert item.reason.endswith("isn't answering; Google's speech is used")
    assert item.impact.startswith("If this stops: JARVIS listens and speaks with Google")
    assert item.fix and "voice_laptop" in rig.svc._own.quiet_ids()  # type: ignore[union-attr]


async def test_a_slow_kit_is_amber() -> None:
    kit = MemoryKit()
    kit.slow = True
    item, _ = await board_item(LaptopVoice(kit, health_s=30))
    assert item is not None and item.status == "amber" and "slow" in item.reason


async def test_no_kit_no_line() -> None:
    item, _ = await board_item(LaptopVoice(None, health_s=30))
    assert item is None
    item, _ = await board_item(None)
    assert item is None


async def test_a_kit_set_up_without_its_reader_is_unknown() -> None:
    item, _ = await board_item(None, local_speech_url=URL, local_speech_key=SecretStr(KEY))
    assert item is not None and item.status == "unknown"


def test_the_note_names_only_known_engines_in_fixed_words() -> None:
    assert voice_note(None, None, 0.0) == (
        "Nothing heard or spoken since JARVIS started. The laptop costs ₹0 a minute."
    )
    odd = voice_note("<script>alert(1)</script>", "laptop-piper", 0.0)
    assert "script" not in odd and "another engine" in odd and "the laptop (Piper)" in odd
    impact, fix = words_for("voice_laptop", LABELS["voice_laptop"])
    assert impact.startswith("If this ") and fix
