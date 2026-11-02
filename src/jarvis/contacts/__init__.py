# src/jarvis/contacts/__init__.py
"""Google Contacts (Phase 2 · slice 12 D5; Layer 5 Communication → Layer 6 Integration).

    phones   phone numbers as E.164 (+91 default for 10-digit Indian numbers), numbers in text
    client   people.searchContacts over the owner's Google link (optional contacts.readonly)
    tools    contacts_search (R1, through the gateway)

Import the pieces from their modules: this init stays import-free, so `jarvis.core.models` (via
`jarvis.whatsapp.draft`) can depend on `jarvis.contacts.phones` without an import cycle.
"""
