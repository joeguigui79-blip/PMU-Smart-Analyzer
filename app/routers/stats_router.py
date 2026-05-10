"""
Router Stats avancées + Calibration.

Endpoints :
  GET  /api/stats/scoring     — Taux de réussite Expert vs Auto par discipline
  GET  /api/stats/calibration — Poids auto-calibrés actuels + date dernière calibration
  POST /api/calibrate         — Force un recalcul des poids auto
"""
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Participant, Course, CalibrationWeight, Reunion
from app.scoring import _normalize_discipline
from app.config import SCORING_WEIGHTS_DISCIPLINE
from app.calibration import calibrate_and_store, get_calibration_status, MIN_COURSES_PAR_DISCIPLINE
from app.service import refresh_programme_statuts

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stats"])


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/stats/scoring
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/stats/scoring")
async def stats_scoring(db: AsyncSession = Depends(get_db)):
    """
    Taux de réussite Expert vs Auto-calibré par discipline.

    Pour chaque discipline avec des courses terminées :
      - % top-1 prédit correct (Expert) : le cheval n°1 du scoring expert finit 1er
      - % top-1 prédit correct (Auto)   : idem avec score_global_auto
      - % top-3 prédits dans le vrai top-3 (Expert et Auto)
      - % top-5 (Expert et Auto)
    """
    # Rattraper les arrivées manquantes avant de calculer les stats
    await refresh_programme_statuts(db)

    courses_result = await db.execute(
        select(Course)
        .options(selectinload(Course.participants))
        .where(Course.statut_resultat == "TERMINE")
    )
    courses = courses_result.scalars().all()

    if not courses:
        return {
            "disciplines": {},
            "total_courses": 0,
            "min_courses_required": MIN_COURSES_PAR_DISCIPLINE,
        }

    # Statistiques par discipline
    disc_stats: dict[str, dict] = {}

    for course in courses:
        disc = _normalize_discipline(course.discipline)

        participants = [p for p in course.participants if p.position_arrivee is not None]
        if len(participants) < 2:
            continue

        if disc not in disc_stats:
            disc_stats[disc] = {
                "nb_courses": 0,
                "expert": {"top1": 0, "top3": 0, "top5": 0},
                "auto":   {"top1": 0, "top3": 0, "top5": 0},
            }

        disc_stats[disc]["nb_courses"] += 1

        # Top pick Expert (score_global_expert le plus élevé)
        best_expert = max(participants, key=lambda p: p.score_global_expert)
        # Top pick Auto (score_global_auto le plus élevé)
        best_auto = max(participants, key=lambda p: p.score_global_auto)

        # Top-N experts : les N premiers selon score_global_expert
        sorted_expert = sorted(participants, key=lambda p: p.score_global_expert, reverse=True)
        sorted_auto   = sorted(participants, key=lambda p: p.score_global_auto,   reverse=True)

        real_top3 = {p.num_pmu for p in participants if p.position_arrivee and p.position_arrivee <= 3}
        real_top5 = {p.num_pmu for p in participants if p.position_arrivee and p.position_arrivee <= 5}

        # Expert
        if best_expert.position_arrivee == 1:
            disc_stats[disc]["expert"]["top1"] += 1
        expert_top3_picks = {p.num_pmu for p in sorted_expert[:3]}
        if expert_top3_picks & real_top3:
            disc_stats[disc]["expert"]["top3"] += 1
        expert_top5_picks = {p.num_pmu for p in sorted_expert[:5]}
        if expert_top5_picks & real_top5:
            disc_stats[disc]["expert"]["top5"] += 1

        # Auto
        if best_auto.position_arrivee == 1:
            disc_stats[disc]["auto"]["top1"] += 1
        auto_top3_picks = {p.num_pmu for p in sorted_auto[:3]}
        if auto_top3_picks & real_top3:
            disc_stats[disc]["auto"]["top3"] += 1
        auto_top5_picks = {p.num_pmu for p in sorted_auto[:5]}
        if auto_top5_picks & real_top5:
            disc_stats[disc]["auto"]["top5"] += 1

    # Formatage résultat
    result: dict[str, dict] = {}
    for disc, s in disc_stats.items():
        nb = s["nb_courses"]
        def pct(val: int) -> float:
            return round(100 * val / nb, 1) if nb > 0 else 0.0

        result[disc] = {
            "nb_courses": nb,
            "has_auto_data": nb >= MIN_COURSES_PAR_DISCIPLINE,
            "expert": {
                "top1_rate":  pct(s["expert"]["top1"]),
                "top3_rate":  pct(s["expert"]["top3"]),
                "top5_rate":  pct(s["expert"]["top5"]),
            },
            "auto": {
                "top1_rate":  pct(s["auto"]["top1"]),
                "top3_rate":  pct(s["auto"]["top3"]),
                "top5_rate":  pct(s["auto"]["top5"]),
            },
        }

    # Évolution 7j vs 7j précédents (global top-1)
    evolution = await _compute_evolution(db)

    # Corrélation par critère (top 5 critères les plus corrélés)
    critere_perf = await _compute_critere_performance(db)

    return {
        "disciplines": result,
        "total_courses": sum(s["nb_courses"] for s in disc_stats.values()),
        "min_courses_required": MIN_COURSES_PAR_DISCIPLINE,
        "evolution": evolution,
        "critere_performance": critere_perf,
    }


async def _compute_evolution(db: AsyncSession) -> dict:
    """Calcule le taux de réussite top-1 sur les 7 derniers jours vs les 7 précédents."""
    from datetime import datetime, timedelta, timezone
    from app.models import Reunion

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff_7 = now - timedelta(days=7)
    cutoff_14 = now - timedelta(days=14)

    # Récupérer les courses terminées récentes
    courses_result = await db.execute(
        select(Course)
        .join(Reunion)
        .options(selectinload(Course.participants))
        .where(Course.statut_resultat == "TERMINE")
    )
    courses = courses_result.scalars().all()

    recent_correct = 0
    recent_total = 0
    prev_correct = 0
    prev_total = 0

    for course in courses:
        heure = course.heure_depart
        if heure is None:
            continue
        # Normaliser en TZ-naive pour comparaison cohérente avec SQLite
        heure_naive = heure.replace(tzinfo=None) if heure.tzinfo else heure

        # Déterminer la fenêtre
        if heure_naive >= cutoff_7:
            window = "recent"
        elif heure_naive >= cutoff_14:
            window = "prev"
        else:
            continue

        participants = [p for p in course.participants if p.position_arrivee is not None]
        if not participants:
            continue

        best = max(participants, key=lambda p: p.score_global)
        is_correct = best.position_arrivee == 1

        if window == "recent":
            recent_total += 1
            if is_correct:
                recent_correct += 1
        else:
            prev_total += 1
            if is_correct:
                prev_correct += 1

    return {
        "last_7d": {
            "nb_courses": recent_total,
            "top1_rate": round(100 * recent_correct / recent_total, 1) if recent_total > 0 else 0.0,
        },
        "prev_7d": {
            "nb_courses": prev_total,
            "top1_rate": round(100 * prev_correct / prev_total, 1) if prev_total > 0 else 0.0,
        },
        "trend": "up" if (recent_total > 0 and prev_total > 0 and (recent_correct / recent_total) > (prev_correct / prev_total)) else
                 "down" if (recent_total > 0 and prev_total > 0 and (recent_correct / recent_total) < (prev_correct / prev_total)) else
                 "stable",
    }


async def _compute_critere_performance(db: AsyncSession) -> list[dict]:
    """Retourne les critères triés par poids de calibration (proxy de performance)."""
    result = await db.execute(
        select(CalibrationWeight).order_by(CalibrationWeight.poids.desc())
    )
    rows = result.scalars().all()

    seen: set[str] = set()
    out = []
    for row in rows:
        key = row.critere
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "critere": row.critere,
            "discipline": row.discipline,
            "poids": round(row.poids * 100, 1),
        })

    return out[:10]  # Top 10 critères


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/stats/calibration
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/stats/calibration")
async def stats_calibration(db: AsyncSession = Depends(get_db)):
    """
    Retourne les poids auto-calibrés actuels par discipline + date dernière calibration.
    Indique si chaque discipline est calibrée (assez de données) ou en fallback Expert.
    """
    status = await get_calibration_status(db)

    # Compter les courses terminées par discipline pour afficher le % de progression
    courses_result = await db.execute(
        select(Course).where(Course.statut_resultat == "TERMINE")
    )
    courses = courses_result.scalars().all()

    nb_by_disc: dict[str, int] = {}
    for course in courses:
        disc = _normalize_discipline(course.discipline)
        nb_by_disc[disc] = nb_by_disc.get(disc, 0) + 1

    # Enrichir le statut avec les infos de couverture
    all_discs = list(SCORING_WEIGHTS_DISCIPLINE.keys())
    disciplines_info: dict[str, dict] = {}

    for disc in all_discs:
        nb_courses = nb_by_disc.get(disc, 0)
        is_calibrated = disc in (status.get("disciplines") or {})
        expert_weights = SCORING_WEIGHTS_DISCIPLINE.get(disc, {})

        auto_poids = None
        last_updated = None
        if is_calibrated and status["disciplines"]:
            auto_poids = status["disciplines"][disc].get("poids", {})
            last_updated = status["disciplines"][disc].get("last_updated")

        disciplines_info[disc] = {
            "nb_courses_terminées": nb_courses,
            "min_courses_required": MIN_COURSES_PAR_DISCIPLINE,
            "calibration_progress": round(100 * min(nb_courses, MIN_COURSES_PAR_DISCIPLINE) / MIN_COURSES_PAR_DISCIPLINE, 0),
            "is_calibrated": is_calibrated,
            "active_mode": "auto" if is_calibrated else "expert",
            "expert_weights": expert_weights,
            "auto_weights": auto_poids,
            "last_updated": last_updated,
        }

    return {
        "calibrated": status.get("calibrated", False),
        "last_updated_global": status.get("last_updated"),
        "disciplines": disciplines_info,
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/calibrate
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/calibrate")
async def force_calibrate(db: AsyncSession = Depends(get_db)):
    """
    Force un recalcul des poids auto-calibrés depuis l'historique complet.
    """
    result = await calibrate_and_store(db)
    logger.info("Calibration forcée: %s", result)
    return result
