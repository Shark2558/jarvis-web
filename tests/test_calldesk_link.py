"""R18 C: linking the call desk with the console's code (I0's DeskDoor `link`), with a fake HTTPS
opener: the request's shape, each refusal in plain words, and that a bad answer saves nothing."""

from __future__ import annotations

import base64
import json
import urllib.error
from typing import Any

import pytest

from jarvis.api import calls_routes
from jarvis.calldesk import link

SEED = bytes(range(32))
URL = "https://jarvis.example"


class Answer:
    def __init__(self, status: int, body: bytes) -> None:
        self.status, self.body = status, body

    def __enter__(self) -> Answer:
        return self

    def __exit__(self, *exc: Any) -> None:
        pass

    def read(self, n: int) -> bytes:
        return self.body[:n]


def _ok(body: object, status: int = 201) -> Any:
    def opener(req: Any, timeout: float) -> Answer:
        return Answer(status, json.dumps(body).encode())

    return opener


def _http(code: int) -> Any:
    def opener(req: Any, timeout: float) -> Answer:
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)  # type: ignore[arg-type]

    return opener


def test_the_path_is_the_routers() -> None:
    assert ("POST", link.LINK_PATH) in calls_routes.ROUTES


def test_a_good_answer_gives_the_desk_id_and_seed() -> None:
    seen: list[Any] = []

    def opener(req: Any, timeout: float) -> Answer:
        seen.append((req, timeout))
        seed = base64.urlsafe_b64encode(SEED).decode().rstrip("=")
        return Answer(201, json.dumps({"desk_id": "h_00c0ffee", "seed": seed}).encode())

    assert link.request_link(URL + "/", " k7m2-x9qp ", opener=opener) == ("h_00c0ffee", SEED)
    req, timeout = seen[0]
    assert req.get_method() == "POST" and req.full_url == URL + link.LINK_PATH
    assert req.get_header("Content-type") == "application/json"
    assert json.loads(req.data) == {"code": "K7M2X9QP", "desk_version": "18.1.0"}  # R5.2 I1
    assert timeout == link.TIMEOUT_S


@pytest.mark.parametrize(
    ("status", "words"),
    [
        (401, "wrong, used or out of time"),
        (429, "Too many tries"),
        (501, "still being built"),
        (503, "switched off"),
        (500, "could not link the call desk now"),
    ],
)
def test_refusals_in_plain_words(status: int, words: str) -> None:
    with pytest.raises(link.LinkFailed) as err:
        link.request_link(URL, "ABCD2345", opener=_http(status))
    assert words in err.value.reason and "ABCD2345" not in err.value.reason


def test_unreachable() -> None:
    def opener(req: Any, timeout: float) -> Answer:
        raise urllib.error.URLError("no route to host")

    with pytest.raises(link.LinkFailed, match="could not be reached"):
        link.request_link(URL, "ABCD2345", opener=opener)


@pytest.mark.parametrize(
    "opener",
    [
        _ok({"desk_id": "h_00c0ffee"}),
        _ok({"desk_id": "bad", "seed": base64.b64encode(SEED).decode()}),
        _ok([1, 2]),
        _ok({"x": "y" * 5000}),
        _ok({"desk_id": "h_00c0ffee", "seed": "AA"}, status=204),
    ],
)
def test_answers_it_cannot_read(opener: Any) -> None:
    with pytest.raises(link.LinkFailed):
        link.request_link(URL, "ABCD2345", opener=opener)


@pytest.mark.parametrize("raw", ["", "abc", "ABCD 2345 6789 0", "ABCD!234"])
def test_codes_that_cannot_be_codes(raw: str) -> None:
    with pytest.raises(link.LinkFailed, match="does not look like"):
        link.clean_code(raw)
