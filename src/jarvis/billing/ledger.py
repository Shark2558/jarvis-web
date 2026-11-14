# src/jarvis/billing/ledger.py
"""The token ledger (docs/plans/r14-hardening.md D8): where the AI money goes, counts only.

Per model call (the brain's record slot, `skills.ports.LedgerCall`, after billing), per owner per
day in his own time zone: `{prefix}token_ledger/{uid}_{yyyymmdd}`, kept `LEDGER_DAYS` (90) days
(the first call of a new day drops older days). Each day holds calls, cold calls (no cache read),
input / cache read / cache write / output tokens (the vendor's own `Usage`), characters by part
(persona, tools, history, tool results, memory, trailer), tools offered, skills opened, and the
call's cost split by part: its output priced as "replies", the rest shared by characters. Never a
word of a prompt, a message or a reply; never a key. `NoLedger` records nothing (I0's stub).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from zoneinfo import ZoneInfo

from jarvis.llm.base import ChatMessage, ImageBlock, ToolCall, ToolResultBlock
from jarvis.llm.pricing import PRICES
from jarvis.recall.retrieval import HEADING
from jarvis.storage.docs import Delete, Docs, DocTx, Query
from jarvis.storage.sessions import safe_id

if TYPE_CHECKING:
    from jarvis.llm.base import ToolSpec
    from jarvis.skills.ports import LedgerCall

LEDGER_DAYS: Final = 90
COLLECTION: Final = "token_ledger"
PARTS: tuple[str, ...] = (
    "persona", "tools", "history", "tool_results", "memory", "trailer", "replies",
)  # fmt: skip
INPUT_PARTS: tuple[str, ...] = PARTS[:-1]
TOKENS: tuple[str, ...] = ("input", "cache_read", "cache_write", "output")
PART_WORDS: Mapping[str, str] = {
    "persona": "rule book",
    "tools": "tool list",
    "history": "conversation",
    "tool_results": "tool results",
    "memory": "notes about you",
    "trailer": "time and turn",
    "replies": "replies",
}
OPEN_TOOL: Final = "skills_open"
_MEMORY_MARK = "\n\n" + HEADING
_MTOK = 1_000_000


class NoLedger:
    async def record(self, call: LedgerCall) -> None:
        return None


NO_LEDGER: Final = NoLedger()


@dataclass(frozen=True)
class CallCounts:
    calls: int
    cold_calls: int
    tokens: dict[str, int]
    chars: dict[str, int]
    tools_offered: int
    skills_opened: int
    usd: dict[str, float]


def _message_chars(messages: Sequence[ChatMessage]) -> tuple[int, int]:
    """(history, tool results) characters; a picture counts nothing here."""
    history = results = 0
    for m in messages:
        if isinstance(m.content, str):
            history += len(m.content)
            continue
        for b in m.content:
            if isinstance(b, ToolResultBlock):
                results += len(b.content)
            elif isinstance(b, ToolCall):
                history += len(b.name) + len(json.dumps(b.arguments, ensure_ascii=False))
            elif not isinstance(b, ImageBlock):
                history += len(b.text)
    return history, results


def _tools_chars(tools: Sequence[ToolSpec]) -> int:
    return sum(len(json.dumps(t.model_dump(), ensure_ascii=False)) for t in tools)


def _chars(call: LedgerCall) -> dict[str, int]:
    cut = call.trailer.find(_MEMORY_MARK)
    trailer = len(call.trailer) if cut < 0 else cut
    history, results = _message_chars(list(call.messages))
    return {
        "persona": len(call.system),
        "tools": _tools_chars(list(call.tools)),
        "history": history,
        "tool_results": results,
        "memory": len(call.trailer) - trailer,
        "trailer": trailer,
    }


def _usd(cost: float, output_usd: float, chars: Mapping[str, int]) -> dict[str, float]:
    """The call's cost by part: its output priced as replies, the rest shared by characters
    (the rounding left over goes to the largest part, so the parts add up to the cost)."""
    total = sum(chars.values())
    replies = round(min(max(0.0, output_usd), cost), 8) if total else round(cost, 8)
    rest = cost - replies
    out = {p: round(rest * chars[p] / total, 8) if total else 0.0 for p in INPUT_PARTS}
    if total:
        big = max(INPUT_PARTS, key=lambda p: chars[p])
        out[big] = round(out[big] + rest - sum(out.values()), 8)
    out["replies"] = replies
    return out


def counts_of(call: LedgerCall) -> CallCounts:
    """One call's counts (pure). Raises ValueError when there is no completion."""
    done = call.completion
    if done is None:
        raise ValueError("no completion to count")
    u = done.usage
    chars = _chars(call)
    price = PRICES.get(done.model)
    output_usd = u.output_tokens * price.output_per_mtok / _MTOK if price else 0.0
    return CallCounts(
        calls=1,
        cold_calls=1 if u.cache_read_tokens == 0 else 0,
        tokens={
            "input": u.input_tokens,
            "cache_read": u.cache_read_tokens,
            "cache_write": u.cache_write_tokens,
            "output": u.output_tokens,
        },
        chars=chars,
        tools_offered=len(call.tools),
        skills_opened=sum(1 for c in done.tool_calls if c.name == OPEN_TOOL),
        usd=_usd(max(0.0, done.cost_usd), output_usd, chars),
    )


def _plus(old: Mapping[str, Any] | None, key: str, add: Mapping[str, float]) -> dict[str, float]:
    have = old.get(key) if isinstance(old, Mapping) else None
    base = dict(have) if isinstance(have, Mapping) else {}
    return {k: round(float(base.get(k, 0)) + v, 8) for k, v in add.items()}


def _int(old: Mapping[str, Any] | None, key: str) -> int:
    v = old.get(key, 0) if isinstance(old, Mapping) else 0
    return int(v) if isinstance(v, int | float) else 0


@dataclass(frozen=True)
class MonthLedger:
    month: str
    days: int = 0
    calls: int = 0
    cold_calls: int = 0
    tokens: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TOKENS, 0))
    chars: dict[str, int] = field(default_factory=lambda: dict.fromkeys(INPUT_PARTS, 0))
    tools_offered: int = 0
    skills_opened: int = 0
    usd: dict[str, float] = field(default_factory=lambda: dict.fromkeys(PARTS, 0.0))

    @property
    def usd_total(self) -> float:
        return round(sum(self.usd.values()), 8)

    def cache_share(self) -> float:
        t = self.tokens
        read_in = t["input"] + t["cache_read"] + t["cache_write"]
        return t["cache_read"] / read_in if read_in else 0.0


def _month_of(rows: Sequence[Mapping[str, Any]], month: str) -> MonthLedger:
    def summed(key: str, names: Sequence[str]) -> dict[str, Any]:
        out: dict[str, Any] = dict.fromkeys(names, 0)
        for r in rows:
            got = r.get(key)
            for n in names:
                if isinstance(got, Mapping) and isinstance(got.get(n), int | float):
                    out[n] += got[n]
        return out

    return MonthLedger(
        month=month,
        days=len(rows),
        calls=sum(_int(r, "calls") for r in rows),
        cold_calls=sum(_int(r, "cold_calls") for r in rows),
        tokens={k: int(v) for k, v in summed("tokens", TOKENS).items()},
        chars={k: int(v) for k, v in summed("chars", INPUT_PARTS).items()},
        tools_offered=sum(_int(r, "tools_offered") for r in rows),
        skills_opened=sum(_int(r, "skills_opened") for r in rows),
        usd={k: round(float(v), 8) for k, v in summed("usd", PARTS).items()},
    )


class TokenLedgerStore:
    """`skills.ports.TokenLedger` on the document store."""

    def __init__(
        self,
        docs: Docs,
        *,
        prefix: str = "jarvis_",
        tz: str = "Asia/Kolkata",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._docs, self._col = docs, f"{prefix}{COLLECTION}"
        self._tz, self._clock = ZoneInfo(tz), clock

    def _local(self) -> datetime:
        return self._clock().astimezone(self._tz)

    def path(self, uid: str, day: str) -> str:
        if not safe_id(uid):
            raise ValueError("invalid user id")
        return f"{self._col}/{uid}_{day}"

    def query_for(self, uid: str) -> Query:
        return Query(self._col, where=("user_id", uid))

    async def record(self, call: LedgerCall) -> None:
        if call.completion is None:
            return
        counts, now = counts_of(call), self._local()
        path = self.path(call.uid, now.strftime("%Y%m%d"))

        async def fn(tx: DocTx) -> bool:
            old = await tx.get(path)
            tx.set(path, self._added(old, counts, call.uid, now))
            return old is None

        if await self._docs.transaction(fn):
            await self._prune(call.uid, now)

    def _added(
        self, old: Mapping[str, Any] | None, c: CallCounts, uid: str, now: datetime
    ) -> dict[str, Any]:
        month = now.strftime("%Y-%m")
        return {
            "user_id": uid,
            "day": now.strftime("%Y-%m-%d"),
            "month": month,
            "month_key": f"{uid}_{month}",
            "calls": _int(old, "calls") + c.calls,
            "cold_calls": _int(old, "cold_calls") + c.cold_calls,
            "tokens": {k: int(v) for k, v in _plus(old, "tokens", c.tokens).items()},
            "chars": {k: int(v) for k, v in _plus(old, "chars", c.chars).items()},
            "tools_offered": _int(old, "tools_offered") + c.tools_offered,
            "skills_opened": _int(old, "skills_opened") + c.skills_opened,
            "usd": _plus(old, "usd", c.usd),
            "updated_at": now.isoformat(),
        }

    async def _prune(self, uid: str, now: datetime) -> int:
        cutoff = (now - timedelta(days=LEDGER_DAYS)).strftime("%Y-%m-%d")
        rows = await self._docs.query(self.query_for(uid))
        old = [i for i, d in rows if isinstance(d.get("day"), str) and d["day"] < cutoff]
        if old:
            await self._docs.write([Delete(f"{self._col}/{i}") for i in old])
        return len(old)

    async def month(self, uid: str) -> MonthLedger:
        """This month (his time zone) summed over its days."""
        if not safe_id(uid):
            raise ValueError("invalid user id")
        month = self._local().strftime("%Y-%m")
        rows = await self._docs.query(Query(self._col, where=("month_key", f"{uid}_{month}")))
        return _month_of([d for _, d in rows], month)

    async def days(self, uid: str) -> int:
        if not safe_id(uid):
            raise ValueError("invalid user id")
        return len(await self._docs.query(self.query_for(uid)))


def ai_parts_note(month: MonthLedger, rate: float) -> str:
    """The Vitals line "Where the AI money goes this month", in ₹ (≤ 300 characters)."""
    if month.calls == 0:
        return "No AI calls counted this month yet."
    parts = sorted(PARTS, key=lambda p: month.usd[p], reverse=True)
    shown = ", ".join(f"{PART_WORDS[p]} ₹{month.usd[p] * rate:,.2f}" for p in parts)
    share = round(month.cache_share() * 100)
    tail = f" · {month.calls:,} calls, {share} % of the input read from the cache."
    return f"This month ≈ ₹{month.usd_total * rate:,.2f}: {shown}{tail}"


__all__ = [
    "COLLECTION",
    "INPUT_PARTS",
    "LEDGER_DAYS",
    "NO_LEDGER",
    "PARTS",
    "PART_WORDS",
    "TOKENS",
    "CallCounts",
    "MonthLedger",
    "NoLedger",
    "TokenLedgerStore",
    "ai_parts_note",
    "counts_of",
]
