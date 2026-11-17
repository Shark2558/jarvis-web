// src/jarvis/api/static/console-tryon-photo.js -- R13.1 I0 STUB (docs/plans/r13-1-try-on.md D12): the THIRD pixel panel
// (tests/test_r13_seams.py PANELS). Part D runs R13's person (SSD) and face (UltraFace) tasks on one bitmap of his photo:
// exactly one person and at most one face pass. The scan module's rules: no fetch, XHR, sendBeacon, WebSocket, storage
// or innerHTML; JarvisConsole.api only to /v1/seeme...; picture bytes leave only through the door's person(); ASCII.
export const NOT_BUILT = 'The photo check is not built yet.';
export function check(file) { void file; return Promise.reject(new Error(NOT_BUILT)); }
