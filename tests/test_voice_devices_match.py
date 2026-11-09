# tests/test_voice_devices_match.py
# ruff: noqa: E501  (embedded JavaScript lines)
"""R5 workstream B: the pure matching helpers (console-voice-devices-match.js), run in Node.

Realistic Windows labels, the review's table of phrases, hostile text, Indic nicknames. The module
has no DOM, so it loads in a bare `vm` context with only a `window` object.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
MATCH_JS = ROOT / "src/jarvis/api/static/console-voice-devices-match.js"
HARNESS = """
const vm = require('vm'), fs = require('fs');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
const M = sandbox.window.JarvisAudioMatch;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = vm.runInContext('(' + input.expr + ')', Object.assign(sandbox, { M, args: input.args }));
process.stdout.write(JSON.stringify(out === undefined ? null : out));
"""

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def js(expr: str, **args: Any) -> Any:
    run = subprocess.run(
        ["node", "-e", HARNESS, str(MATCH_JS)],
        input=json.dumps({"expr": expr, "args": args}),
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    return json.loads(run.stdout)


def describe(labels: list[str], kinds: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Mimic the route's describe(): tidy, classify, built-in and call-quality flags."""
    return js(
        """args.labels.map((l) => ({ label: M.tidy(l), kind: M.classify(l), builtIn: M.isBuiltIn(l),
            callQuality: M.isCallQuality(M.tidy(l), args.labels.map(M.tidy).filter((o) => o !== M.tidy(l))) }))
            .map((d, i) => Object.assign(d, { id: 'd' + i }))""",
        labels=labels,
    )


def pick(devs: list[dict[str, Any]], phrase: str, names: dict[str, str] | None = None) -> list[str]:
    return js(
        "M.rank(args.devs, args.phrase, { nameOf: (d) => args.names[d.id] || '' }).map((r) => r.d.id)",
        devs=devs,
        phrase=phrase,
        names=names or {},
    )


def best(
    devs: list[dict[str, Any]], phrase: str, names: dict[str, str] | None = None
) -> tuple[str | None, bool]:
    r = js(
        "(() => { const x = M.rank(args.devs, args.phrase, { nameOf: (d) => args.names[d.id] || '' });"
        " return [x[0] ? x[0].d.label : null, x.length > 1 && x[0].key === x[1].key]; })()",
        devs=devs,
        phrase=phrase,
        names=names or {},
    )
    return r[0], r[1]


WINDOWS = describe(
    [
        "Speakers (Realtek(R) Audio)",
        "Headphones (Pixel Buds Pro)",
        "Headset (Pixel Buds Pro Hands-Free AG Audio)",
        "Speakers (boAt Stone 352)",
        "Realtek Digital Output (Realtek(R) Audio)",
        "LG HDR 4K (NVIDIA High Definition Audio)",
        "Headphones (WH-1000XM4 Stereo)",
        "Headset (WH-1000XM4 Hands-Free AG Audio)",
        "Steam Streaming Speakers",
        "Speakers (USB Audio Device) (046d:0825)",
    ]
)


def by_label(devs: list[dict[str, Any]], needle: str) -> dict[str, Any]:
    return next(d for d in devs if needle in d["label"])


@pytest.mark.parametrize(
    ("phrase", "expect"),
    [
        ("bluetooth speaker", "Speakers (boAt Stone 352)"),
        ("laptop speakers", "Speakers (Realtek(R) Audio)"),
        ("laptop", "Speakers (Realtek(R) Audio)"),
        ("earphones", "Headphones (Pixel Buds Pro)"),
        ("xm4", "Headphones (WH-1000XM4 Stereo)"),
        ("1000", "Headphones (WH-1000XM4 Stereo)"),
        ("the pixel buds", "Headphones (Pixel Buds Pro)"),
        ("boat", "Speakers (boAt Stone 352)"),
    ],
)
def test_realistic_windows_labels_resolve(phrase: str, expect: str) -> None:
    got, _tie = best(WINDOWS, phrase)
    assert got == expect


@pytest.mark.parametrize(
    "phrase",
    [
        "audio",
        "digital",
        "the device",
        "high definition",
        "constructor",
        "toString",
        "__proto__",
        "zzzz",
    ],
)
def test_generic_or_unknown_phrases_match_nothing(phrase: str) -> None:
    assert pick(WINDOWS, phrase) == []


def test_a_closer_name_ranks_above_a_looser_one() -> None:
    devs = describe(["Headphones (Pixel Buds 2)", "Headphones (Pixel Buds Pro)"])
    assert best(devs, "pixel buds pro", None)[0] == "Headphones (Pixel Buds Pro)"


def test_bluetooth_with_only_a_realtek_and_a_spdif_output_matches_nothing() -> None:
    devs = describe(
        [
            "Speakers (Realtek(R) Audio)",
            "Realtek Digital Output (Realtek(R) Audio)",
            "LG HDR 4K (NVIDIA High Definition Audio)",
        ]
    )
    assert pick(devs, "bluetooth") == []


def test_two_bluetooth_devices_are_a_tie_so_the_router_can_ask_which() -> None:
    devs = describe(
        ["Speakers (Realtek(R) Audio)", "Headphones (Pixel Buds Pro)", "Speakers (boAt Stone 352)"]
    )
    first, tie = best(devs, "bluetooth")
    assert tie is True and first in ("Headphones (Pixel Buds Pro)", "Speakers (boAt Stone 352)")


def test_a_preferred_device_breaks_a_tie() -> None:
    devs = describe(["Headphones (Pixel Buds Pro)", "Speakers (boAt Stone 352)"])
    r = js(
        "(() => { const x = M.rank(args.devs, 'bluetooth', { prefer: (d) => d.id === 'd1' }); return [x[0].d.id, x[0].key === x[1].key]; })()",
        devs=devs,
    )
    assert r == ["d1", False]


def test_display_and_hdmi_endpoints_are_not_built_in() -> None:
    assert by_label(WINDOWS, "NVIDIA")["builtIn"] is False
    assert by_label(WINDOWS, "Digital Output")["builtIn"] is False
    assert by_label(WINDOWS, "Realtek(R) Audio)")["builtIn"] is True
    assert js("M.isBuiltIn('Intel(R) Display Audio')") is False
    assert js("M.isBuiltIn('Realtek HDMI Output')") is False


def test_among_built_ins_the_speakers_endpoint_wins() -> None:
    devs = describe(
        [
            "Realtek Digital Output (Realtek(R) Audio)",
            "Microphone Array (Intel Smart Sound)",
            "Speakers (Realtek(R) Audio)",
        ]
    )
    got, _ = best(devs, "laptop")
    assert got == "Speakers (Realtek(R) Audio)"


@pytest.mark.parametrize(
    ("labels", "demoted"),
    [
        (
            ["Headphones (WH-1000XM4 Stereo)", "Headset (WH-1000XM4 Hands-Free AG Audio)"],
            "Headset (WH-1000XM4 Hands-Free AG Audio)",
        ),
        (["Headphones (X)", "Headset (X)"], "Headset (X)"),
        (
            ["Headphones (Buds (046d:0825))", "Headset (Buds Hands-Free)"],
            "Headset (Buds Hands-Free)",
        ),
        (
            ["Headphones (Galaxy Buds2 Pro)", "Headset (Galaxy Buds2 Pro Hands-Free AG Audio)"],
            "Headset (Galaxy Buds2 Pro Hands-Free AG Audio)",
        ),
    ],
)
def test_call_quality_twins_are_recognised_in_every_naming_pattern(
    labels: list[str], demoted: str
) -> None:
    devs = describe(labels)
    flagged = [d["label"] for d in devs if d["callQuality"]]
    assert flagged == [M_tidy(demoted)]


def M_tidy(label: str) -> str:
    return js("M.tidy(args.l)", l=label)  # type: ignore[no-any-return]


def test_a_lone_headset_is_not_call_quality() -> None:
    assert [
        d["callQuality"] for d in describe(["Headset (Solo)", "Speakers (Realtek(R) Audio)"])
    ] == [False, False]


def test_a_call_quality_endpoint_is_used_only_when_it_is_all_there_is() -> None:
    devs = describe(["Headphones (Buds)", "Headset (Buds Hands-Free AG Audio)"])
    assert best(devs, "earphones")[0] == "Headphones (Buds)"
    only = describe(["Headset (Buds Hands-Free AG Audio)"])
    assert best(only, "earphones")[0] == "Headset (Buds Hands-Free AG Audio)"


@pytest.mark.parametrize("nickname", ["ഹെഡ്ഫോൺ", "हेडफोन", "हेडफ़ोन", "buds", "my buds"])
def test_nicknames_in_any_script_round_trip(nickname: str) -> None:
    devs = describe(["Headphones (Pixel Buds Pro)", "Speakers (boAt Stone 352)"])
    names = {"d1": M_nick(nickname)}
    assert best(devs, nickname.replace("my ", ""), names)[0] == "Speakers (boAt Stone 352)"


def M_nick(n: str) -> str:
    return js("M.nick(args.n)", n=n)  # type: ignore[no-any-return]


def test_a_nickname_survives_the_routers_loss_of_combining_marks() -> None:
    devs = describe(["Headphones (Pixel Buds Pro)", "Speakers (boAt Stone 352)"])
    # the router's word splitter drops combining marks, leaving "ह ड फ न" for "हेडफोन"
    assert best(devs, "ह ड फ न", {"d1": "हेडफोन"})[0] == "Speakers (boAt Stone 352)"


def test_a_slightly_misheard_nickname_still_matches_but_a_stranger_does_not() -> None:
    devs = describe(["Speakers (boAt Stone 352)", "Headphones (Pixel Buds Pro)"])
    assert best(devs, "kitchn", {"d0": "kitchen"})[0] == "Speakers (boAt Stone 352)"
    assert best(devs, "garage", {"d0": "kitchen"})[0] is None


def test_a_nickname_wins_over_a_device_word() -> None:
    devs = describe(["Headphones (Pixel Buds Pro)", "Speakers (boAt Stone 352)"])
    assert best(devs, "buds", {"d1": "buds"})[0] == "Speakers (boAt Stone 352)"


def test_hidden_and_bidi_characters_are_stripped_from_labels_and_nicknames() -> None:
    dirty = "Head‮phones​ (X)\u0000⁦﻿"
    assert js("M.tidy(args.l)", l=dirty) == "Headphones (X)"
    assert js("M.nick(args.n)", n="bu​ds‮\u0007") == "buds"
    assert js("M.nick(args.n)", n="ｋｉｔｃｈｅｎ") == "kitchen"  # NFKC: full-width letters


def test_labels_and_nicknames_are_clipped() -> None:
    assert len(js("M.tidy(args.l)", l="x" * 5000)) == 120
    assert len(js("M.nick(args.n)", n="y" * 500)) == 30


def test_usb_ids_are_removed_before_labels_are_compared() -> None:
    assert (
        js("M.tidy(args.l)", l="Speakers (USB Audio Device) (046d:0825)")
        == "Speakers (USB Audio Device)"
    )


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("earphones", True),
        ("laptop speakers", True),
        ("bluetooth speaker", True),
        ("default", True),
        ("constructor", False),
        ("dark mode", False),
        ("", False),
    ],
)
def test_device_words_are_a_closed_vocabulary(text: str, word: bool) -> None:
    assert js("M.isDeviceWord(args.t)", t=text) is word


def test_spoken_phrases_use_a_kind_word_and_never_a_label() -> None:
    devs = describe(
        [
            "Headphones (Akash's AirPods)",
            "Speakers (Realtek(R) Audio)",
            "Speakers (boAt Stone 352)",
            "Something odd",
        ]
    )
    spoken = js(
        "args.devs.map((d) => [M.outputPhrase(d), M.inputPhrase(d), M.connectPhrases(d).said, M.kindListWord(d)])",
        devs=devs,
    )
    assert spoken[0][0] == "your earphones" and spoken[1][0] == "the laptop speakers"
    assert spoken[2][0] == "the speaker" and spoken[3][0] == "that device"
    flat = json.dumps(spoken).lower()
    for secret in ("akash", "airpods", "boat", "realtek", "stone"):
        assert secret not in flat
