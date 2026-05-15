/* UI helper components — wrapped in IIFE to avoid global name conflicts */
(function () {
  "use strict";

  function scoreClass(score) {
    if (score >= 70) return "high";
    if (score >= 50) return "medium";
    return "low";
  }

  function formatTime(isoStr) {
    if (!isoStr) return "?";
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    } catch { return "?"; }
  }

  function formatCote(cote) {
    if (!cote) return "N/D";
    return cote.toFixed(1);
  }

  function disciplineClass(disc) {
    if (!disc) return "";
    const d = disc.toUpperCase();
    if (d.includes("TROT")) return "disc-trot";
    if (d.includes("OBSTACLE") || d.includes("STEEPLE") || d.includes("HAIES")) return "disc-obstacle";
    return "disc-plat";
  }

  function disciplineLabel(disc) {
    if (!disc) return "";
    const d = disc.toUpperCase();
    if (d.includes("TROT_ATTELE")) return "Trot Attelé";
    if (d.includes("TROT_MONTE")) return "Trot Monté";
    if (d.includes("TROT")) return "Trot";
    if (d.includes("STEEPLE")) return "Steeple";
    if (d.includes("HAIES")) return "Haies";
    if (d.includes("OBSTACLE")) return "Obstacle";
    return "Plat";
  }

  function musiqueParse(musique) {
    if (!musique) return [];
    const items = [];
    let i = 0;
    while (i < musique.length && items.length < 8) {
      const c = musique[i];
      if (c === '(') {
        while (i < musique.length && musique[i] !== ')') i++;
        i++;
        continue;
      }
      if (/\d/.test(c)) {
        let num = c;
        if (i + 1 < musique.length && /\d/.test(musique[i + 1])) {
          num = c + musique[i + 1];
          i++;
        }
        items.push({ val: num, cls: num === "1" ? "win" : parseInt(num) <= 3 ? "place" : "other" });
      } else if (/[DATRNdatrn]/.test(c)) {
        items.push({ val: c.toUpperCase(), cls: "other" });
      }
      i++;
    }
    return items;
  }

  function renderMusiqueHtml(musique) {
    const items = musiqueParse(musique);
    if (!items.length) return '<span style="color:var(--text-muted);font-size:11px">Pas de musique</span>';
    return `<div class="musique-wrap">${items.map(it =>
      `<div class="musique-item ${it.cls}">${it.val}</div>`
    ).join("")}</div>`;
  }

  function renderScoreBar(score) {
    const cls = scoreClass(score);
    return `<div class="score-bar-wrap">
      <div class="score-bar">
        <div class="score-bar-fill ${cls}" style="width:${score}%"></div>
      </div>
      <span class="score-label ${cls}">${Math.round(score)}</span>
    </div>`;
  }

  function renderParticipantRow(p, rank) {
    const cls = rank === 1 ? "rank-1" : "";
    const vb = p.is_value_bet ? `<span class="badge badge-green" style="font-size:10px">VB</span>` : "";
    return `<div class="participant-row" data-pid="${p.id}" onclick="showParticipantModal(${JSON.stringify(p).replace(/"/g, "&quot;")})">
      <div class="p-num ${cls}">${p.num_pmu}</div>
      <div class="p-info">
        <div class="p-name">${p.nom} ${vb}</div>
        <div class="p-sub">${p.jockey || "—"} · ${p.entraineur || "—"}</div>
      </div>
      <div class="p-right">
        <span class="p-cote">${formatCote(p.cote_actuelle)}</span>
        <div class="p-score-wrap">
          <div class="score-bar" style="width:70px">
            <div class="score-bar-fill ${scoreClass(p.score_global)}" style="width:${p.score_global}%"></div>
          </div>
          <span class="score-label ${scoreClass(p.score_global)}" style="font-size:12px">${Math.round(p.score_global)}</span>
        </div>
      </div>
    </div>`;
  }

  function renderCourseCard(course, hippodrome, opts) {
    const disc = disciplineLabel(course.discipline);
    const discCls = disciplineClass(course.discipline);
    const terrain = course.terrain ? `· ${course.terrain.replace(/_/g," ")}` : "";
    const prix = course.montant_prix > 0 ? `· ${(course.montant_prix/1000).toFixed(0)}k€` : "";
    const vbBadge = course._has_vb ? `<span class="badge badge-green">Value Bet</span>` : "";
    const statBadge = course.statut_resultat === "TERMINE"
      ? `<span class="badge badge-gray">Terminée</span>` : "";

    // Ligne de contexte reunion/hippodrome (mode tri par heure)
    var contextLine = "";
    if (opts && opts.showContext) {
      const rNum = opts.reunion_num != null ? `R${opts.reunion_num}` : "";
      const hipp = hippodrome || "";
      const cNum = `C${course.num_ordre}`;
      const heureStr = formatTime(course.heure_depart);
      const parts = [heureStr, rNum, hipp, cNum].filter(Boolean);
      contextLine = `<div class="course-context-line">${parts.join(" · ")}</div>`;
    }

    return `<div class="card clickable" onclick="showCourse(${course.id})">
      ${contextLine}<div class="course-card-header">
        <div class="course-num">C${course.num_ordre}</div>
        <div class="course-info">
          <div class="course-name">${course.libelle || course.libelle_court}</div>
          <div class="course-meta"><span class="${discCls}">${disc}</span> · ${course.distance}m ${terrain}${prix}</div>
        </div>
        <div class="course-time">${formatTime(course.heure_depart)}</div>
      </div>
      <div class="course-badges">
        <span class="badge badge-gray">${course.nombre_partants} partants</span>
        ${statBadge}${vbBadge}
      </div>
    </div>`;
  }

  function skeletonCards(n) {
    n = n || 3;
    return Array.from({ length: n }, () => `<div class="skeleton skeleton-card"></div>`).join("");
  }

  window.Components = {
    scoreClass, formatTime, formatCote, disciplineClass, disciplineLabel,
    musiqueParse, renderMusiqueHtml, renderScoreBar, renderParticipantRow,
    renderCourseCard, skeletonCards,
  };
})();
