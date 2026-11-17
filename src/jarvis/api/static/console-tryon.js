// src/jarvis/api/static/console-tryon.js -- R13.1 I0 STUB (docs/plans/r13-1-try-on.md D1, D7, D8, seam 9): Helpers ->
// Wardrobe -> "Try it on", Part D's section. console-helpers-wardrobe.js mounts it ONCE (mount(host, ctx)), never in
// its draw(); a plan's "Show in 3D" / "See it on me" reach it as the event 'jarvis:tryon-open' {plan, see}, and the
// wardrobe's fresh load as 'jarvis:wardrobe-fresh'. seeOn() says whether "See it on me" is offered. Its modules:
// './console-tryon-list.js' (the checklist), './console-tryon-me.js' (See it on me) and './console-tryon-3d.js' (B).
// Until Part D builds it, the section says so and nothing else runs.
let host = null;
const load = () => Promise.all([import('./console-tryon-list.js'), import('./console-tryon-me.js'), import('./console-tryon-3d.js')]);
export function mount(el, ctx) {
  host = el;
  void ctx; void load;
  const H = window.JarvisHelpers;
  if (H && host) host.replaceChildren(H.mk('h3', 'hp-h', 'Try it on'), H.empty('Try it on is not built yet.'));
}
export function seeOn() { return false; }
export function open(plan, opts) { void plan; void opts; }
document.addEventListener('jarvis:tryon-open', (e) => { const d = e.detail || {}; open(d.plan, { see: !!d.see }); });
