/* =============================================
   PMU Smart Analyzer — Mes Paris (Bets) v2
   Stockage : API backend (SQLite) + fallback localStorage
   ============================================= */
(function () {
  "use strict";

  // ---- Fallback localStorage (hors-ligne) ----
  const LS_KEY = "pmu_bets_local";
  function lsLoad() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || "[]"); } catch { return []; }
  }
  function lsSave(bets) {
    localStorage.setItem(LS_KEY, JSON.stringify(bets));
  }

  // ---- Icônes par type ----
  const TYPE_ICONS = {
    GAGNANT:         "🏇",
    PLACE:           "🎯",
    COUPLE:          "🔗",
    TIERCE:          "🏆",
    DEUX_SUR_QUATRE: "4️⃣",
  };
  const TYPE_LABELS = {
    GAGNANT:         "Gagnant",
    PLACE:           "Placé",
    COUPLE:          "Couplé",
    TIERCE:          "Tiercé",
    DEUX_SUR_QUATRE: "2sur4",
  };

  // ---- Statut ----
  function statutHtml(statut) {
    if (statut === "GAGNE")      return "<span class='bet-statut bet-gagne'>Gagné</span>";
    if (statut === "PERDU")      return "<span class='bet-statut bet-perdu'>Perdu</span>";
    return "<span class='bet-statut bet-attente'>En attente</span>";
  }

  // ---- Rendu page Mes Paris ----
  async function renderBetsPage() {
    const content = document.getElementById("bets-content");
    content.innerHTML = "<div style='padding:40px;text-align:center'><div class='spinner'></div></div>";

    let bets = [];
    let useApi = true;
    try {
      bets = await API.getBets();
    } catch (e) {
      useApi = false;
      // Fallback localStorage
      bets = lsLoad().map(function (b, i) {
        return {
          id: b.id || i,
          created_at: b.date,
          type_pari: b.type_pari || "GAGNANT",
          montant: b.montant || 2,
          statut: b.statut || "EN_ATTENTE",
          gain_reel: null,
          course_label: b.course || "",
          hippodrome: b.hippodrome || "",
          chevaux: b.chevaux || [{ numero: 0, nom: b.nom_cheval || "", cote: b.cote }],
        };
      });
    }

    if (!bets.length) {
      content.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">🎯</div>
          <div class="empty-title">Aucun pari enregistré</div>
          <p style="color:var(--text-muted);font-size:13px">Allez sur une course et cliquez sur "Parier" pour ajouter un pari.</p>
        </div>`;
      return;
    }

    const total_mises = bets.reduce(function (s, b) { return s + (b.montant || 2); }, 0);
    const total_gains = bets.reduce(function (s, b) { return s + (b.gain_reel || 0); }, 0);
    const nb_gagnes  = bets.filter(function (b) { return b.statut === "GAGNE"; }).length;
    const nb_perdus  = bets.filter(function (b) { return b.statut === "PERDU"; }).length;
    const nb_attente = bets.filter(function (b) { return b.statut === "EN_ATTENTE"; }).length;

    let html = `
      <div class="stats-row" style="margin-top:12px">
        <div class="stat-card"><div class="stat-value">${bets.length}</div><div class="stat-label">Paris</div></div>
        <div class="stat-card"><div class="stat-value" style="color:var(--text)">${total_mises.toFixed(0)}€</div><div class="stat-label">Mise totale</div></div>
        <div class="stat-card"><div class="stat-value" style="color:var(--green)">${total_gains.toFixed(0)}€</div><div class="stat-label">Gains réels</div></div>
      </div>
      <div class="bets-status-row">
        <span class="bet-statut bet-gagne">${nb_gagnes} Gagné${nb_gagnes > 1 ? "s" : ""}</span>
        <span class="bet-statut bet-perdu">${nb_perdus} Perdu${nb_perdus > 1 ? "s" : ""}</span>
        <span class="bet-statut bet-attente">${nb_attente} En attente</span>
      </div>
      <div style="display:flex;gap:8px;margin:0 16px 12px">
        <button class="refresh-results-btn" onclick="window.Bets.refreshResults()">↺ Actualiser Résultats</button>
      </div>
      <div class="section-title">Mes Paris</div>`;

    bets.forEach(function (b) {
      const dateStr = b.created_at
        ? new Date(b.created_at).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
        : "—";
      const icon  = TYPE_ICONS[b.type_pari] || "🎯";
      const label = TYPE_LABELS[b.type_pari] || b.type_pari;
      const chevaux = (b.chevaux || []).map(function (c) { return c.nom; }).join(", ");
      const gainHtml = b.gain_reel > 0
        ? `<div style="font-size:13px;color:var(--green);font-weight:700">+${b.gain_reel.toFixed(2)}€</div>`
        : "";

      const deleteAction = useApi
        ? `window.Bets.deleteBetById(${b.id})`
        : `window.Bets.deleteBetLocal('${b.id}')`;

      html += `
        <div class="card" style="padding:14px 16px">
          <div style="display:flex;align-items:flex-start;gap:10px">
            <div style="font-size:24px;flex-shrink:0">${icon}</div>
            <div style="flex:1;min-width:0">
              <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                <span style="font-weight:700;font-size:15px">${chevaux || "—"}</span>
                <span class="badge badge-gray" style="font-size:10px">${label}</span>
                ${statutHtml(b.statut)}
              </div>
              <div style="font-size:12px;color:var(--text-muted);margin-top:2px">${b.course_label || ""} · ${b.hippodrome || ""}</div>
              <div style="font-size:12px;color:var(--text-dim);margin-top:2px">${dateStr}</div>
            </div>
            <div style="text-align:right;flex-shrink:0">
              <div style="font-size:13px;font-weight:700;color:var(--gold)">${b.montant || 2}€</div>
              ${gainHtml}
              <button onclick="${deleteAction}" style="margin-top:6px;background:var(--red-dim);border:1px solid var(--red);border-radius:6px;color:var(--red);font-size:11px;padding:3px 8px;cursor:pointer">Supprimer</button>
            </div>
          </div>
        </div>`;
    });

    content.innerHTML = html;
  }

  async function deleteBetById(id) {
    try {
      await API.deleteBet(id);
      window.showToast && window.showToast("Pari supprimé");
      renderBetsPage();
    } catch (e) {
      window.showToast && window.showToast("Erreur suppression", true);
    }
  }

  function deleteBetLocal(id) {
    const bets = lsLoad().filter(function (b) { return b.id !== id; });
    lsSave(bets);
    window.showToast && window.showToast("Pari supprimé");
    renderBetsPage();
  }

  // Ancien alias pour compat
  function removeBetAndRefresh(id) {
    deleteBetById(id);
  }

  async function refreshResults() {
    window.showToast && window.showToast("Actualisation des résultats...");
    try {
      const r = await API.refreshResults();
      window.showToast && window.showToast("Résultats mis à jour (" + (r.courses_updated || 0) + " course(s))");
      renderBetsPage();
    } catch (e) {
      window.showToast && window.showToast("Erreur actualisation", true);
    }
  }

  // ---- placeBet (appelé depuis app.js via le modal) ----
  async function placeBet(payload) {
    // payload : { type_pari, montant, course_id, course_label, hippodrome, chevaux }
    try {
      const bet = await API.createBet(payload);
      window.showToast && window.showToast("Pari placé : " + (payload.chevaux || []).map(function (c) { return c.nom; }).join(" + ") + " (" + payload.montant + "€)");
      return bet;
    } catch (e) {
      // Fallback localStorage
      const lsBet = {
        id: Date.now() + "_" + Math.random().toString(36).slice(2, 5),
        date: new Date().toISOString(),
        type_pari: payload.type_pari,
        montant: payload.montant,
        statut: "EN_ATTENTE",
        course: payload.course_label,
        hippodrome: payload.hippodrome,
        chevaux: payload.chevaux,
        nom_cheval: (payload.chevaux || []).map(function (c) { return c.nom; }).join(", "),
      };
      const bets = lsLoad();
      bets.unshift(lsBet);
      lsSave(bets);
      window.showToast && window.showToast("Pari sauvegardé localement");
      return lsBet;
    }
  }

  window.Bets = {
    renderBetsPage,
    placeBet,
    deleteBetById,
    deleteBetLocal,
    removeBetAndRefresh,
    refreshResults,
  };
})();
