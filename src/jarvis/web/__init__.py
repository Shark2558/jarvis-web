# src/jarvis/web/__init__.py
"""Web search and page reading with citations (Phase 2 · slice 10 B; Layer 5 Research & Intel →
Layer 6 Integration).

    sources    URL normalisation (https only, punycode hosts) and the `Source` citation model
    ledger     the per-conversation numbered sources: web_read's allow-list and cited `sources`
    guard      the private-query guard (emails, phone numbers, the memory sensitive filter)
    ports      `SearchProvider` (the port) and its result types
    tavily     the Tavily adapter (httpx; the only module that knows the vendor)
    allowance  900 Tavily credits per IST month for the deployment (Firestore / MemoryDocs)
    service    the provider + allowance pair, built from settings (None without a key)
    tools      web_search / web_read (R1, through the gateway)

Import the pieces from their modules: this init stays import-free, so `jarvis.core.models` can
depend on `jarvis.web.sources` without a cycle.
"""
