// docs/plans/r8-mockups/tools/deck.js -- the mockups' stand-in for the Command Deck around the new screens: top bar,
// 24-hour ruler, rails, the 2D Core, floating panels, the dock (laptop) or tab bar (phone). It only draws markup with the
// console's own classes (the kit CSS above styles it), with fixed example numbers: nothing here is product code.
// Query: ?s=night|day (surface), ?st=<state>, ?v=laptop|phone. Sets <html data-ready="1"> when drawn (tools/shoot.py).
(function () {
  'use strict';
  const q = new URLSearchParams(location.search);
  const P = Object.freeze({ s: q.get('s') === 'day' ? 'day' : 'night', st: q.get('st') || '', v: q.get('v') === 'phone' ? 'phone' : 'laptop' });
  const root = document.documentElement;
  root.dataset.surface = P.s;
  root.dataset.theme = 'workshop';
  root.dataset.motion = 'off'; // still pictures: the console's own Motion Off level
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const S = (inner, w) => `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="${w || 1.6}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;

  // icons: the dock's own (console.html) and a few the panels use
  const DOCK = [
    ['chat', 'Chat', '<path d="M3.5 5.5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H9l-3.5 3v-3h0a2 2 0 0 1-2-2z"/><path d="M7 8.5h6"/>'],
    ['brief', 'Brief', '<path d="M2.5 14.5h15M5.5 17.2h9"/><path d="M6 14.5a4 4 0 0 1 8 0"/><path d="M10 2.8v4.4M7.9 4.9 10 2.8l2.1 2.1"/><path d="m3.6 11.2 1.6.9M16.4 11.2l-1.6.9"/>'],
    ['approvals', 'Approvals', '<path d="M10 2.5 4 5v4.6c0 3.6 2.5 6.6 6 7.9 3.5-1.3 6-4.3 6-7.9V5z"/><path d="m7.3 10 1.9 1.9 3.6-3.8"/>'],
    ['activity', 'Activity', '<path d="m4 6 3.5 4L4 14M9.5 14.5H16"/>'],
    ['history', 'History', '<path d="M3.6 10a6.4 6.4 0 1 0 1.9-4.5L3.5 7.5"/><path d="M3.5 3.8v3.7h3.7M10 6.5V10l2.5 1.6"/>'],
    ['memory', 'Memory', '<path d="M5 3.5h9a1.5 1.5 0 0 1 1.5 1.5v11.5H6.5A1.5 1.5 0 0 1 5 15z"/><path d="M5 15a1.5 1.5 0 0 1 1.5-1.5h9"/><path d="M8.5 3.5v5l1.75-1.3L12 8.5v-5"/>'],
    ['integrations', 'Integrations', '<path d="M8.2 11.8 11.8 8.2"/><path d="M7 13 5.6 14.4a2.7 2.7 0 0 1-3.8-3.8L5 7.4a2.7 2.7 0 0 1 3.8 0"/><path d="M13 7l1.4-1.4a2.7 2.7 0 0 1 3.8 3.8L15 12.6a2.7 2.7 0 0 1-3.8 0"/>', 'wide'],
    ['|'],
    ['vault', 'Vault', '<rect x="4" y="9" width="12" height="8.5" rx="1.6"/><path d="M6.8 9V6.6a3.2 3.2 0 0 1 6.4 0V9M10 12.4v2"/>'],
    ['things', 'Things', '<circle cx="7" cy="12.5" r="3.2"/><path d="m9.3 10.2 6.4-6.4M13.6 6.2l2 2M11.8 8l1.6 1.6"/>'],
    ['notes', 'Notes', '<path d="M5 2.5h7.5L16 6v11.5H5z"/><path d="M12.5 2.5V6H16M7.5 10h6M7.5 13h4"/>'],
    ['privacy', 'Privacy', '<path d="M2.5 10s2.8-5 7.5-5 7.5 5 7.5 5-2.8 5-7.5 5-7.5-5-7.5-5z"/><circle cx="10" cy="10" r="2.2"/>'],
    ['home', 'Home', '<path d="M3 9.2 10 3.5l7 5.7"/><path d="M5 8v8.5h10V8"/><path d="M8.5 16.5v-4h3v4"/>'],
    ['faces', 'Faces', '<circle cx="10" cy="8" r="3.2"/><path d="M4 17c.8-3 3.2-4.6 6-4.6s5.2 1.6 6 4.6"/><path d="M2.5 6V3.5H5M15 3.5h2.5V6M2.5 14v2.5M17.5 14v2.5"/>'],
    ['vitals', 'Vitals', '<path d="M2.5 10.5h3.2l1.8-4.5 3 9 2.2-6 1.3 1.5h3.5"/>'],
    ['connectors', 'Connectors', '<circle cx="5" cy="10" r="2.2"/><circle cx="15" cy="5" r="2.2"/><circle cx="15" cy="15" r="2.2"/><path d="m7 9 6-3M7 11l6 3"/>'],
    ['people', 'People', '<circle cx="8.5" cy="8.5" r="4.5"/><path d="m12 12 4.5 4.5"/>'],
    ['book', 'Book', '<path d="M10 5.2C8.4 4 6.2 3.5 3.5 3.8v11.4c2.7-.3 4.9.2 6.5 1.4 1.6-1.2 3.8-1.7 6.5-1.4V3.8c-2.7-.3-4.9.2-6.5 1.4z"/><path d="M10 5.2v11.4"/>'],
    ['voice', 'Voice', '<path d="M10 2.6a2.6 2.6 0 0 0-2.6 2.6v4.6a2.6 2.6 0 0 0 5.2 0V5.2A2.6 2.6 0 0 0 10 2.6z"/><path d="M5 9.6a5 5 0 0 0 10 0M10 14.6v2.8M7.2 17.4h5.6"/>'],
    ['media', 'Media', '<rect x="2.5" y="4.5" width="15" height="11" rx="2.5"/><path d="m8.5 7.6 4 2.4-4 2.4z"/>'],
    ['construct', 'Construct', '<path d="m10 2.5 6.5 3.8v7.4L10 17.5l-6.5-3.8V6.3z"/><path d="m3.5 6.3 6.5 3.8 6.5-3.8M10 10.1v7.4"/>'],
    ['helpers', 'Helpers', '<rect x="4.5" y="3.5" width="11" height="14" rx="1.6"/><path d="M7.5 3.5V2.6h5v.9M7.4 9.2l1.7 1.7 3.5-3.5M7.5 14h5"/>'],
    ['camera', 'Camera', '<path d="M3.5 7.2A1.7 1.7 0 0 1 5.2 5.5h1.9l1.3-1.8h3.2l1.3 1.8h1.9a1.7 1.7 0 0 1 1.7 1.7v7.1a1.7 1.7 0 0 1-1.7 1.7H5.2a1.7 1.7 0 0 1-1.7-1.7z"/><circle cx="10" cy="10.6" r="2.8"/>'],
  ];
  const ICON = {
    more: '<rect x="3.5" y="3.5" width="5" height="5" rx="1"/><rect x="11.5" y="3.5" width="5" height="5" rx="1"/><rect x="3.5" y="11.5" width="5" height="5" rx="1"/><rect x="11.5" y="11.5" width="5" height="5" rx="1"/>',
    grip: '<path d="M10 2.5v15M2.5 10h15M10 2.5 8 4.5M10 2.5l2 2M10 17.5l-2-2M10 17.5l2-2M2.5 10l2-2M2.5 10l2 2M17.5 10l-2-2M17.5 10l-2 2"/>',
    close: '<path d="m5.5 5.5 9 9M14.5 5.5l-9 9"/>',
    edit: '<path d="M11.5 4.5h-6a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-6"/><path d="m9 11 .4-2.1 6-6a1.2 1.2 0 0 1 1.7 1.7l-6 6z"/>',
    eye: '<path d="M2.5 10s2.8-5 7.5-5 7.5 5 7.5 5-2.8 5-7.5 5-7.5-5-7.5-5z"/><circle cx="10" cy="10" r="2.2"/>',
    check: '<path d="m4.5 10.5 3.5 3.5 7.5-8"/>',
    warn: '<path d="M10 3 2.5 16.5h15z"/><path d="M10 8v4M10 14.2v.1"/>',
    no: '<circle cx="10" cy="10" r="7"/><path d="m7.2 7.2 5.6 5.6M12.8 7.2l-5.6 5.6"/>',
    wait: '<circle cx="10" cy="10" r="7"/><path d="M10 6.2V10l2.5 1.6"/>',
    diamond: '<path d="M10 5.5 14.5 10 10 14.5 5.5 10z" fill="currentColor"/>',
    back: '<path d="m12.5 4-6 6 6 6"/>',
    stop: '<rect x="5" y="5" width="10" height="10" rx="1.5"/>',
    pause: '<path d="M7 4.5v11M13 4.5v11"/>',
    play: '<path d="m6.5 4.5 9 5.5-9 5.5z"/>',
    plus: '<path d="M10 4.5v11M4.5 10h11"/>',
    minus: '<path d="M4.5 10h11"/>',
    chev: '<path d="m6 8 4 4 4-4"/>',
    gear: '<circle cx="10" cy="10" r="2.4"/><path d="M10 2.8v2M10 15.2v2M2.8 10h2M15.2 10h2M4.9 4.9l1.4 1.4M13.7 13.7l1.4 1.4M4.9 15.1l1.4-1.4M13.7 6.3l1.4-1.4"/>',
    mic: '<path d="M10 2.6a2.6 2.6 0 0 0-2.6 2.6v4.6a2.6 2.6 0 0 0 5.2 0V5.2A2.6 2.6 0 0 0 10 2.6z"/><path d="M5 9.6a5 5 0 0 0 10 0M10 14.6v2.8M7.2 17.4h5.6"/>',
    clip: '<path d="m14.5 9.2-5.3 5.3a3.2 3.2 0 0 1-4.5-4.5l5.6-5.6a2.1 2.1 0 0 1 3 3l-5.4 5.4a1 1 0 0 1-1.5-1.5l4.9-4.9"/>',
    folder: '<path d="M3 6.2a1.5 1.5 0 0 1 1.5-1.5h3.2l1.6 1.8h6.2A1.5 1.5 0 0 1 17 8v6.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 14.5z"/>',
    up: '<path d="M10 16V4.5M5 9.5l5-5 5 5"/>',
    palette: '<path d="M10 2.8a7.2 7.2 0 1 0 0 14.4c1 0 1.6-.7 1.6-1.5 0-.5-.2-.8-.5-1.2-.3-.3-.4-.7-.4-1.1 0-.9.7-1.6 1.6-1.6h1.9a3.6 3.6 0 0 0 3.6-3.6C17.8 5.6 14.3 2.8 10 2.8z"/><circle cx="6.3" cy="9.6" r=".9" fill="currentColor" stroke="none"/><circle cx="8.6" cy="6.3" r=".9" fill="currentColor" stroke="none"/><circle cx="12.4" cy="6.3" r=".9" fill="currentColor" stroke="none"/>',
  };
  DOCK.forEach((d) => { if (d[2]) ICON[d[0]] = d[2]; });
  const icon = (name, w) => S(ICON[name] || '', w);

  // ---- the 2D Core: console-fx.js coreSVG(), the same arithmetic ------------------------------------------------
  const f2 = (n) => Math.round(n * 100) / 100;
  let seq = 0;
  function tick(deg, r0, r1, cls, w) {
    const a = (deg - 90) * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    return `<line class="${cls}" x1="${f2(60 + r0 * c)}" y1="${f2(60 + r0 * s)}" x2="${f2(60 + r1 * c)}" y2="${f2(60 + r1 * s)}" stroke-width="${w}"/>`;
  }
  function diamond(deg, r, size) {
    const a = (deg - 90) * Math.PI / 180, x = f2(60 + r * Math.cos(a)), y = f2(60 + r * Math.sin(a));
    return `<rect class="mark" x="${f2(x - size / 2)}" y="${f2(y - size / 2)}" width="${size}" height="${size}" transform="rotate(${deg + 45} ${x} ${y})"/>`;
  }
  function coreSVG(size) {
    const lg = size === 'lg' || size === 'xl', k = size === 'xl' ? 0.55 : lg ? 1 : 2.3;
    const n = lg ? 72 : 24, every = lg ? 6 : 3, gid = 'r8g' + (++seq);
    let outer = `<circle class="faint" cx="60" cy="60" r="57.5" stroke-width="${0.8 * k}"/>`;
    for (let i = 0; i < n; i++) { const major = i % every === 0; outer += tick(i * 360 / n, major ? 48.5 : 52.5, 56, major ? 'tick major' : 'tick', (major ? 1.7 : 0.9) * k); }
    const c2 = 2 * Math.PI * 43, c3 = 2 * Math.PI * 31;
    const mid = `<circle class="arc" cx="60" cy="60" r="43" stroke-width="${3 * k}" stroke-dasharray="${f2(c2 * 70 / 360)} ${f2(c2 * 50 / 360)}"/>` +
      (lg ? diamond(95, 36.5, 4) + diamond(215, 36.5, 4) + diamond(335, 36.5, 4) : '');
    const inner = (lg ? '<circle class="faint" cx="60" cy="60" r="31" stroke-width="1" stroke-dasharray="1 3"/>' : '') +
      `<circle class="arc2" cx="60" cy="60" r="31" stroke-width="${2.2 * k}" stroke-dasharray="${f2(c3 * 40 / 360)} ${f2(c3 * 140 / 360)}"/>`;
    return `<svg viewBox="0 0 120 120" focusable="false"><defs><radialGradient id="${gid}"><stop offset="0" stop-color="#fff"/><stop class="s1" offset=".5" stop-opacity=".55"/><stop class="s2" offset="1" stop-opacity="0"/></radialGradient></defs>` +
      `<g class="r1">${outer}</g><g class="r2">${mid}</g><g class="r3">${inner}</g>` +
      `<g class="glow"><circle cx="60" cy="60" r="22" fill="url(#${gid})"/><circle class="nucleus" cx="60" cy="60" r="${lg ? 8 : 11}" stroke-width="${1.5 * k}"/><circle cx="60" cy="60" r="${lg ? 3.2 : 4.5}" fill="var(--accent)"/></g></svg>`;
  }

  // ---- pieces ------------------------------------------------------------------------------------------------------
  const CLOCK = '16:40', DATE = 'Sat Nov 28 2026';
  const promise = (more) => `<p class="r8-promise">${icon('eye')}<span><b>Only you are tracked.</b> Nothing is recorded; only counts and times are kept.${more ? ' ' + more : ''}</span></p>`;
  function panel(p) {
    const style = P.v === 'laptop' && !p.full ? ` style="left:${p.x}px;top:${p.y}px;width:${p.w}px;${p.h ? 'height:' + p.h + 'px' : ''}"` : '';
    const acts = p.full ? '' : `<div class="pacts">${p.edit ? `<button class="pbtn" type="button" aria-label="New conversation">${icon('edit')}</button>` : ''}<button class="pbtn grip" type="button" aria-label="Move ${esc(p.title)} panel with arrow keys">${icon('grip')}</button><button class="pbtn" type="button" aria-label="Close ${esc(p.title)} panel">${icon('close', 1.8)}</button></div>`;
    const head = p.head || `<svg class="pico" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[p.icon] || ''}</svg><h2 id="t-${p.id}">${esc(p.title)}</h2><span class="pmeta${p.metaCls ? ' ' + p.metaCls : ''}">${esc(p.meta || '')}</span>${acts}`;
    return `<section class="panel card${p.front ? ' front' : ''}${p.full ? ' r8-full' : ''}${p.cls ? ' ' + p.cls : ''}" id="p-${p.id}" aria-labelledby="t-${p.id}"${style}><header class="ptitle">${head}</header><div class="pbody${p.flush ? ' flush' : ''}">${p.body}</div></section>`;
  }
  const chat = () => panel({ id: 'chat', title: 'Conversation', icon: 'chat', edit: true, x: 1238, y: 92, w: 437, h: 680, flush: true,
    body: '<div class="r8-empty"></div><div class="composer-wrap"><div class="composer"><button class="icon-btn" type="button" aria-label="Attach">' + icon('clip') + '</button>' +
      '<button class="icon-btn" type="button" aria-label="Files">' + icon('folder') + '</button><textarea rows="1" aria-label="Message JARVIS" placeholder="Message JARVIS"></textarea>' +
      '<button class="icon-btn" type="button" aria-label="Talk">' + icon('mic') + '</button><button class="send" type="button" aria-label="Send" disabled>' + icon('up', 1.8) + '</button></div>' +
      '<p class="hint">Enter to send, Shift + Enter for a new line. Anything that sends, pays or can’t be undone waits for your approval.</p></div>' });
  function topbar(phone) {
    return `<header class="topbar" role="banner"><div class="brand"><span class="core" aria-hidden="true">${coreSVG('sm')}</span><b class="wordmark">JARVIS</b>` +
      `<span class="status"><i aria-hidden="true"></i><span>Online</span></span>` +
      `<span class="bmslot"><button class="status brainmode" type="button"><i aria-hidden="true"></i><span class="bm-long">Brain: AI on</span><span class="bm-short">AI on</span></button></span></div>` +
      (phone ? '' : `<div class="timebox" aria-hidden="true"><time class="clock">${CLOCK}</time><span class="date">${DATE}</span></div>`) +
      `<div class="tools"><label class="picker"><span class="sr-only">AI brain</span><select aria-label="AI brain"><option>Auto</option></select>` +
      `<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4.5 6 8l3.5-3.5"/></svg></label>` +
      `<button class="icon-btn" type="button" aria-label="Appearance">${icon('palette')}</button></div></header>`;
  }
  function ruler() {
    let h = '';
    for (let i = 0; i <= 24; i += 3) h += `<span class="hr" style="left:${(i / 24 * 100).toFixed(3)}%">${String(i).padStart(2, '0')}</span>`;
    const now = (16 + 40 / 60) / 24 * 100;
    return `<div class="ruler" aria-hidden="true">${h}<span class="ev" style="left:${(9.5 / 24 * 100).toFixed(2)}%"></span><span class="ev" style="left:${(14 / 24 * 100).toFixed(2)}%"></span>` +
      `<span class="now flip" style="left:${now.toFixed(3)}%"><b>${CLOCK}</b></span></div>`;
  }
  function rails() {
    const radar = '<div class="r8-radar" aria-hidden="true"><svg viewBox="0 0 100 100"><circle class="g" cx="50" cy="50" r="46"/><circle class="g" cx="50" cy="50" r="31"/><circle class="g" cx="50" cy="50" r="16"/>' +
      '<path class="g" d="M50 2v96M2 50h96"/><text x="27" y="30">TOOL</text><text x="63" y="30">MSG</text><text x="20" y="76">APPROVAL</text><text x="63" y="76">REPLY</text><circle cx="50" cy="50" r="1.6" fill="currentColor"/><circle cx="74" cy="83" r="2.2" fill="currentColor"/></svg></div>';
    const globe = '<div class="globe2d" aria-hidden="true"><svg viewBox="0 0 100 100"><circle class="g" cx="50" cy="50" r="40"/><ellipse class="g" cx="50" cy="50" rx="14" ry="40"/><ellipse class="g" cx="50" cy="50" rx="28" ry="40"/><ellipse class="g" cx="50" cy="50" rx="40" ry="12"/><ellipse class="g" cx="50" cy="50" rx="40" ry="26"/><ellipse class="o" cx="50" cy="50" rx="48" ry="16"/></svg></div>';
    const spark = '<svg class="spark" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true"><line class="base" x1="0" y1="29.5" x2="100" y2="29.5"/><polygon class="area" points="0,30 0,18 14,20 28,12 42,16 56,9 70,14 84,11 100,15 100,30"/><polyline points="0,18 14,20 28,12 42,16 56,9 70,14 84,11 100,15"/></svg>';
    return `<aside class="rail rail-l" aria-label="Link and activity"><div class="rgroup"><div class="ri"><span class="k">Link</span><span class="v ok"><i class="blink" aria-hidden="true"></i>Online</span></div>` +
      `<div class="ri"><span class="k">Reply latency</span><span class="v">1.4<span class="u">s</span></span><span class="bar" aria-hidden="true"><i style="width:46%"></i></span></div><div class="ri"><span class="k">Audit chain</span><span class="v ok">Verified</span></div></div>` +
      `<div><div class="rhead"><span class="k">Activity radar</span><span class="k live">Live</span></div><div class="instrument">${radar}</div>` +
      `<div class="pair"><div class="ri"><span class="k nw">Events 5m</span><span class="v">3</span></div><div class="ri"><span class="k nw">Last</span><span class="v">16:39</span></div></div></div>` +
      `<div class="rgroup"><div class="ri"><span class="k nw">Latency · last 20</span>${spark}</div><div class="ri"><span class="k nw">Turns</span><span class="v">6</span></div><span class="foot">Private by default</span></div></aside>` +
      `<aside class="rail rail-r" aria-label="Brain, approvals and time"><div class="rgroup"><div class="ri"><span class="k">Brain</span><span class="v acc">Auto</span></div><div class="ri"><span class="k">Last reply by</span><span class="v">Gemini</span></div>` +
      `<div class="ri"><span class="k">Approvals</span><span class="v">0 waiting</span></div><div class="ri"><span class="k">Google</span><span class="v up">Linked</span></div></div>` +
      `<div><div class="rhead"><span class="k">Time zone</span><span class="k live">Asia</span></div><div class="instrument">${globe}</div>` +
      `<div class="pair"><div class="ri"><span class="k nw">Zone</span><span class="v">Calcutta</span></div><div class="ri"><span class="k nw">Offset</span><span class="v">UTC+05:30</span></div></div></div>` +
      `<div class="rgroup"><div class="ri"><span class="k">Session uptime</span><span class="v">02:14:09</span></div><div class="ri"><span class="k">Connection</span><span class="v ok">Online</span></div><span class="foot">${DATE}</span></div></aside>`;
  }
  function stage(log) {
    return `<div class="stage"><div class="core-wrap" aria-hidden="true"><div class="core-top"><div class="logline"><span class="k">Log</span><time>${CLOCK}:02</time><span>${esc(log || 'Console online')}</span></div></div>` +
      `<div class="core-fallback"><span class="core xl" aria-hidden="true">${coreSVG('xl')}</span></div><div class="core-label"><b>JARVIS</b><i class="line"></i><span>Standing by</span></div>` +
      `<div class="core-read l"><span class="k">Last reply</span><span class="v">1.4 s</span></div><div class="core-read r"><span class="k">Turns</span><span class="v">6</span></div>` +
      `<div class="core-bottom"><div class="ri"><span class="k">Waiting</span><span class="v">0</span></div><div class="ri"><span class="k">Avg reply</span><span class="v">1.6 s</span></div><div class="ri"><span class="k">Audit</span><span class="v">OK</span></div></div></div></div>`;
  }
  function dock(pressed, phone) {
    const list = phone ? DOCK.filter((d) => ['chat', 'brief', 'approvals', 'activity', 'history', 'memory'].includes(d[0])) : DOCK;
    const more = phone ? `<button class="dk more${pressed.some((p) => !list.find((d) => d[0] === p)) ? ' on' : ''}" type="button" aria-label="More panels">${icon('more')}<span>More</span></button>` : '';
    return `<nav class="dock card" aria-label="Panels">` + list.map((d) => d[0] === '|' ? '<span class="sep" aria-hidden="true"></span>'
      : `<button class="dk${d[3] ? ' ' + d[3] : ''}" type="button" aria-pressed="${pressed.includes(d[0])}">${icon(d[0])}${d[0] === 'integrations' ? '<span class="full">Integrations</span><span class="short" aria-hidden="true">Links</span>' : `<span>${d[1]}</span>`}</button>`).join('') + more + '</nav>';
  }
  const camChip = (text) => text ? `<button class="status alert cam-chip" type="button" aria-label="${esc(text)}. Stop the camera"><i aria-hidden="true"></i>${esc(text)} · Stop</button>` : '';

  /** The laptop deck (1920 x 1080): opts.panels [{id,title,icon,meta,metaCls,x,y,w,h,body,front}], opts.chip, opts.log. */
  function laptop(opts) {
    const ids = opts.panels.map((p) => p.id);
    document.body.innerHTML = '<div class="aurora a1" aria-hidden="true"></div><div class="aurora a2" aria-hidden="true"></div><div class="r8-field" aria-hidden="true"></div>' +
      `<div class="deck">${topbar(false)}${ruler()}${rails()}${stage(opts.log)}</div>` + (opts.noChat ? '' : chat()) + opts.panels.map(panel).join('') +
      dock(['chat', ...ids], false) + camChip(opts.chip);
    layoutCore();
    ready();
  }
  /** console-deck.js layoutCore(): the Core centres itself in the widest free span beside the Conversation panel. */
  function layoutCore() {
    const stageEl = document.querySelector('.stage'), wrap = document.querySelector('.core-wrap'), chatEl = document.getElementById('p-chat');
    if (!stageEl || !wrap) return;
    const sr = stageEl.getBoundingClientRect();
    let cx = sr.left + sr.width / 2, span = sr.width;
    if (chatEl) {
      const r = chatEl.getBoundingClientRect();
      if (r.left < sr.right && r.right > sr.left) {
        const l = Math.max(0, r.left - sr.left), rr = Math.max(0, sr.right - r.right);
        if (l >= rr) { cx = sr.left + l / 2; span = l; } else { cx = r.right + rr / 2; span = rr; }
      }
    }
    const reads = document.querySelector('.core-read');
    const foot = wrap.offsetWidth + (reads && reads.offsetWidth ? 2 * (reads.offsetWidth + 12) : 0);
    const scale = Math.min(1, Math.max(0.42, (span - 24) / foot));
    wrap.style.transform = `translateX(${Math.round(cx - (sr.left + sr.width / 2))}px) scale(${scale.toFixed(3)})`;
  }
  /** The phone (390 x 844): one panel between the top bar and the tab bar, or opts.full for a whole-screen view. */
  function phone(opts) {
    document.body.innerHTML = '<div class="aurora a1" aria-hidden="true"></div><div class="aurora a2" aria-hidden="true"></div><div class="r8-field" aria-hidden="true"></div>' +
      (opts.full ? panel(Object.assign({ full: true }, opts.panel)) : `<div class="deck">${topbar(true)}</div>${panel(opts.panel)}${dock([opts.panel.id], true)}${camChip(opts.chip)}`);
    ready();
  }
  function ready() { requestAnimationFrame(() => requestAnimationFrame(() => { root.dataset.ready = '1'; })); }

  // ---- the Camera panel's frame (console-camera-panel.js): intro line, the tab strip, one pane -----------------------
  const CAM_TABS = [['look', 'Look'], ['desk', 'Desk'], ['workout', 'Workout'], ['results', 'Results'], ['cameras', 'Cameras'], ['wardrobe', 'Wardrobe']];
  function camFrame(sel, pane) {
    const tabs = CAM_TABS.map(([id, t]) => `<button class="hp-tab" type="button" role="tab" id="camt-${id}" aria-selected="${id === sel}" aria-controls="camp-${id}" tabindex="${id === sel ? 0 : -1}">${t}</button>`).join('');
    return '<p class="sfine">JARVIS looks on this device. A picture leaves it only when you press a button that says so.</p>' +
      `<div class="hp-tabs" role="tablist" aria-label="Camera">${tabs}</div><div class="hp-pane" role="tabpanel" id="camp-${sel}" aria-labelledby="camt-${sel}" tabindex="0">${pane}</div>`;
  }
  const chip = (st, word) => `<span class="vt-chip"${st ? ` data-status="${st}"` : ''}>${esc(word)}</span>`;
  const btn = (label, cls, extra) => `<button class="btn lift sact${cls ? ' ' + cls : ''}" type="button"${extra || ''}>${label}</button>`;
  const sw = (on, label) => `<button class="bsw" type="button" aria-pressed="${on}" aria-label="${esc(label)}"><span class="track" aria-hidden="true"><i></i></span><span class="st">${on ? 'On' : 'Off'}</span></button>`;
  const mark = (kind) => icon({ ok: 'check', warn: 'warn', no: 'no', wait: 'wait', need: 'diamond' }[kind], 1.8);

  /** Scroll a panel body so the element with this id sits near its top (a state whose point is lower down). */
  function scrollTo(id, pad) {
    const el = document.getElementById(id), body = el && el.closest('.pbody');
    if (!body) return;
    body.scrollTop += el.getBoundingClientRect().top - body.getBoundingClientRect().top - (pad == null ? 8 : pad);
  }

  window.R8 = Object.freeze({ P, esc, icon, promise, laptop, phone, coreSVG, camFrame, chip, btn, sw, mark, scrollTo });
}());
