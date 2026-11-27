# src/jarvis/voice/wakeword_api.py
"""R5.2 row 83 in the cloud: `WakewordHandlers`, V4's `WakewordApi` (`app.state.voice_wakeword`,
`jarvis.voice.profile_ports`), behind the owner-only routes of `jarvis.api.voice_profile_routes`:

    GET  /v1/voice/profile/wakeword           status: both stages, their jobs, what the console
                                              may use (`use_verifier`, `use_owned`), the licence
    POST /v1/voice/profile/wakeword/train     {"artifact": "verifier" | "owned"} -> the kit's job
    GET  /v1/voice/profile/wakeword/verifier  stage 1's JSON weights (only when it passed)
    GET  /v1/voice/profile/wakeword/model     stage 2's ONNX file (only when it beats today's)

The files come from the laptop kit through `KitClient` and pass straight through: the cloud
stores no wake-word file, audio or voice print (plan D4). Each file is checked before the console
gets it: the kit's hash and licence (`WakeModel`), the status it was announced with, its format,
and for stage 1 that it reads the very features the console computes. Nothing here approves
anything; a wake is only ever a wake (D6).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, ValidationError

from jarvis.localspeech.protocol import (
    OWNER_LICENCE,
    ArtifactInfo,
    JobView,
    KitClient,
    KitRefused,
    KitUnavailable,
    WakeArtifact,
    WakeModel,
    WakeStatus,
    WakeTrainIn,
)
from jarvis.localspeech.wakeword.formats import (
    CURRENT_LICENCE,
    EMBEDDING_MODEL,
    FEATURES_PERMISSIVE,
    LAUNCH_WORDS,
    OWNED_MAX_BYTES,
    OWNED_MEDIA,
    VERIFIER_MEDIA,
    VerifierFile,
    console_pins,
    manifest_sha256,
)
from jarvis.logging import get_logger
from jarvis.voice.profile import SessionState
from jarvis.voice.profile_ports import ProfileRefused, ProfileStore

log = get_logger(__name__)
NOT_SET_UP: Final = KitUnavailable("not_configured")
NO_SESSION: Final = "Record the voice session first: training needs your Hey Jarvis recordings."
BAD_BODY: Final = 'Send {"artifact": "verifier"} or {"artifact": "owned"}.'
NOT_PASSED: Final = "Your personal check did not pass its tests, so it is not used."
NOT_BETTER: Final = "Your own model has not beaten today's yet, so today's stays."
BAD_FILE: Final = "The laptop's wake-word file did not check out, so it was not used."


@lru_cache(maxsize=1)
def embedding_pin() -> str | None:
    """The console's embedding model's pinned SHA-256 (static/wakeword/MANIFEST.txt)."""
    return console_pins().get(EMBEDDING_MODEL)


class TrainBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: WakeArtifact


class WakewordView(BaseModel):
    """What the console's wake-word helper and the "Your voice" screen read."""

    model_config = ConfigDict(frozen=True)

    available: bool
    reason: str = ""  # why not (a `KitUnavailable` reason)
    words: str = ""
    session_ready: bool = False
    verifier: ArtifactInfo | None = None
    owned: ArtifactInfo | None = None
    jobs: tuple[JobView, ...] = ()
    use_verifier: bool = False
    use_owned: bool = False
    current_licence: str = CURRENT_LICENCE
    launch_ready: bool = False
    launch_words: str = LAUNCH_WORDS


def usable_verifier(info: ArtifactInfo | None) -> bool:
    return info is not None and info.licence == OWNER_LICENCE and info.beats_current is True


def usable_owned(info: ArtifactInfo | None) -> bool:
    return (
        info is not None
        and info.licence == OWNER_LICENCE
        and info.beats_current is True
        and info.size <= OWNED_MAX_BYTES
    )


def _unavailable(exc: KitUnavailable) -> ProfileRefused:
    if exc.reason == "busy":
        return ProfileRefused(409, "busy", str(exc))
    return ProfileRefused(503, "laptop_unavailable", str(exc))


def _refused(exc: KitRefused, *, missing: str) -> ProfileRefused:
    if exc.code == "not_found":
        return ProfileRefused(404 if missing == "not_trained" else 409, missing, exc.words)
    if exc.code == "busy":
        return ProfileRefused(409, "busy", exc.words)
    return ProfileRefused(422, "refused", exc.words)


class WakewordHandlers:
    """`WakewordApi` over the laptop kit (`kit` None: the kit is not set up on this server)."""

    def __init__(self, kit: KitClient | None, store: ProfileStore) -> None:
        self._kit, self._store = kit, store

    def _client(self) -> KitClient:
        if self._kit is None:
            raise _unavailable(NOT_SET_UP)
        return self._kit

    async def _status(self) -> WakeStatus:
        try:
            return await self._client().wakeword_status()
        except KitUnavailable as exc:
            raise _unavailable(exc) from None
        except KitRefused as exc:
            raise _refused(exc, missing="not_trained") from None

    async def status(self, uid: str) -> WakewordView:
        profile = await self._store.get(uid)
        ready = profile.session_id is not None and profile.state is not SessionState.NONE
        if self._kit is None:
            return WakewordView(
                available=False,
                reason=NOT_SET_UP.reason,
                words=str(NOT_SET_UP),
                session_ready=ready,
            )
        try:
            st = await self._kit.wakeword_status()
        except KitUnavailable as exc:
            return WakewordView(
                available=False, reason=exc.reason, words=str(exc), session_ready=ready
            )
        except KitRefused as exc:
            return WakewordView(
                available=False, reason="refused", words=exc.words, session_ready=ready
            )
        use_owned = usable_owned(st.owned)
        return WakewordView(
            available=True,
            session_ready=ready,
            verifier=st.verifier,
            owned=st.owned,
            jobs=st.jobs,
            use_verifier=usable_verifier(st.verifier),
            use_owned=use_owned,
            launch_ready=use_owned and FEATURES_PERMISSIVE,
        )

    async def train(self, uid: str, body: dict[str, Any]) -> JobView:
        try:
            asked = TrainBody.model_validate(body)
        except ValidationError:
            raise ProfileRefused(422, "input_rejected", BAD_BODY) from None
        profile = await self._store.get(uid)
        if profile.session_id is None or profile.state is SessionState.NONE:
            raise ProfileRefused(409, "no_session", NO_SESSION)
        req = WakeTrainIn(artifact=asked.artifact, session_id=profile.session_id)
        try:
            job = await self._client().wakeword_train(req)
        except KitUnavailable as exc:
            raise _unavailable(exc) from None
        except KitRefused as exc:
            raise _refused(exc, missing="nothing_to_train") from None
        log.info("wake word training started", extra={"artifact": asked.artifact.value})
        return job

    async def _file(self, artifact: WakeArtifact) -> WakeModel:
        try:
            return await self._client().wakeword_model(artifact)
        except KitUnavailable as exc:
            raise _unavailable(exc) from None
        except KitRefused as exc:
            raise _refused(exc, missing="not_trained") from None

    async def verifier(self, uid: str) -> tuple[bytes, str]:
        st = await self._status()
        if not usable_verifier(st.verifier) or st.verifier is None:
            raise ProfileRefused(409, "not_ready", NOT_PASSED)
        got = await self._file(WakeArtifact.VERIFIER)
        data = got.data_bytes()
        try:
            weights = VerifierFile.parse(data)
        except ValueError:
            raise self._bad("verifier") from None
        same = got.sha256 == st.verifier.sha256 and got.format == "json"
        if not same or got.licence != OWNER_LICENCE or weights.embedding_sha256 != embedding_pin():
            raise self._bad("verifier")
        return data, VERIFIER_MEDIA

    async def model(self, uid: str) -> tuple[bytes, str]:
        st = await self._status()
        if not usable_owned(st.owned) or st.owned is None:
            raise ProfileRefused(409, "not_better", NOT_BETTER)
        got = await self._file(WakeArtifact.OWNED)
        data = got.data_bytes()
        same = got.sha256 == st.owned.sha256 and got.format == "onnx"
        if not same or got.licence != OWNER_LICENCE or len(data) > OWNED_MAX_BYTES:
            raise self._bad("owned")
        if manifest_sha256(got.manifest) != got.sha256 or not data.startswith(b"\x08"):
            raise self._bad("owned")  # its MANIFEST names it; an ONNX file opens with ir_version
        return data, OWNED_MEDIA

    @staticmethod
    def _bad(artifact: str) -> ProfileRefused:
        log.warning("wake word file refused", extra={"artifact": artifact})
        return ProfileRefused(502, "bad_file", BAD_FILE)


__all__ = [
    "TrainBody",
    "WakewordHandlers",
    "WakewordView",
    "embedding_pin",
    "usable_owned",
    "usable_verifier",
]
