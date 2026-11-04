# src/jarvis/family/models.py
"""Family calendars the owner registered (R1 D15). Frozen. `name` is the owner's own label for the
person (never taken from Google); `calendar_id` is the address or `...@group.calendar.google.com`
id the member shared with him; `access` is the role Google gave him on it when it was added."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

Access = Literal["freeBusyReader", "reader", "writer", "owner"]
ACCESS_LEVELS: tuple[str, ...] = ("freeBusyReader", "reader", "writer", "owner")
CAN_WRITE = frozenset({"writer", "owner"})
MAX_MEMBERS = 8
NAME_MAX = 40
ID_MAX = 254
# an e-mail address or a group calendar id: no slash, space, query or percent sign can get in
CALENDAR_ID = re.compile(r"[a-z0-9][a-z0-9._+'-]{0,127}@[a-z0-9][a-z0-9.-]{0,120}\.[a-z]{2,24}")


class Member(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    name: str
    calendar_id: str
    access: Access
    added_at: str
    verified_at: str

    @property
    def can_write(self) -> bool:
        return self.access in CAN_WRITE


class MemberView(BaseModel):
    """What GET /v1/family shows for one member."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    calendar_id: str
    access: Access
    can_write: bool
    added_at: str


def view(m: Member) -> MemberView:
    return MemberView(
        id=m.id,
        name=m.name,
        calendar_id=m.calendar_id,
        access=m.access,
        can_write=m.can_write,
        added_at=m.added_at,
    )


__all__ = [
    "ACCESS_LEVELS",
    "CALENDAR_ID",
    "CAN_WRITE",
    "ID_MAX",
    "MAX_MEMBERS",
    "NAME_MAX",
    "Access",
    "Member",
    "MemberView",
    "view",
]
