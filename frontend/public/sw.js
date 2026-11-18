/**
 * A deliberately small service worker.
 *
 * It does one thing: keep the application shell available offline so that opening the app on
 * a train shows the interface and a clear "cannot reach the server" message rather than the
 * browser's error page.
 *
 * **It never caches the news.** News that is silently hours stale is worse than news that is
 * honestly absent, because a stale list is indistinguishable from a fresh one.
 *
 * That rule was written in this comment from the first version and not actually implemented.
 * The exclusion list covered `/api` and `/health` - the endpoints of a backend the deployed
 * site does not use - and said nothing about `data/articles.json`, which is where the news
 * lives in the static build. So the data fell through to the cache-first branch below, was
 * stored on first visit, and was served from cache forever after. On a phone that had opened
 * the site once, the headlines stopped changing: ten hours old while the desktop showed ten
 * minutes. The exclusion now covers the data, and the cache name is bumped so that every
 * install already carrying a stale copy discards it on the next visit.
 */

const SHELL_CACHE = 'newsreader-shell-v4'

// Everything here is relative to wherever this worker is served from, because that is not
// always the domain root: a GitHub Pages project site lives at /<repo>/. This file is in
// public/ so it is copied verbatim and cannot read Vite's BASE_URL - but a worker knows its
// own location, and `./` resolves against it.
const SCOPE = new URL('./', self.location.href)
const url = (path) => new URL(path, SCOPE).pathname

// The icons are in the shell because the installed app shows them on its splash screen,
// which is exactly when the network is most likely to be missing.
const SHELL_ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon.svg',
  './icon-192.png',
  './icon-512.png',
].map(
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
  // Never cache the news, in either data mode. See the module comment - getting this list
  // wrong is what made a phone show ten-hour-old headlines.
  const path = requestUrl.pathname
  if (
    path.startsWith(url('data/')) || // the static snapshot: this is the news
    path.startsWith(url('api')) || // the REST backend, when VITE_DATA_MODE=api
    path === url('health')
  ) {
    return
  }

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
