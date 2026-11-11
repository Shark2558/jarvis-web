// src/jarvis/api/static/console-helpers-kitchen.js -- R11 Part D's tab in the Helpers panel
// (docs/plans/r11-free-helpers.md D19): pantry, recipes, nutrition, grocery spend this month, cooking and washing-up blocks.
// An ES module loaded by console-helpers.js (never linked); it uses only window.JarvisHelpers' builders and
// textContent. I0 stub: an empty state. Part D fills this file (and only this one) for its tab.
const H = window.JarvisHelpers;
if (H) {
  H.register('kitchen', {
    mount(host) { host.append(H.empty('Kitchen: your pantry, recipes, nutrition and grocery spend will show here.')); },
  });
}
