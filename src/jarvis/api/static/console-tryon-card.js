// src/jarvis/api/static/console-tryon-card.js -- R13.1 I0 STUB (docs/plans/r13-1-try-on.md D21, row 388), Part D's.
// When he asks what to wear, the reply carries ONE card of kind 'tryon' (ChatResponse.cards, made by outfit_suggest):
// {day, plan, code, slots: [{slot, pieces, private}]}. console-media.js hands every reply's cards to
// window.JarvisTryOnCard.cards(row, list); this module takes the 'tryon' one and, with no extra tap, has
// console-tryon.js draw the figure dressed in exactly those pieces under the reply (inline), or the AVT-15 checklist
// when 3D can't run. It reads only the card; console-tryon.js asks the server for the look. Loaded at start by
// console-r7.js. garment(file): a picture shared into the app (the share tray's "See it on me") opens Helpers ->
// Wardrobe -> Try it on's See it on me with it, for his type and colour and the device check; nothing is sent by it
// (D22). Until Part D builds it, nothing is drawn.
function cards(row, list) {
  if (!row || !Array.isArray(list)) return;
  const card = list.find((c) => c && typeof c === 'object' && c.kind === 'tryon');
  if (!card) return;
  void import('./console-tryon.js').then((m) => void m).catch(() => {});
}
async function garment(file) {
  if (!(file instanceof Blob)) return;
  const m = await import('./console-tryon.js');
  m.garment(file);
}
window.JarvisTryOnCard = Object.freeze({ cards, garment });
