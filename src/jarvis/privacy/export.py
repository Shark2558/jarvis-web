# src/jarvis/privacy/export.py
"""What a privacy view or export may contain (R2 D14): never a secret.

Every source builds its export from safe fields; `scrub` is the second line of defence that the
service applies to every export: keys that name a token, key, secret, password, credential,
cookie or encrypted blob are dropped at any depth, and so is any text that looks like a bearer
token. `fingerprint` makes a category's `rev`: a short hash of what was shown, so a delete can
refuse when the data changed since the owner looked.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# a key is secret-looking when its LAST word is one of these ("api_key", "refresh_token", "key")
_SECRET_KEY = re.compile(
    r"(?:^|[_\-\s])(?:token|secret|password|passwd|key|blob|credential|authorization|cookie|"
    r"claim_id)s?$",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)
REV_LEN = 16


def _secret_key(key: object) -> bool:
    return isinstance(key, str) and _SECRET_KEY.search(key) is not None


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
