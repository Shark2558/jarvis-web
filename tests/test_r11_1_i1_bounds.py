# tests/test_r11_1_i1_bounds.py -- R11.1 I1: settings whose bounds must agree with what the code
# can really do (INTEGRATION-B 3.3: the attach setting and ChatRequest's field; INTEGRATION-A 3.13:
# the working output cap and a tool loop that does not stream).
from __future__ import annotations

import pytest
from pydantic import ValidationError

from jarvis.config import Settings
from jarvis.core.models import ChatRequest


def _le(field: str) -> int:
    return next(m.le for m in Settings.model_fields[field].metadata if hasattr(m, "le"))


def test_the_attach_setting_never_allows_more_than_a_message_carries() -> None:
    most = next(
        m.max_length
        for m in ChatRequest.model_fields["attachments"].metadata
        if hasattr(m, "max_length")
    )
    assert _le("attach_max_files") == most == 10
    with pytest.raises(ValidationError):
        ChatRequest(message="hi", attachments=[f"a{i}" for i in range(11)])
    with pytest.raises(ValidationError):
        Settings(_env_file=None, attach_max_files=11)  # type: ignore[call-arg]
    assert Settings(_env_file=None, attach_max_files=10).attach_max_files == 10  # type: ignore[call-arg]


def test_the_attachments_field_says_its_own_number() -> None:
    desc = ChatRequest.model_fields["attachments"].description or ""
    assert "at most 10" in desc and "at most 3" not in desc


def test_the_working_output_cap_stays_where_a_non_streaming_call_is_accepted() -> None:
    """The tool loop does not stream; above about 21,000 output tokens a non-streaming vendor
    call is refused, so the setting stops at 32,000 (code review A L2)."""
    assert _le("work_output_tokens") == 32_000
    assert Settings(_env_file=None, work_output_tokens=32_000).work_output_tokens == 32_000  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, work_output_tokens=32_001)  # type: ignore[call-arg]
