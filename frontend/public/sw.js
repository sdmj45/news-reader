/**
 * A deliberately small service worker.
 *
 * It does one thing: keep the application shell available offline so that opening the app on
 * a train shows the interface and a clear "cannot reach the server" message rather than the
 * browser's error page.
 *
 * It does **not** cache API responses. News that is silently hours stale is worse than news
 * that is honestly absent, and a cached article list would be indistinguishable from a fresh
 * one. Every /api request goes to the network and fails visibly when it cannot.
 */

const SHELL_CACHE = 'newsreader-shell-v2'

// Everything here is relative to wherever this worker is served from, because that is not
// always the domain root: a GitHub Pages project site lives at /<repo>/. This file is in
// public/ so it is copied verbatim and cannot read Vite's BASE_URL - but a worker knows its
// own location, and `./` resolves against it.
const SCOPE = new URL('./', self.location.href)
const url = (path) => new URL(path, SCOPE).pathname

const SHELL_ASSETS = ['./', './index.html', './manifest.webmanifest', './icon.svg'].map(
  (path) => new URL(path, SCOPE).href,
)
const INDEX = new URL('./index.html', SCOPE).href

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      // A missing asset must not leave the previous worker stuck in "installing".
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== SHELL_CACHE).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const requestUrl = new URL(request.url)
  if (requestUrl.origin !== self.location.origin) return
  // Never cache data. See the module comment.
  const path = requestUrl.pathname
  if (path.startsWith(url('api')) || path === url('health')) return

  // Navigations: network first, shell from cache when offline.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match(INDEX).then((r) => r ?? Response.error())),
    )
    return
  }

  // Built assets are content-hashed, so a cache hit is always correct.
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ??
        fetch(request).then((response) => {
          if (response.ok && response.type === 'basic') {
            const copy = response.clone()
            void caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy))
          }
          return response
        }),
    ),
  )
})
