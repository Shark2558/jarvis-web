# src/jarvis/recall/__init__.py
"""Long-term memory (Phase 3 · slice 8; Layer 3 Context & Orchestration + Layer 7 Data).

`jarvis.memory` is the Phase 0 session store (the rolling conversation); this package is what
JARVIS keeps about the owner across conversations: four profile blocks the owner edits, short
dated facts (told, added, imported, or learned from the owner's own words), the notes block sent
with a reply, background learning, the memory tools and the owner's API operations.

Import the pieces from their modules (`jarvis.recall.service.MemoryService`, …): this package
init stays import-free so `jarvis.core.brain` can depend on it without a cycle.
"""
