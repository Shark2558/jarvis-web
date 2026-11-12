// src/jarvis/api/static/console-people.js -- R4 D10/D11/D7: the People panel and the brain-mode switch.
// People: a name (and an optional role / organisation) -> a short dossier from PUBLIC sources. Public
// figures and work due-diligence only: the server refuses anything else with a plain message, shown as is.
// Nothing is saved. Brain mode: AI / No-AI switch and a badge; in No-AI mode JARVIS answers from fixed
// rules and the dossier is links only.
// R11.1 D16 (the owner's observation O8: the old one-press button opened nothing): each profile is a card (the site, the
// page's title, the dossier's own line about that site) with its OWN real link, <a target="_blank"
// rel="noopener noreferrer">: one tab per click, never a pop-up a browser can block. "Open next" presses
// the next unopened card's link from the click itself and the card says "Opened". No button opens every
// profile at once, and this file never asks the browser for a new window itself (with noopener that call
// answers null by specification, so its result could never be counted). No page is framed: most of these
// sites refuse it.
// Server strings reach the page through textContent only. No build step; CSP script-src 'self'; ASCII source.
// Mounts into #p-people .pbody (shell in console.html, integrator). Optional #brainModeSlot gets the pill (console-deck.css styles it; console-people.css the panel).
// API: POST /v1/people/research {name, context?} -> {name, context, profiles:[{platform,url,title}],
//   findings:[{title,domain,snippet}], summary|null, spoken, ambiguous, no_ai, note}; GET /v1/people/last;
//   GET|POST /v1/settings/brain-mode {mode: 'ai'|'none'} -> {mode, meaning}.
// Events: 'jarvis:brainmode' (detail {mode}); window.JarvisBrainMode = {get, set} (set('ai') only asks).
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
  const SITES = { linkedin: 'LinkedIn', linkedin_company: 'LinkedIn company page', github: 'GitHub', youtube: 'YouTube',
    x: 'X', wikipedia: 'Wikipedia', instagram: 'Instagram', facebook: 'Facebook' };
  const siteName = (p) => (Object.prototype.hasOwnProperty.call(SITES, p.toLowerCase()) ? SITES[p.toLowerCase()] : p);
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const MODE_WORD = { ai: 'AI on', none: 'No-AI' };
  const MODE_MEANS = { ai: 'JARVIS reasons and writes with the model. Paid replies apply.', none: 'Fixed rules only, no model. Nothing paid is used.' };
  const S = { dossier: null, mode: null, meaning: '', busy: false, switching: false, failed: false, opened: new Set(), links: [] };
  let nameEl, ctxEl, goBtn, noteEl, card, openBtn, speakBtn, modeAi, modeNone, meaningEl, pill, pillLabel, menu, asking;   // S.mode is null until the server has answered

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
    const findings = arr(d.findings).slice(0, MAX_FINDINGS).map((f) => { const it = obj(f) || {}; return { domain: txt(it.domain, 80), snippet: txt(it.snippet, 400) }; });
    const profiles = arr(d.profiles).slice(0, MAX_PROFILES).map((p) => {
      const it = obj(p), url = it && safeUrl(it.url);
      if (!url) return null;
      // the dossier's own line about that site goes on its card (and is then not repeated below)
      const mine = findings.find((f) => !f.used && f.snippet && f.domain === new URL(url).hostname);
      if (mine) mine.used = true;
      return { platform: txt(it.platform, 20), url, title: txt(it.title, 120), line: mine ? mine.snippet : '' };
    }).filter(Boolean);
    return { name: txt(d.name, 80), profiles, summary: txt(d.summary, 900) || null, spoken: txt(d.spoken, 600),
      ambiguous: d.ambiguous === true, noAi: d.no_ai === true, note: txt(d.note, 200), findings: findings.filter((f) => !f.used) };
  }
  function show(dossier) { S.dossier = dossier; S.opened = new Set(); render(); }   // a new dossier: nothing opened yet

  // One profile: the site, the page's title, the dossier's line about it, and its own link.
  function profileCard(p) {
    const li = mk('li', 'trow pprof'), t = mk('div', 'ttxt'), site = siteName(p.platform);
    const state = mk('span', 'tmeta pstate'); state.hidden = true;
    t.append(mk('b', 'tname', site), mk('span', 'tmeta', p.title || p.url));
    if (p.line) t.append(mk('span', 'tmeta pline', p.line));
    t.append(state);
    const a = mk('a', 'btn bact lift plink', 'Open in browser');
    a.href = p.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    a.setAttribute('aria-label', 'Open in browser: ' + site + (p.title ? ', ' + p.title : ''));
    a.addEventListener('click', () => { S.opened.add(p.url); marks(); });   // the tab itself is the link's own doing
    li.append(t, a);
    S.links.push({ url: p.url, a, li, state });
    return li;
  }
  // Which cards have been opened, and what "Open next" can still do.
  function marks() {
    S.links.forEach((l) => {
      const done = S.opened.has(l.url);
      if (done) l.li.dataset.opened = 'true'; else delete l.li.dataset.opened;
      l.state.textContent = done ? 'Opened' : ''; l.state.hidden = !done;
    });
    const left = S.links.filter((l) => !S.opened.has(l.url)).length;
    openBtn.textContent = S.links.length && !left ? 'All opened' : 'Open next';
    openBtn.disabled = !left;
    if (S.links.length && S.opened.size) say('', left ? 'Opened ' + (S.links.length - left) + ' of ' + S.links.length + '.' : 'All ' + S.links.length + ' opened. A card\'s own link opens it again.');
  }
  function render() {
    const d = S.dossier;
    card.textContent = ''; card.className = 'pcard'; S.links = [];
    openBtn.hidden = speakBtn.hidden = !d || (!d.profiles.length && !d.spoken);
    marks();
    if (!d) return;
    card.className = 'integ pdoss'; card.dataset.state = d.profiles.length ? 'linked' : 'unlinked';
    const head = mk('div', 'ihead'); head.append(mk('b', 'pname', d.name), mk('span', 'istate', d.profiles.length ? d.profiles.length + ' profiles' : 'No profiles'));
    const body = mk('div', 'ibody'); card.append(head, body);
    if (d.summary) body.append(mk('p', 'psum', d.summary));
    else if (d.noAi) body.append(mk('p', 'fine', 'No summary: showing the public links found.'));
    if (d.note) body.append(mk('p', 'fine', d.note));
    if (d.profiles.length) {
      const ul = mk('ul', 'tlist plinks');
      d.profiles.forEach((p) => ul.append(profileCard(p)));
      body.append(ul);
    }
    d.findings.forEach((f) => body.append(mk('p', 'fine', (f.domain ? f.domain + ': ' : '') + f.snippet)));
    marks();
  }

  async function research() {
    if (S.busy || !hasApi()) return;
    const name = nameEl.value.trim(), context = ctxEl.value.trim();
    if (!name) { say('bad', 'Give me a name to research, Sir.'); return; }
    S.busy = true; goBtn.disabled = true; say('', 'Searching public sources...');
    let found = null, note = ['', ''];
    try {
      const body = context ? { name, context } : { name };
      found = normal(await api('/v1/people/research', { method: 'POST', body }));
      note = ['', found && found.ambiguous ? 'Several people share this name. Add a role or organisation.' : ''];
    } catch (e) { note = ['bad', detailOf(e)]; }
    S.busy = false; goBtn.disabled = false; show(found); say(note[0], note[1]);
  }

  // R11.1 D16: ONE tab per click. The next unopened card's own link is pressed from this click itself (no
  // await before it), so the browser opens it as it opens any link; the link's handler marks the card.
  function openNext() {
    const next = S.links.find((l) => !S.opened.has(l.url));
    if (next) next.a.click();
  }

  function speak() {
    const d = S.dossier, V = window.JarvisVoice, sp = V && V.speaker;
    if (!d || !d.spoken || !sp || typeof sp.say !== 'function') { say('bad', 'Voice is not available.'); return; }
    if (typeof sp.unlock === 'function') sp.unlock();
    sp.say(d.spoken); if (typeof sp.end === 'function') sp.end();
  }

  // ---- brain mode ---------------------------------------------------------------------------------
  // The pill never claims a mode the server has not told it: it starts as "Brain: ..." (unknown), shows
  // "Brain: unknown" (tap to retry) when the read fails, and changes only from a server answer. One switch
  // at a time (S.switching); a stale read never overwrites a newer answer (seq). AI back on always asks:
  // the pill menu, the People panel's AI button and JarvisBrainMode.set('ai') all end in the same confirm.
  let seq = 0, noteTimer = 0, pillNote, announce;
  const known = () => S.mode === 'ai' || S.mode === 'none';
  function showMode() {
    const none = S.mode === 'none', word = known() ? MODE_WORD[S.mode] : S.failed ? 'unknown' : '...';
    modeAi.setAttribute('aria-pressed', String(known() && !none)); modeNone.setAttribute('aria-pressed', String(none));
    modeAi.disabled = modeNone.disabled = S.switching;
    meaningEl.textContent = S.meaning || MODE_MEANS[S.mode] || '';
    pill.className = 'status brainmode' + (none || S.failed ? ' alert' : '');
    pill.setAttribute('aria-label', known() ? 'Brain: ' + word + '. Change brain mode'
      : S.failed ? 'Brain: unknown. Press to read it again' : 'Brain: reading the mode');
    pill.setAttribute('aria-busy', String(S.switching));
    pillLabel.replaceChildren(mk('span', 'bm-long', 'Brain: ' + word), mk('span', 'bm-short', known() ? word : S.failed ? '?' : '...'));
    opts().forEach((o) => { o.setAttribute('aria-checked', String(o.dataset.mode === S.mode)); o.setAttribute('aria-disabled', String(S.switching)); });
  }
  // A short note beside the pill (visible whichever panel is open), also read out by screen readers.
  function flash(text) {
    clearTimeout(noteTimer); pillNote.textContent = text || ''; pillNote.hidden = !text;
    if (text) noteTimer = setTimeout(() => flash(''), 8000);
  }
  function applyMode(raw) {
    const d = obj(raw);
    if (!d || (d.mode !== 'ai' && d.mode !== 'none')) return false;
    const changed = d.mode !== S.mode;
    S.mode = d.mode; S.failed = false; S.meaning = txt(d.meaning, 200); showMode();
    if (changed) document.dispatchEvent(new CustomEvent('jarvis:brainmode', { detail: { mode: S.mode } }));
    return true;
  }
  async function refresh() {
    if (!hasApi() || S.switching) return;
    const mine = ++seq;
    try { const d = await api('/v1/settings/brain-mode'); if (mine === seq && !S.switching) applyMode(d); }
    catch (e) {
      if (mine !== seq || S.switching || known()) return;     // a mode we already know stays until the server says otherwise
      S.failed = true; showMode(); flash('I could not read the brain mode. Press the pill to try again.');
    }
  }
  async function switchMode(mode) {
    if (!hasApi() || S.switching || mode === S.mode) return;
    S.switching = true; seq += 1; showMode();
    try {
      if (!applyMode(await api('/v1/settings/brain-mode', { method: 'POST', body: { mode } }))) throw new Error('');
      announce.textContent = 'Brain: ' + MODE_WORD[S.mode]; flash('');
    } catch (e) {
      const why = detailOf(e); flash('The brain mode did not change. ' + (why === 'That did not work, Sir.' ? '' : why)); say('bad', why);
      S.switching = false; await refresh();        // show what the server really has
    }
    S.switching = false; showMode();
  }
  const opts = () => (menu ? [...menu.querySelectorAll('.bmopt')] : []);
  function closeMenu(back) {
    box.hidden = true; asking.hidden = true; pill.setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', outside, true);
    if (back) pill.focus();
  }
  function outside(e) { if (!box.contains(e.target) && !pill.contains(e.target)) closeMenu(false); }
  function openMenu() {
    flash(''); box.hidden = false; asking.hidden = true; pill.setAttribute('aria-expanded', 'true');
    document.addEventListener('pointerdown', outside, true);
    const cur = opts().find((o) => o.dataset.mode === S.mode); (cur || opts()[0]).focus();
    refresh();                                       // another tab or device may have changed it
  }
  // AI back on spends money: ask once, with Cancel focused so a repeated Enter cannot confirm it.
  function askAi() { asking.hidden = false; asking.querySelector('.btn:not(.primary)').focus(); }
  function requestAi() {
    if (S.mode === 'ai' || S.switching) return;
    if (box.hidden) openMenu();
    askAi();
  }
  function choose(mode) {
    if (S.switching || mode === S.mode) { if (!S.switching) closeMenu(true); return; }
    if (mode === 'none') { closeMenu(true); switchMode('none'); return; }
    askAi();
  }
  function menuKeys(e) {
    const list = opts(), at = list.indexOf(document.activeElement);
    if (e.key === 'Tab') { closeMenu(false); return; }
    if (at < 0 || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    const n = e.key === 'Home' ? 0 : e.key === 'End' ? list.length - 1 : (at + (e.key === 'ArrowDown' ? 1 : list.length - 1)) % list.length;
    list[n].focus();
  }
  function boxKeys(e) {
    if (e.key === 'Escape') { e.preventDefault(); closeMenu(true); return; }
    if (e.key !== 'Tab' || !asking.contains(document.activeElement)) return;
    const [no, yes] = asking.querySelectorAll('.btn');      // Tab cycles Cancel / Switch on, then leaves
    if ((!e.shiftKey && document.activeElement === yes) || (e.shiftKey && document.activeElement === no)) closeMenu(false);
  }
  let box;
  function buildPill(slot) {
    slot.className = 'bmslot'; slot.textContent = '';
    pill = mk('button', 'status brainmode'); pill.type = 'button'; pill.id = 'brainModeBadge';
    pill.setAttribute('aria-haspopup', 'menu'); pill.setAttribute('aria-expanded', 'false'); pill.setAttribute('aria-controls', 'brainMenu');
    pillLabel = mk('span', 'bm-label'); pill.append(mk('i'), pillLabel);
    box = mk('div', 'card bmmenu'); box.id = 'brainMenu'; box.hidden = true;
    menu = mk('div', 'bmlist'); menu.setAttribute('role', 'menu'); menu.setAttribute('aria-label', 'Brain mode');   // menu items only
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
    asking.append(mk('p', '', 'Paid replies resume \u2014 switch AI on?'), act);
    box.append(menu, asking);
    pillNote = mk('div', 'bmnote'); pillNote.hidden = true; pillNote.setAttribute('role', 'status');
    announce = mk('span', 'sr-only'); announce.setAttribute('role', 'status'); announce.setAttribute('aria-live', 'polite');
    pill.addEventListener('click', () => { if (!known() && !S.switching) { flash(''); refresh(); return; } if (box.hidden) openMenu(); else closeMenu(true); });
    pill.addEventListener('keydown', (e) => { if (e.key === 'ArrowDown' && box.hidden && known()) { e.preventDefault(); openMenu(); } });
    menu.addEventListener('keydown', menuKeys); box.addEventListener('keydown', boxKeys);
    slot.append(pill, box, pillNote, announce);
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
    openBtn = mk('button', 'btn lift', 'Open next'); openBtn.type = 'button'; openBtn.id = 'peopleOpen'; openBtn.hidden = true;
    openBtn.addEventListener('click', openNext);
    speakBtn = mk('button', 'btn lift', 'Speak'); speakBtn.type = 'button'; speakBtn.id = 'peopleSpeak'; speakBtn.hidden = true;
    speakBtn.addEventListener('click', speak);
    const acts = mk('div', 'actions pacts2'); acts.append(openBtn, speakBtn);
    const modeRow = mk('div', 'bopt pmode'), mt = mk('div', 'btxt');
    meaningEl = mk('small'); meaningEl.id = 'modeMeaning'; mt.append(mk('span', 'bl', 'Brain mode'), meaningEl);
    const sw = mk('div', 'atabs'); sw.setAttribute('role', 'group'); sw.setAttribute('aria-label', 'Brain mode');
    modeAi = mk('button', 'btn bact atab', 'AI'); modeAi.type = 'button'; modeAi.id = 'modeAi';
    modeNone = mk('button', 'btn bact atab', 'No-AI'); modeNone.type = 'button'; modeNone.id = 'modeNone';
    modeAi.addEventListener('click', requestAi);     // AI back on asks first, here too
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
    await refresh();
    try { const l = obj(await api('/v1/people/last')); if (l && l.dossier) show(normal(l.dossier)); } catch (_) { /* nothing researched yet */ }
  }

  build();
  // set('none') switches at once (the safe direction); set('ai') only opens the same confirm as the pill.
  window.JarvisBrainMode = Object.freeze({ get: () => S.mode, set: (m) => (m === 'ai' ? requestAi() : m === 'none' ? switchMode('none') : undefined) });
  const JC = window.JarvisConsole;
  if (JC && typeof JC.ready === 'function' && JC.ready()) load();
  document.addEventListener('jarvis:ready', load);
})();
