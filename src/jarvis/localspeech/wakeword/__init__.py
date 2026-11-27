# src/jarvis/localspeech/wakeword/__init__.py
"""R5.2 row 83, "your own Hey Jarvis" (plan 3.4, D5; Layer 2): the wake word's training on the
laptop kit, and the two files it makes for the console.

- `port`: `WakewordKit`, the interface V1's kit server calls (with `WakeClip`, `WakeJob`,
  `Progress`, `WakewordFailed`, and the `Sealer` / `Voices` ports V1 provides); `build_wakeword`
  (`service`) makes the one instance
- `formats` (pure; the cloud reads it too): `VerifierFile` (stage 1's JSON weights), `ModelCard`
  (stage 2's MANIFEST), the console detector's numbers and the licence record (`LAUNCH_WORDS`)
- `evals` (pure): the console's wake rule (`Decider`), `WakeEval`, `WAKE_BARS`, `beats`
- `store`: the trained files, sealed with the kit's at-rest key
- the kit-only modules (`RUNTIME_MODULES`; NumPy, onnxruntime): `streaming` (the console's
  pipeline in Python), `verifier_train` (stage 1), `mlp`, `onnx_write`, `owned_train` and
  `synth` (stage 2), `runtime` (the vendored models, SHA-256 checked), `fakes` (tests)

The cloud never imports the runtime modules (V1's import-guard test); importing this package or
`port`, `formats`, `evals`, `store`, `service` loads neither NumPy nor onnxruntime.
"""

from typing import Final

from jarvis.localspeech.wakeword.port import WakewordKit
from jarvis.localspeech.wakeword.service import build_wakeword

RUNTIME_MODULES: Final = tuple(
    f"jarvis.localspeech.wakeword.{name}"
    for name in (
        "fakes",
        "mlp",
        "onnx_write",
        "owned_train",
        "runtime",
        "streaming",
        "synth",
        "verifier_train",
    )
)

__all__ = ["RUNTIME_MODULES", "WakewordKit", "build_wakeword"]
