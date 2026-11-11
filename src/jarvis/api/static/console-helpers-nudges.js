// src/jarvis/api/static/console-helpers-nudges.js -- R11 Part C's tab in the Helpers panel
// (docs/plans/r11-free-helpers.md D19): each nudge (stand-up, water, a planned activity, free time, focus), its cap, snooze and stop, the water log and the free-time list.
// An ES module loaded by console-helpers.js (never linked); it uses only window.JarvisHelpers' builders and
// textContent. I0 stub: an empty state. Part C fills this file (and only this one) for its tab.
const H = window.JarvisHelpers;
if (H) {
  H.register('nudges', {
    mount(host) { host.append(H.empty('Nudges: stand-up and water reminders, with your limits, snooze and stop, will show here.')); },
  });
}
