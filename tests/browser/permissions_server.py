# tests/browser/permissions_server.py — the real app for test_permissions.py:
# `python permissions_server.py <port>` (environment as test_permissions.py sets it, including
# JARVIS_PUBLIC_BASE_URL=http://localhost:<port>: WebAuthn needs a domain name, not 127.0.0.1).
# Everything is real — /v1/permissions, /v1/passkeys, the gateway, approvals, py_webauthn — except
# the model: a mock that proposes an irreversible send when the owner types "send: <text>".
# Not a test module (pytest does not collect it).
from __future__ import annotations

import sys

import uvicorn

from jarvis.api.app import create_app
from jarvis.llm.base import ChatMessage, ToolCall, ToolResultBlock
from jarvis.llm.mock_provider import MockProvider


class CommandProvider(MockProvider):
    """'send: <text>' → a send_message call (an irreversible approval card); after a tool result
    or an approval, a short plain reply; anything else is echoed like the mock brain."""

    def _reply(self, messages: list[ChatMessage]) -> tuple[str, list[ToolCall]]:
        last = messages[-1] if messages else None
        if last is not None and not isinstance(last.content, str):
            if any(isinstance(b, ToolResultBlock) for b in last.content):
                return "Noted, Sir.", []
        text = last.text().strip() if last is not None else ""
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
    uvicorn.run(
        create_app(provider=CommandProvider()), host="127.0.0.1", port=port, log_level="warning"
    )


if __name__ == "__main__":
    main()
