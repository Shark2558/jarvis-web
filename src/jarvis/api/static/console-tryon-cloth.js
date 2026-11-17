// src/jarvis/api/static/console-tryon-cloth.js -- R13.1 Part B (docs/plans/r13-1-try-on.md D5, D6, D9): what the
// figure wears and what its cloth looks like. Imported by console-tryon-3d.js only.
//   plan(look, opts)   which of the mannequin's parts are drawn for a look, in the order base layer -> main -> outer
//                      -> socks -> shoes -> belt -> watch, with each part's colour, crop and state. THE PRIVATE ZONE
//                      (D6): the base shorts are in EVERY plan, the base vest whenever no top is drawn, and a private
//                      slot ({slot, private: true}) is never read beyond that flag: it is covered, never drawn.
//   photoCloth(id)     his own crop (the door's read-only thumb(), a data: URL decoded with an Image: connect-src
//                      'self' refuses a fetch of it): the centre 40 % square mirror-tiled 2 x 2 on our own 512 px canvas.
//   weave(rgb, word)   a plain woven, striped, checked or dotted cloth drawn on our own canvas (no image file).
//   picture(...)       "Save a picture of this look": the figure's canvas and D's caption lines on one new canvas.
// A drawing module (tests/test_r13_seams.py DRAWING): canvas calls only on canvases made here; nothing is fetched,
// stored or sent; the door's senders are never called.
const TOPS = ['shirt', 'tee', 'kurta'], TUCKS = ['shirt', 'tee'], BELTED = ['trousers', 'shorts'];
const LAYERS = ['all', 'no_outer', 'base'];
const GREY = [128, 128, 128]; // no colour set: mid-grey
const TEMPLATES = Object.freeze({
  shirt: { place: 'top', parts: [['shirt', 'cloth'], ['shirtButtons', 'button']], state: 'tuck', tile: 0.22 },
  tee: { place: 'top', parts: [['tee', 'cloth']], state: 'tuck', tile: 0.22 },
  kurta: { place: 'top', parts: [['kurta', 'cloth']], tile: 0.22 },
  trousers: { place: 'bottom', parts: [['trousers', 'cloth']], tile: 0.25 },
  shorts: { place: 'bottom', parts: [['shortsG', 'cloth']], tile: 0.25 },
  wrap: { place: 'bottom', parts: [['wrap', 'cloth']], tile: 0.25 },
  jacket: { place: 'outer', parts: [['jacket', 'cloth']], state: 'open', tile: 0.25 },
  socks: { place: 'socks', parts: [['socks', 'plain']] },
  shoe: { place: 'feet', parts: [['shoes', 'leather'], ['soles', 'sole']] },
  sandal: { place: 'feet', parts: [['sandals', 'leather']] },
  belt: { place: 'belt', parts: [['belt', 'leather'], ['buckle', 'steel']] },
  watch: { place: 'watch', parts: [['watchStrap', 'leather'], ['watchCase', 'steel']] },
});
const ORDER = ['top', 'bottom', 'outer', 'socks', 'feet', 'belt', 'watch'];
const flag = (v, fallback) => (typeof v === 'boolean' ? v : fallback);
const rgbOf = (v) => (Array.isArray(v) && v.length === 3 && v.every((c) => Number.isFinite(c) && c >= 0 && c <= 255) ? v.map(Math.round) : null);
const PHOTO = /^wh_[0-9a-f]{12}$/;

/** The look's pieces by place; a second piece for a place, or one without a template, is an image card. */
function picked(look) {
  const by = {}, cards = [];
  let covered = false;
  for (const s of (look && Array.isArray(look.slots) ? look.slots : [])) {
    if (!s || typeof s.slot !== 'string') continue;
    if (s.private === true) { covered = true; continue; } // nothing else of a private slot is read
    const t = TEMPLATES[s.template];
    if (!t || by[t.place]) cards.push(s.slot); else by[t.place] = s;
  }
  return { by, cards, covered };
}

/** What is drawn for a look. Returns { parts, drawn, approx, cards, hidden, covered, state }. */
function plan(look, opts) {
  const o = opts || {}, layers = LAYERS.includes(o.layers) ? o.layers : 'all';
  const { by, cards, covered } = picked(look);
  const on = (place) => (layers === 'base' || (layers === 'no_outer' && place === 'outer') ? null : by[place] || null);
  const top = on('top'), bottom = on('bottom'), outer = on('outer');
  // a wrap is tied over the shirt's tail: the one shape of a wrap has no room for a top worn out over it
  const tucked = !!(top && bottom && TUCKS.includes(top.template) && (bottom.template === 'wrap' || flag(o.tucked, top.variant === 'tucked')));
  const open = !!(outer && flag(o.open, outer.variant !== 'closed'));
  const belted = !!(bottom && BELTED.includes(bottom.template) && (!top || tucked));
  const parts = [], drawn = [], approx = {}, hidden = [];
  const body = (name, shown) => { if (shown) parts.push({ name, slot: null, kind: 'body', weights: {} }); };
  body('bodyCore', true);
  body('bodyArms', !(outer || (top && top.template !== 'tee')));
  body('bodyShoulders', !top); // under a jacket alone the chest still shows in its V
  body('bodyShins', !(bottom && bottom.template === 'trousers'));
  body('bodyThighs', !(bottom && BELTED.includes(bottom.template)));
  body('bodyFeet', !(on('socks') || (on('feet') && on('feet').template === 'shoe')));
  parts.push({ name: 'baseShorts', slot: null, kind: 'base', weights: {} }); // ALWAYS (D6)
  if (!top) parts.push({ name: 'vest', slot: null, kind: 'base', weights: {} });
  for (const place of ORDER) {
    const s = by[place];
    if (!s) continue;
    if (!on(place) || (place === 'belt' && !belted)) { hidden.push(s.slot); continue; }
    const t = TEMPLATES[s.template], rgb = rgbOf(s.rgb), photo = PHOTO.test(String(s.photo || '')) ? s.photo : null;
    const weights = t.state === 'tuck' ? { tuck: tucked ? 1 : 0 } : t.state === 'open' ? { open: open ? 1 : 0 } : {};
    for (const [name, kind] of t.parts) {
      parts.push({ name, slot: s.slot, kind, weights, rgb: rgb || GREY, pattern: typeof s.pattern === 'string' ? s.pattern : null,
        photo: kind === 'cloth' ? photo : null, tile: t.tile || 0 });
    }
    drawn.push(s.slot);
    approx[s.slot] = ['template', ...(rgb ? [] : ['colour']), ...(photo && t.tile ? ['texture'] : [])];
  }
  return { parts, drawn, approx, cards, hidden, covered, state: { tucked, open, layers } };
}

function board(size) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  return c;
}

/** His crop as cloth: a 512 px canvas, or null when it can't be read (the piece is then its colour only). */
async function photoCloth(id) {
  const door = window.JarvisMobile && window.JarvisMobile.parts && window.JarvisMobile.parts.send;
  if (!door || typeof door.thumb !== 'function' || !PHOTO.test(String(id || ''))) return null;
  try {
    const url = await door.thumb(id);
    if (typeof url !== 'string' || !url.startsWith('data:image/')) return null;
    const img = new Image();
    await new Promise((ok, no) => { img.onload = ok; img.onerror = no; img.src = url; });
    const side = Math.min(img.naturalWidth, img.naturalHeight) * 0.4;
    if (!(side >= 8)) return null;
    const c = board(512), g = c.getContext('2d'), sx = (img.naturalWidth - side) / 2, sy = (img.naturalHeight - side) / 2;
    for (const [fx, fy] of [[0, 0], [1, 0], [0, 1], [1, 1]]) { // mirrored 2 x 2, so the tile's edges always meet
      g.setTransform(fx ? -1 : 1, 0, 0, fy ? -1 : 1, fx ? 512 : 0, fy ? 512 : 0);
      g.drawImage(img, sx, sy, side, side, 0, 0, 256, 256);
    }
    return c;
  } catch (_) { return null; }
}

/** A drawn cloth for a colour and a pattern word; `tile` (m) is the size of the canvas on the garment. */
function weave(rgb, word) {
  const c = board(128), g = c.getContext('2d'), [r, gr, b] = rgb;
  const lum = (0.2126 * r + 0.7152 * gr + 0.0722 * b) / 255;
  const dark = 'rgba(0,0,0,' + (lum > 0.5 ? 0.16 : 0.3) + ')', light = 'rgba(255,255,255,' + (lum > 0.5 ? 0.3 : 0.12) + ')';
  const line = (x0, y0, x1, y1, colour, w) => { g.strokeStyle = colour; g.lineWidth = w; g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke(); };
  g.fillStyle = 'rgb(' + r + ',' + gr + ',' + b + ')';
  g.fillRect(0, 0, 128, 128);
  for (let i = 0; i < 128; i += 8) { line(0, i + 1, 128, i + 1, light, 1); line(i + 5, 0, i + 5, 128, dark, 1); }
  let tile = 0.04;
  if (word === 'striped') { tile = 0.05; for (const at of [16, 80]) line(at, 0, at, 128, light, 10); line(48, 0, 48, 128, dark, 4); }
  if (word === 'checked') { tile = 0.07; for (const at of [20, 84]) { line(0, at, 128, at, dark, 14); line(at, 0, at, 128, dark, 14); } line(0, 52, 128, 52, light, 3); line(52, 0, 52, 128, light, 3); }
  if (word === 'dotted') { tile = 0.05; g.fillStyle = light; for (const [x, y] of [[32, 32], [96, 96]]) { g.beginPath(); g.arc(x, y, 9, 0, 6.3); g.fill(); } }
  if (word === 'printed' || word === 'textured') { for (let i = 0; i < 40; i++) { g.fillStyle = i % 2 ? light : dark; g.fillRect((i * 37) % 128, (i * 59) % 128, 5, 3); } }
  return { canvas: c, tile };
}

/** The soft shadow under the feet. */
function contact() {
  const c = board(128), g = c.getContext('2d'), grad = g.createRadialGradient(64, 64, 4, 64, 64, 62);
  grad.addColorStop(0, 'rgba(0,0,0,.5)'); grad.addColorStop(0.55, 'rgba(0,0,0,.2)'); grad.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
  return c;
}

/** The figure's canvas with the caption lines beneath it on ONE new canvas, as a PNG Blob (D9). `style` is
 *  {bg, ink, font}: the console's own colours and font, read by the engine. Only the lines given are written. */
function picture(source, lines, style) {
  const text = (Array.isArray(lines) ? lines : []).filter((l) => typeof l === 'string').slice(0, 12).map((l) => l.slice(0, 120));
  const w = source.width, scale = Math.max(1, w / 480), size = Math.round(14 * scale), gap = Math.round(size * 1.5), pad = Math.round(16 * scale);
  const c = document.createElement('canvas');
  c.width = w; c.height = source.height + (text.length ? pad + text.length * gap : 0);
  const g = c.getContext('2d');
  g.fillStyle = style.bg; g.fillRect(0, 0, c.width, c.height);
  g.drawImage(source, 0, 0);
  g.fillStyle = style.ink; g.font = size + 'px ' + style.font; g.textBaseline = 'top';
  text.forEach((l, i) => g.fillText(l, pad, source.height + pad / 2 + i * gap, w - 2 * pad));
  return new Promise((ok, no) => c.toBlob((b) => (b ? ok(b) : no(new Error('The picture could not be made.'))), 'image/png'));
}

export { plan, photoCloth, weave, contact, picture, TEMPLATES, LAYERS };
