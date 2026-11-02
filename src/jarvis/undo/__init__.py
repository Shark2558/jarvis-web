# src/jarvis/undo/__init__.py
"""Recently deleted — undo for the owner's own deletes (Phase 2 · slice 11 D1; Layers 3/7).

    models   DeletedItem (one kept copy), RestoreOutcome, UndoRef (the reply's Undo chip), views
    store    DeletedStore on the Docs port: {prefix}deleted_items/{user_id}/items/{undo_id}
    service  UndoBin: keep (fail-closed) · restore (idempotent, claimed) · sweep (scheduler tick)
    tools    deleted_list (R1) and deleted_restore (R2), through the gateway

A delete of the owner's own event or to-do keeps a full copy here for 30 days, so it can be
undone — which is why it is R2 and may run without a card (docs/plans/phase2-slice11-full-
control.md). Import the pieces from their modules: this init stays import-free, so
`jarvis.core.models` can depend on `jarvis.undo.models` without a cycle.
"""
