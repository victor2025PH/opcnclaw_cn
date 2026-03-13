// OpenClaw Voice — Service Worker
// Provides offline caching for the app shell

const CACHE_NAME = 'openclaw-v1';
const OFFLINE_URLS = [
  '/app',
  '/chat',
  '/manifest.json',
];

// Install: pre-cache app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(OFFLINE_URLS).catch(() => {
        // Silently ignore cache failures (e.g. server not running during SW install)
      });
    })
  );
  self.skipWaiting();
});

// Activate: clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// Fetch: network-first for API/WS, cache-first for app shell
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Skip non-GET, WebSocket, and API requests — let them pass through
  if (
    event.request.method !== 'GET' ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/ws') ||
    url.protocol === 'wss:' ||
    url.protocol === 'ws:'
  ) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Cache successful responses for app pages
        if (response.ok && OFFLINE_URLS.some((u) => url.pathname === u || url.pathname.startsWith(u))) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        // Network failed — serve from cache
        return caches.match(event.request).then((cached) => {
          if (cached) return cached;
          // Last resort offline page
          return new Response(
            '<!DOCTYPE html><html><head><meta charset="utf-8"><title>OpenClaw 离线</title></head>' +
            '<body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f0f10;color:#fff">' +
            '<h1>📡 无网络连接</h1><p>请连接到 OpenClaw 服务器所在的局域网后重试。</p>' +
            '<button onclick="location.reload()" style="padding:12px 24px;background:#6366f1;color:#fff;border:none;border-radius:8px;font-size:16px;cursor:pointer">重试</button>' +
            '</body></html>',
            { headers: { 'Content-Type': 'text/html;charset=utf-8' } }
          );
        });
      })
  );
});
