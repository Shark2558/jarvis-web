// src/jarvis/api/static/console-voice-devices.js - R5 workstream B (docs/plans/r5-voice.md D13, D14).
// The audio route: which sound output and microphone JARVIS uses, and a quick switch by voice.
// No build step; CSP script-src 'self'.
//   window.JarvisAudioRoute (frozen)
//     supported() -> bool                  devices can be listed in this browser
//     refresh() -> Promise<{outputs, inputs}>   enumerateDevices (never getUserMedia: no names
//                                          appear until the owner has allowed the mic once)
//     current() -> {output, input}         the device in use, or null for the system default
//     chooseOutput(id|null) / chooseInput(id|null) -> Promise<{ok, reason?, warning?}>
//     outputKind() -> 'headphones' | 'speakers' | 'unknown'   (the barge-in Automatic policy reads it)
//     find(name, kind = 'output') -> device | null   fuzzy: nickname, device word, label
//     on(kind, fn) -> off()                kinds: 'devices', 'route'
//   window.JarvisAudioRoutePrefs (frozen): what the picker panel needs (marks, nicknames, policy).
// Registers device.switch, device.input and device.list with the voice-command router. Device
// labels and ids stay in this browser (localStorage + in-page events); nothing here talks to the server.
(() => {
  'use strict';
  const KEY = 'jarvis_audio_route_v1';
  const LIM = Object.freeze({ id: 400, label: 120, nick: 30, marks: 20, debounceMs: 500, match: 0.6, maxWords: 8 });
  const KINDS = Object.freeze(['headphones', 'speakers']);
  const POLICIES = Object.freeze(['ask', 'auto', 'never']);
  const VIRTUAL = Object.freeze(['default', 'communications']);
  const HEADPHONE_RE = /head(phone|set)|ear(phone|bud|pod)|buds|airpods|hands-?free/i;
  const SPEAKER_RE = /speaker|soundbar|built-?in|realtek|high definition/i;
  const BUILTIN_RE = /realtek|high definition|built-?in|internal|intel|microphone array|smart sound|conexant|laptop/i;
  const HANDSFREE_RE = /\s*hands-?free( ag audio)?/i;
  const FILLER = Object.freeze(['my', 'the', 'your', 'our', 'a']);
  const ALIASES = Object.freeze({
    laptop: (d) => d.builtIn, computer: (d) => d.builtIn, desktop: (d) => d.builtIn,
    'built in': (d) => d.builtIn, builtin: (d) => d.builtIn,
    earphones: (d) => d.kind === 'headphones', earphone: (d) => d.kind === 'headphones',
    headphones: (d) => d.kind === 'headphones', headphone: (d) => d.kind === 'headphones',
    earbuds: (d) => d.kind === 'headphones', buds: (d) => d.kind === 'headphones',
    headset: (d) => d.kind === 'headphones', airpods: (d) => d.kind === 'headphones',
    speaker: (d) => d.kind === 'speakers', speakers: (d) => d.kind === 'speakers',
    bluetooth: (d) => !d.builtIn,
  });
  const DEFAULT_WORDS = Object.freeze(['default', 'system default', 'the default', 'normal']);
  const emitDom = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };

  // ---- small helpers -------------------------------------------------------------------------------
  const hon = () => {
    const c = window.JarvisChat;
    try { return String((c && typeof c.honorific === 'function' && c.honorific()) || 'Sir'); } catch (_) { return 'Sir'; }
  };
  const speaker = () => (window.JarvisVoice && window.JarvisVoice.speaker) || null;
  const canRoute = () => { const s = speaker(); return !!(s && s.sinkSupported()); };
  const onAndroid = () => /Android/i.test(String(navigator.userAgent || ''));
  const norm = (s) => String(s == null ? '' : s).normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim();
  const tell = (text, spoken) => {
    const loop = window.JarvisVoiceLoop;
    if (loop) { try { loop.say(text, { speak: spoken === true }); } catch (_) {} }
  };

  // ---- saved choices (ids and labels, so a changed id can be matched again) ------------------------
  const blank = () => ({ v: 1, output: null, input: null, kinds: {}, names: {}, onConnect: 'ask' });
  const str = (v, max) => (typeof v === 'string' && v.length > 0 && v.length <= max ? v : null);
  function pickDevice(o) {
    const id = o && typeof o === 'object' ? str(o.id, LIM.id) : null;
    return id ? { id, label: typeof o.label === 'string' ? o.label.slice(0, LIM.label) : '' } : null;
  }
  function pickMap(src, ok) {
    const out = {};
    if (!src || typeof src !== 'object') return out;
    Object.keys(src).slice(0, LIM.marks).forEach((k) => { const v = ok(src[k]); if (v && str(k, LIM.id)) out[k] = v; });
    return out;
  }
  function sanitise(raw) {
    const p = blank();
    if (!raw || typeof raw !== 'object' || raw.v !== 1) return p;
    p.output = pickDevice(raw.output);
    p.input = pickDevice(raw.input);
    p.kinds = pickMap(raw.kinds, (v) => (KINDS.includes(v) ? v : null));
    p.names = pickMap(raw.names, (v) => (typeof v === 'string' && v.trim() && v.length <= LIM.nick ? v.trim() : null));
    if (POLICIES.includes(raw.onConnect)) p.onConnect = raw.onConnect;
    return p;
  }
  function load() {
    try { return sanitise(JSON.parse(localStorage.getItem(KEY) || 'null')); } catch (_) { return blank(); }
  }
  let P = load();
  function persist() { try { localStorage.setItem(KEY, JSON.stringify(P)); } catch (_) {} }

  // ---- the device list -----------------------------------------------------------------------------
  let rawList = [];
  let view = { outputs: [], inputs: [], defaults: { output: '', input: '' }, labelled: false };
  let seeded = false;
  let skipInput = null;
  const listeners = { devices: [], route: [] };
  const fire = (kind, detail) => listeners[kind].forEach((fn) => { try { fn(detail); } catch (_) {} });

  const tidyLabel = (s) => String(s || '').replace(/\s*\([0-9a-f]{4}:[0-9a-f]{4}\)/gi, '').trim().slice(0, LIM.label);
  const classify = (label) => (HEADPHONE_RE.test(label) ? 'headphones' : SPEAKER_RE.test(label) ? 'speakers' : 'unknown');
  function baseKey(label) {
    const m = String(label).match(/\(([^()]*(?:\([^()]*\))?[^()]*)\)\s*$/);
    return norm((m ? m[1] : label).replace(HANDSFREE_RE, ''));
  }
  function describe(d, n, group, kindWord) {
    const label = tidyLabel(d.label);
    const sibling = HANDSFREE_RE.test(label) && group.some((o) => o !== d && !HANDSFREE_RE.test(o.label) && baseKey(o.label) === baseKey(label));
    const shown = !label ? `${kindWord} ${n}` : sibling ? `${label} (call quality)` : label;
    return {
      id: d.deviceId, label: shown, kind: P.kinds[d.deviceId] || classify(label),
      builtIn: BUILTIN_RE.test(label), callQuality: sibling, name: P.names[d.deviceId] || shown,
    };
  }
  function build(kindName, kindWord) {
    const real = rawList.filter((d) => d.kind === kindName && !VIRTUAL.includes(d.deviceId));
    const items = real.map((d, i) => describe(d, i + 1, real, kindWord));
    return items.filter((d) => !d.callQuality).concat(items.filter((d) => d.callQuality));
  }
  function rebuild() {
    const dflt = (k) => { const d = rawList.find((x) => x.kind === k && x.deviceId === 'default'); return d ? tidyLabel(d.label).replace(/^default\s*-\s*/i, '') : ''; };
    view = {
      outputs: build('audiooutput', 'Sound output'), inputs: build('audioinput', 'Microphone'),
      defaults: { output: dflt('audiooutput'), input: dflt('audioinput') },
      labelled: rawList.some((d) => !!d.label),
    };
  }
  const copy = (list) => list.map((d) => Object.assign({}, d));
  const snapshot = () => ({ outputs: copy(view.outputs), inputs: copy(view.inputs) });
  const byId = (list, id) => list.find((d) => d.id === id) || null;
  function locate(saved, list) {
    if (!saved) return null;
    return byId(list, saved.id) || (saved.label ? list.find((d) => tidyLabel(d.label) === tidyLabel(saved.label)) || null : null);
  }
  function defaultKind() {
    const label = view.defaults.output;
    const own = view.outputs.find((d) => tidyLabel(d.label) === label);
    return own ? own.kind : classify(label);
  }

  // ---- current state -------------------------------------------------------------------------------
  function current() {
    const s = speaker(), A = window.JarvisAudio;
    const out = s && s.sink() ? byId(view.outputs, s.sink()) : null;
    const inp = A && A.inputId() ? byId(view.inputs, A.inputId()) : null;
    return { output: out ? Object.assign({}, out) : null, input: inp ? Object.assign({}, inp) : null };
  }
  function outputKind() {
    if (!canRoute()) return 'unknown';
    const out = current().output;
    return out ? out.kind : defaultKind();
  }

  // ---- fuzzy find ----------------------------------------------------------------------------------
  function bigrams(s) { const m = new Map(); for (let i = 0; i < s.length - 1; i++) { const g = s.slice(i, i + 2); m.set(g, (m.get(g) || 0) + 1); } return m; }
  function dice(a, b) {
    if (a.length < 2 || b.length < 2) return a === b && a ? 1 : 0;
    const x = bigrams(a), y = bigrams(b);
    let hits = 0;
    x.forEach((n, g) => { hits += Math.min(n, y.get(g) || 0); });
    return (2 * hits) / (a.length - 1 + b.length - 1);
  }
  const sameWord = (a, b) => a === b || (a.length >= 3 && b.length >= 3 && (a.startsWith(b) || b.startsWith(a)));
  function overlap(q, label) {
    const ql = q.split(' '), ll = label.split(' ');
    return ql.filter((t) => ll.some((l) => sameWord(t, l))).length / ql.length;
  }
  function cleanTarget(text) {
    let w = norm(text).split(' ').filter(Boolean);
    while (w.length && FILLER.includes(w[0])) w = w.slice(1);
    if (w[w.length - 1] === 'instead') w = w.slice(0, -1);
    return w.join(' ');
  }
  function score(d, q) {
    if (P.names[d.id] && norm(P.names[d.id]) === q) return 1;
    const alias = ALIASES[q];
    if (alias && alias(d)) return 1;
    const label = norm(tidyLabel(d.label).replace(/\(call quality\)/i, ''));
    return Math.max(dice(q.replace(/ /g, ''), label.replace(/ /g, '')), overlap(q, label));
  }
  function defaultDevice(kind) {
    const dk = kind === 'input' ? 'unknown' : defaultKind();
    return { id: 'default', label: 'the default', name: 'the default ' + (kind === 'input' ? 'microphone' : 'output'), kind: dk, builtIn: true, callQuality: false, isDefault: true };
  }
  function find(name, kind) {
    const q = cleanTarget(name);
    if (!q) return null;
    const which = kind === 'input' ? 'input' : 'output';
    if (DEFAULT_WORDS.includes(q)) return defaultDevice(which);
    const list = which === 'input' ? view.inputs : view.outputs;
    const ranked = list.map((d, i) => ({ d, i, s: score(d, q) })).filter((r) => r.s >= LIM.match);
    const external = (q === 'speaker' || q === 'speakers');
    ranked.sort((a, b) => b.s - a.s || (a.d.callQuality - b.d.callQuality) || (external ? (a.d.builtIn - b.d.builtIn) : 0) || a.i - b.i);
    return ranked.length ? Object.assign({}, ranked[0].d) : null;
  }
  const isWord = (text) => { const q = cleanTarget(text); return !!q && (q in ALIASES || DEFAULT_WORDS.includes(q)); };
  const resolves = (text, kind) => isWord(text) || !!find(text, kind);

  // ---- choosing ------------------------------------------------------------------------------------
  const isDefaultId = (id) => id === null || id === undefined || id === 'default';
  const savedAs = (d) => (d ? { id: d.id, label: tidyLabel(d.label).slice(0, LIM.label) } : null);
  function announceRoute(reason) {
    const detail = { output: current().output, input: current().input, reason };
    fire('route', detail);
    emitDom('jarvis:audio-route', detail);
  }
  async function chooseOutput(id) {
    const s = speaker();
    if (!s || !s.sinkSupported()) return { ok: false, reason: 'unsupported' };
    const dev = isDefaultId(id) ? null : (typeof id === 'string' ? byId(view.outputs, id) : null);
    if (!isDefaultId(id) && !dev) return { ok: false, reason: 'not_found' };
    const res = await s.setSink(dev ? dev.id : 'default');
    if (!res || !res.ok) return { ok: false, reason: (res && res.reason) || 'failed' };
    P = Object.assign({}, P, { output: savedAs(dev) });
    persist();
    announceRoute('output_changed');
    return { ok: true };
  }
  async function chooseInput(id) {
    const A = window.JarvisAudio;
    if (!A || typeof A.setInput !== 'function') return { ok: false, reason: 'unsupported' };
    const dev = isDefaultId(id) ? null : (typeof id === 'string' ? byId(view.inputs, id) : null);
    if (!isDefaultId(id) && !dev) return { ok: false, reason: 'not_found' };
    skipInput = null;
    A.setInput(dev ? dev.id : null);
    P = Object.assign({}, P, { input: savedAs(dev) });
    persist();
    announceRoute('input_changed');
    return dev && dev.kind === 'headphones' ? { ok: true, warning: 'call_quality' } : { ok: true };
  }

  // ---- refresh and reconcile -----------------------------------------------------------------------
  function applyInput() {
    const A = window.JarvisAudio;
    if (!A || typeof A.setInput !== 'function' || !P.input) return;
    const dev = locate(P.input, view.inputs);
    if (!dev) { skipInput = null; if (A.inputId()) A.setInput(null); return; }
    if (skipInput === dev.id) return;
    if (dev.id !== P.input.id) { P = Object.assign({}, P, { input: savedAs(dev) }); persist(); }
    A.setInput(dev.id);
  }
  async function restoreOutput() {
    const s = speaker();
    const dev = locate(P.output, view.outputs);
    if (!s || !s.sinkSupported() || !dev) return;
    const res = await s.setSink(dev.id);
    if (res && res.ok && dev.id !== P.output.id) { P = Object.assign({}, P, { output: savedAs(dev) }); persist(); }
  }
  async function fallBack(lost) {
    const s = speaker();
    if (!s) return;
    await s.setSink('default');
    const to = view.defaults.output || 'the default output';
    tell(`${lost.name} disconnected. I'll use ${to}, ${hon()}.`, true);
    announceRoute('output_lost');
  }
  async function use(dev) {
    const r = await chooseOutput(dev.id);
    tell(r.ok ? `Switching to ${dev.name}, ${hon()}.` : failLine(r.reason, dev.name), r.ok);
  }
  function announce(dev) {
    const loop = window.JarvisVoiceLoop, C = window.JarvisVoiceCommands;
    if (P.onConnect === 'never' || !loop) return;
    if (P.onConnect === 'auto') { use(dev); return; }
    const dismiss = loop.offer(`${dev.name} connected.`, [
      { label: `Use ${dev.name}`.slice(0, 40), run: () => { if (C) C.cancelAsk(); use(dev); } },
      { label: 'Not now', run: () => { if (C) C.cancelAsk(); } },
    ]);
    if (loop.inConversation() && loop.state() !== 'speaking') {
      loop.ask(`${dev.name} connected. Shall I use it, ${hon()}?`, {
        yes: () => { dismiss(); use(dev); }, no: () => dismiss(),
      });
    }
  }
  async function reconcile(before) {
    applyInput();
    if (!canRoute()) { seeded = true; return; }
    if (!seeded) { seeded = true; await restoreOutput(); return; }
    const s = speaker();
    const now = new Set(view.outputs.map((d) => d.id));
    const lost = before.find((d) => !now.has(d.id) && s.sink() === d.id);
    if (lost) await fallBack(lost);
    const gone = new Set(before.map((d) => d.id));
    const added = view.outputs.filter((d) => !gone.has(d.id) && !d.callQuality);
    if (added.length && view.labelled) announce(added[0]);
  }
  async function doRefresh() {
    const before = view.outputs;
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      rawList = all.filter((d) => d && typeof d.deviceId === 'string' && d.deviceId && (d.kind === 'audiooutput' || d.kind === 'audioinput'));
    } catch (_) { rawList = []; }
    rebuild();
    await reconcile(before);
    fire('devices', snapshot());
    emitDom('jarvis:audio-devices', snapshot());
    return snapshot();
  }
  let chain = Promise.resolve();
  const refresh = () => { chain = chain.then(doRefresh, doRefresh); return chain; };
  const supported = () => !!(navigator.mediaDevices && typeof navigator.mediaDevices.enumerateDevices === 'function');

  // ---- a chosen microphone that is gone ------------------------------------------------------------
  function onRoute(e) {
    const d = e && e.detail;
    if (!d || d.reason !== 'input_missing') return;     // our own route events carry an output key
    const A = window.JarvisAudio;
    if (A) A.setInput(null);
    skipInput = d.input && d.input.id ? d.input.id : (P.input && P.input.id);
    const name = (P.input && P.input.label) || 'That microphone';
    tell(`${name} isn't available, so I'm using the laptop mic, ${hon()}.`, false);
    announceRoute('input_changed');
  }

  // ---- voice commands (D12) ------------------------------------------------------------------------
  const failLine = (reason, name) => {
    const h = hon();
    if (reason === 'not_found') return `I can't find ${name} any more, ${h}.`;
    if (reason === 'blocked') return `The browser wouldn't let me switch to ${name}, ${h}.`;
    return `I couldn't switch to ${name}, ${h}.`;
  };
  const androidLine = () => `On this phone Android chooses where I sound, ${hon()}: open Quick Settings and pick it under media output (the name varies by phone).`;
  const browserVoiceLine = () => `My browser voice follows Windows' sound output, ${hon()}: press Windows + Ctrl + V to choose it.`;
  const unsupportedLine = () => (onAndroid() ? androidLine() : `This browser doesn't let me choose the sound output, ${hon()}. Use your system's sound settings.`);
  const done = (say) => {
    const loop = window.JarvisVoiceLoop;
    return { say, then: loop && loop.inConversation() ? 'listen' : 'idle' };
  };
  function slotMatcher(id, kind) {
    const forms = ((window.JarvisVoiceCommands && window.JarvisVoiceCommands.PHRASES[id]) || []).map((t) => t.split('{device}'));
    return (text) => {
      if (text.split(' ').length > LIM.maxWords) return null;
      for (const [pre, post] of forms) {
        if (!text.startsWith(pre) || !text.endsWith(post) || text.length <= pre.length + post.length) continue;
        const x = text.slice(pre.length, text.length - post.length).trim();
        if (kind === 'output' && /(^| )mic$/.test(x)) continue;
        if (x && resolves(x, kind)) return { x: cleanTarget(x) };
      }
      return null;
    };
  }
  async function runSwitch(args) {
    if (!canRoute()) return done(unsupportedLine());
    const dev = find(args.x);
    if (!dev) return done(`I can't see any ${args.x} connected, ${hon()}.`);
    const r = await chooseOutput(dev.id);
    if (!r.ok) return done(failLine(r.reason, dev.name));
    return done(speaker().usingBrowser() ? browserVoiceLine() : `Switching to ${dev.name}, ${hon()}.`);
  }
  async function runInput(args) {
    const dev = find(args.x, 'input');
    if (!dev) return done(`I can't see any ${args.x} microphone connected, ${hon()}.`);
    const r = await chooseInput(dev.id);
    if (!r.ok) return done(failLine(r.reason, dev.name));
    const warn = r.warning ? ' Sound drops to call quality while that mic is in use.' : '';
    return done(`I'll listen through ${dev.name}, ${hon()}.${warn}`);
  }
  function runList() {
    if (!canRoute() && onAndroid()) return done(androidLine());
    if (!view.labelled) return done(`I can't see device names yet, ${hon()}. Tap the mic once to allow it.`);
    const cur = current().output;
    const name = cur ? cur.name : (view.defaults.output || 'the default output');
    const others = view.outputs.filter((d) => !d.callQuality && (!cur || d.id !== cur.id)).map((d) => d.name);
    const also = others.length ? `; also connected: ${others.join(', ')}.` : '.';
    const mic = current().input;
    return done(`I'm speaking through ${name}${also}${mic ? ` Listening through ${mic.name}.` : ''}`);
  }
  function registerCommands() {
    const C = window.JarvisVoiceCommands;
    if (!C) return;
    const add = (id, spec) => { try { C.register(id, spec); } catch (_) {} };
    add('device.input', { match: slotMatcher('device.input', 'input'), run: runInput });
    add('device.switch', { match: slotMatcher('device.switch', 'output'), run: runSwitch });
    add('device.list', { match: C.exact('device.list'), run: runList });
  }

  // ---- panel helpers and boot ----------------------------------------------------------------------
  function setMark(map, id, value, valid) {
    if (typeof id !== 'string' || !id) return false;
    const next = Object.assign({}, P[map]);
    if (value && valid(value)) next[id] = value; else delete next[id];
    if (Object.keys(next).length > LIM.marks) return false;
    P = Object.assign({}, P, { [map]: next });
    persist(); rebuild(); fire('devices', snapshot());
    return true;
  }
  const prefsApi = Object.freeze({
    prefs: () => JSON.parse(JSON.stringify(P)),
    devices: () => Object.assign({ outputs: copy(view.outputs), inputs: copy(view.inputs) }, { defaults: Object.assign({}, view.defaults), labelled: view.labelled }),
    setKind: (id, kind) => setMark('kinds', id, kind, (k) => KINDS.includes(k)),
    setName: (id, name) => setMark('names', id, typeof name === 'string' ? name.trim().slice(0, LIM.nick) : '', () => true),
    setOnConnect(v) { if (!POLICIES.includes(v)) return false; P = Object.assign({}, P, { onConnect: v }); persist(); fire('devices', snapshot()); return true; },
    canRoute, onAndroid, defaultKind,
  });
  function on(kind, fn) {
    if (!listeners[kind] || typeof fn !== 'function') return () => {};
    listeners[kind].push(fn);
    return () => { const i = listeners[kind].indexOf(fn); if (i >= 0) listeners[kind].splice(i, 1); };
  }
  function boot() {
    registerCommands();
    document.addEventListener('jarvis:audio-route', onRoute);
    const A = window.JarvisAudio;
    if (A && P.input && typeof A.setInput === 'function') A.setInput(P.input.id);   // before the first open
    if (!supported()) return;
    let timer = 0;
    navigator.mediaDevices.addEventListener('devicechange', () => { clearTimeout(timer); timer = setTimeout(refresh, LIM.debounceMs); });
    refresh();
  }

  window.JarvisAudioRoute = Object.freeze({ supported, refresh, current, chooseOutput, chooseInput, outputKind, find, on });
  window.JarvisAudioRoutePrefs = prefsApi;
  boot();
})();
