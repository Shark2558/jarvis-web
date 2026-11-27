# tests/test_r52_v1_server.py -- R5.2 V1: the kit's speech server over HTTP. Exactly the protocol's
# routes under /v1, the key on every request (constant time, fail closed with no key), bodies
# capped and parsed strictly, refusals as KitErrorBody with the seams' statuses, no-store, and
# nothing of a request (audio, text, the key) in the logs.
from __future__ import annotations

import base64
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from kit_fakes import ENGLISH_ONLY, KEY, FakeMp3, FakeTrainer, make_service, pcm, sha

from jarvis.localspeech import protocol as p
from jarvis.localspeech.server import STATUS, build_app
from jarvis.localspeech.service import KitService

AUTH = {"Authorization": f"Bearer {KEY}"}
SID = "vs_0123456789ab"


@pytest.fixture
async def kit(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, KitService]]:
    service, _ = make_service(tmp_path, mp3=FakeMp3(), trainer=FakeTrainer())
    app = build_app(service, KEY)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c, service
    await service.close()


def clip(prompt: str, audio: bytes, *, kind: str = "command", held_out: bool = True) -> dict:
    return {
        "session_id": SID,
        "prompt_id": prompt,
        "audio": p.encode_pcm(audio),
        "kind": kind,
        "held_out": held_out,
    }


async def test_the_server_serves_exactly_the_protocols_routes(kit) -> None:  # noqa: ANN001
    client, _ = kit
    app_routes = {
        (m, r.path)  # type: ignore[attr-defined]
        for r in client._transport.app.routes  # type: ignore[attr-defined]
        for m in r.methods - {"HEAD"}  # type: ignore[attr-defined]
    }
    assert app_routes == {(m, f"/v1{path}") for m, path in p.ROUTES}


async def test_every_route_needs_the_key(kit) -> None:  # noqa: ANN001
    client, _ = kit
    for method, path in p.ROUTES:
        url = "/v1" + path.format(job_id="job_0123456789ab")
        for headers in ({}, {"Authorization": "Bearer " + "x" * 40}, {"Authorization": KEY}):
            r = await client.request(method, url, headers=headers, content=b"{}")
            assert r.status_code == 401, (method, path)
            assert r.json()["error"] == "unauthorized"
            assert KEY not in r.text


async def test_a_server_without_a_proper_key_refuses_everything(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    for key in ("", "short-key"):
        app = build_app(service, key)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://x") as c:
            r = await c.get("/v1/health", headers={"Authorization": f"Bearer {key}"})
            assert r.status_code == 503 and r.json()["error"] == "unauthorized"


async def test_unknown_addresses_and_methods_are_404(kit) -> None:  # noqa: ANN001
    client, _ = kit
    for method, url in (("GET", "/v1/stt"), ("POST", "/v1/health"), ("GET", "/v1/models")):
        r = await client.request(method, url, headers=AUTH)
        assert r.status_code == 404 and r.json()["error"] == "not_found"
    r = await client.get("/v1/jobs/not-a-job", headers=AUTH)
    assert r.status_code == 404 and r.json()["error"] == "not_found"


async def test_health_answers_the_protocol_with_no_store(kit) -> None:  # noqa: ANN001
    client, _ = kit
    r = await client.get("/v1/health", headers=AUTH)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    health = p.KitHealth.model_validate_json(r.content)
    assert health.compatible and health.kit_version == "1.0.0"
    assert health.engine_for(p.Kind.STT, "en-IN") is p.EngineSlot.WHISPER_SMALL
    assert {e.slot for e in health.engines} == set(p.EngineSlot)


async def test_listening_and_speaking_over_http(kit) -> None:  # noqa: ANN001
    client, _ = kit
    req = p.SttRequest.of_pcm(pcm(1.0, 3), lang="en-IN", phrases=("JARVIS",))
    r = await client.post("/v1/stt", headers=AUTH, content=req.model_dump_json())
    heard = p.SttResult.model_validate_json(r.content)
    assert (heard.text, heard.slot, heard.seconds) == (
        "hello jarvis",
        p.EngineSlot.WHISPER_SMALL,
        1.0,
    )
    say = p.TtsRequest(lang="en-IN", text="Good evening, sir.")
    r = await client.post("/v1/tts", headers=AUTH, content=say.model_dump_json())
    spoken = p.TtsResult.model_validate_json(r.content)
    assert spoken.format is p.AudioFormat.PCM16 and spoken.sample_rate == 16_000
    assert spoken.voice == p.DEFAULT_ENGLISH_VOICE and spoken.slot is p.EngineSlot.KOKORO
    mp3 = p.TtsRequest(lang="en-IN", text="Good evening, sir.", format=p.AudioFormat.MP3)
    r = await client.post("/v1/tts", headers=AUTH, content=mp3.model_dump_json())
    assert p.TtsResult.model_validate_json(r.content).audio_bytes().startswith(b"ID3")


async def test_bad_bodies_are_refused_in_fixed_words_that_never_quote_them(kit) -> None:  # noqa: ANN001
    client, _ = kit
    secret = "my bank PIN is 4321"
    bodies = [
        b"not json " + secret.encode(),
        b'{"lang": "en-IN", "audio": "' + secret.encode() + b'"}',
        b'{"lang": "en-IN", "text": "hi", "extra": "' + secret.encode() + b'"}',
        b"[]",
    ]
    for body in bodies:
        r = await client.post("/v1/stt", headers=AUTH, content=body)
        assert r.status_code == 422 and r.json()["error"] == "bad_request"
        assert secret not in r.text and "4321" not in r.text


async def test_a_body_over_the_cap_is_413(kit) -> None:  # noqa: ANN001
    client, _ = kit
    r = await client.post("/v1/stt", headers=AUTH, content=b" " * (p.BODY_MAX + 1))
    assert r.status_code == 413 and r.json()["error"] == "too_large"

    async def chunks() -> AsyncIterator[bytes]:  # no Content-Length: counted while read
        for _ in range(4):
            yield b" " * 1_000_000

    r = await client.post("/v1/stt", headers=AUTH, content=chunks())
    assert r.status_code == 413


async def test_refusals_carry_the_seams_statuses(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path, ready=ENGLISH_ONLY - {p.EngineSlot.WHISPER_SMALL})
    app = build_app(service, KEY)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://x") as c:
        hindi = p.SttRequest.of_pcm(pcm(1.0), lang="hi-IN")
        r = await c.post("/v1/stt", headers=AUTH, content=hindi.model_dump_json())
        assert r.status_code == 503 and r.json()["error"] == "engine_not_ready"
        small = p.SttRequest.of_pcm(pcm(1.0), lang="en-IN", slot=p.EngineSlot.WHISPER_SMALL)
        r = await c.post("/v1/stt", headers=AUTH, content=small.model_dump_json())
        assert r.status_code == 503 and r.json()["error"] == "engine_not_ready"
        r = await c.post(
            "/v1/tts",
            headers=AUTH,
            content=p.TtsRequest(
                lang="en-IN", text="hi", format=p.AudioFormat.MP3
            ).model_dump_json(),
        )
        assert r.status_code == 503  # this kit has no MP3 encoder
    assert STATUS["unsupported_language"] == 422 and STATUS["busy"] == 503


async def test_the_session_flow_over_http(kit) -> None:  # noqa: ANN001
    client, service = kit
    for i in range(3):
        r = await client.post(
            "/v1/session/clip", headers=AUTH, json=clip(f"cmd_{i}", pcm(1.0, i + 1))
        )
        assert p.ClipStored.model_validate_json(r.content).clips == i + 1
    body = p.ScoreIn(session_id=SID, slots=(p.EngineSlot.WHISPER_SMALL,)).model_dump_json()
    r = await client.post("/v1/session/score", headers=AUTH, content=body)
    job = p.JobView.model_validate_json(r.content)
    await service.runner.wait(job.job_id)
    r = await client.get(f"/v1/jobs/{job.job_id}", headers=AUTH)
    assert p.JobView.model_validate_json(r.content).state is p.JobState.DONE
    r = await client.post("/v1/session/results", headers=AUTH, json={"session_id": SID})
    rows = p.SessionHeard.model_validate_json(r.content).rows
    assert [row.prompt_id for row in rows] == ["cmd_0", "cmd_1", "cmd_2"]
    r = await client.post("/v1/session/delete", headers=AUTH, json={"session_id": SID})
    assert p.Deleted.model_validate_json(r.content).clips == 3
    r = await client.post("/v1/session/results", headers=AUTH, json={"session_id": SID})
    assert p.SessionHeard.model_validate_json(r.content).rows == ()


async def test_the_wake_word_routes_reach_the_trainer(kit) -> None:  # noqa: ANN001
    client, service = kit
    await client.post(
        "/v1/session/clip",
        headers=AUTH,
        json=clip("wake_0", pcm(1.0, 9), kind="wake", held_out=False),
    )
    body = {"artifact": "verifier", "session_id": SID}
    job = p.JobView.model_validate_json(
        (await client.post("/v1/wakeword/train", headers=AUTH, json=body)).content
    )
    await service.runner.wait(job.job_id)
    status = await client.post("/v1/wakeword/status", headers=AUTH, json={})
    assert p.WakeStatus.model_validate_json(status.content).verifier is not None
    r = await client.post("/v1/wakeword/status", headers=AUTH, json={"anything": 1})
    assert r.status_code == 422
    model = await client.post("/v1/wakeword/model", headers=AUTH, json={"artifact": "verifier"})
    assert p.WakeModel.model_validate_json(model.content).licence == p.OWNER_LICENCE
    r = await client.post("/v1/wakeword/model", headers=AUTH, json={"artifact": "owned"})
    assert r.status_code == 404


async def test_nothing_of_a_request_is_logged(kit, caplog: pytest.LogCaptureFixture) -> None:  # noqa: ANN001
    client, service = kit
    caplog.set_level(logging.DEBUG)
    audio = pcm(1.0, 7)
    service.slots.stt(p.EngineSlot.WHISPER_SMALL)  # loaded first, so the request logs nothing new
    req = p.SttRequest.of_pcm(audio, lang="en-IN", phrases=("Ananya",))
    await client.post("/v1/stt", headers=AUTH, content=req.model_dump_json())
    await client.post("/v1/tts", headers=AUTH, json={"lang": "en-IN", "text": "Pay Ravi 500"})
    await client.post("/v1/stt", headers={"Authorization": "Bearer wrong"}, content=b"{}")
    text = caplog.text
    b64 = base64.b64encode(audio).decode()[:40]
    for leak in (KEY, b64, sha(audio), "Ananya", "Ravi", "hello jarvis", "Bearer"):
        assert leak not in text


async def test_an_unexpected_failure_is_a_plain_500(kit, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    client, service = kit

    async def boom() -> p.KitHealth:
        raise RuntimeError("C:\\Users\\someone\\secret path")

    monkeypatch.setattr(service, "health", boom)
    r = await client.get("/v1/health", headers=AUTH)
    assert r.status_code == 500 and r.json()["error"] == "internal"
    assert "secret" not in r.text and "Users" not in r.text
