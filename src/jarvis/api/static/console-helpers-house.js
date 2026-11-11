// src/jarvis/api/static/console-helpers-house.js -- R11 Part B's tab in the Helpers panel
// (docs/plans/r11-free-helpers.md D19): the chores rota, home upkeep, weather and disaster alerts for your place, breach notices.
// An ES module loaded by console-helpers.js (never linked); it uses only window.JarvisHelpers' builders and
// textContent. I0 stub: an empty state. Part B fills this file (and only this one) for its tab.
const H = window.JarvisHelpers;
if (H) {
  H.register('house', {
    mount(host) { host.append(H.empty('Home: the chores rota, home upkeep, weather and disaster alerts will show here.')); },
  });
}
