# tests/test_r18_i0_protocol.py -- R18 I0 (BUILD-BRIEF.md "Contracts"): the binary audio frames and
# every desk <-> cloud, phone <-> cloud and console <-> cloud message as a discriminated union.
from __future__ import annotations

import json

import pytest

from jarvis.calls import protocol as p
from jarvis.calls.models import CallState, SpeechMode

CALL = "call_0123456789ab"


def test_the_audio_format_is_the_briefs() -> None:
    assert (p.SAMPLE_RATE, p.CHANNELS, p.SAMPLE_BYTES, p.FRAME_MS) == (16_000, 1, 2, 20)
    assert p.FRAME_BYTES == 640
    assert (p.AudioKind.THEM, p.AudioKind.JARVIS, p.AudioKind.MIXED) == (0x01, 0x02, 0x03)


def test_frames_pack_and_unpack() -> None:
    pcm = b"\x01\x00" * 320
    msg = p.pack_audio(p.AudioKind.THEM, pcm)
    assert msg[0] == 0x01 and len(msg) == 641
    assert p.unpack_audio(msg) == (p.AudioKind.THEM, pcm)
    two = p.pack_audio(p.AudioKind.MIXED, pcm * 2)
    assert p.unpack_audio(two) == (p.AudioKind.MIXED, pcm * 2)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x01",  # no audio
        b"\x09" + b"\x00" * 640,  # unknown kind
        b"\x01" + b"\x00" * 639,  # not whole frames
        b"\x01" + b"\x00" * (p.FRAME_BYTES * (p.MAX_FRAMES_PER_MESSAGE + 1)),
    ],
)
def test_bad_frames_are_refused(raw: bytes) -> None:
    with pytest.raises(p.ProtocolError):
        p.unpack_audio(raw)


def test_split_frames_pads_the_last_frame_with_silence() -> None:
    frames = p.split_frames(b"\x01\x00" * 500)  # 1000 bytes: one frame and a part
    assert [len(f) for f in frames] == [640, 640]
    assert frames[1].endswith(b"\x00" * 280)
    with pytest.raises(p.ProtocolError):
        p.split_frames(b"\x00")  # half a sample


def test_desk_to_cloud_messages_parse_by_type() -> None:
    hello = p.parse_desk(
        '{"type":"hello","desk_version":"18.0.0","speech_modes":["cloud","laptop"],'
        '"local_languages":["ml-IN"]}'
    )
    assert isinstance(hello, p.Hello) and hello.speech_modes == (
        SpeechMode.CLOUD,
        SpeechMode.LAPTOP,
    )
    state = p.parse_desk(
        {
            "type": "state",
            "ready": False,
            "problems": ["VB-CABLE is not installed"],
            "bt_headset": True,
            "cable": False,
            "phone_link": True,
        }
    )
    assert isinstance(state, p.DeskState) and not state.ready and state.bt_headset
    seen = [
        p.parse_desk({"type": "vad", "call_id": CALL, "speaking": True}),
        p.parse_desk(
            {"type": "heard_text", "call_id": CALL, "lang": "ml-IN", "text": "x", "confidence": 0.7}
        ),
        p.parse_desk({"type": "played", "call_id": CALL, "utterance_id": "u1"}),
        p.parse_desk({"type": "dtmf_done", "call_id": CALL, "digit": "1"}),
        p.parse_desk({"type": "mic", "call_id": CALL, "owner_mic": True}),
        p.parse_desk({"type": "error", "code": "cable_missing", "message": "no cable"}),
    ]
    assert [type(x) for x in seen] == [
        p.Vad,
        p.HeardText,
        p.Played,
        p.DtmfDone,
        p.Mic,
        p.DeskError,
    ]
    assert seen[-1].call_id is None  # type: ignore[union-attr]


def test_cloud_to_desk_messages_round_trip() -> None:
    msgs: list[p.CloudToDesk] = [
        p.Prepare(call_id=CALL, mode=SpeechMode.CLOUD, languages=("en-IN", "ml-IN")),
        p.SayText(call_id=CALL, utterance_id="u1", lang="en-IN", text="Hello"),
        p.Dtmf(call_id=CALL, digit="#"),
        p.StopSpeaking(call_id=CALL),
        p.DeskTakeover(call_id=CALL),
        p.Release(call_id=CALL),
        p.Ping(),
    ]
    for msg in msgs:
        raw = p.dump(msg)
        assert json.loads(raw)["type"] == msg.type
        assert p.parse_cloud_to_desk(raw) == msg
    assert [m.type for m in msgs] == [
        "prepare",
        "say_text",
        "dtmf",
        "stop_speaking",
        "takeover",
        "release",
        "ping",
    ]


def test_phone_commands_and_events() -> None:
    dial = p.CallDial(call_id=CALL, number="+919000000001", approval_id="ap_abcdefgh12")
    assert dial.type == "call.dial" and p.parse_phone_command(p.dump(dial)) == dial
    for cmd in (
        p.CallAnswer(call_id=CALL),
        p.CallEnd(call_id=CALL),
        p.CallRoute(call_id=CALL, to="phone"),
    ):
        assert p.parse_phone_command(p.dump(cmd)) == cmd
    ev = p.parse_phone_event(
        {
            "type": "call.state",
            "state": "ringing",
            "number_e164": "+919000000002",
            "rings": 3,
            "at": "2026-11-27T05:00:00Z",
        }
    )
    assert isinstance(ev, p.CallStateEvent) and ev.call_id is None and ev.rings == 3
    with pytest.raises(p.ProtocolError):
        p.parse_phone_command(
            {
                "type": "call.dial",
                "call_id": CALL,
                "number": "12345",
                "approval_id": "ap_abcdefgh12",
            }
        )


def test_console_live_messages() -> None:
    cap = p.LiveCaption(who="them", lang="ml-IN", text="sheri", english="okay")
    st = p.LiveState(call_id=CALL, state=CallState.TALKING, seconds=12, cost_inr=0.4)
    for msg in (cap, st):
        assert p.parse_live_server(p.dump(msg)) == msg
    got = [
        p.parse_live_client('{"type":"listen","audio":true}'),
        p.parse_live_client('{"type":"takeover"}'),
        p.parse_live_client('{"type":"tell","text":"ask for Saturday instead"}'),
        p.parse_live_client('{"type":"hangup"}'),
    ]
    assert [type(x) for x in got] == [p.Listen, p.LiveTakeover, p.Tell, p.Hangup]


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"type":"nope"}',
        '{"type":"vad","call_id":"bad","speaking":true}',
        '{"type":"vad","call_id":"call_0123456789ab","speaking":true,"extra":1}',
        '{"type":"dtmf_done","call_id":"call_0123456789ab","digit":"12"}',
        '{"type":"heard_text","call_id":"call_0123456789ab","lang":"en-IN","text":"x",'
        '"confidence":2}',
    ],
)
def test_bad_messages_are_protocol_errors(raw: str) -> None:
    with pytest.raises(p.ProtocolError):
        p.parse_desk(raw)


def test_a_message_over_the_size_cap_is_refused_before_parsing() -> None:
    big = json.dumps({"type": "tell", "text": "x" * (p.MAX_JSON_BYTES + 1)})
    with pytest.raises(p.ProtocolError, match="too large"):
        p.parse_live_client(big)


def test_paths_and_close_codes() -> None:
    assert p.DESK_WS_PATH == "/v1/calls/desk/ws"
    assert p.LIVE_WS_PATH == "/v1/calls/{call_id}/live"
    assert (p.WS_UNAUTHORIZED, p.WS_BAD_MESSAGE, p.WS_NOT_BUILT) == (4401, 4400, 4501)
