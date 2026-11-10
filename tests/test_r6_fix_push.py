# tests/test_r6_fix_push.py -- R6 integrated review SEC-5: Web Push lands on the device a guest is
# holding during a show. While a guest lock holds the owner's consoles, push carries only the
# content-free line ("JARVIS has something for you."); Telegram is unchanged. A lock that can't be
# read counts as on (fail closed). After Resume, push carries the alert again.
from __future__ import annotations

from typing import Any

import pytest
from book_app_fakes import (
    CSRF,
    SECOND_OWNER,
    book_app,
    open_book,
    owner_uid,
    proof,
    register_passkey,
    sign_in,
)
from notify_fakes import NOON
from pydantic import SecretStr

from jarvis.alerts import AlertResult
from jarvis.api.book_lock import push_quiet
from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.notify.ports import Signal
from jarvis.notify.service import CONTENT_FREE_PUSH, NotifyService
from jarvis.notify.store import NotifyStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

UID = "u_0123456789abcdef"
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
SECRET = "Your blood pressure reading is 182/121"


class Pushes:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, uid: str, *, kind: str, text: str, silent: bool = False) -> int:
        self.sent.append((uid, kind, text))
        return 1


class Telegram:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, uid: str, text: str, **_kw: Any) -> AlertResult:
        self.sent.append(text)
        return AlertResult(True, "sent")


async def _service(quiet: Any) -> tuple[NotifyService, Pushes, Telegram]:
    pushes, tg = Pushes(), Telegram()
    store = NotifyStore(MemoryDocs(), Keyring(bytes(range(1, 33))))
    svc = NotifyService(
        store, AuditLog(), telegram=tg, push=pushes, now=lambda: NOON, push_quiet=quiet
    )
    return svc, pushes, tg


@pytest.mark.parametrize(("held", "pushed"), [(True, CONTENT_FREE_PUSH), (False, SECRET)])
async def test_push_says_nothing_while_a_guest_lock_holds_the_owner(
    held: bool, pushed: str
) -> None:
    async def quiet(uid: str) -> bool:
        return held

    svc, pushes, tg = await _service(quiet)
    signal = Signal(source="home", kind="vitals_critical", subject="blood pressure")
    delivery = await svc.notify(UID, signal, SECRET)
    assert delivery.push == 1
    assert pushes.sent == [(UID, "vitals_critical", pushed)]
    assert tg.sent == [SECRET]  # Telegram unchanged (D10: untouched by the lock)


async def test_a_lock_that_cant_be_read_keeps_push_content_free() -> None:
    async def quiet(uid: str) -> bool:
        raise RuntimeError("store down")

    svc, pushes, _ = await _service(quiet)
    await svc.notify(UID, Signal(source="home", kind="vitals_critical"), SECRET)
    assert [text for *_, text in pushes.sent] == [CONTENT_FREE_PUSH]
    assert SECRET not in CONTENT_FREE_PUSH and "{" not in CONTENT_FREE_PUSH


async def test_the_app_wires_push_to_the_guest_lock(settings: Settings) -> None:
    keyed = settings.model_copy(update={"token_key": SecretStr(KEY_B64)})  # notify needs the key
    async for app in book_app(keyed):
        assert app.state.notify is not None
        held = push_quiet(app)
        assert await app.state.notify.push_words(owner_uid(), SECRET) == SECRET
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            await open_book(c, auth, "guest")
            assert await held(owner_uid()) is True
            assert await held(owner_uid(SECOND_OWNER)) is True  # the lock holds him too
            words = await app.state.notify.push_words(owner_uid(), SECRET)
            assert words == CONTENT_FREE_PUSH
            lock_id = (await c.get("/v1/book/show/lock")).json()["id"]
            body = {"proof": await proof(c, auth, "book_resume", lock_id)}
            assert (await c.post("/v1/book/resume", json=body, headers=CSRF)).status_code == 200
            assert await app.state.notify.push_words(owner_uid(), SECRET) == SECRET
