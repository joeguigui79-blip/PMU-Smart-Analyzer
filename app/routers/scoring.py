import json
import logging
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Bet, Course, Participant, ScoringWeight
from app.schemas import ScoringAccuracySchema, ScoringAccuracyByDisciplineSchema
from app.config import SCORING_WEIGHTS, SCORING_WEIGHTS_DISCIPLINE
from app.scoring import _normalize_discipline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scoring", tags=["scoring"])


@router.get("/accuracy", response_model=list[ScoringAccuracySchema])
async def get_accuracy(db: AsyncSession = Depends(get_db)):
    """Retourne la précision de chaque critère du scoring (discipline PLAT par défaut)."""
    result = await db.execute(
        select(ScoringWeight)
        .where(ScoringWeight.discipline == "PLAT")
        .order_by(ScoringWeight.critere)
    )
    rows = result.scalars().all()

    if not rows:
        return [
            ScoringAccuracySchema(critere=k, poids=v, precision=0.0, nb_samples=0)
            for k, v in SCORING_WEIGHTS.items()
        ]

    return [
        ScoringAccuracySchema(
            critere=row.critere,
            poids=row.poids,
            precision=row.precision,
            nb_samples=row.nb_samples,
        )
        for row in rows
    ]


@router.get("/accuracy-by-discipline", response_model=list[ScoringAccuracyByDisciplineSchema])
async def get_accuracy_by_discipline(db: AsyncSession = Depends(get_db)):
    """Retourne la précision de chaque critère par discipline."""
    result = await db.execute(
        select(ScoringWeight).order_by(ScoringWeight.discipline, ScoringWeight.critere)
    )
    rows = result.scalars().all()

    if not rows:
        # Retourner les configs par défaut
        out = []
        for disc, weights in SCORING_WEIGHTS_DISCIPLINE.items():
            for k, v in weights.items():
                out.append(ScoringAccuracyByDisciplineSchema(
                    discipline=disc, critere=k, poids=v, precision=0.0, nb_samples=0
                ))
        return out

    return [
        ScoringAccuracyByDisciplineSchema(
            discipline=row.discipline,
            critere=row.critere,
            poids=row.poids,
            precision=row.precision,
            nb_samples=row.nb_samples,
        )
        for row in rows
    ]


@router.get("/discipline-stats")
async def get_discipline_stats(db: AsyncSession = Depends(get_db)):
    """Retourne les statistiques de précision par discipline."""
    from sqlalchemy import func
    from app.models import Course

    # Récupérer toutes les courses terminées avec participants
    courses_result = await db.execute(
        select(Course).where(Course.statut_resultat == "TERMINE")
    )
    courses = courses_result.scalars().all()

    if not courses:
        return {"disciplines": {}, "total_courses": 0}

    stats_by_disc: dict[str, dict] = {}

    for course in courses:
        disc = _normalize_discipline(course.discipline)

        # Récupérer le top pick de cette course (meilleur score_global)
        p_result = await db.execute(
            select(Participant)
            .where(Participant.course_id == course.id)
            .where(Participant.position_arrivee.isnot(None))
        )
        participants = p_result.scalars().all()
        if not participants:
            continue

        if disc not in stats_by_disc:
            stats_by_disc[disc] = {
                "nb_courses": 0,
                "top_pick_wins": 0,
                "top_pick_top3": 0,
                "value_bets_total": 0,
                "value_bets_top3": 0,
            }

        stats_by_disc[disc]["nb_courses"] += 1

        best = max(participants, key=lambda p: p.score_global)
        if best.position_arrivee == 1:
            stats_by_disc[disc]["top_pick_wins"] += 1
        if best.position_arrivee and best.position_arrivee <= 3:
            stats_by_disc[disc]["top_pick_top3"] += 1

        for p in participants:
            if p.is_value_bet:
                stats_by_disc[disc]["value_bets_total"] += 1
                if p.position_arrivee and p.position_arrivee <= 3:
                    stats_by_disc[disc]["value_bets_top3"] += 1

    # Calculer les pourcentages
    result = {}
    for disc, s in stats_by_disc.items():
        nb = s["nb_courses"]
        result[disc] = {
            "nb_courses": nb,
            "top_pick_win_rate": round(100 * s["top_pick_wins"] / nb, 1) if nb > 0 else 0,
            "top_pick_top3_rate": round(100 * s["top_pick_top3"] / nb, 1) if nb > 0 else 0,
            "value_bets_total": s["value_bets_total"],
            "value_bets_top3_rate": round(100 * s["value_bets_top3"] / s["value_bets_total"], 1) if s["value_bets_total"] > 0 else 0,
        }

    return {"disciplines": result, "total_courses": sum(s["nb_courses"] for s in stats_by_disc.values())}


@router.post("/optimize", status_code=200)
async def optimize_weights(db: AsyncSession = Depends(get_db)):
    """
    Analyse l'historique des courses terminées et recalcule la précision + poids par discipline.
    Regroupe les courses terminées par discipline et corrèle chaque critère avec la victoire.
    Met à jour la table scoring_weights (avec discipline).
    """
    from app.models import Course

    # Récupérer toutes les courses terminées avec arrivées
    courses_result = await db.execute(
        select(Course).where(Course.statut_resultat == "TERMINE")
    )
    courses = courses_result.scalars().all()

    if not courses:
        return {"success": True, "message": "Pas assez de données pour optimiser", "nb_courses": 0}

    # Regrouper les stats par discipline et critère
    disc_critere_stats: dict[str, dict[str, dict]] = {}

    # Champs de scores disponibles, mappés par critère
    score_fields = {
        "forme_recente": "score_forme",
        "value_cote":    "score_cote",
        "jockey":        "score_jockey",
        "entraineur":    "score_entraineur",
        "distance":      "score_distance",
        "terrain":       "score_terrain",
        "repos":         "score_repos",
        "partants":      "score_partants",
        "hippodrome":    "score_hippodrome",
        # Critères trot
        "corde":         "score_corde",
        "regularite":    "score_regularite",
        "recence":       "score_recence",
    }

    for course in courses:
        disc = _normalize_discipline(course.discipline)

        p_result = await db.execute(
            select(Participant).where(
                Participant.course_id == course.id,
                Participant.position_arrivee.isnot(None),
            )
        )
        participants = p_result.scalars().all()
        if not participants:
            continue

        if disc not in disc_critere_stats:
            disc_critere_stats[disc] = {
                critere: {"correct": 0, "total": 0}
                for critere in score_fields.keys()
            }

        for critere, field in score_fields.items():
            try:
                best = max(participants, key=lambda p: getattr(p, field, 0.0))
                disc_critere_stats[disc][critere]["total"] += 1
                if best.position_arrivee == 1:
                    disc_critere_stats[disc][critere]["correct"] += 1
            except (ValueError, AttributeError):
                pass

    # Mettre à jour la DB par discipline
    updated_count = 0
    for disc, critere_stats in disc_critere_stats.items():
        # Poids par défaut pour cette discipline
        default_weights = SCORING_WEIGHTS_DISCIPLINE.get(disc, SCORING_WEIGHTS_DISCIPLINE["PLAT"])

        for critere, stats in critere_stats.items():
            if stats["total"] == 0:
                continue

            precision = stats["correct"] / stats["total"]
            poids_defaut = default_weights.get(critere, SCORING_WEIGHTS.get(critere, 0.0))

            # Ajustement proportionnel à la précision vs baseline (25%)
            # Plus la précision est élevée, plus le poids augmente
            baseline = 0.25  # précision espérée aléatoire
            if precision > baseline:
                adjustment = 1.0 + (precision - baseline) * 0.5
            else:
                adjustment = max(0.5, 1.0 - (baseline - precision) * 0.5)
            new_poids = poids_defaut * adjustment

            # Upsert en DB
            sw_result = await db.execute(
                select(ScoringWeight).where(
                    ScoringWeight.discipline == disc,
                    ScoringWeight.critere == critere,
                )
            )
            sw = sw_result.scalar_one_or_none()
            if sw:
                sw.precision = round(precision, 4)
                sw.poids = round(new_poids, 4)
                sw.nb_samples = stats["total"]
                sw.updated_at = datetime.utcnow()
                updated_count += 1
            else:
                sw = ScoringWeight(
                    discipline=disc,
                    critere=critere,
                    poids=round(new_poids, 4),
                    precision=round(precision, 4),
                    nb_samples=stats["total"],
                )
                db.add(sw)
                updated_count += 1

    await db.commit()

    nb_disc = len(disc_critere_stats)
    nb_courses_total = len(courses)
    return {
        "success": True,
        "nb_courses_analysed": nb_courses_total,
        "nb_disciplines": nb_disc,
        "disciplines_optimised": list(disc_critere_stats.keys()),
        "criteres_updated": updated_count,
    }
