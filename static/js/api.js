/* API wrapper — PMU Smart Analyzer v2 */
const BASE = "";

async function apiFetch(path, options) {
  options = options || {};
  // Inject auth token into every request
  var token = window.Auth && window.Auth.getToken ? window.Auth.getToken() : null;
  if (token) {
    options.headers = options.headers || {};
    options.headers["Authorization"] = "Bearer " + token;
  }
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
    console.error("API error [" + path + "]:", e);
    throw e;
  }
}

const API = {
  // ---- Existants ----
  dashboard:  function () { return apiFetch("/api/dashboard"); },
  reunions:   function () { return apiFetch("/api/reunions"); },
  course:     function (id) { return apiFetch("/api/courses/" + id); },
  stats:      function () { return apiFetch("/api/stats"); },
  refresh:    function () { return apiFetch("/api/refresh", { method: "POST" }); },

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
    return apiFetch("/api/bets/refresh-results", { method: "POST" });
  },

  // ---- F2 : Scoring ----
  scoringAccuracy: function () { return apiFetch("/api/scoring/accuracy"); },
  scoringAccuracyByDiscipline: function () { return apiFetch("/api/scoring/accuracy-by-discipline"); },
  scoringDisciplineStats: function () { return apiFetch("/api/scoring/discipline-stats"); },
  scoringOptimize: function () { return apiFetch("/api/scoring/optimize", { method: "POST" }); },

  // ---- Stats avancées + Calibration ----
  statsScoring:     function () { return apiFetch("/api/stats/scoring"); },
  statsCalibration: function () { return apiFetch("/api/stats/calibration"); },
  calibrate:        function () { return apiFetch("/api/calibrate", { method: "POST" }); },
};

window.API = API;
