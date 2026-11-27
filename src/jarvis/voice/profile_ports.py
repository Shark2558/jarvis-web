# src/jarvis/voice/profile_ports.py
"""R5.2 ports (I0; docs/plans/r5-2-integration/I0-SEAMS.md): what each builder implements and the
routes in `jarvis.api.voice_profile_routes` call. Structural (`typing.Protocol`): a part never
imports another part's class.

- I0: `ProfileStore` (`jarvis.voice.profile_store.DocProfileStore` / `MemoryProfileStore`)
- V2: `LaptopApi` (`app.state.voice_laptop`): the kit's health for the console and Vitals
- V3: `ProfileApi` (`app.state.voice_profile_api`): the voice session and the profile
- V4: `WakewordApi` (`app.state.voice_wakeword`): the wake word's two stages
- the laptop kit itself: `jarvis.localspeech.protocol.KitClient` (V2's client; `MemoryKit` in tests)

Each route-facing method returns a JSON-able model or dict and raises `ProfileRefused` to refuse.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel

from jarvis.voice.profile import VoiceProfile

Answer = BaseModel | dict[str, Any]


class ProfileRefused(Exception):
    """A handler's refusal: the route answers `status` {error: code, detail: words}. Words are for
    the owner: never audio, a transcript, a voice print or a key. 402 `needs_yes` is the session's
    ₹ question (the Google comparison beyond the free minutes): the console asks, then re-sends
    with his YES."""

    def __init__(self, status: int, code: str, words: str) -> None:
        super().__init__(words)
        self.status, self.code, self.words = status, code, words


class ProfileStore(Protocol):
    async def get(self, uid: str) -> VoiceProfile: ...  # the default profile when none is stored

    async def save(self, uid: str, profile: VoiceProfile) -> VoiceProfile: ...

    async def update(
        self, uid: str, change: Callable[[VoiceProfile], VoiceProfile]
    ) -> VoiceProfile: ...  # read, change, write in one transaction

    async def delete(self, uid: str) -> bool: ...


class ProfileApi(Protocol):
    """V3's session and profile (`jarvis.voice.session` and its handlers)."""

    async def view(self, uid: str) -> Answer: ...  # the profile, engines ranked, the chosen one

    async def update(self, uid: str, body: dict[str, Any]) -> Answer: ...

    async def session(self, uid: str) -> Answer: ...  # prompts, blocks, progress

    async def start(self, uid: str, body: dict[str, Any]) -> Answer: ...

    async def put_clip(self, uid: str, prompt_id: str, body: dict[str, Any]) -> Answer: ...

    async def score(self, uid: str, body: dict[str, Any]) -> Answer: ...  # may refuse 402

    async def results(self, uid: str) -> Answer: ...

    async def recheck(self, uid: str, body: dict[str, Any]) -> Answer: ...  # "Check again"

    async def delete_recordings(self, uid: str) -> Answer: ...  # "Delete my recordings"


class LaptopApi(Protocol):
    """V2's view of the kit (`jarvis.voice.laptop`)."""

    async def status(self, uid: str) -> Answer: ...


class WakewordApi(Protocol):
    """V4's wake word: stage 1 the personal verifier, stage 2 the owned model."""

    async def status(self, uid: str) -> Answer: ...

    async def train(self, uid: str, body: dict[str, Any]) -> Answer: ...

    async def verifier(self, uid: str) -> tuple[bytes, str]: ...  # bytes, media type

    async def model(self, uid: str) -> tuple[bytes, str]: ...


__all__ = [
    "Answer",
    "LaptopApi",
    "ProfileApi",
    "ProfileRefused",
    "ProfileStore",
    "WakewordApi",
]
