// src/jarvis/api/static/console-r111.js -- R11.1 I0 (docs/plans/r11-1-observations.md "The I0 seams"): the
// one line console.html gains for R11.1. This module loads the four parts' modules and their stylesheets
// itself (the Helpers panel does the same for its tabs), so no builder edits console.html:
//   console-r111-plan.js    A  the calendar batch card's list, the study-plan check-in and re-plan cards
//   console-r111-files.js   B  "heard / understood as" in the chat, folder and zip attach, the cost line
//   console-r111-photos.js  C  a Photos import's progress line, the face groups to name
//   console-r111-look.js    D  profile cards in People, "research this picture"
// Each part's stylesheet (console-r111-<part>.css) may only place things: existing tokens and classes,
// no new colours, fonts, radii or shadows (plan D0). No build step; CSP script-src 'self' and
// style-src 'self'; textContent only.
//   window.JarvisFixes  { mk(tag, cls, text) -> element, api(path, opts) -> Promise<json>,
//                         part(name, obj) -> obj   a part publishes what others may call,
//                         parts                    {plan, files, photos, look} once each has loaded }
const PARTS = ['plan', 'files', 'photos', 'look'];
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
  if (PARTS.includes(name) && obj && typeof obj === 'object') parts[name] = obj;
  return obj;
}

window.JarvisFixes = { mk, api, part, parts };

for (const href of ['/static/console-r111-plan.css', '/static/console-r111-files.css',
  '/static/console-r111-photos.css', '/static/console-r111-look.css']) {
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = href;
  document.head.append(css);
}
import('./console-r111-plan.js').catch(() => {});
import('./console-r111-files.js').catch(() => {});
import('./console-r111-photos.js').catch(() => {});
import('./console-r111-look.js').catch(() => {});
