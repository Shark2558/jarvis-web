# tests/test_r52_v4_wakeword_api.py -- R5.2 V4 (row 83): the cloud's `WakewordApi`
# (jarvis.voice.wakeword_api.WakewordHandlers) over a fake kit: status for the console, training
# from his session, and the two files passed through only when they check out (hash, licence,
# format, the features they read, stage 2 only when it beats today's). The cloud keeps nothing.
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from jarvis.api import voice_profile_routes as vr
from jarvis.config import Settings
from jarvis.localspeech.memory import MemoryKit
from jarvis.localspeech.protocol import (
    OWNER_LICENCE,
    ArtifactInfo,
    ClipIn,
    JobKind,
    KitRefused,
    PromptKind,
    WakeArtifact,
    WakeModel,
    WakeStatus,
    encode_pcm,
)
from jarvis.localspeech.wakeword import formats
from jarvis.localspeech.wakeword.formats import DataSource, ModelCard, VerifierFile, sha256_hex
from jarvis.localspeech.wakeword.onnx_write import Dense, mlp_onnx
from jarvis.voice.profile import SessionState, VoiceProfile
from jarvis.voice.profile_ports import ProfileRefused, WakewordApi
from jarvis.voice.profile_store import MemoryProfileStore
from jarvis.voice.wakeword_api import WakewordHandlers, embedding_pin

UID = "owner-1"
SESSION = "vs_0123456789ab"
NOW = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _verifier_bytes(**over: Any) -> bytes:
    fields: dict[str, Any] = {
        "embedding_sha256": embedding_pin(),
        "weights": tuple([0.001] * formats.FEATURES),
        "bias": -1.0,
        "trained_at": NOW,
        "clips": 25,
    }
    return VerifierFile.model_validate(fields | over).to_bytes()


def _owned_bytes() -> tuple[bytes, str]:
    data = mlp_onnx([Dense([0.0] * formats.FEATURES, [0.0], formats.FEATURES, 1, "sigmoid")])
    card = ModelCard(
        sha256=sha256_hex(data),
        size=len(data),
        trained_at=NOW,
        feature_models={formats.MEL_MODEL: "b" * 64},
        sources=(DataSource(name="his recordings", licence=OWNER_LICENCE),),
        beats_current=True,
    )
    return data, card.text()


class WakeKit(MemoryKit):
    """MemoryKit with wake-word files the test chooses (as the kit's service would serve them)."""

    def __init__(self) -> None:
        super().__init__()
        self.files: dict[WakeArtifact, tuple[bytes, ArtifactInfo, str, str]] = {}

    def give(
        self,
        artifact: WakeArtifact,
        data: bytes,
        *,
        beats: bool | None = True,
        manifest: str = "",
        fmt: str | None = None,
        sha: str | None = None,
    ) -> None:
        info = ArtifactInfo(
            artifact=artifact,
            sha256=sha or sha256_hex(data),
            size=len(data),
            trained_at=NOW,
            licence=OWNER_LICENCE,
            beats_current=beats,
        )
        default = "json" if artifact is WakeArtifact.VERIFIER else "onnx"
        self.files[artifact] = (data, info, manifest, fmt or default)

    async def wakeword_status(self) -> WakeStatus:
        self._enter("wakeword_status")
        found = {a: f[1] for a, f in self.files.items()}
        return WakeStatus(
            verifier=found.get(WakeArtifact.VERIFIER), owned=found.get(WakeArtifact.OWNED)
        )

    async def wakeword_model(self, artifact: WakeArtifact) -> WakeModel:
        self._enter("wakeword_model")
        if artifact not in self.files:
            raise KitRefused("not_found", "That wake-word file has not been trained yet.")
        data, _, manifest, fmt = self.files[artifact]
        return WakeModel(
            artifact=artifact,
            data=encode_pcm(data),
            format=fmt,  # type: ignore[arg-type]
            sha256=sha256_hex(data),
            licence=OWNER_LICENCE,
            manifest=manifest,
        )


async def _store(state: SessionState = SessionState.DONE) -> MemoryProfileStore:
    store = MemoryProfileStore()
    if state is not SessionState.NONE:
        await store.save(UID, VoiceProfile(state=state, session_id=SESSION))
    return store


async def _wake_clips(kit: MemoryKit, n: int = 3) -> None:
    for i in range(n):
        pcm = b"\x01\x00" * 8_000
        await kit.put_clip(
            ClipIn(
                session_id=SESSION,
                prompt_id=f"wake_{i}",
                audio=encode_pcm(pcm),
                kind=PromptKind.WAKE,
            )
        )


# ---- status -------------------------------------------------------------------------------------
async def test_it_is_the_wakeword_api_and_says_when_the_laptop_is_not_set_up() -> None:
    api = WakewordHandlers(None, await _store())
    seam: WakewordApi = api  # the I0 port, structurally
    view = await api.status(UID)
    assert view.available is False and view.reason == "not_configured"
    assert "not set up" in view.words and seam is api


async def test_status_says_what_the_console_may_use_and_the_launch_record() -> None:
    kit = WakeKit()
    kit.give(WakeArtifact.VERIFIER, _verifier_bytes())
    data, manifest = _owned_bytes()
    kit.give(WakeArtifact.OWNED, data, beats=False, manifest=manifest)
    view = await WakewordHandlers(kit, await _store()).status(UID)
    assert view.available and view.session_ready
    assert view.use_verifier is True and view.use_owned is False
    assert view.current_licence == "CC-BY-NC-SA-4.0" and view.launch_ready is False
    assert "before any launch" in view.launch_words
    kit.give(WakeArtifact.OWNED, data, beats=True, manifest=manifest)
    again = await WakewordHandlers(kit, await _store()).status(UID)
    assert again.use_owned is True
    assert again.launch_ready is False  # the feature models still need a permissive source


async def test_status_when_the_laptop_is_off_falls_back_quietly() -> None:
    kit = WakeKit()
    kit.down = "offline"
    view = await WakewordHandlers(kit, await _store(SessionState.NONE)).status(UID)
    assert view.available is False and view.reason == "offline" and not view.session_ready


# ---- training -----------------------------------------------------------------------------------
async def test_training_uses_his_session_and_returns_the_kits_job() -> None:
    kit = WakeKit()
    await _wake_clips(kit)
    job = await WakewordHandlers(kit, await _store()).train(UID, {"artifact": "verifier"})
    assert job.kind is JobKind.VERIFIER and "wakeword_train" in kit.calls


@pytest.mark.parametrize("body", [{}, {"artifact": "other"}, {"artifact": "owned", "x": 1}])
async def test_training_refuses_a_body_it_does_not_know(body: dict[str, Any]) -> None:
    with pytest.raises(ProfileRefused) as refused:
        await WakewordHandlers(WakeKit(), await _store()).train(UID, body)
    assert refused.value.status == 422 and refused.value.code == "input_rejected"


async def test_training_needs_a_session_and_says_what_the_kit_refused() -> None:
    kit = WakeKit()
    no_session = WakewordHandlers(kit, await _store(SessionState.NONE))
    with pytest.raises(ProfileRefused) as refused:
        await no_session.train(UID, {"artifact": "owned"})
    assert (refused.value.status, refused.value.code) == (409, "no_session")
    with pytest.raises(ProfileRefused) as empty:
        await WakewordHandlers(kit, await _store()).train(UID, {"artifact": "owned"})
    assert (empty.value.status, empty.value.code) == (409, "nothing_to_train")
    kit.down = "busy"
    with pytest.raises(ProfileRefused) as busy:
        await WakewordHandlers(kit, await _store()).train(UID, {"artifact": "owned"})
    assert (busy.value.status, busy.value.code) == (409, "busy")
    kit.down = "offline"
    with pytest.raises(ProfileRefused) as off:
        await WakewordHandlers(kit, await _store()).train(UID, {"artifact": "owned"})
    assert (off.value.status, off.value.code) == (503, "laptop_unavailable")
    with pytest.raises(ProfileRefused) as unset:
        await WakewordHandlers(None, await _store()).train(UID, {"artifact": "owned"})
    assert unset.value.status == 503


# ---- the files ----------------------------------------------------------------------------------
async def test_the_verifier_passes_through_only_when_it_checks_out() -> None:
    kit = WakeKit()
    api = WakewordHandlers(kit, await _store())
    with pytest.raises(ProfileRefused) as none:
        await api.verifier(UID)
    assert none.value.code == "not_ready"
    good = _verifier_bytes()
    kit.give(WakeArtifact.VERIFIER, good)
    assert await api.verifier(UID) == (good, "application/json")
    kit.give(WakeArtifact.VERIFIER, good, beats=False)
    with pytest.raises(ProfileRefused, match="did not pass"):
        await api.verifier(UID)


@pytest.mark.parametrize(
    "case",
    ["other features", "announced another file", "not json", "onnx format"],
)
async def test_a_verifier_that_does_not_check_out_never_reaches_the_console(case: str) -> None:
    kit = WakeKit()
    if case == "other features":
        kit.give(WakeArtifact.VERIFIER, _verifier_bytes(embedding_sha256="0" * 64))
    elif case == "announced another file":
        kit.give(WakeArtifact.VERIFIER, _verifier_bytes(), sha="1" * 64)
    elif case == "not json":
        kit.give(WakeArtifact.VERIFIER, b"\x08\x07not a verifier")
    else:
        kit.give(WakeArtifact.VERIFIER, _verifier_bytes(), fmt="onnx")
    with pytest.raises(ProfileRefused) as refused:
        await WakewordHandlers(kit, await _store()).verifier(UID)
    assert (refused.value.status, refused.value.code) == (502, "bad_file")


async def test_the_owned_model_passes_through_only_when_it_beats_todays() -> None:
    kit = WakeKit()
    api = WakewordHandlers(kit, await _store())
    data, manifest = _owned_bytes()
    kit.give(WakeArtifact.OWNED, data, beats=False, manifest=manifest)
    with pytest.raises(ProfileRefused) as worse:
        await api.model(UID)
    assert (worse.value.status, worse.value.code) == (409, "not_better")
    kit.give(WakeArtifact.OWNED, data, beats=True, manifest=manifest)
    assert await api.model(UID) == (data, "application/octet-stream")
    kit.give(WakeArtifact.OWNED, data, beats=True, manifest="no MANIFEST line")
    with pytest.raises(ProfileRefused) as unnamed:
        await api.model(UID)
    assert unnamed.value.code == "bad_file"
    kit.down = "timeout"
    with pytest.raises(ProfileRefused) as late:
        await api.model(UID)
    assert late.value.status == 503


async def test_a_file_the_kit_lost_is_not_trained() -> None:
    kit = WakeKit()
    kit.give(WakeArtifact.VERIFIER, _verifier_bytes())
    api = WakewordHandlers(kit, await _store())

    async def lost(artifact: WakeArtifact) -> WakeModel:
        raise KitRefused("not_found", "That wake-word file has not been trained yet.")

    kit.wakeword_model = lost  # type: ignore[method-assign]
    with pytest.raises(ProfileRefused) as missing:
        await api.verifier(UID)
    assert (missing.value.status, missing.value.code) == (404, "not_trained")


# ---- through the routes -------------------------------------------------------------------------
def test_the_routes_serve_the_handlers_owner_only_and_no_store(settings: Settings) -> None:
    s = settings.model_copy(update={"env": "prod", "api_token": SecretStr(TOKEN)})
    app = FastAPI()
    app.state.settings = s
    vr.install_voice_profile_routes(app)
    kit = WakeKit()
    good = _verifier_bytes()
    kit.give(WakeArtifact.VERIFIER, good)
    store = MemoryProfileStore()
    app.state.voice_wakeword = WakewordHandlers(kit, store)
    with TestClient(app) as c:
        status = c.get("/v1/voice/profile/wakeword", headers=AUTH)
        assert status.status_code == 200 and status.json()["use_verifier"] is True
        assert status.headers["cache-control"] == "no-store"
        weights = c.get("/v1/voice/profile/wakeword/verifier", headers=AUTH)
        assert weights.status_code == 200 and weights.content == good
        assert weights.headers["content-type"].startswith("application/json")
        assert c.get("/v1/voice/profile/wakeword/verifier").status_code == 401
        train = c.post("/v1/voice/profile/wakeword/train", json={"artifact": "x"}, headers=AUTH)
        assert train.status_code == 422 and train.json()["error"] == "input_rejected"
        model = c.get("/v1/voice/profile/wakeword/model", headers=AUTH)
        assert model.status_code == 409 and model.json()["error"] == "not_better"
        asked = c.post("/v1/voice/profile/wakeword/train", json={"artifact": "owned"}, headers=AUTH)
        assert asked.status_code == 409 and asked.json()["error"] == "no_session"  # no session yet
