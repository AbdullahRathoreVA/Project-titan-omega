/**
 * Titan Omega service worker.
 *
 * Exists so the dashboard installs to a phone home screen — Android, iOS via
 * "Add to Home Screen", and Windows via Edge — without paying any store fee.
 * Apple charges $99/year for App Store distribution, which is roughly twice
 * this project's entire annual budget; a PWA costs nothing and, for a
 * dashboard, users cannot tell the difference.
 *
 * The caching strategy is deliberately conservative, because getting this
 * wrong is worse than having no service worker at all:
 *
 *  - API responses are NEVER cached. This dashboard's whole promise is that
 *    the numbers are real. Serving a cached /api/status would show yesterday's
 *    revenue as today's, which is exactly the kind of quiet lie the rest of the
 *    codebase goes out of its way to avoid.
 *
 *  - The HTML shell is network-first. Next.js chunk filenames are content
 *    hashed, so a cached index.html keeps pointing at OLD chunk names — the
 *    documented failure that made the HF Space serve a stale dashboard. Network
 *    first means a deploy is picked up immediately; the cache is only a
 *    fallback for being offline.
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
  // fixed bug actually reaches the user on next load.
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
