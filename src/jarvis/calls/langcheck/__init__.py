# src/jarvis/calls/langcheck/__init__.py
"""R18 B: the language check (docs/plans/r18-calls.md 5.3), the gate every call language passes.

- `scoring`    normalisation, key facts, character error rate and the plan's bars (pure)
- `fleurs`     FLEURS test clips (CC BY 4.0), fetched from Hugging Face at run time
- `sentences`  the 10 call sentences per language, translated once by the brain
- `runner`     the ₹ estimate, then hearing, the voice round trip and speed per language and option
- `select`     the verdict against the bars, the option a language uses, the language table
- `api`        what the Calls panel's language routes call

Import the submodules directly (this package imports nothing, so `jarvis.calls.speech` can use
the scorer without a cycle).
"""
