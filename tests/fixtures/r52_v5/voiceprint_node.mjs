// tests/fixtures/r52_v5/voiceprint_node.mjs -- R5.2 V5 (row 84): the speaker check's arithmetic outside a browser.
//   node voiceprint_node.mjs <repo root> <request.json>   -> one JSON line on stdout
// Requests (tests/test_r52_v5_voiceprint.py):
//   {"cmd": "fbank", "pcm": [int16...], "window": "hamming"}  -> {frames, data}   features after CMN
//   {"cmd": "voices", "model": <path to an ONNX file>, "threshold": t, "enrol": [seed...], "probe": [[speaker, seed, s]...]}
//        the console's own pipeline (console-voiceprint-math.js features -> the model on the vendored onnxruntime-web
//        -> unit -> buildPrint -> cosine -> verdict) on synthetic voices (voices.js): the owner's print from 3 s
//        pieces of a 60 s reading, then each probe's score and verdict -> {print: {count, selfMean, selfMin}, probes}
// ASCII only. Synthetic audio only.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const [root, requestPath] = process.argv.slice(2);
const STATIC = root + '/src/jarvis/api/static';
globalThis.window = globalThis;
vm.runInThisContext(readFileSync(STATIC + '/console-voiceprint-math.js', 'utf8'));
vm.runInThisContext(readFileSync(root + '/tests/fixtures/r52_v5/voices.js', 'utf8'));
const M = globalThis.JarvisVoicePrintMath, V = globalThis.JarvisTestVoices;
const req = JSON.parse(readFileSync(requestPath, 'utf8'));

async function session(path) {
  const ort = await import(STATIC + '/vendor/ort/ort.wasm.min.mjs');
  ort.env.wasm.numThreads = 1; ort.env.wasm.proxy = false; ort.env.wasm.wasmPaths = STATIC + '/vendor/ort/';
  const s = await ort.InferenceSession.create(readFileSync(path), { executionProviders: ['wasm'], logSeverityLevel: 3 });
  return async (pcm) => {
    const f = M.features(pcm, { window: 'hamming' });
    if (!f) return null;
    const out = await s.run({ [s.inputNames[0]]: new ort.Tensor('float32', f.data, f.dims) });
    return M.unit(out[s.outputNames[0]].data);
  };
}

async function main() {
  if (req.cmd === 'fbank') {
    const f = M.cmn(M.fbank(Int16Array.from(req.pcm), { window: req.window }));
    return { frames: f.frames, data: Array.from(f.data) };
  }
  if (req.cmd === 'voices') {
    const embed = await session(req.model);
    const embeddings = [];
    for (const seed of req.enrol) {
      for (const piece of M.segments(V.utter('owner', 60, seed))) embeddings.push(await embed(piece));
    }
    const print = M.buildPrint(embeddings);
    const probes = [];
    for (const [speaker, seed, seconds] of req.probe) {
      const pcm = M.join(V.frames(V.utter(speaker, seconds, seed)));
      const e = await embed(pcm), voiced = M.voicedMs(pcm), score = e ? M.cosine(e, print.vector) : 0;
      probes.push({ speaker, seed, seconds, voiced, score, verdict: M.verdict(score, voiced, req.threshold) });
    }
    return { print: { count: print.count, selfMean: print.selfMean, selfMin: print.selfMin, dims: print.vector.length }, probes };
  }
  throw new Error('unknown cmd');
}
process.stdout.write(JSON.stringify(await main()) + '\n');
