# src/jarvis/calls/__init__.py
"""R18 "Calls from your laptop" (docs/plans/r18-calls.md; seams: docs/plans/r18-calls/I0-SEAMS.md).

The Communication skill's calls: call cards approved by the owner (R3), the call desk on his laptop
(audio over Windows Phone Link), the phone app placing and answering calls, speech per language,
records in the vault. The shared seams:

- `models`: cards, records, states, settings, the brief's caps and limits as constants
- `protocol`: every desk / phone / console message and the binary audio frames
- `ports`: the Protocols the parts implement (hearing, voice, detector, store, desk, phone)
- `store`: `DocCallStore` on the `Docs` port (Firestore in production) and `MemoryCallStore`
- `settings`: the owner's call settings with their defaults
- `prices`: speech prices in ₹ from `Settings` (unknown is never ₹0)
- `tools`: the gateway tools `calls_place` (R3) and `calls_answer_mode`

Nothing here imports a vendor SDK; speech vendors are reached over REST / WebSocket (`jarvis.calls
.speech`) and the brain only through `jarvis.llm` tiers.
"""
