# tests/test_no_ai_errors.py
"""A stray model call in no-AI mode (BrainOff) is answered as what it is (R4 py-M2/M3): a 409
saying the AI is off, not "the AI service could not answer"; and the quiet paths skip it."""

from __future__ import annotations

from httpx import AsyncClient

from jarvis.api.app import friendly_llm_error
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import NO_AI_REFUSAL, BrainOff


def test_friendly_error_for_brain_off_says_the_ai_is_off() -> None:
    assert friendly_llm_error(BrainOff("x")) == NO_AI_REFUSAL


async def test_the_api_answers_brain_off_with_409(
    client: AsyncClient, provider: MockProvider
) -> None:
    async def boom(**_kw: object) -> None:
        raise BrainOff(NO_AI_REFUSAL)

    provider.complete = boom  # type: ignore[method-assign]

    r = await client.post("/v1/chat", json={"message": "hello"})

    assert r.status_code == 409
    assert r.json() == {"error": "brain_off", "detail": NO_AI_REFUSAL}
