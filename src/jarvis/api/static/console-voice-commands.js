// src/jarvis/api/static/console-voice-commands.js — R5 D12 (docs/plans/r5-voice.md): the local
// voice-command router. No build step; CSP script-src 'self'.
// It runs in the console BEFORE a spoken transcript reaches the chat, so "mic off", "stop" and
// "switch to my earphones" work with the AI off. Every action is local and reversible. Only spoken
// transcripts are routed: handle() refuses unless ctx.source === 'voice' (typed text, replies and
// anything from the server never get here).
//   window.JarvisVoiceCommands
//     register(id, {match(norm, raw) -> null | args, run(args, ctx) -> Result | Promise<Result>,
//                   states?: ['listening','standby','thinking','speaking']}) -> unregister()
//     handle(text, ctx)  ctx {source:'voice', state, spoken, peak} -> Promise<{handled, id?, result?}>
//                        Result = {say?, then?: 'listen'|'idle'|'keyboard'|'off'}
//     ask(question, {yes, no, timeoutMs = 8000}) -> Promise<'yes'|'no'|'timeout'|'cancelled'>
//     pending() -> the question being asked, or null; cancelAsk()
//     normalise(text), owns(text, state) -> id | null (a dry run), addressed(text) -> bool
//     exact(id) -> a match function for the PHRASES list of that id
//     PHRASES  frozen table, the same one tests/test_r5_seams.py parses.
// Matching order: answer.* (only while ask() is pending) -> mic.off -> speech.stop ->
// conversation.keyboard -> everything else in registration order. First match wins. Only the whole
// utterance is matched, and only when it is 8 words or fewer: "remind me to stop at the shop" is a
// chat message. Built-in matchers (mic.off, speech.stop, conversation.keyboard) belong to the
// listening loop; device commands to the devices module. Fires jarvis:voice-command {id, handled, state}.
(() => {
  'use strict';
  const MAX_WORDS = 8;
  const ASK_MS = 8000;
  const PRIORITY = ['mic.off', 'speech.stop', 'conversation.keyboard'];
  const ID = /^[a-z][a-z0-9._-]{0,63}$/;
  const STATES = ['listening', 'standby', 'thinking', 'speaking'];
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };

  // Written the way normalise() writes text, so a phrase can be compared as it stands. {device} is
  // a slot the devices module fills. "yes please" / "no thanks" are not listed: the trailing
  // "please" / "thanks" is dropped before matching.
  const PHRASES = deepFreeze(/*PHRASES-BEGIN*/{
    "answer.yes": ["yes", "yeah", "yep", "sure", "okay", "ok", "go ahead", "do it", "carry on", "keep listening"],
    "answer.no": ["no", "not now", "nope", "leave it"],
    "mic.off": ["mic off", "switch off mic", "switch off the mic", "switch mic off", "switch the mic off",
      "mute mic", "mute the mic", "mute yourself", "stop listening", "stop listening to me",
      "don't listen", "don't listen to me"],
    "speech.stop": ["stop", "stop it", "stop talking", "stop speaking", "stop there", "wait", "wait a moment",
      "hold on", "hang on", "one moment", "quiet", "be quiet", "enough", "that's enough", "pause", "shush",
      "cancel", "never mind", "forget it"],
    "conversation.keyboard": ["keyboard", "keyboard mode", "switch to keyboard", "switch to the keyboard",
      "i'll type", "let me type", "typing mode", "that's all", "that'll be all", "we're done",
      "end conversation", "end the conversation", "goodbye", "bye"],
    "device.switch": ["switch to {device}", "change to {device}", "use {device}", "move to {device}",
      "move the sound to {device}", "play it on {device}", "play on {device}", "speak through {device}"],
    "device.input": ["use {device} mic", "listen through {device}"],
    "device.list": ["what's connected", "which devices are connected", "list devices", "list my devices",
      "list sound devices", "list audio devices", "which speaker are you using"]
  }/*PHRASES-END*/);
  function deepFreeze(o) {
    Object.values(o).forEach(v => { if (v && typeof v === 'object') deepFreeze(v); });
    return Object.freeze(o);
  }

  // ---- normalise ---------------------------------------------------------------------------------
  const NAMES = new Set(['jarvis', 'jervis', "jarvis's", "jervis's"]);
  const LEAD_WORDS = new Set(['hey', 'ok', 'okay']);
  const SWAPS = { turn: 'switch', microphone: 'mic', mike: 'mic' };
  const TRAIL = [['thank', 'you'], ['please'], ['now'], ['sir'], ["ma'am"], ['thanks']];
  const LEAD = [['can', 'you'], ['could', 'you'], ['please']];
  const startsWith = (w, seq) => seq.every((x, i) => w[i] === x);
  const endsWith = (w, seq) => w.length >= seq.length && seq.every((x, i) => w[w.length - seq.length + i] === x);

  function words(text) {
    const t = String(text == null ? '' : text).normalize('NFKC').toLowerCase()
      .replace(/[‘’ʼ`]/g, "'")
      .replace(/[^\p{L}\p{N}'\s]/gu, ' ');
    return t.split(/\s+/).map(x => x.replace(/^'+|'+$/g, '')).filter(Boolean);
  }
  function dropName(w) {
    if (NAMES.has(w[0])) return w.slice(1);
    if (LEAD_WORDS.has(w[0]) && NAMES.has(w[1])) return w.slice(2);
    return w;
  }
  function honorific() {
    const c = window.JarvisChat;
    try { return String((c && typeof c.honorific === 'function' && c.honorific()) || '').toLowerCase(); } catch (_) { return ''; }
  }
  function strip(text) {
    let w = words(text), n;
    do {
      n = w.length;
      w = dropName(w);
      LEAD.forEach(seq => { if (startsWith(w, seq)) w = w.slice(seq.length); });
    } while (w.length !== n);
    const hon = honorific();
    do {
      n = w.length;
      TRAIL.forEach(seq => {
        if (endsWith(w, seq) && !(seq[0] === 'now' && w[w.length - 2] === 'not')) w = w.slice(0, w.length - seq.length); // "not now" stays
      });
      if (hon && w.length > 1 && w[w.length - 1] === hon) w = w.slice(0, -1);
    } while (w.length !== n);
    return w.map(x => SWAPS[x] || x);
  }
  const normalise = (text) => strip(text).join(' ');
  /** Does the utterance start with the name ("Jarvis, ...")? A name-mode check clip uses it. */
  function addressed(text) {
    const w = words(text);
    return w.length > 0 && dropName(w).length < w.length;
  }

  // ---- registry ----------------------------------------------------------------------------------
  const registry = [];                 // {id, spec}
  let asking = null;                   // {question, yes, no, timer, settle}

  function register(id, spec) {
    if (typeof id !== 'string' || !ID.test(id)) throw new Error('bad command id');
    if (!spec || typeof spec.match !== 'function' || typeof spec.run !== 'function') throw new Error('bad command');
    if (id.startsWith('answer.')) throw new Error('duplicate command id');
    const old = registry.findIndex(r => r.id === id);
    if (old >= 0 && !registry[old].builtin) throw new Error('duplicate command id');
    if (old >= 0) registry.splice(old, 1);          // a built-in matcher may be replaced once (tests do)
    const entry = { id, spec };
    registry.push(entry);
    return () => { const i = registry.indexOf(entry); if (i >= 0) registry.splice(i, 1); };
  }
  // ---- the built-in matchers (R5 workstream A) -------------------------------------------------------
  // They only decide WHAT was said; what to do belongs to the listening loop, which binds its actions
  // with bindLoop({micOff(ctx), stop(ctx), keyboard(ctx)}) -> Result.
  let loop = null;
  const act = (name) => (_, ctx) => (loop && typeof loop[name] === 'function' ? loop[name](ctx) : {});
  const BUILTIN = {
    'mic.off': { states: null, run: act('micOff') },
    'speech.stop': { states: ['speaking', 'thinking', 'listening', 'standby'], run: act('stop') },
    'conversation.keyboard': { states: null, run: act('keyboard') },
  };
  function exact(id) {
    const list = new Set(Array.isArray(PHRASES[id]) ? PHRASES[id] : []);
    return (norm) => (list.has(norm) ? {} : null);
  }
  function ordered() {
    const first = PRIORITY.map(id => registry.find(r => r.id === id)).filter(Boolean);
    return first.concat(registry.filter(r => !PRIORITY.includes(r.id)));
  }
  const hit = (v) => v !== null && v !== undefined && v !== false;
  function allowed(entry, state) {
    const s = entry.spec.states;
    return !Array.isArray(s) || s.length === 0 || s.includes(state);
  }
  /** The first command that owns this utterance: {id, args, entry?} or null. */
  function find(text, state) {
    if (state === 'off') return null;
    const w = strip(text);
    if (!w.length || w.length > MAX_WORDS) return null;
    const norm = w.join(' ');
    if (asking) {
      if (PHRASES['answer.yes'].includes(norm)) return { id: 'answer.yes', args: {} };
      if (PHRASES['answer.no'].includes(norm)) return { id: 'answer.no', args: {} };
    }
    for (const entry of ordered()) {
      if (!allowed(entry, state)) continue;
      let args = null;
      try { args = entry.spec.match(norm, String(text)); } catch (_) { args = null; } // a broken matcher is no match
      if (hit(args)) return { id: entry.id, args, entry };
    }
    return null;
  }
  const owns = (text, state) => { const f = find(text, state); return f ? f.id : null; };

  async function handle(text, ctx) {
    const none = { handled: false };
    if (!ctx || typeof ctx !== 'object' || ctx.source !== 'voice' || typeof text !== 'string') return none;
    const state = STATES.includes(ctx.state) ? ctx.state : String(ctx.state || '');
    const f = find(text, state);
    if (!f) return none;
    if (!f.entry) {
      const a = asking;
      settleAsk(f.id === 'answer.yes' ? 'yes' : 'no');
      if (a) { try { const cb = f.id === 'answer.yes' ? a.yes : a.no; if (typeof cb === 'function') cb(); } catch (_) {} }
      emit('jarvis:voice-command', { id: f.id, handled: true, state });
      return { handled: true, id: f.id };
    }
    let result = {};
    try {
      const r = await f.entry.spec.run(f.args, Object.assign({}, ctx, { state }));
      result = r && typeof r === 'object' ? r : {};
    } catch (_) { result = { error: 'failed' }; }
    emit('jarvis:voice-command', { id: f.id, handled: true, state });
    return { handled: true, id: f.id, result };
  }

  // ---- ask: one yes/no question -------------------------------------------------------------------
  function settleAsk(answer) {
    const a = asking;
    if (!a) return;
    asking = null;
    clearTimeout(a.timer);
    a.settle(answer);
  }
  /** The caller says the question aloud; this only listens for the answer. A newer question cancels
   *  the older one. Other words pass through to the normal commands while one is pending. */
  function ask(question, opts) {
    const o = opts && typeof opts === 'object' ? opts : {};
    const ms = typeof o.timeoutMs === 'number' && Number.isFinite(o.timeoutMs) ? Math.min(60000, Math.max(100, o.timeoutMs)) : ASK_MS;
    settleAsk('cancelled');
    return new Promise(resolve => {
      const a = { question: String(question == null ? '' : question).slice(0, 200), yes: o.yes, no: o.no, settle: resolve, timer: 0 };
      a.timer = setTimeout(() => { if (asking === a) settleAsk('timeout'); }, ms);
      asking = a;
    });
  }

  Object.keys(BUILTIN).forEach(id => {
    const un = register(id, { match: exact(id), run: BUILTIN[id].run, states: BUILTIN[id].states || undefined });
    registry.find(r => r.id === id).builtin = true;
    void un;
  });
  const bindLoop = (actions) => { loop = actions && typeof actions === 'object' ? actions : null; };

  window.JarvisVoiceCommands = Object.freeze({
    register, handle, bindLoop, ask, normalise, owns, addressed, exact, PHRASES,
    pending: () => (asking ? asking.question : null),
    cancelAsk: () => settleAsk('cancelled'),
  });
})();
