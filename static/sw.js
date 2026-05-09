/* =============================================
   PMU Smart Analyzer — Service Worker v1
   Stratégie :
   - Assets statiques  → Cache-first (toujours rapide)
   - Appels API        → Network-first avec fallback cache
   ============================================= */

const CACHE_STATIC  = "pmu-static-v4";
const CACHE_API     = "pmu-api-v2";

const STATIC_ASSETS = [
  "/",
  "/static/index.html",
  "/static/css/style.css",
  "/static/js/auth.js",
  "/static/js/api.js",
  "/static/js/components.js",
  "/static/js/bets.js",
  "/static/js/app.js",
  "/static/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

const API_CACHE_PATHS = [
  "/api/dashboard",
  "/api/courses",
  "/api/stats",
  "/api/stats/scoring",
  "/api/stats/calibration",
  "/api/reunions",
];

// ---- Install : précache des assets statiques ----
self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_STATIC).then(function (cache) {
      return Promise.allSettled(
        STATIC_ASSETS.map(function (url) {
          return cache.add(url).catch(function (err) {
            console.warn("[SW] Impossible de cacher " + url + " :", err);
          });
        })
      );
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

// ---- Activate : nettoie les anciens caches ----
self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (key) {
          return key !== CACHE_STATIC && key !== CACHE_API;
        }).map(function (key) {
          console.log("[SW] Suppression ancien cache :", key);
          return caches.delete(key);
        })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

// ---- Fetch : stratégie selon le type de requête ----
self.addEventListener("fetch", function (event) {
  const url = new URL(event.request.url);

  // Ignorer les requêtes non-GET et les requêtes cross-origin
  if (event.request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;

  // API POST (refresh, bets...) → réseau direct, pas de cache
  const isApiPost = url.pathname.startsWith("/api/") && event.request.method === "POST";
  if (isApiPost) return;

  // Endpoints API à mettre en cache → Network-first
  const isApiCacheable = API_CACHE_PATHS.some(function (p) {
    return url.pathname === p || url.pathname.startsWith(p + "/");
  });

  if (isApiCacheable) {
    event.respondWith(networkFirstWithCache(event.request));
    return;
  }

  // Assets statiques → Cache-first
  if (url.pathname.startsWith("/static/") || url.pathname === "/") {
    event.respondWith(cacheFirstWithNetwork(event.request));
    return;
  }
});

/* Network-first : essaie le réseau, si échec sert le cache */
function networkFirstWithCache(request) {
  return fetch(request).then(function (response) {
    if (response.ok) {
      const clone = response.clone();
      caches.open(CACHE_API).then(function (cache) {
        cache.put(request, clone);
      });
    }
    return response;
  }).catch(function () {
    return caches.match(request).then(function (cached) {
      if (cached) {
        console.log("[SW] Offline — données cachées servies pour", request.url);
        return cached;
      }
      // Réponse vide JSON pour éviter une erreur bloquante
      return new Response(JSON.stringify({ offline: true, error: "Hors ligne" }), {
        headers: { "Content-Type": "application/json" },
        status: 503,
      });
    });
  });
}

/* Cache-first : sert depuis le cache, met à jour en arrière-plan */
function cacheFirstWithNetwork(request) {
  return caches.match(request).then(function (cached) {
    const networkFetch = fetch(request).then(function (response) {
      if (response.ok) {
        caches.open(CACHE_STATIC).then(function (cache) {
          cache.put(request, response.clone());
        });
      }
      return response;
    }).catch(function () { return null; });

    return cached || networkFetch;
  });
}
