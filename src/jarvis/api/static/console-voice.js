// src/jarvis/api/static/console-voice.js — the Voice panel and the voice settings (slice 9,
// docs/plans/phase1-slice9-voice.md §3–§5). No build step; CSP script-src 'self'.
// Every server string reaches the page through textContent; a field of the wrong type is dropped,
// never guessed. Costs are rupees only. Transport is the console's own api() for JSON
// (window.JarvisConsole) and JarvisChat.raw() for audio (same cookie / X-Requested-With: JARVIS /
// bearer token; 401 → the sign-in gate).
// Two kinds of setting:
//   the owner's (server, PUT /v1/voice/settings, debounced and one at a time): voice, rate, wit;
//   this device's (localStorage, wrapped in try/catch): speech engine, voice finish, speak replies,
//   send straight away, keep listening, "Hey Jarvis" (off by default).
// window.JarvisVoice (used by console-voice-mic.js and console-3d.js):
//   config() (undefined = not loaded, null = no voice service here), load(force), device(),
//   setDevice(patch), settings(), inputEngine() / outputEngine() ('cloud' | 'browser' | 'none'),
//   markDown(kind, ms), refusal() / refused(response) (the {error, detail, reason} contract),
//   language(), speaker (JarvisSpeaker), visual() / setVisual(fn) for the Core.
//   R5 (docs/plans/r5-voice.md): panelSlot('devices' | 'phrases' | 'pace') -> the element other
//   modules render into (null until the panel is built; jarvis:voice-panel {built: true} says when),
//   updateSettings({voice, rate, wit, phrases}) -> bool (type-checked, then saved like any change).
//   New device keys: interruptBy, followUpS, longPauseS, endSilenceMs, checkIn, cues.
// GET /v1/voice is asked at most once a minute when fresh, and backs off after a refusal (429
// rate_limited: 10 s, doubling to a minute; other errors: 5 s); a 429 on PUT keeps the change and
// saves it again later. 503 budget_unavailable (the allowance can't be read) keeps the panel usable
// with this browser's voice.
// Fires: jarvis:voice-config, jarvis:voice-device, jarvis:voice-note {text}, jarvis:speech {text, engine}.
// Listens: jarvis:ready, jarvis:panel (Voice shown), jarvis:wake {state} (console-voice-mic.js).
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const panel = $('p-voice'), box = $('voice'), noteEl = $('voiceNote'), metaEl = $('voiceMeta');
  const Deck = window.JarvisDeck || { rupees: () => '' };
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
  };
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });

  const DEVICE_KEY = 'jarvis_voice_device_v1';
  const ENGINES = { auto: 'Automatic', cloud: 'Google Cloud', browser: 'This browser' };
  const SPEAKS = { voice: 'When I speak', always: 'Always', never: 'Never' };
  const FINISHES = { comms: 'Comms', clean: 'Clean' };
  const INTERRUPTS = { auto: 'Automatic', speech: 'Speaking', name: 'Saying "Jarvis" or "stop"', tap: 'Tapping only' };
  const FOLLOWS = { 5: '5 seconds', 8: '8 seconds', 12: '12 seconds', 20: '20 seconds', 30: '30 seconds' };
  const LONG_PAUSES = { 15: '15 seconds', 20: '20 seconds', 30: '30 seconds', 60: '1 minute', 120: '2 minutes' };
  const END_SILENCES = { 800: '0.8 seconds', 1000: '1 second', 1200: '1.2 seconds', 1600: '1.6 seconds', 2000: '2 seconds', 2500: '2.5 seconds' };
  const DEVICE_DEFAULTS = Object.freeze({ engine: 'auto', finish: 'comms', speak: 'voice', autoSend: true, keepListening: true, wake: false,
    interruptBy: 'auto', followUpS: 8, longPauseS: 20, endSilenceMs: 1200, checkIn: true, cues: true });
  const RATE_MIN = 0.8, RATE_MAX = 1.25, RATE_STEP = 0.05;
  const SAVE_DEBOUNCE_MS = 500, FRESH_MS = 60 * 1000, DOWN_MS = 10 * 60 * 1000, NOTE_MS = 5000;
  const BACKOFF_MIN_MS = 10 * 1000, BACKOFF_MAX_MS = 60 * 1000, ERROR_PAUSE_MS = 5000, PUT_RETRY_MS = 8000;
  const TOO_MANY = 'Too many requests just now. JARVIS will ask again in a few seconds.';
  const NO_ALLOWANCE = 'JARVIS can\'t read this month\'s voice allowance right now, so it uses this browser\'s voice. Please try again later.';
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const GCLOUD_FIX = 'gcloud services enable texttospeech.googleapis.com speech.googleapis.com';
  const WAKE_LICENCE = 'Wake word model: openWakeWord (CC BY-NC-SA 4.0), personal use';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;

  // ---- small, type-checking helpers -----------------------------------------------------------
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').trim().slice(0, max) : '');
  const own = (map, key) => typeof key === 'string' && Object.prototype.hasOwnProperty.call(map, key);
  const ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;
  const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$/;
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const count = (n) => { try { return Math.round(n).toLocaleString('en-US'); } catch (_) { return String(Math.round(n)); } };
  const clampRate = (r) => Math.min(RATE_MAX, Math.max(RATE_MIN, Math.round(r / RATE_STEP) * 5 / 100)); // 1.15, never 1.1500000000000001
  function detailOf(e) { // the server's plain-English message, never a bare code or "[object …]"
    if (e && e.name === 'TypeError') return OFFLINE;
    const t = (e && typeof e.message === 'string' ? e.message : '').replace(INVISIBLE, '').trim();
    return t && t.length <= 300 && !t.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(t) ? t : '';
  }

  // ---- this device's settings ------------------------------------------------------------------
  const inRange = (v, lo, hi) => typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi;
  /** Copy the valid device settings of `src` onto `dst`; a value of the wrong type or range is dropped. */
  function pickDevice(src, dst) {
    if (own(ENGINES, src.engine)) dst.engine = src.engine;
    if (own(FINISHES, src.finish)) dst.finish = src.finish;
    if (own(SPEAKS, src.speak)) dst.speak = src.speak;
    if (own(INTERRUPTS, src.interruptBy)) dst.interruptBy = src.interruptBy;
    if (inRange(src.followUpS, 3, 30)) dst.followUpS = Math.round(src.followUpS);
    if (inRange(src.longPauseS, 10, 120)) dst.longPauseS = Math.round(src.longPauseS);
    if (typeof src.endSilenceMs === 'number' && own(END_SILENCES, String(src.endSilenceMs))) dst.endSilenceMs = src.endSilenceMs;
    ['autoSend', 'keepListening', 'wake', 'checkIn', 'cues'].forEach(k => { if (typeof src[k] === 'boolean') dst[k] = src[k]; });
    dst.longPauseS = Math.min(120, Math.max(dst.longPauseS, dst.followUpS + 5)); // the handover never comes before the wait ends
    return dst;
  }
  function readDevice() {
    let saved = null;
    try { saved = obj(JSON.parse(store.get(DEVICE_KEY) || 'null')); } catch (_) { saved = null; }
    return Object.freeze(pickDevice(saved || {}, Object.assign({}, DEVICE_DEFAULTS)));
  }
  let device = readDevice();
  function setDevice(patch) {
    device = Object.freeze(pickDevice(obj(patch) || {}, Object.assign({}, device)));
    store.set(DEVICE_KEY, JSON.stringify(device));
    speaker.setFinish(device.finish);
    emit('jarvis:voice-device', device);
    render();
  }

  // ---- what GET /v1/voice sends, checked field by field ------------------------------------------
  const CLOUD_STATES = ['ready', 'off', 'unavailable'];
  const phraseList = (v) => arr(v).filter(p => typeof p === 'string').map(p => txt(p, 100)).filter(Boolean).slice(0, 100);
  function normal(r) {
    const o = obj(r);
    if (!o) return null;
    const cloud = obj(o.cloud) || {}, st = obj(o.settings) || {}, al = obj(o.allowance) || {};
    const tts = obj(al.tts) || {}, stt = obj(al.stt) || {}, month = obj(o.month) || {};
    const voices = arr(o.voices).map(obj).filter(Boolean)
      .filter(v => v.available === true && typeof v.id === 'string' && ID.test(v.id))
      .map(v => ({ id: v.id, label: txt(v.label, 60) || v.id, style: txt(v.style, 60), type: txt(v.type, 30) }));
    const wit = arr(o.wit_levels).map(obj).filter(Boolean)
      .filter(w => typeof w.id === 'string' && ID.test(w.id))
      .map(w => ({ id: w.id, label: txt(w.label, 40) || w.id, description: txt(w.description, 300) }));
    const lang = txt(o.language, 20);
    const rate = num(st.rate);
    return {
      cloud: {
        tts: CLOUD_STATES.includes(cloud.tts) ? cloud.tts : 'off',
        stt: CLOUD_STATES.includes(cloud.stt) ? cloud.stt : 'off',
        reason: typeof cloud.reason === 'string' && /^[a-z_]{1,40}$/.test(cloud.reason) ? cloud.reason : null,
      },
      settings: {
        voice: typeof st.voice === 'string' && ID.test(st.voice) ? st.voice : null,
        rate: rate !== null ? clampRate(rate) : 1,
        wit: typeof st.wit === 'string' && ID.test(st.wit) ? st.wit : null,
        phrases: phraseList(st.phrases),
      },
      phraseLimits: { items: num(obj(o.phrase_limits) && o.phrase_limits.items) || 50, chars: num(obj(o.phrase_limits) && o.phrase_limits.chars) || 40 },
      voices, wit,
      allowance: {
        chars: num(tts.used_chars), freeChars: num(tts.free_chars),
        seconds: num(stt.used_seconds), freeSeconds: num(stt.free_seconds),
        resetsAt: typeof al.resets_at === 'string' && ISO.test(al.resets_at) ? al.resets_at : null,
      },
      inr: num(month.voice_inr),
      language: /^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$/.test(lang) ? lang : 'en-IN',
    };
  }

  // ---- state + server ------------------------------------------------------------------------------
  const S = {
    cfg: undefined, error: '', seq: 0, at: 0, loading: null,
    local: null, sending: null, saving: false, timer: 0,
    down: { tts: 0, stt: 0 }, noteTimer: 0, wake: { state: 'off', note: '' }, built: false,
    retryAt: 0, backoff: 0, retryTimer: 0, wakeSaid: 'off',
  };
  const hasApi = () => !!(window.JarvisConsole && window.JarvisConsole.api);
  const api = (path, opts) => window.JarvisConsole.api(path, opts);

  const current = () => (S.cfg === undefined ? null : S.cfg);
  function load(force) {
    if (!hasApi()) return Promise.resolve(current());
    if (S.loading) return S.loading;
    if (Date.now() < S.retryAt) return Promise.resolve(current()); // backing off: not even a Retry
    if (!force && S.cfg !== undefined && Date.now() - S.at < FRESH_MS) return Promise.resolve(S.cfg);
    const seq = ++S.seq;
    S.loading = (async () => {
      try {
        const d = normal(await api('/v1/voice'));
        if (seq === S.seq) { if (d) { S.cfg = d; S.error = ''; } else S.error = 'The server sent something unexpected.'; }
        S.backoff = 0;
      } catch (e) {
        if (seq === S.seq && e.status !== 401) {
          if (e.status === 404) { S.cfg = null; S.error = ''; }
          else if (e.status === 429) { S.error = TOO_MANY; pause(S.backoff = Math.min(BACKOFF_MAX_MS, Math.max(BACKOFF_MIN_MS, S.backoff * 2))); }
          else if (e.status === 503 && e.code === 'budget_unavailable') { S.error = NO_ALLOWANCE; pause(ERROR_PAUSE_MS); }
          else { S.error = detailOf(e) || 'Please try again.'; pause(ERROR_PAUSE_MS); }
        }
      } finally { S.loading = null; S.at = Date.now(); }
      emit('jarvis:voice-config', { ready: !!S.cfg });
      render();
      return S.cfg === undefined ? null : S.cfg;
    })();
    render();
    return S.loading;
  }

  /** No GET until `ms` from now (the Retry button waits too); then the panel can try again. */
  function pause(ms) {
    S.retryAt = Date.now() + ms;
    clearTimeout(S.retryTimer);
    S.retryTimer = setTimeout(render, ms + 50);
  }

  /** The owner's settings as this page wants them: saved, then in flight, then not yet sent. */
  function settings() {
    const base = S.cfg ? S.cfg.settings : { voice: null, rate: 1, wit: null, phrases: [] };
    return Object.freeze(Object.assign({}, base, S.sending || {}, S.local || {}));
  }
  function change(patch) {
    S.local = Object.assign({}, S.local || {}, patch);
    clearTimeout(S.timer);
    S.timer = setTimeout(save, SAVE_DEBOUNCE_MS);
    renderValues();
  }
  /** For other modules (the words editor): only known keys, type-checked, then saved like any change. */
  function updateSettings(patch) {
    const p = obj(patch);
    if (!p) return false;
    const out = {}, r = num(p.rate);
    if (typeof p.voice === 'string' && ID.test(p.voice)) out.voice = p.voice;
    if (r !== null) out.rate = clampRate(r);
    if (typeof p.wit === 'string' && ID.test(p.wit)) out.wit = p.wit;
    if (Array.isArray(p.phrases) && p.phrases.length <= 100 && p.phrases.every(x => typeof x === 'string' && x.length <= 200)) out.phrases = p.phrases.slice();
    if (!Object.keys(out).length) return false;
    change(out);
    return true;
  }
  /** One PUT at a time; changes made meanwhile go in the next one. */
  async function save() {
    if (S.saving || !S.local || !hasApi()) return;
    const body = S.local;
    S.local = null; S.sending = body; S.saving = true;
    let later = false;
    try {
      const r = obj(await api('/v1/voice/settings', { method: 'PUT', body }));
      ++S.seq; // an older GET still on its way must not overwrite what was just saved
      if (r && S.cfg) {
        const fresh = normal({ settings: r }).settings;
        const phrases = Array.isArray(r.phrases) ? fresh.phrases : Array.isArray(body.phrases) ? phraseList(body.phrases) : S.cfg.settings.phrases;
        S.cfg = Object.assign({}, S.cfg, { settings: { voice: fresh.voice || S.cfg.settings.voice, rate: fresh.rate, wit: fresh.wit || S.cfg.settings.wit, phrases } });
      }
      flash('ok', 'Saved.');
      log('info', 'Voice settings saved');
    } catch (e) {
      if (e.status === 429) { // rate_limited: keep the change (newer edits win) and try again later
        later = true;
        S.local = Object.assign({}, body, S.local || {});
        flash('bad', 'Too many changes just now: saving again in a few seconds.');
      } else {
        if (e.status !== 401) flash('bad', 'Couldn\'t save. ' + (detailOf(e) || 'Please try again.'));
        if (e.status === 422) load(true); // what the server holds may differ: show it again
      }
    } finally {
      S.sending = null; S.saving = false;
      renderValues();
      clearTimeout(S.timer);
      if (later) S.timer = setTimeout(save, PUT_RETRY_MS);
      else if (S.local) save();
    }
  }
  function flash(kind, text) {
    if (!noteEl) return;
    clearTimeout(S.noteTimer);
    noteEl.textContent = kind ? text : '';
    noteEl.className = 'bnote vlive' + (kind ? ' ' + kind : '');
    if (kind === 'ok') S.noteTimer = setTimeout(() => flash(null), NOTE_MS);
  }

  // ---- engines (§1 D3: cloud when ready, else the browser's, else typing) -------------------------
  const recognition = () => window.SpeechRecognition || window.webkitSpeechRecognition || null;
  const capture = () => !!(window.JarvisAudio && window.JarvisAudio.supported());
  const cloudReady = (kind) => !!(S.cfg && S.cfg.cloud[kind] === 'ready' && Date.now() >= S.down[kind]);
  /** Automatic: cloud, else the browser's. A chosen engine is kept to (audio never goes somewhere
   *  the owner did not pick), so it may be 'none' while that engine is unavailable. */
  function inputEngine() {
    const cloud = cloudReady('stt') && capture(), browser = !!recognition();
    if (device.engine === 'cloud') return cloud ? 'cloud' : 'none';
    if (device.engine === 'browser') return browser ? 'browser' : 'none';
    return cloud ? 'cloud' : browser ? 'browser' : 'none';
  }
  function outputEngine() {
    if (cloudReady('tts')) return 'cloud';
    return window.speechSynthesis && typeof window.SpeechSynthesisUtterance === 'function' ? 'browser' : 'none';
  }
  /** The cloud said no (503 / 402): use the browser's engine for ten minutes, then ask again. */
  function markDown(kind, ms) {
    if (kind !== 'tts' && kind !== 'stt') return;
    const span = typeof ms === 'number' && ms > 0 ? Math.min(ms, DOWN_MS) : DOWN_MS;
    S.down[kind] = Math.max(S.down[kind], Date.now() + span);
    render();
  }
  /** What a refused voice call means for the console (backend contract: {error, detail, reason}
   *  plus Retry-After on 429). Returns {fallback, skip, downMs, reason}. */
  function refusal(status, code, reason, retryAfter) {
    if (status === 401) return { skip: true };                                 // the sign-in gate takes over
    if (status === 402) return { fallback: true, downMs: DOWN_MS, reason: 'budget' }; // budget_reached
    if (status === 503) return { fallback: true, downMs: DOWN_MS, reason: reason || code || 'unavailable' };
    if (status === 429 && code === 'voice_busy') return { fallback: true, downMs: (retryAfter || 10) * 1000, reason: 'busy' };
    if (status === 422 && code === 'nothing_to_say') return { skip: true };     // nothing speakable in it
    return { fallback: true, downMs: 0, reason: code || 'error' };               // rate_limited, input_rejected, 5xx
  }
  /** Read a refused voice response: status, code, reason, Retry-After seconds, plain words. */
  async function refused(r) {
    let j = null;
    try { j = obj(await r.json()); } catch (_) { j = null; }
    const o = j || {}, d = obj(o.detail);
    const code = typeof o.error === 'string' ? o.error : d && typeof d.code === 'string' ? d.code : '';
    const reason = typeof o.reason === 'string' ? o.reason : d && typeof d.reason === 'string' ? d.reason : '';
    const retry = parseInt(r.headers.get('Retry-After') || '', 10);
    return { status: r.status, code, reason, retryAfter: Number.isFinite(retry) && retry > 0 ? retry : 0,
      detail: typeof o.detail === 'string' ? txt(o.detail, 300) : '' };
  }

  // ---- speech out: POST /v1/voice/speak → MP3 → the shared speaker ---------------------------------
  function speakError(status, code, reason, retryAfter) {
    const e = new Error(code || 'speak_failed'), what = refusal(status, code, reason, retryAfter);
    e.status = status;
    if (what.skip) e.skip = true;
    if (what.fallback) { e.fallback = true; e.reason = what.reason; if (what.downMs) markDown('tts', what.downMs); }
    return e;
  }
  async function synth(text, signal, meta) {
    const raw = window.JarvisChat && window.JarvisChat.raw;
    if (!raw) throw Object.assign(new Error('no_transport'), { fallback: true });
    const s = settings();
    let body;
    if (meta && meta.preview) body = { preview: true, voice: meta.preview };  // the server's fixed sample line
    else { body = { text, rate: s.rate }; if (s.voice) body.voice = s.voice; }
    let r;
    try {
      r = await raw('/v1/voice/speak', { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' }, signal });
    } catch (err) {
      if (err && err.name === 'AbortError') throw err;
      if (err && err.status === 401) throw speakError(401);
      throw Object.assign(new Error('network'), { fallback: true, reason: 'network' });
    }
    if (r.ok) return r.arrayBuffer();
    const f = await refused(r);
    throw speakError(f.status, f.code, f.reason, f.retryAfter);
  }
  const speaker = window.JarvisSpeaker.create({ synth, finish: device.finish });
  speaker.on('chunk', (d) => emit('jarvis:speech', { text: d.text, engine: d.engine }));
  let visualFn = null;

  // ---- rendering ---------------------------------------------------------------------------------
  // The structure is built once (a re-render must never interrupt a slider being dragged); every
  // render after that only updates values, states and texts.
  const UI = {};
  function section(title, id) {
    const s = mk('section', 'bsec'); s.setAttribute('aria-labelledby', id);
    const h = mk('h3'); h.id = id; h.append(mk('span', '', title)); s.append(h);
    return s;
  }
  function toggle(id, label, help, onPress) {
    const row = mk('div', 'bopt'), t = mk('div', 'btxt');
    const l = mk('span', 'bl', label); l.id = id + 'L';
    const d = mk('small', '', help); d.id = id + 'D';
    t.append(l, d);
    const b = mk('button', 'bsw'); b.type = 'button'; b.id = id;
    b.setAttribute('aria-pressed', 'false'); b.setAttribute('aria-labelledby', l.id); b.setAttribute('aria-describedby', d.id);
    const track = mk('span', 'track'); track.setAttribute('aria-hidden', 'true'); track.append(mk('i'));
    const st = mk('span', 'st', 'Off'); st.setAttribute('aria-hidden', 'true');
    b.append(track, st);
    b.addEventListener('click', (e) => onPress(b.getAttribute('aria-pressed') !== 'true', e));
    row.append(t, b);
    return { row, button: b, help: d };
  }
  function setPressed(b, on) { b.setAttribute('aria-pressed', String(on)); b.querySelector('.st').textContent = on ? 'On' : 'Off'; }
  function select(id, label, help, options, onChange) {
    const row = mk('div', 'bopt'), t = mk('div', 'btxt');
    const l = mk('label', 'bl', label); l.htmlFor = id;
    const d = mk('small', '', help); d.id = id + 'D';
    t.append(l, d);
    const s = mk('select', 'bsel'); s.id = id; s.setAttribute('aria-describedby', d.id);
    Object.keys(options).forEach(k => { const o = mk('option', '', options[k]); o.value = k; s.append(o); });
    s.addEventListener('change', () => onChange(s.value));
    row.append(t, s);
    return { row, select: s, help: d };
  }
  function build() {
    box.textContent = '';
    UI.state = mk('div', 'vstate'); UI.state.id = 'voiceState';
    UI.status = mk('div', 'vstatus'); UI.status.id = 'voiceStatus'; UI.status.setAttribute('role', 'status');
    // the owner's settings (saved on the server)
    UI.voiceSec = section('Voice', 'vVoiceT');
    UI.voiceList = mk('div', 'vlist'); UI.voiceList.setAttribute('role', 'radiogroup'); UI.voiceList.setAttribute('aria-labelledby', 'vVoiceT');
    UI.voiceSec.append(mk('p', 'bfine vlead', 'An original British voice. Press Preview to hear one.'), UI.voiceList);
    UI.rateSec = section('Speed', 'vRateT');
    const rr = mk('div', 'vrate');
    UI.rate = mk('input', 'vrange'); UI.rate.type = 'range'; UI.rate.id = 'vRate';
    UI.rate.min = String(RATE_MIN); UI.rate.max = String(RATE_MAX); UI.rate.step = String(RATE_STEP);
    UI.rate.setAttribute('aria-labelledby', 'vRateT');
    UI.rateOut = mk('output', 'vrout'); UI.rateOut.id = 'vRateOut'; UI.rateOut.htmlFor = 'vRate';
    UI.rate.addEventListener('input', () => { UI.rateOut.textContent = rateText(+UI.rate.value); UI.rate.setAttribute('aria-valuetext', rateText(+UI.rate.value)); });
    UI.rate.addEventListener('change', () => change({ rate: clampRate(+UI.rate.value) }));
    rr.append(UI.rate, UI.rateOut);
    UI.rateSec.append(rr);
    UI.witSec = section('Wit', 'vWitT');
    UI.witList = mk('div', 'vlist'); UI.witList.setAttribute('role', 'radiogroup'); UI.witList.setAttribute('aria-labelledby', 'vWitT');
    UI.witSec.append(mk('p', 'bfine vlead', 'How much dry humour JARVIS allows himself. Never in approvals, bad news or money matters.'), UI.witList);
    // this device's settings
    UI.devSec = section('On this device', 'vDevT');
    const eng = select('vEngine', 'Speech engine', '', ENGINES, (v) => setDevice({ engine: v }));
    UI.engine = eng.select; UI.engineHelp = eng.help;
    const fin = select('vFinish', 'Voice finish', 'Comms adds a light radio-and-room finish to the cloud voice. Clean plays it as it is.', FINISHES, (v) => setDevice({ finish: v }));
    UI.finish = fin.select;
    const sp = select('vSpeak', 'Speak replies', '', SPEAKS, (v) => setDevice({ speak: v }));
    UI.speak = sp.select; UI.speakHelp = sp.help;
    const auto = toggle('vAuto', 'Send what I say straight away', 'Off: your words wait in the message box so you can check them first.', (on) => setDevice({ autoSend: on }));
    const keep = toggle('vKeep', 'Keep listening after replies', 'After a spoken reply JARVIS keeps listening. If you say nothing for 20 seconds he tells you and switches to the keyboard.', (on) => setDevice({ keepListening: on }));
    UI.auto = auto.button; UI.keep = keep.button;
    const A = window.JarvisAudio;
    const mic = toggle('vMic', 'Microphone on this device', 'Off cuts the microphone completely until you switch it on here or with the mic button. It stays off after a reload.', (on, e) => { if (!A) return; if (on) { if (e && e.isTrusted) A.unlock('panel'); } else A.lock('panel'); renderValues(); });
    const intr = select('vInterrupt', 'Interrupt JARVIS by', 'Automatic: speaking over earphones, "Jarvis" or "stop" on speakers. In "Jarvis or stop" mode JARVIS gets quieter when you talk over him and sends a clip of up to 2.5 seconds to Google Cloud speech to check for a command; the words are dropped unless they are one. ' + 'The "Hey Jarvis" model listens only while JARVIS speaks, unless you switch it on below.', INTERRUPTS, (v) => setDevice({ interruptBy: v }));
    const fol = select('vFollow', 'Wait for me to start speaking', 'How long JARVIS listens for your next words after he finishes a reply.', FOLLOWS, (v) => setDevice({ followUpS: Number(v) }));
    const lp = select('vLongPause', 'Switch to the keyboard after', 'If you say nothing for this long, JARVIS tells you and switches to the keyboard.', LONG_PAUSES, (v) => setDevice({ longPauseS: Number(v) }));
    const es = select('vEndSilence', 'Pause allowed mid-sentence', 'How long you can pause before JARVIS decides you have finished. Shorter is quicker to answer.', END_SILENCES, (v) => setDevice({ endSilenceMs: Number(v) }));
    const ci = toggle('vCheckIn', 'Check in when the room keeps talking', 'After 8 replies in a row without a tap, JARVIS asks whether to keep listening, in case a TV is talking to him.', (on) => setDevice({ checkIn: on }));
    const cu = toggle('vCues', 'Sound cues', 'Short tones when listening starts and when the microphone goes off.', (on) => setDevice({ cues: on }));
    UI.mic = mic.button; UI.interrupt = intr.select; UI.follow = fol.select; UI.longPause = lp.select; UI.endSilence = es.select;
    UI.checkIn = ci.button; UI.cues = cu.button;
    UI.devSec.append(mic.row, eng.row, sp.row, auto.row, keep.row, intr.row, fol.row, lp.row, es.row, ci.row, cu.row, fin.row);
    // "Hey Jarvis": only when the wake-word module is here and works in this browser
    const wake = toggle('vWake', 'Say "Hey Jarvis"', 'This device only, off by default. Listens on this device; no audio leaves it until you say "Hey Jarvis".', (on) => setDevice({ wake: on }));
    UI.wake = wake.button;
    UI.wakeRow = mk('div', 'vwake'); UI.wakeRow.id = 'vWakeRow';
    UI.wakeChip = mk('p', 'vchip'); UI.wakeChip.id = 'vWakeChip'; // flips on every turn: not a live region
    UI.wakeLive = mk('span', 'sr-only'); UI.wakeLive.id = 'vWakeLive';
    UI.wakeLive.setAttribute('role', 'status'); UI.wakeLive.setAttribute('aria-live', 'polite'); UI.wakeLive.setAttribute('aria-atomic', 'true');
    UI.wakeRow.append(wake.row, UI.wakeChip, UI.wakeLive, mk('p', 'bfine', WAKE_LICENCE));
    UI.devSec.append(UI.wakeRow);
    // this month
    UI.useSec = section('This month', 'vUseT');
    UI.allow = mk('p', 'vallow'); UI.allow.id = 'vAllow';
    UI.allowFine = mk('p', 'bfine'); UI.allowFine.id = 'vAllowFine';
    UI.useSec.append(UI.allow, UI.allowFine);
    UI.slots = {};
    ['devices', 'phrases', 'pace'].forEach(name => { UI.slots[name] = mk('div', 'vslot'); UI.slots[name].id = 'vSlot' + name[0].toUpperCase() + name.slice(1); });
    box.append(UI.state, UI.status, UI.voiceSec, UI.rateSec, UI.witSec, UI.devSec, UI.slots.devices, UI.slots.phrases, UI.slots.pace, UI.useSec);
    S.built = true;
    emit('jarvis:voice-panel', { built: true });
  }
  const rateText = (r) => r.toFixed(2) + '×';

  /** A radio list, rebuilt only when its options change (a re-render must not move the focus or the
   *  ground under a click); otherwise only which one is checked is updated. */
  function radio(list, name, items, current, onPick, extra) {
    const key = JSON.stringify(items);
    if (list.dataset.key === key) {
      list.querySelectorAll('input.vin').forEach(inp => { inp.checked = inp.value === current; });
      return;
    }
    list.dataset.key = key;
    const keepFocus = list.contains(document.activeElement) ? document.activeElement.id : null;
    list.textContent = '';
    items.forEach((it, i) => {
      const row = mk('div', 'vopt');
      const id = `${name}-${i}`;
      const inp = mk('input', 'vin'); inp.type = 'radio'; inp.name = name; inp.id = id; inp.value = it.id;
      inp.checked = it.id === current;
      inp.addEventListener('change', () => { if (inp.checked) onPick(it.id); });
      const lab = mk('label', 'vlab'); lab.htmlFor = id;
      lab.append(mk('b', '', it.label));
      const sub = it.style || it.description; if (sub) lab.append(mk('small', '', sub));
      row.append(inp, lab);
      if (extra) row.append(extra(it, i));
      list.append(row);
    });
    if (keepFocus && $(keepFocus)) $(keepFocus).focus({ preventScroll: true });
  }
  function previewButton(v, i) {
    const b = mk('button', 'btn lift bact vprev'); b.type = 'button'; b.id = `vPrev-${i}`;
    b.setAttribute('aria-label', `Preview ${v.label}`);
    b.append(mk('span', 'vplay', '▶'), document.createTextNode(' Preview'));
    b.firstChild.setAttribute('aria-hidden', 'true');
    b.addEventListener('click', () => preview(v.id));
    return b;
  }
  function preview(id) {
    if (outputEngine() !== 'cloud') { flash('bad', 'Previews need the cloud voice, which isn\'t available right now.'); return; }
    speaker.stop();
    speaker.unlock();
    speaker.browser(false);
    const h = window.JarvisChat && typeof window.JarvisChat.honorific === 'function' ? window.JarvisChat.honorific() : 'Sir';
    speaker.say(`Good evening, ${h}. Systems are running smoothly.`, { preview: id });
    speaker.end();
  }

  function statusLines(cfg) {
    if (cfg === null) return [['', 'Not available in this setup: this server has no voice service yet. This browser\'s own voice and speech recognition still work where supported.']];
    if (!cfg) return [];
    const c = cfg.cloud, worst = [c.tts, c.stt].includes('unavailable') ? 'unavailable' : [c.tts, c.stt].includes('off') ? 'off' : 'ready';
    const downNow = Date.now() < S.down.tts || Date.now() < S.down.stt;
    if (worst === 'ready' && !downNow) return [['ok', 'Cloud voice ready: Google speech, in your own Google Cloud project.']];
    if (worst === 'ready') return [['warn', 'Google\'s voice service said no just now (busy, or this month\'s limit), so JARVIS uses this browser\'s voice. It tries the cloud again in about 10 minutes.']];
    if (worst === 'off') return [['', 'Cloud voice is switched off on this server (JARVIS_VOICE_CLOUD). JARVIS uses this browser\'s voice and speech recognition.']];
    if (c.reason === 'api_disabled') return [['warn', 'Google\'s speech services aren\'t switched on in your Google Cloud project yet, so JARVIS uses this browser\'s voice for now. To fix it, run this once in Cloud Shell:'], ['code', GCLOUD_FIX]];
    if (c.reason === 'not_configured') return [['warn', 'This server has no Google Cloud credentials for speech, so JARVIS uses this browser\'s voice. Deploying on Cloud Run with the jarvis-run account switches it on.']];
    return [['warn', 'Google\'s speech service isn\'t answering right now, so JARVIS uses this browser\'s voice. It tries again in about 10 minutes.']];
  }
  /** A free allowance of 0 (a shared billing account) means every character and minute is priced. */
  function allowanceText(a, inr) {
    const parts = [];
    if (a.chars !== null && a.freeChars !== null) {
      parts.push(a.freeChars > 0 ? `${count(a.chars)} of ${count(a.freeChars)} free characters` : `${count(a.chars)} characters, priced`);
    }
    if (a.seconds !== null && a.freeSeconds !== null) {
      const used = count(Math.ceil(a.seconds / 60));
      parts.push(a.freeSeconds > 0 ? `${used} of ${count(Math.floor(a.freeSeconds / 60))} free minutes` : `${used} minutes, priced`);
    }
    if (inr !== null) {
      const r = typeof Deck.rupees === 'function' ? Deck.rupees(inr) : '';
      if (r) parts.push(/^[≈<]/.test(r) ? r : '≈ ' + r);
    }
    return parts.length ? 'This month: ' + parts.join(' · ') : '';
  }
  function allowanceFine(a) {
    const est = 'Rupee figures are estimates.';
    if (a.freeChars === 0 || a.freeSeconds === 0) {
      return 'No free allowance is counted here (the Google billing account is shared), so voice use is priced. ' + est;
    }
    let when = '';
    if (a.resetsAt) {
      try { when = new Date(a.resetsAt).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'America/Los_Angeles' }); } catch (_) { when = ''; }
    }
    return 'The free allowance is this JARVIS\'s share of Google\'s, for the whole deployment' +
      (when && !/invalid/i.test(when) ? `; it resets on ${when} (Pacific time). ` : '. ') + est;
  }
  const WORDS = { cloud: 'Google Cloud', browser: 'this browser', none: 'not available here' };
  const WAKE_WORDS = { loading: 'Loading the wake word…', on: 'Listening for ‘Hey Jarvis’', paused: 'Paused while JARVIS speaks or listens',
    resume: 'Paused: tap anywhere on the page to resume ‘Hey Jarvis’', micoff: 'Off while the microphone is switched off', error: '' };

  function renderValues() {
    if (!S.built) return;
    const cfg = S.cfg, s = settings(), server = !!cfg;
    [UI.voiceSec, UI.rateSec, UI.witSec, UI.useSec].forEach(n => { n.hidden = !server; });
    if (server) {
      radio(UI.voiceList, 'vVoice', cfg.voices, s.voice, (id) => change({ voice: id }), previewButton);
      if (!cfg.voices.length) UI.voiceList.append(mk('p', 'bfine', 'No cloud voice is available right now.'));
      if (document.activeElement !== UI.rate) { UI.rate.value = String(s.rate); UI.rateOut.textContent = rateText(s.rate); UI.rate.setAttribute('aria-valuetext', rateText(s.rate)); }
      radio(UI.witList, 'vWit', cfg.wit, s.wit, (id) => change({ wit: id }));
      const allow = allowanceText(cfg.allowance, cfg.inr);
      UI.allow.textContent = allow; UI.useSec.hidden = !allow;
      UI.allowFine.textContent = allowanceFine(cfg.allowance);
    }
    UI.engine.value = device.engine; UI.finish.value = device.finish; UI.speak.value = device.speak;
    UI.engineHelp.textContent = `Now: ${WORDS[inputEngine()]}. Google Cloud keeps your audio in your own project (60 free minutes a month); this browser's recognition is free and shows your words as you speak, but your audio goes to the browser's maker.`;
    UI.speakHelp.textContent = `Out loud with ${WORDS[outputEngine()]}. "When I speak" answers spoken messages aloud; typed ones stay quiet.`;
    setPressed(UI.auto, device.autoSend); setPressed(UI.keep, device.keepListening); setPressed(UI.wake, device.wake);
    setPressed(UI.mic, !(window.JarvisAudio && window.JarvisAudio.locked()));
    setPressed(UI.checkIn, device.checkIn); setPressed(UI.cues, device.cues);
    UI.interrupt.value = device.interruptBy;
    pick(UI.follow, device.followUpS, ' seconds'); pick(UI.longPause, device.longPauseS, ' seconds'); pick(UI.endSilence, device.endSilenceMs, ' ms');
    const W = window.JarvisWake;
    UI.wakeRow.hidden = !(W && typeof W.supported === 'function' && safe(() => W.supported()));
    const ws = S.wake.state;
    UI.wakeChip.textContent = ws === 'error' ? S.wake.note || 'Couldn\'t start ‘Hey Jarvis’.' : WAKE_WORDS[ws] || '';
    UI.wakeChip.className = 'vchip' + (ws === 'on' ? ' on' : ws === 'error' ? ' bad' : '');
    UI.wakeChip.hidden = !UI.wakeChip.textContent;
  }
  /** Show a stored value that is not one of the listed options (the setting accepts a wider range). */
  function pick(sel, v, unit) {
    const key = String(v);
    if (!Array.from(sel.options).some(o => o.value === key)) { const o = mk('option', '', key + unit); o.value = key; sel.append(o); }
    sel.value = key;
  }
  const safe = (fn) => { try { return !!fn(); } catch (_) { return false; } };
  function render() {
    if (!box || !panel) return;
    const opened = !panel.hidden || S.built;
    if (!opened) return;
    if (!S.built) build();
    UI.state.textContent = '';
    if (S.cfg === undefined && !S.error) UI.state.append(mk('div', 'empty', S.loading ? 'Loading voice settings…' : 'Voice settings load when this panel opens.'));
    if (S.error) {
      const retry = mk('button', 'btn lift bact', 'Retry'); retry.type = 'button'; retry.id = 'voiceRetry';
      retry.disabled = Date.now() < S.retryAt;
      retry.addEventListener('click', () => { if (Date.now() < S.retryAt) return; S.error = ''; load(true); });
      UI.state.append(mk('p', 'bmiss warn', (S.cfg ? 'Couldn\'t refresh: showing what was loaded earlier. ' : 'Couldn\'t load voice settings. ') + S.error), retry);
    }
    UI.status.textContent = '';
    statusLines(S.cfg).forEach(([kind, text]) => {
      if (kind === 'code') { const c = mk('code', 'vfix', text); UI.status.append(c); return; }
      UI.status.append(mk('p', 'vline-s' + (kind ? ' ' + kind : ''), text));
    });
    UI.status.hidden = !UI.status.childElementCount;
    box.setAttribute('aria-busy', String(!!S.loading));
    if (metaEl) {
      const out = outputEngine();
      metaEl.textContent = S.cfg === null ? 'Not available' : S.cfg === undefined && !S.error ? '' : out === 'cloud' ? 'Cloud voice' : out === 'browser' ? 'Browser voice' : 'Typing only';
    }
    renderValues();
  }

  // ---- wiring ------------------------------------------------------------------------------------
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'voice' && d.open) { render(); load(false); } });
  /** The polite announcement for a wake-word state; 'paused' ↔ 'on' flips on every turn and is
   *  shown on the chip but not announced. */
  function announceWake() {
    const st = S.wake.state === 'paused' ? 'on' : S.wake.state;
    if (st === S.wakeSaid) return;
    S.wakeSaid = st;
    if (!UI.wakeLive) return;
    UI.wakeLive.textContent = st === 'error' ? S.wake.note || 'Couldn\'t start ‘Hey Jarvis’.' : st === 'off' ? '' : WAKE_WORDS[st] || '';
  }
  document.addEventListener('jarvis:mic-lock', renderValues);
  document.addEventListener('jarvis:wake', (e) => {
    const d = e.detail || {};
    S.wake = { state: typeof d.state === 'string' ? d.state : 'off', note: typeof d.note === 'string' ? d.note.slice(0, 200) : '' };
    if (d.state === 'error' && device.wake) setDevice({ wake: false }); else renderValues();
    announceWake();
  });
  function onReady() { if (device.speak === 'always' || device.wake) load(false); }
  document.addEventListener('jarvis:ready', onReady);
  const JC = window.JarvisConsole;
  const readyNow = JC && typeof JC.ready === 'function' ? JC.ready() : null;
  if (readyNow) onReady();

  window.JarvisVoice = Object.freeze({
    config: () => S.cfg,
    load: (force) => load(!!force),
    device: () => device,
    setDevice,
    settings,
    inputEngine,
    outputEngine,
    markDown,
    refusal,
    refused,
    language: () => (S.cfg ? S.cfg.language : 'en-IN'),
    speaker,
    visual: () => (visualFn ? visualFn() : null),
    setVisual(fn) { if (!visualFn && typeof fn === 'function') visualFn = fn; },
    panelSlot: (name) => (S.built && own(UI.slots, name) ? UI.slots[name] : null),
    updateSettings,
  });
})();
