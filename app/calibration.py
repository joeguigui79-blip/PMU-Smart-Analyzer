"""
Auto-calibration du scoring PMU.

Calcule des poids optimisés par corrélation entre chaque score
et la position réelle d'arrivée sur les courses terminées.

Logique :
  - Pour chaque discipline, on récupère les participants avec position_arrivee renseignée
  - On calcule la corrélation de Spearman (rang) entre chaque critère et le classement inversé
    (position 1 = meilleur → on utilise (-position) pour que plus haut = mieux)
  - Les corrélations négatives sont mises à 0
  - poids_critere = correlation / somme_correlations
  - Minimum MIN_COURSES_PAR_DISCIPLINE courses terminées pour calibrer,
    sinon fallback sur les poids Expert (config)
"""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Participant, Course, CalibrationWeight
from app.config import SCORING_WEIGHTS_DISCIPLINE
from app.scoring import _normalize_discipline

logger = logging.getLogger(__name__)

MIN_COURSES_PAR_DISCIPLINE: dict[str, int] = {
    "PLAT":        40,
    "TROT_ATTELE": 40,
    # Autres disciplines : 20 (voir MIN_COURSES_DEFAULT)
}
MIN_COURSES_DEFAULT = 20

# Planchers/plafonds appliqués APRÈS shrinkage, AVANT renormalisation (section 5.3.D.A)
# Format : critere -> (plancher | None, plafond | None)
CALIBRATION_CAPS: dict[str, tuple] = {
    "partants":      (None, 0.08),
    "value_cote":    (None, 0.22),
    "forme_recente": (0.20, None),
    "jockey":        (0.06, None),   # appliqué seulement si jockey est dans les critères
}

# Mapping critère → champ score dans Participant
CRITERE_FIELD_MAP = {
    "forme_recente": "score_forme",
    "value_cote":    "score_cote",
    "jockey":        "score_jockey",
    "entraineur":    "score_entraineur",
    "distance":      "score_distance",
    "terrain":       "score_terrain",
    "repos":         "score_repos",
    "partants":      "score_partants",
    "hippodrome":    "score_hippodrome",
    "gains":         "score_gains",
    "age":           "score_age",
    "poids":         "score_poids",
    "corde":         "score_corde",
    "regularite":    "score_regularite",
    "recence":       "score_recence",
}


def _spearman_correlation(xs: list[float], ys: list[float]) -> float:
    """
    Corrélation de Spearman entre deux listes de valeurs.
    Retourne une valeur entre -1 et 1.
    """
    n = len(xs)
    if n < 4:
        return 0.0

    def rank_list(vals: list[float]) -> list[float]:
        sorted_indexed = sorted(enumerate(vals), key=lambda t: t[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            # Trouver les ex-aequo
            while j < n - 1 and sorted_indexed[j + 1][1] == sorted_indexed[j][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[sorted_indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    rx = rank_list(xs)
    ry = rank_list(ys)

    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n

    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den_x = sum((rx[i] - mean_rx) ** 2 for i in range(n)) ** 0.5
    den_y = sum((ry[i] - mean_ry) ** 2 for i in range(n)) ** 0.5

    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


async def compute_auto_weights(db: AsyncSession) -> dict[str, dict[str, float]]:
    """
    Calcule les poids auto-calibrés par discipline depuis l'historique.

    Retourne:
        {
            "PLAT": {"forme_recente": 0.32, "value_cote": 0.25, ...},
            "TROT_ATTELE": {...},
            ...
        }
    Disciplines avec moins de MIN_COURSES_PAR_DISCIPLINE courses → absentes du résultat.
    """
    # Charger toutes les courses terminées
    courses_result = await db.execute(
        select(Course).where(Course.statut_resultat == "TERMINE")
    )
    courses = courses_result.scalars().all()

    if not courses:
        return {}

    # Regrouper les données par discipline
    disc_data: dict[str, list[dict]] = {}

    for course in courses:
        disc = _normalize_discipline(course.discipline)

        p_result = await db.execute(
            select(Participant).where(
                Participant.course_id == course.id,
                Participant.position_arrivee.isnot(None),
            )
        )
        participants = p_result.scalars().all()
        if len(participants) < 2:
            continue

        if disc not in disc_data:
            disc_data[disc] = []

        for p in participants:
            row: dict = {
                "position": p.position_arrivee,
                "score_forme": p.score_forme,
                "score_cote": p.score_cote,
                "score_jockey": p.score_jockey,
                "score_entraineur": p.score_entraineur,
                "score_distance": p.score_distance,
                "score_terrain": p.score_terrain,
                "score_repos": p.score_repos,
                "score_partants": p.score_partants,
                "score_hippodrome": p.score_hippodrome,
                "score_gains": getattr(p, "score_gains", 50.0),
                "score_age": getattr(p, "score_age", 50.0),
                "score_corde": p.score_corde,
                "score_regularite": p.score_regularite,
                "score_recence": p.score_recence,
            }
            disc_data[disc].append(row)

    auto_weights: dict[str, dict[str, float]] = {}

    for disc, rows in disc_data.items():
        # Compter les courses (approximation: nb participants / taille moyenne course)
        # On utilise len(rows) >= MIN * 2 comme proxy (min 2 chevaux par course)
        positions = [r["position"] for r in rows]
        # Estimer le nombre de courses via la variance des positions (minimum check)
        min_courses = MIN_COURSES_PAR_DISCIPLINE.get(disc, MIN_COURSES_DEFAULT)
        if len(rows) < min_courses * 2:
            logger.info(
                "Calibration [%s]: pas assez de données (%d participants)", disc, len(rows)
            )
            continue

        # Valeur cible : position inversée (plus bas = mieux → on utilise -position)
        neg_positions = [-p for p in positions]

        # Critères pertinents pour cette discipline
        expert_weights = SCORING_WEIGHTS_DISCIPLINE.get(disc, SCORING_WEIGHTS_DISCIPLINE["PLAT"])
        relevant_criteres = list(expert_weights.keys())

        correlations: dict[str, float] = {}
        for critere in relevant_criteres:
            field = CRITERE_FIELD_MAP.get(critere)
            if not field:
                continue
            scores = [r.get(field, 50.0) or 50.0 for r in rows]
            corr = _spearman_correlation(scores, neg_positions)
            # Seulement les corrélations positives (score élevé → bon classement)
            correlations[critere] = max(0.0, corr)

        total_corr = sum(correlations.values())

        if total_corr <= 0:
            logger.info(
                "Calibration [%s]: toutes les corrélations nulles, fallback sur Expert", disc
            )
            continue

        # Normaliser les corrélations brutes
        raw_weights = {k: v / total_corr for k, v in correlations.items()}

        # B) Shrinkage vers les poids experts (section 5.3.D.B) — AVANT les caps
        shrunk = {
            k: 0.7 * raw_weights[k] + 0.3 * expert_weights.get(k, 0.0)
            for k in raw_weights
        }

        # A) Planchers/plafonds par critère (section 5.3.D.A)
        capped = {}
        for k, v in shrunk.items():
            floor_val, ceiling_val = CALIBRATION_CAPS.get(k, (None, None))
            if floor_val is not None:
                v = max(v, floor_val)
            if ceiling_val is not None:
                v = min(v, ceiling_val)
            capped[k] = v

        # C) Renormaliser pour que le total = 1.00 (section 5.3.D.C)
        total_capped = sum(capped.values())
        if total_capped > 0:
            weights = {k: round(v / total_capped, 4) for k, v in capped.items()}
        else:
            weights = {k: round(v, 4) for k, v in raw_weights.items()}

        auto_weights[disc] = weights
        logger.info("Calibration [%s]: poids calculés → %s", disc, weights)

    return auto_weights


async def calibrate_and_store(db: AsyncSession) -> dict:
    """
    Calcule les poids auto et les stocke dans la table calibration_weights.
    Retourne un résumé de l'opération.
    """
    auto_weights = await compute_auto_weights(db)

    if not auto_weights:
        return {
            "success": True,
            "message": "Pas assez de données pour calibrer",
            "disciplines_calibrated": [],
            "fallback_disciplines": list(SCORING_WEIGHTS_DISCIPLINE.keys()),
        }

    now = datetime.utcnow()
    updated = []

    for disc, weights in auto_weights.items():
        for critere, poids in weights.items():
            # Upsert CalibrationWeight
            existing = await db.execute(
                select(CalibrationWeight).where(
                    CalibrationWeight.discipline == disc,
                    CalibrationWeight.critere == critere,
                )
            )
            cw = existing.scalar_one_or_none()
            if cw:
                cw.poids = poids
                cw.updated_at = now
            else:
                cw = CalibrationWeight(
                    discipline=disc,
                    critere=critere,
                    poids=poids,
                    updated_at=now,
                )
                db.add(cw)

        updated.append(disc)

    await db.commit()

    all_discs = list(SCORING_WEIGHTS_DISCIPLINE.keys())
    fallback = [d for d in all_discs if d not in updated]

    return {
        "success": True,
        "disciplines_calibrated": updated,
        "fallback_disciplines": fallback,
        "updated_at": now.isoformat(),
    }


async def get_auto_weights_from_db(db: AsyncSession) -> dict[str, dict[str, float]]:
    """
    Charge les poids auto depuis la DB.
    Retourne {} si aucun poids calibré.
    """
    result = await db.execute(select(CalibrationWeight))
    rows = result.scalars().all()

    weights_by_disc: dict[str, dict[str, float]] = {}
    for row in rows:
        disc = row.discipline
        if disc not in weights_by_disc:
            weights_by_disc[disc] = {}
        weights_by_disc[disc][row.critere] = row.poids

    return weights_by_disc


async def get_calibration_status(db: AsyncSession) -> dict:
    """
    Retourne le statut de la calibration auto : disciplines calibrées, date de dernière MAJ.
    """
    result = await db.execute(select(CalibrationWeight))
    rows = result.scalars().all()

    if not rows:
        return {
            "calibrated": False,
            "disciplines": {},
            "last_updated": None,
        }

    by_disc: dict[str, dict] = {}
    for row in rows:
        d = row.discipline
        if d not in by_disc:
            by_disc[d] = {"criteres": {}, "last_updated": row.updated_at}
        by_disc[d]["criteres"][row.critere] = row.poids
        if row.updated_at and (not by_disc[d]["last_updated"] or row.updated_at > by_disc[d]["last_updated"]):
            by_disc[d]["last_updated"] = row.updated_at

    last_updated_global = max(
        (v["last_updated"] for v in by_disc.values() if v["last_updated"]),
        default=None,
    )

    return {
        "calibrated": True,
        "disciplines": {
            d: {
                "poids": v["criteres"],
                "last_updated": v["last_updated"].isoformat() if v["last_updated"] else None,
            }
            for d, v in by_disc.items()
        },
        "last_updated": last_updated_global.isoformat() if last_updated_global else None,
    }
