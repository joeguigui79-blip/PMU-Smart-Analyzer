"""
Router Bilan — Backtesting des modes de scoring sur les courses terminées.

Endpoint :
  GET /api/bilan — Retourne pour chaque type de pari et chaque mode (auto/expert/sans_cote)
                   le nombre de courses évaluées et le nombre de paris gagnés.

Logique de simulation par type de pari (top N chevaux selon le score du mode) :
  - Gagnant       : top1 finit 1er
  - Place         : top1 finit dans top3
  - Couple Gagnant: top2 tous dans top2 (sans ordre)
  - Couple Place  : top2 tous dans top3
  - Couple Ordre  : top1 est 1er ET top2 est 2ème
  - Tierce        : top3 tous dans top3
  - Quarte+       : top4 tous dans top4
  - Quinte+       : top5 tous dans top5
  - 2sur4         : top2 tous dans top4
  - Multi en 4    : top4 tous dans top4
  - Multi en 5    : top5, au moins 4 dans top4
  - Multi en 6    : top6, au moins 4 dans top4
  - Multi en 7    : top7, au moins 4 dans top4
  - Trio          : top3 tous dans top3

Seuls les paris présents dans course.paris_disponibles sont comptabilisés.
Seules les courses avec des position_arrivee renseignées sont prises en compte.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Course, Participant, Reunion

logger = logging.getLogger(__name__)
router = APIRouter(tags=["bilan"])

# Mapping type de pari → clé API normalisée
# La clé correspond aux valeurs potentielles dans paris_disponibles
PARIS_LABELS = {
    "GAGNANT":        "Gagnant",
    "PLACE":          "Place",
    "COUPLE_GAGNANT": "Couple Gagnant",
    "COUPLE_PLACE":   "Couple Place",
    "COUPLE_ORDRE":   "Couple Ordre",
    "TIERCE":         "Tiercé",
    "QUARTE":         "Quarté+",
    "QUINTE":         "Quinté+",
    "DEUX_SUR_QUATRE": "2sur4",
    "MULTI_4":        "Multi en 4",
    "MULTI_5":        "Multi en 5",
    "MULTI_6":        "Multi en 6",
    "MULTI_7":        "Multi en 7",
    "TRIO":           "Trio",
}

# Alias supplémentaires pour la correspondance avec paris_disponibles
PARIS_ALIASES: dict[str, list[str]] = {
    "GAGNANT":        ["SIMPLE_GAGNANT", "E_SIMPLE_GAGNANT", "GAGNANT", "gagnant"],
    "PLACE":          ["SIMPLE_PLACE", "E_SIMPLE_PLACE", "PLACE", "place"],
    "COUPLE_GAGNANT": ["COUPLE_GAGNANT", "E_COUPLE_GAGNANT", "couple_gagnant", "COUPLE", "couple"],
    "COUPLE_PLACE":   ["COUPLE_PLACE", "E_COUPLE_PLACE", "couple_place"],
    "COUPLE_ORDRE":   ["COUPLE_ORDRE", "E_COUPLE_ORDRE", "couple_ordre"],
    "TIERCE":         ["TIERCE", "E_TIERCE", "tierce", "TIERCE_ORDRE", "TIERCE_DESORDRE"],
    "QUARTE":         ["QUARTE_PLUS", "E_QUARTE_PLUS", "QUARTE", "quarte", "QUARTE+"],
    "QUINTE":         ["QUINTE_PLUS", "E_QUINTE_PLUS", "QUINTE", "quinte", "QUINTE+"],
    "DEUX_SUR_QUATRE": ["DEUX_SUR_QUATRE", "E_DEUX_SUR_QUATRE", "2sur4", "2SUR4"],
    "MULTI_4":        ["MULTI", "E_MULTI", "MINI_MULTI", "E_MINI_MULTI"],
    "MULTI_5":        ["MULTI", "E_MULTI", "MINI_MULTI", "E_MINI_MULTI"],
    "MULTI_6":        ["MULTI", "E_MULTI"],
    "MULTI_7":        ["MULTI", "E_MULTI"],
    "TRIO":           ["TRIO", "E_TRIO", "trio", "TIC_TROIS"],
}

MODES = ["auto", "expert", "sans_cote"]


def _score_for_mode(p: Participant, mode: str) -> float:
    """Retourne le score du participant selon le mode, avec fallback."""
    if mode == "auto":
        # fallback: score_global_expert si auto est 0
        return p.score_global_auto if p.score_global_auto != 0.0 else p.score_global_expert
    elif mode == "expert":
        # fallback: score_global si expert est 0
        return p.score_global_expert if p.score_global_expert != 0.0 else p.score_global
    else:  # sans_cote
        return p.score_sans_cote


def _pari_in_disponibles(pari_key: str, paris_disponibles_str: str) -> bool:
    """Vérifie si un type de pari est dans la liste paris_disponibles de la course."""
    if not paris_disponibles_str:
        return False
    try:
        paris_list = json.loads(paris_disponibles_str)
    except (json.JSONDecodeError, TypeError):
        # Essayer comme liste séparée par virgules ou espaces
        paris_list = [p.strip() for p in paris_disponibles_str.replace(",", " ").split()]

    aliases = PARIS_ALIASES.get(pari_key, [pari_key])
    for alias in aliases:
        if alias in paris_list:
            return True
        # Recherche insensible à la casse
        alias_upper = alias.upper()
        for p in paris_list:
            if isinstance(p, str) and p.upper() == alias_upper:
                return True
    return False


def _simulate_pari(pari_key: str, sorted_participants: list, positions: dict) -> bool:
    """
    Simule si le pari est gagné selon le classement prédit.
    sorted_participants : liste triée par score décroissant (les meilleurs en premier)
    positions : dict num_pmu -> position_arrivee réelle
    """
    if pari_key == "GAGNANT":
        # top1 finit 1er
        if len(sorted_participants) < 1:
            return False
        top1 = sorted_participants[0].num_pmu
        return positions.get(top1) == 1

    elif pari_key == "PLACE":
        # top1 finit dans top3
        if len(sorted_participants) < 1:
            return False
        top1 = sorted_participants[0].num_pmu
        pos = positions.get(top1)
        return pos is not None and pos <= 3

    elif pari_key == "COUPLE_GAGNANT":
        # top2 tous dans top2 (sans ordre)
        if len(sorted_participants) < 2:
            return False
        top2 = {sorted_participants[0].num_pmu, sorted_participants[1].num_pmu}
        real_top2 = {num for num, pos in positions.items() if pos is not None and pos <= 2}
        return top2 == real_top2

    elif pari_key == "COUPLE_PLACE":
        # top2 tous dans top3
        if len(sorted_participants) < 2:
            return False
        top2 = {sorted_participants[0].num_pmu, sorted_participants[1].num_pmu}
        real_top3 = {num for num, pos in positions.items() if pos is not None and pos <= 3}
        return top2.issubset(real_top3)

    elif pari_key == "COUPLE_ORDRE":
        # top1 est 1er ET top2 est 2ème
        if len(sorted_participants) < 2:
            return False
        top1 = sorted_participants[0].num_pmu
        top2 = sorted_participants[1].num_pmu
        return positions.get(top1) == 1 and positions.get(top2) == 2

    elif pari_key == "TIERCE":
        # top3 tous dans top3
        if len(sorted_participants) < 3:
            return False
        top3 = {sorted_participants[i].num_pmu for i in range(3)}
        real_top3 = {num for num, pos in positions.items() if pos is not None and pos <= 3}
        return top3 == real_top3

    elif pari_key == "QUARTE":
        # top4 tous dans top4
        if len(sorted_participants) < 4:
            return False
        top4 = {sorted_participants[i].num_pmu for i in range(4)}
        real_top4 = {num for num, pos in positions.items() if pos is not None and pos <= 4}
        return top4 == real_top4

    elif pari_key == "QUINTE":
        # top5 tous dans top5
        if len(sorted_participants) < 5:
            return False
        top5 = {sorted_participants[i].num_pmu for i in range(5)}
        real_top5 = {num for num, pos in positions.items() if pos is not None and pos <= 5}
        return top5 == real_top5

    elif pari_key == "DEUX_SUR_QUATRE":
        # top2 tous dans top4
        if len(sorted_participants) < 2:
            return False
        top2 = {sorted_participants[0].num_pmu, sorted_participants[1].num_pmu}
        real_top4 = {num for num, pos in positions.items() if pos is not None and pos <= 4}
        return top2.issubset(real_top4)

    elif pari_key == "MULTI_4":
        # top4 tous dans top4
        if len(sorted_participants) < 4:
            return False
        top4 = {sorted_participants[i].num_pmu for i in range(4)}
        real_top4 = {num for num, pos in positions.items() if pos is not None and pos <= 4}
        return top4 == real_top4

    elif pari_key == "MULTI_5":
        # top5, au moins 4 dans top4
        if len(sorted_participants) < 5:
            return False
        top5 = {sorted_participants[i].num_pmu for i in range(5)}
        real_top4 = {num for num, pos in positions.items() if pos is not None and pos <= 4}
        return len(top5 & real_top4) >= 4

    elif pari_key == "MULTI_6":
        # top6, au moins 4 dans top4
        if len(sorted_participants) < 6:
            return False
        top6 = {sorted_participants[i].num_pmu for i in range(6)}
        real_top4 = {num for num, pos in positions.items() if pos is not None and pos <= 4}
        return len(top6 & real_top4) >= 4

    elif pari_key == "MULTI_7":
        # top7, au moins 4 dans top4
        if len(sorted_participants) < 7:
            return False
        top7 = {sorted_participants[i].num_pmu for i in range(7)}
        real_top4 = {num for num, pos in positions.items() if pos is not None and pos <= 4}
        return len(top7 & real_top4) >= 4

    elif pari_key == "TRIO":
        # top3 tous dans top3
        if len(sorted_participants) < 3:
            return False
        top3 = {sorted_participants[i].num_pmu for i in range(3)}
        real_top3 = {num for num, pos in positions.items() if pos is not None and pos <= 3}
        return top3 == real_top3

    return False


@router.get("/api/bilan")
async def get_bilan(
    periode: Optional[str] = Query(default="all", description="today|7days|30days|month|all"),
    db: AsyncSession = Depends(get_db),
):
    """
    Retourne le bilan de backtesting pour chaque type de pari et chaque mode de scoring.
    Filtre par période : today, 7days, 30days, month, all.
    """
    # Déterminer la date de début selon la période
    paris_tz = ZoneInfo("Europe/Paris")
    now = datetime.now(paris_tz)
    date_from: Optional[str] = None

    if periode == "today":
        date_from = now.strftime("%d%m%Y")
    elif periode == "7days":
        date_from = (now - timedelta(days=7)).strftime("%d%m%Y")
    elif periode == "30days":
        date_from = (now - timedelta(days=30)).strftime("%d%m%Y")
    elif periode == "month":
        date_from = now.replace(day=1).strftime("%d%m%Y")
    # else: all — pas de filtre

    # Récupérer les courses terminées avec filtre date
    query = select(Course).join(Reunion).where(Course.statut_resultat == "TERMINE")
    if date_from:
        query = query.where(Reunion.date_str >= date_from)
    courses_result = await db.execute(query)
    courses = courses_result.scalars().all()

    # Initialiser les compteurs
    stats: dict[str, dict[str, dict]] = {}
    for pari_key in PARIS_LABELS:
        stats[pari_key] = {
            mode: {"evaluees": 0, "gagnes": 0} for mode in MODES
        }

    total_courses_with_results = 0

    for course in courses:
        # Récupérer TOUS les participants de la course
        p_result = await db.execute(
            select(Participant).where(Participant.course_id == course.id)
        )
        all_participants = p_result.scalars().all()

        # Vérifier qu'il y a des arrivées renseignées
        participants_with_pos = [p for p in all_participants if p.position_arrivee is not None]
        if len(participants_with_pos) < 2:
            continue

        total_courses_with_results += 1

        # Construire le dict positions (seulement ceux avec position)
        positions = {p.num_pmu: p.position_arrivee for p in participants_with_pos}

        # Pour chaque type de pari disponible dans la course
        for pari_key in PARIS_LABELS:
            if not _pari_in_disponibles(pari_key, course.paris_disponibles):
                continue

            # Pour chaque mode — trier TOUS les participants par score
            for mode in MODES:
                sorted_parts = sorted(
                    all_participants,
                    key=lambda p: _score_for_mode(p, mode),
                    reverse=True,
                )
                stats[pari_key][mode]["evaluees"] += 1
                if _simulate_pari(pari_key, sorted_parts, positions):
                    stats[pari_key][mode]["gagnes"] += 1

    # Construire la réponse finale
    paris_result = {}
    for pari_key, label in PARIS_LABELS.items():
        paris_result[pari_key] = {"label": label}
        for mode in MODES:
            ev = stats[pari_key][mode]["evaluees"]
            ga = stats[pari_key][mode]["gagnes"]
            paris_result[pari_key][mode] = {
                "evaluees": ev,
                "gagnes": ga,
                "taux": round(100 * ga / ev, 1) if ev > 0 else None,
            }

    return {
        "total_courses": total_courses_with_results,
        "paris": paris_result,
    }
