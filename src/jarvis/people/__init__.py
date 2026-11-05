# src/jarvis/people/__init__.py
"""Scoped people research (R4 D10/D11; Layer 5 Research & Intel).

    guard      the scope guard: public figures and work due-diligence only (code + tests)
    models     Profile / Dossier
    sources    profile-URL classification (an allow-list of public profile hosts)
    research   PeopleService: search public sources, disambiguate, optional one-call summary
    tools      research_person / people_open_profiles through the gateway
    routes     POST /v1/people/research for the console panel

Import the pieces from their modules. See INTEGRATION.md for what the integrator registers.
"""
