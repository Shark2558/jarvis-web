// src/jarvis/api/static/console-wardrobe-scan.js -- R13 Part D (docs/plans/r13-wardrobe.md D5, D7, D9): Camera ->
// Wardrobe, the SECOND named pixel panel (tests/test_r13_seams.py PANELS), mounted into the camera panel's fourth
// sub-tab through window.JarvisCameraModes.register('wardrobe', {mount, stop}). I0 stub: it says the phone
// checkpoints are not built yet. Part D fills it ("Add pieces", "To laundry", "Back clean", "Find", "Read a label")
// under the camera panel's rules: no fetch, XHR, sendBeacon, WebSocket, localStorage, sessionStorage or indexedDB;
// JarvisConsole.api only to /v1/wardrobe and /v1/laundry paths and never with picture bytes; picture bytes only
// through the door (window.JarvisMobile.parts.send: wardrobe(), tag()); textContent only; ASCII source.
const NOT_YET = 'The wardrobe\u2019s phone checkpoints are not built yet.';

function mount(host, P) { host.append(P.mk('p', 'snote', NOT_YET)); }
function stop() {}
function join() {
  const modes = window.JarvisCameraModes;
  return !!(modes && modes.register('wardrobe', { mount, stop }));
}
if (!join()) document.addEventListener('jarvis:camera-modes', join, { once: true });
