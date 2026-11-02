# tests/browser/permissions_server.py — the real app for test_permissions.py:
# `python permissions_server.py <port>` (environment as test_permissions.py sets it: Google sign-in
# mode, JARVIS_PUBLIC_BASE_URL=http://localhost:<port> — WebAuthn needs a domain name, not an IP).
# Everything is real — /auth (cookie, re-sign-in window), /v1/permissions, /v1/passkeys, the
# gateway, approvals, py_webauthn — except two things: Google's half of sign-in (the redirect comes
# straight back saying "this is the owner, just authenticated") and the model (a mock that proposes
# an irreversible send when the owner types "send: <text>").
# Not a test module (pytest does not collect it).
from __future__ import annotations

import os
import sys
import time
from typing import Any

import uvicorn
from starlette.responses import RedirectResponse

from jarvis.api.app import create_app
from jarvis.llm.base import ChatMessage, ToolCall, ToolResultBlock
from jarvis.llm.mock_provider import MockProvider


class CommandProvider(MockProvider):
    """'send: <text>' → a send_message call (an irreversible approval card); 'batch: <n>' (slice
    11) → n create_reminder calls (reversible: cards on a spoken turn) and one send_message; after
    a tool result or an approval, a short plain reply; anything else is echoed like the mock."""

    def _reply(self, messages: list[ChatMessage]) -> tuple[str, list[ToolCall]]:
        last = messages[-1] if messages else None
        if last is not None and not isinstance(last.content, str):
            if any(isinstance(b, ToolResultBlock) for b in last.content):
                return "Noted, Sir.", []
        text = last.text().strip() if last is not None else ""
        if text.lower().startswith("batch:"):
            n = max(1, min(int(text[6:].strip() or "3"), 4))
            calls = [
                ToolCall(
                    id=f"b{len(self.calls)}_{i}",
                    name="create_reminder",
                    arguments={"text": f"reminder {i + 1}", "when": f"{17 + i}:00"},
                )
                for i in range(n)
            ]
            send = {"to": "priya@example.com", "body": "batch done"}
            return "", [
                *calls,
                ToolCall(id=f"s{len(self.calls)}", name="send_message", arguments=send),
            ]
        if text.lower().startswith("send:"):
            body = text[5:].strip() or "hello"
            call = ToolCall(
                id=f"s{len(self.calls)}",
                name="send_message",
                arguments={"to": "priya@example.com", "body": body},
            )
            return "", [call]
        return super()._reply(messages)


def main() -> None:
    port = int(sys.argv[1])
    app = create_app(provider=CommandProvider())
    owner = os.environ["JARVIS_OWNER_EMAILS"]

    async def to_google(request: Any, redirect_uri: str, **kw: Any) -> RedirectResponse:
        return RedirectResponse("/auth/callback?code=browser-test&state=browser-test", 302)

    async def from_google(request: Any) -> dict[str, Any]:
        return {
            "userinfo": {
                "email": owner,
                "email_verified": True,
                "sub": "1",
                "auth_time": int(time.time()),
            }
        }

    app.state.oauth.google.authorize_redirect = to_google
    app.state.oauth.google.authorize_access_token = from_google
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
