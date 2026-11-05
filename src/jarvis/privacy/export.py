# src/jarvis/privacy/export.py
"""What a privacy view or export may contain (R2 D14): never a secret.

Every source builds its export from safe fields; `scrub` is the second line of defence that the
service applies to every export: keys that name a token, key, secret, password, credential,
cookie or encrypted blob (in any spelling: accessToken, api-key, CIPHERTEXT) are dropped at any
depth, and so is any text that looks like a bearer token. `fingerprint` makes a category's `rev`:
a short hash of what was shown, so a delete can refuse when the data changed since the owner
looked.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# A key is secret-looking when, split into words (camelCase, _, -, space), ANY word is one of
# _SECRET_WORDS, or when its words run together into a string holding one of _SECRET_PARTS
# ("apikey", "accesstoken", "ciphertext"). Whole words keep "keep", "monkey" and "author" safe;
# the substrings are long enough not to hit ordinary words.
_SECRET_WORDS = frozenset(
    "token tokens secret secrets password passwords passwd pwd key keys blob blobs cipher "
    "ciphertext nonce salt dek kek hmac credential credentials cred auth authorization cookie "
    "cookies enc sig bearer claim jwt otp pin passkey apikey".split()
)
_SECRET_PARTS = (
    "token", "secret", "password", "passwd", "apikey", "privatekey", "cipher",
    "nonce", "credential", "authorization", "cookie", "bearer", "claimid", "hmac",
)  # fmt: skip
_WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)
REV_LEN = 16


def _secret_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    words = [w.lower() for w in _WORDS.findall(key)]
    if any(w in _SECRET_WORDS for w in words):
        return True
    joined = "".join(words)
    return any(part in joined for part in _SECRET_PARTS)


def scrub(value: Any) -> Any:
    """A copy of `value` without secret-looking keys or bearer-token-looking text."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if not _secret_key(k) and not _leaks(v)}
    if isinstance(value, list | tuple):
        return [scrub(v) for v in value if not _leaks(v)]
    return value


def _leaks(value: Any) -> bool:
    return isinstance(value, str) and _BEARER.search(value) is not None


def fingerprint(*parts: Any) -> str:
    """A short stable hash of `parts` (length-prefixed, so adjacent parts never blur)."""
    h = hashlib.sha256()
    for part in parts:
        raw = json.dumps(part, sort_keys=True, default=str, ensure_ascii=False).encode()
        h.update(len(raw).to_bytes(8, "big"))
        h.update(raw)
    return h.hexdigest()[:REV_LEN]


__all__ = ["REV_LEN", "fingerprint", "scrub"]
