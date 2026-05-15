/* =============================================
   PMU Smart Analyzer — Main App JS v3
   ============================================= */

let currentPage = "dashboard";
var _coursesScrollPos = 0;
var _coursesLoaded = false;
var _coursesData = null;        // cache reunions pour le tri
var _coursesSortMode = "default"; // "default" | "heure"
let _betModalCourse = null;   // course courante pour le modal de pari
var _scoringMode = "auto"; // "auto" | "expert" | "sans_cote"

// Cache de chargement par page : null = jamais chargé, sinon timestamp (ms)
var _pageLoaded = {
  dashboard: null,
  courses: null,
  stats: null,
  bilan: null,
  pronostics: null
};
var PAGE_TTL_MS = 60 * 1000; // 60 secondes

const H = () => window.Components;

// ---- Helpers cache ----
function _isPageFresh(page) {
  var ts = _pageLoaded[page];
  if (!ts) return false;
  return (Date.now() - ts) < PAGE_TTL_MS;
}

function _markPageLoaded(page) {
  _pageLoaded[page] = Date.now();
}

function _invalidatePage(page) {
  _pageLoaded[page] = null;
}

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

  if (page === "dashboard") {
    if (!_isPageFresh("dashboard")) {
      loadDashboard();
    }
  } else if (page === "courses") {
    // Les courses changent souvent (statuts) : toujours recharger
    loadCourses();
  } else if (page === "pronostics") {
    if (!_isPageFresh("pronostics")) {
      loadPronosticsPage();
    }
  } else if (page === "stats") {
    if (!_isPageFresh("stats")) {
      loadStatsPage();
    }
  } else if (page === "bilan") {
    if (!_isPageFresh("bilan")) {
      loadBilanPage();
    }
  }
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

  try {
    const [data, stats, accuracy, trend] = await Promise.all([
      API.dashboard(),
      API.stats().catch(function () { return null; }),
      API.scoringAccuracyByDiscipline().catch(function () { return null; }),
      API.scoringAccuracyTrend().catch(function () { return null; }),
    ]);
    if (data && data.offline) {
      content.innerHTML = "<div class='empty-state'><div class='empty-icon'>📵</div><div class='empty-title'>Hors ligne</div><p style='color:var(--text-muted);font-size:13px'>Reconnectez-vous pour voir les données du jour.</p></div>";
      return;
    }
    renderDashboard(data, stats, accuracy, trend);
    _markPageLoaded("dashboard");
  } catch (e) {
    if (e && e.isAuthError) return; // 401 → login screen already shown by apiFetch
    console.error("Dashboard error:", e);
    content.innerHTML = "<div class='empty-state'><div class='empty-icon'>⚠️</div><div class='empty-title'>Impossible de charger les données</div><p style='color:var(--text-muted);font-size:13px'>Vérifiez votre connexion internet</p></div>";
    showToast("Erreur de chargement", true);
  }
}

function renderDashboard(data, stats, accuracy, trend) {
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
    html += renderAccuracyCard(accuracy, trend);
  }

  if (stats && stats.length) {
    html += renderStatsChart(stats);
  }

  if (data.top_picks && data.top_picks.length > 0) {
    // Construire un index course_id → {reunion_num, course_num, hippodrome, heure_depart}
    var _courseIndex = {};
    if (data.reunions) {
      data.reunions.forEach(function (r) {
        r.courses.forEach(function (c) {
          _courseIndex[c.id] = {
            reunion_num: r.num_officiel,
            course_num: c.num_ordre,
            hippodrome: r.hippodrome_libelle,
            heure_depart: c.heure_depart
          };
        });
      });
    }

    html += "<div class='section-title'>Top Picks du Jour</div>";
    data.top_picks.forEach(function (p, i) {
      const medal = i === 0 ? "1er" : i === 1 ? "2e" : "3e";
      const vb = p.is_value_bet ? "<span class='badge badge-green' style='margin-left:6px'>VALUE BET</span>" : "";
      var courseInfo = _courseIndex[p.course_id];
      var courseInfoHtml = "";
      if (courseInfo) {
        var heureStr = courseInfo.heure_depart ? H().formatTime(courseInfo.heure_depart) : "";
        courseInfoHtml = "<div style='font-size:11px;color:var(--text-muted);margin-top:2px'>" +
          "R" + courseInfo.reunion_num + " C" + courseInfo.course_num +
          (courseInfo.hippodrome ? " &mdash; " + courseInfo.hippodrome : "") +
          (heureStr ? " &mdash; " + heureStr : "") +
          "</div>";
      }
      var onclickAttr = courseInfo
        ? "onclick='navigate(\"pronostics\")' style='padding:12px 16px;cursor:pointer'"
        : "style='padding:12px 16px'";
      html += "<div class='card clickable' " + onclickAttr + ">" +
        "<div style='display:flex;align-items:center;gap:10px'>" +
        "<span style='font-size:22px;min-width:36px;text-align:center;font-weight:800;color:var(--gold)'>" + medal + "</span>" +
        "<div style='flex:1;min-width:0'>" +
        "<div style='font-weight:700;font-size:15px'>" + p.nom + vb + "</div>" +
        courseInfoHtml +
        "<div style='font-size:12px;color:var(--text-muted);margin-top:2px'>" + (p.jockey || "—") + " · Cote " + H().formatCote(p.cote_actuelle) + "</div>" +
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

// ---- F2 : Card précision modèle ----
function renderAccuracyCard(accuracy, trend) {
  // accuracy vient de /api/scoring/accuracy-by-discipline
  // Format: [{discipline, critere, poids, precision, nb_samples}, ...]
  // trend (optionnel): [{discipline, precision_all, nb_all, precision_recent, nb_recent}, ...]

  // Index trend par discipline
  var trendByDisc = {};
  if (trend && trend.length) {
    trend.forEach(function (t) { trendByDisc[t.discipline] = t; });
  }

  // Grouper par discipline
  var byDisc = {};
  accuracy.forEach(function (a) {
    if (!byDisc[a.discipline]) byDisc[a.discipline] = [];
    byDisc[a.discipline].push(a);
  });

  // Par discipline : précision moyenne + nb_samples d'un seul critère représentatif
  var discStats = [];
  Object.keys(byDisc).sort().forEach(function (disc) {
    var rows = byDisc[disc];
    var active = rows.filter(function (r) { return r.nb_samples > 0; });
    if (active.length === 0) return; // ignorer disciplines sans données
    var avgPrecision = active.reduce(function (s, r) { return s + r.precision; }, 0) / active.length;
    var rep = active.find(function (r) { return r.critere === "forme_recente"; }) || active[0];
    discStats.push({ disc: disc, precision: avgPrecision, nb_samples: rep.nb_samples });
  });

  if (discStats.length === 0) {
    return "<div class='accuracy-card'><div class='accuracy-title'>Précision modèle IA</div>" +
      "<div style='font-size:12px;color:var(--text-muted)'>Pas encore de données — lancez l'optimisation pour calibrer le modèle</div></div>";
  }

  var html = "<div class='accuracy-card'><div class='accuracy-title'>Précision modèle IA</div>";
  discStats.forEach(function (d) {
    // Indicateur de tendance basé sur les 30 dernières courses
    var trendHtml = "";
    var t = trendByDisc[d.disc];
    if (t && t.nb_recent >= 5) {
      var diff = (t.precision_recent - t.precision_all) * 100; // en points de %
      if (diff >= 2) {
        trendHtml = "<span title='Hausse: +" + Math.round(diff) + " pts sur 30 dernières courses' " +
          "style='font-size:13px;color:var(--green);margin-left:4px;font-weight:700'>↑</span>";
      } else if (diff <= -2) {
        trendHtml = "<span title='Baisse: " + Math.round(diff) + " pts sur 30 dernières courses' " +
          "style='font-size:13px;color:var(--red);margin-left:4px;font-weight:700'>↓</span>";
      } else {
        trendHtml = "<span title='Stable (écart: " + (diff >= 0 ? "+" : "") + Math.round(diff) + " pts sur 30 dernières courses)' " +
          "style='font-size:13px;color:var(--orange, #f59e0b);margin-left:4px;font-weight:700'>→</span>";
      }
    }
    html += "<div class='accuracy-row' style='margin-bottom:4px'>" +
      "<span class='accuracy-label'>" + d.disc + "</span>" +
      "<span style='font-size:16px;font-weight:700;color:var(--blue)'>" + Math.round(d.precision * 100) + "%" + trendHtml + "</span>" +
      "<span style='font-size:11px;color:var(--text-muted);min-width:80px;text-align:right'>" + d.nb_samples + " courses</span>" +
      "</div>";
  });
  html += "</div>";
  return html;
}

// ---- Stats Chart (7 jours) ----
function renderStatsChart(stats) {
  const maxCourses = Math.max.apply(null, stats.map(function (s) { return s.nb_courses || 0; }).concat([1]));
  let html = "<div class='section-title'>📈 Stats 7 Derniers Jours</div><div class='stats-chart'>";
  stats.forEach(function (s) {
    const pct = Math.round(((s.nb_courses || 0) / maxCourses) * 100);
    const pctVb = maxCourses > 0 ? Math.round(((s.nb_value_bets || 0) / maxCourses) * 100) : 0;
    const label = s.date ? s.date.slice(8, 10) + '/' + s.date.slice(5, 7) : "—";
    html += "<div class='stat-bar-col'>" +
      "<div class='stat-bar-track'>" +
      "<div class='stat-bar-pair'>" +
      "<div class='stat-bar-fill courses' style='height:" + pct + "%' title='Courses: " + (s.nb_courses || 0) + "'></div>" +
      "<div class='stat-bar-fill vb' style='height:" + pctVb + "%' title='Value Bets: " + (s.nb_value_bets || 0) + "'></div>" +
      "</div>" +
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
    _coursesData = reunions;
    renderCoursesList(reunions);
    _coursesLoaded = true;
    _markPageLoaded("courses");
    // Restaurer la position de scroll si applicable
    setTimeout(function() { window.scrollTo(0, _coursesScrollPos); }, 50);
  } catch (e) {
    if (e && e.isAuthError) return; // 401 → login screen already shown by apiFetch
    content.innerHTML = "<div class='empty-state'><div class='empty-icon'>⚠️</div><div class='empty-title'>Erreur de chargement</div></div>";
    showToast("Erreur de chargement", true);
  }
}

function _applyCourseSort(reunions, mode) {
  if (mode === "heure") {
    // Aplatir toutes les courses, trier par heure_depart, puis reconstruire
    var allCourses = [];
    reunions.forEach(function (r) {
      r.courses.forEach(function (c) {
        allCourses.push({ course: c, hippodrome: r.hippodrome_libelle, reunion_num: r.num_officiel });
      });
    });
    allCourses.sort(function (a, b) {
      var ha = a.course.heure_depart || "";
      var hb = b.course.heure_depart || "";
      return ha < hb ? -1 : ha > hb ? 1 : 0;
    });
    return allCourses; // flat list
  }
  return null; // default: grouped by reunion
}

function renderCoursesList(reunions) {
  const content = document.getElementById("courses-content");
  if (!reunions || !reunions.length) {
    content.innerHTML = "<div class='empty-state'><div class='empty-icon'>🐴</div><div class='empty-title'>Aucune course aujourd'hui</div></div>";
    return;
  }

  // Barre de tri
  var sortBar = "<div class='courses-sort-bar'>" +
    "<span class='courses-sort-label'>Tri :</span>" +
    "<select class='courses-sort-select' id='courses-sort-select' onchange='_onCoursesSortChange(this.value)'>" +
    "<option value='default'" + (_coursesSortMode === "default" ? " selected" : "") + ">Par défaut</option>" +
    "<option value='heure'" + (_coursesSortMode === "heure" ? " selected" : "") + ">Par heure de départ</option>" +
    "</select>" +
    "</div>";

  var listHtml = "";
  if (_coursesSortMode === "heure") {
    var flat = _applyCourseSort(reunions, "heure");
    flat.forEach(function (item) {
      listHtml += H().renderCourseCard(item.course, item.hippodrome, { reunion_num: item.reunion_num, showContext: true });
    });
  } else {
    reunions.forEach(function (r) {
      listHtml += "<div class='hipp-header'>" +
        "<span class='hipp-icon'>🏟️</span>" +
        "<span class='hipp-name'>" + r.hippodrome_libelle + "</span>" +
        "<span class='hipp-count'>" + r.courses.length + " courses · R" + r.num_officiel + "</span>" +
        "</div>";
      r.courses.forEach(function (c) {
        listHtml += H().renderCourseCard(c, r.hippodrome_libelle);
      });
    });
  }

  content.innerHTML = sortBar + listHtml;
}

function _onCoursesSortChange(mode) {
  _coursesSortMode = mode;
  if (_coursesData) {
    renderCoursesList(_coursesData);
  }
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
    if (e && e.isAuthError) return; // 401 → login screen already shown by apiFetch
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

  // Pronostics Equidia — zone placeholder (chargé en async)
  html += "<div id='prono-equidia'></div>";

  if (course.participants && course.participants.length > 0) {
    var sectionTitle = _scoringMode === "sans_cote"
      ? "Partants (score sans cote)"
      : _scoringMode === "expert"
      ? "Partants (score Expert)"
      : _scoringMode === "cote_reelle"
      ? "Partants (cote r\u00e9elle)"
      : "Partants (score Auto)";

    // Tri selon le mode
    var sorted = course.participants.slice().sort(function(a, b) {
      var sa, sb;
      if (_scoringMode === "sans_cote") {
        sa = a.score_sans_cote || 0;
        sb = b.score_sans_cote || 0;
      } else if (_scoringMode === "expert") {
        sa = a.score_global_expert || 0;
        sb = b.score_global_expert || 0;
      } else if (_scoringMode === "cote_reelle" && course._liveScores) {
        var la = course._liveScores[a.num_pmu];
        var lb = course._liveScores[b.num_pmu];
        sa = la ? la.score_live : (a.score_global_auto || 0);
        sb = lb ? lb.score_live : (b.score_global_auto || 0);
      } else {
        sa = a.score_global_auto || 0;
        sb = b.score_global_auto || 0;
      }
      return sb - sa;
    });

    // Badge fallback: mode auto + 1er cheval a score_global_auto == score_global_expert ou == 0
    var fallbackBadge = "";
    if (_scoringMode === "auto" && sorted.length > 0) {
      var first = sorted[0];
      var autoScore = first.score_global_auto || 0;
      var expertScore = first.score_global_expert || 0;
      if (autoScore === 0 || autoScore === expertScore) {
        fallbackBadge = "<span class='fallback-badge'>(= Expert)</span>";
      }
    }

    html += "<div style='display:flex;align-items:center;justify-content:space-between;padding:16px 16px 4px;flex-wrap:wrap;gap:6px'>" +
      "<span class='section-title' style='padding:0;margin:0'>" + sectionTitle + fallbackBadge + "</span>" +
      "<div class='scoring-toggle'>" +
      "<button class='scoring-toggle-btn" + (_scoringMode === "auto" ? " active" : "") + "' onclick='setScoringMode(\"auto\")'>Auto</button>" +
      "<button class='scoring-toggle-btn" + (_scoringMode === "expert" ? " active" : "") + "' onclick='setScoringMode(\"expert\")'>Expert</button>" +
      "<button class='scoring-toggle-btn" + (_scoringMode === "sans_cote" ? " active" : "") + "' onclick='setScoringMode(\"sans_cote\")'>Sans cote</button>" +
      "<button class='scoring-toggle-btn" + (_scoringMode === "cote_reelle" ? " active" : "") + "' onclick='setScoringMode(\"cote_reelle\")'>Cote r\u00e9elle</button>" +
      "</div>" +
      "</div>";

    html += "<div class='card' style='padding:0 16px' id='participants-list'>";
    sorted.forEach(function (p, i) {
      html += renderParticipantRowWithBet(p, i + 1, course, course.hippodrome);
    });
    html += "</div>";
  } else {
    html += "<div class='empty-state'><div class='empty-icon'>🐴</div><div class='empty-title'>Partants non disponibles</div><p style='color:var(--text-muted);font-size:13px'>Les partants ne sont pas encore publiés</p></div>";
  }

  content.innerHTML = html;

  // Charger les pronostics Equidia en async
  _loadPronostics(course.id);
}

async function _loadPronostics(courseId) {
  var container = document.getElementById("prono-equidia");
  if (!container) return;
  try {
    var data = await API.pronostics(courseId);
    if (!data || !data.selection || data.selection.length === 0) {
      container.innerHTML = "";
      return;
    }
    var nums = data.selection.map(function(s) { return s.num_partant; });
    var source = data.source || "PMU";
    container.innerHTML = "<div class='reco-banner' style='border-left:4px solid var(--gold);background:var(--surface)'>" +
      "<div class='reco-title' style='color:var(--gold)'>\uD83D\uDCF0 Prono " + source + "</div>" +
      "<div style='font-size:15px;font-weight:600;letter-spacing:1px'>" + nums.join(" - ") + "</div>" +
      "</div>";
  } catch (e) {
    container.innerHTML = "";
  }
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
  var displayScore;
  if (_scoringMode === "sans_cote") {
    displayScore = p.score_sans_cote != null ? p.score_sans_cote : (p.score_global || 0);
  } else if (_scoringMode === "expert") {
    displayScore = p.score_global_expert != null ? p.score_global_expert : (p.score_global || 0);
  } else if (_scoringMode === "cote_reelle" && _betModalCourse && _betModalCourse._liveScores) {
    var liveP = _betModalCourse._liveScores[p.num_pmu];
    displayScore = liveP ? liveP.score_live : (p.score_global_auto || 0);
  } else {
    // auto: score_global_auto, fallback expert, fallback global
    displayScore = p.score_global_auto != null ? p.score_global_auto : (p.score_global_expert != null ? p.score_global_expert : (p.score_global || 0));
  }

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
    "</div>";
}

// ---- Toggle mode scoring ----
async function setScoringMode(mode) {
  _scoringMode = mode;
  if (_betModalCourse) {
    if (mode === "cote_reelle") {
      // Appel API pour recalculer avec cotes fraîches
      var container = document.getElementById("participants-list");
      if (container) container.innerHTML = '<div class="stats-loading"><div class="spinner"></div><p>Calcul avec cotes r\u00e9elles\u2026</p></div>';
      try {
        var data = await API.liveScores(_betModalCourse.id);
        // Stocker les scores live dans les participants
        _betModalCourse._liveScores = {};
        data.participants.forEach(function(p) {
          _betModalCourse._liveScores[p.num_pmu] = p;
        });
      } catch (e) {
        console.warn("Erreur live-scores:", e);
      }
    }
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
var _refreshing = false;
async function doRefresh() {
  if (_refreshing) return;
  _refreshing = true;
  // Mettre en pause le polling auto pour éviter les conflits DB concurrents
  if (_autoPollingInterval) {
    clearInterval(_autoPollingInterval);
    _autoPollingInterval = null;
  }
  showToast("Rechargement en cours...");
  // Invalider la page courante pour forcer rechargement
  _invalidatePage(currentPage);
  _coursesLoaded = false;
  var refreshOk = false;
  try {
    await API.refresh();
    refreshOk = true;
  } catch(e) {
    console.error("Refresh programme:", e);
  }
  try { await API.refreshProgramme(); } catch(e) { console.warn("Refresh statuts:", e); }
  // Récupérer aussi les arrivées des courses terminées
  try { await API.refreshResults(); } catch(e) { console.warn("Arrivées:", e); }
  showToast(refreshOk ? "Données + résultats mis à jour !" : "Rechargement partiel — vérifiez la connexion");
  // Toujours recharger la page courante même en cas d'erreur partielle
  if (currentPage === "dashboard") loadDashboard();
  else if (currentPage === "courses") loadCourses();
  else if (currentPage === "pronostics") loadPronosticsPage();
  else if (currentPage === "stats") loadStatsPage();
  else if (currentPage === "bilan") loadBilanPage();
  else if (currentPage === "course" && _betModalCourse) showCourse(_betModalCourse.id);
  _refreshing = false;
  // Reprendre le polling auto après le refresh
  startAutoPolling();
}

// ---- Pull-to-Refresh ----
function initPullToRefresh() {
  const app = document.getElementById("app");
  let startY = 0;
  let pulling = false;
  const THRESHOLD = 60;
  const indicator = document.getElementById("ptr-indicator");

  app.addEventListener("touchstart", function (e) {
    pulling = false;
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

// ---- Auto-polling des résultats (toutes les 2 minutes) ----
var _autoPollingInterval = null;
var AUTO_POLL_INTERVAL_MS = 2 * 60 * 1000; // 2 minutes

async function _pollResults() {
  if (_refreshing) return; // Ne pas polluer pendant un refresh manuel
  try {
    var result = await API.refreshResults();
    var updated = result && result.courses_updated ? result.courses_updated : 0;
    if (updated > 0) {
      // Invalider le cache des pages concernées
      _invalidatePage("courses");
      _invalidatePage("bilan");
      _invalidatePage("dashboard");
      // Recharger silencieusement la page active
      if (currentPage === "courses") loadCourses();
      else if (currentPage === "bilan") loadBilanPage();
      else if (currentPage === "dashboard") loadDashboard();
    }
  } catch (e) {
    // Polling silencieux : ignorer les erreurs réseau
    console.warn("Auto-polling résultats:", e);
  }
}

function startAutoPolling() {
  if (_autoPollingInterval) clearInterval(_autoPollingInterval);
  _autoPollingInterval = setInterval(_pollResults, AUTO_POLL_INTERVAL_MS);
  // Déclencher immédiatement au démarrage sans attendre le premier cycle de 2 min
  setTimeout(_pollResults, 3000);
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
    startAutoPolling();
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
  // boot() now handles _appInit() call itself after token verification
  if (window.Auth && window.Auth.boot) {
    window.Auth.boot(); // boot handles _appInit() or showLoginScreen() internally
    return;
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
    _markPageLoaded("stats");
  } catch (e) {
    if (e && e.isAuthError) return; // 401 → login screen already shown by apiFetch
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
  html += '<p class="stats-subtitle">Expert (poids manuels) vs Auto-calibré (historique) vs Sans cote</p>';
  html += '<button class="btn-calibrate" onclick="doCalibrate()">Recalibrer maintenant</button>';
  html += "</div>";

  var discs = (scoringData && scoringData.disciplines) ? scoringData.disciplines : {};
  var calDiscs = (calibData && calibData.disciplines) ? calibData.disciplines : {};
  var totalCourses = (scoringData && scoringData.total_courses) || 0;
  var summary = (scoringData && scoringData.discipline_summary) ? scoringData.discipline_summary : [];

  // ── Résumé modes recommandés par discipline ───────────────────────────────
  if (summary.length > 0) {
    html += '<div class="stats-section stats-section-recommande">';
    html += '<h3 class="stats-section-title">Mode recommandé par discipline</h3>';
    html += '<div class="recommande-row">';
    summary.forEach(function (s) {
      var modeLabel = s.mode_recommande === "auto" ? "Auto" : s.mode_recommande === "sans_cote" ? "Sans cote" : "Expert";
      var modeCls   = s.mode_recommande === "auto" ? "mode-auto" : s.mode_recommande === "sans_cote" ? "mode-sans-cote" : "mode-expert";
      var taux = s.mode_recommande === "auto" ? s.taux_auto : s.mode_recommande === "sans_cote" ? s.taux_sans_cote : s.taux_expert;
      html += '<div class="recommande-card">';
      html += '<div class="rec-disc">' + s.discipline + '</div>';
      html += '<div class="rec-mode ' + modeCls + '">' + modeLabel + '</div>';
      html += '<div class="rec-taux">' + _rateBadge(taux) + '</div>';
      html += '</div>';
    });
    html += '</div></div>';
  }

  // ── Résumé global ────────────────────────────────────────────────────────────
  html += '<div class="stats-summary-row">';
  html += '<div class="stats-summary-card"><div class="ssc-value">' + totalCourses + '</div><div class="ssc-label">Courses analysées</div></div>';

  // Mode actif global = mode le plus souvent recommandé parmi les disciplines
  var modeCounters = { expert: 0, auto: 0, sans_cote: 0 };
  summary.forEach(function (s) { if (modeCounters[s.mode_recommande] !== undefined) modeCounters[s.mode_recommande]++; });
  var globalBestMode = Object.keys(modeCounters).reduce(function (a, b) { return modeCounters[a] >= modeCounters[b] ? a : b; }, "expert");
  var modeActifLabel = globalBestMode === "auto" ? "Auto" : globalBestMode === "sans_cote" ? "Sans cote" : "Expert";
  var modeActifCls   = globalBestMode === "auto" ? "mode-auto" : globalBestMode === "sans_cote" ? "mode-sans-cote" : "mode-expert";
  html += '<div class="stats-summary-card"><div class="ssc-value ' + modeActifCls + '">' + modeActifLabel + '</div><div class="ssc-label">Mode actif global</div></div>';

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

  // ── Taux de réussite Top-1 par discipline ─────────────────────────────────
  html += '<div class="stats-section">';
  html += '<h3 class="stats-section-title">Taux Top-1 par discipline</h3>';

  var discKeys = Object.keys(discs);
  if (discKeys.length === 0) {
    html += '<p class="stats-empty">Pas encore de courses terminées.</p>';
  } else {
    discKeys.forEach(function (disc) {
      var d    = discs[disc];
      var calD = calDiscs[disc] || {};
      // Mode recommandé depuis les données scoring (taux réels) — fallback active_mode calibration
      var modeRec = d.mode_recommande || calD.active_mode || "expert";
      var modeBadgeLabel = modeRec === "auto" ? "Auto" : modeRec === "sans_cote" ? "Sans cote" : "Expert";
      var modeBadgeCls   = modeRec === "auto" ? "mode-auto" : modeRec === "sans_cote" ? "mode-sans-cote" : "mode-expert";
      var modeBadge = '<span class="mode-badge ' + modeBadgeCls + '">' + modeBadgeLabel + '</span>';

      html += '<div class="disc-card">';
      html += '<div class="disc-card-header">';
      html += '<span class="disc-name">' + disc + '</span>';
      html += modeBadge;
      html += '<span class="disc-count">' + d.nb_courses + " courses</span>";
      html += "</div>";

      if (!d.has_auto_data) {
        var minC = (scoringData.min_courses_required || 10);
        html += '<div class="disc-progress-msg">Calibration auto disponible après ' + minC + ' courses. ';
        html += _progressBar(d.nb_courses, minC);
        html += "</div>";
      }

      // Tableau Top-1 — 3 modes, meilleur surligné
      var expertRate    = d.expert    ? d.expert.top1_rate    : 0;
      var autoRate      = d.auto      ? d.auto.top1_rate      : 0;
      var sansCoteRate  = d.sans_cote ? d.sans_cote.top1_rate : 0;
      var bestRate      = Math.max(expertRate, autoRate, sansCoteRate);

      function _cell(rate) {
        var highlight = (rate === bestRate && bestRate > 0) ? ' class="best-cell"' : '';
        return '<td' + highlight + '>' + _rateBadge(rate) + '</td>';
      }

      html += '<table class="stats-table">';
      html += "<thead><tr><th>Critère</th><th>Expert</th><th>Auto</th><th>Sans cote</th></tr></thead><tbody>";
      html += "<tr><td>Top-1 exact</td>" + _cell(expertRate) + _cell(autoRate) + _cell(sansCoteRate) + "</tr>";
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
    // Invalider le cache stats et recharger
    _invalidatePage("stats");
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

// =============================================================================
// PAGE BILAN — Backtesting des modes de scoring
// =============================================================================

var _bilanData = null;
var _bilanPeriode = "all";
var _bilanDiscipline = "all";
var _bilanEvolutionPari = "GAGNANT";
var _bilanEvolutionKeys = ["GAGNANT", "PLACE_1", "COUPLE_GAGNANT", "COUPLE_PLACE_12", "TIERCE_DESORDRE", "QUARTE_DESORDRE"];

// ---- PAGE PRONOSTICS ----
var _pronoSeuil = 30;

async function loadPronosticsPage(seuil) {
  if (seuil !== undefined) {
    _pronoSeuil = seuil;
    _invalidatePage("pronostics"); // filtre changé → rechargement forcé
  }
  var container = document.getElementById("pronostics-content");
  if (!container) return;
  container.innerHTML = '<div class="stats-loading"><div class="spinner"></div><p>Calcul des pronostics\u2026</p></div>';

  try {
    var data = await API.pronosticsPage(_pronoSeuil);
    container.innerHTML = renderPronosticsPage(data);
    _markPageLoaded("pronostics");
  } catch (e) {
    if (e && e.isAuthError) return; // 401 → login screen already shown by apiFetch
    container.innerHTML = '<div class="stats-error">Erreur lors du chargement des pronostics.<br>' + (e.message || "") + '</div>';
  }
}

function renderPronosticsPage(data) {
  var html = "";

  // Header
  html += '<div class="stats-header">';
  html += '<h2 class="stats-title">Pronostics du jour</h2>';
  html += '<p class="stats-subtitle">Bas\u00e9s sur les taux de r\u00e9ussite historiques (' + data.nb_courses + ' courses)</p>';
  html += '</div>';

  // Filtre seuil de confiance
  var seuils = [
    {key: 20, label: "20%+"},
    {key: 30, label: "30%+"},
    {key: 40, label: "40%+"},
    {key: 50, label: "50%+"}
  ];
  html += '<div class="scoring-toggle" style="margin-bottom:16px;">';
  for (var i = 0; i < seuils.length; i++) {
    var s = seuils[i];
    html += '<button class="scoring-toggle-btn' + (_pronoSeuil === s.key ? ' active' : '') + '" onclick="loadPronosticsPage(' + s.key + ')">' + s.label + '</button>';
  }
  html += '</div>';

  if (!data.courses || data.courses.length === 0) {
    html += '<div class="stats-error">Aucun pronostic disponible avec ce seuil de confiance.</div>';
    return html;
  }

  // Top paris confiance (tous paris toutes courses, triés par taux)
  var allPronos = [];
  for (var c = 0; c < data.courses.length; c++) {
    var course = data.courses[c];
    for (var p = 0; p < course.pronostics.length; p++) {
      var prono = course.pronostics[p];
      allPronos.push({
        course: course,
        prono: prono
      });
    }
  }
  allPronos.sort(function(a, b) {
    var ha = a.course.heure_depart || '';
    var hb = b.course.heure_depart || '';
    if (ha < hb) return -1;
    if (ha > hb) return 1;
    return b.prono.taux - a.prono.taux;
  });

  // Afficher le top 10 confiance
  html += '<div class="stats-card" style="margin-bottom:20px">';
  html += '<h3 style="margin:0 0 12px;color:var(--gold)">\uD83C\uDFC6 Top confiance</h3>';
  var topN = Math.min(allPronos.length, 10);
  for (var t = 0; t < topN; t++) {
    var item = allPronos[t];
    var chevNums = item.prono.chevaux.map(function(ch) { return ch.num_pmu; }).join("-");
    var hasVb = item.prono.chevaux.some(function(ch) { return ch.is_value_bet; });
    var confClass = item.prono.taux >= 50 ? "bilan-green" : item.prono.taux >= 40 ? "bilan-orange" : "bilan-red";
    html += '<div style="display:flex;align-items:center;gap:8px;padding:6px 4px;' + (hasVb ? 'background:rgba(245,166,35,0.22);border-left:3px solid var(--gold);border-radius:6px;margin-bottom:2px;' : 'border-bottom:1px solid var(--border);') + '">';
    html += '<span class="' + confClass + '" style="font-weight:700;min-width:45px">' + item.prono.taux + '%</span>';
    html += '<span style="font-size:12px;color:var(--text-secondary)">R' + item.course.reunion_num + 'C' + item.course.course_num + '</span>';
    html += '<span style="font-weight:600">' + item.prono.pari_label + '</span>';
    html += '<span style="font-size:12px;background:var(--surface);padding:2px 6px;border-radius:4px">' + item.prono.mode_label + '</span>';
    html += '<span style="font-weight:700;color:var(--gold)">' + chevNums + '</span>';
    if (hasVb) html += '<span style="font-size:10px;font-weight:700;color:var(--gold);margin-left:auto">VB</span>';
    html += '</div>';
  }
  html += '</div>';

  // Détail par course
  for (var c = 0; c < data.courses.length; c++) {
    var course = data.courses[c];
    html += '<div class="stats-card" id="prono-course-' + course.course_id + '" style="margin-bottom:16px">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">';
    html += '<h3 style="margin:0;font-size:15px">R' + course.reunion_num + 'C' + course.course_num + ' \u2014 ' + course.libelle + '</h3>';
    html += '<span class="badge badge-gray" style="font-size:11px">' + (course.discipline || "") + '</span>';
    html += '</div>';
    var heureStr = course.heure_depart ? H().formatTime(course.heure_depart) : "";
    var partantsStr = course.nombre_partants ? ' &mdash; ' + course.nombre_partants + ' partants' : "";
    html += '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px">' + (course.hippodrome || "") + (heureStr ? ' &mdash; ' + heureStr : '') + partantsStr + '</div>';

    for (var p = 0; p < course.pronostics.length; p++) {
      var prono = course.pronostics[p];
      var hasVb = prono.chevaux.some(function(ch) { return ch.is_value_bet; });
      var chevStr = prono.chevaux.map(function(ch) {
        var vbMark = ch.is_value_bet ? ' <span style="font-size:10px;font-weight:700;color:var(--gold)">[VB]</span>' : '';
        return ch.num_pmu + "-" + ch.nom + vbMark;
      }).join(" + ");
      var confClass = prono.taux >= 50 ? "bilan-green" : prono.taux >= 40 ? "bilan-orange" : "bilan-red";
      var rowBg = hasVb ? 'background:rgba(245,166,35,0.22);border-left:3px solid var(--gold);border-radius:6px;padding:4px 6px;margin-bottom:2px;' : 'padding:4px 0;border-bottom:1px solid var(--border);';
      html += '<div style="display:flex;align-items:center;gap:8px;' + rowBg + '">';
      html += '<span class="' + confClass + '" style="font-weight:700;min-width:45px;font-size:13px">' + prono.taux + '%</span>';
      html += '<span style="font-weight:600;font-size:13px">' + prono.pari_label + '</span>';
      html += '<span style="font-size:11px;background:var(--surface);padding:2px 5px;border-radius:4px">' + prono.mode_label + '</span>';
      html += '<span style="font-size:13px;color:var(--text-secondary)">' + chevStr + '</span>';
      html += '</div>';
    }
    html += '</div>';
  }

  return html;
}

// ---- PAGE BILAN ----
async function loadBilanPage(periode, discipline) {
  if (periode !== undefined) {
    _bilanPeriode = periode;
    _invalidatePage("bilan"); // filtre changé → rechargement forcé
  }
  if (discipline !== undefined) {
    _bilanDiscipline = discipline;
    _invalidatePage("bilan"); // filtre changé → rechargement forcé
  }
  var container = document.getElementById("bilan-content");
  if (!container) return;
  container.innerHTML = '<div class="stats-loading"><div class="spinner"></div><p>Calcul du bilan en cours\u2026</p></div>';

  try {
    _bilanData = await API.bilan(_bilanPeriode, _bilanDiscipline);
    if (!_bilanData.evolution || !_bilanData.evolution[_bilanEvolutionPari]) {
      _bilanEvolutionPari = "GAGNANT";
    }
    container.innerHTML = renderBilanPage(_bilanData);
    _markPageLoaded("bilan");
  } catch (e) {
    if (e && e.isAuthError) return; // 401 → login screen already shown by apiFetch
    container.innerHTML = '<div class="stats-error">Erreur lors du chargement du bilan.<br>' + (e.message || "") + "</div>";
  }
}

function setBilanEvolutionPari(pariKey) {
  _bilanEvolutionPari = pariKey;
  var host = document.getElementById("bilan-evolution-block");
  if (!host) return;
  host.outerHTML = renderBilanEvolutionBlock(_bilanData);
}

function _getBilanPariLabel(pariKey, data) {
  return data && data.paris && data.paris[pariKey] && data.paris[pariKey].label ? data.paris[pariKey].label : pariKey;
}

function _buildBilanSeriesPoints(series, mode, chartWidth, chartHeight, padLeft, padTop) {
  if (!series || !series.length) return "";
  var stepX = series.length > 1 ? chartWidth / (series.length - 1) : 0;
  var points = [];
  for (var i = 0; i < series.length; i++) {
    var val = series[i][mode];
    if (val === null || val === undefined) continue;
    var x = padLeft + (stepX * i);
    var y = padTop + chartHeight - ((Math.max(0, Math.min(100, val)) / 100) * chartHeight);
    points.push(x.toFixed(1) + "," + y.toFixed(1));
  }
  return points.join(" ");
}

function renderBilanEvolutionBlock(data) {
  var evolution = (data && data.evolution) || {};
  if (!evolution[_bilanEvolutionPari]) {
    _bilanEvolutionPari = "GAGNANT";
  }
  var currentSeries = evolution[_bilanEvolutionPari] || [];
  var html = '<div class="stats-section" id="bilan-evolution-block">';
  html += '<h3 class="stats-section-title">Évolution temporelle du taux de réussite</h3>';
  html += '<p class="stats-subtitle" style="margin-bottom:12px">8 dernières semaines, filtre discipline appliqué, période ignorée pour garder la perspective.</p>';
  html += '<div class="bilan-evolution-toolbar">';
  html += '<select class="bilan-evolution-select" onchange="setBilanEvolutionPari(this.value)">';
  for (var i = 0; i < _bilanEvolutionKeys.length; i++) {
    var key = _bilanEvolutionKeys[i];
    html += '<option value="' + key + '"' + (_bilanEvolutionPari === key ? ' selected' : '') + '>' + _getBilanPariLabel(key, data) + '</option>';
  }
  html += '</select>';
  html += '<div class="bilan-evolution-series-legend">';
  html += '<span class="bilan-evolution-series-item"><span class="bilan-evolution-series-dot auto"></span>Auto</span>';
  html += '<span class="bilan-evolution-series-item"><span class="bilan-evolution-series-dot expert"></span>Expert</span>';
  html += '<span class="bilan-evolution-series-item"><span class="bilan-evolution-series-dot sans-cote"></span>Sans cote</span>';
  html += '</div>';
  html += '</div>';

  if (!currentSeries.length) {
    html += '<p class="stats-empty">Pas assez de données sur les dernières semaines pour ce type de pari.</p>';
    html += '</div>';
    return html;
  }

  var width = 640;
  var height = 280;
  var padLeft = 42;
  var padRight = 12;
  var padTop = 16;
  var padBottom = 34;
  var chartWidth = width - padLeft - padRight;
  var chartHeight = height - padTop - padBottom;
  var yTicks = [0, 25, 50, 75, 100];
  var modes = [
    { key: "auto", color: "var(--green)" },
    { key: "expert", color: "var(--gold)" },
    { key: "sans_cote", color: "var(--blue)" }
  ];

  html += '<div class="bilan-evolution-card">';
  html += '<svg class="bilan-evolution-chart" viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Évolution hebdomadaire du taux de réussite">';

  for (var t = 0; t < yTicks.length; t++) {
    var tick = yTicks[t];
    var tickY = padTop + chartHeight - ((tick / 100) * chartHeight);
    html += '<line x1="' + padLeft + '" y1="' + tickY + '" x2="' + (padLeft + chartWidth) + '" y2="' + tickY + '" stroke="rgba(255,255,255,0.10)" stroke-width="1"></line>';
    html += '<text x="' + (padLeft - 8) + '" y="' + (tickY + 4) + '" text-anchor="end" class="bilan-evolution-axis-label">' + tick + '%</text>';
  }

  html += '<line x1="' + padLeft + '" y1="' + padTop + '" x2="' + padLeft + '" y2="' + (padTop + chartHeight) + '" stroke="rgba(255,255,255,0.22)" stroke-width="1.2"></line>';
  html += '<line x1="' + padLeft + '" y1="' + (padTop + chartHeight) + '" x2="' + (padLeft + chartWidth) + '" y2="' + (padTop + chartHeight) + '" stroke="rgba(255,255,255,0.22)" stroke-width="1.2"></line>';

  var stepX = currentSeries.length > 1 ? chartWidth / (currentSeries.length - 1) : 0;
  for (var x = 0; x < currentSeries.length; x++) {
    var xPos = padLeft + (stepX * x);
    html += '<text x="' + xPos + '" y="' + (height - 10) + '" text-anchor="middle" class="bilan-evolution-axis-label">' + currentSeries[x].semaine.replace(/^[0-9]{4}-/, "") + '</text>';
  }

  for (var m = 0; m < modes.length; m++) {
    var mode = modes[m];
    var points = _buildBilanSeriesPoints(currentSeries, mode.key, chartWidth, chartHeight, padLeft, padTop);
    if (!points) continue;
    html += '<polyline fill="none" stroke="' + mode.color + '" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="' + points + '"></polyline>';
    for (var s = 0; s < currentSeries.length; s++) {
      var val = currentSeries[s][mode.key];
      if (val === null || val === undefined) continue;
      var cx = padLeft + (stepX * s);
      var cy = padTop + chartHeight - ((Math.max(0, Math.min(100, val)) / 100) * chartHeight);
      html += '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="3.5" fill="' + mode.color + '"></circle>';
    }
  }

  html += '</svg>';
  html += '</div>';
  html += '</div>';
  return html;
}

function renderBilanPage(data) {
  var totalCourses = (data && data.total_courses) || 0;
  var paris = (data && data.paris) || {};

  var html = '<div class="stats-page">';

  // Header
  html += '<div class="stats-header">';
  html += '<h2 class="stats-title">Bilan &mdash; Backtesting</h2>';
  html += '<p class="stats-subtitle">Simulation des paris sur les courses termin\u00e9es</p>';
  html += '</div>';

  // Filtre période
  var periodes = [
    {key: "today", label: "Ce jour"},
    {key: "7days", label: "7 derniers jours"},
    {key: "30days", label: "30 derniers jours"},
    {key: "month", label: "Ce mois"},
    {key: "all", label: "Depuis le d\u00e9but"}
  ];
  html += '<div class="scoring-toggle" style="margin-bottom:16px;">';
  for (var i = 0; i < periodes.length; i++) {
    var p = periodes[i];
    html += '<button class="scoring-toggle-btn' + (_bilanPeriode === p.key ? ' active' : '') + '" onclick="loadBilanPage(\'' + p.key + '\')">' + p.label + '</button>';
  }
  html += '</div>';

  // Filtre discipline
  var disciplines = [
    {key: "all", label: "Tout"},
    {key: "PLAT", label: "Plat"},
    {key: "TROT_MONTE", label: "Mont\u00e9"},
    {key: "TROT_ATTELE", label: "Attel\u00e9"},
    {key: "OBSTACLE", label: "Obstacle"},
    {key: "HAIE", label: "Haie"},
    {key: "STEEPLE", label: "Steeple"},
    {key: "CROSS", label: "Cross"}
  ];
  html += '<div class="scoring-toggle" style="margin-bottom:16px;">';
  for (var i = 0; i < disciplines.length; i++) {
    var d = disciplines[i];
    html += '<button class="scoring-toggle-btn' + (_bilanDiscipline === d.key ? ' active' : '') + '" onclick="loadBilanPage(undefined, \'' + d.key + '\')">' + d.label + '</button>';
  }
  html += '</div>';

  // Résumé
  html += '<div class="stats-summary-row">';
  html += '<div class="stats-summary-card"><div class="ssc-value">' + totalCourses + '</div><div class="ssc-label">Courses \u00e9valu\u00e9es</div></div>';
  html += '</div>';

  if (totalCourses === 0) {
    html += '<div class="stats-section"><p class="stats-empty">Aucune course termin\u00e9e avec arriv\u00e9es connues pour l\u2019instant.</p></div>';
    html += '</div>';
    return html;
  }

  // Tableau des paris
  html += '<div class="stats-section">';
  html += '<h3 class="stats-section-title">Taux de r\u00e9ussite par type de pari</h3>';
  html += '<div class="bilan-table-wrap">';
  html += '<table class="bilan-table">';
  html += '<thead><tr>';
  html += '<th class="bilan-th-pari">Type de pari</th>';
  html += '<th class="bilan-th-mode">Auto</th>';
  html += '<th class="bilan-th-mode">Expert</th>';
  html += '<th class="bilan-th-mode">Sans cote</th>';
  html += '</tr></thead>';
  html += '<tbody>';

  var parisOrder = [
    "GAGNANT",
    "__sep_place8__",
    "PLACE8_1", "PLACE8_2", "PLACE8_3",
    "COUPLE_GAGNANT",
    "COUPLE_PLACE8_12", "COUPLE_PLACE8_23", "COUPLE_PLACE8_13",
    "TRIO",
    "__sep_place47__",
    "PLACE47_1", "PLACE47_2",
    "COUPLE_PLACE47_12",
    "TRIO_ORDRE",
    "__sep_tierce__",
    "TIERCE_ORDRE", "TIERCE_DESORDRE",
    "__sep_quarte__",
    "QUARTE_ORDRE", "QUARTE_DESORDRE", "QUARTE_BONUS3",
    "__sep_quinte__",
    "QUINTE_ORDRE", "QUINTE_DESORDRE", "QUINTE_BONUS4", "QUINTE_BONUS3",
    "DEUX_SUR_QUATRE",
    "__sep_multi_classique__",
    "MULTI_4", "MULTI_5", "MULTI_6", "MULTI_7",
    "__sep_mini_multi__",
    "MINI_MULTI_4", "MINI_MULTI_5", "MINI_MULTI_6",
    "__sep_super4__",
    "SUPER4"
  ];

  parisOrder.forEach(function (key) {
    // Lignes séparatrices avec titre de groupe
    if (key === "__sep_place8__") {
      html += '<tr class="bilan-row-group-header"><td colspan="4" class="bilan-td-group">Plac\u00e9 \u2014 8 partants ou plus (top 3)</td></tr>';
      return;
    }
    if (key === "__sep_place47__") {
      html += '<tr class="bilan-row-group-header"><td colspan="4" class="bilan-td-group">Plac\u00e9 \u2014 4 \u00e0 7 partants (top 2 seulement)</td></tr>';
      return;
    }
    if (key === "__sep_tierce__") {
      html += '<tr class="bilan-row-group-header"><td colspan="4" class="bilan-td-group">Tierc\u00e9 \u2014 3 chevaux (Ordre / D\u00e9sordre)</td></tr>';
      return;
    }
    if (key === "__sep_quarte__") {
      html += '<tr class="bilan-row-group-header"><td colspan="4" class="bilan-td-group">Quart\u00e9+ \u2014 4 chevaux (Ordre / D\u00e9sordre / Bonus 3)</td></tr>';
      return;
    }
    if (key === "__sep_quinte__") {
      html += '<tr class="bilan-row-group-header"><td colspan="4" class="bilan-td-group">Quint\u00e9+ \u2014 5 chevaux (Ordre / D\u00e9sordre / Bonus 4\u20445 / Bonus 3)</td></tr>';
      return;
    }
    if (key === "__sep_multi_classique__") {
      html += '<tr class="bilan-row-group-header"><td colspan="4" class="bilan-td-group">Multi classique (9+ partants)</td></tr>';
      return;
    }
    if (key === "__sep_mini_multi__") {
      html += '<tr class="bilan-row-group-header"><td colspan="4" class="bilan-td-group">Mini Multi (&lt;9 partants)</td></tr>';
      return;
    }
    if (key === "__sep_super4__") {
      html += '<tr class="bilan-row-group-header"><td colspan="4" class="bilan-td-group">Super4</td></tr>';
      return;
    }
    if (key === "__sep_autres__") {
      html += '<tr class="bilan-row-group-header"><td colspan="4" class="bilan-td-group">Trio / Super4</td></tr>';
      return;
    }

    var pari = paris[key];
    if (!pari) return;

    // Vérifier si au moins un mode a des données
    var anyData = ["auto", "expert", "sans_cote"].some(function (m) {
      return pari[m] && pari[m].evaluees > 0;
    });

    html += '<tr class="bilan-row">';
    html += '<td class="bilan-td-pari">' + (pari.label || key) + '</td>';

    ["auto", "expert", "sans_cote"].forEach(function (mode) {
      var cell = pari[mode];
      if (!cell || cell.evaluees === 0) {
        html += '<td class="bilan-td-mode bilan-na"><span class="bilan-na-text">—</span></td>';
      } else {
        var taux = cell.taux;
        var cls = taux === null ? "" : taux >= 40 ? "bilan-good" : taux >= 20 ? "bilan-mid" : "bilan-bad";
        var tauxStr = taux !== null ? taux + "%" : "0%";
        html += '<td class="bilan-td-mode ' + cls + '">';
        html += '<span class="bilan-ratio">' + cell.gagnes + '/' + cell.evaluees + '</span>';
        html += '<span class="bilan-pct">' + tauxStr + '</span>';
        html += '</td>';
      }
    });

    html += '</tr>';
  });

  html += '</tbody></table>';
  html += '</div>'; // bilan-table-wrap

  // Légende
  html += '<div class="bilan-legend">';
  html += '<span class="bilan-legend-item"><span class="bilan-dot bilan-good"></span>&ge;40%</span>';
  html += '<span class="bilan-legend-item"><span class="bilan-dot bilan-mid"></span>20&ndash;39%</span>';
  html += '<span class="bilan-legend-item"><span class="bilan-dot bilan-bad"></span>&lt;20%</span>';
  html += '<span class="bilan-legend-item"><span class="bilan-na-text">&mdash;</span> Pari non disponible</span>';
  html += '</div>';

  html += '</div>'; // stats-section
  html += renderBilanEvolutionBlock(data);
  html += '</div>'; // stats-page
  return html;
}

window.setBilanEvolutionPari = setBilanEvolutionPari;
