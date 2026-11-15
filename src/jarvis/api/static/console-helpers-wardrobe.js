// src/jarvis/api/static/console-helpers-wardrobe.js -- R13 Part D (docs/plans/r13-wardrobe.md D1): Helpers -> Wardrobe,
// the sixth sub-tab (console-only: helpers/kinds.py TABS stays the five). I0 stub: it says the wardrobe is not built
// yet, asks the server nothing and loads Part D's pieces module. Part D fills it: the sections "Needs a check", "Today
// and tomorrow", "Laundry", "Pieces", "Labels" and "Settings", from window.JarvisHelpers' builders and existing classes
// only (the look does not change); the routes and shapes of jarvis.wardrobe.http; every change through
// POST /v1/wardrobe/tools/{tool} (the gateway's cards); textContent only; nothing asked before sign-in; ASCII source.
const H = window.JarvisHelpers;
if (H) H.register('wardrobe', { mount(host) { host.append(H.empty('The wardrobe is not built yet.')); } });
import('./console-wardrobe-pieces.js').catch(() => {});
