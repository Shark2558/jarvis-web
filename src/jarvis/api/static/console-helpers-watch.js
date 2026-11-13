// src/jarvis/api/static/console-helpers-watch.js -- R7 Part D (docs/plans/r7-mobile.md D17, D18): Helpers -> Watch,
// the fifth sub-tab (not an R11 part): steps, heart rate and sleep, "Last synced", a typed sleep time.
// I0 stub: Part D builds it. Loaded by console-helpers.js (an ES module); register with
// window.JarvisHelpers.register('watch', {mount(host, H), refresh?(view)}); textContent only; ASCII source.
const H = window.JarvisHelpers;
if (H) H.register('watch', { mount(host, h) { host.append(h.empty('Your watch and sleep come here once the phone app is linked.')); } });
