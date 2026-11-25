// src/jarvis/api/static/console-book-chapter-view.js -- R6.4 D7 (docs/plans/r6-4-book-look.md): the chapter player's
// DOM inside #brPlayer, an ES module imported by console-book-chapter.js (the mockups E, F laptop and J phone): the stage
// (the effects engine draws in it), the chapter's side panel (its pages as steps: done, now, next, with minutes), the
// caption bar (aria-live, the spoken words lit: already said in --ink, the rest in --ink-2) and the controls (previous /
// next page and line, play / pause, the progress in page segments with the time and "Page n of m", CC, Sound, speed and
// Stop). A failed load or the chapter's end shows one plain sentence with Back to reading. Every word from the server goes
// in by textContent; icons are built with createElementNS. No build step; CSP script-src 'self'; ASCII source; <= 400 lines.
const SVG = 'http://www.w3.org/2000/svg';
const ICONS = Object.freeze({
  play: ['fill', 'M6 4.2v11.6L15.5 10z'],
  pause: ['fill', 'M5 4h3.4v12H5zM11.6 4H15v12h-3.4z'],
  prev: ['line', 'm12.5 4-6 6 6 6'],
  next: ['line', 'm7.5 4 6 6-6 6'],
  prevp: ['line', 'M5 4v12M15 4l-7 6 7 6'],
  nextp: ['line', 'M15 4v12M5 4l7 6-7 6'],
  back: ['line', 'M8 5 3 10l5 5M3.5 10H17'],
  again: ['line', 'M4 10a6 6 0 1 0 2-4.5M4 4v3h3'],
});
const SECTION = Object.freeze({ title: 'Opening', plain: 'In plain words', example: 'Example', how: 'How it works', chart: 'How it works',
  costs: 'What it costs', fails: 'When it fails' });
export const RUPEE = '\u20b9';

function icon(name) {
  const [how, d] = ICONS[name], s = document.createElementNS(SVG, 'svg'), p = document.createElementNS(SVG, 'path');
  s.setAttribute('viewBox', '0 0 20 20'); s.setAttribute('aria-hidden', 'true'); s.setAttribute('focusable', 'false');
  if (how === 'fill') s.setAttribute('fill', 'currentColor');
  else { s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round'); }
  p.setAttribute('d', d); s.append(p);
  return s;
}
function mk(tag, cls, words) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (words !== undefined) n.textContent = words;
  return n;
}
function btn(id, cls, label, content) {
  const b = mk('button', cls);
  b.type = 'button'; b.id = id; b.setAttribute('aria-label', label);
  if (typeof content === 'string' && ICONS[content]) b.append(icon(content)); else if (content) b.textContent = content;
  return b;
}
/** m:ss */
export function clock(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}
export const sectionName = (view) => SECTION[view] || '';
export const minutesWords = (min) => (min < 1 ? 'under a minute' : min === 1 ? '1 min' : min + ' min');

/**
 * Build the player in `root` (#brPlayer). `on` = {toggle, prevLine, nextLine, prevPage, nextPage, cc, sound, speed, stop,
 * page(index), again}. Returns the view's handle.
 */
export function mount(root, on) {
  root.textContent = '';
  const stage = mk('div', 'bk-stage');
  stage.id = 'brPStage';
  const side = mk('aside', 'bk-side');
  side.setAttribute('aria-label', 'This chapter');
  const kind = mk('span', 'k lp', 'Chapter \u00b7 narrated'), kindPh = mk('span', 'k ph', '');
  const title = mk('h2', '', ''); title.id = 'brPTitle';
  const sub = mk('p', 'sub lp', ''), subPh = mk('p', 'sub ph', '');
  const note = mk('p', 'bk-vnote', ''); note.id = 'brPNote'; note.hidden = true;
  const steps = mk('ol', 'bk-steps lp'); steps.id = 'brPSteps';
  side.append(kind, kindPh, title, sub, subPh, note, steps);

  const cap = mk('div', 'bk-cap'); cap.id = 'brPCap';
  const capText = mk('p', '', ''); capText.id = 'brPCapText';
  capText.setAttribute('aria-live', 'polite');
  cap.append(capText);

  const ctl = mk('nav', 'bk-ctl'); ctl.setAttribute('aria-label', 'Chapter controls');
  const g1 = mk('div', 'grp'), g2 = mk('div', 'grp main'), g3 = mk('div', 'grp'), g4 = mk('div', 'grp');
  const B = {
    prevPage: btn('brPPrevPage', 'bk-btn icon lp', 'Previous page (Page Up)', 'prevp'),
    prevLine: btn('brPPrevLine', 'bk-btn icon', 'Previous line (Left arrow)', 'prev'),
    play: btn('brPPlay', 'play', 'Pause (Space)', 'pause'),
    nextLine: btn('brPNextLine', 'bk-btn icon', 'Next line (Right arrow)', 'next'),
    nextPage: btn('brPNextPage', 'bk-btn icon lp', 'Next page (Page Down)', 'nextp'),
    cc: btn('brPCC', 'bk-btn', 'Captions (C)', 'CC'),
    sound: btn('brPSound', 'bk-btn', 'Sound (M)', 'Sound'),
    speed: btn('brPSpeed', 'bk-btn lp', 'Speed 1\u00d7', '1\u00d7'),
    stop: btn('brPStop', 'bk-btn', 'Stop and go back to reading (Esc)', ''),
  };
  B.stop.append(mk('span', 'lp', 'Stop \u00b7 read'), mk('span', 'ph', 'Stop'));
  g1.append(B.prevPage, B.prevLine); g2.append(B.play); g3.append(B.nextLine, B.nextPage); g4.append(B.cc, B.sound, B.speed, B.stop);
  const prog = mk('div', 'bk-prog'), segs = mk('div', 'bk-segs'), time = mk('div', 'bk-time');
  segs.setAttribute('aria-hidden', 'true');
  prog.setAttribute('role', 'progressbar'); prog.setAttribute('aria-label', 'Chapter progress');
  prog.setAttribute('aria-valuemin', '0'); prog.setAttribute('aria-valuemax', '100');
  const tNow = mk('span', '', '0:00 / 0:00'), tPage = mk('span', '', '');
  tNow.id = 'brPTime'; tPage.id = 'brPPageOf';
  time.append(tNow, tPage); prog.append(segs, time);
  ctl.append(g1, g2, g3, prog, g4);

  const msg = mk('div', 'bk-pmsg'); msg.id = 'brPMsg'; msg.hidden = true;
  const msgText = mk('p', '', ''); msgText.id = 'brPMsgText'; msgText.setAttribute('role', 'status');
  const again = btn('brPAgain', 'bk-btn', 'Play the chapter again', ''); again.append(icon('again'), mk('span', '', 'Play again'));
  const back = btn('brPBack', 'bk-btn cta', 'Back to reading', ''); back.append(icon('back'), mk('span', '', 'Back to reading'));
  const msgRow = mk('div', 'row'); msgRow.append(again, back); msg.append(msgText, msgRow);
  root.append(stage, side, cap, ctl, msg);

  const wire = (b, fn) => b.addEventListener('click', () => fn());
  wire(B.play, on.toggle); wire(B.prevLine, on.prevLine); wire(B.nextLine, on.nextLine); wire(B.prevPage, on.prevPage);
  wire(B.nextPage, on.nextPage); wire(B.cc, on.cc); wire(B.sound, on.sound); wire(B.speed, on.speed); wire(B.stop, on.stop);
  wire(back, on.stop); wire(again, on.again);

  const V = { words: [], lit: -1, pages: [], stepEls: [], segEls: [] };
  function setState(st) { root.dataset.state = st; }

  /** The chapter is known: its title, pages (steps and segments) and the plain line under the title. */
  function ready(info) {
    setState('ready'); msg.hidden = true;
    title.textContent = info.title;
    sub.textContent = info.pages.length + (info.pages.length === 1 ? ' page' : ' pages') + ' \u00b7 about ' + info.minutes +
      (info.minutes === 1 ? ' minute' : ' minutes') + ' \u00b7 your browser\u2019s voice, ' + RUPEE + '0';
    V.pages = info.pages; steps.textContent = ''; segs.textContent = '';
    V.stepEls = info.pages.map((p, i) => {
      const li = mk('li'), b = mk('button', 'step'), no = mk('span', 'no', String(i + 1)), t = mk('span', 'tt');
      b.type = 'button'; b.setAttribute('aria-label', 'Page ' + (i + 1) + ': ' + p.title);
      t.append(mk('b', '', p.title), mk('small', '', minutesWords(p.minutes)));
      b.append(no, t); li.append(b); steps.append(li);
      b.addEventListener('click', () => on.page(i));
      return li;
    });
    V.segEls = info.pages.map(() => { const i = mk('i'); segs.append(i); return i; });
  }
  /** One plain sentence and Back to reading (a failed load, an unnarrated chapter). */
  function fail(words) {
    setState('failed'); msgText.textContent = words; again.hidden = true; msg.hidden = false;
    back.focus();
  }
  function done(words) {
    setState('done'); msgText.textContent = words; again.hidden = false; msg.hidden = false;
    again.focus();
  }
  function loading() { setState('loading'); msg.hidden = true; title.textContent = ''; capText.textContent = ''; }

  // ---- the caption: one span a word; words already spoken are lit --------------------------------------------------
  function caption(text) {
    capText.textContent = '';
    V.words = []; V.lit = -1;
    const re = /\S+/g;
    let m, at = 0;
    while ((m = re.exec(text)) !== null) {
      if (m.index > at) capText.append(document.createTextNode(text.slice(at, m.index)));
      const w = mk('span', 'w', m[0]);
      w.dataset.at = String(m.index);
      capText.append(w); V.words.push({ el: w, at: m.index, end: m.index + m[0].length });
      at = m.index + m[0].length;
    }
    if (at < text.length) capText.append(document.createTextNode(text.slice(at)));
  }
  /** Light the words up to and including the k-th (0-based); -1 none. */
  function lightTo(k) {
    const to = Math.min(V.words.length - 1, k);
    if (to === V.lit) return;
    V.words.forEach((w, i) => w.el.classList.toggle('on', i <= to));
    V.lit = to;
  }
  /** The word a boundary's character index falls in. */
  function wordAt(charIndex) {
    let k = -1;
    V.words.forEach((w, i) => { if (w.at <= charIndex) k = i; });
    return k;
  }

  /** Controls, side panel and progress from the player's state. */
  function sync(st) {
    root.dataset.playing = String(!!st.playing);
    B.play.textContent = ''; B.play.append(icon(st.playing ? 'pause' : 'play'));
    B.play.setAttribute('aria-label', st.playing ? 'Pause (Space)' : 'Play (Space)');
    B.cc.setAttribute('aria-pressed', String(st.cc)); cap.hidden = !st.cc;
    B.sound.setAttribute('aria-pressed', String(st.sound)); B.sound.textContent = st.sound ? 'Sound' : 'Muted';
    const r = st.rate === 1 ? '1' : String(st.rate);
    B.speed.textContent = r + '\u00d7'; B.speed.setAttribute('aria-label', 'Speed ' + r + '\u00d7 (change)');
    if (!V.pages.length) return;
    const pi = st.pageIndex, page = V.pages[pi] || V.pages[0], sec = sectionName(st.view);
    const where = (sec ? sec + ' \u00b7 ' : '') + 'line ' + (st.lineInPage + 1) + ' of ' + page.lines;
    kindPh.textContent = 'Chapter \u00b7 page ' + (pi + 1) + ' of ' + V.pages.length;
    subPh.textContent = (page.title && page.title !== title.textContent ? page.title + ' \u00b7 ' : '') + where;
    V.stepEls.forEach((li, i) => {
      li.className = i < pi ? 'done' : i === pi ? 'now' : '';
      const small = li.querySelector('small');
      if (small) small.textContent = i === pi ? where : minutesWords(V.pages[i].minutes);
      const b = li.querySelector('button');
      if (b) { if (i === pi) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current'); }
    });
    V.segEls.forEach((seg, i) => {
      seg.className = i < pi ? 'done' : i === pi ? 'now' : '';
      seg.style.setProperty('--p', i === pi ? Math.round(st.pageFrac * 100) + '%' : '0%');
    });
    tNow.textContent = clock(st.elapsed) + ' / ' + clock(st.total);
    tPage.textContent = 'Page ' + (pi + 1) + ' of ' + V.pages.length;
    const pct = st.total ? Math.round((st.elapsed / st.total) * 100) : 0;
    prog.setAttribute('aria-valuenow', String(pct));
    prog.setAttribute('aria-valuetext', 'Page ' + (pi + 1) + ' of ' + V.pages.length + ', ' + where);
  }
  function cloudNote(on) {
    note.hidden = !on;
    note.textContent = on ? 'Your Book is set to the cloud voice. Chapters use your browser\u2019s voice (' + RUPEE + '0); the cloud voice reads the short tour only.' : '';
  }
  return { stage, steps, buttons: B, ready, fail, done, loading, caption, lightTo, wordAt, words: () => V.words.length, sync, cloudNote };
}
