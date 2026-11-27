// src/jarvis/api/static/console-coach-bp.js -- R8 I0 stub (docs/plans/r8-vision.md v8.0.3 D7; owner from I0 on: R8
// builder D). PURE (held to the use-case guard, `export` aside): the blood-pressure monitor's reading from the
// engine's `digits` lines, the same rule as jarvis.coach.bp.proposal_from_digits: three lines top to bottom, each read
// with a score of at least 0.8, the top number the larger; else null (never a guess). The desk pane shows it; he
// confirms or corrects; only then is it sent (POST /v1/coach/bp/readings). I0: the rule, nothing more.
export const READ_MIN_SCORE = 0.8;
const within = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
export function proposal(lines) {
  if (!Array.isArray(lines) || lines.length !== 3 || lines.some((l) => !l || !(l.score >= READ_MIN_SCORE))) return null;
  const [s, d, p] = lines.map((l) => l.value);
  if (!within(s, 60, 260) || !within(d, 30, 160) || !within(p, 30, 220) || d >= s) return null;
  return Object.freeze({ systolic: s, diastolic: d, pulse: p });
}
