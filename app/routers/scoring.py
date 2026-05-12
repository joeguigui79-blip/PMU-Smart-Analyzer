import json
import logging
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Bet, Course, Participant, ScoringWeight
from app.schemas import ScoringAccuracySchema, ScoringAccuracyByDisciplineSchema, ScoringAccuracyTrendSchema
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


@router.get("/accuracy-trend", response_model=list[ScoringAccuracyTrendSchema])
async def get_accuracy_trend(db: AsyncSession = Depends(get_db)):
    """Précision globale vs 30 dernières courses par discipline (pour indicateur de tendance)."""
    # Récupérer toutes les courses terminées, du plus récent au plus ancien
    courses_result = await db.execute(
        select(Course)
        .where(Course.statut_resultat == "TERMINE")
        .order_by(Course.id.desc())
    )
    all_courses = courses_result.scalars().all()

    if not all_courses:
        return []

    # Récupérer les participants avec arrivée en une seule requête groupée
    course_ids = [c.id for c in all_courses]
    p_result = await db.execute(
        select(Participant)
        .where(Participant.course_id.in_(course_ids))
        .where(Participant.position_arrivee.isnot(None))
    )
    participants_all = p_result.scalars().all()

    # Indexer les participants par course_id
    part_by_course: dict[int, list] = {}
    for p in participants_all:
        if p.course_id not in part_by_course:
            part_by_course[p.course_id] = []
        part_by_course[p.course_id].append(p)

    # Grouper les courses par discipline (ordre décroissant conservé)
    by_disc: dict[str, list] = {}
    for c in all_courses:
        disc = _normalize_discipline(c.discipline)
        if disc not in by_disc:
            by_disc[disc] = []
        by_disc[disc].append(c)

    def calc_prec(course_list):
        total = 0
        correct = 0
        for c in course_list:
            parts = part_by_course.get(c.id, [])
            if not parts:
                continue
            total += 1
            best = max(parts, key=lambda p: p.score_global or 0.0)
            if best.position_arrivee == 1:
                correct += 1
        return (round(correct / total, 4) if total > 0 else 0.0), total

    result = []
    for disc, disc_courses in by_disc.items():
        prec_all, nb_all = calc_prec(disc_courses)
        recent = disc_courses[:30]  # 30 plus récentes (déjà triées id desc)
        prec_recent, nb_recent = calc_prec(recent)
        result.append(ScoringAccuracyTrendSchema(
            discipline=disc,
            precision_all=prec_all,
            nb_all=nb_all,
            precision_recent=prec_recent,
            nb_recent=nb_recent,
        ))

    return sorted(result, key=lambda x: x.discipline)


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

        # Calculer d'abord tous les nouveaux poids bruts pour la discipline
        new_poids: dict[str, float] = {}
        precisions: dict[str, float] = {}
        samples: dict[str, int] = {}

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

            new_poids[critere] = poids_defaut * adjustment
            precisions[critere] = precision
            samples[critere] = stats["total"]

        # Normaliser les poids pour que leur somme = 1
        total = sum(new_poids.values())
        if total > 0:
            new_poids = {k: round(v / total, 4) for k, v in new_poids.items()}

        # Upsert en DB avec poids normalisés
        for critere, poids_val in new_poids.items():
            sw_result = await db.execute(
                select(ScoringWeight).where(
                    ScoringWeight.discipline == disc,
                    ScoringWeight.critere == critere,
                )
            )
            sw = sw_result.scalar_one_or_none()
            if sw:
                sw.precision = round(precisions[critere], 4)
                sw.poids = poids_val
                sw.nb_samples = samples[critere]
                sw.updated_at = datetime.utcnow()
                updated_count += 1
            else:
                sw = ScoringWeight(
                    discipline=disc,
                    critere=critere,
                    poids=poids_val,
                    precision=round(precisions[critere], 4),
                    nb_samples=samples[critere],
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
