/* =============================================
   PMU Smart Analyzer — Main App JS v3
   ============================================= */

let currentPage = "dashboard";
var _coursesScrollPos = 0;
var _coursesLoaded = false;
let _betModalCourse = null;   // course courante pour le modal de pari
var _scoringMode = "avec_cote"; // "avec_cote" | "sans_cote"

const H = () => window.Components;

// ---- Page Transitions ----
function navigate(page, opts) {
  opts = opts || {};
  const prev = document.getElementById("page-" + currentPage);
  if (prev) prev.classList.add("page-exit");

  document.querySelectorAll(".nav-item").forEach(function (n) { n.classList.remove("active"); });

  const pageEl = document.getElementById("page-" + page);
  if (pageEl) {
    pageEl.classList.remove("page-exit");
    pageEl.classList.add("page-enter");
    void pageEl.offsetWidth;
    document.querySelectorAll(".page").forEach(function (p) {
      if (p !== pageEl) {
        p.classList.remove("active", "page-enter");
        p.classList.add("page-exit");
      }
    });
    pageEl.classList.add("active");
    setTimeout(function () { pageEl.classList.remove("page-enter"); }, 250);
  }

  const navEl = document.querySelector("[data-nav='" + page + "']");
  if (navEl) navEl.classList.add("active");

  currentPage = page;

  if (page === "dashboard") loadDashboard();
  else if (page === "courses") {
    if (!_coursesLoaded) {
      loadCourses();
    } else {
      // Restaurer la position de scroll
      setTimeout(function() { window.scrollTo(0, _coursesScrollPos); }, 50);
    }
  }
  else if (page === "bets") window.Bets && window.Bets.renderBetsPage();
  else if (page === "stats") loadStatsPage();
}

// ---- Toast ----
function showToast(msg, error) {
  error = error || false;
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast show" + (error ? " error" : "");
  setTimeout(function () { t.className = "toast"; }, 3000);
}

// ---- Alert Badge ----
function updateAlertBadge(count) {
  const badge = document.getElementById("alert-badge");
  if (!badge) return;
  if (count > 0) {
    badge.textContent = count;
    badge.style.display = "inline-flex";
  } else {
    badge.style.display = "none";
  }
}

// ---- Alertes ----
function buildAlertes(data) {
  const now = new Date();
  const in30 = new Date(now.getTime() + 30 * 60 * 1000);
  const alerts = [];

  if (data.reunions) {
    data.reunions.forEach(function (r) {
      r.courses.forEach(function (c) {
        if (c.heure_depart) {
          const dep = new Date(c.heure_depart);
          if (dep > now && dep <= in30) {
            alerts.push({ type: "soon", text: "Départ dans < 30 min : " + (c.libelle_court || c.libelle) + " · " + r.hippodrome_libelle });
          }
        }
      });
    });
  }

  if (data.top_picks) {
    data.top_picks.forEach(function (p) {
      if (p.is_value_bet && p.confiance === "HIGH") {
        alerts.push({ type: "value", text: "Value Bet HIGH : " + p.nom + " (cote " + H().formatCote(p.cote_actuelle) + ")" });
      }
      if (p.score_global > 75) {
        alerts.push({ type: "score", text: "Score > 75 : " + p.nom + " — " + Math.round(p.score_global) + "/100" });
      }
    });
  }

  updateAlertBadge(alerts.length);
  return alerts;
}

function renderAlertes(alerts) {
  if (!alerts || !alerts.length) return "";
  const icons = { soon: "⏰", value: "💎", score: "🔥" };
  let html = "<div class='section-title'>🚨 Alertes du Jour</div><div class='alerts-box'>";
  alerts.forEach(function (a) {
    html += "<div class='alert-item alert-" + a.type + "'>" + (icons[a.type] || "•") + " " + a.text + "</div>";
  });
  html += "</div>";
  return html;
}

// ---- Dashboard ----
async function loadDashboard() {
  const content = document.getElementById("dashboard-content");
  content.innerHTML = H().skeletonCards(4);

  // Mettre à jour la date à chaque chargement du dashboard
  var now = new Date();
  var dateLabel = now.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });
  document.querySelectorAll(".date-badge").forEach(function (el) { el.textContent = dateLabel; });

  // Récupérer les arrivées en arrière-plan au chargement
  API.refreshResults().catch(function() {});

  try {
    const [data, stats, accuracy, discStats] = await Promise.all([
      API.dashboard(),
      API.stats().catch(function () { return null; }),
      API.scoringAccuracy().catch(function () { return null; }),
      API.scoringDisciplineStats().catch(function () { return null; }),
    ]);
    if (data && data.offline) {
      content.innerHTML = "<div class='empty-state'><div class='empty-icon'>📵</div><div class='empty-title'>Hors ligne</div><p style='color:var(--text-muted);font-size:13px'>Reconnectez-vous pour voir les données du jour.</p></div>";
      return;
    }
    renderDashboard(data, stats, accuracy, discStats);
  } catch (e) {
    console.error("Dashboard error:", e);
    content.innerHTML = "<div class='empty-state'><div class='empty-icon'>⚠️</div><div class='empty-title'>Impossible de charger les données</div><p style='color:var(--text-muted);font-size:13px'>Vérifiez votre connexion internet</p></div>";
    showToast("Erreur de chargement", true);
  }
}

function renderDashboard(data, stats, accuracy, discStats) {
  const content = document.getElementById("dashboard-content");

  const dateStr = data.date;
  const d = dateStr.slice(0, 2) + "/" + dateStr.slice(2, 4) + "/" + dateStr.slice(4);

  const alerts = buildAlertes(data);
  let html = renderAlertes(alerts);

  html += "<div class='stats-row'>" +
    "<div class='stat-card'><div class='stat-value'>" + data.nb_reunions + "</div><div class='stat-label'>Réunions</div></div>" +
    "<div class='stat-card'><div class='stat-value'>" + data.nb_courses + "</div><div class='stat-label'>Courses</div></div>" +
    "<div class='stat-card'><div class='stat-value' style='color:var(--green)'>" + data.nb_value_bets + "</div><div class='stat-label'>Value Bets</div></div>" +
    "</div>";

  // F2 : Précision du modèle globale
  if (accuracy && accuracy.length) {
    html += renderAccuracyCard(accuracy);
  }

  // Précision par discipline
  if (discStats && discStats.disciplines && Object.keys(discStats.disciplines).length > 0) {
    html += renderDisciplineStatsCard(discStats);
  }

  if (stats && stats.length) {
    html += renderStatsChart(stats);
  }

  if (data.top_picks && data.top_picks.length > 0) {
    html += "<div class='section-title'>Top Picks du Jour</div>";
    data.top_picks.forEach(function (p, i) {
      const medal = i === 0 ? "1er" : i === 1 ? "2e" : "3e";
      const vb = p.is_value_bet ? "<span class='badge badge-green' style='margin-left:6px'>VALUE BET</span>" : "";
      html += "<div class='card' style='padding:12px 16px'>" +
        "<div style='display:flex;align-items:center;gap:10px'>" +
        "<span style='font-size:22px;min-width:36px;text-align:center;font-weight:800;color:var(--gold)'>" + medal + "</span>" +
        "<div style='flex:1;min-width:0'>" +
        "<div style='font-weight:700;font-size:15px'>" + p.nom + vb + "</div>" +
        "<div style='font-size:12px;color:var(--text-muted)'>" + (p.jockey || "—") + " · Cote " + H().formatCote(p.cote_actuelle) + "</div>" +
        "</div>" +
        "<div style='text-align:right'>" +
        "<div class='score-label " + H().scoreClass(p.score_global) + "' style='font-size:18px;font-weight:800'>" + Math.round(p.score_global) + "</div>" +
        "<div style='font-size:10px;color:var(--text-muted)'>Score</div>" +
        "</div>" +
        "</div>" +
        "<div style='margin-top:8px;font-size:12px;color:var(--text-dim)'>" + p.explication + "</div>" +
        "</div>";
    });
  }

  if (data.reunions && data.reunions.length > 0) {
    html += "<div class='section-title'>Réunions du jour</div>";
    data.reunions.forEach(function (r) {
      html += "<div class='hipp-header'>" +
        "<span class='hipp-icon'>🏟</span>" +
        "<span class='hipp-name'>" + r.hippodrome_libelle + "</span>" +
        "<span class='hipp-count'>" + r.courses.length + " courses</span>" +
        "</div>";
      r.courses.forEach(function (c) {
        html += "<div class='card clickable' style='margin:6px 16px;padding:12px' onclick='showCourse(" + c.id + ")'>" +
          "<div style='display:flex;align-items:center;gap:8px'>" +
          "<span class='badge badge-gray' style='font-size:11px'>C" + c.num_ordre + "</span>" +
          "<span style='font-size:13px;font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>" + (c.libelle_court || c.libelle) + "</span>" +
          "<span style='font-size:14px;font-weight:700;color:var(--text-dim)'>" + H().formatTime(c.heure_depart) + "</span>" +
          "</div>" +
          "</div>";
      });
    });
  }

  if (!data.nb_courses) {
    html += "<div class='empty-state'><div class='empty-icon'>🐴</div><div class='empty-title'>Aucune course disponible</div><p style='color:var(--text-muted);font-size:13px'>Revenez plus tard ou rafraîchissez</p></div>";
  }

  content.innerHTML = html;
}

// ---- Card précision par discipline ----
function renderDisciplineStatsCard(discStats) {
  var discs = discStats.disciplines || {};
  var keys = Object.keys(discs);
  if (!keys.length) return "";

  var DISC_LABELS = {
    "PLAT": "Plat",
    "TROT_ATTELE": "Trot Attelé",
    "TROT_MONTE": "Trot Monté",
    "HAIE": "Haies",
    "STEEPLE": "Steeple",
    "CROSS": "Cross",
  };

  var html = "<div class='accuracy-card'>" +
    "<div class='accuracy-title'>Précision par Discipline</div>";

  keys.forEach(function(disc) {
    var s = discs[disc];
    if (!s || s.nb_courses === 0) return;
    var label = DISC_LABELS[disc] || disc;
    var winRate = s.top_pick_win_rate || 0;
    var top3Rate = s.top_pick_top3_rate || 0;
    var cls = winRate >= 30 ? "high" : winRate >= 15 ? "medium" : "low";

    html += "<div style='margin-top:8px'>" +
      "<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:3px'>" +
      "<span style='font-size:12px;font-weight:600'>" + label + "</span>" +
      "<span style='font-size:11px;color:var(--text-muted)'>" + s.nb_courses + " courses</span>" +
      "</div>" +
      "<div style='display:flex;gap:12px;font-size:11px'>" +
      "<span>Victoire top pick : <strong class='score-label " + cls + "'>" + winRate + "%</strong></span>" +
      "<span>Top 3 : <strong>" + top3Rate + "%</strong></span>" +
      "</div>" +
      "<div class='score-bar' style='height:4px;margin-top:4px'>" +
      "<div class='score-bar-fill " + cls + "' style='width:" + Math.min(winRate * 2, 100) + "%'></div>" +
      "</div>" +
      "</div>";
  });

  html += "</div>";
  return html;
}

// ---- F2 : Card précision modèle ----
function renderAccuracyCard(accuracy) {
  const topPick = accuracy.find(function (a) { return a.critere === "forme_recente"; });
  const total_samples = accuracy.reduce(function (s, a) { return s + (a.nb_samples || 0); }, 0);

  let bestPrecision = 0;
  let bestLabel = "—";
  accuracy.forEach(function (a) {
    if (a.nb_samples > 0 && a.precision > bestPrecision) {
      bestPrecision = a.precision;
      bestLabel = a.critere.replace(/_/g, " ");
    }
  });

  if (total_samples === 0) {
    return "<div class='accuracy-card'><div class='accuracy-title'>Précision modèle</div>" +
      "<div style='font-size:12px;color:var(--text-muted)'>Pas encore de données — placez des paris pour calibrer le modèle</div></div>";
  }

  const avgPrecision = accuracy.filter(function (a) { return a.nb_samples > 0; })
    .reduce(function (s, a) { return s + a.precision; }, 0) /
    accuracy.filter(function (a) { return a.nb_samples > 0; }).length;

  return "<div class='accuracy-card'>" +
    "<div class='accuracy-title'>Précision modèle IA</div>" +
    "<div class='accuracy-row'>" +
    "<span class='accuracy-label'>Top Pick</span>" +
    "<span class='accuracy-pct'>" + Math.round(avgPrecision * 100) + "%</span>" +
    "<span style='font-size:11px;color:var(--text-muted)'>sur " + total_samples + " courses</span>" +
    "</div>" +
    "<div style='font-size:11px;color:var(--text-muted);margin-top:4px'>Meilleur critère : " + bestLabel + " (" + Math.round(bestPrecision * 100) + "%)</div>" +
    "</div>";
}

// ---- Stats Chart (7 jours) ----
function renderStatsChart(stats) {
  const maxCourses = Math.max.apply(null, stats.map(function (s) { return s.nb_courses || 0; }).concat([1]));
  let html = "<div class='section-title'>📈 Stats 7 Derniers Jours</div><div class='stats-chart'>";
  stats.forEach(function (s) {
    const pct = Math.round(((s.nb_courses || 0) / maxCourses) * 100);
    const pctVb = maxCourses > 0 ? Math.round(((s.nb_value_bets || 0) / maxCourses) * 100) : 0;
    const label = s.date ? s.date.slice(0, 5) : "—";
    html += "<div class='stat-bar-col'>" +
      "<div class='stat-bar-track'>" +
      "<div class='stat-bar-fill vb' style='height:" + pctVb + "%' title='Value Bets: " + (s.nb_value_bets || 0) + "'></div>" +
      "<div class='stat-bar-fill courses' style='height:" + pct + "%' title='Courses: " + (s.nb_courses || 0) + "'></div>" +
      "</div>" +
      "<div class='stat-bar-label'>" + label + "</div>" +
      "</div>";
  });
  html += "</div><div class='stats-chart-legend'>" +
    "<span class='legend-dot courses'></span> Courses &nbsp;" +
    "<span class='legend-dot vb'></span> Value Bets" +
    "</div>";
  return html;
}

// ---- Courses List ----
async function loadCourses() {
  const content = document.getElementById("courses-content");
  content.innerHTML = H().skeletonCards(5);
  try {
    const reunions = await API.reunions();
    renderCoursesList(reunions);
    _coursesLoaded = true;
  } catch (e) {
    content.innerHTML = "<div class='empty-state'><div class='empty-icon'>⚠️</div><div class='empty-title'>Erreur de chargement</div></div>";
    showToast("Erreur de chargement", true);
  }
}

function renderCoursesList(reunions) {
  const content = document.getElementById("courses-content");
  if (!reunions || !reunions.length) {
    content.innerHTML = "<div class='empty-state'><div class='empty-icon'>🐴</div><div class='empty-title'>Aucune course aujourd'hui</div></div>";
    return;
  }
  let html = "";
  reunions.forEach(function (r) {
    html += "<div class='hipp-header'>" +
      "<span class='hipp-icon'>🏟️</span>" +
      "<span class='hipp-name'>" + r.hippodrome_libelle + "</span>" +
      "<span class='hipp-count'>" + r.courses.length + " courses · R" + r.num_officiel + "</span>" +
      "</div>";
    r.courses.forEach(function (c) {
      html += H().renderCourseCard(c, r.hippodrome_libelle);
    });
  });
  content.innerHTML = html;
}

// ---- Course Detail ----
async function showCourse(courseId) {
  // Sauvegarder la position de scroll avant de quitter la page courses
  _coursesScrollPos = window.scrollY || window.pageYOffset || 0;
  navigate("course", { id: courseId });
  const content = document.getElementById("course-content");
  content.innerHTML = "<div style='padding:40px;text-align:center'><div class='spinner'></div></div>";
  document.getElementById("page-course-back-btn").style.display = "flex";

  try {
    const course = await API.course(courseId);
    renderCourseDetail(course, null);
  } catch (e) {
    content.innerHTML = "<div class='empty-state'><div class='empty-icon'>⚠️</div><div class='empty-title'>Erreur de chargement</div></div>";
    showToast("Impossible de charger cette course", true);
  }
}

function renderCourseDetail(course, suggestions) {
  const content = document.getElementById("course-content");
  _betModalCourse = course;

  document.getElementById("course-header-title").textContent = course.libelle_court || ("C" + course.num_ordre);

  const terrain = course.terrain ? course.terrain.replace(/_/g, " ") : "—";
  const penet = course.penetrometre_valeur ? " (" + course.penetrometre_valeur + ")" : "";
  const disc = H().disciplineLabel(course.discipline);
  const discCls = H().disciplineClass(course.discipline);
  const prix = course.montant_prix > 0 ? ((course.montant_prix / 1000).toFixed(0) + "k€") : "—";

  // Badge statut résultat
  const statutRes = course.statut_resultat || "EN_COURS";
  const statutBadge = statutRes === "TERMINE"
    ? "<span class='badge badge-green'>Terminée</span>"
    : "";

  let html = "<div class='course-detail-header'>" +
    "<div class='detail-hippodrome'>" + (course.hippodrome || "—") + " " + statutBadge + "</div>" +
    "<div style='font-size:14px;color:var(--text-muted)'>" + course.libelle + "</div>" +
    "<div class='detail-meta'>" +
    "<span class='detail-chip'>🕐 " + H().formatTime(course.heure_depart) + "</span>" +
    "<span class='detail-chip'>📏 " + course.distance + "m</span>" +
    "<span class='detail-chip'><span class='" + discCls + "'>" + disc + "</span></span>" +
    "<span class='detail-chip'>🌿 " + terrain + penet + "</span>" +
    "<span class='detail-chip'>💰 " + prix + "</span>" +
    "<span class='detail-chip'>🐴 " + course.nombre_partants + " partants</span>" +
    "</div>";

  // Afficher les types de paris disponibles
  if (course.paris_disponibles && course.paris_disponibles.length > 0) {
    var parisArr = course.paris_disponibles.split(",").filter(function(p) { return p.trim(); });
    if (parisArr.length > 0) {
      html += "<div class='paris-disponibles'><span class='paris-label'>🎰 Paris :</span> ";
      parisArr.forEach(function(p) {
        html += "<span class='paris-badge'>" + p.trim() + "</span>";
      });
      html += "</div>";
    }
  }

  html += "</div>";

  // F3 : Suggestions IA — désactivé (affichage masqué)
  // if (suggestions && (suggestions.couple || suggestions.tierce || suggestions.deux_sur_quatre)) {
  //   html += renderSuggestions(suggestions, course);
  // }

  if (course.top_pick) {
    const p = course.top_pick;
    html += "<div class='reco-banner top-pick'>" +
      "<div class='reco-title top-pick'>🏆 Top Pick</div>" +
      "<div class='reco-horse'>" + p.nom + " <span style='font-size:14px;font-weight:400;color:var(--gold)'>· Cote " + H().formatCote(p.cote_actuelle) + "</span></div>" +
      "<div class='reco-expl'>" + p.explication + "</div>" +
      "<div class='reco-mise'>Mise suggérée : 2€ Gagnant · 1€ Placé</div>" +
      "</div>";
  }

  if (course.value_bets && course.value_bets.length > 0) {
    course.value_bets.forEach(function (vb) {
      html += "<div class='reco-banner value-bet'>" +
        "<div class='reco-title value-bet'>💎 Value Bet détecté</div>" +
        "<div class='reco-horse'>" + vb.nom + " <span style='font-size:14px;font-weight:400;color:var(--green)'>· Cote " + H().formatCote(vb.cote_actuelle) + "</span></div>" +
        "<div class='reco-expl'>" + vb.explication + "</div>" +
        "<div class='reco-mise'>Mise suggérée : 1€ Gagnant (risque élevé, rendement potentiel fort)</div>" +
        "</div>";
    });
  }

  if (course.participants && course.participants.length > 0) {
    var sectionTitle = _scoringMode === "sans_cote"
      ? "Partants (triés sans cote)"
      : "Partants (triés par score)";
    html += "<div style='display:flex;align-items:center;justify-content:space-between;padding:16px 16px 4px'>" +
      "<span class='section-title' style='padding:0;margin:0'>" + sectionTitle + "</span>" +
      "<div class='scoring-toggle'>" +
      "<button class='scoring-toggle-btn" + (_scoringMode === "avec_cote" ? " active" : "") + "' onclick='setScoringMode(\"avec_cote\")'>Avec cote</button>" +
      "<button class='scoring-toggle-btn" + (_scoringMode === "sans_cote" ? " active" : "") + "' onclick='setScoringMode(\"sans_cote\")'>Sans cote</button>" +
      "</div>" +
      "</div>";

    var sorted = course.participants.slice().sort(function(a, b) {
      var sa = _scoringMode === "sans_cote" ? (a.score_sans_cote || 0) : (a.score_global || 0);
      var sb = _scoringMode === "sans_cote" ? (b.score_sans_cote || 0) : (b.score_global || 0);
      return sb - sa;
    });

    html += "<div class='card' style='padding:0 16px' id='participants-list'>";
    sorted.forEach(function (p, i) {
      html += renderParticipantRowWithBet(p, i + 1, course, course.hippodrome);
    });
    html += "</div>";
  } else {
    html += "<div class='empty-state'><div class='empty-icon'>🐴</div><div class='empty-title'>Partants non disponibles</div><p style='color:var(--text-muted);font-size:13px'>Les partants ne sont pas encore publiés</p></div>";
  }

  content.innerHTML = html;
}

// ---- F3 : Suggestions IA ----
function renderSuggestions(s, course) {
  const couples = (s.couple || []).map(function (p) { return p.nom; }).join(" + ") || "—";
  const tierce  = (s.tierce || []).map(function (p) { return p.nom; }).join(" > ") || "—";
  const d4      = (s.deux_sur_quatre || []).slice(0, 2).map(function (p) { return p.nom; }).join(" + ") || "—";

  function makeComboPayload(type, horses) {
    return {
      type_pari: type,
      montant: type === "GAGNANT" || type === "PLACE" ? 2 : 1,
      course_id: course.id,
      course_label: course.libelle_court || course.libelle,
      hippodrome: course.hippodrome || "",
      chevaux: horses.map(function (p) {
        return { numero: p.num_pmu, nom: p.nom, cote: p.cote_actuelle || null };
      }),
    };
  }

  // Store payloads in registry to avoid HTML escaping issues
  window._suggestionPayloads = window._suggestionPayloads || {};
  var ts = Date.now();
  var couple_key = null, tierce_key = null, d4_key = null, gagnant_key = null;

  if (s.couple && s.couple.length >= 2) {
    couple_key = "couple_" + ts;
    window._suggestionPayloads[couple_key] = makeComboPayload("COUPLE", s.couple.slice(0, 2));
  }
  if (s.tierce && s.tierce.length >= 3) {
    tierce_key = "tierce_" + ts;
    window._suggestionPayloads[tierce_key] = makeComboPayload("TIERCE", s.tierce.slice(0, 3));
  }
  if (s.deux_sur_quatre && s.deux_sur_quatre.length >= 2) {
    d4_key = "d4_" + ts;
    window._suggestionPayloads[d4_key] = makeComboPayload("DEUX_SUR_QUATRE", s.deux_sur_quatre.slice(0, 2));
  }
  if (s.gagnant) {
    gagnant_key = "gagnant_" + ts;
    window._suggestionPayloads[gagnant_key] = makeComboPayload("GAGNANT", [s.gagnant]);
  }

  let html = "<div class='section-title'>Suggestions IA</div>" +
    "<div style='overflow:hidden;max-width:100%'><div class='suggestions-scroll'>";

  if (couple_key) {
    html += "<div class='suggestion-card'>" +
      "<div class='suggestion-type'>🔗 Couplé</div>" +
      "<div class='suggestion-horses'>" + couples + "</div>" +
      "<button class='suggestion-btn' onclick='placeSuggestedBetByKey(\"" + couple_key + "\")'>Parier 1€</button>" +
      "</div>";
  }
  if (tierce_key) {
    html += "<div class='suggestion-card'>" +
      "<div class='suggestion-type'>🏆 Tiercé</div>" +
      "<div class='suggestion-horses'>" + tierce + "</div>" +
      "<button class='suggestion-btn' onclick='placeSuggestedBetByKey(\"" + tierce_key + "\")'>Parier 1€</button>" +
      "</div>";
  }
  if (d4_key) {
    html += "<div class='suggestion-card'>" +
      "<div class='suggestion-type'>4️⃣ 2sur4</div>" +
      "<div class='suggestion-horses'>" + d4 + "</div>" +
      "<button class='suggestion-btn' onclick='placeSuggestedBetByKey(\"" + d4_key + "\")'>Parier 1€</button>" +
      "</div>";
  }
  if (gagnant_key) {
    html += "<div class='suggestion-card'>" +
      "<div class='suggestion-type'>🏇 Gagnant</div>" +
      "<div class='suggestion-horses'>" + s.gagnant.nom + "</div>" +
      "<button class='suggestion-btn' onclick='placeSuggestedBetByKey(\"" + gagnant_key + "\")'>Parier 2€</button>" +
      "</div>";
  }

  html += "</div></div>";
  return html;
}

// Registry for suggestion payloads (avoids HTML escaping issues)
window._suggestionPayloads = {};

function escAttr(str) {
  // Encode JSON for use as a string argument inside onclick='func("...")'
  // The onclick uses single quotes, so double quotes in JSON must be HTML-escaped
  return '"' + str.replace(/&/g, "&amp;").replace(/"/g, "&quot;") + '"';
}

// Build an onclick attribute with properly escaped JSON argument
function makeOnclick(fnName, payload) {
  var escaped = payload.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
  return "onclick=\"" + fnName + "(&quot;" + escaped.replace(/"/g, "\\&quot;") + "&quot;)\"";
}
async function placeSuggestedBet(payloadStr) {
  try {
    const payload = JSON.parse(payloadStr);
    await window.Bets.placeBet(payload);
  } catch (e) {
    showToast("Erreur lors du placement du pari", true);
  }
}

async function placeSuggestedBetByKey(key) {
  try {
    const payload = window._suggestionPayloads && window._suggestionPayloads[key];
    if (!payload) { showToast("Pari introuvable", true); return; }
    await window.Bets.placeBet(payload);
  } catch (e) {
    showToast("Erreur lors du placement du pari", true);
  }
}

// ---- Participant row avec bouton Parier ----
function renderParticipantRowWithBet(p, rank, course, hippodrome) {
  const cls = rank === 1 ? "rank-1" : "";
  const vb = p.is_value_bet ? "<span class='badge badge-green' style='font-size:10px'>VB</span>" : "";
  const safeP = JSON.stringify(p).replace(/"/g, "&quot;");

  // Score affiché selon le mode actif
  var displayScore = _scoringMode === "sans_cote"
    ? (p.score_sans_cote != null ? p.score_sans_cote : p.score_global)
    : p.score_global;

  // Position d'arrivée si disponible
  const posHtml = p.position_arrivee
    ? "<span class='arrival-pos pos-" + p.position_arrivee + "'>" + p.position_arrivee + "e</span>"
    : "";

  return "<div class='participant-row-wrap'>" +
    "<div class='participant-row' data-pid='" + p.id + "' onclick='showParticipantModal(" + safeP + ")'>" +
    "<div class='p-num " + cls + "'>" + p.num_pmu + "</div>" +
    "<div class='p-info'>" +
    "<div class='p-name'>" + p.nom + " " + vb + " " + posHtml + "</div>" +
    "<div class='p-sub'>" + (p.jockey || "—") + " · " + (p.entraineur || "—") + "</div>" +
    "</div>" +
    "<div class='p-right'>" +
    "<span class='p-cote'>" + H().formatCote(p.cote_actuelle) + "</span>" +
    "<div class='p-score-wrap'>" +
    "<div class='score-bar' style='width:70px'>" +
    "<div class='score-bar-fill " + H().scoreClass(displayScore) + "' style='width:" + displayScore + "%'></div>" +
    "</div>" +
    "<span class='score-label " + H().scoreClass(displayScore) + "' style='font-size:12px'>" + Math.round(displayScore) + "</span>" +
    "</div>" +
    "</div>" +
    "</div>" +
    "<div style='padding:0 0 8px;text-align:right'>" +
    "<button class='bet-btn' onclick=\"event.stopPropagation();showBetModal(" + JSON.stringify(p).replace(/"/g, "&quot;") + ")\">🎯 Parier</button>" +
    "</div>" +
    "</div>";
}

// ---- Toggle mode scoring ----
function setScoringMode(mode) {
  _scoringMode = mode;
  if (_betModalCourse) {
    renderCourseDetail(_betModalCourse, null);
  }
}

// ---- F3 : Modal de pari multi-type ----
function showBetModal(preSelectedHorse) {
  if (!_betModalCourse) { showToast("Aucune course sélectionnée", true); return; }
  const course = _betModalCourse;
  const participants = course.participants || [];
  const overlay = document.getElementById("modal-overlay");
  const body = document.getElementById("modal-body");

  let selectedType = preSelectedHorse ? "GAGNANT" : "GAGNANT";
  let selectedHorses = preSelectedHorse ? [preSelectedHorse] : [];
  let selectedMontant = 2;

  function maxHorses(type) {
    if (type === "GAGNANT" || type === "PLACE") return 1;
    if (type === "COUPLE") return 2;
    if (type === "TIERCE") return 3;
    if (type === "DEUX_SUR_QUATRE") return 2;
    return 1;
  }
  function defaultMontant(type) {
    return (type === "GAGNANT" || type === "PLACE") ? 2 : 1;
  }

  function renderModal() {
    const types = [
      { id: "GAGNANT", icon: "🏇", label: "Gagnant", desc: "1er" },
      { id: "PLACE",   icon: "🎯", label: "Placé",   desc: "Top 3" },
      { id: "COUPLE",  icon: "🔗", label: "Couplé",  desc: "Top 2" },
      { id: "TIERCE",  icon: "🏆", label: "Tiercé",  desc: "Top 3" },
      { id: "DEUX_SUR_QUATRE", icon: "4️⃣", label: "2sur4", desc: "2 dans Top 4" },
    ];

    const maxH = maxHorses(selectedType);
    const selectedNums = selectedHorses.map(function (h) { return h.num_pmu; });

    let html = "<div class='modal-handle'></div>" +
      "<div class='modal-title'>Placer un pari</div>";

    // Type selector
    html += "<div class='bet-type-selector'>";
    types.forEach(function (t) {
      const active = t.id === selectedType ? " active" : "";
      html += "<button class='bet-type-btn" + active + "' onclick='_betModalSetType(\"" + t.id + "\")'>" +
        "<span style='font-size:18px'>" + t.icon + "</span>" +
        "<span class='bet-type-label'>" + t.label + "</span>" +
        "<span class='bet-type-desc'>" + t.desc + "</span>" +
        "</button>";
    });
    html += "</div>";

    // Info type
    html += "<div class='bet-type-info'>Sélectionner " + maxH + " cheval" + (maxH > 1 ? "aux" : "") + "</div>";

    // Chevaux disponibles
    html += "<div class='bet-horse-list'>";
    if (selectedType === "GAGNANT" || selectedType === "PLACE") {
      // Sélecteur simple avec radio visuel
      participants.forEach(function (p) {
        const checked = selectedNums.includes(p.num_pmu);
        html += "<div class='bet-horse-row" + (checked ? " selected" : "") + "' onclick='_betModalToggleHorse(" + JSON.stringify(p).replace(/"/g, "&quot;") + ")'>" +
          "<div class='bet-horse-check'>" + (checked ? "●" : "○") + "</div>" +
          "<div class='bet-horse-num'>" + p.num_pmu + "</div>" +
          "<div class='bet-horse-name'>" + p.nom + "</div>" +
          "<div class='bet-horse-cote'>" + H().formatCote(p.cote_actuelle) + "</div>" +
          "<div class='bet-horse-score " + H().scoreClass(p.score_global) + "'>" + Math.round(p.score_global) + "</div>" +
          "</div>";
      });
    } else {
      participants.forEach(function (p) {
        const checked = selectedNums.includes(p.num_pmu);
        const disabled = !checked && selectedHorses.length >= maxH;
        html += "<div class='bet-horse-row" + (checked ? " selected" : "") + (disabled ? " disabled" : "") + "' onclick='" + (disabled ? "" : "_betModalToggleHorse(" + JSON.stringify(p).replace(/"/g, "&quot;") + ")") + "'>" +
          "<div class='bet-horse-check'>" + (checked ? "✓" : "□") + "</div>" +
          "<div class='bet-horse-num'>" + p.num_pmu + "</div>" +
          "<div class='bet-horse-name'>" + p.nom + "</div>" +
          "<div class='bet-horse-cote'>" + H().formatCote(p.cote_actuelle) + "</div>" +
          "<div class='bet-horse-score " + H().scoreClass(p.score_global) + "'>" + Math.round(p.score_global) + "</div>" +
          "</div>";
      });
    }
    html += "</div>";

    // Montant
    const montants = [1, 2, 5, 10];
    html += "<div class='bet-montant-selector'>" +
      "<div class='bet-type-info'>Montant</div>" +
      "<div class='bet-montant-btns'>";
    montants.forEach(function (m) {
      html += "<button class='bet-montant-btn" + (m === selectedMontant ? " active" : "") + "' onclick='_betModalSetMontant(" + m + ")'>" + m + "€</button>";
    });
    html += "</div></div>";

    // Résumé
    const ok = selectedHorses.length === maxH;
    html += "<div class='bet-summary'>" +
      (ok
        ? selectedHorses.map(function (h) { return h.nom; }).join(" + ") + " · " + selectedMontant + "€ " + selectedType
        : "<span style='color:var(--text-muted)'>Sélectionner " + maxH + " cheval" + (maxH > 1 ? "aux" : "") + "</span>") +
      "</div>";

    html += "<button class='modal-confirm-btn" + (ok ? "" : " disabled") + "' " +
      (ok ? "onclick='_betModalConfirm()'" : "disabled") +
      ">Confirmer le pari</button>" +
      "<button class='modal-close-btn' onclick='closeModal()' style='margin-top:8px'>Annuler</button>";

    body.innerHTML = html;
  }

  // Exposer les callbacks du modal sur window
  window._betModalSetType = function (type) {
    selectedType = type;
    selectedMontant = defaultMontant(type);
    // Réinitialiser la sélection sauf si 1 cheval et nouveau type est aussi single
    if (maxHorses(type) === 1 && selectedHorses.length === 1) {
      // Garder
    } else if (maxHorses(type) === 1) {
      selectedHorses = preSelectedHorse ? [preSelectedHorse] : [];
    } else {
      selectedHorses = preSelectedHorse ? [preSelectedHorse] : [];
    }
    renderModal();
  };

  window._betModalToggleHorse = function (horse) {
    const max = maxHorses(selectedType);
    const idx = selectedHorses.findIndex(function (h) { return h.num_pmu === horse.num_pmu; });
    if (idx >= 0) {
      selectedHorses.splice(idx, 1);
    } else {
      if (max === 1) {
        selectedHorses = [horse];
      } else if (selectedHorses.length < max) {
        selectedHorses.push(horse);
      }
    }
    renderModal();
  };

  window._betModalSetMontant = function (m) {
    selectedMontant = m;
    renderModal();
  };

  window._betModalConfirm = async function () {
    const payload = {
      type_pari: selectedType,
      montant: selectedMontant,
      course_id: course.id,
      course_label: course.libelle_court || course.libelle,
      hippodrome: course.hippodrome || "",
      chevaux: selectedHorses.map(function (h) {
        return { numero: h.num_pmu, nom: h.nom, cote: h.cote_actuelle || null };
      }),
    };
    closeModal();
    await window.Bets.placeBet(payload);
  };

  renderModal();
  overlay.classList.add("open");
}

// ---- Participant Modal (détail cheval) ----
function showParticipantModal(p) {
  const overlay = document.getElementById("modal-overlay");
  const body = document.getElementById("modal-body");

  // Détecter la discipline depuis la course courante
  var discipline = (_betModalCourse && _betModalCourse.discipline) ? _betModalCourse.discipline.toUpperCase() : "PLAT";
  var isTrot = discipline.includes("ATTELE") || discipline.includes("MONTE") || discipline.includes("TROT");
  var isObstacle = discipline.includes("HAIE") || discipline.includes("STEEPLE") || discipline.includes("CROSS") || discipline.includes("OBSTACLE");
  var isTrotMonte = discipline.includes("MONTE");

  var breakdown;
  if (isTrot && !isTrotMonte) {
    // TROT_ATTELE : forme 26%, value_cote 14%, corde 16%, regularite 13%, gains 7%, recence 8%, entraineur 6%, distance 5%, age 3%, partants 2%
    breakdown = [
      { label: "Forme récente",            val: p.score_forme,                                          weight: "26%" },
      { label: "Cote / Valeur",            val: p.score_cote,                                           weight: "14%" },
      { label: "Corde (numéro départ)",    val: p.score_corde != null ? p.score_corde : 50,             weight: "16%" },
      { label: "Régularité (sans D)",      val: p.score_regularite != null ? p.score_regularite : 50,  weight: "13%" },
      { label: "Gains",                    val: p.score_gains != null ? p.score_gains : 50,             weight: "7%" },
      { label: "Récence (saison)",         val: p.score_recence != null ? p.score_recence : 50,        weight: "8%" },
      { label: "Driver / Entraîneur",      val: p.score_entraineur,                                     weight: "6%" },
      { label: "Distance",                 val: p.score_distance,                                       weight: "5%" },
      { label: "Âge",                      val: p.score_age != null ? p.score_age : 50,                weight: "3%" },
      { label: "Partants",                 val: p.score_partants || 0,                                  weight: "2%" },
    ];
  } else if (isTrotMonte) {
    // TROT_MONTE : forme 27%, value_cote 14%, corde 13%, regularite 11%, gains 7%, recence 8%, jockey 8%, entraineur 5%, distance 4%, age 3%
    breakdown = [
      { label: "Forme récente",            val: p.score_forme,                                          weight: "27%" },
      { label: "Cote / Valeur",            val: p.score_cote,                                           weight: "14%" },
      { label: "Corde (numéro départ)",    val: p.score_corde != null ? p.score_corde : 50,             weight: "13%" },
      { label: "Régularité (sans D)",      val: p.score_regularite != null ? p.score_regularite : 50,  weight: "11%" },
      { label: "Gains",                    val: p.score_gains != null ? p.score_gains : 50,             weight: "7%" },
      { label: "Récence (saison)",         val: p.score_recence != null ? p.score_recence : 50,        weight: "8%" },
      { label: "Jockey",                   val: p.score_jockey,                                         weight: "8%" },
      { label: "Entraîneur",               val: p.score_entraineur,                                     weight: "5%" },
      { label: "Distance",                 val: p.score_distance,                                       weight: "4%" },
      { label: "Âge",                      val: p.score_age != null ? p.score_age : 50,                weight: "3%" },
    ];
  } else if (isObstacle) {
    // HAIE/STEEPLE/CROSS : forme 30%, value_cote 14%, jockey 15%, terrain 15%, entraineur 8%, distance 7%, gains 5%, age 3%, partants 3%
    breakdown = [
      { label: "Forme récente",   val: p.score_forme,                                    weight: "30%" },
      { label: "Cote / Valeur",   val: p.score_cote,                                     weight: "14%" },
      { label: "Jockey",          val: p.score_jockey,                                   weight: "15%" },
      { label: "Terrain",         val: p.score_terrain,                                  weight: "15%" },
      { label: "Entraîneur",      val: p.score_entraineur,                               weight: "8%" },
      { label: "Distance",        val: p.score_distance,                                 weight: "7%" },
      { label: "Gains",           val: p.score_gains != null ? p.score_gains : 50,       weight: "5%" },
      { label: "Âge",             val: p.score_age != null ? p.score_age : 50,           weight: "3%" },
      { label: "Partants",        val: p.score_partants || 0,                            weight: "3%" },
    ];
  } else {
    // PLAT : forme 32%, value_cote 15%, jockey 12%, entraineur 8%, distance 10%, terrain 8%, repos 5%, gains 5%, age 3%, partants 2%
    breakdown = [
      { label: "Forme récente",   val: p.score_forme,                                    weight: "32%" },
      { label: "Cote / Valeur",   val: p.score_cote,                                     weight: "15%" },
      { label: "Jockey",          val: p.score_jockey,                                   weight: "12%" },
      { label: "Distance",        val: p.score_distance,                                 weight: "10%" },
      { label: "Entraîneur",      val: p.score_entraineur,                               weight: "8%" },
      { label: "Terrain",         val: p.score_terrain,                                  weight: "8%" },
      { label: "Repos",           val: p.score_repos || 0,                               weight: "5%" },
      { label: "Gains",           val: p.score_gains != null ? p.score_gains : 50,       weight: "5%" },
      { label: "Âge",             val: p.score_age != null ? p.score_age : 50,           weight: "3%" },
      { label: "Partants",        val: p.score_partants || 0,                            weight: "2%" },
    ];
  }

  const vbBadge = p.is_value_bet ? "<span class='badge badge-green'>VALUE BET</span>" : "";
  const confBadge = p.confiance === "HIGH"
    ? "<span class='badge badge-green'>" + p.confiance + "</span>"
    : p.confiance === "MEDIUM"
    ? "<span class='badge badge-gold'>" + p.confiance + "</span>"
    : "<span class='badge badge-gray'>" + p.confiance + "</span>";

  const posHtml = p.position_arrivee
    ? "<div style='margin-bottom:8px'><span class='badge' style='background:var(--gold-dim);color:var(--gold)'>Position d'arrivée : " + p.position_arrivee + "e</span></div>"
    : "";

  // Label discipline
  var discLabel = isTrot ? " · Trot" : isObstacle ? " · Obstacle" : " · Plat";

  body.innerHTML = "<div class='modal-handle'></div>" +
    "<div class='modal-title'>" + p.nom + " " + vbBadge + "</div>" +
    "<div class='modal-sub'>" +
    (p.jockey ? (isTrot ? "Driver : " : "Jockey : ") + "<strong>" + p.jockey + "</strong> · " : "") +
    (p.entraineur ? "Entraîneur : <strong>" + p.entraineur + "</strong><br>" : "") +
    "Cote : <strong>" + H().formatCote(p.cote_actuelle) + "</strong> · Score : <strong>" + Math.round(p.score_global) + "/100</strong> " + confBadge + discLabel +
    "</div>" +
    posHtml +
    "<div style='margin-bottom:12px'>" +
    "<div style='font-size:12px;color:var(--text-muted);margin-bottom:4px'>Musique (performances récentes)</div>" +
    H().renderMusiqueHtml(p.musique) +
    "</div>" +
    "<div style='font-size:12px;color:var(--text-muted);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px'>Détail du score" + discLabel + "</div>" +
    breakdown.map(function (b) {
      return "<div class='breakdown-row'>" +
        "<span class='breakdown-label'>" + b.label + " <span style='color:var(--text-dim);font-size:10px'>(" + b.weight + ")</span></span>" +
        "<div class='breakdown-bar'><div class='breakdown-bar-fill' style='width:" + b.val + "%;background:" + (b.val >= 70 ? "var(--green)" : b.val >= 50 ? "var(--gold)" : "var(--red)") + "'></div></div>" +
        "<span class='breakdown-val'>" + Math.round(b.val) + "</span>" +
        "</div>";
    }).join("") +
    "<div style='margin-top:12px;font-size:13px;color:var(--text-dim);line-height:1.5'>" + p.explication + "</div>" +
    "<button class='modal-close-btn' onclick='closeModal()'>Fermer</button>";

  // Nettoyer les callbacks modal pari
  delete window._betModalSetType;
  delete window._betModalToggleHorse;
  delete window._betModalSetMontant;
  delete window._betModalConfirm;

  overlay.classList.add("open");
}

function closeModal() {
  document.getElementById("modal-overlay").classList.remove("open");
}

// ---- Refresh ----
async function doRefresh() {
  showToast("Rechargement en cours...");
  _coursesLoaded = false;  // Forcer le rechargement des courses
  try {
    await API.refresh();
    // Récupérer aussi les arrivées des courses terminées
    try { await API.refreshResults(); } catch(e) { console.warn("Arrivées:", e); }
    showToast("Données + résultats mis à jour !");
    if (currentPage === "dashboard") loadDashboard();
    else if (currentPage === "courses") loadCourses();
    else if (currentPage === "bets") window.Bets && window.Bets.renderBetsPage();
  } catch (e) {
    showToast("Erreur lors du rechargement", true);
  }
}

// ---- Pull-to-Refresh ----
function initPullToRefresh() {
  const app = document.getElementById("app");
  let startY = 0;
  let pulling = false;
  const THRESHOLD = 60;
  const indicator = document.getElementById("ptr-indicator");

  app.addEventListener("touchstart", function (e) {
    if (window.scrollY === 0) {
      startY = e.touches[0].clientY;
      pulling = true;
    }
  }, { passive: true });

  app.addEventListener("touchmove", function (e) {
    if (!pulling) return;
    const delta = e.touches[0].clientY - startY;
    if (delta > 0 && window.scrollY === 0) {
      const progress = Math.min(delta / THRESHOLD, 1);
      if (indicator) {
        indicator.style.opacity = progress;
        indicator.style.transform = "translateY(" + (Math.min(delta, THRESHOLD) - THRESHOLD) + "px)";
      }
    }
  }, { passive: true });

  app.addEventListener("touchend", function (e) {
    if (!pulling) return;
    pulling = false;
    const delta = e.changedTouches[0].clientY - startY;
    if (indicator) {
      indicator.style.opacity = 0;
      indicator.style.transform = "translateY(-60px)";
    }
    if (delta >= THRESHOLD) doRefresh();
  }, { passive: true });
}

// ---- Init ----
window.onerror = function (msg, src, line, col, err) {
  console.error("JS Error:", msg, "at", src, line, col, err);
};

// ---- Bannière offline ----
(function () {
  function setOfflineBanner(offline) {
    var existing = document.getElementById("offline-banner");
    if (offline) {
      if (existing) return;
      var banner = document.createElement("div");
      banner.id = "offline-banner";
      banner.textContent = "📵 Hors ligne — données du dernier chargement";
      banner.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:9999;background:#b45309;color:#fff;text-align:center;font-size:12px;padding:5px 8px;letter-spacing:.3px;";
      document.body.prepend(banner);
    } else {
      if (existing) existing.remove();
    }
  }
  window.addEventListener("online",  function () { setOfflineBanner(false); });
  window.addEventListener("offline", function () { setOfflineBanner(true); });
  if (!navigator.onLine) setOfflineBanner(true);
})();

function _appInit() {
  try {
    document.querySelectorAll(".nav-item").forEach(function (item) {
      item.addEventListener("click", function () { navigate(item.dataset.nav); });
    });

    const backBtn = document.getElementById("page-course-back-btn");
    if (backBtn) {
      backBtn.addEventListener("click", function () {
        navigate("courses");
        backBtn.style.display = "none";
      });
    }

    const overlay = document.getElementById("modal-overlay");
    if (overlay) {
      overlay.addEventListener("click", function (e) {
        if (e.target === overlay) closeModal();
      });
    }

    const now = new Date();
    const dateLabel = now.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });
    document.querySelectorAll(".date-badge").forEach(function (el) { el.textContent = dateLabel; });

    initPullToRefresh();
    navigate("dashboard");
  } catch (err) {
    console.error("Init error:", err);
    document.getElementById("dashboard-content").innerHTML =
      "<div class='empty-state'><div class='empty-icon'>⚠️</div><div class='empty-title'>Erreur d'initialisation</div><p style='color:var(--text-muted);font-size:13px'>" + err.message + "</p></div>";
  }
}

// Expose so auth.js can call it after login
window._appInit = _appInit;

document.addEventListener("DOMContentLoaded", function () {
  // Check authentication before starting the app
  if (window.Auth && window.Auth.boot) {
    var hasToken = window.Auth.boot();
    if (!hasToken) return; // login screen shown by boot()
  }
  _appInit();
});

window.showCourse = showCourse;
window.showParticipantModal = showParticipantModal;
window.showBetModal = showBetModal;
window.placeSuggestedBet = placeSuggestedBet;
window.placeSuggestedBetByKey = placeSuggestedBetByKey;
window.closeModal = closeModal;
window.doRefresh = doRefresh;
window.navigate = navigate;
window.showToast = showToast;
window.setScoringMode = setScoringMode;

// =============================================================================
// PAGE STATS AVANCÉES
// =============================================================================

async function loadStatsPage() {
  const container = document.getElementById("stats-content");
  if (!container) return;
  container.innerHTML = '<div class="stats-loading"><div class="spinner"></div><p>Chargement des statistiques…</p></div>';

  try {
    const [scoringData, calibData] = await Promise.all([
      API.statsScoring(),
      API.statsCalibration(),
    ]);
    container.innerHTML = renderStatsPage(scoringData, calibData);
  } catch (e) {
    container.innerHTML = '<div class="stats-error">Erreur lors du chargement des statistiques.<br>' + (e.message || "") + "</div>";
  }
}

function _rateBadge(rate) {
  var cls = rate >= 40 ? "badge-green" : rate >= 25 ? "badge-orange" : "badge-red";
  return '<span class="stat-badge ' + cls + '">' + rate + "%</span>";
}

function _progressBar(value, max) {
  var pct = Math.min(100, Math.round((value / max) * 100));
  return (
    '<div class="prog-bar-wrap">' +
    '<div class="prog-bar" style="width:' + pct + '%"></div>' +
    '<span class="prog-bar-label">' + pct + "%</span>" +
    "</div>"
  );
}

function renderStatsPage(scoringData, calibData) {
  var html = '<div class="stats-page">';

  // ── Header ──────────────────────────────────────────────────────────────────
  html += '<div class="stats-header">';
  html += '<h2 class="stats-title">Stats avancées — Scoring</h2>';
  html += '<p class="stats-subtitle">Expert (poids manuels) vs Auto-calibré (historique)</p>';
  html += '<button class="btn-calibrate" onclick="doCalibrate()">Recalibrer maintenant</button>';
  html += "</div>";

  var discs = (scoringData && scoringData.disciplines) ? scoringData.disciplines : {};
  var calDiscs = (calibData && calibData.disciplines) ? calibData.disciplines : {};
  var totalCourses = (scoringData && scoringData.total_courses) || 0;

  // ── Résumé global ────────────────────────────────────────────────────────────
  html += '<div class="stats-summary-row">';
  html += '<div class="stats-summary-card"><div class="ssc-value">' + totalCourses + '</div><div class="ssc-label">Courses analysées</div></div>';

  var modeActif = calibData && calibData.calibrated ? "Auto" : "Expert";
  var modeClass = calibData && calibData.calibrated ? "mode-auto" : "mode-expert";
  html += '<div class="stats-summary-card"><div class="ssc-value ' + modeClass + '">' + modeActif + '</div><div class="ssc-label">Mode actif global</div></div>';

  if (calibData && calibData.last_updated_global) {
    var dt = new Date(calibData.last_updated_global);
    var dtStr = dt.toLocaleDateString("fr-FR") + " " + dt.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    html += '<div class="stats-summary-card"><div class="ssc-value ssc-small">' + dtStr + '</div><div class="ssc-label">Dernière calibration</div></div>';
  } else {
    html += '<div class="stats-summary-card"><div class="ssc-value ssc-small">—</div><div class="ssc-label">Dernière calibration</div></div>';
  }
  html += "</div>";

  // ── Évolution 7j ─────────────────────────────────────────────────────────────
  if (scoringData && scoringData.evolution) {
    var ev = scoringData.evolution;
    var trendIcon = ev.trend === "up" ? "↑" : ev.trend === "down" ? "↓" : "→";
    var trendCls  = ev.trend === "up" ? "trend-up" : ev.trend === "down" ? "trend-down" : "trend-stable";
    html += '<div class="stats-section">';
    html += '<h3 class="stats-section-title">Évolution du taux top-1 <span class="trend-icon ' + trendCls + '">' + trendIcon + "</span></h3>";
    html += '<div class="evolution-row">';
    html += '<div class="evolution-card"><div class="ev-label">7 derniers jours</div>';
    html += '<div class="ev-value">' + _rateBadge(ev.last_7d.top1_rate) + '</div>';
    html += '<div class="ev-sub">' + ev.last_7d.nb_courses + " courses</div></div>";
    html += '<div class="evolution-card"><div class="ev-label">7 jours précédents</div>';
    html += '<div class="ev-value">' + _rateBadge(ev.prev_7d.top1_rate) + '</div>';
    html += '<div class="ev-sub">' + ev.prev_7d.nb_courses + " courses</div></div>";
    html += "</div></div>";
  }

  // ── Taux de réussite par discipline ──────────────────────────────────────────
  html += '<div class="stats-section">';
  html += '<h3 class="stats-section-title">Taux de réussite par discipline</h3>';

  var discKeys = Object.keys(discs);
  if (discKeys.length === 0) {
    html += '<p class="stats-empty">Pas encore de courses terminées.</p>';
  } else {
    discKeys.forEach(function (disc) {
      var d = discs[disc];
      var calD = calDiscs[disc] || {};
      var modeBadge = calD.active_mode === "auto"
        ? '<span class="mode-badge mode-auto">Auto</span>'
        : '<span class="mode-badge mode-expert">Expert</span>';

      html += '<div class="disc-card">';
      html += '<div class="disc-card-header">';
      html += '<span class="disc-name">' + disc + '</span>';
      html += modeBadge;
      html += '<span class="disc-count">' + d.nb_courses + " courses</span>";
      html += "</div>";

      if (!d.has_auto_data) {
        var min = (scoringData.min_courses_required || 10);
        html += '<div class="disc-progress-msg">Calibration auto disponible après ' + min + ' courses. ';
        html += _progressBar(d.nb_courses, min);
        html += "</div>";
      }

      // Tableau comparatif Expert vs Auto
      html += '<table class="stats-table">';
      html += "<thead><tr><th>Critère</th><th>Expert</th><th>Auto</th></tr></thead><tbody>";
      html += "<tr><td>Top-1 exact</td><td>" + _rateBadge(d.expert.top1_rate) + "</td><td>" + _rateBadge(d.auto.top1_rate) + "</td></tr>";
      html += "<tr><td>Top-3 prédits</td><td>" + _rateBadge(d.expert.top3_rate) + "</td><td>" + _rateBadge(d.auto.top3_rate) + "</td></tr>";
      html += "<tr><td>Top-5 prédits</td><td>" + _rateBadge(d.expert.top5_rate) + "</td><td>" + _rateBadge(d.auto.top5_rate) + "</td></tr>";
      html += "</tbody></table>";
      html += "</div>"; // disc-card
    });
  }
  html += "</div>"; // stats-section

  // ── Poids auto-calibrés ───────────────────────────────────────────────────────
  html += '<div class="stats-section">';
  html += '<h3 class="stats-section-title">Poids auto-calibrés actuels</h3>';

  var calDiscKeys = Object.keys(calDiscs);
  if (calDiscKeys.length === 0) {
    html += '<p class="stats-empty">Aucune calibration auto disponible. Cliquez sur "Recalibrer maintenant".</p>';
  } else {
    calDiscKeys.forEach(function (disc) {
      var calD = calDiscs[disc];
      if (!calD.auto_weights) return;

      html += '<div class="weights-card">';
      html += '<div class="weights-card-title">' + disc;
      if (calD.last_updated) {
        var d2 = new Date(calD.last_updated);
        html += ' <span class="weights-date">MAJ: ' + d2.toLocaleDateString("fr-FR") + "</span>";
      }
      html += "</div>";

      // Barres horizontales pour chaque critère
      var entries = Object.entries(calD.auto_weights || {}).sort(function (a, b) { return b[1] - a[1]; });
      var expertWeights = calD.expert_weights || {};

      entries.forEach(function (kv) {
        var critere = kv[0];
        var autoVal = kv[1];
        var expertVal = expertWeights[critere] || 0;
        var autoPct = Math.round(autoVal * 100);
        var expertPct = Math.round(expertVal * 100);

        html += '<div class="weight-row">';
        html += '<span class="weight-label">' + critere + "</span>";
        html += '<div class="weight-bars">';
        // Expert bar
        html += '<div class="weight-bar-group">';
        html += '<span class="wb-tag expert-tag">Expert</span>';
        html += '<div class="wb-track"><div class="wb-fill expert-fill" style="width:' + Math.min(100, expertPct * 3) + '%"></div></div>';
        html += '<span class="wb-pct">' + expertPct + "%</span>";
        html += "</div>";
        // Auto bar
        html += '<div class="weight-bar-group">';
        html += '<span class="wb-tag auto-tag">Auto</span>';
        html += '<div class="wb-track"><div class="wb-fill auto-fill" style="width:' + Math.min(100, autoPct * 3) + '%"></div></div>';
        html += '<span class="wb-pct">' + autoPct + "%</span>";
        html += "</div>";
        html += "</div>"; // weight-bars
        html += "</div>"; // weight-row
      });

      html += "</div>"; // weights-card
    });
  }
  html += "</div>"; // stats-section

  html += "</div>"; // stats-page
  return html;
}

async function doCalibrate() {
  var btn = document.querySelector(".btn-calibrate");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Calibration en cours…";
  }
  try {
    var result = await API.calibrate();
    var msg = "Calibration terminée. Disciplines calibrées: " +
      ((result.disciplines_calibrated || []).join(", ") || "aucune");
    showToast(msg);
    // Recharger la page stats
    loadStatsPage();
  } catch (e) {
    showToast("Erreur lors de la calibration: " + (e.message || ""), true);
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Recalibrer maintenant";
    }
  }
}

window.doCalibrate = doCalibrate;
