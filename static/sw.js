/* =============================================
   PMU Smart Analyzer — Service Worker v6
   Stratégies :
     - CACHE-FIRST (stale-while-revalidate) pour les assets statiques
       (.css, .js, .png, .ico, .webmanifest, fonts)
     - NETWORK-FIRST pour les appels API (/api/)
     - Page offline.html pré-cachée pour les navigations sans réseau
   ============================================= */

const CACHE_STATIC_V  = "pmu-static-v11";
const CACHE_API_V     = "pmu-api-v7";

const STATIC_ASSETS = [
  "/",
  "/static/index.html",
  "/static/offline.html",
  "/static/css/style.css",
  "/static/js/auth.js",
  "/static/js/api.js",
  "/static/js/components.js",
  "/static/js/bets.js",
  "/static/js/app.js",
  "/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

// Extensions d'assets statiques éligibles au cache-first
const STATIC_EXTS = /\.(css|js|png|ico|webmanifest|woff2?|ttf|eot|svg)(\?.*)?$/i;

// Paths API mis en cache (network-first)
const API_CACHE_PATHS = [
  "/api/dashboard",
  "/api/courses",
  "/api/stats",
  "/api/stats/scoring",
  "/api/stats/calibration",
  "/api/reunions",
];

// ---- Install : précache des assets statiques + offline.html ----
self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_STATIC_V).then(function (cache) {
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
          return key !== CACHE_STATIC_V && key !== CACHE_API_V;
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

// ---- Message : force skipWaiting depuis la page ----
self.addEventListener("message", function (event) {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

// ---- Fetch ----
self.addEventListener("fetch", function (event) {
  const url = new URL(event.request.url);

  // Ignorer les requêtes non-GET et cross-origin
  if (event.request.method !== "GET") return;
  if (url.origin !== self.location.origin) return;

  // ----- API calls → Network-first -----
  if (url.pathname.startsWith("/api/")) {
    const isCacheable = API_CACHE_PATHS.some(function (p) {
      return url.pathname === p || url.pathname.startsWith(p + "/");
    });
    if (isCacheable) {
      event.respondWith(networkFirstApi(event.request));
    }
    // Appels API non listés (ex: POST, non-cacheable) → réseau direct, pas de respondWith
    return;
  }

  // ----- Assets statiques → Cache-first (stale-while-revalidate) -----
  if (STATIC_EXTS.test(url.pathname) || url.pathname === "/" || url.pathname.startsWith("/static/")) {
    event.respondWith(cacheFirstSWR(event.request));
    return;
  }

  // ----- Navigation (HTML) sans asset connu → Network-first + offline fallback -----
  if (event.request.mode === "navigate") {
    event.respondWith(navigationWithOfflineFallback(event.request));
    return;
  }
});

/* -------------------------------------------------------
   CACHE-FIRST avec stale-while-revalidate
   1. Retourne le cache immédiatement si disponible
   2. Lance un fetch en arrière-plan pour mettre à jour le cache
   3. Si pas de cache, fait le fetch et met en cache
------------------------------------------------------- */
function cacheFirstSWR(request) {
  return caches.open(CACHE_STATIC_V).then(function (cache) {
    return cache.match(request).then(function (cached) {
      // Refresh en arrière-plan (stale-while-revalidate)
      var networkUpdate = fetch(request).then(function (response) {
        if (response && response.ok) {
          cache.put(request, response.clone());
        }
        return response;
      }).catch(function () { return null; });

      // Servir depuis le cache immédiatement, ou attendre le réseau si pas de cache
      return cached || networkUpdate;
    });
  });
}

/* -------------------------------------------------------
   NETWORK-FIRST pour les appels API
   Essaie le réseau, sert le cache si hors ligne
------------------------------------------------------- */
function networkFirstApi(request) {
  return fetch(request).then(function (response) {
    if (response && response.ok) {
      caches.open(CACHE_API_V).then(function (cache) {
        cache.put(request, response.clone());
      });
    }
    return response;
  }).catch(function () {
    return caches.match(request).then(function (cached) {
      if (cached) {
        console.log("[SW] Offline — données API cachées pour", request.url);
        return cached;
      }
      return new Response(JSON.stringify({ offline: true, error: "Hors ligne" }), {
        headers: { "Content-Type": "application/json" },
        status: 503,
      });
    });
  });
}

/* -------------------------------------------------------
   NAVIGATION avec fallback offline.html
   Network-first, si échec → cache, si rien → offline.html
------------------------------------------------------- */
function navigationWithOfflineFallback(request) {
  return fetch(request).then(function (response) {
    if (response && response.ok) {
      caches.open(CACHE_STATIC_V).then(function (cache) {
        cache.put(request, response.clone());
      });
    }
    return response;
  }).catch(function () {
    return caches.match(request).then(function (cached) {
      if (cached) return cached;
      return caches.match("/static/offline.html").then(function (offlinePage) {
        return offlinePage || new Response("Vous êtes hors ligne.", {
          headers: { "Content-Type": "text/plain" },
          status: 503,
        });
      });
    });
  });
}
