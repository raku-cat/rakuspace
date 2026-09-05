// Install-only service worker - no caching, just enough (install/activate,
// a no-op fetch handler) for Chrome/Android to consider the site
// installable as a PWA.
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// A no-op fetch handler. Some browsers' install criteria look for a
// registered fetch handler, not just install/activate; this doesn't cache
// or intercept anything, it just lets the default network response through.
self.addEventListener("fetch", () => {});
