# tests/test_privacy_export.py - R2 D14: what an export may contain (never a secret) and how a
# category's "rev" fingerprint behaves.
from __future__ import annotations

from jarvis.privacy.export import fingerprint, scrub


def test_m3_scrub_drops_every_secret_looking_key_however_it_is_spelled() -> None:
    bad = {
        "accessToken": 1, "refreshToken": 2, "passkey": 3, "apikey": 4, "ciphertext": 5,
        "nonce": 6, "credential_id": 7, "client_secret": 8, "api_key": 9, "enc": 10, "dek": 11,
        "wrapped_key": 12, "salt": 13, "hmac": 14, "bearer": 15, "sig": 16, "API-KEY": 17,
        "Authorization": 18, "setCookie": 19, "privateKey": 20, "claim_id": 21, "blob": 22,
        "idToken": 23, "wrappedDEK": 24,
    }  # fmt: skip
    assert scrub(bad) == {}
    assert scrub({"outer": {"accessToken": 1, "ok": 2}}) == {"outer": {"ok": 2}}


def test_m3_scrub_keeps_harmless_keys() -> None:
    fine = {
        "keep": 1, "monkey": 2, "title": 3, "turns": 4, "content": 5, "account": 6, "at": 7,
        "scopes": 8, "needs_reconnect": 9, "author": 10, "senior": 11, "encoded": 12,
        "signal": 13, "design": 14, "calendar": 15, "newest": 16, "paired_at": 17,
    }  # fmt: skip
    assert scrub(fine) == fine


def test_scrub_drops_secret_looking_keys_at_any_depth() -> None:
    data = {
        "name": "Home",
        "access_token": "ya29.abc",
        "nested": {
            "refresh_token": "r",
            "api_key": "k",
            "ok": 1,
            "items": [{"password": "p", "a": 2}],
        },
        "key": "root",
        "blob": "ciphertext",
        "client_secret": "s",
        "Authorization": "Bearer x",
    }
    assert scrub(data) == {"name": "Home", "nested": {"ok": 1, "items": [{"a": 2}]}}


def test_scrub_keeps_ordinary_words_that_contain_key() -> None:
    data = {"keywords": ["a"], "monkey": 1, "args_hash": "h", "hash": "chain"}
    assert scrub(data) == data


def test_scrub_does_not_mutate_its_input_and_handles_scalars() -> None:
    data = {"token": "t", "list": [1, "x", None]}
    out = scrub(data)
    assert "token" in data and out == {"list": [1, "x", None]}
    assert scrub("plain") == "plain" and scrub(None) is None


def test_scrub_drops_a_value_that_looks_like_a_bearer_secret() -> None:
    out = scrub({"note": "Bearer abcdefghijklmnop1234567890", "ok": "hello"})
    assert out == {"ok": "hello"}


def test_fingerprint_is_stable_short_and_changes_with_content() -> None:
    a = fingerprint(3, ["x", "y"])
    assert a == fingerprint(3, ["x", "y"])
    assert len(a) == 16 and all(c in "0123456789abcdef" for c in a)
    assert a != fingerprint(3, ["x", "z"]) and a != fingerprint(4, ["x", "y"])


def test_fingerprint_does_not_confuse_adjacent_parts() -> None:
    assert fingerprint("ab", "c") != fingerprint("a", "bc")
