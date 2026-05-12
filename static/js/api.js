/* API wrapper — PMU Smart Analyzer v2 */
const BASE = "";

// ---- Cache mémoire TTL 60s pour les GET ----
var _cache = {};
var _CACHE_TTL = 60000; // 60 secondes

async function cachedFetch(path) {
  var now = Date.now();
  var entry = _cache[path];
  if (entry && (now - entry.ts) < _CACHE_TTL) {
    return entry.data;
  }
  var data = await apiFetch(path);
  _cache[path] = { data: data, ts: Date.now() };
  return data;
}

function clearCache() {
  _cache = {};
}

function clearCacheForResults() {
  var keysToDelete = Object.keys(_cache).filter(function(k) {
    return k.startsWith("/api/reunions") ||
           k.startsWith("/api/bilan") ||
           k.startsWith("/api/dashboard") ||
           k.startsWith("/api/stats");
  });
  keysToDelete.forEach(function(k) { delete _cache[k]; });
}

async function apiFetch(path, options) {
  options = options || {};
  // Inject auth token into every request
  var token = window.Auth && window.Auth.getToken ? window.Auth.getToken() : null;
  if (token) {
    options.headers = options.headers || {};
    options.headers["Authorization"] = "Bearer " + token;
  }
  // Timeout via AbortController (45s — couvre les cold starts Render free tier ~30s)
  var controller = new AbortController();
  var timeoutId = setTimeout(function () { controller.abort(); }, 45000);
  options.signal = controller.signal;
  try {
    const res = await fetch(BASE + path, options);
    if (res.status === 401) {
      // Token expired / invalid → show login screen
      if (window.Auth && window.Auth.showLoginScreen) {
        window.Auth.showLoginScreen("Session expirée. Reconnectez-vous.");
      }
      throw new Error("HTTP 401");
    }
    if (!res.ok) throw new Error("HTTP " + res.status);
    return await res.json();
  } catch (e) {
    if (e.name === "AbortError") {
      var timeoutErr = new Error("Délai de connexion dépassé");
      console.error("API error [" + path + "]:", timeoutErr);
      throw timeoutErr;
    }
    console.error("API error [" + path + "]:", e);
    throw e;
  } finally {
    clearTimeout(timeoutId);
  }
}

const API = {
  // ---- Existants ----
  dashboard:  function () { return cachedFetch("/api/dashboard"); },
  reunions:   function () { return cachedFetch("/api/reunions"); },
  course:     function (id) { return apiFetch("/api/courses/" + id); },
  stats:      function () { return cachedFetch("/api/stats"); },
  refresh:          function () { clearCache(); return apiFetch("/api/refresh", { method: "POST" }); },
  refreshProgramme: function () { return apiFetch("/api/refresh-programme", { method: "POST" }); },

  // ---- F3 : Suggestions combos ----
  courseSuggestions: function (id) { return apiFetch("/api/courses/" + id + "/suggestions"); },

  // ---- F3 : Paris ----
  getBets: function (statut) {
    const qs = statut ? "?statut=" + encodeURIComponent(statut) : "";
    return apiFetch("/api/bets" + qs);
  },
  createBet: function (payload) {
    return apiFetch("/api/bets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  deleteBet: function (id) {
    return apiFetch("/api/bets/" + id, { method: "DELETE" });
  },
  refreshResults: function () {
    clearCacheForResults();
    return apiFetch("/api/bets/refresh-results", { method: "POST" });
  },

  // ---- F2 : Scoring ----
  scoringAccuracy: function () { return apiFetch("/api/scoring/accuracy"); },
  scoringAccuracyByDiscipline: function () { return apiFetch("/api/scoring/accuracy-by-discipline"); },
  scoringAccuracyTrend: function () { return apiFetch("/api/scoring/accuracy-trend"); },
  scoringDisciplineStats: function () { return apiFetch("/api/scoring/discipline-stats"); },
  scoringOptimize: function () { return apiFetch("/api/scoring/optimize", { method: "POST" }); },

  // ---- Stats avancées + Calibration ----
  statsScoring:     function () { return cachedFetch("/api/stats/scoring"); },
  statsCalibration: function () { return cachedFetch("/api/stats/calibration"); },
  calibrate:        function () { return apiFetch("/api/calibrate", { method: "POST" }); },

  // ---- Bilan backtesting ----
  bilan: function (periode, discipline) { return cachedFetch("/api/bilan?periode=" + (periode || "all") + "&discipline=" + (discipline || "all")); },
  liveScores: function (courseId) { return apiFetch("/api/courses/" + courseId + "/live-scores"); },
  pronostics: function (courseId) { return apiFetch("/api/courses/" + courseId + "/pronostics"); },
  pronosticsPage: function (seuil) { return cachedFetch("/api/pronostics?seuil=" + (seuil || 30)); },
};

window.API = API;
