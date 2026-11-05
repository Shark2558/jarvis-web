# src/jarvis/telegram/client.py
"""Telegram Bot API over httpx (R1 D1). The token sits in the URL path, so this client logs method
names only, never a URL, and raises `TelegramError` with our own words (no exception text, no
Telegram description): `from None`, so no chained httpx error carries the address either."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import SecretStr

from jarvis.logging import get_logger

log = get_logger(__name__)
API = "https://api.telegram.org"
MAX_RESPONSE_BYTES = 1_000_000
TIMEOUT_S = 15.0
CAPTION_MAX = 1024  # Telegram's limit for a photo caption


class TelegramError(Exception):
    """A Bot API call failed. The message names the method and our own reason only."""

    def __init__(self, method: str, reason: str) -> None:
        super().__init__(f"Telegram {method} failed: {reason}")
        self.method = method
        self.reason = reason


class TelegramClient:
    def __init__(
        self,
        token: SecretStr,
        *,
        http: httpx.AsyncClient | None = None,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self._token = token
        self._http = http or httpx.AsyncClient(follow_redirects=False)
        self._timeout = timeout_s
        self._username: str | None = None

    def __repr__(self) -> str:
        return "TelegramClient()"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        return await self._call(method, json=payload or {})

    async def _call(self, method: str, **body: Any) -> Any:
        url = f"{API}/bot{self._token.get_secret_value()}/{method}"
        try:
            status, raw = await self._read(url, **body)
        except httpx.HTTPError as exc:
            log.warning(
                "telegram call failed", extra={"method": method, "error": type(exc).__name__}
            )
            raise TelegramError(method, "could not reach Telegram") from None
        if raw is None:
            log.warning("telegram answer too large", extra={"method": method})
            raise TelegramError(method, "answer too large")
        if status != 200:
            log.warning("telegram call refused", extra={"method": method, "status": status})
            raise TelegramError(method, f"HTTP {status}")
        try:
            body = json.loads(raw)
        except ValueError:
            raise TelegramError(method, "unreadable answer") from None
        if not isinstance(body, dict) or body.get("ok") is not True:
            code = body.get("error_code") if isinstance(body, dict) else None
            log.warning("telegram call not ok", extra={"method": method, "code": code})
            raise TelegramError(method, "Telegram said no")
        return body.get("result")

    async def _read(self, url: str, **body: Any) -> tuple[int, bytes | None]:
        """(status, body); body None when it passed the size cap. Streams, so a huge answer is
        never held whole: reading stops at the cap."""
        async with self._http.stream(
            "POST", url, timeout=self._timeout, follow_redirects=False, **body
        ) as resp:
            size = 0
            parts: list[bytes] = []
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    return resp.status_code, None
                parts.append(chunk)
            return resp.status_code, b"".join(parts)

    async def send_message(
        self, chat_id: int, text: str, *, buttons: list[tuple[str, str]] | None = None
    ) -> int:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": label, "callback_data": data} for label, data in buttons]
                ]
            }
        result = await self.call("sendMessage", payload)
        mid = result.get("message_id") if isinstance(result, dict) else None
        return mid if isinstance(mid, int) else 0

    async def send_photo(self, chat_id: int, jpeg: bytes, caption: str) -> None:
        """R3 D12 (I1): one small JPEG with a burglar alert, only after the owner's opt-in.
        `protect_content` stops forwarding and saving in Telegram's apps. The bytes go out in this
        request and are dropped: never stored, logged or audited (errors name the method only)."""
        await self._call(
            "sendPhoto",
            data={
                "chat_id": str(chat_id),
                "caption": caption[:CAPTION_MAX],
                "protect_content": "true",
            },
            files={"photo": ("alert.jpg", jpeg, "image/jpeg")},
        )

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        await self.call("answerCallbackQuery", payload)

    async def edit_buttons(self, chat_id: int, message_id: int) -> None:
        """Remove the inline buttons of a message (it was decided)."""
        await self.call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
        )

    async def get_me(self) -> str:
        """The bot's username (cached)."""
        if self._username is None:
            result = await self.call("getMe")
            name = result.get("username") if isinstance(result, dict) else None
            if not isinstance(name, str) or not name:
                raise TelegramError("getMe", "no username")
            self._username = name
        return self._username

    async def webhook_info(self) -> dict[str, Any]:
        """{registered, pending, last_error}: last_error is our own sentence, never Telegram's."""
        result = await self.call("getWebhookInfo")
        info = result if isinstance(result, dict) else {}
        pending = info.get("pending_update_count")
        return {
            "registered": bool(info.get("url")),
            "pending": pending if isinstance(pending, int) else 0,
            "last_error": "Telegram could not deliver the last update."
            if info.get("last_error_message")
            else None,
        }


__all__ = ["TelegramClient", "TelegramError"]
