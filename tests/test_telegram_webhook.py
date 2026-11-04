# tests/test_telegram_webhook.py -- R1 D1: POST /telegram/webhook. Outside /v1, no require_auth; the
# secret header is compared in constant time; a wrong or missing secret is a bare 401 and nothing
# is parsed; update_id is claimed create-only; everything accepted or ignored is a 200.
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from telegram_fakes import SECRET, TOKEN, World, build_world, dev_settings, message

from jarvis.api import create_app
from jarvis.api.telegram import WEBHOOK_PATH, install_telegram
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

HEADER = "X-Telegram-Bot-Api-Secret-Token"


async def _serve(w: World | None) -> AsyncIterator[AsyncClient]:
    from pydantic import SecretStr

    s = dev_settings(telegram_bot_token=SecretStr(TOKEN), telegram_webhook_secret=SecretStr(SECRET))
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    install_telegram(app)
    async with app.router.lifespan_context(app):
        if w is not None:
            app.state.telegram = w.service
            app.state.webhook_secret = SECRET
        else:
            app.state.telegram = None
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        c.app = app  # type: ignore[attr-defined]
        yield c
        await c.aclose()


@pytest.fixture
async def world() -> World:
    w = build_world()
    await w.pair()
    return w


@pytest.fixture
async def hook(world: World) -> AsyncIterator[AsyncClient]:
    async for c in _serve(world):
        yield c


def _post(
    c: AsyncClient, body: Any, *, secret: str | None = SECRET, raw: bytes | None = None
) -> Any:
    headers = {} if secret is None else {HEADER: secret}
    content = raw if raw is not None else json.dumps(body).encode()
    return c.post(
        WEBHOOK_PATH, content=content, headers={"content-type": "application/json", **headers}
    )


def test_path_is_outside_v1() -> None:
    assert WEBHOOK_PATH == "/telegram/webhook"


async def test_not_configured_is_a_404() -> None:
    async for c in _serve(None):
        r = await _post(c, message(1))
        assert r.status_code == 404


async def test_a_missing_or_wrong_secret_is_a_bare_401_and_nothing_is_handled(
    hook: AsyncClient, world: World
) -> None:
    for secret in (None, "wrong", SECRET[:-1], SECRET + "x", ""):
        r = await _post(hook, message(1, "hi"), secret=secret)
        assert r.status_code == 401 and r.content == b""
    assert world.provider.calls == [] and world.bot.calls == []
    assert world.audited("telegram_rejected") == []  # logged, not audited: a flood can't fill it
    assert await world.store.claim_update(1) is True  # not even claimed


async def test_the_secret_is_compared_in_constant_time() -> None:
    import inspect

    from jarvis.api import telegram as mod

    assert "compare_digest" in inspect.getsource(mod)


async def test_a_good_update_is_handled_and_answered(hook: AsyncClient, world: World) -> None:
    world.provider.script("Hello, Sir.")
    r = await _post(hook, message(1, "hi"))
    assert r.status_code == 200
    assert world.bot.texts == ["Hello, Sir."]


async def test_a_retry_of_the_same_update_is_a_no_op_200(hook: AsyncClient, world: World) -> None:
    assert (await _post(hook, message(1, "hi"))).status_code == 200
    assert (await _post(hook, message(1, "hi"))).status_code == 200
    assert len(world.provider.calls) == 1


async def test_garbage_and_unknown_updates_are_200(hook: AsyncClient, world: World) -> None:
    assert (await _post(hook, None, raw=b"not json")).status_code == 200
    assert (await _post(hook, {"update_id": 5, "edited_message": {}})).status_code == 200
    assert (await _post(hook, {"update_id": 6, "channel_post": {"x": 1}})).status_code == 200
    assert world.provider.calls == []


async def test_a_body_over_64_kb_is_refused_before_parsing(hook: AsyncClient, world: World) -> None:
    big = message(2, "x" * 70_000)
    r = await _post(hook, big)
    assert r.status_code == 413
    assert world.provider.calls == []


async def test_a_storage_failure_while_claiming_is_a_503_so_telegram_retries(
    hook: AsyncClient, world: World
) -> None:
    async def boom(_: int) -> bool:
        raise RuntimeError("firestore down")

    world.store.claim_update = boom  # type: ignore[method-assign]
    r = await _post(hook, message(3, "hi"))
    assert r.status_code == 503 and r.content == b""


async def test_an_internal_error_after_the_claim_is_still_a_200(
    hook: AsyncClient, world: World
) -> None:
    async def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("bug")

    world.brain.chat = boom  # type: ignore[method-assign]
    assert (await _post(hook, message(4, "hi"))).status_code == 200


async def test_the_token_never_reaches_the_logs(
    hook: AsyncClient, world: World, caplog: pytest.LogCaptureFixture
) -> None:
    world.bot.fail.add("sendMessage")
    with caplog.at_level(logging.DEBUG):
        await _post(hook, message(5, "hi"))
        await _post(hook, message(6, "hi"), secret="wrong")
    assert TOKEN not in caplog.text and SECRET not in caplog.text
    assert "api.telegram.org" not in caplog.text


async def test_the_webhook_needs_no_sign_in_but_v1_telegram_does() -> None:
    from pydantic import SecretStr

    s = dev_settings(
        telegram_bot_token=SecretStr(TOKEN),
        telegram_webhook_secret=SecretStr(SECRET),
        api_token=SecretStr("cli-token"),
    )
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    install_telegram(app)
    w = build_world()
    async with app.router.lifespan_context(app):
        app.state.telegram = w.service
        app.state.webhook_secret = SECRET
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            assert (await _post(c, message(1, "hi"))).status_code == 200
            assert (await c.get("/v1/telegram")).status_code == 401
