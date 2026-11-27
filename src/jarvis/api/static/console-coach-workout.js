// src/jarvis/api/static/console-coach-workout.js -- R8.1 I0 stub (docs/plans/r8-vision.md v8.0.3 2.2, 4.3; owner from I0
// on: R8.1 builder E). Camera -> Workout, a pixel pane (tests/test_r13_seams.py PANELS) mounted through the Camera
// panel's mode hook: window.JarvisCameraModes.register('workout', {mount(host, P), stop()}). Full screen on the tripod
// phone (390 x 844): the picker, Stop, the wake lock, the browser's voice for counts and tips, the safety lines; it runs
// JarvisVision.live(tasks, {uses, rate, target, onError}) from a tap and posts tallies (POST /v1/coach/results).
// I0: the use cases it loads, and a plain "not built yet" line.
const USES = Object.freeze({
  'reps': () => import('./console-coach-reps.js'),
  'warm-up': () => import('./console-coach-warmup.js'),
  'band': () => import('./console-coach-band.js'),
  'form': () => import('./console-coach-form.js'),
  'yoga': () => import('./console-coach-yoga.js'),
  'plank': () => import('./console-coach-plank.js'),
  'space-check': () => import('./console-coach-space.js'),
  'balance': () => import('./console-coach-balance.js'),
  'boxing': () => import('./console-coach-boxing.js'),
  'agility': () => import('./console-coach-agility.js'),
  'pilates': () => import('./console-coach-pilates.js'),
  'tai-chi': () => import('./console-coach-taichi.js'),
  'jump': () => import('./console-coach-jump.js'),
  'dance': () => import('./console-coach-dance.js'),
  'handstand': () => import('./console-coach-handstand.js'),
  'kettlebell': () => import('./console-coach-kettlebell.js'),
  'partner-stretch': () => import('./console-coach-partner.js'),
  'walk-test': () => import('./console-coach-walk.js'),
  'sit-to-stand': () => import('./console-coach-sitstand.js'),
  'meal': () => import('./console-coach-meal.js'),
});
const VIEW = () => import('./console-coach-view.js'); // the one view renderer (C)
const GEOM = () => import('./console-coach-geom.js'); // preloaded once: the use cases import it statically
const NOT_BUILT = 'The workout coach is not built yet.';
let host = null;
function mount(el, P) { host = el; host.replaceChildren(P.mk('p', 'sfine', NOT_BUILT)); }
function stop() {}
function join() { const modes = window.JarvisCameraModes; return !!(modes && modes.register('workout', { mount, stop })); }
if (!join()) document.addEventListener('jarvis:camera-modes', join, { once: true });
export { USES, VIEW, GEOM };
