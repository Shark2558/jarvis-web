# tests/test_r63_write.py -- R6.3 I0 seam 2 (docs/plans/r6-3-book-content.md D1, plan review M1,
# M2, L10): `jarvis.llm.write`, the Book writer's ONE model call. By tier, never another tier,
# never the laptop, no retry inside a call, a cut or length-stopped stream reported as such,
# BrainOff under No-AI, prices only through `jarvis.llm.pricing`; and its helpers in `jarvis.llm`
# only: `AnthropicProvider.no_retry()`, `StreamUsage.stop_reason` from both vendors' streams.
from __future__ import annotations

import json

import anthropic
import httpx
import httpx2
import pytest
from r63_fake_brains import (
    GOOD_DRAFT,
    RecordingLaptop,
    Step,
    busy,
    claude_like,
    custom_brain,
    cut,
    down,
    gemini_like,
    length_stop,
    paid_gemini,
    provider_of,
    registry,
    slow,
)

from jarvis.llm import pricing, write
from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import ChatMessage, LLMAuthError, Role, StreamUsage
from jarvis.llm.gemini_provider import GeminiProvider
from jarvis.llm.router import BrainOff, ModelTier
from jarvis.llm.write import WriterUnavailable, Written, write_text

MSGS = [ChatMessage(role=Role.USER, content="Write the page for C16.")]
BAL = ModelTier.BALANCED


async def _write(router: object, **kw: object) -> Written:
    args: dict[str, object] = {
        "tier": BAL,
        "system": "SYSTEM",
        "system_dynamic": None,
        "messages": MSGS,
        "max_tokens": 4000,
        "timeout_s": 5.0,
    }
    args.update(kw)
    return await write_text(router, **args)  # type: ignore[arg-type]


# ---- the call: by tier, the model reported, priced by the table ---------------------------------
async def test_the_model_reported_is_the_routers_balanced_model_and_priced_by_the_table() -> None:
    spec = claude_like(Step(text=GOOD_DRAFT, input_tokens=20_000, output_tokens=3_000))
    reg = registry(spec)
    got = await _write(reg.router_for("anthropic"))
    assert got.text == GOOD_DRAFT and got.complete and got.stop_reason == "end_turn"
    assert (got.model, got.provider, got.tier) == ("claude-sonnet-5-5", "anthropic", BAL)
    assert (got.usage.input_tokens, got.usage.output_tokens) == (20_000, 3_000)
    assert got.cost_usd == pricing.cost_usd("claude-sonnet-5-5", got.usage) == 0.07
    (call,) = provider_of(spec).calls
    assert call.model == "claude-sonnet-5-5" and call.max_tokens == 4000 and call.retries_off
    assert got.seconds >= 0


async def test_a_free_brain_reports_no_counts_and_is_estimated_at_zero_dollars() -> None:
    spec = gemini_like(Step(text=GOOD_DRAFT, input_tokens=None, stop="end_turn"))
    got = await _write(registry(claude_like(), spec).router_for("gemini"))
    assert got.model == "gemini-3.8-flash" and got.usage.estimated and got.cost_usd == 0.0
    assert got.complete


# ---- never another tier, never the laptop, no retry inside the call ------------------------------
async def test_a_transient_error_never_changes_tier_and_is_released() -> None:
    spec = claude_like(busy())
    with pytest.raises(WriterUnavailable) as err:
        await _write(registry(spec).router_for("anthropic"))
    assert err.value.why == "busy"
    calls = provider_of(spec).calls
    assert [c.model for c in calls] == ["claude-sonnet-5-5"] and calls[0].retries_off


async def test_an_unreachable_cloud_never_reaches_a_ready_laptop() -> None:
    laptop = RecordingLaptop()
    spec = claude_like(down())
    router = registry(spec, laptop=laptop).router_for("anthropic")
    with pytest.raises(WriterUnavailable) as err:
        await _write(router)
    assert err.value.why == "cloud_down" and laptop.calls == 0
    assert len(provider_of(spec).calls) == 1


async def test_an_open_breaker_refuses_before_any_call() -> None:
    laptop = RecordingLaptop()
    spec = claude_like()
    router = registry(spec, laptop=laptop).router_for("anthropic")
    router._breaker.trip()  # a recent cloud miss answered by the laptop (the chat's path)
    with pytest.raises(WriterUnavailable) as err:
        await _write(router)
    assert err.value.why == "cloud_down" and provider_of(spec).calls == [] and laptop.calls == 0


async def test_a_refused_key_is_unavailable_and_never_retried() -> None:
    spec = claude_like(Step(fail=LLMAuthError("the AI provider refused the key")))
    with pytest.raises(WriterUnavailable) as err:
        await _write(registry(spec).router_for("anthropic"))
    assert err.value.why == "refused" and len(provider_of(spec).calls) == 1


async def test_no_ai_mode_raises_brain_off_and_calls_nothing() -> None:
    spec = claude_like()
    router = registry(spec).router_for("anthropic")
    router.bind_blocked(lambda: True)
    with pytest.raises(BrainOff):
        await _write(router)
    assert provider_of(spec).calls == []


# ---- complete or not (L10) -----------------------------------------------------------------------
async def test_a_stream_cut_after_text_is_reported_cut_with_what_arrived() -> None:
    spec = claude_like(cut(GOOD_DRAFT, after=2))
    got = await _write(registry(spec).router_for("anthropic"))
    assert not got.complete and 0 < len(got.text) < len(GOOD_DRAFT)
    assert got.usage.input_tokens == 20_000 and got.usage.estimated  # input from message_start


async def test_our_own_timeout_reports_a_cut_call_never_unavailable() -> None:
    spec = claude_like(slow(GOOD_DRAFT, seconds=2.0))
    got = await _write(registry(spec).router_for("anthropic"), timeout_s=0.05)
    assert not got.complete and got.stop_reason is None
    assert got.usage.input_tokens == 20_000  # the call left: it may be billed (D8)


async def test_a_length_stop_is_not_complete() -> None:
    spec = claude_like(length_stop(GOOD_DRAFT))
    got = await _write(registry(spec).router_for("anthropic"))
    assert got.text == GOOD_DRAFT and not got.complete and got.stop_reason == "max_tokens"


async def test_a_stream_with_no_stop_reported_counts_as_complete() -> None:
    spec = gemini_like(Step(text=GOOD_DRAFT, input_tokens=None, stop=None))
    got = await _write(registry(claude_like(), spec).router_for("gemini"))
    assert got.complete and got.stop_reason is None


# ---- estimates, holds and the offer rule (M1, M2) ------------------------------------------------
def test_the_worst_case_hold_is_the_plans_figure() -> None:
    spec = claude_like()
    # 96,000 bytes / 2.5 = 38,400 tokens in, a 3,000-token system prompt at the cache-write price,
    # 4,000 out: US$0.1243 (D8: Rs 11.84 at Rs 95.24)
    usd = write.worst_usd(spec, BAL, 38_400, 4_000, system_cap=3_000)
    assert usd == pytest.approx(0.1243) and round(usd * 95.24, 2) == 11.84
    assert write.estimate_usd(spec, BAL, 16_000, 3_000) == pytest.approx(0.062)
    assert write.estimate_usd(gemini_like(), BAL, 16_000, 3_000) == 0.0


def test_only_a_priced_brain_is_offered() -> None:
    assert write.offered(claude_like()) and write.paid(claude_like())
    assert write.offered(gemini_like()) and not write.paid(gemini_like())
    assert not write.offered(paid_gemini())  # not training, $0 in the table: not offered (M2)
    assert not write.offered(custom_brain())  # its model has no price: not offered (M2)
    assert write.model_of(claude_like()) == "claude-sonnet-5-5"


# ---- the providers' halves, inside jarvis.llm only ----------------------------------------------
def test_anthropic_no_retry_is_a_view_with_no_retries() -> None:
    p = AnthropicProvider("sk-test", timeout_s=20, max_retries=2)
    view = p.no_retry()
    assert view is not p and view._client.max_retries == 0 and p._client.max_retries == 2
    assert view.name == "anthropic" and view.cache_history == p.cache_history


def _stream(p: object, sink: StreamUsage) -> object:
    return p.stream(system="s", messages=MSGS, model="m", max_tokens=5, usage=sink)  # type: ignore[attr-defined]


def _sse(*events: dict) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


def _anthropic_stream(stop: str) -> AnthropicProvider:
    start = {
        "type": "message_start",
        "message": {
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 120, "output_tokens": 1},
        },
    }
    block = {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}
    block["content_block"]["text"] = ""
    text = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta"}}
    text["delta"]["text"] = "Hello"
    end = {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}}
    end["usage"] = {"output_tokens": 9}
    body = _sse(start, block, text, {"type": "content_block_stop", "index": 0}, end)
    body += _sse({"type": "message_stop"})

    def handler(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    p = AnthropicProvider("sk-test", timeout_s=5, max_retries=0)
    p._client = anthropic.AsyncAnthropic(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return p


@pytest.mark.parametrize("stop", ["end_turn", "max_tokens"])
async def test_the_claude_stream_reports_its_stop_reason(stop: str) -> None:
    sink = StreamUsage()
    p = _anthropic_stream(stop)
    got = [d async for d in _stream(p, sink)]
    assert got == ["Hello"] and sink.stop_reason == stop and sink.final


@pytest.mark.parametrize(("reason", "said"), [("STOP", "end_turn"), ("MAX_TOKENS", "max_tokens")])
async def test_the_gemini_stream_reports_its_finish_reason(reason: str, said: str) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        chunks = [
            {"candidates": [{"content": {"parts": [{"text": "At your "}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "service."}]}, "finishReason": ""}]},
        ]
        chunks[1]["candidates"][0]["finishReason"] = reason
        sse = "".join(f"data: {json.dumps(c)}\r\n\r\n" for c in chunks)
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    sink = StreamUsage()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = GeminiProvider("AIza-test", client=client)
    got = [d async for d in _stream(p, sink)]
    assert "".join(got) == "At your service." and sink.stop_reason == said


def test_stream_usage_starts_with_no_stop_reason() -> None:
    assert StreamUsage().stop_reason is None
