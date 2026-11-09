# tests/r51c_fakes.py -- stand-ins for the R5.1 Part C tests (watchdog ring, briefing, stream,
# reminder route). Imported bare (`from r51c_fakes import ...`); never from conftest.
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from jarvis.home.models import HomeStatus
from jarvis.home.ports import ArmView
from jarvis.llm.base import ToolCall
from jarvis.notify.ports import Delivery, Signal
from jarvis.tools.gateway import GatewayOutcome, GatewayResult
from jarvis.vitals.models import Board, Provider, ProviderView, Spend

UID = "u_owner"
SEEN = 1_800_000_000.0


class Clock:
    def __init__(self, now: float = SEEN) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class HomeStoreFake:
    """`status` / `mark_offline` of a HomeStore, for one owner."""

    def __init__(self, status: HomeStatus | None) -> None:
        self.current = status
        self.marks: list[bool] = []

    async def status(self, uid: str) -> HomeStatus | None:
        return self.current

    async def mark_offline(self, uid: str, *, alerted: bool) -> None:
        self.marks.append(alerted)
        assert self.current is not None
        self.current = replace(self.current, state="offline", outage_alerted=alerted)


def home_status(seen: float = SEEN, state: str = "online", alerted: bool = False) -> HomeStatus:
    return HomeStatus(
        home_id="h1",
        state=state,  # type: ignore[arg-type]
        linked_at=1.0,
        last_seen_at=seen,
        outage_alerted=alerted,
    )


class ArmFake:
    def __init__(self, armed: bool = False) -> None:
        self.armed = armed

    async def view(self, uid: str) -> ArmView:
        return ArmView(armed=self.armed, mode="away", rev=1, confirmed=True)


class Scripted:
    """A Notifier that answers each call with the next scripted Delivery (the last one repeats)."""

    def __init__(self, *answers: Delivery) -> None:
        self.answers = list(answers) or [Delivery(action="ring", reason="test", telegram=True)]
        self.sent: list[tuple[Signal, str]] = []

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        self.sent.append((signal, message))
        return self.answers[min(len(self.sent), len(self.answers)) - 1]

    def kinds(self) -> list[str]:
        return [s.kind for s, _ in self.sent]


RANG = Delivery(action="ring", reason="important", telegram=True)
HELD = Delivery(action="hold", reason="quiet_hours")
UNHEARD = Delivery(action="ring", reason="important")  # nobody took it
SWITCHED_OFF = Delivery(action="drop", reason="switched_off")
FLAP = Delivery(action="drop", reason="flap_gap")


# ---- vitals --------------------------------------------------------------------------------------
def view(
    pid: str,
    label: str,
    status: str,
    *,
    kind: str = "key",
    percent: float | None = None,
    reason: str = "",
    **extra: Any,
) -> ProviderView:
    p = Provider(id=pid, label=label, kind=kind, source="auto")  # type: ignore[arg-type]
    v = ProviderView(provider=p, status=status, percent=percent, reason=reason)  # type: ignore[arg-type]
    for k, val in extra.items():  # Part B's impact / fix / group, when present
        object.__setattr__(v, k, val)
    return v


def board(*items: ProviderView, used: float = 120.0, limit: int | None = 500) -> Board:
    spend = Spend(used_inr=used, limit_inr=limit, text="")
    return Board(items=tuple(items), spend=spend, overall="ok")


class VitalsFake:
    def __init__(self, b: Board | None = None, exc: Exception | None = None) -> None:
        self.b, self.exc = b, exc
        self.calls = 0

    async def board(self, uid: str) -> Board:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        assert self.b is not None
        return self.b


# ---- the reminder route ----------------------------------------------------------------------------
@dataclass
class GatewayFake:
    result: GatewayResult = field(
        default_factory=lambda: GatewayResult(GatewayOutcome.EXECUTED, result={"id": "r1"})
    )
    calls: list[tuple[ToolCall, str | None, dict[str, Any]]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)

    async def execute(self, call: ToolCall, *, scope: str | None = None) -> GatewayResult:
        from jarvis.tools.taint import content_tainted, owner_text, spoken_in_context

        trust = {
            "outside": content_tainted(),
            "spoken": spoken_in_context(),
            "owner_text": owner_text(),
        }
        self.calls.append((call, scope, trust))
        return self.result

    @property
    def gate(self) -> GatewayFake:
        return self

    async def cancel(self, approval_id: str) -> bool:
        self.cancelled.append(approval_id)
        return True


class GoogleFake:
    def __init__(self, connected: bool = True, exc: Exception | None = None) -> None:
        self.connected, self.exc = connected, exc

    async def status(self, uid: str) -> dict[str, Any]:
        if self.exc is not None:
            raise self.exc
        return {"connected": self.connected}
