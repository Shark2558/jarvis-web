// src/jarvis/api/static/console-camera-setup.js -- R8 I0 stub (docs/plans/r8-vision.md v8.0.3 4.5, 4.6; owner from I0 on:
// R8 builder B). Camera -> Cameras, a pixel pane (it runs the setup test: tests/test_r13_seams.py PANELS) mounted
// through the Camera panel's mode hook: window.JarvisCameraModes.register('cameras', {mount(host, P), stop()}), below
// the pane's own "This device" and "Home camera" sections. It will hold the cameras, spots and rooms with their off
// switches (GET/PUT /v1/camera/spots), each camera's health, "Run the setup test" (console-vision-check.js, A) and
// "Check a camera" before and after buying (the bridge's camera check, for his Imou Ranger S2 or any RTSP/ONVIF camera).
// I0: the setup test's module, and a plain "not built yet" line.
const CHECK = () => import('./console-vision-check.js');
const STYLE = '/static/console-camera-setup.css'; // B links it when the pane is built
const NOT_BUILT = 'Camera setup is not built yet.';
function mount(el, P) { el.append(P.mk('p', 'sfine', NOT_BUILT)); }
function stop() {}
function join() { const modes = window.JarvisCameraModes; return !!(modes && modes.register('cameras', { mount, stop })); }
if (!join()) document.addEventListener('jarvis:camera-modes', join, { once: true });
export { CHECK, STYLE };
