// src/jarvis/api/static/console-dock-edit.js -- R8 I0 stub (docs/plans/r8-vision.md v8.0.3 D13, part I "your bar, your
// way"; owner from I0 on: R8 builder I, with console-dock.js and console-dock-edit.css). The bar's editor: "Edit the bar"
// from a right-click on the bar, a long-press on touch, a keyboard shortcut and a line in the console's settings (never
// a new always-visible button); drag and drop, arrow keys on a picked item, Remove (to More), Put back, Reset to
// default, Hide the bar with a slim handle and a shortcut to show it again; on the phone, a list in the More sheet. More
// keeps today's behaviour: it shows only when tabs overflow or he removed one. The layout model and its rules are
// console-dock-layout.js (I0). With no saved layout nothing changes: the 1920 px bar stays byte-identical.
// I0: reads nothing, draws nothing.
import { KEY, VERSION } from './console-dock-layout.js';
const STYLE = '/static/console-dock-edit.css'; // I links it when the edit mode first opens
export { KEY, STYLE, VERSION };
