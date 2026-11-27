// src/jarvis/api/static/console-coach-desk.js -- R8 I0 stub (docs/plans/r8-vision.md v8.0.3 4.3, 4.5a, 4.10; owner from
// I0 on: R8 builder C). Camera -> Desk, a pixel pane (tests/test_r13_seams.py PANELS) mounted through the Camera panel's
// mode hook: window.JarvisCameraModes.register('desk', {mount(host, P), stop()}). It will run the webcam's coaches with
// JarvisVision.live(tasks, {uses, rate, target, onError}) from a tap (and the small always-on-top window, D10), draw
// each use case's view with console-coach-view.js, post tallies (POST /v1/coach/results) and camera health, read the
// switches every 60 s, and show the home camera's coaches from GET /v1/coach/live (they run on the home laptop, D3).
// I0: the use cases it loads, and a plain "not built yet" line.
const USES = Object.freeze({
  'reaction-game': () => import('./console-coach-reaction.js'),
  'breath': () => import('./console-coach-breath.js'),
  'water': () => import('./console-coach-water.js'),
  'hand-rehab': () => import('./console-coach-handrehab.js'),
  'reach-grasp': () => import('./console-coach-reach.js'),
});
const VIEW = () => import('./console-coach-view.js'); // the one view renderer (C)
const GEOM = () => import('./console-coach-geom.js'); // preloaded once: the use cases import it statically
const BP = () => import('./console-coach-bp.js'); // the monitor's reading (D7, D)
const NOT_BUILT = 'The desk coach is not built yet.';
let host = null;
function mount(el, P) { host = el; host.replaceChildren(P.mk('p', 'sfine', NOT_BUILT)); }
function stop() {}
function join() { const modes = window.JarvisCameraModes; return !!(modes && modes.register('desk', { mount, stop })); }
if (!join()) document.addEventListener('jarvis:camera-modes', join, { once: true });
export { USES, VIEW, GEOM, BP };
