// src/jarvis/api/static/console-book-reader.js -- R6 D16: the build book's sections reader (architecture, stack, libraries,
// integrations, workflows, limitations, costs, decisions) and the Book settings form, used by console-book.js.
// Every section is a collapsed disclosure (.dsc / .dbody, the Brief's settings look) that builds its rows only when
// opened, so a long library list costs nothing until it is read. Rows reuse the Brief's pieces (.bsec, .bev / .btime /
// .bwhat, .blines, .bchips) and the amber .tag for a flagged licence (the word says it too, never colour alone).
// Server text reaches the page through textContent only; a field of the wrong type is dropped, never guessed.
// No build step; CSP script-src 'self'; ASCII source; <= 400 lines.
// window.JarvisBookReader = { sections(host, raw) -> count, settings(host, deps) }.
(() => {
  'use strict';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const SVG = 'http://www.w3.org/2000/svg';
  const fmt = (n) => { try { return new Intl.NumberFormat('en-IN').format(n); } catch (_) { return String(n); } };
  const inr = (v) => '\u20b9' + (v >= 100 ? fmt(Math.round(v)) : (Math.round(v * 100) / 100).toFixed(2));
  // the architecture's own names, as buildbook/sections.py LAYERS gives them (a static test keeps the two equal)
  const LAYER_NAMES = { L1: 'User Interaction', L2: 'Input Processing', L3: 'Context & Orchestration', L4: 'Core Reasoning Engine',
    L5: 'Skills & Capabilities', L6: 'Integration & Tools', L7: 'Data & Persistence', L8: 'Response & Output', X: 'Cross-cutting' };
  const FLAG = { copyleft: 'Copyleft', non_commercial: 'Non-commercial' };
  const KIND = { not_in_plan: 'Not in a plan', risk: 'Risk', needs_owner: 'Needs you', open_question: 'Open question', deferred: 'Deferred', licence: 'Licence' };
  let seq = 0;

  function chevron() {
    const s = document.createElementNS(SVG, 'svg'), p = document.createElementNS(SVG, 'path');
    s.setAttribute('viewBox', '0 0 20 20'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('aria-hidden', 'true');
    s.setAttribute('class', 'dchev'); p.setAttribute('d', 'm6 8 4 4 4-4'); s.append(p); return s;
  }
  /** A disclosure: label, a one-line summary while closed, and a body built on first open. */
  function disclosure(label, summary, build, open) {
    const wrap = mk('div', 'bset bk-sec'), id = 'bkSec' + (++seq);
    const btn = mk('button', 'dsc'); btn.type = 'button'; btn.setAttribute('aria-controls', id);
    btn.append(mk('span', 'dl', label), chevron(), mk('span', 'dsum', summary));
    const body = mk('div', 'dbody'); body.id = id; body.hidden = true;
    let built = false;
    const set = (on) => {
      btn.setAttribute('aria-expanded', String(on)); body.hidden = !on;
      if (on && !built) { built = true; build(body); }
    };
    btn.addEventListener('click', () => set(btn.getAttribute('aria-expanded') !== 'true'));
    set(!!open); wrap.append(btn, body); return wrap;
  }
  /** One row: a short key on the left (a layer, a price, a kind), a title and its detail. */
  function row(key, title, detail, chip) {
    const li = mk('li', 'bev'), what = mk('div', 'bwhat');
    li.append(mk('span', 'btime', key || '\u2014'), what);
    const b = mk('b', '', title); what.append(b);
    if (chip) b.append(' ', mk('span', 'tag bk-flag', chip));
    if (detail) what.append(mk('small', '', detail));
    return li;
  }
  const list = (rows, cls) => { const ul = mk('ul', 'bevents' + (cls ? ' ' + cls : '')); rows.forEach((r) => ul.append(r)); return ul; };
  function group(body, title, rows, count) {
    if (!rows.length) return;
    const sec = mk('div', 'bsec'), h = mk('h3', '', title);
    if (count) h.append(mk('span', 'bcount', count));
    sec.append(h, list(rows)); body.append(sec);
  }
  const none = (body, words) => body.append(mk('p', 'bempty', words));

  // ---- the eight sections ----------------------------------------------------------------------
  function architecture(d) {
    const pk = arr(d.packages).map(obj).filter(Boolean);
    const layers = Object.keys(LAYER_NAMES);
    const by = (l) => pk.filter((p) => p.layer === l);
    return {
      sum: pk.length + ' packages in ' + layers.filter((l) => by(l).length).length + ' layers',
      build(body) {
        layers.forEach((l) => group(body, l + ' \u00b7 ' + LAYER_NAMES[l], by(l).map((p) => row(txt(p.name, 60),
          txt(p.summary, 200) || txt(p.name, 60), [num(p.files) !== null ? fmt(p.files) + ' files' : '', num(p.lines) !== null ? fmt(p.lines) + ' lines' : ''].filter(Boolean).join(' \u00b7 '))), String(by(l).length)));
        group(body, 'Where each release fits', arr(d.fit).map(obj).filter(Boolean).map((f) => row(txt(f.release, 8),
          txt(f.feature, 160), [txt(f.layer, 160), txt(f.phase, 60) && 'Phase ' + txt(f.phase, 60), txt(f.verdict, 160)].filter(Boolean).join(' \u00b7 '))));
        if (!pk.length) none(body, 'No packages listed.');
      },
    };
  }
  function stack(d) {
    const items = arr(obj(d) ? d.items : d).map(obj).filter(Boolean);
    return { sum: items.length + ' parts', build(body) {
      group(body, 'What JARVIS runs on', items.map((s) => row(txt(s.role, 40), txt(s.name, 80) + (txt(s.version, 40) ? ' ' + txt(s.version, 40) : ''), txt(s.source, 160))));
      if (!items.length) none(body, 'Nothing listed.');
    } };
  }
  function libraries(d) {
    const libs = arr(d).map(obj).filter(Boolean), flagged = libs.filter((l) => FLAG[l.flag]);
    return { sum: libs.length + ' libraries' + (flagged.length ? ', ' + flagged.length + ' flagged' : ''), build(body) {
      const r = (l) => row(txt(l.kind, 20), txt(l.name, 80) + (txt(l.version, 40) ? ' ' + txt(l.version, 40) : ''),
        [txt(l.licence, 80) || 'not stated', txt(l.role, 40)].filter(Boolean).join(' \u00b7 '), FLAG[l.flag] || '');
      group(body, 'Flagged licences', flagged.map(r), String(flagged.length));
      group(body, 'Every library', libs.map(r), String(libs.length));
      if (!libs.length) none(body, 'No libraries listed.');
    } };
  }
  function integrations(d) {
    const sv = arr(d.services).map(obj).filter(Boolean), keys = arr(d.key_purposes).map((k) => txt(k, 60)).filter(Boolean);
    const alerts = arr(d.alert_kinds).map(obj).filter(Boolean);
    return { sum: sv.length + ' services, ' + alerts.length + ' alert kinds', build(body) {
      group(body, 'Services', sv.map((s) => row(s.checked === true ? 'checked' : '', txt(s.label, 80), [txt(s.what, 300),
        arr(s.settings).map((x) => txt(x, 60)).filter(Boolean).join(', ')].filter(Boolean).join(' \u00b7 '))));
      if (keys.length) {
        const sec = mk('div', 'bsec'), chips = mk('ul', 'bchips');
        keys.forEach((k) => chips.append(mk('li', 'bchip', k)));
        sec.append(mk('h3', '', 'Key purposes'), chips); body.append(sec);
      }
      group(body, 'Alerts', alerts.map((a) => row(txt(a.level, 20), txt(a.kind, 60), txt(a.what, 200))));
    } };
  }
  function workflows(d) {
    const flows = arr(d).map(obj).filter(Boolean);
    return { sum: flows.length + ' flows', build(body) {
      flows.forEach((f) => group(body, txt(f.title, 80), arr(f.steps).map(obj).filter(Boolean).map((s, i) =>
        row(String(i + 1), txt(s.label, 160), txt(s.symbol, 200)))));
      if (!flows.length) none(body, 'No flows listed.');
    } };
  }
  function limitations(d) {
    const items = arr(d).map(obj).filter(Boolean);
    return { sum: items.length + ' listed, newest first', build(body) {
      group(body, 'What JARVIS cannot do yet', items.map((l) => row(txt(l.release, 8), txt(l.text, 200),
        [KIND[l.kind] || '', txt(l.source, 160)].filter(Boolean).join(' \u00b7 '))));
      if (!items.length) none(body, 'Nothing listed.');
    } };
  }
  function costs(d) {
    const items = arr(d.items).map(obj).filter(Boolean), rate = num(d.usd_inr), date = txt(d.rate_date, 10);
    return { sum: items.length + ' prices in rupees', build(body) {
      group(body, 'Each subscription, in rupees', items.map((c) => row(num(c.inr) !== null ? inr(c.inr) : '',
        txt(c.label, 80), ['per ' + txt(c.unit, 60), txt(c.free, 120) && 'free: ' + txt(c.free, 120)].filter(Boolean).join(' \u00b7 '))));
      if (rate) body.append(mk('p', 'bfine', 'At \u20b9' + rate + ' to the US dollar' + (date ? ', ' + date : '') + '.'));
    } };
  }
  function decisions(d) {
    const plans = arr(d).map(obj).filter(Boolean);
    return { sum: plans.length + ' plans', build(body) {
      plans.forEach((p) => {
        const sec = mk('div', 'bsec'), h = mk('h3', '', txt(p.title, 300)), ul = mk('ul', 'blines');
        if (txt(p.release, 8)) h.append(mk('span', 'bcount', txt(p.release, 8)));
        arr(p.decisions).forEach((x) => { const t = txt(x, 200); if (t) ul.append(mk('li', '', t)); });
        sec.append(h, ul); body.append(sec);
      });
      if (!plans.length) none(body, 'No decisions listed.');
    } };
  }
  const SECTIONS = [['architecture', 'Architecture', architecture], ['stack', 'Stack', stack], ['libraries', 'Libraries & licences', libraries],
    ['integrations', 'Integrations', integrations], ['workflows', 'Workflows', workflows], ['limitations', 'Limitations', limitations],
    ['costs', 'Costs', costs], ['decisions', 'Decisions', decisions]];

  /** The reader: one disclosure per section that came back well-formed. Returns how many. */
  function sections(host, raw) {
    const top = obj(raw), d = top && obj(top.sections) ? top.sections : top;
    host.textContent = '';
    if (!d) return 0;
    let n = 0;
    SECTIONS.forEach(([key, label, view]) => {
      const v = d[key];
      if (v === undefined || v === null) return;
      const s = view(Array.isArray(v) ? v : obj(v) || {});
      host.append(disclosure(label, s.sum, s.build, false)); n += 1;
    });
    return n;
  }

  // ---- Book settings (D16): creator name, show voice, questions, a training brain --------------
  const VOICES = [['cloud', 'JARVIS\u2019s cloud voice'], ['browser', 'This browser\u2019s voice']];
  function sw(key, label, hint, on, flip) {
    const opt = mk('div', 'bopt'), t = mk('div', 'btxt'), b = mk('button', 'bsw'), tr = mk('span', 'track');
    t.append(mk('span', 'bl', label), mk('small', '', hint));
    b.type = 'button'; b.dataset.key = key; b.setAttribute('aria-pressed', String(on)); b.setAttribute('aria-label', label);
    tr.append(mk('i')); b.append(tr, mk('span', 'st', on ? 'On' : 'Off'));
    b.addEventListener('click', () => flip(key, !on));
    opt.append(t, b); return opt;
  }
  function nameRow(value, save) {
    const opt = mk('div', 'bopt bk-name'), lab = mk('label', 'k', 'Creator name in the closing');
    lab.htmlFor = 'bkCreator';
    const inp = mk('input', 'dinput'); inp.id = 'bkCreator'; inp.maxLength = 40; inp.autocomplete = 'off'; inp.value = value;
    inp.placeholder = 'my owner and creator';
    const go = mk('button', 'btn lift', 'Save name'); go.type = 'button';
    go.addEventListener('click', () => save({ creator_name: inp.value.replace(/\s+/g, ' ').trim().slice(0, 40) }));
    const line = mk('div', 'bk-namerow'); line.append(inp, go);
    opt.append(lab, line); return opt;
  }
  function voiceRow(value, save) {
    const opt = mk('div', 'bopt'), t = mk('div', 'btxt'), sel = mk('select', 'bsel');
    sel.id = 'bkVoice';
    const lab = mk('label', 'bl', 'Show voice'); lab.htmlFor = 'bkVoice';
    t.append(lab, mk('small', '', 'The browser voice is free and works without the cloud.'));
    VOICES.forEach(([v, words]) => { const o = mk('option', '', words); o.value = v; o.selected = v === value; sel.append(o); });
    sel.addEventListener('change', () => save({ show_voice: sel.value }));
    opt.append(t, sel); return opt;
  }
  /** deps: {load() -> settings, save(patch) -> settings (throws plain words), ask(title, lines, buttons) -> id} */
  function settings(host, deps) {
    const wrap = mk('div', 'bk-set'), noteEl = mk('p', 'bnote bk-setnote');
    noteEl.setAttribute('role', 'status');
    let data = null;
    const say = (kind, words) => { noteEl.className = 'bnote bk-setnote' + (kind ? ' ' + kind : ''); noteEl.textContent = words; };
    const keyOf = (n) => (n && (n.dataset.key || n.id || n.textContent)) || '';
    const paint = (body) => {
      const a = document.activeElement, was = a && body.contains(a) ? keyOf(a) : ''; // a save repaints: keep the focus
      draw(body);
      const back = was && [...body.querySelectorAll('button, input, select')].find((n) => keyOf(n) === was);
      if (back) back.focus();
    };
    const draw = (body) => {
      body.textContent = '';
      if (!data) { body.append(mk('p', 'bempty', 'Reading the settings...')); return; }
      const save = async (patch) => {
        try { const d = obj(await deps.save(patch)); if (d) { data = d; paint(body); } say('ok', 'Saved.'); }
        catch (e) { say('bad', (e && e.message) || 'Couldn\u2019t save. Please try again.'); }
      };
      const flip = async (key, on) => {
        if (key === 'allow_training_brain' && on) {
          const yes = await deps.ask('Allow a brain that may learn?', ['The free brain may learn from what a guest asks about JARVIS.',
            'Nothing of yours is in a book session, but questions would leave your control.'],
          [{ id: '', label: 'Keep it off' }, { id: 'go', label: 'Allow it', kind: 'primary' }]);
          if (yes !== 'go') return;
        }
        await save({ [key]: on });
      };
      body.append(nameRow(txt(data.creator_name, 40), save), voiceRow(data.show_voice === 'browser' ? 'browser' : 'cloud', save),
        sw('talk_through', 'Questions after the show', 'JARVIS answers questions about how he is built.', data.talk_through !== false, flip),
        sw('allow_training_brain', 'Allow a brain that may learn', 'Off: questions use a brain that does not train on them.', data.allow_training_brain === true, flip));
    };
    const box = disclosure('Book settings', 'Creator name, voice, questions', (body) => {
      paint(body);
      deps.load().then((d) => { data = obj(d) || {}; paint(body); }, () => { body.textContent = ''; body.append(mk('p', 'bempty', 'Couldn\u2019t read the settings.')); });
    }, false);
    wrap.append(box, noteEl); host.append(wrap);
    return wrap;
  }

  window.JarvisBookReader = Object.freeze({ sections, settings });
})();
