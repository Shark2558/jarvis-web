// src/jarvis/api/static/console-calls-audio.js -- R18 E: the two sounds of the Calls panel, both through Web Audio
// (the console's CSP has no media-src, so no <audio> element is ever made; the Voice panel plays replies the same way).
//   listener()  Listen live: starts ONLY from a press (the browser's rule for sound), plays the binary 0x03 messages of
//               the live WebSocket (16 kHz PCM16 mono) through calls-listen-worklet.js; stop() closes the context.
//   player(host, path, seconds)  a recording's player: Play / Pause, a position slider (keyboard: arrows, Home, End)
//               and "0:42 / 3:10"; the bytes are fetched on the first Play only, decoded here, never kept.
// ASCII source; textContent only.
import { bytes, duration, failed, mk, button, uid } from './console-calls-api.js';

const WORKLET = '/static/calls-listen-worklet.js';
const NODE = 'jarvis-calls-listen';
const AC = () => window.AudioContext || window.webkitAudioContext || null;
export const canListen = () => !!(AC() && 'audioWorklet' in AC().prototype && typeof window.AudioWorkletNode === 'function');

export function listener() {
  const S = { ctx: null, node: null, starting: null };
  async function start() { // call from the press itself: the context is made before any await
    if (S.node) return true;
    if (S.starting) return S.starting;
    const C = AC();
    if (!canListen()) throw new Error('This browser can\u2019t play the call. Captions still show.');
    S.ctx = new C();
    const ctx = S.ctx;
    S.starting = (async () => {
      try {
        if (ctx.state === 'suspended') await ctx.resume();
        await ctx.audioWorklet.addModule(WORKLET);
        if (S.ctx !== ctx) return false; // stopped while it loaded
        S.node = new window.AudioWorkletNode(ctx, NODE, { numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [1] });
        S.node.connect(ctx.destination);
        return true;
      } catch (e) {
        stop();
        throw new Error('The call\u2019s sound couldn\u2019t start here. Captions still show.');
      } finally { S.starting = null; }
    })();
    return S.starting;
  }
  /** One binary message of the live socket: [0x03, PCM16 ...]. Anything else is dropped. */
  function feed(buf) {
    if (!S.node || !(buf instanceof ArrayBuffer) || buf.byteLength < 3) return;
    if (new Uint8Array(buf, 0, 1)[0] !== 0x03 || (buf.byteLength - 1) % 2) return;
    const pcm = buf.slice(1);
    S.node.port.postMessage(pcm, [pcm]);
  }
  function stop() {
    const ctx = S.ctx;
    S.ctx = null;
    if (S.node) { try { S.node.port.postMessage('flush'); S.node.disconnect(); } catch (_) { /* already gone */ } }
    S.node = null;
    if (ctx) ctx.close().catch(() => {});
  }
  return Object.freeze({ start, feed, stop, on: () => !!S.node });
}

export function player(host, path, seconds) {
  const S = { ctx: null, buf: null, src: null, at: 0, began: 0, timer: 0, loading: false };
  const box = mk('div', 'cl-player');
  box.setAttribute('role', 'group');
  const label = mk('span', 'sr-only', 'Recording');
  label.id = uid('clp');
  box.setAttribute('aria-labelledby', label.id);
  const play = button('Play', 'sact', toggle);
  const range = mk('input', 'cl-seek');
  range.type = 'range'; range.min = '0'; range.step = '1'; range.value = '0';
  range.max = String(Math.max(1, Math.round(seconds || 1)));
  range.setAttribute('aria-label', 'Position in the recording');
  const time = mk('span', 'cl-time', '0:00 / ' + duration(seconds));
  const note = mk('p', 'snote');
  note.setAttribute('role', 'status');
  box.append(label, play, range, time);
  host.append(box, note);
  const total = () => (S.buf ? S.buf.duration : seconds || 0);
  const now = () => (S.src ? Math.min(total(), S.at + (S.ctx.currentTime - S.began)) : S.at);
  function paint() {
    const t = now();
    range.max = String(Math.max(1, Math.round(total())));
    range.value = String(Math.round(t));
    range.setAttribute('aria-valuetext', duration(t) + ' of ' + duration(total()));
    time.textContent = duration(t) + ' / ' + duration(total());
    play.textContent = S.src ? 'Pause' : 'Play';
    play.setAttribute('aria-pressed', S.src ? 'true' : 'false');
  }
  async function load() {
    const C = AC();
    if (!C) throw new Error('This browser can\u2019t play recordings.');
    S.ctx = S.ctx || new C();
    if (S.ctx.state === 'suspended') await S.ctx.resume();
    if (!S.buf) {
      S.loading = true; play.disabled = true; note.textContent = 'Loading the recording\u2026';
      try { S.buf = await S.ctx.decodeAudioData(await bytes(path)); } finally { S.loading = false; play.disabled = false; }
      note.textContent = '';
    }
  }
  function begin() {
    const src = S.ctx.createBufferSource();
    src.buffer = S.buf;
    src.connect(S.ctx.destination);
    src.onended = () => { if (S.src !== src) return; S.src = null; S.at = 0; clearInterval(S.timer); paint(); };
    S.began = S.ctx.currentTime;
    src.start(0, Math.min(S.at, Math.max(0, S.buf.duration - 0.05)));
    S.src = src;
    clearInterval(S.timer);
    S.timer = setInterval(paint, 250);
  }
  function halt() {
    if (!S.src) return;
    S.at = now();
    const src = S.src; S.src = null;
    try { src.stop(); } catch (_) { /* ended */ }
    clearInterval(S.timer);
  }
  async function toggle() {
    if (S.loading) return;
    if (S.src) { halt(); paint(); return; }
    try { await load(); begin(); } catch (e) { note.textContent = failed(e); }
    paint();
  }
  range.addEventListener('input', () => {
    const playing = !!S.src;
    halt();
    S.at = Math.max(0, Math.min(total(), Number(range.value) || 0));
    if (playing && S.buf) begin();
    paint();
  });
  paint();
  return Object.freeze({ stop: () => { halt(); if (S.ctx) S.ctx.close().catch(() => {}); S.ctx = null; S.buf = null; paint(); }, el: box });
}
