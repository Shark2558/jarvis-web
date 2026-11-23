// src/jarvis/api/static/console-book-script.js -- R6.3 I0 seam 9 (docs/plans/r6-3-book-content.md D9): the show's
// script reader, moved out of console-book-show.js unchanged in behaviour (line, normalScene, normalScript, timeline),
// plus the short tour's shape. GET /v1/book/show/script answers kind "show" (today's scenes 1-11, beats sNNbMM) or
// kind "tour" (scenes 1-17, beats tNNbMM, each scene's picture {visual: one of today's 11 pictures, facts}, its
// audience and its full-book chapter). Questions and Closing follow the last scene (qn, cn: 12 and 13 for the show,
// 18 and 19 for the tour); `picture(scene)` gives the picture modules the scene they draw: a tour scene as today's
// picture `visual` with its OWN facts, Questions as 12 and Closing as 13, so the 3D and 2D pictures need no change.
// window.JarvisBookScript = { line, normalScene, normalScript, timeline, picture }. Every field is checked; text is
// returned as plain strings for textContent. No build step; CSP script-src 'self'; ASCII source; <= 200 lines.
(() => {
  'use strict';
  const SHOW_ID = /^s\d{2}b\d{2}$/, TOUR_ID = /^t\d{2}b\d{2}$/, KEY_ID = /^[a-z_]{2,20}$/, RID = /^[0-9a-f]{7}$/;
  const VER = /^v\d{1,3}\.\d{1,3}\.\d{1,4}$/; // R6.1 decision 3: the release's version, next to its id
  const PAGE = /^pg_(?:chapter|module|card|screen|service)_[a-z0-9_]{1,40}$/;
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const LAST = { show: 11, tour: 17 }; // the content scenes of each kind
  const QUESTIONS = 12, CLOSING = 13; // the picture modules' numbers for the two fixed scenes
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 400) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const who = (v, allowed) => (allowed.includes(v) ? v : 'both');

  function line(v) {
    const o = obj(v), id = o ? txt(o.id, 40) : '', text = o ? txt(o.text, 1200) : txt(v, 1200);
    return text ? { id: KEY_ID.test(id) ? id : '', text } : null;
  }
  function facts(v) {
    return arr(v).map(obj).filter(Boolean).slice(0, 60).map((f) => ({ label: txt(f.label, 80), value: txt(f.value, 120),
      n: num(f.n), group: txt(f.group, 40), flag: txt(f.flag, 20) }));
  }
  /** One scene of either kind; null when it is not one (wrong number, no beat, a beat id of the other kind). */
  function normalScene(v, kind = 'show') {
    const s = obj(v), tour = kind === 'tour', id = tour ? TOUR_ID : SHOW_ID;
    if (!s || !Number.isInteger(s.n) || s.n < 1 || s.n > LAST[tour ? 'tour' : 'show']) return null;
    const beats = arr(s.beats).map(obj).filter((b) => b && id.test(b.id || '') && txt(b.text))
      .map((b) => (tour ? { id: b.id, text: txt(b.text), focus: txt(b.focus, 60), audience: who(b.audience, ['owner', 'guest']) }
        : { id: b.id, text: txt(b.text), focus: txt(b.focus, 60) }));
    if (!beats.length) return null;
    const out = { n: s.n, id: txt(s.id, 40), title: txt(s.title, 60), beats, facts: facts(s.facts) };
    if (!tour) return out;
    const p = obj(s.picture) || {}, visual = Number.isInteger(p.visual) && p.visual >= 1 && p.visual <= 11 ? p.visual : 0;
    if (!visual) return null;
    return Object.assign(out, { facts: [], picture: { visual, facts: facts(p.facts) }, audience: who(s.audience, ['owner']),
      chapter: PAGE.test(s.chapter || '') ? s.chapter : '' });
  }
  function normalScript(raw, audience) {
    const d = obj(raw);
    if (!d) return null;
    const kind = d.kind === 'tour' ? 'tour' : 'show';
    const scenes = arr(d.scenes).map((s) => normalScene(s, kind)).filter(Boolean).sort((a, b) => a.n - b.n);
    if (!scenes.length) return null;
    const L = obj(d.lines) || {}, lines = {};
    ['ask', 'anything_else', 'hand_back', 'ai_off'].forEach((k) => { const l = line(L[k]); if (l) lines[k] = { id: l.id || k, text: l.text }; });
    const whose = d.audience === 'owner' || d.audience === 'guest' ? d.audience : audience;
    let closing = d.closing;
    if (obj(closing)) closing = closing[whose];
    const rel = obj(d.release) || {}, talk = obj(d.talk) || {}, costs = obj(d.costs) || {};
    const last = LAST[kind]; // the show: 12 and 13 as before; the tour: 18 and 19
    return { kind, qn: last + 1, cn: last + 2, seconds: num(d.seconds),
      release: { id: RID.test(rel.id || '') ? rel.id : '', label: txt(rel.label, 8), version: VER.test(rel.version || '') ? rel.version : '' },
      audience: whose, scenes, lines,
      closing: arr(closing).map(line).filter(Boolean).slice(0, 6), costs: { month: num(costs.month_inr), limit: num(costs.limit_inr) },
      talk: { on: talk.on !== false, why: txt(talk.why, 200) }, until: txt(d.until, 40),
      voice: d.voice === 'cloud' ? 'cloud' : 'browser', listening: d.listening === 'cloud' ? 'cloud' : 'browser' }; // R6.2 decision 4: Rs 0 unless he chose the cloud
  }
  function timeline(sc) {
    const out = [];
    sc.scenes.forEach((s) => s.beats.forEach((b, i) => out.push({ scene: s.n, i, id: b.id, text: b.text, focus: b.focus })));
    const q = sc.talk.on ? sc.lines.ask : sc.lines.ai_off;
    out.push({ scene: sc.qn, i: 0, id: q ? q.id : '', text: q ? q.text : '', focus: '', ask: true });
    sc.closing.forEach((l, i) => out.push({ scene: sc.cn, i, id: l.id, text: l.text, focus: '', closing: true }));
    return out;
  }
  /** What the picture modules draw for scene n of the script: today's picture numbers, the scene's own data. */
  function picture(sc, n, beats) {
    if (n === sc.qn || n === sc.cn) {
      return { n: n === sc.qn ? QUESTIONS : CLOSING, id: n === sc.qn ? 'questions' : 'closing', title: '', beats: beats.filter((b) => b.scene === n), facts: [] };
    }
    const s = sc.scenes.find((x) => x.n === n);
    if (!s) return { n, id: '', title: '', beats: [], facts: [] };
    return s.picture ? { n: s.picture.visual, id: s.id, title: s.title, beats: s.beats, facts: s.picture.facts } : s;
  }
  window.JarvisBookScript = Object.freeze({ line, normalScene, normalScript, timeline, picture, QUESTIONS, CLOSING });
})();
