// src/jarvis/api/static/console-sw.js -- R3 D11: the Web Push service worker. Two handlers only
// (push, notificationclick) and NO fetch handler, so it can never serve a stale console. It is
// registered with scope /static/push/, so it controls no page; push needs only the registration.
// The payload is {kind, text, url} (template text, <= 1 KB, never a picture). Anything else is
// ignored; the click target must be a path on this origin.
'use strict';

self.addEventListener('push', (event) => {
  let data = null;
  try { data = event.data ? event.data.json() : null; } catch (_) { data = null; }
  const ok = data && typeof data === 'object' && !Array.isArray(data);
  const text = ok && typeof data.text === 'string' ? data.text.slice(0, 300) : 'JARVIS has something for you.';
  const url = ok && typeof data.url === 'string' && /^\/(?!\/)[#A-Za-z0-9_\/-]*$/.test(data.url) ? data.url : '/';
  const kind = ok && typeof data.kind === 'string' ? data.kind.slice(0, 40) : 'alert';
  event.waitUntil(self.registration.showNotification('JARVIS', {
    body: text,
    tag: kind,
    data: { url },
    renotify: true,
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const d = event.notification.data;
  const target = d && typeof d.url === 'string' && d.url.charAt(0) === '/' && d.url.charAt(1) !== '/' ? d.url : '/';
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const w of wins) {
      if (new URL(w.url).origin === self.location.origin && 'focus' in w) {
        try { await w.focus(); if ('navigate' in w) await w.navigate(target); return; } catch (_) { /* open a new one */ }
      }
    }
    if (self.clients.openWindow) await self.clients.openWindow(target);
  })());
});
