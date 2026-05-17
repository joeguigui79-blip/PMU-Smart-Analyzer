"""
Router Stats avancées + Calibration.

Endpoints :
  GET  /api/stats/scoring            — Taux de réussite Expert vs Auto vs Sans-cote par discipline
  GET  /api/stats/calibration        — Poids auto-calibrés actuels + date dernière calibration
"""
import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Course, CalibrationWeight, Reunion
from app.scoring import _normalize_discipline
from app.config import SCORING_WEIGHTS_DISCIPLINE
from app.calibration import get_calibration_status, MIN_COURSES_PAR_DISCIPLINE, MIN_COURSES_DEFAULT
from app.service import refresh_programme_statuts
from app.cache import cache, TTL_STATS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stats"])

# ─────────────────────────────────────────────────────────────────────────────
# Helper partagé : taux top-1 par discipline pour les 3 modes
# ─────────────────────────────────────────────────────────────────────────────

async def _get_top1_rates_by_disc(db: AsyncSession) -> dict[str, dict]:
    """
    Calcule le taux top-1 des 3 modes (expert, auto, sans_cote) par discipline.
    Logique identique à bilan_router._score_for_mode + _simulate_pari("GAGNANT").
    Retourne :
      { disc: { expert: float, auto: float, sans_cote: float,
                mode_recommande: str, nb_courses: int } }
    """
    courses_result = await db.execute(
        select(Course)
        .options(selectinload(Course.participants))
        .where(Course.statut_resultat == "TERMINE")
    )
    courses = courses_result.scalars().all()

    raw: dict[str, dict] = {}
    for course in courses:
        disc = _normalize_discipline(course.discipline)
        all_participants = course.participants
        participants_with_pos = [p for p in all_participants if p.position_arrivee is not None]
        if len(participants_with_pos) < 2:
            continue
        if disc not in raw:
            raw[disc] = {"nb": 0, "expert": 0, "auto": 0, "sans_cote": 0}
        raw[disc]["nb"] += 1

        positions = {p.num_pmu: p.position_arrivee for p in participants_with_pos}

        # Trier TOUS les participants par score (fallbacks identiques à bilan_router)
        def _score_expert(p) -> float:
            v = p.score_global_expert or 0.0
            return v if v != 0.0 else (p.score_global or 0.0)

        def _score_auto(p) -> float:
            v = p.score_global_auto or 0.0
            return v if v != 0.0 else (p.score_global_expert or 0.0)

        def _score_sans_cote(p) -> float:
            return p.score_sans_cote or 0.0

        best_expert   = max(all_participants, key=_score_expert)
        best_auto     = max(all_participants, key=_score_auto)
        best_sans     = max(all_participants, key=_score_sans_cote)

        if positions.get(best_expert.num_pmu) == 1:
            raw[disc]["expert"]    += 1
        if positions.get(best_auto.num_pmu) == 1:
            raw[disc]["auto"]      += 1
        if positions.get(best_sans.num_pmu) == 1:
            raw[disc]["sans_cote"] += 1

    result: dict[str, dict] = {}
    for disc, s in raw.items():
        nb = s["nb"]
        def pct(v: int) -> float:
            return round(100 * v / nb, 1) if nb > 0 else 0.0
        rates = {
            "expert":    pct(s["expert"]),
            "auto":      pct(s["auto"]),
            "sans_cote": pct(s["sans_cote"]),
        }
        best_mode = max(rates, key=lambda k: rates[k])
        result[disc] = {**rates, "mode_recommande": best_mode, "nb_courses": nb}

    return result


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/stats/scoring
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/stats/scoring")
async def stats_scoring(nocache: int = Query(default=0), db: AsyncSession = Depends(get_db)):
    """
    Taux de réussite Top-1 exact (Expert / Auto / Sans-cote) par discipline.
    Inclut le mode recommandé (meilleur taux top-1) pour chaque discipline.
    """
    cache_key = "stats:scoring"

    if not nocache:
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache HIT: %s", cache_key)
            return cached

    # Rattraper les arrivées manquantes avant de calculer les stats
    try:
        await refresh_programme_statuts(db)
    except Exception as exc:
        logger.warning("refresh_programme_statuts failed (non-blocking): %s", exc)

    rates_by_disc = await _get_top1_rates_by_disc(db)

    if not rates_by_disc:
        return {
            "disciplines": {},
            "total_courses": 0,
            "min_courses_required": MIN_COURSES_PAR_DISCIPLINE,
            "discipline_summary": [],
        }

    # Formatage résultat
    result: dict[str, dict] = {}
    discipline_summary: list[dict] = []

    for disc, r in rates_by_disc.items():
        nb = r["nb_courses"]
        result[disc] = {
            "nb_courses":    nb,
            "has_auto_data": nb >= MIN_COURSES_PAR_DISCIPLINE.get(disc, MIN_COURSES_DEFAULT),
            "expert":    {"top1_rate": r["expert"]},
            "auto":      {"top1_rate": r["auto"]},
            "sans_cote": {"top1_rate": r["sans_cote"]},
            "mode_recommande": r["mode_recommande"],
        }
        discipline_summary.append({
            "discipline":      disc,
            "mode_recommande": r["mode_recommande"],
            "taux_expert":     r["expert"],
            "taux_auto":       r["auto"],
            "taux_sans_cote":  r["sans_cote"],
        })

    # Évolution 7j vs 7j précédents (global top-1)
    evolution = await _compute_evolution(db)

    # Corrélation par critère (top 10 critères les plus pondérés)
    critere_perf = await _compute_critere_performance(db)

    response = {
        "disciplines":        result,
        "total_courses":      sum(r["nb_courses"] for r in rates_by_disc.values()),
        "min_courses_required": MIN_COURSES_PAR_DISCIPLINE,
        "evolution":          evolution,
        "critere_performance": critere_perf,
        "discipline_summary": discipline_summary,
    }
    cache.set(cache_key, response, ttl=TTL_STATS)
    logger.debug("Cache SET: %s (TTL=%ds)", cache_key, TTL_STATS)
    return response


async def _compute_evolution(db: AsyncSession) -> dict:
    """Calcule le taux de réussite top-1 sur les 7 derniers jours vs les 7 précédents."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff_7  = now - timedelta(days=7)
    cutoff_14 = now - timedelta(days=14)

    courses_result = await db.execute(
        select(Course)
        .join(Reunion)
        .options(selectinload(Course.participants))
        .where(Course.statut_resultat == "TERMINE")
    )
    courses = courses_result.scalars().all()

    recent_correct = 0
    recent_total   = 0
    prev_correct   = 0
    prev_total     = 0

    for course in courses:
        heure = course.heure_depart
        if heure is None:
            continue
        heure_naive = heure.replace(tzinfo=None) if heure.tzinfo else heure

        if heure_naive >= cutoff_7:
            window = "recent"
        elif heure_naive >= cutoff_14:
            window = "prev"
        else:
            continue

        participants = [p for p in course.participants if p.position_arrivee is not None]
        if not participants:
            continue

        best = max(participants, key=lambda p: p.score_global or 0)
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
            "top1_rate":  round(100 * recent_correct / recent_total, 1) if recent_total > 0 else 0.0,
        },
        "prev_7d": {
            "nb_courses": prev_total,
            "top1_rate":  round(100 * prev_correct / prev_total, 1) if prev_total > 0 else 0.0,
        },
        "trend": (
            "up"   if (recent_total > 0 and prev_total > 0 and (recent_correct / recent_total) > (prev_correct / prev_total)) else
            "down" if (recent_total > 0 and prev_total > 0 and (recent_correct / recent_total) < (prev_correct / prev_total)) else
            "stable"
        ),
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
            "critere":    row.critere,
            "discipline": row.discipline,
            "poids":      round(row.poids * 100, 1),
        })

    return out[:10]


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/stats/calibration
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/stats/calibration")
async def stats_calibration(nocache: int = Query(default=0), db: AsyncSession = Depends(get_db)):
    """
    Retourne les poids auto-calibrés actuels par discipline + date dernière calibration.
    Le mode actif est désormais basé sur le meilleur taux top-1 observé (pas seulement
    la présence d'une calibration auto).
    """
    cache_key = "stats:calibration"

    if not nocache:
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache HIT: %s", cache_key)
            return cached

    status = await get_calibration_status(db)

    # Taux top-1 par discipline (pour choisir le mode actif réel)
    rates_by_disc = await _get_top1_rates_by_disc(db)

    # Compter les courses terminées par discipline pour la barre de progression
    courses_result = await db.execute(
        select(Course).where(Course.statut_resultat == "TERMINE")
    )
    courses = courses_result.scalars().all()

    nb_by_disc: dict[str, int] = {}
    for course in courses:
        disc = _normalize_discipline(course.discipline)
        nb_by_disc[disc] = nb_by_disc.get(disc, 0) + 1

    all_discs = list(SCORING_WEIGHTS_DISCIPLINE.keys())
    disciplines_info: dict[str, dict] = {}

    for disc in all_discs:
        nb_courses    = nb_by_disc.get(disc, 0)
        is_calibrated = disc in (status.get("disciplines") or {})
        expert_weights = SCORING_WEIGHTS_DISCIPLINE.get(disc, {})

        auto_poids   = None
        last_updated = None
        if is_calibrated and status["disciplines"]:
            auto_poids   = status["disciplines"][disc].get("poids", {})
            last_updated = status["disciplines"][disc].get("last_updated")

        # Mode actif = mode avec le meilleur taux top-1 (fallback expert si pas de données)
        disc_rates = rates_by_disc.get(disc)
        if disc_rates:
            active_mode = disc_rates["mode_recommande"]
        else:
            active_mode = "expert"

        disciplines_info[disc] = {
            "nb_courses_terminées":  nb_courses,
            "min_courses_required":  MIN_COURSES_PAR_DISCIPLINE.get(disc, MIN_COURSES_DEFAULT),
            "calibration_progress":  round(100 * min(nb_courses, MIN_COURSES_PAR_DISCIPLINE.get(disc, MIN_COURSES_DEFAULT)) / MIN_COURSES_PAR_DISCIPLINE.get(disc, MIN_COURSES_DEFAULT), 0),
            "is_calibrated":         is_calibrated,
            "active_mode":           active_mode,
            "expert_weights":        expert_weights,
            "auto_weights":          auto_poids,
            "last_updated":          last_updated,
        }

    calib_response = {
        "calibrated":          status.get("calibrated", False),
        "last_updated_global": status.get("last_updated"),
        "disciplines":         disciplines_info,
    }
    cache.set(cache_key, calib_response, ttl=TTL_STATS)
    logger.debug("Cache SET: %s (TTL=%ds)", cache_key, TTL_STATS)
    return calib_response
