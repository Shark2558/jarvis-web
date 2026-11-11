// src/jarvis/api/static/console-helpers-today.js -- R11 Part A's tab in the Helpers panel
// (docs/plans/r11-free-helpers.md D19): top priority now, what is pending, bills and the prepared UPI payment, birthdays.
// An ES module loaded by console-helpers.js (never linked); it uses only window.JarvisHelpers' builders and
// textContent. I0 stub: an empty state. Part A fills this file (and only this one) for its tab.
const H = window.JarvisHelpers;
if (H) {
  H.register('today', {
    mount(host) { host.append(H.empty('Today: your top priority, what is pending, bills and birthdays will show here.')); },
  });
}
