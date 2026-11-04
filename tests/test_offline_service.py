# tests/test_offline_service.py -- R1 C (D10-D12): the LocalFallback service. It answers for the
# router when the cloud is unreachable: only OFFLINE_TOOLS offered, the offline note added, other
# calls dropped, marked offline, metered at zero, alerts on switching on / off, honest status.
from __future__ import annotations

import json
from typing import Any

import pytest
from offline_fakes import KEY, MODEL, OWNER, T0, URL, Rig
from pydantic import SecretStr

from jarvis.core import channel
from jarvis.llm.base import ChatMessage, LLMError, Role, StreamUsage, ToolSpec
from jarvis.llm.fallback import CANT_OFFLINE, OFFLINE_NOTE, OFFLINE_TOOLS
from jarvis.llm.router import ModelTier
from jarvis.offline.service import OfflineRejected

MSGS = [ChatMessage(role=Role.USER, content="what is on today?")]


def _tool(name: str) -> ToolSpec:
    return ToolSpec(name=name, description="d", input_schema={"type": "object", "properties": {}})


def _kw(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tier": ModelTier.BALANCED,
        "system": "You are JARVIS.",
        "system_dynamic": "now: 9am",
        "messages": MSGS,
        "max_tokens": 200,
        "effort": None,
        "tools": None,
    }
    base.update(over)
    return base


def _call(name: str, **args: Any) -> dict[str, Any]:
    return {
        "id": "c1",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


@pytest.fixture(autouse=True)
def _fresh() -> None:
    channel.reset_offline()


# ---- ready ---------------------------------------------------------------------------------


async def test_not_configured_is_not_ready() -> None:
    rig = await Rig(configured=False).ready()
    assert await rig.svc.ready() is False


async def test_configured_but_switched_off_is_not_ready() -> None:
    rig = await Rig(enabled=False).ready()
    assert await rig.svc.ready() is False


async def test_configured_and_on_is_ready() -> None:
    assert await (await Rig().ready()).svc.ready() is True


# ---- complete ------------------------------------------------------------------------------


async def test_answers_with_the_laptop_marks_offline_and_costs_nothing() -> None:
    rig = await Rig().ready()
    c = await rig.svc.complete(**_kw())
    assert c.text == "Right away, Sir." and c.offline is True and c.cost_usd == 0.0
    assert c.model == MODEL
    assert channel.answered_offline() is True
    req = rig.laptop.requests[0]
    assert str(req.url) == f"{URL}/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert rig.laptop.chats()[0]["model"] == MODEL


async def test_every_tier_uses_the_one_configured_model() -> None:
    rig = await Rig().ready()
    for tier in ModelTier:
        await rig.svc.complete(**_kw(tier=tier))
    assert {b["model"] for b in rig.laptop.chats()} == {MODEL}


async def test_only_the_offline_tool_set_is_offered_and_no_r3() -> None:
    rig = await Rig().ready()
    offered = [
        _tool(n)
        for n in (*OFFLINE_TOOLS, "gmail_send", "calendar_delete_event", "send_message", "doc_read")
    ]
    await rig.svc.complete(**_kw(tools=offered))
    sent = [t["function"]["name"] for t in rig.laptop.chats()[0]["tools"]]
    assert sorted(sent) == sorted(OFFLINE_TOOLS) and len(sent) <= 12


async def test_a_turn_with_no_allowed_tool_sends_no_tools_field() -> None:
    rig = await Rig().ready()
    await rig.svc.complete(**_kw(tools=[_tool("gmail_send")]))
    assert "tools" not in rig.laptop.chats()[0]


async def test_the_offline_note_is_added_to_the_prompt() -> None:
    rig = await Rig().ready()
    await rig.svc.complete(**_kw())
    system = rig.laptop.chats()[0]["messages"][0]["content"]
    assert system.startswith("You are JARVIS.") and "now: 9am" in system and OFFLINE_NOTE in system


async def test_a_call_to_a_tool_outside_the_set_is_dropped_in_plain_words() -> None:
    rig = await Rig().ready()
    rig.laptop.reply = rig.laptop.completion("", [_call("gmail_send", to="a@b.c", body="hi")])
    c = await rig.svc.complete(**_kw(tools=[_tool("calendar_list_events")]))
    assert c.tool_calls == [] and CANT_OFFLINE in c.text


async def test_a_call_inside_the_set_survives() -> None:
    rig = await Rig().ready()
    rig.laptop.reply = rig.laptop.completion("", [_call("reminder_add", text="milk")])
    c = await rig.svc.complete(**_kw(tools=[_tool("reminder_add")]))
    assert [t.name for t in c.tool_calls] == ["reminder_add"]
    assert c.tool_calls[0].arguments == {"text": "milk"} and c.stop_reason == "tool_use"


async def test_a_dead_laptop_raises_and_does_not_mark_offline() -> None:
    rig = await Rig().ready()
    rig.laptop.up = False
    with pytest.raises(LLMError):
        await rig.svc.complete(**_kw())
    assert channel.answered_offline() is False
    assert (await rig.svc.status())["state"] == "unreachable"


async def test_a_slow_laptop_times_out_at_the_configured_limit() -> None:
    rig = await Rig(timeout_s=0.2).ready()
    rig.laptop.delay_s = 1.0
    with pytest.raises(LLMError):
        await rig.svc.complete(**_kw())


async def test_the_address_is_rechecked_before_every_call() -> None:
    rig = await Rig().ready()
    rig.resolver.box["ips"] = ["169.254.169.254"]  # the name now points inward
    with pytest.raises(LLMError):
        await rig.svc.complete(**_kw())
    assert rig.laptop.requests == []  # nothing was sent


async def test_switched_off_since_ready_still_refuses() -> None:
    rig = await Rig(enabled=False).ready()
    with pytest.raises(LLMError):
        await rig.svc.complete(**_kw())
    assert rig.laptop.requests == []


# ---- stream --------------------------------------------------------------------------------


async def test_stream_comes_from_the_laptop_and_marks_offline() -> None:
    rig = await Rig().ready()
    usage = StreamUsage()
    kw = _kw()
    kw.pop("tools")
    got = [d async for d in rig.svc.stream(usage=usage, **kw)]
    assert got == ["lap ", "top "] and channel.answered_offline() is True
    assert usage.reported and usage.output_tokens == 0
    assert rig.laptop.chats()[0]["stream"] is True and "tools" not in rig.laptop.chats()[0]


async def test_stream_from_a_dead_laptop_raises_before_any_text() -> None:
    rig = await Rig().ready()
    rig.laptop.up = False
    kw = _kw()
    kw.pop("tools")
    with pytest.raises(LLMError):
        async for _ in rig.svc.stream(usage=None, **kw):
            pass
    assert channel.answered_offline() is False


# ---- alerts --------------------------------------------------------------------------------


async def test_switching_on_alerts_the_owner_once() -> None:
    rig = await Rig().ready()
    await rig.svc.complete(**_kw())
    await rig.svc.complete(**_kw())
    assert [k for _, _, k in rig.alerts.sent] == ["offline_on"]
    uid, text, _ = rig.alerts.sent[0]
    assert uid == OWNER and 0 < len(text) <= 300 and KEY not in text


async def test_the_cloud_coming_back_alerts_off_once() -> None:
    rig = await Rig().ready()
    await rig.svc.cloud_ok()
    assert rig.alerts.sent == []  # was never offline: silence
    await rig.svc.complete(**_kw())
    await rig.svc.cloud_ok()
    await rig.svc.cloud_ok()
    assert [k for _, _, k in rig.alerts.sent] == ["offline_on", "offline_off"]


async def test_alerts_are_limited_to_one_per_kind_per_half_hour() -> None:
    rig = await Rig().ready()
    await rig.svc.complete(**_kw())
    await rig.svc.cloud_ok()
    rig.clock.t += 600
    await rig.svc.complete(**_kw())  # on again after 10 minutes: suppressed
    await rig.svc.cloud_ok()
    assert [k for _, _, k in rig.alerts.sent] == ["offline_on", "offline_off"]
    rig.clock.t += 1801
    await rig.svc.complete(**_kw())
    assert [k for _, _, k in rig.alerts.sent][-1] == "offline_on"


async def test_a_failing_alert_sink_never_breaks_the_answer() -> None:
    rig = await Rig().ready()
    rig.alerts.fail = True
    c = await rig.svc.complete(**_kw())
    assert c.offline is True


# ---- status --------------------------------------------------------------------------------


async def test_status_off_standby_active_and_back() -> None:
    off = await Rig(configured=False).ready()
    s = await off.svc.status()
    assert s["available"] is True and s["configured"] is False and s["state"] == "off"
    rig = await Rig(enabled=False).ready()
    assert (await rig.svc.status())["state"] == "off"
    rig = await Rig().ready()
    st = await rig.svc.status()
    assert st["state"] == "standby" and st["enabled"] is True
    await rig.svc.complete(**_kw())
    st = await rig.svc.status()
    assert st["state"] == "active" and st["last_used_at"] is not None
    await rig.svc.cloud_ok()
    assert (await rig.svc.status())["state"] == "standby"


async def test_status_never_carries_the_key_or_the_whole_url() -> None:
    rig = await Rig().ready()
    s = await rig.svc.status()
    assert s["host"] == "laptop.tail1234.ts.net" and s["model"] == MODEL
    dump = json.dumps(s, default=str)
    assert KEY not in dump and "/v1" not in dump and "https://" not in dump
    assert set(s) == {
        "available",
        "configured",
        "enabled",
        "host",
        "model",
        "state",
        "last_ok_at",
        "last_used_at",
    }


async def test_a_successful_answer_records_last_ok() -> None:
    rig = await Rig().ready()
    await rig.svc.complete(**_kw())
    cfg = await rig.store.get()
    assert cfg is not None and cfg.last_ok_at == T0
    assert (await rig.svc.status())["last_ok_at"] == T0.isoformat()


async def test_last_ok_is_not_rewritten_on_every_answer() -> None:
    rig = await Rig().ready()
    await rig.svc.complete(**_kw())
    writes = rig.docs.sets
    await rig.svc.complete(**_kw())
    assert rig.docs.sets == writes  # throttled to one write a minute
    rig.clock.t += 61
    await rig.svc.complete(**_kw())
    assert rig.docs.sets == writes + 1


# ---- configure / clear ---------------------------------------------------------------------


async def test_first_configuration_needs_url_key_and_model() -> None:
    rig = await Rig(configured=False).ready()
    for missing in ("url", "key", "model"):
        body = {"url": URL, "key": KEY, "model": MODEL}
        body.pop(missing)
        with pytest.raises(OfflineRejected) as ei:
            await rig.svc.configure(OWNER, **body)
        assert ei.value.status == 422
    assert await rig.store.get() is None


async def test_configure_saves_switched_off_until_told() -> None:
    rig = await Rig(configured=False).ready()
    s = await rig.svc.configure(OWNER, url=URL + "/", key=KEY, model=MODEL)
    assert s["configured"] is True and s["enabled"] is False and s["state"] == "off"
    cfg = await rig.store.get()
    assert cfg is not None and cfg.url == URL and cfg.set_by == OWNER


async def test_configure_rejects_a_bad_address_in_plain_words() -> None:
    rig = await Rig(configured=False).ready()
    with pytest.raises(OfflineRejected) as ei:
        await rig.svc.configure(OWNER, url="http://10.0.0.5:11434/v1", key=KEY, model=MODEL)
    assert ei.value.status == 422 and ei.value.code == "invalid_url"
    assert await rig.store.get() is None


async def test_configure_rejects_a_private_resolution() -> None:
    rig = await Rig(configured=False).ready()
    rig.resolver.box["ips"] = ["10.1.1.1"]
    with pytest.raises(OfflineRejected):
        await rig.svc.configure(OWNER, url=URL, key=KEY, model=MODEL)


@pytest.mark.parametrize(
    "key", ["short", "has space in it 0123456789", "bad\nkey0123456789abcd", "k" * 400]
)
async def test_configure_rejects_a_bad_key(key: str) -> None:
    rig = await Rig(configured=False).ready()
    with pytest.raises(OfflineRejected) as ei:
        await rig.svc.configure(OWNER, url=URL, key=key, model=MODEL)
    assert ei.value.code == "invalid_key" and key.strip() not in ei.value.detail


@pytest.mark.parametrize("model", ["", "bad model", "x;y", "a" * 100])
async def test_configure_rejects_a_bad_model(model: str) -> None:
    rig = await Rig(configured=False).ready()
    with pytest.raises(OfflineRejected) as ei:
        await rig.svc.configure(OWNER, url=URL, key=KEY, model=model)
    assert ei.value.code == "invalid_model"


async def test_changing_the_address_needs_the_key_again() -> None:
    rig = await Rig().ready()
    with pytest.raises(OfflineRejected) as ei:
        await rig.svc.configure(OWNER, url="https://other.tail1234.ts.net")
    assert ei.value.code == "invalid_key"  # the saved key is never sent to a new host unasked
    cfg = await rig.store.get()
    assert cfg is not None and cfg.url == URL


async def test_changing_only_the_model_or_the_switch_keeps_the_key() -> None:
    rig = await Rig(enabled=False).ready()
    s = await rig.svc.configure(OWNER, model="qwen2.5:3b", enabled=True)
    assert s["model"] == "qwen2.5:3b" and s["enabled"] is True
    cfg = await rig.store.get()
    assert cfg is not None and cfg.key.get_secret_value() == KEY and cfg.url == URL


async def test_switching_on_without_a_configuration_is_refused() -> None:
    rig = await Rig(configured=False).ready()
    with pytest.raises(OfflineRejected) as ei:
        await rig.svc.configure(OWNER, enabled=True)
    assert ei.value.status == 422


async def test_switching_off_clears_the_active_state() -> None:
    rig = await Rig().ready()
    await rig.svc.complete(**_kw())
    s = await rig.svc.configure(OWNER, enabled=False)
    assert s["state"] == "off"


async def test_clear_forgets_everything() -> None:
    rig = await Rig().ready()
    s = await rig.svc.clear(OWNER)
    assert s["configured"] is False and s["state"] == "off"
    assert await rig.store.get() is None and await rig.svc.ready() is False


# ---- test button ---------------------------------------------------------------------------


async def test_test_says_the_laptop_answered_with_the_model() -> None:
    rig = await Rig().ready()
    rig.laptop.models = [MODEL, "llama3.2:3b"]
    r = await rig.svc.test()
    assert r["ok"] is True and r["models"] == [MODEL, "llama3.2:3b"]
    assert r["detail"] == f"Your laptop answered (model {MODEL})."
    req = rig.laptop.requests[0]
    assert req.method == "GET" and str(req.url) == f"{URL}/models"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    cfg = await rig.store.get()
    assert cfg is not None and cfg.last_ok_at == T0


async def test_test_names_a_model_that_is_not_pulled() -> None:
    rig = await Rig().ready()
    rig.laptop.models = ["llama3.2:3b"]
    r = await rig.svc.test()
    assert r["ok"] is False and MODEL in r["detail"] and "ollama pull" in r["detail"]


async def test_test_accepts_a_latest_tag_for_a_bare_model_name() -> None:
    rig = await Rig().ready()
    await rig.store.put(url=URL, key=SecretStr(KEY), model="llama3.2", enabled=True, set_by=OWNER)
    rig.laptop.models = ["llama3.2:latest"]
    assert (await rig.svc.test())["ok"] is True


@pytest.mark.parametrize(
    ("status", "needle"),
    [(401, "key"), (403, "key"), (404, "gate"), (502, "Ollama"), (503, "Ollama")],
)
async def test_test_explains_each_failure_without_vendor_text(status: int, needle: str) -> None:
    rig = await Rig().ready()
    rig.laptop.status = status
    r = await rig.svc.test()
    assert r["ok"] is False and needle in r["detail"] and KEY not in json.dumps(r)
    assert r["models"] == []


async def test_test_when_the_laptop_is_asleep() -> None:
    rig = await Rig().ready()
    rig.laptop.up = False
    r = await rig.svc.test()
    assert r["ok"] is False and "awake" in r["detail"]
    assert (await rig.svc.status())["state"] == "unreachable"


async def test_test_times_out_in_five_seconds_at_most() -> None:
    import jarvis.offline.service as svc_mod

    assert svc_mod.TEST_TIMEOUT_S == 5.0


async def test_test_with_nothing_configured_says_so() -> None:
    rig = await Rig(configured=False).ready()
    r = await rig.svc.test()
    assert r["ok"] is False and "isn't set up" in r["detail"]
    assert rig.laptop.requests == []


async def test_test_refuses_a_name_that_now_points_inward() -> None:
    rig = await Rig().ready()
    rig.resolver.box["ips"] = ["127.0.0.1"]
    r = await rig.svc.test()
    assert r["ok"] is False and rig.laptop.requests == []


async def test_test_does_not_follow_a_redirect() -> None:
    rig = await Rig().ready()
    rig.laptop.status = 302
    r = await rig.svc.test()
    assert r["ok"] is False and len(rig.laptop.requests) == 1


async def test_a_second_after_ok_the_state_returns_to_standby() -> None:
    rig = await Rig().ready()
    rig.laptop.up = False
    await rig.svc.test()
    rig.laptop.up = True
    assert (await rig.svc.test())["ok"] is True
    assert (await rig.svc.status())["state"] == "standby"
