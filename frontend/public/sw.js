/**
 * Titan Omega service worker.
 *
 * Lets the dashboard install to a phone home screen (Android, iOS via "Add to
 * Home Screen", Windows via Edge) without an app store. For a dashboard, a PWA
 * is indistinguishable from a native app and costs nothing.
 *
 * Caching is deliberately conservative, since getting it wrong is worse than
 * having no service worker:
 *
 *  - API responses are never cached. A cached /api/status would show
 *    yesterday's numbers as today's.
 *
 *  - The HTML shell is network-first. Next.js chunk filenames are content
 *    hashed, so a cached index.html keeps pointing at old chunk names and
 *    serves a stale dashboard. Network-first picks up a deploy immediately;
 *    the cache is only an offline fallback.
 *
 *  - Hashed static assets are cache-first. Their names change when their
 *    contents change, so they can never go stale.
 *
 *  - /api/stream (Server-Sent Events) is passed straight through. Intercepting
 *    a streaming response in a service worker is a reliable way to break it.
 */

const VERSION = "titan-v1";
const SHELL = `${VERSION}-shell`;
const ASSETS = `${VERSION}-assets`;

self.addEventListener("install", (event) => {
  // Take over immediately rather than waiting for every tab to close, so a
  // fix reaches the user on the next load.
  self.skipWaiting();
  event.waitUntil(
    caches.open(SHELL).then((c) => c.addAll(["/", "/manifest.webmanifest"]))
      .catch(() => {/* offline at install time is not fatal */}),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)),
      ),
    ).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never touch the API, and never touch the live stream.
  if (url.pathname.startsWith("/api/")) return;

  // Content-hashed build output: safe to serve from cache forever.
  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(
      caches.match(request).then((hit) =>
        hit ||
        fetch(request).then((res) => {
          const copy = res.clone();
          caches.open(ASSETS).then((c) => c.put(request, copy));
          return res;
        }),
      ),
    );
    return;
  }

  // Everything else (the HTML shell): network first, cache as offline fallback.
  event.respondWith(
    fetch(request)
      .then((res) => {
        const copy = res.clone();
        caches.open(SHELL).then((c) => c.put(request, copy));
        return res;
      })
      .catch(() =>
        caches.match(request).then((hit) => hit || caches.match("/")),
      ),
  );
});
