# src/jarvis/calls/protocol.py
"""R18 wire contracts (BUILD-BRIEF.md "Contracts"; I0-SEAMS.md): the binary audio frames and every
JSON message between the call desk, the phone app, the console and the cloud.

Audio everywhere: 16 kHz, mono, signed 16-bit little-endian PCM in 20 ms frames (640 bytes), sent
as ONE binary WebSocket message of whole frames behind one prefix byte (`AudioKind`):
0x01 the other person (desk -> cloud), 0x02 JARVIS's voice (cloud -> desk), 0x03 mixed live audio
(cloud -> listener). JSON messages are `{"type": ..., ...}`, one Pydantic model per type, parsed
through a discriminated union per direction (`parse_desk`, `parse_cloud_to_desk`,
`parse_phone_command`, `parse_phone_event`, `parse_live_client`, `parse_live_server`); `dump`
writes one. Anything else raises `ProtocolError`, whose words never quote the message (it may carry
a transcript).

Pure Pydantic and `jarvis.calls.models` (no other `jarvis` import): the desk kit can ship this file.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import IntEnum
from typing import Annotated, Any, Final, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from jarvis.calls.models import CALL_ID, E164, LANG_CODE, CallState, EndReason, Speaker, SpeechMode

# ---- paths and close codes -----------------------------------------------------------------------
DESK_WS_PATH: Final = "/v1/calls/desk/ws"  # the brief's /api/calls/desk/ws: JARVIS's routes are /v1
LIVE_WS_PATH: Final = "/v1/calls/{call_id}/live"
WS_BAD_MESSAGE: Final = 4400
WS_UNAUTHORIZED: Final = 4401
WS_NOT_BUILT: Final = 4501  # the I0 stub: the route exists, its part is not wired yet
WS_GONE: Final = 4404  # no such call (or it ended)

# ---- audio ---------------------------------------------------------------------------------------
SAMPLE_RATE: Final = 16_000
CHANNELS: Final = 1
SAMPLE_BYTES: Final = 2  # signed 16-bit little-endian
FRAME_MS: Final = 20
FRAME_BYTES: Final = SAMPLE_RATE * FRAME_MS // 1000 * SAMPLE_BYTES * CHANNELS  # 640
MAX_FRAMES_PER_MESSAGE: Final = 50  # one second of audio a message at most
MAX_JSON_BYTES: Final = 8_192
TEXT_MAX: Final = 2_000  # a caption, a heard text, a spoken sentence
TELL_MAX: Final = 500
SILENCE: Final = b"\x00\x00"


class ProtocolError(ValueError):
    """A frame or message that is not one of the contract's."""


class AudioKind(IntEnum):
    THEM = 0x01  # the other person, desk -> cloud
    JARVIS = 0x02  # JARVIS's voice, cloud -> desk
    MIXED = 0x03  # both sides, cloud -> a live listener


def pack_audio(kind: AudioKind, pcm: bytes) -> bytes:
    _check_pcm(pcm)
    return bytes((int(kind),)) + pcm


def unpack_audio(data: bytes) -> tuple[AudioKind, bytes]:
    if len(data) < 1 + FRAME_BYTES:
        raise ProtocolError("an audio message carries at least one frame")
    try:
        kind = AudioKind(data[0])
    except ValueError:
        raise ProtocolError("unknown audio kind") from None
    pcm = data[1:]
    _check_pcm(pcm)
    return kind, pcm


def split_frames(pcm: bytes) -> list[bytes]:
    """Whole 20 ms frames; the last one padded with silence."""
    if len(pcm) % SAMPLE_BYTES:
        raise ProtocolError("PCM16 audio has an even number of bytes")
    out = [pcm[i : i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]
    if out and len(out[-1]) < FRAME_BYTES:
        out[-1] = out[-1] + b"\x00" * (FRAME_BYTES - len(out[-1]))
    return out


def _check_pcm(pcm: bytes) -> None:
    if not pcm or len(pcm) % FRAME_BYTES:
        raise ProtocolError(f"audio is whole {FRAME_BYTES}-byte frames")
    if len(pcm) > FRAME_BYTES * MAX_FRAMES_PER_MESSAGE:
        raise ProtocolError(f"at most {MAX_FRAMES_PER_MESSAGE} frames a message")


# ---- shared fields -------------------------------------------------------------------------------
class _Msg(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


CallId = Annotated[str, Field(pattern=CALL_ID)]
Lang = Annotated[str, Field(pattern=LANG_CODE)]
Digit = Annotated[str, Field(pattern=r"^[0-9*#]$")]
UtteranceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")]
Text = Annotated[str, Field(max_length=TEXT_MAX)]
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")]
Short = Annotated[str, Field(max_length=200)]


# ---- desk -> cloud -------------------------------------------------------------------------------
class Hello(_Msg):
    type: Literal["hello"] = "hello"
    desk_version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    speech_modes: tuple[SpeechMode, ...] = (SpeechMode.CLOUD,)
    local_languages: tuple[Lang, ...] = ()


class DeskState(_Msg):
    """The desk's ready check; also its answer to `ping`."""

    type: Literal["state"] = "state"
    ready: bool
    problems: tuple[Short, ...] = Field(default=(), max_length=10)
    bt_headset: bool  # a Bluetooth headset on the laptop: Phone Link refuses calls
    cable: bool  # VB-CABLE installed and found
    phone_link: bool  # Phone Link running with a phone connected for calls


class Vad(_Msg):
    type: Literal["vad"] = "vad"
    call_id: CallId
    speaking: bool


class HeardText(_Msg):
    """Laptop speech mode only: the desk's own hearing."""

    type: Literal["heard_text"] = "heard_text"
    call_id: CallId
    lang: Lang
    text: Text
    confidence: Annotated[float, Field(ge=0, le=1)]


class Played(_Msg):
    type: Literal["played"] = "played"
    call_id: CallId
    utterance_id: UtteranceId


class DtmfDone(_Msg):
    type: Literal["dtmf_done"] = "dtmf_done"
    call_id: CallId
    digit: Digit


class Mic(_Msg):
    type: Literal["mic"] = "mic"
    call_id: CallId
    owner_mic: bool  # True: the owner's own microphone is the default again


class DeskError(_Msg):
    type: Literal["error"] = "error"
    call_id: CallId | None = None
    code: Code
    message: Short


DeskToCloud = Annotated[
    Hello | DeskState | Vad | HeardText | Played | DtmfDone | Mic | DeskError,
    Field(discriminator="type"),
]


# ---- cloud -> desk -------------------------------------------------------------------------------
class Prepare(_Msg):
    """Switch the default microphones to the cable and start listening for this call."""

    type: Literal["prepare"] = "prepare"
    call_id: CallId
    mode: SpeechMode
    languages: tuple[Lang, ...] = Field(min_length=1, max_length=4)


class SayText(_Msg):
    """Laptop speech mode: the desk speaks this itself."""

    type: Literal["say_text"] = "say_text"
    call_id: CallId
    utterance_id: UtteranceId
    lang: Lang
    text: Annotated[str, Field(min_length=1, max_length=TEXT_MAX)]


class Dtmf(_Msg):
    type: Literal["dtmf"] = "dtmf"
    call_id: CallId
    digit: Digit


class StopSpeaking(_Msg):
    type: Literal["stop_speaking"] = "stop_speaking"
    call_id: CallId


class DeskTakeover(_Msg):
    """Restore the owner's microphone; keep the loopback recording."""

    type: Literal["takeover"] = "takeover"
    call_id: CallId


class Release(_Msg):
    """The call is over: restore every device."""

    type: Literal["release"] = "release"
    call_id: CallId


class Ping(_Msg):
    type: Literal["ping"] = "ping"


CloudToDesk = Annotated[
    Prepare | SayText | Dtmf | StopSpeaking | DeskTakeover | Release | Ping,
    Field(discriminator="type"),
]


# ---- cloud -> phone (the R7 cloud -> phone channel signs each one) -------------------------------
class CallDial(_Msg):
    type: Literal["call.dial"] = "call.dial"
    call_id: CallId
    number: Annotated[str, Field(pattern=E164)]
    approval_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")]


class CallAnswer(_Msg):
    type: Literal["call.answer"] = "call.answer"
    call_id: CallId


class CallEnd(_Msg):
    type: Literal["call.end"] = "call.end"
    call_id: CallId


class CallRoute(_Msg):
    type: Literal["call.route"] = "call.route"
    call_id: CallId
    to: Literal["phone", "bluetooth"]


PhoneCommand = Annotated[
    CallDial | CallAnswer | CallEnd | CallRoute,
    Field(discriminator="type"),
]


# ---- phone -> cloud ------------------------------------------------------------------------------
class CallStateEvent(_Msg):
    type: Literal["call.state"] = "call.state"
    call_id: CallId | None = None  # None: an incoming call JARVIS did not place
    state: Literal["ringing", "dialing", "active", "ended"]
    number_e164: Annotated[str, Field(pattern=E164)] | None = None  # incoming only (the policy)
    rings: Annotated[int, Field(ge=0, le=60)] = 0
    at: AwareDatetime


PhoneEvent = Annotated[CallStateEvent, Field(discriminator="type")]


# ---- console <-> cloud (GET /v1/calls/{call_id}/live) --------------------------------------------
class LiveCaption(_Msg):
    type: Literal["caption"] = "caption"
    who: Speaker
    lang: Lang
    text: Text
    english: Text


class LiveState(_Msg):
    type: Literal["state"] = "state"
    call_id: CallId
    state: CallState
    lang: Lang | None = None  # the language JARVIS speaks now
    seconds: Annotated[int, Field(ge=0)] = 0
    cost_inr: Annotated[float, Field(ge=0)] = 0
    listening: bool = False  # this listener receives 0x03 audio
    taken_over: bool = False
    recording: bool = True
    end_reason: EndReason | None = None


LiveServer = Annotated[LiveCaption | LiveState, Field(discriminator="type")]


class Listen(_Msg):
    type: Literal["listen"] = "listen"
    audio: bool  # False: captions only


class LiveTakeover(_Msg):
    type: Literal["takeover"] = "takeover"


class Tell(_Msg):
    """A silent instruction to JARVIS; the other person does not hear it."""

    type: Literal["tell"] = "tell"
    text: Annotated[str, Field(min_length=1, max_length=TELL_MAX)]


class Hangup(_Msg):
    type: Literal["hangup"] = "hangup"


LiveClient = Annotated[Listen | LiveTakeover | Tell | Hangup, Field(discriminator="type")]

Message = (
    Hello
    | DeskState
    | Vad
    | HeardText
    | Played
    | DtmfDone
    | Mic
    | DeskError
    | Prepare
    | SayText
    | Dtmf
    | StopSpeaking
    | DeskTakeover
    | Release
    | Ping
    | CallDial
    | CallAnswer
    | CallEnd
    | CallRoute
    | CallStateEvent
    | LiveCaption
    | LiveState
    | Listen
    | LiveTakeover
    | Tell
    | Hangup
)

# ---- parsing -------------------------------------------------------------------------------------
T = TypeVar("T")
Raw = str | bytes | Mapping[str, Any]

_DESK: TypeAdapter[DeskToCloud] = TypeAdapter(DeskToCloud)
_TO_DESK: TypeAdapter[CloudToDesk] = TypeAdapter(CloudToDesk)
_PHONE_CMD: TypeAdapter[PhoneCommand] = TypeAdapter(PhoneCommand)
_PHONE_EVENT: TypeAdapter[PhoneEvent] = TypeAdapter(PhoneEvent)
_LIVE_CLIENT: TypeAdapter[LiveClient] = TypeAdapter(LiveClient)
_LIVE_SERVER: TypeAdapter[LiveServer] = TypeAdapter(LiveServer)


def _load(raw: Raw) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return raw
    if len(raw) > MAX_JSON_BYTES:
        raise ProtocolError("message too large")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ProtocolError("message is not JSON") from None
    if not isinstance(data, dict):
        raise ProtocolError("message is not a JSON object")
    return data


def _parse(adapter: TypeAdapter[T], raw: Raw) -> T:
    data = _load(raw)
    try:
        return adapter.validate_python(data)
    except ValidationError as exc:  # field names and kinds only: never the values
        where = sorted({".".join(str(x) for x in e["loc"]) or "type" for e in exc.errors()})
        raise ProtocolError(f"message not valid: {', '.join(where)[:200]}") from None


def parse_desk(raw: Raw) -> DeskToCloud:
    return _parse(_DESK, raw)


def parse_cloud_to_desk(raw: Raw) -> CloudToDesk:
    return _parse(_TO_DESK, raw)


def parse_phone_command(raw: Raw) -> PhoneCommand:
    return _parse(_PHONE_CMD, raw)


def parse_phone_event(raw: Raw) -> PhoneEvent:
    return _parse(_PHONE_EVENT, raw)


def parse_live_client(raw: Raw) -> LiveClient:
    return _parse(_LIVE_CLIENT, raw)


def parse_live_server(raw: Raw) -> LiveServer:
    return _parse(_LIVE_SERVER, raw)


def dump(msg: Message) -> str:
    return msg.model_dump_json()


__all__ = [
    "CHANNELS",
    "DESK_WS_PATH",
    "FRAME_BYTES",
    "FRAME_MS",
    "LIVE_WS_PATH",
    "MAX_FRAMES_PER_MESSAGE",
    "MAX_JSON_BYTES",
    "SAMPLE_BYTES",
    "SAMPLE_RATE",
    "TELL_MAX",
    "TEXT_MAX",
    "WS_BAD_MESSAGE",
    "WS_GONE",
    "WS_NOT_BUILT",
    "WS_UNAUTHORIZED",
    "AudioKind",
    "CallAnswer",
    "CallDial",
    "CallEnd",
    "CallRoute",
    "CallStateEvent",
    "CloudToDesk",
    "DeskError",
    "DeskState",
    "DeskTakeover",
    "DeskToCloud",
    "Dtmf",
    "DtmfDone",
    "Hangup",
    "HeardText",
    "Hello",
    "Listen",
    "LiveCaption",
    "LiveClient",
    "LiveServer",
    "LiveState",
    "LiveTakeover",
    "Message",
    "Mic",
    "PhoneCommand",
    "PhoneEvent",
    "Ping",
    "Played",
    "Prepare",
    "ProtocolError",
    "Release",
    "SayText",
    "StopSpeaking",
    "Tell",
    "Vad",
    "dump",
    "pack_audio",
    "parse_cloud_to_desk",
    "parse_desk",
    "parse_live_client",
    "parse_live_server",
    "parse_phone_command",
    "parse_phone_event",
    "split_frames",
    "unpack_audio",
]
