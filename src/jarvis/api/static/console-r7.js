// src/jarvis/api/static/console-r7.js -- R7 I0 (docs/plans/r7-mobile.md "The I0 seams" 10, 25): the one line
// console.html gains for R7's modules. This module loads the parts' modules and their stylesheets itself, so no
// builder edits console.html:
//   console-r7-send.js      I0  the one door that sends a picture: Ask, Vault, Attach, "Pictures sent today"
//   console-vision.js       I0  the vision engine's port (core); B fills its tasks
//   console-r7-links.js     A   launch addresses (?do=talk|look|sos|shared, ?open=<panel>): open a screen, never act
//   console-r7-share.js     A   the share tray (items wait on the phone until a press)
//   console-camera.js       B   the camera's one door and hard off switch
//   console-camera-panel.js B   the Camera panel (Look, Results, Cameras)
//   console-r7-phone.js     C   Integrations -> Phone app (link, unlink, sign out everywhere)
//   console-r7-lock.js      C   the app lock's unlock cover (console.js fires jarvis:device-locked)
//   console-r7-sos.js       D   the SOS sheet and Integrations -> Emergency SOS
// (Helpers -> Watch, console-helpers-watch.js, is loaded by the Helpers frame.) Each part's stylesheet may only
// place things: existing tokens and classes, no new colours, fonts, radii or shadows (plan D0), at most 150
// lines. No build step; CSP script-src 'self' and style-src 'self'; textContent only. A module asks the server
// NOTHING before sign-in (BRIEF-COMMON.md): it waits for jarvis:ready.
//   window.JarvisMobile  { mk(tag, cls, text) -> element, api(path, opts) -> Promise<json>,
//                          part(name, obj) -> obj   a part publishes what others may call,
//                          parts                    {send, vision, links, share, camera, panel, phone, lock, sos} }
const PARTS = ['send', 'vision', 'links', 'share', 'camera', 'panel', 'phone', 'lock', 'sos'];
const parts = {};

function mk(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

// the console's own transport (auth, X-Requested-With); a part never calls fetch itself
function api(path, opts) {
  const con = window.JarvisConsole;
  if (!con || typeof con.api !== 'function') return Promise.reject(new Error('The console is still starting.'));
  return con.api(path, opts);
}

function part(name, obj) {
  if (PARTS.includes(name) && obj && typeof obj === 'object' && !parts[name]) parts[name] = obj;
  return obj;
}

window.JarvisMobile = { mk, api, part, parts };

for (const href of ['/static/console-r7-share.css', '/static/console-camera.css',
  '/static/console-r7-phone.css', '/static/console-r7-sos.css']) {
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = href;
  document.head.append(css);
}
import('./console-r7-send.js').catch(() => {});
import('./console-vision.js').catch(() => {});
import('./console-r7-links.js').catch(() => {});
import('./console-r7-share.js').catch(() => {});
import('./console-camera.js').catch(() => {});
import('./console-camera-panel.js').catch(() => {});
import('./console-r7-phone.js').catch(() => {});
import('./console-r7-lock.js').catch(() => {});
import('./console-r7-sos.js').catch(() => {});
