/* =============================================
   PMU Smart Analyzer — Auth (login/logout) v1
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

  /* ---- Boot check ---- */
  function boot() {
    var token = getToken();
    if (!token) {
      showLoginScreen();
      return false;
    }
    // Verify the token is still valid with a lightweight API call
    fetch("/api/dashboard", {
      headers: { "Authorization": "Bearer " + token },
    }).then(function (res) {
      if (res.status === 401) {
        clearToken();
        showLoginScreen();
      }
    }).catch(function () {
      // Network error — still show app (offline mode)
    });
    return true;
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
    logout: logout,
    boot: boot,
    showLoginScreen: showLoginScreen,
  };

  /* ---- Inject login CSS ---- */
  var style = document.createElement("style");
  style.textContent = [
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
  ].join("");
  document.head.appendChild(style);

})();
