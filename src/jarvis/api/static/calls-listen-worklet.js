// src/jarvis/api/static/calls-listen-worklet.js -- R18 E (BUILD-BRIEF.md "Audio format everywhere"): the
// AudioWorkletProcessor that plays a live call in the Calls panel. console-calls-audio.js posts each binary 0x03
// message's PCM (16 kHz, mono, signed 16-bit little-endian, the leading byte already removed) to this port; it is
// resampled to the device's own rate (linear), kept at most MAX_LAG_S behind (older audio is dropped, never sped up)
// and primed with PRIME_S before it starts again after a gap, so a slow network plays silence, not crackle.
// Loaded with audioWorklet.addModule under CSP script-src 'self'. No build step; ASCII source.
const IN_RATE = 16000;
const CAP = 65536; // ring size in input samples (4 s), a power of two
const MASK = CAP - 1;
const MAX_LAG_S = 1.0;
const KEEP_S = 0.3; // after a jump ahead, this much is kept to play
const PRIME_S = 0.12;
const MAX_POST = 64 * 1024; // bytes in one message at most

class JarvisCallsListen extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ring = new Float32Array(CAP);
    this.w = 0; // samples written, in total
    this.r = 0; // read position, in input samples (fractional)
    this.step = IN_RATE / sampleRate;
    this.playing = false;
    this.port.onmessage = (e) => this.push(e.data);
  }

  push(data) {
    if (data === 'flush') { this.r = this.w; this.playing = false; return; }
    if (!(data instanceof ArrayBuffer) || data.byteLength < 2 || data.byteLength > MAX_POST) return;
    const view = new DataView(data), n = data.byteLength >> 1;
    for (let i = 0; i < n; i += 1) {
      this.ring[this.w & MASK] = view.getInt16(i * 2, true) / 32768;
      this.w += 1;
    }
    if (this.w - this.r > MAX_LAG_S * IN_RATE) this.r = this.w - KEEP_S * IN_RATE; // too far behind: drop the oldest
  }

  process(_inputs, outputs) {
    const out = outputs[0];
    if (!out || !out.length) return true;
    const ch = out[0];
    if (!this.playing && this.w - this.r >= PRIME_S * IN_RATE) this.playing = true;
    for (let i = 0; i < ch.length; i += 1) {
      if (!this.playing || this.r + 1 >= this.w) { ch[i] = 0; this.playing = false; continue; }
      const i0 = Math.floor(this.r), f = this.r - i0;
      const a = this.ring[i0 & MASK], b = this.ring[(i0 + 1) & MASK];
      ch[i] = a + (b - a) * f;
      this.r += this.step;
    }
    for (let c = 1; c < out.length; c += 1) out[c].set(ch);
    return true;
  }
}

registerProcessor('jarvis-calls-listen', JarvisCallsListen);
