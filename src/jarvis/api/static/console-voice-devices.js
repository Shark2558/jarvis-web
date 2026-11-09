// src/jarvis/api/static/console-voice-devices.js - R5 workstream B (docs/plans/r5-voice.md D13, D14).
// The audio route: which sound output and microphone JARVIS uses, and a quick switch by voice.
// Needs console-voice-devices-match.js (JarvisAudioMatch) loaded first. No build step; CSP script-src 'self'.
//   window.JarvisAudioRoute (frozen)
//     supported() -> bool                  devices can be listed in this browser
//     refresh() -> Promise<{outputs, inputs}>   enumerateDevices (never getUserMedia: no names
//                                          appear until the owner has allowed the mic once). Never rejects.
//     current() -> {output, input}         the device chosen, or null for the system default
//     chooseOutput(id|null) / chooseInput(id|null) -> Promise<{ok, reason?, warning?, pending?}>  (saved)
//     outputKind() -> 'headphones' | 'speakers' | 'unknown'   (the barge-in Automatic policy reads it)
//     find(name, kind = 'output') -> device | null   fuzzy: nickname, device word, label
//     on(kind, fn) -> off()                kinds: 'devices', 'route'
//   window.JarvisAudioRoutePrefs (frozen): what the picker panel needs (marks, nicknames, policy, status, text).
// Privacy (D18): device labels and nicknames stay in this browser. They are shown on screen and kept in
// localStorage, but NEVER put in spoken text (spoken text goes to the cloud voice): a spoken line says
// "your earphones", not the name. Voice-made choices last for this page only; panel choices are saved.
(() => {
  'use strict';
  const M = window.JarvisAudioMatch;
  if (!M) return;
  const KEY = 'jarvis_audio_route_v1';
  const LIM = Object.freeze({ id: 400, label: 120, nick: 30, marks: 20, debounceMs: 500, addSettleMs: 1500, enumMs: 3000, maxWords: 8, status: 300, showAgainMs: 80 });
  const KINDS = Object.freeze(['headphones', 'speakers']);
  const POLICIES = Object.freeze(['ask', 'auto', 'never']);
  const VIRTUAL = Object.freeze(['default', 'communications']);
  const VIRTUAL_DEVICE_RE = /steam|virtual|voicemeeter|vb-audio|cable|oculus|nvidia|hdmi|display|obs|streaming|remote|rdp|nahimic|sonar|s\/?pdif/i;
  const ASKABLE = Object.freeze(['listening', 'standby']);
  const COUNT_WORDS = Object.freeze(['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']);
  const emitDom = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };

  // ---- small helpers -------------------------------------------------------------------------------
  const hon = () => {
    const c = window.JarvisChat;
    try { return String((c && typeof c.honorific === 'function' && c.honorific()) || 'Sir'); } catch (_) { return 'Sir'; }
  };
  const speaker = () => (window.JarvisVoice && window.JarvisVoice.speaker) || null;
  const canRoute = () => { const s = speaker(); return !!(s && s.sinkSupported()); };
  const onAndroid = () => /Android/i.test(String(navigator.userAgent || ''));
  const visible = () => document.visibilityState === 'visible';
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const TEXT = Object.freeze({
    android: () => `On this phone Android chooses where I sound, ${hon()}: open Quick Settings and pick it under media output (the name varies by phone).`,
    browserVoice: () => `My browser voice follows Windows' sound output, ${hon()}: press Windows + Ctrl + V to choose it.`,
    unsupported: () => (onAndroid() ? TEXT.android() : `This browser doesn't let me choose the sound output, ${hon()}. Use your system's sound settings.`),
    noNames: 'Device names appear after you allow the microphone once (tap the mic).',
  });

  // ---- saving what the owner chose -----------------------------------------------------------------
  // v2: kinds / names hold {value, label} under the device id, so a device whose id changed is found by label.
  const blank = () => ({ v: 2, output: null, input: null, kinds: Object.create(null), names: Object.create(null), onConnect: 'ask' });
  const str = (v, max) => (typeof v === 'string' && v.length > 0 && v.length <= max ? v : null);
  function pickDevice(o) {
    const id = o && typeof o === 'object' ? str(o.id, LIM.id) : null;
    return id ? { id, label: typeof o.label === 'string' ? M.tidy(o.label) : '' } : null;
  }
  function pickMarks(src, valueOf) {
    const out = Object.create(null);
    if (!src || typeof src !== 'object') return out;
    Object.keys(src).slice(0, LIM.marks).forEach((k) => {
      const e = src[k];
      const value = valueOf(e && typeof e === 'object' ? e.value : e);   // v1 stored the bare value
      if (value && str(k, LIM.id)) out[k] = { value, label: e && typeof e === 'object' && typeof e.label === 'string' ? M.tidy(e.label) : '' };
    });
    return out;
  }
  const kindOf = (v) => (KINDS.includes(v) ? v : null);
  const nameOf = (v) => (typeof v === 'string' && v.length <= LIM.nick && M.nick(v) ? M.nick(v) : null);
  function sanitise(raw) {
    const p = blank();
    if (!raw || typeof raw !== 'object' || (raw.v !== 1 && raw.v !== 2)) return p;
    p.output = pickDevice(raw.output);
    p.input = pickDevice(raw.input);
    p.kinds = pickMarks(raw.kinds, kindOf);
    p.names = pickMarks(raw.names, nameOf);
    if (POLICIES.includes(raw.onConnect)) p.onConnect = raw.onConnect;
    return p;
  }
  function load() {
    try { return sanitise(JSON.parse(localStorage.getItem(KEY) || 'null')); } catch (_) { return null; }
  }
  let P = load() || blank();
  /** Change and save: always on top of what is stored now, so another tab's change is not lost. */
  function commit(change) {
    P = sanitise(change(load() || P));
    try { localStorage.setItem(KEY, JSON.stringify(P)); } catch (_) {}
  }
  const withMap = (cur, map, fn) => { const next = Object.assign(Object.create(null), cur[map]); fn(next); return Object.assign({}, cur, { [map]: next }); };

  // ---- the device list -----------------------------------------------------------------------------
  let rawList = [];
  let live = new Set();
  let view = { outputs: [], inputs: [], defaults: { output: '', input: '' }, labelled: false };
  let seeded = false;
  let statusText = '';
  let pendingInput = false;
  let session = { input: undefined };      // a voice-made input choice, for this page only
  const listeners = { devices: [], route: [] };
  const fire = (kind, detail) => listeners[kind].forEach((fn) => { try { fn(detail); } catch (_) {} });

  /** The stored key of a mark: the device id, or (when that id is gone) a device with the same label. */
  function keyFor(map, id, label) {
    if (map[id]) return id;
    return label ? Object.keys(map).find((k) => map[k].label === label && !live.has(k)) || null : null;
  }
  const markOf = (map, d) => { const k = keyFor(map, d.id, d.plain); return k ? map[k] : null; };
  function describe(d, n, group, kindWord) {
    const plain = M.tidy(d.label);
    const call = !!plain && M.isCallQuality(plain, group.filter((o) => o !== d).map((o) => M.tidy(o.label)));
    const shown = !plain ? `${kindWord} ${n}` : call ? `${plain} (call quality)` : plain;
    const item = { id: d.deviceId, label: shown, plain: plain || shown, builtIn: M.isBuiltIn(plain), callQuality: call };
    const kind = markOf(P.kinds, item), nick = markOf(P.names, item);
    return Object.assign(item, { kind: kind ? kind.value : M.classify(plain), name: nick ? nick.value : shown });
  }
  function build(kindName, kindWord) {
    const real = rawList.filter((d) => d.kind === kindName && !VIRTUAL.includes(d.deviceId));
    const items = real.map((d, i) => describe(d, i + 1, real, kindWord));
    return items.filter((d) => !d.callQuality).concat(items.filter((d) => d.callQuality));
  }
  function rebuild() {
    live = new Set(rawList.map((d) => d.deviceId));
    const dflt = (k) => { const d = rawList.find((x) => x.kind === k && x.deviceId === 'default'); return d ? M.tidy(d.label).replace(/^default\s*-\s*/i, '') : ''; };
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
    return byId(list, saved.id) || (saved.label ? list.find((d) => d.plain === saved.label) || null : null);
  }
  const savedAs = (d) => (d ? { id: d.id, label: d.plain.slice(0, LIM.label) } : null);
  function ownDefault() {
    const label = view.defaults.output;
    return view.outputs.find((d) => d.plain === label) || null;
  }
  const defaultKind = () => { const own = ownDefault(); return own ? own.kind : M.classify(view.defaults.output); };

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
  function setStatus(text) {
    const next = String(text == null ? '' : text).slice(0, LIM.status);
    if (next === statusText) return;
    statusText = next;
    fire('devices', snapshot());
  }
  function inputPending() {
    const A = window.JarvisAudio;
    if (!A || typeof A.isOpen !== 'function' || !A.isOpen()) pendingInput = false;
    return pendingInput;
  }

  // ---- saying and showing --------------------------------------------------------------------------
  // The device's name is for the screen; what is spoken uses a kind word (M.outputPhrase and friends).
  let shownToken = 0;
  function show(text) {
    const loop = window.JarvisVoiceLoop, mine = ++shownToken;
    if (!loop) return;
    const put = () => { try { loop.say(text, { speak: false }); } catch (_) {} };
    put();
    setTimeout(() => { if (mine === shownToken) put(); }, LIM.showAgainMs);   // after a caller's own line
  }
  function speak(text) {
    const loop = window.JarvisVoiceLoop;
    if (loop && visible()) { try { loop.say(text, { speak: true }); } catch (_) {} }
  }
  function announceLine(spokenText, screenText) {
    if (!visible()) return;
    speak(spokenText);
    show(screenText);
  }
  const failSpoken = () => `I couldn't switch the sound to that device, ${hon()}.`;
  function failStatus() {
    const cur = current().output;
    return `I couldn't switch the sound to that device, ${hon()} — still using ${M.outputPhrase(cur || ownDefault() || { isDefault: true })}.`;
  }

  // ---- choosing ------------------------------------------------------------------------------------
  const isDefaultId = (id) => id === null || id === undefined || id === 'default';
  function announceRoute(reason) {
    const now = current();
    const detail = { output: now.output, input: now.input, reason };
    fire('route', detail);
    emitDom('jarvis:audio-route', detail);
  }
  async function sinkTo(s, id) {
    try { return await s.setSink(id); } catch (_) { return { ok: false, reason: 'failed' }; }
  }
  /** keep: save the choice (a panel click); otherwise it holds for this page only (a voice command). */
  async function pickOutput(id, keep) {
    const s = speaker();
    if (!s || !s.sinkSupported()) return { ok: false, reason: 'unsupported' };
    const dev = isDefaultId(id) ? null : (typeof id === 'string' ? byId(view.outputs, id) : null);
    if (!isDefaultId(id) && !dev) return { ok: false, reason: 'not_found' };
    const res = await sinkTo(s, dev ? dev.id : 'default');
    if (!res || !res.ok) { setStatus(failStatus()); return { ok: false, reason: (res && res.reason) || 'failed' }; }
    if (keep) commit((cur) => Object.assign({}, cur, { output: savedAs(dev) }));
    setStatus('');
    announceRoute('output_changed');
    return { ok: true };
  }
  function pickInput(id, keep) {
    const A = window.JarvisAudio;
    if (!A || typeof A.setInput !== 'function') return { ok: false, reason: 'unsupported' };
    const dev = isDefaultId(id) ? null : (typeof id === 'string' ? byId(view.inputs, id) : null);
    if (!isDefaultId(id) && !dev) return { ok: false, reason: 'not_found' };
    session = { input: keep ? undefined : { id: dev ? dev.id : null, label: dev ? dev.plain : '' } };
    A.setInput(dev ? dev.id : null);
    if (keep) commit((cur) => Object.assign({}, cur, { input: savedAs(dev) }));
    const open = typeof A.isOpen === 'function' && A.isOpen();
    pendingInput = open;
    announceRoute('input_changed');
    const res = { ok: true };
    if (dev && dev.kind === 'headphones') res.warning = 'call_quality';
    if (open) res.pending = true;
    return res;
  }
  const chooseOutput = (id) => pickOutput(id, true);
  const chooseInput = async (id) => pickInput(id, true);

  // ---- a new device, a lost device -----------------------------------------------------------------
  function autoOk(dev) {
    if (markOf(P.kinds, dev)) return true;
    return !dev.builtIn && dev.kind !== 'unknown' && !VIRTUAL_DEVICE_RE.test(dev.plain);
  }
  async function useDevice(dev, keep) {
    const r = await pickOutput(dev.id, keep);
    if (!r.ok) { announceLine(failSpoken(), failStatus()); return; }
    announceLine(`Switching to ${M.outputPhrase(dev)}, ${hon()}.`, `Switching to ${dev.name}, ${hon()}.`);
  }
  function offerUse(dev) {
    const loop = window.JarvisVoiceLoop, C = window.JarvisVoiceCommands;
    if (P.onConnect === 'never' || !loop || !visible()) return;
    const stop = () => { if (C) C.cancelAsk(); };
    const dismiss = loop.offer(`${dev.name} connected.`, [
      { label: `Use ${dev.name}`.slice(0, 40), run: () => { stop(); useDevice(dev, true); } },
      { label: 'Not now', run: stop },
    ]);
    if (loop.inConversation() && ASKABLE.includes(loop.state())) {
      const w = M.connectPhrases(dev);
      loop.ask(`${w.said} — shall I use ${w.pronoun}, ${hon()}?`, { yes: () => { dismiss(); useDevice(dev, false); }, no: () => dismiss() });
    }
  }
  const byPreference = (a, b) => (b.kind === 'headphones') - (a.kind === 'headphones');
  async function restoreReturning(added) {
    const s = speaker(), back = P.output ? locate(P.output, added) : null;
    if (!s || !back || s.sink() === back.id) return null;
    const res = await sinkTo(s, back.id);
    if (!res || !res.ok) return null;
    if (back.id !== P.output.id) commit((cur) => Object.assign({}, cur, { output: savedAs(back) }));
    show(`${back.name} is back, ${hon()}.`);
    announceRoute('output_changed');
    return back;
  }
  async function settleAdds(list) {
    const back = await restoreReturning(list);
    const fresh = list.filter((d) => d !== back && !d.callQuality && !M.isHandsFree(d.plain)).sort(byPreference);
    if (!fresh.length || !visible()) return;
    const ready = fresh.filter(autoOk);
    if (P.onConnect === 'auto' && ready.length) useDevice(ready[0], false);
    else offerUse(fresh[0]);
  }
  let pendingAdds = new Map();
  let addTimer = 0;
  function flushAdds() {
    addTimer = 0;
    const list = Array.from(pendingAdds.keys()).map((id) => byId(view.outputs, id)).filter(Boolean);
    pendingAdds = new Map();
    if (list.length) settleAdds(list).catch(() => {});
  }
  /** Windows lists a Bluetooth device in two or three steps; wait for them all before saying anything. */
  function queueAdds(added) {
    added.forEach((d) => { if (!M.isHandsFree(d.plain)) pendingAdds.set(d.id, true); });
    if (!addTimer && pendingAdds.size) addTimer = setTimeout(flushAdds, LIM.addSettleMs);
  }
  async function fallBack(lost) {
    const s = speaker();
    if (!s) return;
    const res = await sinkTo(s, 'default');
    const h = hon();
    if (!res || !res.ok) {
      setStatus(`${lost.name} disconnected, ${h}, and I couldn't move the sound to the default output.`);
      announceLine(`That device disconnected, ${h}.`, `${lost.name} disconnected, ${h}.`);
      return;
    }
    const screen = `${lost.name} disconnected. I'll use ${view.defaults.output || 'the default output'}, ${h}.`;
    setStatus(screen);
    announceLine(`${cap(M.outputPhrase(lost))} disconnected. I'll use the default output, ${h}.`, screen);
    announceRoute('output_lost');
  }
  async function checkLost(before) {
    const s = speaker(), cur = s ? s.sink() : '';
    const gone = cur ? before.find((d) => d.id === cur && !byId(view.outputs, d.id)) : null;
    if (!gone) return;
    const twin = view.outputs.find((d) => d.plain === gone.plain);   // the same device under a new id
    if (!twin) { await fallBack(gone); return; }
    const res = await sinkTo(s, twin.id);
    if (res && res.ok && P.output && P.output.id === gone.id) commit((cur2) => Object.assign({}, cur2, { output: savedAs(twin) }));
  }

  // ---- refresh and reconcile -----------------------------------------------------------------------
  function inputTarget() {
    if (session.input) return session.input.id ? session.input : null;
    return P.input;
  }
  function applyInput() {
    const A = window.JarvisAudio;
    if (!A || typeof A.setInput !== 'function') return;
    if (session.input && !session.input.id) { A.setInput(null); return; }
    const want = inputTarget();
    if (!want) return;
    const dev = locate(want, view.inputs);
    if (!dev) { if (A.inputId()) A.setInput(null); return; }
    if (!session.input && dev.id !== want.id) commit((cur) => Object.assign({}, cur, { input: savedAs(dev) }));
    A.setInput(dev.id);
  }
  async function restoreOutput() {
    const s = speaker(), dev = locate(P.output, view.outputs);
    if (!s || !s.sinkSupported() || !dev) return;
    const res = await sinkTo(s, dev.id);
    if (!res || !res.ok) { setStatus(failStatus()); return; }
    if (dev.id !== P.output.id) commit((cur) => Object.assign({}, cur, { output: savedAs(dev) }));
  }
  /** A mark whose device came back under a new id follows it (and gains its label). */
  function healMarks() {
    const fix = (map) => {
      const next = Object.assign(Object.create(null), map);
      let changed = false;
      view.outputs.concat(view.inputs).forEach((d) => {
        const k = keyFor(map, d.id, d.plain);
        if (!k || (k === d.id && map[k].label === d.plain)) return;
        delete next[k];
        next[d.id] = { value: map[k].value, label: d.plain };
        changed = true;
      });
      return changed ? next : null;
    };
    const kinds = fix(P.kinds), names = fix(P.names);
    if (!kinds && !names) return;
    commit((cur) => Object.assign({}, cur, { kinds: kinds || cur.kinds, names: names || cur.names }));
    rebuild();
  }
  async function reconcile(before) {
    healMarks();
    applyInput();
    if (!canRoute()) { seeded = true; return; }
    if (!seeded) { seeded = true; await restoreOutput(); return; }
    await checkLost(before);
    const known = new Set(before.map((d) => d.id));
    queueAdds(view.outputs.filter((d) => !known.has(d.id) && !d.callQuality));
  }
  const listDevices = () => new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('timeout')), LIM.enumMs);
    navigator.mediaDevices.enumerateDevices().then((v) => { clearTimeout(t); resolve(v); }, (e) => { clearTimeout(t); reject(e); });
  });
  const usable = (list) => Array.isArray(list) && list.some((d) => !!d.label);
  async function doRefresh() {
    const before = view.outputs;
    let list = null;
    try {
      const all = await listDevices();
      list = all.filter((d) => d && typeof d.deviceId === 'string' && d.deviceId && (d.kind === 'audiooutput' || d.kind === 'audioinput'));
    } catch (_) { list = null; }                                // a failed listing changes nothing
    if (list && (usable(list) || !seeded)) {
      rawList = list;
      rebuild();
      if (view.labelled) { try { await reconcile(before); } catch (_) {} }
    }
    fire('devices', snapshot());
    emitDom('jarvis:audio-devices', snapshot());
    return snapshot();
  }
  let chain = Promise.resolve();
  const refresh = () => { chain = chain.then(doRefresh, doRefresh).catch(snapshot); return chain; };
  const supported = () => !!(navigator.mediaDevices && typeof navigator.mediaDevices.enumerateDevices === 'function');

  // ---- a chosen microphone that is gone ------------------------------------------------------------
  function onRoute(e) {
    const d = e && e.detail;
    if (!d || d.reason !== 'input_missing') return;     // our own route events carry an output key
    const A = window.JarvisAudio;
    if (A) A.setInput(null);
    const want = inputTarget();
    const name = (want && want.label) || 'That microphone';
    session = { input: { id: null, label: '' } };       // stay on the default until it is chosen again
    show(`${name} isn't available, so I'm using the laptop mic, ${hon()}.`);
    announceRoute('input_changed');
  }

  // ---- voice commands (D12) ------------------------------------------------------------------------
  const defaultDevice = (which) => ({ id: 'default', label: 'the default', name: 'the default ' + (which === 'input' ? 'microphone' : 'output'), plain: 'the default', kind: which === 'input' ? 'unknown' : defaultKind(), builtIn: true, callQuality: false, isDefault: true });
  function resolve(text, which) {
    const none = { dev: null, tied: [] };
    const q = M.cleanTarget(text);
    if (!q) return none;
    if (M.DEFAULT_WORDS.includes(q)) return { dev: defaultDevice(which), tied: [] };
    const s = speaker();
    const prefer = (d) => !!markOf(P.kinds, d) || (!!P.output && P.output.id === d.id) || (!!s && s.sink() === d.id);
    const ranked = M.rank(which === 'input' ? view.inputs : view.outputs, text, { nameOf: (d) => (markOf(P.names, d) || {}).value || '', prefer });
    if (!ranked.length) return none;
    const top = ranked.filter((r) => r.key === ranked[0].key);
    return { dev: Object.assign({}, ranked[0].d), tied: top.length > 1 ? top.map((r) => Object.assign({}, r.d)) : [] };
  }
  const find = (name, kind) => resolve(name, kind === 'input' ? 'input' : 'output').dev;
  const resolves = (text, kind) => M.isDeviceWord(text) || !!resolve(text, kind).dev;
  const done = (say) => {
    const loop = window.JarvisVoiceLoop;
    return { say, then: loop && loop.inConversation() ? 'listen' : 'idle' };
  };
  /** The screen gets the real name; the returned (spoken) sentence stays generic. */
  function withScreen(screenText, spokenText, keep) {
    show(screenText);
    if (keep) setStatus(screenText);
    return done(spokenText);
  }
  const noMatch = (x, mic) => {
    const word = M.isDeviceWord(x) ? x : '';          // only a known device word is repeated, never the owner's own name for it
    if (!word) return `I can't find that ${mic ? 'microphone' : 'device'}, ${hon()}.`;
    return `I can't see ${mic ? 'a ' + word + ' microphone' : word} connected, ${hon()}.`;
  };
  const askWhich = (tied) => withScreen(`I can see ${tied.map((d) => d.name).join(' or ')}.`, `I can see two, which one, ${hon()}?`, true);
  function slotMatcher(id, kind) {
    const forms = ((window.JarvisVoiceCommands && window.JarvisVoiceCommands.PHRASES[id]) || []).map((t) => t.split('{device}'));
    return (text) => {
      if (text.split(' ').length > LIM.maxWords) return null;
      for (const [pre, post] of forms) {
        if (!text.startsWith(pre) || !text.endsWith(post) || text.length <= pre.length + post.length) continue;
        const x = text.slice(pre.length, text.length - post.length).trim();
        if (kind === 'output' && /(^| )mic$/.test(x)) continue;
        if (x && resolves(x, kind)) return { x: M.cleanTarget(x) };
      }
      return null;
    };
  }
  async function runSwitch(args) {
    if (!canRoute()) return done(TEXT.unsupported());
    const found = resolve(args.x, 'output');
    if (!found.dev) return done(noMatch(args.x, false));
    if (found.tied.length) return askWhich(found.tied);
    const dev = found.dev, h = hon();
    const r = await pickOutput(dev.id, false);
    if (!r.ok) return withScreen(statusText || failStatus(), failSpoken(), true);
    const screen = `Switching to ${dev.name}, ${h}.`;
    return withScreen(screen, speaker().usingBrowser() ? TEXT.browserVoice() : `Switching to ${M.outputPhrase(dev)}, ${h}.`);
  }
  async function runInput(args) {
    const found = resolve(args.x, 'input');
    if (!found.dev) return done(noMatch(args.x, true));
    if (found.tied.length) return askWhich(found.tied);
    const dev = found.dev, h = hon();
    const r = pickInput(dev.id, false);
    if (!r.ok) return done(failSpoken());
    const screen = `Listening through ${dev.name}, ${h}.`;
    if (r.pending) return withScreen(screen, `I'll use that microphone from the next time I open the mic, ${h}.`);
    const warn = r.warning ? ' Sound drops to call quality while that mic is in use.' : '';
    return withScreen(screen, `I'll listen through ${M.inputPhrase(dev)}, ${h}.${warn}`);
  }
  const countWord = (n) => COUNT_WORDS[n] || String(n);
  const sayList = (words) => (words.length < 2 ? words.join('') : `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`);
  function runList() {
    if (!canRoute() && onAndroid()) return done(TEXT.android());
    const h = hon();
    if (!view.labelled) return done(`I can't see device names yet, ${h}. Tap the mic once to allow it.`);
    const real = view.outputs.filter((d) => !d.callQuality);
    if (!real.length) return done(`I can't see any sound outputs, ${h}.`);
    const cur = current().output, active = cur || ownDefault();
    const others = real.filter((d) => !cur || d.id !== cur.id).map((d) => d.name);
    const mic = current().input;
    const screen = `Speaking through ${cur ? cur.name : view.defaults.output || 'the default output'}${others.length ? `; also connected: ${others.join(', ')}.` : '.'}${mic ? ` Listening through ${mic.name}.` : ''}`;
    const n = real.length;
    const said = `You have ${countWord(n)} output${n === 1 ? '' : 's'}: ${sayList(real.map(M.kindListWord))}. I'm speaking through ${M.outputPhrase(active || { isDefault: true })}; the names are on screen, ${h}.`;
    return withScreen(screen, said, true);
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
  const flat = (map) => {
    const out = Object.create(null);
    Object.keys(map).forEach((k) => { out[k] = map[k].value; });
    view.outputs.concat(view.inputs).forEach((d) => { const m = markOf(map, d); if (m) out[d.id] = m.value; });
    return out;
  };
  const labelOfId = (id) => { const d = byId(view.outputs, id) || byId(view.inputs, id); return d ? d.plain : ''; };
  function setMark(map, id, value, valid) {
    if (typeof id !== 'string' || !id) return false;
    const label = labelOfId(id), add = !!value && valid(value);
    const edit = (next) => {
      const old = keyFor(next, id, label);
      if (old) delete next[old];
      if (add) next[id] = { value, label };
    };
    if (Object.keys(withMap(load() || P, map, edit)[map]).length > LIM.marks) return false;
    commit((cur) => withMap(cur, map, edit));
    rebuild(); fire('devices', snapshot());
    return true;
  }
  const prefsApi = Object.freeze({
    prefs: () => ({ v: P.v, output: P.output && Object.assign({}, P.output), input: P.input && Object.assign({}, P.input), kinds: flat(P.kinds), names: flat(P.names), onConnect: P.onConnect }),
    devices: () => Object.assign({ outputs: copy(view.outputs), inputs: copy(view.inputs) }, { defaults: Object.assign({}, view.defaults), labelled: view.labelled }),
    setKind: (id, kind) => setMark('kinds', id, kind, (k) => KINDS.includes(k)),
    setName: (id, name) => setMark('names', id, typeof name === 'string' ? M.nick(name) : '', () => true),
    setOnConnect(v) {
      if (!POLICIES.includes(v)) return false;
      commit((cur) => Object.assign({}, cur, { onConnect: v }));
      fire('devices', snapshot());
      return true;
    },
    canRoute, onAndroid, defaultKind, status: () => statusText, setStatus, inputPending, text: TEXT,
  });
  function on(kind, fn) {
    if (!listeners[kind] || typeof fn !== 'function') return () => {};
    listeners[kind].push(fn);
    return () => { const i = listeners[kind].indexOf(fn); if (i >= 0) listeners[kind].splice(i, 1); };
  }
  function onStorage(e) {
    if (e && e.key !== null && e.key !== undefined && e.key !== KEY) return;
    P = load() || P;
    rebuild();
    fire('devices', snapshot());
  }
  /** Names appear once the mic has been allowed: look again when something suggests it was. */
  function wireRelist() {
    let timer = 0;
    const later = (ms) => { clearTimeout(timer); timer = setTimeout(() => { refresh(); }, ms); };
    const ifUnlabelled = () => { if (!view.labelled && visible()) later(LIM.debounceMs); };
    const md = navigator.mediaDevices;
    if (typeof md.addEventListener === 'function') md.addEventListener('devicechange', () => later(LIM.debounceMs));
    ['visibilitychange', 'jarvis:voice-loop', 'jarvis:mic-lock'].forEach((n) => document.addEventListener(n, ifUnlabelled));
    try {
      const q = navigator.permissions && navigator.permissions.query({ name: 'microphone' });
      if (q) q.then((st) => { if (st && typeof st.addEventListener === 'function') st.addEventListener('change', ifUnlabelled); }, () => {});
    } catch (_) {}
  }
  function boot() {
    registerCommands();
    document.addEventListener('jarvis:audio-route', onRoute);
    window.addEventListener('storage', onStorage);
    const A = window.JarvisAudio;
    if (A && P.input && typeof A.setInput === 'function') A.setInput(P.input.id);   // before the first open
    if (!supported()) return;
    wireRelist();
    refresh();
  }

  window.JarvisAudioRoute = Object.freeze({ supported, refresh, current, chooseOutput, chooseInput, outputKind, find, on });
  window.JarvisAudioRoutePrefs = prefsApi;
  boot();
})();
