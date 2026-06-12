// Minimal service worker: enables install (PWA) and offline app shell.
// Network-first for navigations/assets so the dashboard stays fresh online and
// still opens offline from cache. API (POST, /api/) is never intercepted.
const CACHE = "ia-shell-v2";
const IS_DEV_SERVER = self.location.port === "5173";

async function clearAllCaches() {
  const keys = await caches.keys();
  await Promise.all(keys.map((key) => caches.delete(key)));
}

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      if (IS_DEV_SERVER) {
        await clearAllCaches();
        await self.registration.unregister();
        return;
      }
      const keys = await caches.keys();
      await Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  if (IS_DEV_SERVER) return;
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  event.respondWith(
    (async () => {
      try {
        const res = await fetch(req);
        const cache = await caches.open(CACHE);
        cache.put(req, res.clone()).catch(() => {});
        return res;
      } catch {
        const cached = await caches.match(req);
        return cached || (await caches.match("/")) || Response.error();
      }
    })(),
  );
});
