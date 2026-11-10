# tests/test_book_unlock.py -- R6 D10's recovery for a passkey lost during a guest show: the
# owner-only emergency unlock (`python -m jarvis.buildbook.unlock --owner ... --reason ...`), run
# with the server's own Google Cloud credentials, never through a browser. It audits FIRST (no
# audit, no change), lifts the lock, ends EVERY book session (each with its notice), tells the
# owner even when no session was open, and asks before it changes anything.
from __future__ import annotations

from typing import Any

import pytest
from book_app_fakes import OWNER, owner_uid
from book_rig_fakes import ServiceRig

from jarvis.buildbook import unlock
from jarvis.buildbook.ports import BookOff
from jarvis.config import AuthMode, SessionBackend, Settings

UID = owner_uid()


@pytest.fixture
def rig(settings: Settings) -> ServiceRig:
    return ServiceRig(settings)


@pytest.fixture
def s(settings: Settings) -> Settings:
    return settings.model_copy(update={"owner_emails": [OWNER], "auth_mode": AuthMode.GOOGLE})


async def test_it_lifts_the_lock_ends_every_session_and_tells(rig: ServiceRig) -> None:
    opened = await rig.open(UID)
    rig.clock.advance(minutes=4)
    report = await rig.svc.emergency_unlock(UID, "lost my\n passkey\x00", now=rig.clock())
    assert report == unlock.UnlockReport(lifted=True, closed=1)
    assert await rig.lock.get(UID) is None
    assert await rig.docs.get(f"jarvis_book_sessions/{opened.session.session_id}") is None
    tools = await rig.tools()
    assert [t for t, _ in tools] == ["book_open", "book_resume", "book_close"]
    assert (
        tools[1][1] == "Emergency unlock at 14:06 from Google Cloud (no passkey): lost my passkey"
    )
    assert len(rig.notices()) == 1 and "has closed (4 min, 0 questions)" in rig.notices()[0]


async def test_with_no_session_open_the_owner_still_hears_of_it(rig: ServiceRig) -> None:
    await rig.open(UID)
    await rig.svc.close(UID, (await rig.sessions.live(UID, now=rig.clock())).session_id,
                        reason="closing", now=rig.clock())  # fmt: skip
    report = await rig.svc.emergency_unlock(UID, "lost it", now=rig.clock())
    assert report == unlock.UnlockReport(lifted=True, closed=0)
    assert rig.notices()[-1] == (
        "Sir, the emergency unlock ran at 14:02: the guest lock was lifted, and no build book "
        "session was open."
    )


async def test_nothing_changes_when_it_cannot_be_audited(rig: ServiceRig) -> None:
    await rig.open(UID)

    async def broken(**kw: Any) -> Any:
        raise RuntimeError("audit down")

    rig.audit.append = broken  # type: ignore[method-assign]
    with pytest.raises(BookOff):
        await rig.svc.emergency_unlock(UID, "lost it", now=rig.clock())
    assert await rig.lock.get(UID) is not None
    assert await rig.sessions.live(UID, now=rig.clock()) is not None


class Out:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


async def _cli(rig: ServiceRig, s: Settings, *argv: str, yes: bool = True) -> tuple[int, Out]:
    out = Out()
    code = await unlock.amain(
        list(argv),
        settings=s,
        build=lambda _: rig.svc,
        confirm=lambda prompt: yes,
        out=out,
        clock=rig.clock,
    )
    return code, out


async def test_the_command_asks_then_unlocks(rig: ServiceRig, s: Settings) -> None:
    await rig.open(UID)
    code, out = await _cli(rig, s, "--owner", OWNER, "--reason", "lost my passkey", yes=False)
    assert code == 1 and await rig.lock.get(UID) is not None and out.lines[-1] == unlock.KEPT
    code, out = await _cli(rig, s, "--owner", UID, "--reason", "lost my passkey")
    assert code == 0 and await rig.lock.get(UID) is None
    assert "lifted" in out.lines[-1] and "1 build book session ended" in out.lines[-1]
    code, out = await _cli(rig, s, "--owner", OWNER, "--reason", "again", "--yes")
    assert code == 0 and out.lines[-1] == unlock.NOTHING


@pytest.mark.parametrize(
    "argv",
    [
        ("--owner", "stranger@example.com", "--reason", "lost my passkey"),
        ("--owner", "u_ffffffffffffffff", "--reason", "lost my passkey"),
        ("--owner", OWNER, "--reason", " \x00 "),
    ],
)
async def test_the_command_refuses_a_stranger_or_no_reason(
    rig: ServiceRig, s: Settings, argv: tuple[str, ...]
) -> None:
    await rig.open(UID)
    code, out = await _cli(rig, s, *argv)
    assert code == 2 and await rig.lock.get(UID) is not None


def test_it_runs_only_with_the_servers_firestore_and_key(settings: Settings) -> None:
    with pytest.raises(unlock.UnlockUnavailable, match="Firestore"):
        unlock.build_service(settings)
    out = Out()
    s = settings.model_copy(update={"owner_emails": [OWNER]})
    code = unlock.main(["--owner", OWNER, "--reason", "lost it"], settings=s, out=out)
    assert code == 2 and "Firestore" in out.lines[-1]


# ---- integrated review SEC-6: no keyring, several owners, sessions valid after ------------------
OTHER_OWNER = "second.owner@example.com"


def test_it_builds_its_lock_and_closer_without_the_token_key(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jarvis.buildbook.lock import DocShowLock
    from jarvis.storage.docs import MemoryDocs

    docs = MemoryDocs()

    class Built:
        def __init__(self) -> None:
            self.docs, self.audit = docs, None

    monkeypatch.setattr("jarvis.storage.build_storage", lambda _s: Built())
    s = settings.model_copy(
        update={
            "session_backend": SessionBackend.FIRESTORE,
            "firestore_project": "proj",
            "owner_emails": [OWNER, OTHER_OWNER],
            "token_key": None,
        }
    )
    svc = unlock.build_service(s)  # no JARVIS_TOKEN_KEY: it lifts and closes all the same
    assert isinstance(svc.lock, DocShowLock)
    assert not hasattr(unlock, "NEEDS_KEY")


async def test_a_session_store_without_the_key_still_closes(rig: ServiceRig) -> None:
    from jarvis.buildbook.sessions import DocBookSessions

    opened = await rig.open(UID)
    closer = DocBookSessions(rig.docs, None)
    assert await closer.owned_ids(UID) == [opened.session.session_id]
    closing = await closer.close_claim(UID, opened.session.session_id, "resume", rig.clock())
    assert closing is not None and await closer.owned_ids(UID) == []
    with pytest.raises(BookOff):
        await closer.resolve(UID, opened.token, now=rig.clock())  # reading a token needs the key


async def test_a_lock_on_another_owner_is_named_and_nothing_changes(
    rig: ServiceRig, s: Settings
) -> None:
    both = s.model_copy(update={"owner_emails": [OWNER, OTHER_OWNER]})
    other = owner_uid(OTHER_OWNER)
    await rig.open(other)  # the OTHER owner's guest show holds every owner's consoles
    code, out = await _cli(rig, both, "--owner", OWNER, "--reason", "lost my passkey")
    assert code == 1 and out.lines[-1] == unlock.OTHER_LOCK
    assert await rig.lock.get(other) is not None


async def test_the_command_ends_every_cookie_session_from_now(rig: ServiceRig, s: Settings) -> None:
    await rig.open(UID)
    code, _ = await _cli(rig, s, "--owner", OWNER, "--reason", "lost my passkey")
    assert code == 0
    assert await rig.lock.valid_after(UID) == rig.clock().timestamp()


def test_the_runbook_installs_hash_locked_in_a_subshell_without_the_key() -> None:
    from pathlib import Path

    doc = (Path(unlock.__file__).parent / "INTEGRATION-C.md").read_text("utf-8")
    book = doc[doc.index("## Runbook: the emergency unlock") :]
    shell = book[book.index("```bash") : book.index("```", book.index("```bash") + 7)]
    assert "pip install -q --require-hashes -r requirements.lock" in shell
    assert "pip install -q --no-deps -e ." in shell
    assert "JARVIS_TOKEN_KEY" not in shell
    assert shell.split("\n")[1].strip() == "(" and shell.rstrip().endswith(")")
