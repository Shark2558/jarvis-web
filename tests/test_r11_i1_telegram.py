# tests/test_r11_i1_telegram.py -- R11 I1, the helpers on Telegram (a cloud chat): amounts stay out
# of a Telegram reply. focus_now and pending_list (safe on Telegram: his own lists) drop a bill's
# amount there, and keep it in the console; bill_list and spend_month are private reads on
# Telegram (tests/test_telegram_tool_guard.py).
from __future__ import annotations

import json
from datetime import UTC, datetime

from r11_fakes import UID, Clock
from r11_fakes_a import FAKE_UPI, today_ctx

from jarvis.core.channel import telegram_turn
from jarvis.helpers.today import part as today_part
from jarvis.tools.context import tool_context

NOON = datetime(2026, 11, 12, 6, 30, tzinfo=UTC)  # 12:00 IST, the bill is due tomorrow


async def _tools() -> dict[str, object]:
    c, _, _, _ = today_ctx(clock=Clock(NOON))
    part = today_part.build(c)
    await part.services["bills"].add(
        UID, label="Electricity", payee="Power Co", upi=FAKE_UPI, amount="1240", day=13
    )
    return {t.name: t for t in part.tools}


async def _run(tool: object) -> str:
    with tool_context(f"{UID}:s1"):
        return json.dumps(await tool.run({}), ensure_ascii=False)  # type: ignore[attr-defined]


async def test_a_bills_amount_never_reaches_a_telegram_reply_but_stays_in_the_console() -> None:
    tools = await _tools()
    for name in ("focus_now", "pending_list"):
        console = await _run(tools[name])
        assert "₹1,240" in console and "Electricity" in console, name
        with telegram_turn():
            tg = await _run(tools[name])
        assert "₹" not in tg and "1,240" not in tg and "Electricity" in tg, (name, tg)
