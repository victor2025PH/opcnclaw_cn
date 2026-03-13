// OpenClaw Voice — Service Worker v2
// App shell caching + API response caching for offline support

const CACHE_NAME = 'openclaw-v2';
const API_CACHE = 'openclaw-api-v1';

const OFFLINE_URLS = [
  '/app',
  '/chat',
  '/manifest.json',
];

const CACHEABLE_API = [
  '/api/models',
  '/api/mcp/servers',
  '/api/mcp/tools',
  '/api/mcp/skills',
  '/api/desktop-skills',
  '/api/system/gpu',
  '/api/system/disk',
  '/api/models/summary',
  '/api/emotion/state',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(OFFLINE_URLS).catch(() => {});
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME && k !== API_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  if (event.request.method !== 'GET' || url.protocol === 'wss:' || url.protocol === 'ws:') {
    return;
  }

  // Cacheable GET API endpoints: network-first, fall back to cached
  if (CACHEABLE_API.some(p => url.pathname === p)) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(API_CACHE).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => caches.match(event.request).then((cached) => {
          if (cached) {
            const headers = new Headers(cached.headers);
            headers.set('X-OC-Cache', 'offline');
            return new Response(cached.body, { status: cached.status, statusText: cached.statusText, headers });
          }
          return new Response(JSON.stringify({ error: 'offline', cached: false }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          });
        }))
    );
    return;
  }

  // Skip non-cacheable API / POST requests
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) {
    return;
  }

  // App shell: network-first with cache fallback
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok && OFFLINE_URLS.some((u) => url.pathname === u || url.pathname.startsWith(u))) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request).then((cached) => {
          if (cached) return cached;
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

// Listen for cache-clear messages from the app
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'CLEAR_API_CACHE') {
    caches.delete(API_CACHE);
  }
});
