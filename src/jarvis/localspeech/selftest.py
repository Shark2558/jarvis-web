# src/jarvis/localspeech/selftest.py
"""The kit's self-test (R5.2 V1; plan 5 "Laptop kit"): the owner runs it on the laptop and pastes
the report into JARVIS's chat. Kit-safe: the standard library and the kit's own modules.

It checks the pinned model files (sizes and SHA-256) and their licence files, the recordings'
encryption, MP3, a round trip through the running kit (its voice says a fixed test sentence and
its listening hears it: word error, first audio, speed against the plan's bars) and the gate
(no key refused, a wrong key refused, an unknown address 404, the key accepted). The report never
holds the key, a folder name (it would show the Windows user name), the laptop's Tailscale name,
or anything the owner said: the only text in it is the fixed test sentence.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

from pydantic import BaseModel

from jarvis.calls.models import ENGLISH
from jarvis.localspeech.audio import Mp3Encoder, tone
from jarvis.localspeech.clips import ClipVault
from jarvis.localspeech.kitconfig import KIT_VERSION_NOW
from jarvis.localspeech.manager import LICENCE_NAME, ModelManager
from jarvis.localspeech.protocol import (
    GATE_PORT,
    HEALTH,
    LOOPBACK_BASE,
    PROTOCOL,
    STT,
    TTS,
    AudioFormat,
    ClipIn,
    Device,
    Kind,
    KitError,
    KitErrorBody,
    KitHealth,
    KitRefused,
    KitUnavailable,
    PromptKind,
    SttRequest,
    SttResult,
    TtsRequest,
    TtsResult,
    bearer,
    encode_pcm,
    new_session_id,
    parse_reply,
)

TEST_SENTENCE: Final = "Hello, this is JARVIS. One, two, three, four, five."
WER_BAR: Final = 0.20
FIRST_AUDIO_BAR_MS: Final = {Device.CUDA: 700, Device.CPU: 1_500}  # plan 5
SPEED_BAR: Final = 3.0  # listening faster than real time x3
PROBE_TIMEOUT_S: Final = 5
CALL_TIMEOUT_S: Final = 120  # the first call loads a model
_WORD = re.compile(r"[a-z0-9']+")
_NUMBERS: Final = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five"}


class KitCalls(Protocol):
    """What the round trip calls: the running kit through its gate (`GateCalls`), or a
    `service.KitService` in-process (the tests)."""

    async def health(self) -> KitHealth: ...

    async def stt(self, req: SttRequest) -> SttResult: ...

    async def tts(self, req: TtsRequest) -> TtsResult: ...


Probe = Callable[[str, str | None], Awaitable[int | None]]  # (path, key) -> HTTP status


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool | None  # None: skipped
    words: str

    def line(self) -> str:
        mark = {True: "PASS", False: "FAIL", None: "SKIP"}[self.ok]
        return f"{mark}  {self.name}: {self.words}"


@dataclass(frozen=True)
class Report:
    checks: tuple[Check, ...]
    when: datetime

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.ok is False)

    def text(self) -> str:
        lines = [
            f"JARVIS laptop speech kit - self-test (kit {KIT_VERSION_NOW}, protocol {PROTOCOL})",
            f"When: {self.when:%d %b %Y %H:%M} UTC",
            "",
            *(c.line() for c in self.checks),
            "",
            f"Result: {self.passed} passed, {self.failed} failed, "
            f"{len(self.checks) - self.passed - self.failed} skipped.",
            "Paste everything from the first line to here into JARVIS's chat.",
        ]
        return "\n".join(lines)


# ---- word error (a fixed English sentence: no cloud code needed) -------------------------------
def words_of(text: str) -> list[str]:
    return [_NUMBERS.get(w, w) for w in _WORD.findall(text.lower())]


def word_error(expected: str, heard: str) -> float:
    ref, hyp = words_of(expected), words_of(heard)
    if not ref:
        return 0.0 if not hyp else 1.0
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[len(hyp)] / len(ref)


# ---- the running kit, through its gate ----------------------------------------------------------
class GateCalls:
    """The kit's own API on 127.0.0.1 through the gate, with the key (stdlib only)."""

    def __init__(self, key: str, base: str = LOOPBACK_BASE) -> None:
        self._headers = {**bearer(key), "Content-Type": "application/json"}
        self._base = base

    def __repr__(self) -> str:
        return "GateCalls(127.0.0.1)"

    def _call(self, method: str, path: str, body: BaseModel | None) -> bytes:
        data = body.model_dump_json().encode() if body is not None else None
        request = urllib.request.Request(
            f"{self._base}{path}", data=data, headers=self._headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=CALL_TIMEOUT_S) as response:  # noqa: S310
                raw: bytes = response.read()
                return raw
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                refusal = KitErrorBody.model_validate_json(raw)
            except ValueError:
                raise KitUnavailable("protocol") from None
            if err.code == 401:
                raise KitUnavailable("unauthorized") from None
            raise KitRefused(refusal.error, refusal.detail) from None
        except (urllib.error.URLError, OSError):
            raise KitUnavailable("offline") from None

    async def health(self) -> KitHealth:
        raw = await asyncio.to_thread(self._call, "GET", HEALTH, None)
        return parse_reply(KitHealth, raw)

    async def stt(self, req: SttRequest) -> SttResult:
        return parse_reply(SttResult, await asyncio.to_thread(self._call, "POST", STT, req))

    async def tts(self, req: TtsRequest) -> TtsResult:
        return parse_reply(TtsResult, await asyncio.to_thread(self._call, "POST", TTS, req))


async def gate_probe(path: str, key: str | None) -> int | None:
    """The gate's HTTP status for `GET path` (with `key` when given), None when it isn't up."""

    def probe() -> int | None:
        headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
        url = f"http://127.0.0.1:{GATE_PORT}{path}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_S) as response:  # noqa: S310
                return int(response.status)
        except urllib.error.HTTPError as err:
            return int(err.code)
        except (urllib.error.URLError, OSError):
            return None

    return await asyncio.to_thread(probe)


# ---- the checks ---------------------------------------------------------------------------------
def check_models(manager: ModelManager) -> list[Check]:
    if not manager.manifest.models:
        left = ", ".join(m.slot.value for m in manager.manifest.left_out) or "none"
        return [Check("models", None, f"this kit pins no model files yet (left out: {left})")]
    found: list[Check] = []
    verified = manager.verify([m.slot for m in manager.manifest.models])
    for entry in manager.manifest.models:
        problem = verified.get(entry.slot)
        folder = manager.models_dir / entry.slot.value
        if problem is None and not (folder / LICENCE_NAME).is_file():
            problem = "its LICENCE.txt is missing"
        words = f"{entry.model}, {entry.licence}, hashes OK" if problem is None else problem
        found.append(Check(f"model {entry.slot.value}", problem is None, words))
    return found


def check_vault(vault: ClipVault) -> Check:
    """A synthetic clip is stored, read back and deleted; the file on disk must not hold it."""
    clip = ClipIn(
        session_id=new_session_id(),
        prompt_id="selftest",
        audio=encode_pcm(tone(0.5, 523.0)),
        kind=PromptKind.COMMAND,
        held_out=True,
    )
    try:
        vault.put(clip)
        on_disk = (vault.root / clip.session_id / "selftest.clip").read_bytes()
        back = vault.clips(clip.session_id)
        plain = clip.pcm()
        sealed = plain[:64] not in on_disk
        private = os.name == "nt" or (vault.key_file.stat().st_mode & 0o077) == 0
        ok = sealed and private and len(back) == 1 and back[0].pcm == plain
    finally:
        vault.delete(clip.session_id)
    words = "stored encrypted, read back, deleted" if ok else "recordings are NOT stored safely"
    if not private:
        words += "; the key file can be read by others"
    return Check("recordings", ok, words)


def check_mp3(mp3: Mp3Encoder | None) -> Check:
    if mp3 is None:
        return Check("MP3", False, "the kit can't make MP3 (PyAV missing): run the installer again")
    try:
        data = mp3.encode(tone(0.5), 16_000)
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return Check("MP3", False, f"the encoder failed ({type(exc).__name__})")
    ok = data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    return Check("MP3", ok, f"{len(data):,} bytes for half a second" if ok else "not MP3 audio")


async def check_round_trip(calls: KitCalls) -> list[Check]:
    try:
        health = await calls.health()
    except KitError as err:
        return [Check("kit", False, f"the running kit did not answer: {err}")]
    ready = [e.slot.value for e in health.engines if e.ready]
    found = [
        Check(
            "kit",
            health.compatible,
            f"kit {health.kit_version} on {health.device.value}"
            + (f", graphics memory free {health.gpu_free_mb:,} MB" if health.gpu_free_mb else "")
            + f", memory free {health.ram_free_mb:,} MB; ready: {', '.join(ready) or 'none'}",
        )
    ]
    voice_slot, ear_slot = (
        health.engine_for(Kind.TTS, ENGLISH),
        health.engine_for(Kind.STT, ENGLISH),
    )
    if voice_slot is None or ear_slot is None:
        found.append(Check("round trip", None, "needs an English voice and listening engine"))
        return found
    try:
        say = TtsRequest(lang=ENGLISH, text=TEST_SENTENCE, format=AudioFormat.PCM16)
        await calls.tts(say)  # the first call loads the voice: not timed
        spoken = await calls.tts(say)
        await calls.stt(SttRequest(lang=ENGLISH, audio=spoken.audio))  # loads the listener
        heard = await calls.stt(SttRequest(lang=ENGLISH, audio=spoken.audio))
    except KitError as err:
        found.append(Check("round trip", False, str(err)))
        return found
    bar = FIRST_AUDIO_BAR_MS[health.device]
    error = word_error(TEST_SENTENCE, heard.text)
    speed = heard.seconds / max(heard.elapsed_ms / 1000, 1e-3)
    found += [
        Check(
            "voice",
            spoken.first_audio_ms <= bar,
            f"{voice_slot.value}: first audio {spoken.first_audio_ms} ms (bar {bar} ms)",
        ),
        Check(
            "listening",
            error <= WER_BAR and speed >= SPEED_BAR,
            f"{ear_slot.value}: word error {error:.0%} on the test sentence (bar {WER_BAR:.0%}), "
            f"{speed:.1f}x real time (bar {SPEED_BAR:.0f}x)",
        ),
    ]
    return found


async def check_gate(key: str | None, probe: Probe) -> list[Check]:
    if key is None:
        return [Check("gate", None, "no key on this laptop yet (run the start script)")]
    health = f"/v1{HEALTH}"
    seen = {
        "no key": await probe(health, None),
        "wrong key": await probe(health, "x" * len(key)),
        "unknown address": await probe("/v1/nothing-here", key),
        "the key": await probe(health, key),
    }
    if seen["the key"] is None:
        return [
            Check("gate", False, "the gate is not answering on 127.0.0.1 (run the start script)")
        ]
    wanted = {"no key": 401, "wrong key": 401, "unknown address": 404, "the key": 200}
    ok = all(seen[k] == wanted[k] for k in wanted)
    words = ", ".join(f"{k}: {seen[k]}" for k in wanted)
    return [Check("gate", ok, words)]


async def run(
    calls: KitCalls,
    *,
    manager: ModelManager,
    vault: ClipVault,
    key: str | None,
    mp3: Mp3Encoder | None,
    probe: Probe = gate_probe,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Report:
    checks: list[Check] = []
    checks += check_models(manager)
    checks.append(await asyncio.to_thread(check_vault, vault))
    checks.append(await asyncio.to_thread(check_mp3, mp3))
    checks += await check_round_trip(calls)
    checks += await check_gate(key, probe)
    return Report(tuple(checks), now())


def report_json(report: Report) -> str:
    """The same report as JSON (for `selftest --json`)."""
    return json.dumps(
        {
            "kit_version": KIT_VERSION_NOW,
            "when": report.when.isoformat(),
            "checks": [{"name": c.name, "ok": c.ok, "words": c.words} for c in report.checks],
        },
        indent=2,
    )


__all__ = [
    "TEST_SENTENCE",
    "Check",
    "GateCalls",
    "KitCalls",
    "Report",
    "check_gate",
    "check_models",
    "check_mp3",
    "check_round_trip",
    "check_vault",
    "gate_probe",
    "report_json",
    "run",
    "word_error",
]
