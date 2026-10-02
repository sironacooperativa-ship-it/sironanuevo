const CACHE = 'sirona-public-v1';
const OFFLINE = '/static/pwa/offline.html';
self.addEventListener('install', event => { event.waitUntil(caches.open(CACHE).then(cache => cache.add(OFFLINE))); self.skipWaiting(); });
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('sirona-public-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim())));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
  } else if (url.pathname.startsWith('/static/')) {
    event.respondWith(caches.open(CACHE).then(async cache => {
      try { const response = await fetch(event.request); if (response.ok && response.type === 'basic') await cache.put(event.request, response.clone()); return response; }
      catch (error) { const saved = await cache.match(event.request); if (saved) return saved; throw error; }
    }));
  }
});
