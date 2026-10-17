const CACHE_NAME = 'pos-wai-offline-v84';
const ASSETS = [
  "/",
  "/index.html",
  "/ui.css",
  "/workspace.css?v=45",
  "/sales-redesign.css?v=49",
  "/ops-redesign.css?v=19",
  "/people-redesign.css?v=19",
  "/staff-admin.css?v=38",
  "/staff-dossier.css?v=39",
  "/reports-restore.css?v=19",
  "/reports-live.css?v=20",
  "/service-call.css?v=77",
  "/auth-ui.css?v=51",
  "/payment-ui.css?v=21",
  "/billing-ui.css?v=49",
  "/workspace.js?v=46",
  "/sales-redesign.js?v=49",
  "/ops-redesign.js?v=19",
  "/people-redesign.js?v=38",
  "/staff-admin.js?v=59",
  "/staff-dossier.js?v=59",
  "/reports-restore.js?v=19",
  "/reports-live.js?v=31",
  "/service-call.js?v=77",
  "/auth-ui.js?v=84",
  "/landing.css?v=42",
  "/landing.js?v=43",
  "/assets/landing/prompt.css",
  "/assets/landing/logo.webp",
  "/assets/landing/hero-bg.webp",
  "/assets/landing/hero-mascot.webp",
  "/assets/landing/badge-icon.webp",
  "/assets/landing/swoosh.webp",
  "/assets/landing/feat-fast.webp",
  "/assets/landing/feat-chef.webp",
  "/assets/landing/feat-chart.webp",
  "/assets/landing/card-pos.webp",
  "/assets/landing/card-kitchen.webp",
  "/assets/landing/card-sales.webp",
  "/assets/landing/tile-order.webp",
  "/assets/landing/tile-staff.webp",
  "/assets/landing/tile-sales.webp",
  "/assets/landing/prompt-400-thai.woff2",
  "/assets/landing/prompt-400-latin.woff2",
  "/assets/landing/prompt-500-thai.woff2",
  "/assets/landing/prompt-500-latin.woff2",
  "/assets/landing/prompt-600-thai.woff2",
  "/assets/landing/prompt-600-latin.woff2",
  "/assets/landing/prompt-700-thai.woff2",
  "/assets/landing/prompt-700-latin.woff2",
  "/assets/landing/prompt-800-thai.woff2",
  "/assets/landing/prompt-800-latin.woff2",
  "/payment-ui.js?v=21",
  "/billing-ui.js?v=49",
  "/qr.js?v=72",
  "/live-data.js?v=72",
  "/tables-ui.js?v=77",
  "/inventory-live.js?v=23",
  "/commerce-ui.css?v=29",
  "/commerce-ui.js?v=30",
  "/cashier-void.js?v=72",
  "/icons.svg",
  "/manifest.json",
  "/icon-192.png",
  "/icon-512.png",
  "/assets/brand-logo.webp",
  "/assets/brand-mark.webp",
  "/assets/mascot-pos.webp",
  "/assets/mascot-wave.webp",
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
