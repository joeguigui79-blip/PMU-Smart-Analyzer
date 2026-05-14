"""
Endpoint /api/pronostics
Génère des recommandations de paris pour les courses du jour
basées sur les taux de réussite historiques du bilan.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Course, Participant, Reunion
from app.config import today_str
from app.routers.bilan_router import get_bilan, PARIS_ALIASES
from app.cache import cache, TTL_PRONOSTICS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["pronostics"])

# Seuil minimum de taux de réussite pour recommander un pari (en %)
SEUIL_CONFIANCE = 30

# Nombre de chevaux à prendre selon le type de pari
CHEVAUX_PAR_PARI = {
    "GAGNANT": 1,
    "PLACE_1": 1,
    "PLACE_2": 2,
    "PLACE_3": 3,
    "COUPLE_GAGNANT": 2,
    "COUPLE_PLACE_12": 2,
    "COUPLE_PLACE_23": 3,
    "COUPLE_PLACE_13": 3,
    "COUPLE_ORDRE": 2,
    "TIERCE_ORDRE": 3,
    "TIERCE_DESORDRE": 3,
    "QUARTE_ORDRE": 4,
    "QUARTE_DESORDRE": 4,
    "QUARTE_BONUS3": 4,
    "QUINTE_ORDRE": 5,
    "QUINTE_DESORDRE": 5,
    "QUINTE_BONUS4": 5,
    "QUINTE_BONUS3": 5,
    "DEUX_SUR_QUATRE": 2,
    "MULTI_4": 4,
    "MULTI_5": 5,
    "MULTI_6": 6,
    "MULTI_7": 7,
    "MINI_MULTI_4": 4,
    "MINI_MULTI_5": 5,
    "MINI_MULTI_6": 6,
    "TRIO_ORDRE": 3,
    "TRIO": 3,
    "SUPER4": 4,
}

# Labels lisibles
PARIS_LABELS = {
    "GAGNANT": "Gagnant",
    "PLACE_1": "Plac\u00e9 1",
    "PLACE_2": "Plac\u00e9 2",
    "PLACE_3": "Plac\u00e9 3",
    "COUPLE_GAGNANT": "Coupl\u00e9 Gagnant",
    "COUPLE_PLACE_12": "C. Plac\u00e9 1-2",
    "COUPLE_PLACE_23": "C. Plac\u00e9 2-3",
    "COUPLE_PLACE_13": "C. Plac\u00e9 1-3",
    "COUPLE_ORDRE": "Coupl\u00e9 Ordre",
    "TIERCE_ORDRE": "Tierc\u00e9 Ordre",
    "TIERCE_DESORDRE": "Tierc\u00e9 D\u00e9sordre",
    "QUARTE_ORDRE": "Quart\u00e9+ Ordre",
    "QUARTE_DESORDRE": "Quart\u00e9+ D\u00e9sordre",
    "QUARTE_BONUS3": "Quart\u00e9+ Bonus 3",
    "QUINTE_ORDRE": "Quint\u00e9+ Ordre",
    "QUINTE_DESORDRE": "Quint\u00e9+ D\u00e9sordre",
    "QUINTE_BONUS4": "Quint\u00e9+ Bonus 4/5",
    "QUINTE_BONUS3": "Quint\u00e9+ Bonus 3",
    "DEUX_SUR_QUATRE": "2sur4",
    "MULTI_4": "Multi en 4",
    "MULTI_5": "Multi en 5",
    "MULTI_6": "Multi en 6",
    "MULTI_7": "Multi en 7",
    "MINI_MULTI_4": "Mini Multi 4",
    "MINI_MULTI_5": "Mini Multi 5",
    "MINI_MULTI_6": "Mini Multi 6",
    "TRIO_ORDRE": "Trio Ordre",
    "TRIO": "Trio",
    "SUPER4": "Super 4",
}

MODES = ["auto", "expert", "sans_cote"]
MODE_LABELS = {"auto": "Auto", "expert": "Expert", "sans_cote": "Sans cote"}


def _map_discipline_filter(discipline: str) -> str:
    """Mappe la discipline d'une course vers le filtre bilan correspondant."""
    d = discipline.upper() if discipline else "PLAT"
    if d in ("HAIE", "STEEPLE", "CROSS"):
        return d
    if d == "OBSTACLE":
        return "OBSTACLE"
    return d


def _get_score_for_mode(p, mode: str) -> float:
    if mode == "auto":
        return p.score_global_auto or p.score_global_expert or 0
    elif mode == "expert":
        return p.score_global_expert or p.score_global or 0
    else:
        return p.score_sans_cote or 0


@router.get("/pronostics")
async def get_pronostics(
    seuil: int = Query(default=SEUIL_CONFIANCE, description="Seuil minimum de confiance en %"),
    nocache: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Pour chaque course du jour (non terminée, avec participants chargés),
    retourne les paris recommandés basés sur les taux historiques du bilan.
    """
    date = today_str()
    cache_key = f"pronostics:{date}:{seuil}"

    if not nocache:
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache HIT: %s", cache_key)
            return cached

    # 1. Récupérer le bilan global (toutes périodes) pour chaque discipline
    bilan_all = await get_bilan(periode="all", discipline="all", db=db)
    # Aussi par discipline
    disciplines_to_check = ["PLAT", "TROT_ATTELE", "TROT_MONTE", "HAIE", "STEEPLE", "CROSS"]
    bilan_par_discipline = {"all": bilan_all}
    for disc in disciplines_to_check:
        bilan_par_discipline[disc] = await get_bilan(periode="all", discipline=disc, db=db)

    # 2. Récupérer les courses du jour non terminées avec participants
    date = today_str()
    result = await db.execute(
        select(Course)
        .join(Reunion)
        .where(Reunion.date_str == date)
        .where(Course.statut_resultat != "TERMINE")
        .options(selectinload(Course.participants), selectinload(Course.reunion))
        .order_by(Course.heure_depart.nullslast(), Reunion.num_officiel, Course.num_externe)
    )
    courses = result.scalars().all()

    # 3. Pour chaque course, générer les recommandations
    recommendations = []
    for course in courses:
        if not course.participants:
            continue

        reunion = course.reunion
        disc_filter = _map_discipline_filter(course.discipline)
        bilan = bilan_par_discipline.get(disc_filter, bilan_all)

        # Si pas assez de données pour cette discipline, utiliser le bilan global
        if bilan.get("total_courses", 0) < 5:
            bilan = bilan_all

        paris_data = bilan.get("paris", {})

        # Récupérer les paris disponibles pour cette course (filtrage strict)
        paris_dispo_raw = course.paris_disponibles or ""
        paris_dispo: set = set()
        if paris_dispo_raw.strip():
            try:
                parsed = json.loads(paris_dispo_raw)
                if isinstance(parsed, list):
                    paris_dispo = {str(p).upper() for p in parsed}
            except (json.JSONDecodeError, ValueError):
                # Stocké en CSV par service.py (ex: "GAGNANT,MINI_MULTI,TIERCE")
                paris_dispo = {p.strip().upper() for p in paris_dispo_raw.split(",") if p.strip()}

        course_pronostics = []

        for pari_key, pari_info in paris_data.items():
            if pari_key not in CHEVAUX_PAR_PARI:
                continue

            # Ne proposer que les paris disponibles pour cette course (via les aliases PMU)
            if paris_dispo:
                pari_aliases = PARIS_ALIASES.get(pari_key, [pari_key])
                if not any(alias.upper() in paris_dispo for alias in pari_aliases):
                    continue

            # Règle PMU : PLACE_3 et paris impliquant le 3ème uniquement si ≥8 partants
            nb_partants = course.nombre_partants or 0
            if nb_partants > 0 and nb_partants < 8:
                if pari_key in ("PLACE_3", "COUPLE_PLACE_23", "COUPLE_PLACE_13"):
                    continue

            # Trouver le meilleur mode pour ce pari
            best_mode = None
            best_taux = 0
            for mode in MODES:
                mode_data = pari_info.get(mode, {})
                evaluees = mode_data.get("evaluees", 0)
                gagnes = mode_data.get("gagnes", 0)
                if evaluees >= 3:  # Minimum 3 courses évaluées
                    taux = (gagnes / evaluees) * 100
                    if taux > best_taux:
                        best_taux = taux
                        best_mode = mode

            if best_mode is None or best_taux < seuil:
                continue

            # Récupérer les chevaux selon le mode et le nombre requis
            nb_chevaux = CHEVAUX_PAR_PARI[pari_key]
            sorted_participants = sorted(
                course.participants,
                key=lambda p: _get_score_for_mode(p, best_mode),
                reverse=True,
            )

            # Pour PLACE_2, on prend le 2ème ; PLACE_3 le 3ème ; COUPLE_PLACE_23 les 2ème+3ème, etc.
            chevaux = []
            if pari_key == "PLACE_2":
                if len(sorted_participants) >= 2:
                    chevaux = [sorted_participants[1]]
            elif pari_key == "PLACE_3":
                if len(sorted_participants) >= 3:
                    chevaux = [sorted_participants[2]]
            elif pari_key == "COUPLE_PLACE_23":
                if len(sorted_participants) >= 3:
                    chevaux = [sorted_participants[1], sorted_participants[2]]
            elif pari_key == "COUPLE_PLACE_13":
                if len(sorted_participants) >= 3:
                    chevaux = [sorted_participants[0], sorted_participants[2]]
            else:
                chevaux = sorted_participants[:nb_chevaux]

            if not chevaux or len(chevaux) < (1 if "PLACE" in pari_key and pari_key.startswith("PLACE") else nb_chevaux):
                continue

            course_pronostics.append({
                "pari": pari_key,
                "pari_label": PARIS_LABELS.get(pari_key, pari_key),
                "mode": best_mode,
                "mode_label": MODE_LABELS[best_mode],
                "taux": round(best_taux, 1),
                "chevaux": [
                    {
                        "num_pmu": c.num_pmu,
                        "nom": c.nom,
                        "score": round(_get_score_for_mode(c, best_mode), 1),
                        "is_value_bet": bool(c.is_value_bet),
                    }
                    for c in chevaux
                ],
            })

        # Trier par taux décroissant
        course_pronostics.sort(key=lambda x: x["taux"], reverse=True)

        if course_pronostics:
            recommendations.append({
                "course_id": course.id,
                "reunion_num": reunion.num_officiel,
                "course_num": course.num_externe,
                "libelle": course.libelle or f"C{course.num_externe}",
                "discipline": course.discipline,
                "hippodrome": reunion.hippodrome_libelle,
                "heure_depart": course.heure_depart.isoformat() if course.heure_depart else None,
                "pronostics": course_pronostics,
            })

    result_data = {
        "date": date,
        "seuil_confiance": seuil,
        "nb_courses": len(recommendations),
        "courses": recommendations,
    }
    cache.set(cache_key, result_data, ttl=TTL_PRONOSTICS)
    logger.debug("Cache SET: %s (TTL=%ds)", cache_key, TTL_PRONOSTICS)
    return result_data
