# tests/test_r51_out_of_credit.py -- R5.1 I1 (brief §3): Anthropic's "credit balance is too low"
# answer (HTTP 400, invalid_request_error) is its own state at every layer, in fixed words, never
# the vendor's text: jarvis.llm raises LLMOutOfCredit and the router remembers "no_credit"; the
# systems check's brain probe is down "the AI account is out of credit"; the briefing says paid
# replies pause; the Vitals Claude key is red "is out of credit" with the top-up fix; the chat
# answer says the account has no credit.
from __future__ import annotations

import anthropic
import httpx2 as httpx
import pytest
from fallback_fakes import KW, TIERS, CloudProvider
from r51b_fakes import Brain, OwnRig

from jarvis.api.app import friendly_llm_error
from jarvis.health import probes as P
from jarvis.health.briefing import compose_briefing
from jarvis.health.models import HealthReport, ProbeResult
from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import ChatMessage, LLMError, LLMOutOfCredit, Role
from jarvis.llm.router import BrainHealth, ModelRouter, ModelTier
from jarvis.vitals.own import OwnSources

VENDOR = (
    "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing "
    "to upgrade or purchase credits."
)
TOP_UP = "Top up at console.anthropic.com → Plans & billing"
MSGS = [ChatMessage(role=Role.USER, content="x")]
UID = "u_owner"


def _provider(status: int, err_type: str, message: str) -> AnthropicProvider:
    def handler(_: httpx.Request) -> httpx.Response:
        body = {"type": "error", "error": {"type": err_type, "message": message}}
        return httpx.Response(status, json=body)

    p = AnthropicProvider("sk-test", timeout_s=5, max_retries=0)
    p._client = anthropic.AsyncAnthropic(  # noqa: SLF001 - the real SDK over a fake transport
        api_key="sk-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return p


# ---- jarvis.llm ---------------------------------------------------------------------------------
async def test_the_low_credit_answer_is_its_own_error_in_fixed_words() -> None:
    with pytest.raises(LLMOutOfCredit) as got:
        await _provider(400, "invalid_request_error", VENDOR).complete(
            system="s", messages=MSGS, model="m", max_tokens=5
        )
    assert str(got.value) == "the AI account is out of credit"
    assert "Plans & Billing" not in str(got.value) and "too low" not in str(got.value)


async def test_the_low_credit_answer_while_streaming_too() -> None:
    p = _provider(400, "invalid_request_error", VENDOR)
    with pytest.raises(LLMOutOfCredit):
        _ = [d async for d in p.stream(system="s", messages=MSGS, model="m", max_tokens=5)]


@pytest.mark.parametrize(
    ("status", "err_type", "message"),
    [
        (400, "invalid_request_error", "max_tokens: 99999999 > 64000"),  # another bad request
        (400, "invalid_request_error", ""),
        (402, "billing_error", "a credit balance mentioned in some other error"),  # not a 400
    ],
)
async def test_other_bad_requests_stay_plain_errors(
    status: int, err_type: str, message: str
) -> None:
    with pytest.raises(LLMError) as got:
        await _provider(status, err_type, message).complete(
            system="s", messages=MSGS, model="m", max_tokens=5
        )
    assert not isinstance(got.value, LLMOutOfCredit)


async def test_the_router_remembers_no_credit_and_does_not_retry_or_degrade() -> None:
    cloud = CloudProvider(LLMOutOfCredit(), LLMOutOfCredit(), LLMOutOfCredit())
    r = ModelRouter(cloud, TIERS)
    with pytest.raises(LLMOutOfCredit):
        await r.complete(tier=ModelTier.STRONG, **KW)
    assert r.health() == BrainHealth(state="no_credit", on_laptop=False)
    assert len(cloud.models) == 1  # the same account answers every tier: no second paid try


def test_the_chat_answer_says_the_account_has_no_credit() -> None:
    line = friendly_llm_error(LLMOutOfCredit())
    assert "no credit" in line and "Plans" not in line


# ---- the systems check --------------------------------------------------------------------------
async def test_the_brain_probe_is_down_out_of_credit() -> None:
    async def ai(uid: str) -> str:
        return "ai"

    probe = P.brain_probe(lambda: BrainHealth(state="no_credit", on_laptop=False), ai)
    out = await probe.check(UID)
    assert out is not None and out.status == "down"
    assert out.reason == P.BRAIN_NO_CREDIT == "the AI account is out of credit"


def test_the_briefing_says_paid_replies_pause_and_how_to_top_up() -> None:
    brain = ProbeResult(key="brain", label="brain", status="down", reason=P.BRAIN_NO_CREDIT, at=1.0)
    b = compose_briefing(HealthReport(overall="down", results=(brain,), at=1.0), None)
    assert "The AI brain is out of credit — paid AI replies pause" in b.spoken
    (concern,) = b.concerns
    assert concern.key == "brain" and "paid AI replies pause" in concern.impact
    assert concern.fix == TOP_UP + "."
    assert "is not answering" not in b.spoken  # it answers: the account has no credit


def test_any_other_brain_fault_keeps_its_r51_words() -> None:
    brain = ProbeResult(key="brain", label="brain", status="down", reason="x", at=1.0)
    b = compose_briefing(HealthReport(overall="down", results=(brain,), at=1.0), None)
    assert "The AI brain is not answering — JARVIS can't think" in b.spoken


# ---- Vitals -------------------------------------------------------------------------------------
async def test_the_claude_key_is_red_out_of_credit_with_the_top_up_fix() -> None:
    rig = OwnRig(OwnSources(claude=Brain("no_credit")))
    board = await rig.svc.board(UID)
    v = next(v for v in board.items if v.provider.id == "brain_claude")
    assert (v.status, v.reason) == ("red", "is out of credit")
    assert v.fix == TOP_UP
    assert "paid AI replies" in v.impact and "pause" in v.impact
