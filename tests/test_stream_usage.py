# tests/test_stream_usage.py — slice 10 A2: a streamed reply is metered from the provider's own
# usage events; characters/4 is only the fallback, and it is flagged `estimated`.
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from billing_fakes import UID, PricedMock, billing, registry

from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest
from jarvis.llm.base import LLMTransientError, StreamUsage, Usage
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.pricing import cost_usd, estimate_usage, stream_usage
from jarvis.memory.inmemory import InMemorySessionStore

# ---- the sink and the pricing rule --------------------------------------------------------------


def test_nothing_reported_falls_back_to_the_character_estimate_and_says_so() -> None:
    u = stream_usage(StreamUsage(), input_chars=400, output_chars=81)
    assert u == estimate_usage(400, 81).model_copy(update={"estimated": True})
    assert u.input_tokens == 100 and u.output_tokens == 21 and u.estimated is True


def test_a_finished_stream_is_metered_exactly_including_the_cache() -> None:
    sink = StreamUsage()
    sink.started(input_tokens=120, output_tokens=1, cache_read_tokens=900, cache_write_tokens=30)
    sink.finished(output_tokens=57)
    u = stream_usage(sink, input_chars=99_999, output_chars=99_999)  # the estimate is ignored
    assert u == Usage(
        input_tokens=120, output_tokens=57, cache_read_tokens=900, cache_write_tokens=30
    )
    assert u.estimated is False and sink.reported and sink.final


def test_final_counts_replace_the_opening_ones_when_the_vendor_sends_them() -> None:
    sink = StreamUsage()
    sink.started(input_tokens=120, output_tokens=1, cache_read_tokens=0, cache_write_tokens=0)
    sink.finished(output_tokens=40, input_tokens=125, cache_read_tokens=10, cache_write_tokens=5)
    u = stream_usage(sink, input_chars=0, output_chars=0)
    assert (u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens) == (
        125,
        40,
        10,
        5,
    )


def test_a_stream_cut_short_meters_the_exact_input_and_estimates_the_output() -> None:
    sink = StreamUsage()
    sink.started(input_tokens=300, output_tokens=1, cache_read_tokens=2000, cache_write_tokens=0)
    u = stream_usage(sink, input_chars=10, output_chars=400)  # 100 tokens had arrived
    assert u.input_tokens == 300 and u.cache_read_tokens == 2000  # exact: message_start came
    assert u.output_tokens == 100 and u.estimated is True  # the closing count never came


def test_vendor_numbers_are_never_negative() -> None:
    sink = StreamUsage()
    sink.started(input_tokens=-5, output_tokens=-1, cache_read_tokens=-2, cache_write_tokens=-3)
    sink.finished(output_tokens=-9)
    u = stream_usage(sink, input_chars=0, output_chars=0)
    assert u == Usage()


def test_usage_is_exact_unless_flagged_including_turns_stored_before() -> None:
    assert Usage().estimated is False
    assert Usage.model_validate({"input_tokens": 1}).estimated is False  # turns stored before


# ---- through the Brain --------------------------------------------------------------------------


@dataclass
class ReportingStream(PricedMock):
    """A paid brain whose stream reports usage like Anthropic's: counts at the start, the final
    output count at the end. `fail_after_start` raises before any text (a provider error)."""

    opening: tuple[int, int, int] = (200, 1500, 40)  # input, cache read, cache write
    closing_output: int = 33
    fail_after_start: bool = False
    gap_s: float = 0.0
    seen_sinks: list[StreamUsage | None] = field(default_factory=list)

    async def stream(  # type: ignore[override]
        self, *, usage: StreamUsage | None = None, **kw: object
    ) -> AsyncIterator[str]:
        self.seen_sinks.append(usage)
        i, cr, cw = self.opening
        if usage is not None:
            usage.started(
                input_tokens=i, output_tokens=1, cache_read_tokens=cr, cache_write_tokens=cw
            )
        if self.fail_after_start:
            raise LLMTransientError("overloaded")
        async for chunk in MockProvider.stream(self, **kw):  # type: ignore[arg-type]
            yield chunk
            if self.gap_s:
                await asyncio.sleep(self.gap_s)
        if usage is not None:
            usage.finished(output_tokens=self.closing_output)


def _brain(settings: Settings, paid: MockProvider) -> tuple[Brain, InMemorySessionStore]:
    brains = registry(paid=paid)
    store = InMemorySessionStore()
    return Brain(brains=brains, store=store, settings=settings, billing=billing(brains)), store


def _req(text: str = "stream please") -> ChatRequest:
    return ChatRequest(message=text, user_id=UID)


async def test_a_streamed_reply_is_metered_from_the_vendor_usage(settings: Settings) -> None:
    paid = ReportingStream()
    brain, store = _brain(settings, paid)
    text = "".join([d async for d in brain.chat_stream(_req())])
    assert "stream please" in text and isinstance(paid.seen_sinks[0], StreamUsage)
    exact = Usage(input_tokens=200, output_tokens=33, cache_read_tokens=1500, cache_write_tokens=40)
    want = cost_usd("claude-sonnet-5-5", exact)
    (summary,) = await store.list_for_user(UID)
    session = await store.get(summary.id)
    assert session is not None
    reply = session.turns[-1]
    assert reply.usage == exact and reply.usage.estimated is False
    assert reply.cost_usd == pytest.approx(want) and session.total_output_tokens == 33
    u = await brain.billing.meter.get(UID, "2026-11")
    assert u.calls == 1 and u.inr_total == pytest.approx(want * 95.24, rel=1e-3)


async def test_a_stream_without_usage_is_flagged_as_an_estimate(settings: Settings) -> None:
    brain, store = _brain(settings, PricedMock())  # reports nothing, like Gemini today
    "".join([d async for d in brain.chat_stream(_req())])
    (summary,) = await store.list_for_user(UID)
    session = await store.get(summary.id)
    assert session is not None
    reply = session.turns[-1]
    assert reply.usage is not None and reply.usage.estimated is True
    assert reply.usage.output_tokens > 0 and reply.cost_usd > 0


async def test_a_stream_the_owner_left_meters_the_exact_input(settings: Settings) -> None:
    paid = ReportingStream(gap_s=0.01)
    brain, _ = _brain(settings, paid)
    gen = brain.chat_stream(_req("a long answer please " * 5))
    assert await gen.__anext__()
    await gen.aclose()
    u = await brain.billing.meter.get(UID, "2026-11")
    sink = paid.seen_sinks[0]
    assert sink is not None and sink.final is False
    floor = cost_usd(
        "claude-sonnet-5-5", Usage(input_tokens=200, cache_read_tokens=1500, cache_write_tokens=40)
    )
    assert u.calls == 1 and u.inr_total >= floor * 95.24 * 0.999


async def test_a_provider_error_after_the_start_still_meters_the_input(
    settings: Settings,
) -> None:
    paid = ReportingStream(fail_after_start=True)
    brain, _ = _brain(settings, paid)
    with pytest.raises(LLMTransientError):
        async for _ in brain.chat_stream(_req()):
            pass
    u = await brain.billing.meter.get(UID, "2026-11")
    assert u.calls == 1 and u.inr_total > 0  # the vendor billed the prompt it had read
