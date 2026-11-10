// src/jarvis/api/static/console-book-scenes-flow.js -- R6 D15: scenes 3, 5, 6, 8 (one conversation turn, confirm before commit,
// voice, on its own).
// ES module imported by console-book-3d.js. All facts come from book.show; none are hard-coded.
// One flow per scene: its facts are the steps, in order, as nodes along a gentle arc; a packet travels the path to the step
// a beat lights (its focus, else one step a beat) and the path behind it glows. A fact's `group` may ask for an accent:
// 'gateway' or 'guard' -> a shield ring, 'audit' -> chain links, 'passkey' -> the passkey ring the approval card meets
// (scene 5), and scene 6 opens with a waveform driven by the narration, scene 8 with a clock ring. Without hints: plain nodes.
// Builders take the engine's kit and return {root, labels, reset(full), enter(beatIndex, lit), update(t, dt, level)}.
// No build step; CSP script-src 'self'; ASCII source; <= 400 lines.
const MAX_STEPS = 12;
const ease = (x) => 1 - Math.pow(1 - Math.max(0, Math.min(1, x)), 3);
const words = (f, max) => { const s = f.label || f.value; return s.length > max ? s.slice(0, max - 1) + '\u2026' : s; };

/** Points of the path: left to right on a shallow arc (two rows when there are many steps). */
function layout(n) {
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const u = n > 1 ? i / (n - 1) : 0.5;
    out.push([-5.3 + 10.6 * u, -0.35 + 1.25 * Math.sin(Math.PI * u) - (n > 8 && i % 2 ? 0.9 : 0), 0]);
  }
  return out;
}
function segmentsAlong(pts) {
  const p = [];
  for (let i = 0; i + 1 < pts.length; i += 1) p.push(...pts[i], ...pts[i + 1]);
  return p;
}

/** The shared flow: nodes, the path, the travelled path, a packet; returns hooks for the decorations. */
function flow(k, decorate) {
  const { THREE, K } = k, root = new THREE.Group(), labels = [], nodes = [];
  const facts = k.facts.slice(0, MAX_STEPS), pts = layout(facts.length);
  const octa = K.geo(new THREE.OctahedronGeometry(0.34, 0)), octaEdges = K.geo(new THREE.EdgesGeometry(octa));
  const path = new THREE.LineSegments(K.positions(segmentsAlong(pts)), K.line('soft'));
  const trail = new THREE.LineSegments(K.positions(segmentsAlong(pts)), K.line('lit'));
  trail.geometry.setDrawRange(0, 0); root.add(path, trail);
  facts.forEach((f, i) => {
    const g = new THREE.Group(), edge = K.line('line'), fill = K.mesh('bold', 'fill');
    g.add(new THREE.LineSegments(octaEdges, edge), new THREE.Mesh(octa, fill));
    g.position.set(...pts[i]); root.add(g); nodes.push({ g, edge, fill, f });
    labels.push({ text: words(f, 28), obj: g, at: new THREE.Vector3(0, i % 2 ? -0.82 : 0.82, 0), key: i });
  });
  const packet = new THREE.Sprite(K.sprite('lit')); packet.scale.setScalar(0.9); root.add(packet);
  const st = { from: 0, to: 0, u: 1, spin: 0 };
  const posAt = (x) => {
    if (!pts.length) return [0, 0, 0];
    const i = Math.max(0, Math.min(pts.length - 1, Math.floor(x))), j = Math.min(pts.length - 1, i + 1), r = x - i;
    return pts[i].map((v, c) => v + (pts[j][c] - v) * r);
  };
  const hooks = { root, nodes, pts, packet, st, labels, K, THREE, k, extra: [] };
  if (decorate) decorate(hooks);
  function place(x) {
    packet.position.set(...posAt(x));
    trail.geometry.setDrawRange(0, Math.max(0, Math.round(x * 2)));
  }
  return {
    root, labels,
    reset() { st.from = 0; st.to = 0; st.u = 1; place(0); },
    enter(i, lit) {
      const target = lit.size ? Math.min(...lit) : 0;
      st.from = st.u >= 1 ? st.to : st.from + (st.to - st.from) * ease(st.u); st.to = target; st.u = k.motion() ? 0 : 1;
      nodes.forEach((n, j) => { const on = lit.has(j); K.setRole(n.edge, on ? 'lit' : 'line'); K.setRole(n.fill, 'bold', on ? 'litfill' : 'fill'); n.on = on; });
      hooks.extra.forEach((x) => x.enter && x.enter(i, lit));
      place(st.u >= 1 ? st.to : st.from);
    },
    update(t, dt, lv) {
      st.u = dt > 0 ? Math.min(1, st.u + dt / 0.9) : 1; // a still: the packet where the beat puts it
      place(st.from + (st.to - st.from) * ease(st.u));
      nodes.forEach((n) => { if (dt > 0) n.g.rotation.y += dt * (n.on ? 1.4 : 0.25); n.g.scale.setScalar(n.on ? 1.3 : 1); });
      packet.scale.setScalar(0.8 + 0.5 * lv);
      hooks.extra.forEach((x) => x.update && x.update(t, dt, lv));
    },
  };
}

// ---- accents a fact's group can ask for ------------------------------------------------------------
function ring(h, at, r, ticks, role) {
  const { THREE, K } = h, g = new THREE.Group();
  g.add(new THREE.LineLoop(K.circle(r, 72), K.line(role || 'line')));
  if (ticks) g.add(new THREE.LineSegments(K.ticks(r + 0.04, ticks, 0.12), K.line('soft')));
  g.position.set(...at); h.root.add(g);
  return g;
}
function groupAccents(h) {
  h.nodes.forEach((n, i) => {
    const grp = (n.f.group || '').toLowerCase();
    if (grp === 'gateway' || grp === 'guard') {
      const shield = ring(h, h.pts[i], 0.72, 24, 'bold');
      h.extra.push({ update(t, dt) { if (dt > 0) shield.rotation.z += dt * 0.5; } });
    } else if (grp === 'audit') {
      for (let c = 0; c < 3; c += 1) { const link = ring(h, [h.pts[i][0] + (c - 1) * 0.36, h.pts[i][1] - 0.62, 0], 0.17, 0, 'soft'); link.scale.y = 0.6; }
    }
  });
}

// ---- 3 \u00b7 One conversation turn --------------------------------------------------------------------
function turn(k) { return flow(k, groupAccents); }

// ---- 5 \u00b7 Confirm before commit: the approval card travels to the passkey ring ------------------------
function confirm(k) {
  return flow(k, (h) => {
    groupAccents(h);
    const { THREE, K } = h;
    const ringAt = h.nodes.findIndex((n) => (n.f.group || '').toLowerCase() === 'passkey');
    const end = ringAt >= 0 ? ringAt : h.nodes.length - 1;
    if (end < 0) return;
    const key = ring(h, h.pts[end], 0.8, 36, 'bold');
    const card = new THREE.Group(), w = 1.15, c = 0.72;
    card.add(new THREE.LineSegments(K.positions([-w / 2, -c / 2, 0, w / 2, -c / 2, 0, w / 2, -c / 2, 0, w / 2, c / 2, 0, w / 2, c / 2, 0, -w / 2, c / 2, 0, -w / 2, c / 2, 0, -w / 2, -c / 2, 0,
      -0.38, 0.12, 0, 0.38, 0.12, 0, -0.38, -0.08, 0, 0.2, -0.08, 0]), K.line('amber')));
    h.root.add(card);
    const st = { x: 0, want: 0 };
    h.extra.push({
      enter(i, lit) { st.want = lit.size ? Math.min(Math.max(...lit), end) : 0; if (!k.motion()) st.x = st.want; },
      update(t, dt) {
        if (dt > 0) { st.x += (st.want - st.x) * Math.min(1, dt * 2.5); key.rotation.z += dt * (st.x >= end - 0.05 ? 1.6 : 0.2); } else st.x = st.want;
        const i = Math.floor(st.x), j = Math.min(h.pts.length - 1, i + 1), r = st.x - i;
        card.position.set(h.pts[i][0] + (h.pts[j][0] - h.pts[i][0]) * r, h.pts[i][1] + (h.pts[j][1] - h.pts[i][1]) * r + 1.45, 0.2);
      },
    });
  });
}

// ---- 6 \u00b7 Voice: a waveform driven by the narration opens the chain --------------------------------
function voice(k) {
  return flow(k, (h) => {
    groupAccents(h);
    const { THREE, K } = h, N = 72, pos = new Float32Array(N * 3);
    const geo = K.geo(new THREE.BufferGeometry()); geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const wave = new THREE.Line(geo, K.line('lit'));
    const x0 = (h.pts[0] ? h.pts[0][0] : -5.3), y0 = (h.pts[0] ? h.pts[0][1] : 0) - 1.45;
    wave.position.set(x0 - 0.6, y0, 0); h.root.add(wave);
    const draw = (t, lv) => {
      for (let i = 0; i < N; i += 1) {
        const u = i / (N - 1), a = (0.12 + 0.55 * lv) * Math.sin(u * Math.PI);
        pos[i * 3] = u * 3.2; pos[i * 3 + 1] = a * Math.sin(u * 26 + t * 7) * Math.cos(u * 9 - t * 3); pos[i * 3 + 2] = 0;
      }
      geo.attributes.position.needsUpdate = true;
    };
    draw(0, 0);
    h.extra.push({ update(t, dt, lv) { if (dt > 0 || t === 0) draw(t, lv); } });
  });
}

// ---- 8 \u00b7 On its own: a clock ring at the first step (the tick that starts it) ------------------------
function own(k) {
  return flow(k, (h) => {
    groupAccents(h);
    if (!h.pts.length) return;
    const { THREE, K } = h;
    const clock = ring(h, h.pts[0], 0.95, 12, 'bold');
    const hand = new THREE.LineSegments(K.positions([0, 0, 0, 0, 0.78, 0]), K.line('lit'));
    clock.add(hand);
    h.extra.push({ update(t, dt) { if (dt > 0) hand.rotation.z -= dt * 1.1; } });
  });
}

export const SCENES = Object.freeze({ 3: turn, 5: confirm, 6: voice, 8: own });
