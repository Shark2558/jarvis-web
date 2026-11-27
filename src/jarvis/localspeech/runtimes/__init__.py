# src/jarvis/localspeech/runtimes/__init__.py
"""The kit's model runtimes (R5.2 V1): one module per engine, each importing its package
(faster-whisper, kokoro-onnx, onnxruntime, Piper, transformers, PyAV) only inside its functions,
so importing a module here costs nothing and works where the package is not installed.

Only the kit imports these modules (`engines.Slots` by name, on first use; `service.default_mp3`);
the cloud never does, and no runtime package is in `pyproject.toml`'s dependencies
(tests/test_r52_v1_import_guard.py). Nothing is re-exported here.
"""
