const CACHE_NAME = 'pos-wai-offline-v11';
const ASSETS = ['/', '/index.html', '/line_pos_prototype.html', '/ui.css', '/icons.svg', '/manifest.json', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(Promise.all([
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)))),
    self.clients.claim()
  ]));
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || new URL(event.request.url).pathname.startsWith('/api/')) return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request).then(res => res || (event.request.mode === 'navigate' ? caches.match('/index.html') : Response.error())))
  );
});
