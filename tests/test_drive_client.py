# tests/test_drive_client.py — slice 12 D1: the Drive v3 adapter. httpx only, redirects off, size
# caps, strict shape checks, one retry on 401 (fresh token) and on 429/5xx (all calls are reads),
# plain-English errors that never carry Google's text. No network: a fake Drive transport.
from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
from drive_fakes import DOC, FOLDER, PDF, SHEET, SHORTCUT, FakeDrive, StaticTokens

from jarvis.drive.client import DriveClient, escape_query
from jarvis.drive.ports import DriveError, DriveNotFound, DriveUnavailable

OWNER = "akash@example.com"


def _drive() -> FakeDrive:
    d = FakeDrive()
    d.folder("root1", "Registry", shared_by=OWNER)
    d.folder("sub1", "Minutes", "root1")
    d.file("doc1", "Steering notes", "sub1", "Budget is four crore.")
    d.file("pdf1", "Scope.pdf", "root1", b"%PDF-1.7 ...", mime=PDF)
    d.folder("other", "Their stuff", shared_by="stranger@example.net")
    return d


def _client(d: FakeDrive, tokens: StaticTokens | None = None) -> DriveClient:
    return DriveClient(tokens or StaticTokens(), http=d.client())


def _q(req: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}


async def test_shared_folders_lists_folders_shared_with_jarvis_and_who_shared_them() -> None:
    d = _drive()
    found = await _client(d).shared_folders()
    assert {(f.id, f.sharer) for f in found} == {
        ("root1", OWNER),
        ("other", "stranger@example.net"),
    }
    q = _q(d.requests[0])
    assert q["q"] == f"sharedWithMe and mimeType = '{FOLDER}' and trashed = false"
    assert "sharingUser" in q["fields"]


async def test_children_lists_one_folder_paged() -> None:
    d = _drive()
    for i in range(7):
        d.file(f"f{i}", f"File {i}", "root1", "x")
    c = _client(d)
    first = await c.children("root1", page_size=5)
    assert len(first.files) == 5 and first.next_token
    second = await c.children("root1", page_token=first.next_token, page_size=5)
    assert len(second.files) == 4 and second.next_token is None  # 7 files + sub1 + pdf1
    assert _q(d.requests[0])["q"] == "'root1' in parents and trashed = false"


async def test_search_escapes_quotes_and_backslashes() -> None:
    d = _drive()
    await _client(d).search("o'brien \\ budget")
    assert _q(d.requests[0])["q"] == "fullText contains 'o\\'brien \\\\ budget' and trashed = false"


def test_escape_query() -> None:
    assert escape_query("a'b\\c") == "a\\'b\\\\c"


async def test_get_reads_metadata_with_strict_types() -> None:
    d = _drive()
    f = await _client(d).get("doc1")
    assert (f.id, f.name, f.mime, f.parents, f.trashed) == (
        "doc1",
        "Steering notes",
        DOC,
        ("sub1",),
        False,
    )
    assert f.sharer == OWNER  # inherited from the shared folder above it


async def test_shortcut_details_are_read() -> None:
    d = _drive()
    d.shortcut("sc1", "Link", "root1", target="doc1")
    f = await _client(d).get("sc1")
    assert f.is_shortcut and f.target_id == "doc1" and f.target_mime == DOC


async def test_export_and_download() -> None:
    d = _drive()
    d.file("sheet1", "Costs", "root1", "a,b\n1,2\n", mime=SHEET)
    c = _client(d)
    assert await c.export("doc1", "text/plain") == b"Budget is four crore."
    assert await c.export("sheet1", "text/csv") == b"a,b\n1,2\n"
    assert await c.download("pdf1") == b"%PDF-1.7 ..."
    media = [r for r in d.requests if _q(r).get("alt") == "media"]
    assert len(media) == 1


async def test_not_shared_is_not_found() -> None:
    d = _drive()
    d.file("secret", "Payroll", None, "x")  # never shared with JARVIS
    with pytest.raises(DriveNotFound):
        await _client(d).get("secret")


async def test_a_401_gets_a_fresh_token_once() -> None:
    d = _drive()
    tokens = StaticTokens("stale")

    class Rotating(StaticTokens):
        def invalidate(self) -> None:
            super().invalidate()
            self.value = d.token

    tokens = Rotating("stale")
    f = await _client(d, tokens).get("doc1")
    assert f.id == "doc1" and tokens.invalidated == 1 and len(d.requests) == 2


async def test_a_401_twice_is_unavailable() -> None:
    d = _drive()
    with pytest.raises(DriveUnavailable):
        await _client(d, StaticTokens("wrong")).get("doc1")


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_busy_is_retried_once_then_reported_plainly(status: int) -> None:
    d = _drive()
    d.fail["doc1"] = status
    with pytest.raises(DriveError) as e:
        await _client(d).get("doc1")
    assert len(d.requests) == 2
    assert "VENDOR" not in str(e.value) and "vendor" not in str(e.value)


async def test_api_switched_off_is_said_plainly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "error": {
                "code": 403,
                "message": "VENDOR",
                "errors": [{"reason": "accessNotConfigured"}],
            }
        }
        return httpx.Response(403, json=body)

    c = DriveClient(StaticTokens(), http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(DriveError) as e:
        await c.get("doc1")
    assert "switched on" in str(e.value) and "VENDOR" not in str(e.value)


async def test_redirects_are_not_followed() -> None:
    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.example/steal"})

    c = DriveClient(StaticTokens(), http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(DriveError):
        await c.download("pdf1")
    assert all("evil" not in h for h in hits)


async def test_downloads_over_ten_megabytes_are_refused() -> None:
    d = _drive()
    d.file("big", "Huge.pdf", "root1", b"%PDF-" + b"x" * (10 * 1024 * 1024), mime=PDF)
    with pytest.raises(DriveError) as e:
        await _client(d).download("big")
    assert "10 MB" in str(e.value)


async def test_oversized_json_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"files": [' + b" " * 3_000_000 + b"]}")

    c = DriveClient(StaticTokens(), http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(DriveError):
        await c.children("root1")


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"files": "nope"},
        {"id": "doc1"},  # get: no name / mimeType
        {"id": "../x", "name": "n", "mimeType": DOC},
        {"id": "doc1", "name": 5, "mimeType": DOC},
        {"id": "doc1", "name": "n", "mimeType": DOC, "parents": "root1"},
        {"id": "doc1", "name": "n", "mimeType": DOC, "trashed": "false"},
    ],
)
async def test_malformed_metadata_is_unreadable(body: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    c = DriveClient(StaticTokens(), http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(DriveError):
        await c.get("doc1")


async def test_malformed_list_entries_are_dropped_not_guessed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        files = [
            {"id": "ok1", "name": "Fine", "mimeType": DOC, "parents": ["root1"]},
            {"id": "bad id!", "name": "x", "mimeType": DOC},
            {"id": "ok2", "name": None, "mimeType": DOC},
            "junk",
            {"id": "ok3", "name": "Shortcut", "mimeType": SHORTCUT, "parents": ["root1"]},
        ]
        return httpx.Response(200, json={"files": files, "nextPageToken": 7})

    c = DriveClient(StaticTokens(), http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    page = await c.children("root1")
    assert [f.id for f in page.files] == ["ok1", "ok3"]
    assert page.next_token is None  # not a string: ignored


@pytest.mark.parametrize("bad", ["", "../etc", "a b", "x" * 200, "id'or'1"])
async def test_ids_are_checked_before_any_request(bad: str) -> None:
    d = _drive()
    with pytest.raises(ValueError):
        await _client(d).get(bad)
    assert d.requests == []


async def test_the_token_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    d = _drive()
    d.token = "ya29.SECRET"
    caplog.set_level("DEBUG")
    await _client(d, StaticTokens("ya29.SECRET")).get("doc1")
    d.fail["doc1"] = 500
    with pytest.raises(DriveError):
        await _client(d, StaticTokens("ya29.SECRET")).get("doc1")
    assert "SECRET" not in caplog.text


async def test_unreachable_drive_is_plain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom with vendor detail")

    c = DriveClient(StaticTokens(), http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(DriveError) as e:
        await c.get("doc1")
    assert "boom" not in str(e.value)
