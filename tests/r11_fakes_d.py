# tests/r11_fakes_d.py -- R11 Part D (kitchen) fakes, shared by tests/test_r11_d_*.py and
# evals/r11_helpers/kitchen.py. I0's shared fakes (`tests/r11_fakes.py`) are imported, never copied.
#
# - `keyring()`: a Keyring on fixed test bytes (never a real key).
# - `brains(...)`: a BrainRegistry whose private brain answers from a script (and, optionally, a
#   default brain that may train on what it is told, which recipes must never use).
# - `Rules`: an `OwnerRules` with a fixed row (ALLOW / ASK / DENY for a tool pattern) or a failure.
# - `MailBox`: a fake Gmail that serves the `.eml` fixtures in tests/fixtures/r11/ with their own
#   headers (Authentication-Results included), as `format=full` messages.
# - `kctx(...)`: a kitchen HelperContext with whatever the test needs switched on.
from __future__ import annotations

import base64
import dataclasses
import email
import email.policy
import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr
from r11_fakes import UID, Clock, FakeNotifier, ctx, reads_over

from jarvis.billing import Billing, BudgetStore, FxRates, UsageMeter
from jarvis.helpers.ports import HelperContext
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import GoogleTokens, MemoryTokenStore
from jarvis.keyring import Keyring
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.offline.mode import BrainMode
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.policy import Effect, PolicyRule

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "r11"
PRIVATE = {
    ModelTier.FAST: "claude-haiku-5-5",
    ModelTier.BALANCED: "claude-sonnet-5-5",
    ModelTier.STRONG: "claude-opus-5-5",
}
FREE = {t: "gemini-3.8-flash" for t in ModelTier}
GMAIL = "/gmail/v1/users/me/messages"
CARD = "4111 1111 1111 1111"  # the well-known test card number, planted in a fixture
CARD_DIGITS = CARD.replace(" ", "")


def keyring() -> Keyring:
    return Keyring(bytes(range(7, 39)))


def recipe_json(title: str, *ingredients: tuple[str, int], diet: str = "veg") -> str:
    return json.dumps(
        {
            "title": title,
            "cuisine": "Kerala",
            "diet": diet,
            "minutes": 30,
            "ingredients": [{"name": n, "grams": g} for n, g in ingredients],
            "steps": ["Wash and chop.", "Cook gently.", "Serve hot."],
        }
    )


DAL = recipe_json("Dal tadka", ("toor dal", 150), ("onion", 80), ("tomato", 100))
CHICKEN = recipe_json("Chicken curry", ("chicken", 400), ("onion", 80))


def brains(
    *replies: str, train_default: bool = False, private: bool = True
) -> tuple[BrainRegistry, MockProvider, MockProvider]:
    """(registry, private provider, training provider). `train_default`: the default brain is
    the one that may learn from what it is told; `private=False`: there is no other."""
    safe, free = MockProvider(name="private"), MockProvider(name="training")
    safe.script(*replies)
    free.script(*replies)
    specs = [BrainSpec("gemini", "Gemini (free)", free, FREE, trains_on_content=True)]
    if private:
        specs.append(BrainSpec("anthropic", "Claude", safe, PRIVATE))
    default = "gemini" if train_default or not private else "anthropic"
    return BrainRegistry(specs, default_id=default), safe, free


def billing(reg: BrainRegistry, docs: MemoryDocs, clock: Clock) -> Billing:
    return Billing(
        fx=FxRates(docs=None, default_rate=95.24, http=None, clock=clock),
        meter=UsageMeter(docs, tz="Asia/Kolkata"),
        budgets=BudgetStore(docs),
        brains=reg,
        clock=clock,
    )


@dataclasses.dataclass
class Rules:
    """`OwnerRules`: `effect` for every tool matching `pattern`, or `fail` (raises)."""

    pattern: str = "*"
    effect: Effect | None = None
    fail: bool = False

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        if self.fail:
            raise RuntimeError("the permission rows can't be read")
        if self.effect is None:
            return []
        return [PolicyRule(tool_pattern=self.pattern, effect=self.effect, source="owner")]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def eml(name: str) -> dict[str, Any]:
    """One .eml fixture as Gmail's `format=full` message (headers as written, one text part)."""
    raw = (FIXTURES / name).read_bytes()
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    headers = [{"name": k, "value": str(v)} for k, v in msg.items()]
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body is not None else ""
    mime = body.get_content_type() if body is not None else "text/plain"
    payload = {
        "mimeType": mime,
        "headers": headers,
        "body": {"data": _b64(text.encode()), "size": len(text)},
    }
    return {"id": re.sub(r"[^A-Za-z0-9_-]", "_", Path(name).stem), "payload": payload}


@dataclasses.dataclass
class MailBox:
    """Serves `messages.list` (every mail, newest first; `page` mails a page with Gmail's
    `nextPageToken`) and `messages.get` (`fail_read` ids answer 500). `on_request` sees every
    request first (a test's clock moves there)."""

    names: Sequence[str] = ()
    fail_list: int | None = None
    page: int | None = None
    fail_read: set[str] = dataclasses.field(default_factory=set)
    on_request: Callable[[httpx.Request], None] | None = None
    requests: list[httpx.Request] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        self.mails = [eml(n) for n in self.names]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def reads(self) -> int:
        return sum(1 for r in self.requests if r.url.path.startswith(GMAIL + "/"))

    def lists(self) -> int:
        return sum(1 for r in self.requests if r.url.path == GMAIL)

    def _listing(self, request: httpx.Request) -> httpx.Response:
        if self.fail_list:
            return httpx.Response(self.fail_list, json={"error": {"message": "fake"}})
        start = int(request.url.params.get("pageToken") or 0)
        size = self.page or len(self.mails) or 1
        rows = [{"id": m["id"]} for m in self.mails[start : start + size]]
        body: dict[str, Any] = {"messages": rows}
        if start + size < len(self.mails):
            body["nextPageToken"] = str(start + size)
        return httpx.Response(200, json=body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.on_request is not None:
            self.on_request(request)
        path = request.url.path
        if request.method != "GET":
            return httpx.Response(599, json={"error": "a read-only fake got a write"})
        if path == GMAIL:
            return self._listing(request)
        if path.rsplit("/", 1)[-1] in self.fail_read:
            return httpx.Response(500, json={"error": {"message": "fake"}})
        found = next((m for m in self.mails if path == f"{GMAIL}/{m['id']}"), None)
        if found is None:
            return httpx.Response(404, json={"error": {"message": "no such mail"}})
        return httpx.Response(200, json=found)


async def connector(http: httpx.AsyncClient, uid: str = UID) -> GoogleConnector:
    store = MemoryTokenStore()
    tokens = GoogleTokens(
        email="owner@example.com",
        access_token=SecretStr("not-a-token"),
        refresh_token=SecretStr("not-a-refresh-token"),
        expires_at=4_000_000_000.0,
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.readonly",
        ],
    )
    await store.put(uid, tokens)
    return GoogleConnector(store, client_id="cid", client_secret=SecretStr("s"), http=http)


def kctx(
    *,
    sealed: bool = True,
    reg: BrainRegistry | None = None,
    metered: bool = True,
    no_ai: bool = False,
    google: GoogleConnector | None = None,
    rules: Rules | None = None,
    **over: Any,
) -> tuple[HelperContext, FakeNotifier, MemoryDocs, Clock]:
    """A kitchen context on fakes: sealed (a keyring) unless told otherwise; `reg` brains with
    billing (unless `metered=False`); `no_ai` = the owner's switch is off."""
    c, notifier, docs, clock = ctx("kitchen", **over)
    mode = BrainMode(c.settings.model_copy(update={"brain_mode": "none" if no_ai else "ai"}))
    c = dataclasses.replace(
        c,
        keyring=keyring() if sealed else None,
        brains=reg,
        billing=billing(reg, docs, clock) if reg is not None and metered else None,
        brain_mode=mode,
        google=google,
        permissions=(lambda: rules) if rules is not None else (lambda: None),
        reads=reads_over(lambda: rules, c.audit, now=clock),
    )
    return c, notifier, docs, clock


__all__ = [
    "CARD",
    "CARD_DIGITS",
    "CHICKEN",
    "DAL",
    "FIXTURES",
    "MailBox",
    "Rules",
    "brains",
    "connector",
    "eml",
    "kctx",
    "keyring",
    "recipe_json",
]
