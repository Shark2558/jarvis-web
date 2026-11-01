# src/jarvis/storage/__init__.py
"""Persistence wiring (Layer 7): one place decides where sessions, approvals and audit live."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from jarvis.config import SessionBackend, Settings
from jarvis.core.guardrails import ApprovalStore, InMemoryApprovalStore
from jarvis.logging import get_logger
from jarvis.memory.base import SessionStore
from jarvis.storage.docs import Docs
from jarvis.tools.audit import AuditLog, AuditTrail

if TYPE_CHECKING:  # vault imports storage.docs; keep the runtime import one-directional
    from jarvis.integrations.vault import TokenStore

log = get_logger(__name__)


def _memory_tokens() -> TokenStore:
    from jarvis.integrations.vault import MemoryTokenStore

    return MemoryTokenStore()


@dataclass(frozen=True)
class Storage:
    sessions: SessionStore
    approvals: ApprovalStore
    audit: AuditTrail
    persistent: bool
    tokens: TokenStore = field(default_factory=_memory_tokens)


def doc_storage(docs: Docs, *, prefix: str = "jarvis_", token_key: bytes | None = None) -> Storage:
    """Everything on the Docs port. Google tokens persist only when an encryption key is given;
    without one they live in-process (dev) — prod enforces the key via require_prod_invariants."""
    from jarvis.storage.approvals import DocApprovalStore
    from jarvis.storage.audit import DocAuditLog
    from jarvis.storage.sessions import DocSessionStore

    tokens: TokenStore
    if token_key is not None:
        from jarvis.integrations.vault import DocTokenStore

        tokens = DocTokenStore(docs, key=token_key, prefix=prefix)
    else:
        log.warning("no JARVIS_TOKEN_KEY: Google links will not survive a restart")
        tokens = _memory_tokens()
    return Storage(
        sessions=DocSessionStore(docs, prefix=prefix),
        approvals=DocApprovalStore(docs, prefix=prefix),
        audit=DocAuditLog(docs, prefix=prefix),
        persistent=True,
        tokens=tokens,
    )


def build_storage(s: Settings) -> Storage:
    if s.session_backend is SessionBackend.FIRESTORE:
        from jarvis.storage.firestore_docs import FirestoreDocs  # lazy: SDK only when used

        docs = FirestoreDocs(project=s.firestore_project, database=s.firestore_database)
        return doc_storage(docs, prefix=s.firestore_prefix, token_key=s.token_key_bytes())
    from jarvis.memory import build_session_store

    # memory / redis: approvals and audit stay in-process (dev, docker-compose)
    return Storage(
        sessions=build_session_store(s),
        approvals=InMemoryApprovalStore(),
        audit=AuditLog(),
        persistent=False,
    )


__all__ = ["Storage", "build_storage", "doc_storage"]
