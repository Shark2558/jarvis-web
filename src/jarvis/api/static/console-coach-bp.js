// src/jarvis/api/static/console-coach-bp.js -- R8 builder D, row 262's reading (docs/plans/r8-vision.md v8.0.4 D7, seam
// S26). PURE (held to the use-case guard, `export` aside): numbers in, numbers out; no page, network, storage, camera
// or engine, and it keeps nothing. The monitor's seven-segment display is read by the engine's `digits` task (its
// body, segment arithmetic, is in console-vision-r8.js: the engine alone sees pixels); this is the rule that turns
// that task's lines into what the pane shows him, the same rule as jarvis.coach.bp.proposal_from_digits: three lines
// top to bottom, each read with a score of at least READ_MIN_SCORE, the top number the larger; else null (never a
// guess). The desk pane shows the proposal; he confirms or corrects it; only then is it sent (POST
// /v1/coach/bp/readings), and the server keeps only a confirmed reading (BpConfirm).
export const READ_MIN_SCORE = 0.8;
const within = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
export function proposal(lines) {
  if (!Array.isArray(lines) || lines.length !== 3 || lines.some((l) => !l || !(l.score >= READ_MIN_SCORE))) return null;
  const [s, d, p] = lines.map((l) => l.value);
  if (!within(s, 60, 260) || !within(d, 30, 160) || !within(p, 30, 220) || d >= s) return null;
  return Object.freeze({ systolic: s, diastolic: d, pulse: p });
}
