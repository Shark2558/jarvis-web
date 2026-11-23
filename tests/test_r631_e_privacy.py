# tests/test_r631_e_privacy.py
"""R6.3.1 D9 (docs/plans/r6-3-1-book-at-build.md): the runtime writer is gone, but what its trial
stored (pick, caps, YES records, run, lease, rupee ledger, drafts, trial pages, the AI pages' own
sealed index and its chunks) is never deleted by itself. Privacy keeps the row "Book writer (old
trial)": its count, an export (counts and his choices, never page text) and Delete (passkey). The
row leaves the list once nothing is left; a row that can't be checked still shows."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

import jarvis.api.r6_wiring as r6
from jarvis.api import create_app
from jarvis.api.identity import primary_user_id
from jarvis.buildbook.release import ReleaseSource
from jarvis.buildbook.writer.privacy import LABEL, OldWriterSource
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.privacy.ports import CategoryView, PrivacyRegistry
from jarvis.storage.docs import Docs, MemoryDocs, Set

P = "jarvis_"
UID, OTHER = "u_owner", "u_other"
SECRET_TEXT = "sealed-page-text-never-exported"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "book" / "_book"
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


async def seed(docs: Docs, uid: str = UID) -> int:
    """The old trial's records of `uid` (10) and one record of another owner."""
    own = {"owner": uid, "updated_at": "2026-11-24T01:00:00+05:30"}
    pick = {"brain": "anthropic", "caps": {"trial": 100}}
    await docs.write([
        Set(f"{P}book_writer/{uid}", {**own, "pick": pick, "consents": {"trial": {"at": "x"}}}),
        Set(f"{P}book_write_lease/{uid}", {**own, "holder": "h", "until": "x"}),
        *(Set(f"{P}book_write_spend/{uid}_2026-{m}", {**own, "spent_inr": 11.8}) for m in "01"),
        *(Set(f"{P}book_drafts/{uid}_4a70683_pg_card_c0{n}", {**own, "blob": SECRET_TEXT})
          for n in (1, 2)),
        *(Set(f"{P}book_trial/{uid}_0{n}", {**own, "blob": SECRET_TEXT}) for n in (1, 2, 3)),
        Set(f"{P}book_pages/{uid}", {"rev": 1, "kid": "k", "blob": SECRET_TEXT}),
        *(Set(f"{P}book_pages/{uid}/book_chunks/bf_{n:012d}_00", {"blob": SECRET_TEXT})
          for n in range(3)),
        Set(f"{P}book_trial/{OTHER}_01", {"owner": OTHER, "blob": SECRET_TEXT}),
    ])  # fmt: skip
    return 10


async def test_the_row_counts_exports_and_deletes_every_old_record() -> None:
    docs = MemoryDocs()
    want = await seed(docs)
    src = OldWriterSource(docs, prefix=P)
    view = await src.describe(UID)
    assert (view.id, view.label, view.count, view.delete) == ("book_writer", LABEL, want, "passkey")
    assert view.export and view.rev and "old trial" in view.label
    out = await src.export(UID)
    assert out is not None and SECRET_TEXT not in str(out)
    assert out["records"] == {"book_writer": 1, "book_write_lease": 1, "book_write_spend": 2,
                              "book_drafts": 2, "book_trial": 3, "book_pages": 1}  # fmt: skip
    assert out["pick"]["brain"] == "anthropic" and "trial" in out["consents"]
    assert await src.delete(UID) == want
    assert (await src.describe(UID)).count == 0 and await src.export(UID) is None
    assert await docs.get(f"{P}book_trial/{OTHER}_01") is not None  # another owner's stays


async def test_chunks_left_without_their_index_still_show_and_go() -> None:
    docs = MemoryDocs()
    await docs.write([Set(f"{P}book_pages/{UID}/book_chunks/bf_{0:012d}_00", {"blob": "x"})])
    src = OldWriterSource(docs, prefix=P)
    assert (await src.describe(UID)).count == 1
    assert await src.delete(UID) == 1
    assert (await src.describe(UID)).count == 0


class _Plain:
    id, section, label = "plain", "s", "Plain"

    async def describe(self, uid: str) -> CategoryView:
        return CategoryView(id="plain", section="s", label="Plain", what="", count=0, unit="",
                            retention="", where="")  # fmt: skip

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        return 0


class _Down(MemoryDocs):
    async def query(self, q: Any) -> Any:
        raise RuntimeError("down")


async def test_the_row_leaves_the_list_when_empty_and_stays_when_it_can_t_be_checked() -> None:
    docs = MemoryDocs()
    reg = PrivacyRegistry()
    reg.register(_Plain())  # an ordinary empty row always shows
    reg.register(OldWriterSource(docs, prefix=P))
    assert [v.id for v in await reg.describe_all(UID)] == ["plain"]
    await seed(docs)
    assert [v.id for v in await reg.describe_all(UID)] == ["plain", "book_writer"]
    down = PrivacyRegistry()
    down.register(OldWriterSource(_Down(), prefix=P))
    (view,) = await down.describe_all(UID)
    assert view.id == "book_writer" and view.available is False


@pytest.fixture
async def keyed_app(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    monkeypatch.setattr(r6, "default_source", lambda: ReleaseSource(FIXTURE))
    keyed = settings.model_copy(update={"token_key": SecretStr(KEY_B64)})
    app = create_app(keyed, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        yield app


async def test_on_the_app_the_row_shows_only_while_old_records_are_left(keyed_app: Any) -> None:
    st = keyed_app.state
    uid = primary_user_id(st.settings)
    ids = [c.id for c in (await st.privacy.view(uid)).categories]
    assert "book_writer" not in ids and "book_settings" in ids
    await seed(st.book_old_writer._docs, uid)
    cats = (await st.privacy.view(uid)).categories
    ids = [c.id for c in cats]
    assert ids.index("book_settings") < ids.index("book_writer") < ids.index("faces")
    row = next(c for c in cats if c.id == "book_writer")
    assert (row.label, row.count, row.delete) == ("Book writer (old trial)", 10, "passkey")
