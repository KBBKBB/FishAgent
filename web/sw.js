'use strict';

// Bump CACHE_VERSION whenever a precached shell asset changes.
var CACHE_VERSION = 'fishagent-v10';
var STATIC_CACHE = CACHE_VERSION + '-static';
var PRECACHE_URLS = [
  '/',
  '/index.html',
  '/styles.css',
  '/app.js',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-192.png',
  '/icons/icon-maskable-512.png',
  '/icons/apple-touch-icon-180.png'
];
var OFFLINE_API_MESSAGE = '当前处于离线状态，无法获取实时数据；请恢复网络后重试。';

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then(function (cache) {
        return cache.addAll(PRECACHE_URLS);
      })
      // Take over immediately. Without this the new worker waits for every old
      // tab to close, and because static assets below are cache-first a phone
      // that never fully closes the page keeps serving the previous app.js.
      .then(function () {
        return self.skipWaiting();
      })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches
      .keys()
      .then(function (keys) {
        return Promise.all(
          keys
            .filter(function (key) {
              return key !== STATIC_CACHE;
            })
            .map(function (key) {
              return caches.delete(key);
            })
        );
      })
      .then(function () {
        return self.clients.claim();
      })
  );
});

function offlineApiResponse() {
  return new Response(JSON.stringify({ detail: OFFLINE_API_MESSAGE }), {
    status: 503,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store'
    }
  });
}

function offlineDocumentResponse() {
  return new Response(
    '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">' +
      '<meta name="viewport" content="width=device-width, initial-scale=1">' +
      '<title>FishAgent 离线</title></head>' +
      '<body style="margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;' +
      'padding:24px;font-family:system-ui,sans-serif;background:#f3f0e7;color:#17231e">' +
      '<main style="max-width:420px"><h1 style="font-size:20px;margin:0 0 10px">当前处于离线状态</h1>' +
      '<p style="margin:0;color:#5a6a63;line-height:1.7">FishAgent 暂时无法连接网络，' +
      '请恢复网络后重试。本页不会显示缓存的鱼情或钓位数据。</p></main></body></html>',
    {
      status: 503,
      headers: {
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-store'
      }
    }
  );
}

function handleNavigation(request) {
  return fetch(request)
    .then(function (response) {
      if (response && response.ok) {
        var copy = response.clone();
        caches.open(STATIC_CACHE).then(function (cache) {
          cache.put('/index.html', copy);
        });
      }
      return response;
    })
    .catch(function () {
      return caches.match('/index.html').then(function (cached) {
        return cached || offlineDocumentResponse();
      });
    });
}

function handleStatic(request) {
  // Stale-while-revalidate: serve the cached copy immediately for speed, then
  // refresh it in the background. Pure cache-first meant a cached app.js was
  // never re-fetched, so a new deployment could not reach an installed client
  // even after CACHE_VERSION was bumped.
  return caches.match(request).then(function (cached) {
    var network = fetch(request)
      .then(function (response) {
        if (response && response.ok && response.type === 'basic') {
          var copy = response.clone();
          caches.open(STATIC_CACHE).then(function (cache) {
            cache.put(request, copy);
          });
        }
        return response;
      })
      .catch(function () {
        return cached || new Response('', { status: 504, statusText: 'Offline' });
      });
    return cached || network;
  });
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET') return;

  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.indexOf('/api/') === 0) {
    event.respondWith(fetch(request).catch(offlineApiResponse));
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(handleNavigation(request));
    return;
  }

  event.respondWith(handleStatic(request));
});
