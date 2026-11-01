# src/jarvis/storage/__init__.py
"""Persistence wiring (Layer 7): one place decides where sessions, approvals and audit live."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.config import SessionBackend, Settings
from jarvis.core.guardrails import ApprovalStore, InMemoryApprovalStore
from jarvis.memory.base import SessionStore
from jarvis.storage.docs import Docs
from jarvis.tools.audit import AuditLog, AuditTrail


@dataclass(frozen=True)
class Storage:
    sessions: SessionStore
    approvals: ApprovalStore
    audit: AuditTrail
    persistent: bool


def doc_storage(docs: Docs, *, prefix: str = "jarvis_") -> Storage:
    from jarvis.storage.approvals import DocApprovalStore
    from jarvis.storage.audit import DocAuditLog
    from jarvis.storage.sessions import DocSessionStore

    return Storage(
        sessions=DocSessionStore(docs, prefix=prefix),
        approvals=DocApprovalStore(docs, prefix=prefix),
        audit=DocAuditLog(docs, prefix=prefix),
        persistent=True,
    )


def build_storage(s: Settings) -> Storage:
    if s.session_backend is SessionBackend.FIRESTORE:
        from jarvis.storage.firestore_docs import FirestoreDocs  # lazy: SDK only when used

        docs = FirestoreDocs(project=s.firestore_project, database=s.firestore_database)
        return doc_storage(docs, prefix=s.firestore_prefix)
    from jarvis.memory import build_session_store

    # memory / redis: approvals and audit stay in-process (dev, docker-compose)
    return Storage(
        sessions=build_session_store(s),
        approvals=InMemoryApprovalStore(),
        audit=AuditLog(),
        persistent=False,
    )


__all__ = ["Storage", "build_storage", "doc_storage"]
