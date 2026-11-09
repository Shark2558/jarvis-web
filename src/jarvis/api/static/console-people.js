// src/jarvis/api/static/console-people.js -- R4 D10/D11/D7: the People panel and the brain-mode switch.
// People: a name (and an optional role / organisation) -> a short dossier from PUBLIC sources -> "Open all
// profiles" opens each profile in its own browser tab (window.open per URL, from the click itself so the
// browser's pop-up rules allow it). Public figures and work due-diligence only: the server refuses anything
// else with a plain message, shown as is. Nothing is saved. Brain mode: AI / No-AI switch and a badge; in
// No-AI mode JARVIS answers from fixed rules and the dossier is links only.
// Server strings reach the page through textContent only. No build step; CSP script-src 'self'; ASCII source.
// Mounts into #p-people .pbody (shell in console.html, integrator). Optional #brainModeSlot gets the pill (console-deck.css styles it; console-people.css the panel).
// API: POST /v1/people/research {name, context?} -> {name, context, profiles:[{platform,url,title}],
//   findings:[{title,domain,snippet}], summary|null, spoken, ambiguous, no_ai, note}; GET /v1/people/last;
//   GET|POST /v1/settings/brain-mode {mode: 'ai'|'none'} -> {mode, meaning}.
// Events: 'jarvis:brainmode' (detail {mode}); window.JarvisBrainMode = {get, set}.
(() => {
  'use strict';
  const panel = document.getElementById('p-people');
  const host = panel && panel.querySelector('.pbody');
  if (!host) return;
  // Mirrors the server's exact-host rule (people/sources.py): a look-alike or a stray subdomain never opens.
  const HOST_OK = [
    /^(?:[a-z0-9-]+\.)*linkedin\.com$/, /^(?:www\.)?github\.com$/, /^(?:[a-z0-9-]+\.)*youtube\.com$/,
    /^(?:www\.|mobile\.)?(?:x|twitter)\.com$/, /^[a-z0-9-]+\.wikipedia\.org$/,
    /^(?:[a-z0-9-]+\.)*instagram\.com$/, /^(?:[a-z0-9-]+\.)*facebook\.com$/];
  const hostOk = (h) => HOST_OK.some((re) => re.test(h));
  const MAX_PROFILES = 8, MAX_FINDINGS = 4;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const MODE_WORD = { ai: 'AI on', none: 'No-AI' };
  const MODE_MEANS = { ai: 'JARVIS reasons and writes with the model. Paid replies apply.', none: 'Fixed rules only, no model. Nothing paid is used.' };
  const S = { dossier: null, mode: 'ai', meaning: '', busy: false };
  let nameEl, ctxEl, goBtn, noteEl, card, openBtn, speakBtn, modeAi, modeNone, meaningEl, pill, pillLabel, menu, asking;

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
      return u.protocol === 'https:' && !u.username && !u.password && hostOk(u.hostname) ? u.href : null;
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
    card.textContent = ''; card.className = 'pcard';
    openBtn.hidden = speakBtn.hidden = !d || (!d.profiles.length && !d.spoken);
    openBtn.disabled = !d || !d.profiles.length;
    if (!d) return;
    card.className = 'integ pdoss'; card.dataset.state = d.profiles.length ? 'linked' : 'unlinked';
    const head = mk('div', 'ihead'); head.append(mk('b', 'pname', d.name), mk('span', 'istate', d.profiles.length ? d.profiles.length + ' profiles' : 'No profiles'));
    const body = mk('div', 'ibody'); card.append(head, body);
    if (d.summary) body.append(mk('p', 'psum', d.summary));
    else if (d.noAi) body.append(mk('p', 'fine', 'No summary: showing the public links found.'));
    if (d.note) body.append(mk('p', 'fine', d.note));
    if (d.profiles.length) {
      const ul = mk('ul', 'tlist plinks');
      d.profiles.forEach((p) => {
        const li = mk('li', 'trow'), t = mk('div', 'ttxt'), a = mk('a', 'tname plink', p.platform);
        a.href = p.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        t.append(a, mk('span', 'tmeta', p.title || p.url)); li.append(t); ul.append(li);
      });
      body.append(ul);
    }
    d.findings.forEach((f) => body.append(mk('p', 'fine', (f.domain ? f.domain + ': ' : '') + f.snippet)));
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
    const none = S.mode === 'none', word = MODE_WORD[S.mode] || S.mode;
    modeAi.setAttribute('aria-pressed', String(!none)); modeNone.setAttribute('aria-pressed', String(none));
    meaningEl.textContent = S.meaning || MODE_MEANS[S.mode] || '';
    pill.className = 'status brainmode' + (none ? ' alert' : '');
    pill.setAttribute('aria-label', 'Brain: ' + word + '. Change brain mode');
    pillLabel.replaceChildren(mk('span', 'bm-long', 'Brain: ' + word), mk('span', 'bm-short', word));
    menu.querySelectorAll('.bmopt').forEach((o) => o.setAttribute('aria-checked', String(o.dataset.mode === S.mode)));
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
  const opts = () => [...menu.querySelectorAll('.bmopt')];
  function closeMenu(back) {
    menu.hidden = true; asking.hidden = true; pill.setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', outside, true);
    if (back) pill.focus();
  }
  function outside(e) { if (!menu.contains(e.target) && !pill.contains(e.target)) closeMenu(false); }
  function openMenu() {
    menu.hidden = false; asking.hidden = true; pill.setAttribute('aria-expanded', 'true');
    document.addEventListener('pointerdown', outside, true);
    const cur = opts().find((o) => o.dataset.mode === S.mode); (cur || opts()[0]).focus();
  }
  function choose(mode) {
    if (mode === S.mode) { closeMenu(true); return; }
    if (mode === 'none') { closeMenu(true); switchMode('none'); return; }
    asking.hidden = false; asking.querySelector('.btn.primary').focus();     // AI back on spends money: ask once
  }
  function menuKeys(e) {
    const list = opts(), at = list.indexOf(document.activeElement);
    if (e.key === 'Escape') { e.preventDefault(); closeMenu(true); return; }
    if (e.key === 'Tab') { closeMenu(false); return; }
    if (at < 0 || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    const n = e.key === 'Home' ? 0 : e.key === 'End' ? list.length - 1 : (at + (e.key === 'ArrowDown' ? 1 : list.length - 1)) % list.length;
    list[n].focus();
  }
  function buildPill(slot) {
    slot.className = 'bmslot'; slot.textContent = '';
    pill = mk('button', 'status brainmode'); pill.type = 'button'; pill.id = 'brainModeBadge';
    pill.setAttribute('aria-haspopup', 'menu'); pill.setAttribute('aria-expanded', 'false'); pill.setAttribute('aria-controls', 'brainMenu');
    pillLabel = mk('span', 'bm-label'); pill.append(mk('i'), pillLabel);
    menu = mk('div', 'card bmmenu'); menu.id = 'brainMenu'; menu.setAttribute('role', 'menu'); menu.setAttribute('aria-label', 'Brain mode'); menu.hidden = true;
    ['ai', 'none'].forEach((m) => {
      const o = mk('button', 'bmopt'); o.type = 'button'; o.dataset.mode = m; o.setAttribute('role', 'menuitemradio');
      o.append(mk('b', '', m === 'ai' ? 'AI on' : 'No-AI'), mk('small', '', MODE_MEANS[m]));
      o.addEventListener('click', () => choose(m)); menu.append(o);
    });
    asking = mk('div', 'bmask'); asking.hidden = true; asking.setAttribute('role', 'group'); asking.setAttribute('aria-label', 'Confirm AI on');
    const yes = mk('button', 'btn primary lift', 'Switch on'), no = mk('button', 'btn lift', 'Cancel');
    yes.type = no.type = 'button';
    yes.addEventListener('click', () => { closeMenu(true); switchMode('ai'); });
    no.addEventListener('click', () => { asking.hidden = true; opts()[0].focus(); });
    const act = mk('div', 'actions'); act.append(no, yes);
    asking.append(mk('p', '', 'Paid replies resume \u2014 switch AI on?'), act); menu.append(asking);
    pill.addEventListener('click', () => (menu.hidden ? openMenu() : closeMenu(true)));
    pill.addEventListener('keydown', (e) => { if (e.key === 'ArrowDown' && menu.hidden) { e.preventDefault(); openMenu(); } });
    menu.addEventListener('keydown', menuKeys);
    slot.append(pill, menu);
  }

  function field(id, label, input) {
    const w = mk('div', 'pfield'), l = mk('label', 'k', label); l.htmlFor = id; input.id = id; w.append(l, input); return w;
  }
  function build() {
    const root = mk('div', 'people'); root.id = 'people';
    noteEl = mk('div', 'bnote pnote'); noteEl.id = 'peopleNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite');
    const intro = mk('p', 'bfine pintro', 'Public figures and work contacts, from public sources only. I never gather a private person\'s home, movements or accounts, and never identify anyone from a face.');
    nameEl = mk('input', 'minput'); nameEl.maxLength = 80; nameEl.placeholder = 'e.g. Satya Nadella';
    ctxEl = mk('input', 'minput'); ctxEl.maxLength = 200; ctxEl.placeholder = 'e.g. Microsoft';
    goBtn = mk('button', 'btn primary lift bact', 'Research'); goBtn.type = 'button'; goBtn.id = 'peopleGo';
    goBtn.addEventListener('click', research);
    [nameEl, ctxEl].forEach((n) => n.addEventListener('keydown', (e) => { if (e.key === 'Enter') research(); }));
    const form = mk('div', 'pform'); form.append(field('peopleName', 'Name', nameEl), field('peopleContext', 'Role or organisation (optional)', ctxEl));
    const go = mk('div', 'actions'); go.append(goBtn);
    card = mk('div', 'pcard'); card.id = 'peopleCard';
    openBtn = mk('button', 'btn lift', 'Open all profiles'); openBtn.type = 'button'; openBtn.id = 'peopleOpen'; openBtn.hidden = true;
    openBtn.addEventListener('click', openAll);
    speakBtn = mk('button', 'btn lift', 'Speak'); speakBtn.type = 'button'; speakBtn.id = 'peopleSpeak'; speakBtn.hidden = true;
    speakBtn.addEventListener('click', speak);
    const acts = mk('div', 'actions pacts2'); acts.append(openBtn, speakBtn);
    const modeRow = mk('div', 'bopt pmode'), mt = mk('div', 'btxt');
    meaningEl = mk('small'); meaningEl.id = 'modeMeaning'; mt.append(mk('span', 'bl', 'Brain mode'), meaningEl);
    const sw = mk('div', 'atabs'); sw.setAttribute('role', 'group'); sw.setAttribute('aria-label', 'Brain mode');
    modeAi = mk('button', 'btn bact atab', 'AI'); modeAi.type = 'button'; modeAi.id = 'modeAi';
    modeNone = mk('button', 'btn bact atab', 'No-AI'); modeNone.type = 'button'; modeNone.id = 'modeNone';
    modeAi.addEventListener('click', () => switchMode('ai'));
    modeNone.addEventListener('click', () => switchMode('none'));
    sw.append(modeAi, modeNone); modeRow.append(mt, sw);
    const slot = document.getElementById('brainModeSlot');
    buildPill(slot || mk('span'));
    root.append(noteEl, intro, form, go, card, acts, modeRow);
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
