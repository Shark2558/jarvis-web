# src/jarvis/calls/pending.py
"""A waiting call card's numbers, sealed at rest (R18 combined review; the plan's "numbers stored
encrypted", docs/plans/r18-calls.md section 9).

The gateway keeps every waiting R3 card in the `approvals` collection with its arguments, which
the gate compares with the approved call and then runs. For `calls_place` those arguments hold
the number to call (and a booking's `give_number`), which every other R18 store keeps sealed.
`CallNumberSeal` is the approval store's `ArgumentSeal` for it: each number is AES-GCM sealed under
the keyring's `calls` purpose, bound to the card's own approval id and field (a sealed number moved
to another card or field does not open), and opened again on the way out, so the gate, Approvals
(which shows it masked, `core.models.shown_arguments`) and the call path see it whole. Any other
tool's card, and a value that isn't a string, pass untouched. `seal_pending_calls` puts it on the
gateway's store when that store keeps cards at rest (`DocApprovalStore`); an in-memory store holds
nothing at rest.
"""

from __future__ import annotations

from typing import Any, Protocol

from jarvis.calls.tools import PLACE
from jarvis.core.guardrails import PendingAction
from jarvis.keyring import Keyring

SEALED = "sealed:v1:"
FIELDS = ("number", "booking.give_number")  # a key, or "<outer>.<key>"


class _Cipher(Protocol):
    def encrypt(self, plaintext: bytes, *, aad: str) -> str: ...

    def decrypt(self, blob: str, *, aad: str) -> bytes: ...


class CallNumberSeal:
    """`storage.approvals.ArgumentSeal` for `calls_place` cards."""

    def __init__(self, cipher: _Cipher) -> None:
        self._cipher = cipher

    def __repr__(self) -> str:
        return "CallNumberSeal()"

    @staticmethod
    def _aad(action: PendingAction, field: str) -> str:
        return f"approvals/{action.id}/{field}"

    def _close(self, action: PendingAction, field: str, value: Any) -> Any:
        if not isinstance(value, str) or value.startswith(SEALED):
            return value
        return SEALED + self._cipher.encrypt(value.encode(), aad=self._aad(action, field))

    def _open(self, action: PendingAction, field: str, value: Any) -> Any:
        if not isinstance(value, str) or not value.startswith(SEALED):
            return value
        blob = value.removeprefix(SEALED)
        return self._cipher.decrypt(blob, aad=self._aad(action, field)).decode()

    def _each(self, action: PendingAction, change: Any) -> PendingAction:
        if action.tool != PLACE:
            return action
        args: dict[str, Any] = {**action.arguments}
        for field in FIELDS:
            outer, _, key = field.rpartition(".")
            if not outer:
                if key in args:
                    args[key] = change(action, field, args[key])
                continue
            inner = args.get(outer)
            if isinstance(inner, dict) and key in inner:
                args[outer] = {**inner, key: change(action, field, inner[key])}
        return action.model_copy(update={"arguments": args})

    def seal(self, action: PendingAction) -> PendingAction:
        return self._each(action, self._close)

    def open(self, action: PendingAction) -> PendingAction:
        return self._each(action, self._open)


def seal_pending_calls(gateway: Any, ring: Keyring) -> bool:
    """Put the seal on the gateway's approval store when it keeps cards at rest."""
    store = getattr(getattr(gateway, "gate", None), "store", None)
    use = getattr(store, "use_seal", None)
    if not callable(use):
        return False
    use(CallNumberSeal(ring.cipher("calls")))
    return True


__all__ = ["FIELDS", "SEALED", "CallNumberSeal", "seal_pending_calls"]
