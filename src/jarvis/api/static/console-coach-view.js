// src/jarvis/api/static/console-coach-view.js -- R8 builder C (docs/plans/r8-vision.md 4.3; ADR-47): the ONE renderer of
// a use case's view, for the Desk and Workout panes. render(host, view) draws the fixed widget kinds with textContent
// only, the console's own classes and tokens (console-coach.css places them); a widget of any other kind is skipped, so
// a use case never touches the page. Not a pixel pane: it never reads a frame or a camera. ASCII source.
// The widgets (flat scalars, so a home camera's report carries them too; arrays only where named):
//   big        {n, word}                 a number and its word                    e.g. {kind:'big', n: 8, word: 'reps'}
//   line       {text}                    one sentence from the use case's own list
//   tip        {text}                    one form tip, shown as a note
//   timer      {s, word}                 seconds, shown m:ss, and what is timed
//   pacer      {phase, s, of}            breathe in | hold | out, seconds left of `of`
//   targets    {lit, dots: [{x, y}], hands: [{x, y}]}  (or flat t0x, t0y ... t7x, t7y, h0x ... h1y)  0..1 of the view
//   checklist  {items: [{text, ok}]}     (or flat text0, ok0 ... text9, ok9); ok: true | false | null (waiting)
//   bar        {n, word}                 a 0..100 score
//   paused     {why}                     why the count is paused
// Numbers are clamped and words cut to 120 characters; nothing a use case gives is ever parsed as markup.
export const KINDS = Object.freeze(['big', 'line', 'tip', 'timer', 'pacer', 'targets', 'checklist', 'bar', 'paused']);
const MAX = 8, WORDS_MAX = 120, DOTS_MAX = 8, HANDS_MAX = 2, ITEMS_MAX = 10;
const SVG = 'http://www.w3.org/2000/svg';
const PHASES = Object.freeze({ in: 'Breathe in', hold: 'Hold', out: 'Breathe out', rest: 'Rest' });
const MARKS = Object.freeze({ yes: 'Yes', no: 'Not yet', wait: 'Waiting' });

function mk(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined && text !== null) el.textContent = String(text);
  return el;
}
function words(v) { return typeof v === 'string' ? v.slice(0, WORDS_MAX) : ''; }
function num(v, lo, hi) { const n = Number(v); return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : null; }
function unit(v) { return num(v, 0, 1); }

/** "1:05" for 65 seconds; "1:02:03" past an hour. */
export function clock(seconds) {
  const s = Math.round(num(seconds, 0, 86400) || 0), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const two = (x) => (x < 10 ? '0' : '') + x;
  return h ? h + ':' + two(m) + ':' + two(r) : m + ':' + two(r);
}

function big(w) {
  const n = num(w.n !== undefined ? w.n : w.value, -1e6, 1e6);
  if (n === null) return null;
  const box = mk('div', 'r8-big');
  box.setAttribute('role', 'status');
  box.append(mk('b', '', Number.isInteger(n) ? n : n.toFixed(1)), mk('span', '', words(w.word)));
  return box;
}
function line(w) { const t = words(w.text); return t ? mk('p', 'r8-lead', t) : null; }
function tip(w) {
  const t = words(w.text);
  if (!t) return null;
  const p = mk('p', 'bnote r8-tip', t);
  p.setAttribute('role', 'status');
  return p;
}
function timer(w) {
  const s = num(w.s !== undefined ? w.s : w.seconds, 0, 86400);
  if (s === null) return null;
  const box = mk('div', 'r8-big r8-timer');
  box.append(mk('b', '', clock(s)), mk('span', '', words(w.word)));
  return box;
}
function ring(frac) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 64 64');
  svg.setAttribute('aria-hidden', 'true');
  const c = (cls, r) => { const el = document.createElementNS(SVG, 'circle'); el.setAttribute('class', cls); el.setAttribute('cx', '32'); el.setAttribute('cy', '32'); el.setAttribute('r', r); return el; };
  const arc = c('arc', '29'), len = 2 * Math.PI * 29;
  arc.setAttribute('stroke-dasharray', (len * frac).toFixed(1) + ' ' + len.toFixed(1));
  arc.setAttribute('transform', 'rotate(-90 32 32)');
  svg.append(c('trk', '29'), arc, c('disc', String(Math.round(14 + 7 * frac))));
  return svg;
}
function pacer(w) {
  const phase = PHASES[w.phase] ? w.phase : null, s = num(w.s, 0, 600), of = num(w.of, 0.1, 600);
  if (!phase || s === null) return null;
  const left = Math.ceil(s), frac = of ? Math.min(1, Math.max(0, 1 - s / of)) : 0;
  const box = mk('div', 'r8-breath'), r = mk('div', 'r8-ring');
  r.setAttribute('role', 'img');
  r.setAttribute('aria-label', PHASES[phase] + ', ' + left);
  r.append(ring(phase === 'out' ? 1 - frac : frac), mk('b', '', left));
  const say = mk('p', 'r8-bwords');
  say.append(mk('b', '', PHASES[phase]));
  box.append(r, say);
  return box;
}
function spots(list, flat, w, max) { // [{x, y}] or flat keys t0x/t0y (dots) and h0x/h0y (hands)
  const out = [];
  if (Array.isArray(list)) list.slice(0, max).forEach((d) => { const x = unit(d && d.x), y = unit(d && d.y); if (x !== null && y !== null) out.push([x, y]); });
  else for (let i = 0; i < max; i += 1) { const x = unit(w[flat + i + 'x']), y = unit(w[flat + i + 'y']); if (x !== null && y !== null) out.push([x, y]); }
  return out;
}
function targets(w) {
  const dots = spots(w.dots, 't', w, DOTS_MAX), hands = spots(w.hands, 'h', w, HANDS_MAX);
  if (!dots.length) return null;
  const lit = Number.isInteger(w.lit) && w.lit >= 0 && w.lit < dots.length ? w.lit : -1;
  const box = mk('div', 'r8-play');
  box.setAttribute('role', 'img');
  box.setAttribute('aria-label', dots.length + ' targets' + (lit >= 0 ? '; one is lit' : '') + (hands.length ? '; your hands are shown as rings' : ''));
  const place = (el, [x, y]) => { el.style.left = (x * 100).toFixed(1) + '%'; el.style.top = (y * 100).toFixed(1) + '%'; return el; };
  dots.forEach((d, i) => box.append(place(mk('span', 'r8-tg' + (i === lit ? ' lit' : '')), d)));
  hands.forEach((h) => box.append(place(mk('span', 'r8-hand'), h)));
  box.append(mk('span', 'r8-playcap', 'Body lines only'));
  return box;
}
function items(w) { // [{text, ok}] or flat text0/ok0
  const out = [];
  if (Array.isArray(w.items)) w.items.slice(0, ITEMS_MAX).forEach((it) => { if (it && words(it.text)) out.push([words(it.text), it.ok]); });
  else for (let i = 0; i < ITEMS_MAX; i += 1) { if (words(w['text' + i])) out.push([words(w['text' + i]), w['ok' + i]]); }
  return out;
}
function checklist(w) {
  const list = items(w);
  if (!list.length) return null;
  const ul = mk('ul', 'r8-checks');
  ul.setAttribute('role', 'status');
  list.forEach(([text, ok]) => {
    const state = ok === true ? 'ok' : ok === false ? 'warn' : 'wait';
    const li = mk('li', state), mark = mk('i', 'r8-mark', ok === true ? '\u2713' : ok === false ? '!' : '\u2026');
    mark.setAttribute('aria-hidden', 'true');
    li.append(mark, mk('span', '', text), mk('em', '', ok === true ? MARKS.yes : ok === false ? MARKS.no : MARKS.wait));
    ul.append(li);
  });
  return ul;
}
function bar(w) {
  const n = num(w.n !== undefined ? w.n : w.value, 0, 100);
  if (n === null) return null;
  const box = mk('div', 'r8-bar'), head = mk('div', 'rhead'), meter = mk('div', 'mbar'), fill = mk('i');
  head.append(mk('span', 'k', words(w.word) || 'Score'), mk('span', 'k nw', Math.round(n) + ' %'));
  fill.style.width = n + '%';
  meter.setAttribute('role', 'meter');
  meter.setAttribute('aria-valuemin', '0');
  meter.setAttribute('aria-valuemax', '100');
  meter.setAttribute('aria-valuenow', String(Math.round(n)));
  meter.setAttribute('aria-label', words(w.word) || 'Score');
  meter.append(fill);
  box.append(head, meter);
  return box;
}
function paused(w) {
  const p = mk('p', 'bnote r8-paused', words(w.why) || 'Paused.');
  p.setAttribute('role', 'status');
  return p;
}
const DRAW = Object.freeze({ big, line, tip, timer, pacer, targets, checklist, bar, paused });

/** Draw a view into `host` (replacing what was there); returns how many widgets it drew. */
export function render(host, view) {
  if (!host || typeof host.replaceChildren !== 'function') return 0;
  const list = Array.isArray(view) ? view.slice(0, MAX) : [];
  const out = [];
  list.forEach((w) => {
    if (!w || typeof w !== 'object' || !KINDS.includes(w.kind)) return;
    let el = null;
    try { el = DRAW[w.kind](w); } catch (_) { el = null; }
    if (el) { el.dataset.kind = w.kind; out.push(el); }
  });
  host.replaceChildren(...out);
  return out.length;
}
