// src/jarvis/api/static/console-tryon.js -- R13.1 I0 STUB (docs/plans/r13-1-try-on.md D1, D7, D8, seam 9): Helpers ->
// Wardrobe -> "Try it on", Part D's section. console-helpers-wardrobe.js mounts it ONCE (mount(host, ctx)), never in
// its draw(); it opens dressed in today's look (tomorrow's from the evening) by itself (D21); a plan's "Show in 3D"
// reaches it as the event 'jarvis:tryon-open' {plan}, and the wardrobe's fresh load as 'jarvis:wardrobe-fresh'. "See
// it on me" (D22) is here too: a photo of a garment he may buy, paired with his own pieces. Its modules:
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
export function open(plan) { void plan; }
// row 388 (D21): console-tryon-card.js hands over a reply's 'tryon' card {day, plan, code, slots}; D draws the
// figure dressed in exactly those pieces under the reply (a private slot covered), or the checklist without 3D
export function inline(el, card) { void el; void card; }
// D22: a picture shared into the app, for See it on me's new garment (his type and colour, the device check, then the
// door's garment()); never sent by this call
export function garment(file) { void file; }
document.addEventListener('jarvis:tryon-open', (e) => open((e.detail || {}).plan));
