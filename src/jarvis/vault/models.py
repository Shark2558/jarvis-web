# src/jarvis/vault/models.py
"""The document vault's data model (R2 D1-D5; Layer 7 data).

Everything in `VaultIndex` is stored encrypted (one AES-GCM blob per owner, key `vault_index`);
nothing here is ever written to Firestore in clear. No structured field holds a full ID number:
`last4` is at most four characters (D3). Original file names are never kept.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ME = "me"  # the holder id of the owner himself
MAX_ITEMS = 100
MAX_FILES_PER_ITEM = 2
MAX_HOLDERS = 12
HOLDER_LABEL_MAX = 40
TITLE_MAX = 60
NOTE_MAX = 300
PENDING_TTL_S = 3600
REMINDER_CHOICES: tuple[int, ...] = (180, 90, 60, 30, 14, 7, 1)
DEFAULT_REMINDERS: tuple[int, ...] = (90, 30, 7)
ID_ITEM = re.compile(r"v_[0-9a-f]{12}")
ID_FILE = re.compile(r"f_[0-9a-f]{12}")
ID_HOLDER = re.compile(r"h_[0-9a-f]{8}")
LAST4 = re.compile(r"[A-Z0-9]{1,4}")

AlertDetail = Literal["generic", "type"]
SourceKind = Literal["upload", "digilocker"]


@dataclass(frozen=True)
class TypeInfo:
    label: str  # "Driving licence"
    expires: bool  # does it normally expire (a PAN or Aadhaar does not)
    slug: str  # file-name part


TYPES: dict[str, TypeInfo] = {
    "passport": TypeInfo("Passport", True, "passport"),
    "driving_licence": TypeInfo("Driving licence", True, "driving-licence"),
    "pan": TypeInfo("PAN card", False, "pan"),
    "aadhaar": TypeInfo("Aadhaar", False, "aadhaar"),
    "voter_id": TypeInfo("Voter ID", False, "voter-id"),
    "vehicle_rc": TypeInfo("Vehicle registration", True, "vehicle-rc"),
    "vehicle_insurance": TypeInfo("Vehicle insurance", True, "vehicle-insurance"),
    "puc": TypeInfo("PUC certificate", True, "puc"),
    "health_insurance": TypeInfo("Health insurance", True, "health-insurance"),
    "life_insurance": TypeInfo("Life insurance", True, "life-insurance"),
    "other_insurance": TypeInfo("Insurance", True, "insurance"),
    "birth_certificate": TypeInfo("Birth certificate", False, "birth-certificate"),
    "certificate": TypeInfo("Certificate", True, "certificate"),
    "property": TypeInfo("Property document", False, "property"),
    "other": TypeInfo("Document", True, "document"),
}
TYPE_IDS: tuple[str, ...] = tuple(TYPES)


class VaultRejected(Exception):
    """A request the vault refuses, in plain words (`code` is stable, `detail` is shown)."""

    def __init__(self, code: str, detail: str, *, status: int = 422) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status


class VaultUnavailable(Exception):
    """The vault could not be read or written safely (storage down, an undecryptable index or
    chunk). Fail closed: nothing is overwritten, nothing partial is shown (503)."""


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class Holder(Frozen):
    id: str
    label: str = Field(max_length=HOLDER_LABEL_MAX)


class FileRef(Frozen):
    fid: str
    mime: str
    size: int
    sha256: str
    chunks: int
    dek: str  # the file's data key, wrapped (base64), never in clear
    added_at: dt.datetime


class Proposal(Frozen):
    """What the extractor found, shown with its fixed label and the parsed value only."""

    type: str | None = None
    issued_on: dt.date | None = None
    issued_label: str | None = None
    expires_on: dt.date | None = None
    expires_label: str | None = None
    last4: str | None = None

    @property
    def empty(self) -> bool:
        return not any((self.type, self.issued_on, self.expires_on, self.last4))


class Source(Frozen):
    kind: SourceKind = "upload"
    drive_id: str | None = None


class Item(Frozen):
    id: str
    type: str
    holder_id: str = ME
    title: str = Field(max_length=TITLE_MAX)
    last4: str | None = None
    note: str = Field(default="", max_length=NOTE_MAX)
    issued_on: dt.date | None = None
    expires_on: dt.date | None = None
    dates_confirmed: bool = False
    reminders: tuple[int, ...] = DEFAULT_REMINDERS
    source: Source = Source()
    files: tuple[FileRef, ...] = ()
    proposal: Proposal | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    deleted_at: dt.datetime | None = None

    @property
    def live(self) -> bool:
        return self.deleted_at is None


class Pending(Frozen):
    fid: str
    item_id: str
    chunks: int
    size: int
    started_at: dt.datetime


class Orphan(Frozen):
    fid: str
    chunks: int


class VaultSettings(Frozen):
    alert_detail: AlertDetail = "generic"
    brief: bool = True
    inbox_copy: bool = False


class VaultIndex(Frozen):
    holders: tuple[Holder, ...] = ()
    items: tuple[Item, ...] = ()
    pending: tuple[Pending, ...] = ()
    orphans: tuple[Orphan, ...] = ()
    settings: VaultSettings = VaultSettings()

    def item(self, item_id: str) -> Item | None:
        return next((i for i in self.items if i.id == item_id), None)

    def live_items(self) -> tuple[Item, ...]:
        return tuple(i for i in self.items if i.live)

    def bytes_total(self) -> int:
        stored = sum(f.size for i in self.items for f in i.files)
        return stored + sum(p.size for p in self.pending)

    def holder_label(self, holder_id: str) -> str:
        if holder_id == ME:
            return "you"
        found = next((h for h in self.holders if h.id == holder_id), None)
        return found.label if found is not None else "family"


def replace_item(index: VaultIndex, item: Item) -> VaultIndex:
    return index.model_copy(
        update={"items": tuple(item if i.id == item.id else i for i in index.items)}
    )


def days_left(item: Item, today: dt.date) -> int | None:
    return None if item.expires_on is None else (item.expires_on - today).days


__all__ = [
    "DEFAULT_REMINDERS",
    "HOLDER_LABEL_MAX",
    "ID_FILE",
    "ID_HOLDER",
    "ID_ITEM",
    "LAST4",
    "ME",
    "MAX_FILES_PER_ITEM",
    "MAX_HOLDERS",
    "MAX_ITEMS",
    "NOTE_MAX",
    "PENDING_TTL_S",
    "REMINDER_CHOICES",
    "TITLE_MAX",
    "TYPES",
    "TYPE_IDS",
    "AlertDetail",
    "FileRef",
    "Holder",
    "Item",
    "Orphan",
    "Pending",
    "Proposal",
    "Source",
    "SourceKind",
    "TypeInfo",
    "VaultIndex",
    "VaultRejected",
    "VaultSettings",
    "VaultUnavailable",
    "days_left",
    "replace_item",
]
