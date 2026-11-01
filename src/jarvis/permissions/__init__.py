# src/jarvis/permissions/__init__.py
"""Owner permission rules and passkeys for irreversible approvals (slice 10 D).

- `groups`      the tool groups (Allow / Ask first / Never) and their policy rules
- `store`       per-owner choices on the `Docs` port, read by the gateway on every call
- `passkeys`    registered passkeys and single-use WebAuthn challenges on the `Docs` port
- `ceremony`    the only module that imports `webauthn` (py_webauthn, BSD-3-Clause)
- `service`     what the API calls: the view, changes, passkey ceremonies, the approval guard
"""

from __future__ import annotations

from jarvis.permissions.groups import GROUPS, PermissionGroup, PermissionRejected

__all__ = ["GROUPS", "PermissionGroup", "PermissionRejected"]
