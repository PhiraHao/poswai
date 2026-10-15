const CACHE_NAME = 'pos-wai-offline-v14';
const ASSETS = [
  "/",
  "/index.html",
  "/line_pos_prototype.html",
  "/ui.css",
  "/workspace.css?v=14",
  "/sales-redesign.css?v=14",
  "/ops-redesign.css?v=14",
  "/people-redesign.css?v=14",
  "/workspace.js?v=14",
  "/sales-redesign.js?v=14",
  "/ops-redesign.js?v=14",
  "/people-redesign.js?v=14",
  "/icons.svg",
  "/manifest.json",
  "/icon-192.png",
  "/icon-512.png",
  "/assets/fonts.css",
  "/assets/food-icon.svg",
  "/assets/drink-icon.svg",
  "/assets/dessert-icon.svg",
  "/assets/menu-placeholder.svg",
  "/assets/noto-thai-0.ttf",
  "/assets/noto-thai-1.ttf",
  "/assets/noto-thai-2.ttf",
  "/assets/noto-thai-3.ttf"
];

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
    fetch(event.request).catch(() => caches.match(event.request, { ignoreSearch: true }).then(res => res || (event.request.mode === 'navigate' ? caches.match('/index.html') : Response.error())))
  );
});
