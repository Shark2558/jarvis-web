# src/jarvis/telegram/service.py
"""The Telegram front door (R1 D1-D5; Layer 1 surface). `TelegramService.handle(update)`:

* claims `update_id` create-only first, so a retry is a no-op (a storage failure here raises: the
  route answers 503 and Telegram tries again);
* accepts input only from the paired owner: `from.id` and `chat.id` both match the binding, the chat
  is private and the sender is not a bot. Anyone else never reaches the brain, gets no reply and is
  audited as `telegram_rejected` (args hash only; at most 20 an hour, then log only);
* pairing: `/start <code>` from a private, non-bot sender; `/unpair` and `/new` from the owner;
* a chat turn is an ordinary `Brain.chat` with `channel="telegram"` inside `telegram_turn()`;
* R2 cards proposed in the conversation get Approve / Decline buttons (from.id, the card's scope and
  `tool_risk == reversible` are all checked); R3 is NEVER approvable here: "Waiting in the console
  for your approval (and passkey)" plus an `approval_waiting` alert.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from jarvis.billing import BudgetReached
from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ActionRisk, InputRejected
from jarvis.core.models import ChatRequest, ChatResponse, PendingApproval
from jarvis.llm.base import LLMError
from jarvis.logging import get_logger
from jarvis.memory.base import SessionNotFound
from jarvis.telegram.alerts import ALERT_TEXT, TelegramAlerts
from jarvis.telegram.client import TelegramClient, TelegramError
from jarvis.telegram.format import reply_messages
from jarvis.telegram.models import CallbackQuery, Chat, Message, TelegramLink, Update, User
from jarvis.telegram.store import TelegramStore
from jarvis.tools.audit import AuditTrail

if TYPE_CHECKING:
    from jarvis.core.brain import Brain

log = get_logger(__name__)
MAX_MESSAGES_PER_WINDOW = 20
MESSAGE_WINDOW_S = 600
REJECTED_AUDIT_PER_HOUR = 20
CARD_CHARS = 240
R3_REFUSAL = True  # read at call time; only the eval negative control switches it off
_CALLBACK = re.compile(r"([ad]):([A-Za-z0-9_-]{1,64})")

WELCOME = (
    "Paired. Ask me anything. Replies here are plain text, and anything that can't be undone waits "
    "for your approval in the console. Telegram keeps bot chats on its servers, so email, Drive, "
    "documents and contacts stay off here unless you switch them on in Integrations. "
    "/new starts a fresh conversation; /unpair disconnects this account."
)
NON_TEXT = "I can read text messages only for now."
TOO_MANY = (
    "That's a lot of messages in a short time. Slow down a little and try again in a few minutes."
)
TOO_LONG = "That message is too long for me. Please shorten it and try again."
FRESH = "Fresh conversation started."
UNPAIRED = "Unpaired. This Telegram account no longer reaches JARVIS. Pair again from the console."
BUDGET = "The monthly AI limit has been reached. Open the console to change it."
UNAVAILABLE = "The AI service is busy or unavailable right now. Please try again in a minute."
FAILED = "Something went wrong on my side. Please try again."
CONSOLE_ONLY = "Approve in the console: this one can't be approved from Telegram."
GONE = "That request was already handled or has expired."
OTHER_CONVERSATION = "That request belongs to another conversation. Open the console to handle it."
WAITING = "Waiting in the console for your approval (and passkey): "


def _utc() -> datetime:
    return datetime.now(UTC)


def _one_line(text: str, limit: int = CARD_CHARS) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


class TelegramService:
    def __init__(
        self,
        client: TelegramClient,
        store: TelegramStore,
        audit: AuditTrail,
        *,
        brain: Brain | None = None,
        clock: Callable[[], datetime] = _utc,
        alerts: TelegramAlerts | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.audit = audit
        self.brain = brain
        self.alerts = alerts or TelegramAlerts(client, store, audit)
        self._clock = clock
        self._recent: dict[str, list[float]] = {}
        self._rejected = (-1, 0)  # (hour bucket, audited so far)

    def bind(self, brain: Brain) -> None:
        """Late wiring: the Brain is built after this service."""
        self.brain = brain

    # ---- entry ------------------------------------------------------------------------------

    async def handle(self, update: Update) -> None:
        if not await self.store.claim_update(update.update_id):
            return  # a retry of an update already taken
        try:
            if update.message is not None:
                await self._message(update.message)
            elif update.callback_query is not None:
                await self._callback(update.callback_query)
        except Exception as exc:  # noqa: BLE001 - Telegram must still get its 200
            log.error("telegram update failed", extra={"error": type(exc).__name__})

    # ---- who is this ------------------------------------------------------------------------

    @staticmethod
    def _eligible(sender: User | None, chat: Chat | None) -> bool:
        return (
            sender is not None and chat is not None and not sender.is_bot and chat.type == "private"
        )

    async def _owner(
        self, sender: User | None, chat: Chat | None
    ) -> tuple[str, TelegramLink] | None:
        """(uid, link) when this is exactly the paired owner in the paired private chat."""
        if not self._eligible(sender, chat):
            return None
        assert sender is not None and chat is not None
        uid = await self.store.uid_for(sender.id)
        link = await self.store.get(uid) if uid else None
        if uid and link and link.tg_user_id == sender.id and link.chat_id == chat.id:
            return uid, link
        return None

    async def _reject(self, sender: User | None, chat: Chat | None, why: str) -> None:
        bucket = int(self._clock().timestamp() // 3600)
        seen_bucket, count = self._rejected
        if seen_bucket != bucket:
            count = 0
        if count >= REJECTED_AUDIT_PER_HOUR:
            self._rejected = (bucket, count)
            log.warning("telegram sender rejected (not audited: hourly cap)", extra={"why": why})
            return
        self._rejected = (bucket, count + 1)
        try:
            await self.audit.append(
                agent="telegram",
                tool="telegram_rejected",
                risk=ActionRisk.READ_ONLY,
                outcome="rejected",
                args={"from": sender.id if sender else None, "chat": chat.id if chat else None},
                detail=why,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("AUDIT WRITE FAILED for a rejection", extra={"error": type(exc).__name__})

    async def _audit(self, tool: str, outcome: str, uid: str) -> None:
        try:
            await self.audit.append(
                agent="telegram",
                tool=tool,
                risk=ActionRisk.REVERSIBLE,
                outcome=outcome,
                args={"user": uid},
            )
        except Exception as exc:  # noqa: BLE001 - it already happened
            log.error("AUDIT WRITE FAILED", extra={"tool": tool, "error": type(exc).__name__})

    async def _say(
        self, chat_id: int, text: str, buttons: list[tuple[str, str]] | None = None
    ) -> None:
        try:
            await self.client.send_message(chat_id, text, buttons=buttons)
        except TelegramError:
            pass  # the client already logged the method; nothing to tell the owner

    # ---- messages ---------------------------------------------------------------------------

    async def _message(self, msg: Message) -> None:
        sender, chat = msg.sender, msg.chat
        text = (msg.text or "").strip() if msg.text is not None else None
        command = text.split()[0].split("@")[0].lower() if text and text.startswith("/") else ""
        owner = await self._owner(sender, chat)
        if owner is None:
            await self._stranger(sender, chat, text, command)
            return
        uid, link = owner
        if text is None or not text:
            await self._say(chat.id, NON_TEXT)
        elif command == "/unpair":
            await self.store.unpair(uid)
            await self._audit("telegram_unpaired", "unpaired", uid)
            await self._say(chat.id, UNPAIRED)
        elif command == "/new":
            await self.store.set_session(uid, None)
            await self._say(chat.id, FRESH)
        elif command == "/start":
            await self._say(chat.id, WELCOME)
        else:
            await self._chat(uid, link, text)

    async def _stranger(
        self, sender: User | None, chat: Chat, text: str | None, command: str
    ) -> None:
        if command == "/start" and text and self._eligible(sender, chat):
            assert sender is not None
            parts = text.split(maxsplit=1)
            uid = (
                await self.store.finish_pairing(parts[1], tg_user_id=sender.id, chat_id=chat.id)
                if len(parts) == 2
                else None
            )
            if uid is not None:
                await self._audit("telegram_paired", "paired", uid)
                await self._say(chat.id, WELCOME)
                return
        await self._reject(sender, chat, "not the paired owner")

    def _allowed_now(self, uid: str) -> bool:
        now = self._clock().timestamp()
        recent = [t for t in self._recent.get(uid, []) if now - t < MESSAGE_WINDOW_S]
        if len(recent) >= MAX_MESSAGES_PER_WINDOW:
            self._recent[uid] = recent
            return False
        self._recent[uid] = [*recent, now]
        return True

    async def _chat(self, uid: str, link: TelegramLink, text: str) -> None:
        brain = self.brain
        if brain is None:
            await self._say(link.chat_id, UNAVAILABLE)
            return
        if len(text) > brain.s.max_input_chars:
            await self._say(link.chat_id, TOO_LONG)
            return
        if not self._allowed_now(uid):
            await self._say(link.chat_id, TOO_MANY)
            return
        resp = await self._ask(brain, uid, link, text)
        if resp is None:
            return
        await self._deliver(uid, link, resp)

    async def _ask(
        self, brain: Brain, uid: str, link: TelegramLink, text: str
    ) -> ChatResponse | None:
        sid = link.session_id
        for attempt in (0, 1):
            req = ChatRequest(message=text, session_id=sid, user_id=uid, channel="telegram")
            try:
                with telegram_turn():
                    return await brain.chat(req)
            except SessionNotFound:
                if attempt == 1 or sid is None:
                    break
                sid = None  # the stored conversation is gone: start a new one
            except InputRejected:
                await self._say(link.chat_id, TOO_LONG)
                return None
            except BudgetReached:
                await self._say(link.chat_id, BUDGET)
                return None
            except LLMError:
                await self._say(link.chat_id, UNAVAILABLE)
                return None
            except Exception as exc:  # noqa: BLE001
                log.error("telegram turn failed", extra={"error": type(exc).__name__})
                break
        await self._say(link.chat_id, FAILED)
        return None

    async def _deliver(self, uid: str, link: TelegramLink, resp: ChatResponse) -> None:
        if resp.session_id != link.session_id:
            await self.store.set_session(uid, resp.session_id)
        for part in reply_messages(resp):
            await self._say(link.chat_id, part)
        await self._propose(uid, link, resp.pending_approvals)

    async def _propose(self, uid: str, link: TelegramLink, cards: list[PendingApproval]) -> None:
        for card in cards:
            line = _one_line(card.summary)
            if card.tool_risk == ActionRisk.REVERSIBLE.value:
                await self._say(
                    link.chat_id,
                    f"{line}\n\nApprove or decline?",
                    [("Approve", f"a:{card.id}"), ("Decline", f"d:{card.id}")],
                )
                continue
            await self._say(link.chat_id, WAITING + line)  # R3 or unknown: the console only
            await self.alerts.send(uid, ALERT_TEXT["approval_waiting"], kind="approval_waiting")

    # ---- buttons ----------------------------------------------------------------------------

    async def _callback(self, cq: CallbackQuery) -> None:
        chat = cq.message.chat if cq.message else None
        owner = await self._owner(cq.sender, chat)
        if owner is None or chat is None:
            await self._reject(cq.sender, chat, "button from someone else")
            return
        uid, link = owner
        try:
            await self.client.answer_callback(cq.id)
        except TelegramError:
            pass
        found = _CALLBACK.fullmatch(cq.data or "")
        brain = self.brain
        if found is None or brain is None or brain.gateway is None:
            return
        approve, approval_id = found.group(1) == "a", found.group(2)
        action = await brain.gateway.gate.get(approval_id)
        if action is None:
            await self._say(chat.id, GONE)
            return
        if link.session_id is None or action.scope != f"{uid}:{link.session_id}":
            await self._say(chat.id, OTHER_CONVERSATION)
            return
        if (
            R3_REFUSAL and action.tool_risk is not ActionRisk.REVERSIBLE
        ):  # R3 or unknown: never here
            await self._say(chat.id, CONSOLE_ONLY)
            return
        try:
            with telegram_turn():
                resp = (
                    await brain.approve(approval_id, session_id=link.session_id, user_id=uid)
                    if approve
                    else await brain.decline(approval_id, session_id=link.session_id, user_id=uid)
                )
        except LookupError:
            await self._say(chat.id, GONE)
            return
        except Exception as exc:  # noqa: BLE001
            log.error("telegram decision failed", extra={"error": type(exc).__name__})
            await self._say(chat.id, FAILED)
            return
        if cq.message is not None:
            try:
                await self.client.edit_buttons(chat.id, cq.message.message_id)
            except TelegramError:
                pass
        await self._deliver(uid, link, resp)


__all__ = ["MAX_MESSAGES_PER_WINDOW", "REJECTED_AUDIT_PER_HOUR", "TelegramService"]
