/* =============================================
   PMU Smart Analyzer — Auth (login/logout) v2
   ============================================= */

(function () {
  var TOKEN_KEY = "pmu_token";

  /* ---- Token helpers ---- */
  function getToken() {
    try { return localStorage.getItem(TOKEN_KEY) || null; }
    catch (e) { return null; }
  }

  function setToken(t) {
    try { localStorage.setItem(TOKEN_KEY, t); } catch (e) {}
  }

  function clearToken() {
    try { localStorage.removeItem(TOKEN_KEY); } catch (e) {}
  }

  /* ---- Login screen ---- */
  function showLoginScreen(errorMsg) {
    var existing = document.getElementById("login-overlay");
    if (existing) existing.remove();

    var overlay = document.createElement("div");
    overlay.id = "login-overlay";
    overlay.innerHTML =
      "<div class='login-box'>" +
        "<div class='login-logo'>PMU<span>Smart</span></div>" +
        "<div class='login-subtitle'>Analyzer</div>" +
        (errorMsg
          ? "<div class='login-error'>" + escHtml(errorMsg) + "</div>"
          : "") +
        "<form id='login-form' autocomplete='on'>" +
          "<input id='login-pwd' type='password' class='login-input'" +
          " placeholder='Mot de passe' autocomplete='current-password'" +
          " autofocus />" +
          "<button type='submit' class='login-btn'>Connexion</button>" +
        "</form>" +
        "<div class='login-footer'>Accès sécurisé — PMU Smart Analyzer</div>" +
      "</div>";

    document.body.appendChild(overlay);

    var form = document.getElementById("login-form");
    var pwd  = document.getElementById("login-pwd");

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = form.querySelector(".login-btn");
      btn.disabled = true;
      btn.textContent = "Connexion...";

      fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: pwd.value }),
      })
        .then(function (res) {
          if (!res.ok) throw new Error("Mot de passe incorrect");
          return res.json();
        })
        .then(function (data) {
          setToken(data.token);
          overlay.remove();
          // Re-init the app now that we are authenticated
          if (typeof window._appInit === "function") {
            window._appInit();
          } else {
            window.location.reload();
          }
        })
        .catch(function (err) {
          showLoginScreen(err.message || "Mot de passe incorrect");
        });
    });
  }

  /* ---- Logout ---- */
  function logout() {
    var token = getToken();
    clearToken();
    if (token) {
      fetch("/api/logout", {
        method: "POST",
        headers: { "Authorization": "Bearer " + token },
      }).catch(function () {});
    }
    showLoginScreen();
  }

  /* ---- Wake-up overlay ---- */
  var _wakeupOverlay = null;

  function showWakeupOverlay(attempt, maxAttempts) {
    if (!_wakeupOverlay) {
      _wakeupOverlay = document.createElement("div");
      _wakeupOverlay.id = "wakeup-overlay";
      document.body.appendChild(_wakeupOverlay);
    }
    _wakeupOverlay.innerHTML =
      "<div class='wakeup-box'>" +
        "<div class='wakeup-logo'>PMU<span>Smart</span></div>" +
        "<div class='wakeup-subtitle'>Analyzer</div>" +
        "<div class='wakeup-spinner'></div>" +
        "<div class='wakeup-message'>R\u00e9veil du serveur en cours\u2026</div>" +
        "<div class='wakeup-attempt'>Tentative " + attempt + "/" + maxAttempts + "</div>" +
      "</div>";
  }

  function showWakeupError() {
    if (!_wakeupOverlay) {
      _wakeupOverlay = document.createElement("div");
      _wakeupOverlay.id = "wakeup-overlay";
      document.body.appendChild(_wakeupOverlay);
    }
    _wakeupOverlay.innerHTML =
      "<div class='wakeup-box'>" +
        "<div class='wakeup-logo'>PMU<span>Smart</span></div>" +
        "<div class='wakeup-subtitle'>Analyzer</div>" +
        "<div class='wakeup-error-icon'>\u26a0\ufe0f</div>" +
        "<div class='wakeup-message wakeup-message-error'>Serveur indisponible</div>" +
        "<div class='wakeup-attempt'>Le serveur ne r\u00e9pond pas apr\u00e8s plusieurs tentatives.</div>" +
        "<button class='wakeup-retry-btn' id='wakeup-retry-btn'>R\u00e9essayer</button>" +
      "</div>";
    var btn = document.getElementById("wakeup-retry-btn");
    if (btn) {
      btn.addEventListener("click", function () {
        removeWakeupOverlay();
        boot();
      });
    }
  }

  function removeWakeupOverlay() {
    if (_wakeupOverlay) {
      _wakeupOverlay.remove();
      _wakeupOverlay = null;
    }
  }

  /* ---- Ping /health with retry ---- */
  function pingUntilReady(maxAttempts, intervalMs, onReady, onFail) {
    var attempt = 0;

    function tryPing() {
      attempt++;
      showWakeupOverlay(attempt, maxAttempts);

      fetch("/health", { method: "GET", cache: "no-store" })
        .then(function (res) {
          if (res.ok) {
            onReady();
          } else if (attempt < maxAttempts) {
            setTimeout(tryPing, intervalMs);
          } else {
            onFail();
          }
        })
        .catch(function () {
          if (attempt < maxAttempts) {
            setTimeout(tryPing, intervalMs);
          } else {
            onFail();
          }
        });
    }

    tryPing();
  }

  /* ---- Boot check ---- */
  function boot() {
    var token = getToken();
    if (!token) {
      showLoginScreen();
      return false;
    }

    // Quick probe: first try /health once without showing overlay
    fetch("/health", { method: "GET", cache: "no-store" })
      .then(function (res) {
        if (res.ok) {
          // Server already awake — verify token
          verifyToken(token);
        } else {
          // Server returned error (502/503 cold start) — start retry loop
          startRetryLoop(token);
        }
      })
      .catch(function () {
        // Network error — start retry loop
        startRetryLoop(token);
      });

    return true;
  }

  function startRetryLoop(token) {
    var MAX_ATTEMPTS = 6;
    var INTERVAL_MS  = 5000;

    pingUntilReady(
      MAX_ATTEMPTS,
      INTERVAL_MS,
      function onReady() {
        removeWakeupOverlay();
        verifyToken(token);
      },
      function onFail() {
        showWakeupError();
      }
    );
  }

  function verifyToken(token) {
    fetch("/api/dashboard", {
      headers: { "Authorization": "Bearer " + token },
    }).then(function (res) {
      if (res.status === 401) {
        // Token invalid (e.g. old UUID token after HMAC migration)
        clearToken();
        showLoginScreen();
        return;
      }
      // Token valid → start the app
      if (typeof window._appInit === "function") {
        window._appInit();
      }
    }).catch(function () {
      // Should not happen — server was just confirmed alive by ping
      // Show login as fallback
      showLoginScreen("Erreur de connexion. Veuillez vous reconnecter.");
    });
  }

  /* ---- Escape helper ---- */
  function escHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  /* ---- Expose globally ---- */
  window.Auth = {
    getToken: getToken,
    clearToken: clearToken,
    logout: logout,
    boot: boot,
    showLoginScreen: showLoginScreen,
  };

  /* ---- Inject login + wakeup CSS ---- */
  var style = document.createElement("style");
  style.textContent = [
    /* login overlay */
    "#login-overlay{position:fixed;inset:0;z-index:10000;background:var(--bg,#0f1117);display:flex;align-items:center;justify-content:center;padding:24px}",
    ".login-box{width:100%;max-width:340px;text-align:center}",
    ".login-logo{font-size:32px;font-weight:800;color:var(--gold,#f5a623);letter-spacing:-1px;margin-bottom:2px}",
    ".login-logo span{color:var(--text,#e2e8f0);font-weight:400}",
    ".login-subtitle{font-size:13px;color:var(--text-muted,#64748b);margin-bottom:32px;text-transform:uppercase;letter-spacing:2px}",
    ".login-error{background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.4);color:#ef4444;border-radius:8px;padding:10px 14px;font-size:13px;margin-bottom:16px}",
    ".login-input{width:100%;background:var(--bg3,#1e2436);border:1px solid var(--border,#2a3045);border-radius:10px;padding:14px 16px;color:var(--text,#e2e8f0);font-size:16px;outline:none;margin-bottom:12px;transition:.18s}",
    ".login-input:focus{border-color:var(--gold,#f5a623)}",
    ".login-btn{width:100%;background:var(--gold,#f5a623);color:#0f1117;font-weight:700;font-size:15px;border:none;border-radius:10px;padding:14px;cursor:pointer;transition:.18s}",
    ".login-btn:hover{opacity:.88}",
    ".login-btn:disabled{opacity:.5;cursor:default}",
    ".login-footer{font-size:11px;color:var(--text-muted,#64748b);margin-top:24px}",
    /* wakeup overlay */
    "#wakeup-overlay{position:fixed;inset:0;z-index:10000;background:var(--bg,#0f1117);display:flex;align-items:center;justify-content:center;padding:24px}",
    ".wakeup-box{width:100%;max-width:340px;text-align:center}",
    ".wakeup-logo{font-size:32px;font-weight:800;color:var(--gold,#f5a623);letter-spacing:-1px;margin-bottom:2px}",
    ".wakeup-logo span{color:var(--text,#e2e8f0);font-weight:400}",
    ".wakeup-subtitle{font-size:13px;color:var(--text-muted,#64748b);margin-bottom:32px;text-transform:uppercase;letter-spacing:2px}",
    ".wakeup-spinner{width:36px;height:36px;border:3px solid var(--border,#2a3045);border-top-color:var(--gold,#f5a623);border-radius:50%;animation:wakeup-spin .8s linear infinite;margin:0 auto 20px}",
    "@keyframes wakeup-spin{to{transform:rotate(360deg)}}",
    ".wakeup-message{font-size:16px;font-weight:600;color:var(--text,#e2e8f0);margin-bottom:8px}",
    ".wakeup-message-error{color:var(--text-muted,#64748b)}",
    ".wakeup-attempt{font-size:12px;color:var(--text-muted,#64748b);letter-spacing:.3px}",
    ".wakeup-error-icon{font-size:40px;margin-bottom:16px}",
    ".wakeup-retry-btn{margin-top:24px;padding:13px 32px;background:var(--gold,#f5a623);color:#0f1117;font-weight:700;font-size:15px;border:none;border-radius:10px;cursor:pointer;transition:.18s}",
    ".wakeup-retry-btn:hover{opacity:.88}",
  ].join("");
  document.head.appendChild(style);

})();
