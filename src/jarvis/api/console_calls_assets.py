# src/jarvis/api/console_calls_assets.py
"""R18 E (docs/plans/r18-calls/E-NOTES.md): the Calls panel's static files, joined into
`jarvis.api.console.APP_ASSETS`, the console's one exact allow-list (each name below is a literal:
no route builds a path from request input). Kept here so console.py stays inside its size guard.

`console-calls.js` is loaded by console-r7.js; it brings its stylesheet and its parts (ES modules);
`console-calls-audio.js` adds the AudioWorklet module with `audioWorklet.addModule`.
"""

from __future__ import annotations

from typing import Final

_JS: Final = "application/javascript"

CALLS_ASSETS: Final[dict[str, str]] = {
    "console-calls.js": _JS,  # the panel's frame: readiness line, tabs, window.JarvisCalls
    "console-calls-api.js": _JS,  # paths, checks, words, shared builders
    "console-calls-shapes.js": _JS,  # the server's shapes, checked field by field
    "console-calls-card.js": _JS,  # the call card (chat and panel): Call, Edit, Cancel
    "console-calls-form.js": _JS,  # New call: ready cards (Laundry) and the card's fields
    "console-calls-list.js": _JS,  # today's and recent calls, a call's record
    "console-calls-live.js": _JS,  # the live call: captions, Listen, Take over, Tell, Hang up
    "console-calls-audio.js": _JS,  # Listen live (AudioWorklet) and a recording's player
    "console-calls-langs.js": _JS,  # the language check's table and Run
    "console-calls-settings.js": _JS,  # caps, limits, languages, answering, records, speech
    "console-calls-vitals.js": _JS,  # Vitals' "Calls this month" line
    "console-calls.css": "text/css",  # places only (existing tokens and classes)
    "calls-listen-worklet.js": _JS,  # AudioWorkletProcessor: the live call's 16 kHz PCM
}
