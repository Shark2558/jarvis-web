# src/jarvis/whatsapp/__init__.py
"""WhatsApp drafts (Phase 2 · slice 12 D6; Layer 5 Communication → Layer 1/8 draft card).

JARVIS writes the message; the owner opens it in WhatsApp (a wa.me link) and presses Send.
JARVIS sends nothing and talks to no WhatsApp service.

    draft        the draft text rules, the wa.me link, the `DraftCard` a reply carries (pure)
    provenance   where a recipient number came from: the owner's words, Contacts, or elsewhere
    tools        whatsapp_draft (R1, through the gateway)
    cards        the reply's draft cards, read from the tool results that ran

Import the pieces from their modules: this init stays import-free, so `jarvis.core.models` can
depend on `jarvis.whatsapp.draft` without an import cycle.
"""
