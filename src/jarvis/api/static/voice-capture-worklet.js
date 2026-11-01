// src/jarvis/api/static/voice-capture-worklet.js — slice 9 D4: the one capture pipeline.
// AudioWorkletProcessor (loaded by console-voice-capture.js with audioWorklet.addModule, CSP
// script-src 'self'). Takes the microphone at the context's own rate (44.1 / 48 kHz, mono after the
// node's explicit down-mix), low-passes it below 8 kHz (windowed-sinc FIR, Hamming, unity DC gain)
// so nothing above the new Nyquist folds back as noise, resamples to 16 kHz by linear interpolation
// at a fractional step, and posts Int16 frames of exactly 1280 samples (80 ms) to the page. The
// buffers are transferred, never shared. Nothing here stores audio or talks to the network.
const OUT_RATE = 16000;
const FRAME = 1280;
const CUTOFF_HZ = 7000;   // pass speech up to ~6 kHz; well down by 8 kHz (the 16 kHz Nyquist)
const TAPS = 63;          // odd: a centred, linear-phase filter

function lowPass(rate) {
  const fc = CUTOFF_HZ / rate, mid = (TAPS - 1) / 2, h = new Float32Array(TAPS);
  let sum = 0;
  for (let i = 0; i < TAPS; i++) {
    const n = i - mid;
    const sinc = n === 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * n) / (Math.PI * n);
    const w = 0.54 - 0.46 * Math.cos((2 * Math.PI * i) / (TAPS - 1));
    h[i] = sinc * w; sum += h[i];
  }
  for (let i = 0; i < TAPS; i++) h[i] /= sum;
  return h;
}

class JarvisCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / OUT_RATE;          // input samples per output sample (2.75625 at 44.1 kHz)
    this.filter = this.step > 1.001 ? lowPass(sampleRate) : null;
    this.ring = new Float32Array(TAPS);          // the last TAPS input samples, circular
    this.pos = 0;
    this.prev = 0;                               // filtered sample just before the current one
    this.t = 0;                                  // next output position, in input samples from `prev`
    this.out = new Int16Array(FRAME);
    this.n = 0;
    this.port.onmessage = (e) => { if (e.data === 'flush') this.flush(); };
  }

  filtered(x) {
    if (!this.filter) return x;
    const r = this.ring, h = this.filter;
    r[this.pos] = x;
    let acc = 0, k = this.pos;
    for (let i = 0; i < TAPS; i++) { acc += h[i] * r[k]; k = k === 0 ? TAPS - 1 : k - 1; }
    this.pos = this.pos === TAPS - 1 ? 0 : this.pos + 1;
    return acc;
  }

  emit(v) {
    const s = v >= 1 ? 32767 : v <= -1 ? -32768 : Math.round(v * 32767);
    this.out[this.n++] = s;
    if (this.n === FRAME) {
      const frame = this.out;
      this.out = new Int16Array(FRAME);
      this.n = 0;
      this.port.postMessage(frame, [frame.buffer]);
    }
  }

  /** Drop a partial frame: the page asked for a clean start (a new listening turn). */
  flush() { this.n = 0; }

  process(inputs) {
    const input = inputs[0];
    const ch = input && input[0];
    if (!ch) return true; // no source connected yet (or it ended): keep the node alive
    for (let i = 0; i < ch.length; i++) {
      const cur = this.filtered(ch[i]);
      // output samples that fall between `prev` (position 0) and `cur` (position 1)
      while (this.t <= 1) {
        this.emit(this.prev + (cur - this.prev) * this.t);
        this.t += this.step;
      }
      this.t -= 1;
      this.prev = cur;
    }
    return true;
  }
}

registerProcessor('jarvis-capture', JarvisCapture);
