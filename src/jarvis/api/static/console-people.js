// src/jarvis/api/static/console-people.js -- R4 D10/D11/D7: the People panel and the brain-mode switch.
// People: a name (and an optional role / organisation) -> a short dossier from PUBLIC sources -> "Open all
// profiles" opens each profile in its own browser tab (window.open per URL, from the click itself so the
// browser's pop-up rules allow it). Public figures and work due-diligence only: the server refuses anything
// else with a plain message, shown as is. Nothing is saved. Brain mode: AI / No-AI switch and a badge; in
// No-AI mode JARVIS answers from fixed rules and the dossier is links only.
// Server strings reach the page through textContent only. No build step; CSP script-src 'self'; ASCII source.
// Mounts into #p-people .pbody (shell in console.html, integrator). Optional #brainModeSlot gets the badge.
// API: POST /v1/people/research {name, context?} -> {name, context, profiles:[{platform,url,title}],
//   findings:[{title,domain,snippet}], summary|null, spoken, ambiguous, no_ai, note}; GET /v1/people/last;
//   GET|POST /v1/settings/brain-mode {mode: 'ai'|'none'} -> {mode, meaning}.
// Events: 'jarvis:brainmode' (detail {mode}); window.JarvisBrainMode = {get, set}.
(() => {
  'use strict';
  const panel = document.getElementById('p-people');
  const host = panel && panel.querySelector('.pbody');
  if (!host) return;
  const HOSTS = /^(?:[a-z0-9-]+\.)*(?:linkedin\.com|github\.com|youtube\.com|x\.com|twitter\.com|wikipedia\.org|instagram\.com|facebook\.com)$/;
  const MAX_PROFILES = 8, MAX_FINDINGS = 4;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const MODE_TEXT = { ai: 'AI on', none: 'No-AI' };
  const S = { dossier: null, mode: 'ai', meaning: '', busy: false };
  let nameEl, ctxEl, goBtn, noteEl, card, openBtn, speakBtn, modeAi, modeNone, meaningEl, badge;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = 300) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
    return m && m.length <= 300 && !/^[a-z0-9_.-]+$/i.test(m) ? m : 'That did not work, Sir.';
  }
  function say(kind, text) { noteEl.className = 'bnote pnote' + (kind === 'bad' ? ' bad' : ''); noteEl.textContent = text || ''; }

  // A profile link is opened only if it is https on a known profile host (the server checks too).
  function safeUrl(raw) {
    try {
      const u = new URL(String(raw));
      return u.protocol === 'https:' && !u.username && !u.password && HOSTS.test(u.hostname) ? u.href : null;
    } catch (_) { return null; }
  }
  function normal(raw) {
    const d = obj(raw);
    if (!d) return null;
    const profiles = arr(d.profiles).slice(0, MAX_PROFILES).map((p) => {
      const it = obj(p), url = it && safeUrl(it.url);
      return url ? { platform: txt(it.platform, 20), url, title: txt(it.title, 120) } : null;
    }).filter(Boolean);
    return { name: txt(d.name, 80), profiles, summary: txt(d.summary, 900) || null, spoken: txt(d.spoken, 600),
      ambiguous: d.ambiguous === true, noAi: d.no_ai === true, note: txt(d.note, 200),
      findings: arr(d.findings).slice(0, MAX_FINDINGS).map((f) => { const it = obj(f) || {}; return { domain: txt(it.domain, 80), snippet: txt(it.snippet, 400) }; }) };
  }

  function render() {
    const d = S.dossier;
    card.textContent = '';
    openBtn.hidden = speakBtn.hidden = !d || (!d.profiles.length && !d.spoken);
    openBtn.disabled = !d || !d.profiles.length;
    if (!d) return;
    card.append(mk('h3', 'ptitle', d.name));
    if (d.summary) card.append(mk('p', 'pbody', d.summary));
    else if (d.noAi) card.append(mk('p', 'bfine', 'No summary: showing the public links found.'));
    if (d.note) card.append(mk('p', 'bfine', d.note));
    const ul = mk('ul', 'tlist');
    d.profiles.forEach((p) => {
      const li = mk('li', 'titem');
      li.append(mk('span', 'tname', p.platform), mk('span', 'bfine', ' ' + (p.title || p.url)));
      ul.append(li);
    });
    card.append(ul);
    d.findings.forEach((f) => card.append(mk('p', 'bfine', (f.domain ? f.domain + ': ' : '') + f.snippet)));
  }

  async function research() {
    if (S.busy || !hasApi()) return;
    const name = nameEl.value.trim(), context = ctxEl.value.trim();
    if (!name) { say('bad', 'Give me a name to research, Sir.'); return; }
    S.busy = true; goBtn.disabled = true; say('', 'Searching public sources...');
    try {
      const body = context ? { name, context } : { name };
      S.dossier = normal(await api('/v1/people/research', { method: 'POST', body }));
      say('', S.dossier && S.dossier.ambiguous ? 'Several people share this name. Add a role or organisation.' : '');
    } catch (e) { S.dossier = null; say('bad', detailOf(e)); }
    S.busy = false; goBtn.disabled = false; render();
  }

  // D11: one tab per profile. Called straight from the click, with no await before window.open.
  function openAll() {
    const d = S.dossier;
    if (!d) return;
    let opened = 0;
    d.profiles.forEach((p) => { if (window.open(p.url, '_blank', 'noopener,noreferrer')) opened += 1; });
    say(opened < d.profiles.length ? 'bad' : '', opened < d.profiles.length
      ? 'Your browser blocked some tabs. Allow pop-ups for JARVIS and try again.' : 'Opened ' + opened + ' profile(s).');
  }

  function speak() {
    const d = S.dossier, V = window.JarvisVoice, sp = V && V.speaker;
    if (!d || !d.spoken || !sp || typeof sp.say !== 'function') { say('bad', 'Voice is not available.'); return; }
    if (typeof sp.unlock === 'function') sp.unlock();
    sp.say(d.spoken); if (typeof sp.end === 'function') sp.end();
  }

  // ---- brain mode ---------------------------------------------------------------------------------
  function showMode() {
    modeAi.setAttribute('aria-pressed', String(S.mode === 'ai'));
    modeNone.setAttribute('aria-pressed', String(S.mode === 'none'));
    meaningEl.textContent = S.meaning;
    badge.textContent = 'Brain: ' + (MODE_TEXT[S.mode] || S.mode);
    badge.className = 'bnote brainmode' + (S.mode === 'none' ? ' bad' : '');
  }
  function setMode(raw) {
    const d = obj(raw);
    if (!d || (d.mode !== 'ai' && d.mode !== 'none')) return;
    S.mode = d.mode; S.meaning = txt(d.meaning, 200); showMode();
    document.dispatchEvent(new CustomEvent('jarvis:brainmode', { detail: { mode: S.mode } }));
  }
  async function switchMode(mode) {
    if (!hasApi() || mode === S.mode) return;
    try { setMode(await api('/v1/settings/brain-mode', { method: 'POST', body: { mode } })); }
    catch (e) { say('bad', detailOf(e)); }
  }

  function build() {
    const root = mk('div', 'people'); root.id = 'people';
    noteEl = mk('div', 'bnote pnote'); noteEl.id = 'peopleNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite');
    const intro = mk('p', 'bfine', 'Public figures and work contacts, from public sources only. I never gather a private person\'s home, movements or accounts, and never identify anyone from a face.');
    nameEl = mk('input', 'tinput'); nameEl.id = 'peopleName'; nameEl.maxLength = 80; nameEl.placeholder = 'Name'; nameEl.setAttribute('aria-label', 'Name');
    ctxEl = mk('input', 'tinput'); ctxEl.id = 'peopleContext'; ctxEl.maxLength = 200; ctxEl.placeholder = 'Role or organisation (optional)'; ctxEl.setAttribute('aria-label', 'Role or organisation');
    goBtn = mk('button', 'btn lift bact', 'Research'); goBtn.type = 'button'; goBtn.id = 'peopleGo';
    goBtn.addEventListener('click', research);
    [nameEl, ctxEl].forEach((n) => n.addEventListener('keydown', (e) => { if (e.key === 'Enter') research(); }));
    card = mk('div', 'pcard'); card.id = 'peopleCard';
    openBtn = mk('button', 'btn lift', 'Open all profiles'); openBtn.type = 'button'; openBtn.id = 'peopleOpen'; openBtn.hidden = true;
    openBtn.addEventListener('click', openAll);
    speakBtn = mk('button', 'btn', 'Speak'); speakBtn.type = 'button'; speakBtn.id = 'peopleSpeak'; speakBtn.hidden = true;
    speakBtn.addEventListener('click', speak);
    const modeRow = mk('div', 'brow'); modeRow.setAttribute('role', 'group'); modeRow.setAttribute('aria-label', 'Brain mode');
    modeAi = mk('button', 'btn', 'AI'); modeAi.type = 'button'; modeAi.id = 'modeAi';
    modeNone = mk('button', 'btn', 'No-AI'); modeNone.type = 'button'; modeNone.id = 'modeNone';
    modeAi.addEventListener('click', () => switchMode('ai'));
    modeNone.addEventListener('click', () => switchMode('none'));
    modeRow.append(modeAi, modeNone);
    meaningEl = mk('p', 'bfine'); meaningEl.id = 'modeMeaning';
    badge = mk('span', 'bnote brainmode'); badge.id = 'brainModeBadge';
    const slot = document.getElementById('brainModeSlot');
    (slot || root).append(badge);
    root.append(noteEl, intro, nameEl, ctxEl, goBtn, card, openBtn, speakBtn, modeRow, meaningEl);
    host.appendChild(root);
    render(); showMode();
  }

  async function load() {
    if (!hasApi()) return;
    try { setMode(await api('/v1/settings/brain-mode')); } catch (e) { say('bad', detailOf(e)); }
    try { const l = obj(await api('/v1/people/last')); if (l && l.dossier) { S.dossier = normal(l.dossier); render(); } } catch (_) { /* nothing researched yet */ }
  }

  build();
  window.JarvisBrainMode = Object.freeze({ get: () => S.mode, set: switchMode });
  const JC = window.JarvisConsole;
  if (JC && typeof JC.ready === 'function' && JC.ready()) load();
  document.addEventListener('jarvis:ready', load);
})();
