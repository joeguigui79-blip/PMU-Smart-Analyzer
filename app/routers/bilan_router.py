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
  - Trio Ordre    : top3 dans l'ordre exact (1er, 2ème, 3ème)
  - Trio          : top3 tous dans top3 dans n'importe quel ordre
  - Super4        : top4 dans l'ordre exact, uniquement si nb_partants entre 5 et 9

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
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Course, Participant, Reunion

logger = logging.getLogger(__name__)
router = APIRouter(tags=["bilan"])

# Mapping type de pari → clé API normalisée
# La clé correspond aux valeurs potentielles dans paris_disponibles
PARIS_LABELS = {
    "GAGNANT":          "Gagnant",
    "PLACE_1":          "Plac\u00e9 1",
    "PLACE_2":          "Plac\u00e9 2",
    "PLACE_3":          "Plac\u00e9 3",
    "COUPLE_GAGNANT":   "Coupl\u00e9 Gagnant",
    "COUPLE_PLACE_12":  "C. Plac\u00e9 1-2",
    "COUPLE_PLACE_23":  "C. Plac\u00e9 2-3",
    "COUPLE_PLACE_13":  "C. Plac\u00e9 1-3",
    "COUPLE_ORDRE":     "Coupl\u00e9 Ordre",
    "TIERCE_ORDRE":     "Tierc\u00e9 Ordre",
    "TIERCE_DESORDRE":  "Tierc\u00e9 D\u00e9sordre",
    "QUARTE_ORDRE":     "Quart\u00e9+ Ordre",
    "QUARTE_DESORDRE":  "Quart\u00e9+ D\u00e9sordre",
    "QUARTE_BONUS3":    "Quart\u00e9+ Bonus 3",
    "QUINTE_ORDRE":     "Quint\u00e9+ Ordre",
    "QUINTE_DESORDRE":  "Quint\u00e9+ D\u00e9sordre",
    "QUINTE_BONUS4":    "Quint\u00e9+ Bonus 4/5",
    "QUINTE_BONUS3":    "Quint\u00e9+ Bonus 3",
    "DEUX_SUR_QUATRE":  "2sur4",
    "MULTI_4":          "Multi en 4",
    "MULTI_5":          "Multi en 5",
    "MULTI_6":          "Multi en 6",
    "MULTI_7":          "Multi en 7",
    "MINI_MULTI_4":     "Mini Multi 4",
    "MINI_MULTI_5":     "Mini Multi 5",
    "MINI_MULTI_6":     "Mini Multi 6",
    "TRIO_ORDRE":       "Trio Ordre",
    "TRIO":             "Trio",
    "SUPER4":           "Super4",
}

# Alias supplémentaires pour la correspondance avec paris_disponibles
PARIS_ALIASES: dict[str, list[str]] = {
    "GAGNANT":          ["SIMPLE_GAGNANT", "E_SIMPLE_GAGNANT", "GAGNANT", "gagnant"],
    "PLACE_1":          ["SIMPLE_PLACE", "E_SIMPLE_PLACE", "PLACE", "place"],
    "PLACE_2":          ["SIMPLE_PLACE", "E_SIMPLE_PLACE", "PLACE", "place"],
    "PLACE_3":          ["SIMPLE_PLACE", "E_SIMPLE_PLACE", "PLACE", "place"],
    "COUPLE_GAGNANT":   ["COUPLE_GAGNANT", "E_COUPLE_GAGNANT", "couple_gagnant", "COUPLE", "couple"],
    "COUPLE_PLACE_12":  ["COUPLE_PLACE", "E_COUPLE_PLACE", "couple_place"],
    "COUPLE_PLACE_23":  ["COUPLE_PLACE", "E_COUPLE_PLACE", "couple_place"],
    "COUPLE_PLACE_13":  ["COUPLE_PLACE", "E_COUPLE_PLACE", "couple_place"],
    "COUPLE_ORDRE":     ["COUPLE_ORDRE", "E_COUPLE_ORDRE", "couple_ordre"],
    "TIERCE_ORDRE":     ["TIERCE", "E_TIERCE", "tierce", "TIERCE_ORDRE", "TIERCE_DESORDRE"],
    "TIERCE_DESORDRE":  ["TIERCE", "E_TIERCE", "tierce", "TIERCE_ORDRE", "TIERCE_DESORDRE"],
    "QUARTE_ORDRE":     ["QUARTE_PLUS", "E_QUARTE_PLUS", "QUARTE", "quarte", "QUARTE+"],
    "QUARTE_DESORDRE":  ["QUARTE_PLUS", "E_QUARTE_PLUS", "QUARTE", "quarte", "QUARTE+"],
    "QUARTE_BONUS3":    ["QUARTE_PLUS", "E_QUARTE_PLUS", "QUARTE", "quarte", "QUARTE+"],
    "QUINTE_ORDRE":     ["QUINTE_PLUS", "E_QUINTE_PLUS", "QUINTE", "quinte", "QUINTE+"],
    "QUINTE_DESORDRE":  ["QUINTE_PLUS", "E_QUINTE_PLUS", "QUINTE", "quinte", "QUINTE+"],
    "QUINTE_BONUS4":    ["QUINTE_PLUS", "E_QUINTE_PLUS", "QUINTE", "quinte", "QUINTE+"],
    "QUINTE_BONUS3":    ["QUINTE_PLUS", "E_QUINTE_PLUS", "QUINTE", "quinte", "QUINTE+"],
    "DEUX_SUR_QUATRE":  ["DEUX_SUR_QUATRE", "E_DEUX_SUR_QUATRE", "2sur4", "2SUR4"],
    "MULTI_4":          ["MULTI", "E_MULTI"],
    "MULTI_5":          ["MULTI", "E_MULTI"],
    "MULTI_6":          ["MULTI", "E_MULTI"],
    "MULTI_7":          ["MULTI", "E_MULTI"],
    "MINI_MULTI_4":     ["MINI_MULTI", "E_MINI_MULTI"],
    "MINI_MULTI_5":     ["MINI_MULTI", "E_MINI_MULTI"],
    "MINI_MULTI_6":     ["MINI_MULTI", "E_MINI_MULTI"],
    "TRIO_ORDRE":       ["TRIO", "E_TRIO", "trio", "TIC_TROIS"],
    "TRIO":             ["TRIO", "E_TRIO", "trio", "TIC_TROIS"],
    "SUPER4":           ["SUPER_QUATRE", "E_SUPER_QUATRE"],
}

MODES = ["auto", "expert", "sans_cote"]
EVOLUTION_PARIS = [
    "GAGNANT",
    "PLACE_1",
    "COUPLE_GAGNANT",
    "COUPLE_PLACE_12",
    "TIERCE_DESORDRE",
    "QUARTE_DESORDRE",
]


def _is_discipline_match(course_discipline: str, discipline_filter: Optional[str]) -> bool:
    if not discipline_filter or discipline_filter == "all":
        return True
    if discipline_filter == "OBSTACLE":
        return course_discipline in {"HAIE", "STEEPLE", "CROSS", "OBSTACLE"}
    return course_discipline == discipline_filter


def _week_key_from_date_str(date_str: str) -> Optional[str]:
    if not date_str:
        return None
    try:
        course_date = datetime.strptime(date_str, "%d%m%Y").date()
    except ValueError:
        return None
    iso_year, iso_week, _ = course_date.isocalendar()
    return f"{iso_year}-S{iso_week:02d}"


def _ddmmyyyy_to_iso(date_str: str) -> Optional[str]:
    """Convertit DDMMYYYY en YYYYMMDD pour comparaison lexicographique correcte."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%d%m%Y").strftime("%Y%m%d")
    except ValueError:
        return None


def _init_stats(pari_keys: list[str]) -> dict[str, dict[str, dict[str, int]]]:
    return {
        pari_key: {
            mode: {"evaluees": 0, "gagnes": 0} for mode in MODES
        }
        for pari_key in pari_keys
    }


def _process_course_for_stats(
    course: Course,
    pari_keys: list[str],
    stats: dict[str, dict[str, dict[str, int]]],
) -> bool:
    all_participants = course.participants
    participants_with_pos = [p for p in all_participants if p.position_arrivee is not None]
    if len(participants_with_pos) < 2:
        return False

    positions = {p.num_pmu: p.position_arrivee for p in participants_with_pos}
    sorted_by_mode = {
        mode: sorted(all_participants, key=lambda p, m=mode: _score_for_mode(p, m), reverse=True)
        for mode in MODES
    }

    for pari_key in pari_keys:
        if not _pari_in_disponibles(pari_key, course.paris_disponibles):
            continue

        for mode in MODES:
            stats[pari_key][mode]["evaluees"] += 1
            if _simulate_pari(pari_key, sorted_by_mode[mode], positions):
                stats[pari_key][mode]["gagnes"] += 1

    return True


def _serialize_stats(stats: dict[str, dict[str, dict[str, int]]], labels: dict[str, str]) -> dict[str, dict]:
    result = {}
    for pari_key, label in labels.items():
        result[pari_key] = {"label": label}
        for mode in MODES:
            ev = stats[pari_key][mode]["evaluees"]
            ga = stats[pari_key][mode]["gagnes"]
            result[pari_key][mode] = {
                "evaluees": ev,
                "gagnes": ga,
                "taux": round(100 * ga / ev, 1) if ev > 0 else None,
            }
    return result


def _score_for_mode(p: Participant, mode: str) -> float:
    """Retourne le score du participant selon le mode, avec fallback."""
    if mode == "auto":
        v = p.score_global_auto or 0.0
        return v if v != 0.0 else (p.score_global_expert or 0.0)
    elif mode == "expert":
        v = p.score_global_expert or 0.0
        return v if v != 0.0 else (p.score_global or 0.0)
    else:  # sans_cote
        return p.score_sans_cote or 0.0


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

    elif pari_key == "PLACE_1":
        # top1 finit dans top3
        if len(sorted_participants) < 1:
            return False
        pos = positions.get(sorted_participants[0].num_pmu)
        return pos is not None and pos <= 3

    elif pari_key == "PLACE_2":
        # top2 finit dans top3
        if len(sorted_participants) < 2:
            return False
        pos = positions.get(sorted_participants[1].num_pmu)
        return pos is not None and pos <= 3

    elif pari_key == "PLACE_3":
        # top3 finit dans top3
        if len(sorted_participants) < 3:
            return False
        pos = positions.get(sorted_participants[2].num_pmu)
        return pos is not None and pos <= 3

    elif pari_key == "COUPLE_GAGNANT":
        # top2 tous dans top2 (sans ordre)
        if len(sorted_participants) < 2:
            return False
        top2 = {sorted_participants[0].num_pmu, sorted_participants[1].num_pmu}
        real_top2 = {num for num, pos in positions.items() if pos is not None and pos <= 2}
        return top2 == real_top2

    elif pari_key == "COUPLE_PLACE_12":
        # top1 et top2 tous dans top3
        if len(sorted_participants) < 2:
            return False
        real_top3 = {num for num, pos in positions.items() if pos is not None and pos <= 3}
        return {sorted_participants[0].num_pmu, sorted_participants[1].num_pmu}.issubset(real_top3)

    elif pari_key == "COUPLE_PLACE_23":
        # top2 et top3 tous dans top3
        if len(sorted_participants) < 3:
            return False
        real_top3 = {num for num, pos in positions.items() if pos is not None and pos <= 3}
        return {sorted_participants[1].num_pmu, sorted_participants[2].num_pmu}.issubset(real_top3)

    elif pari_key == "COUPLE_PLACE_13":
        # top1 et top3 tous dans top3
        if len(sorted_participants) < 3:
            return False
        real_top3 = {num for num, pos in positions.items() if pos is not None and pos <= 3}
        return {sorted_participants[0].num_pmu, sorted_participants[2].num_pmu}.issubset(real_top3)

    elif pari_key == "COUPLE_ORDRE":
        # top1 est 1er ET top2 est 2ème
        if len(sorted_participants) < 2:
            return False
        top1 = sorted_participants[0].num_pmu
        top2 = sorted_participants[1].num_pmu
        return positions.get(top1) == 1 and positions.get(top2) == 2

    elif pari_key == "TIERCE_ORDRE":
        # top3 dans l'ordre exact
        if len(sorted_participants) < 3:
            return False
        return (positions.get(sorted_participants[0].num_pmu) == 1
                and positions.get(sorted_participants[1].num_pmu) == 2
                and positions.get(sorted_participants[2].num_pmu) == 3)

    elif pari_key == "TIERCE_DESORDRE":
        # top3 tous dans top3 mais PAS dans l'ordre exact
        if len(sorted_participants) < 3:
            return False
        top3 = {sorted_participants[i].num_pmu for i in range(3)}
        real_top3 = {num for num, pos in positions.items() if pos is not None and pos <= 3}
        if not top3 == real_top3:
            return False
        # Vérifier que ce n'est PAS dans l'ordre
        in_order = (positions.get(sorted_participants[0].num_pmu) == 1
                    and positions.get(sorted_participants[1].num_pmu) == 2
                    and positions.get(sorted_participants[2].num_pmu) == 3)
        return not in_order

    elif pari_key == "QUARTE_ORDRE":
        # top4 dans l'ordre exact
        if len(sorted_participants) < 4:
            return False
        return (positions.get(sorted_participants[0].num_pmu) == 1
                and positions.get(sorted_participants[1].num_pmu) == 2
                and positions.get(sorted_participants[2].num_pmu) == 3
                and positions.get(sorted_participants[3].num_pmu) == 4)

    elif pari_key == "QUARTE_DESORDRE":
        # top4 tous dans top4 mais PAS dans l'ordre exact
        if len(sorted_participants) < 4:
            return False
        top4 = {sorted_participants[i].num_pmu for i in range(4)}
        real_top4 = {num for num, pos in positions.items() if pos is not None and pos <= 4}
        if not top4 == real_top4:
            return False
        in_order = (positions.get(sorted_participants[0].num_pmu) == 1
                    and positions.get(sorted_participants[1].num_pmu) == 2
                    and positions.get(sorted_participants[2].num_pmu) == 3
                    and positions.get(sorted_participants[3].num_pmu) == 4)
        return not in_order

    elif pari_key == "QUARTE_BONUS3":
        # les 3 premiers de la sélection (top3 sur 4) sont dans le vrai top3, pas dans l'ordre exact
        if len(sorted_participants) < 4:
            return False
        top3_of_selection = {sorted_participants[i].num_pmu for i in range(3)}
        real_top3 = {num for num, pos in positions.items() if pos is not None and pos <= 3}
        if not top3_of_selection == real_top3:
            return False
        # Pas dans l'ordre exact
        in_order = (positions.get(sorted_participants[0].num_pmu) == 1
                    and positions.get(sorted_participants[1].num_pmu) == 2
                    and positions.get(sorted_participants[2].num_pmu) == 3)
        return not in_order

    elif pari_key == "QUINTE_ORDRE":
        # top5 dans l'ordre exact
        if len(sorted_participants) < 5:
            return False
        return (positions.get(sorted_participants[0].num_pmu) == 1
                and positions.get(sorted_participants[1].num_pmu) == 2
                and positions.get(sorted_participants[2].num_pmu) == 3
                and positions.get(sorted_participants[3].num_pmu) == 4
                and positions.get(sorted_participants[4].num_pmu) == 5)

    elif pari_key == "QUINTE_DESORDRE":
        # top5 tous dans top5 mais PAS dans l'ordre exact
        if len(sorted_participants) < 5:
            return False
        top5 = {sorted_participants[i].num_pmu for i in range(5)}
        real_top5 = {num for num, pos in positions.items() if pos is not None and pos <= 5}
        if not top5 == real_top5:
            return False
        in_order = (positions.get(sorted_participants[0].num_pmu) == 1
                    and positions.get(sorted_participants[1].num_pmu) == 2
                    and positions.get(sorted_participants[2].num_pmu) == 3
                    and positions.get(sorted_participants[3].num_pmu) == 4
                    and positions.get(sorted_participants[4].num_pmu) == 5)
        return not in_order

    elif pari_key == "QUINTE_BONUS4":
        # exactement 4 des 5 joués sont dans le vrai top5
        if len(sorted_participants) < 5:
            return False
        top5 = {sorted_participants[i].num_pmu for i in range(5)}
        real_top5 = {num for num, pos in positions.items() if pos is not None and pos <= 5}
        return len(top5 & real_top5) == 4

    elif pari_key == "QUINTE_BONUS3":
        # les 3 premiers de la sélection (top3 sur 5) sont dans le vrai top3, pas dans l'ordre exact
        if len(sorted_participants) < 5:
            return False
        top3_of_selection = {sorted_participants[i].num_pmu for i in range(3)}
        real_top3 = {num for num, pos in positions.items() if pos is not None and pos <= 3}
        if not top3_of_selection == real_top3:
            return False
        in_order = (positions.get(sorted_participants[0].num_pmu) == 1
                    and positions.get(sorted_participants[1].num_pmu) == 2
                    and positions.get(sorted_participants[2].num_pmu) == 3)
        return not in_order

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

    elif pari_key == "MINI_MULTI_4":
        # Mini Multi en 4 : top4 tous dans top4 (identique à MULTI_4, mais pour courses MINI_MULTI)
        if len(sorted_participants) < 4:
            return False
        top4 = {sorted_participants[i].num_pmu for i in range(4)}
        real_top4 = {num for num, pos in positions.items() if pos is not None and pos <= 4}
        return top4 == real_top4

    elif pari_key == "MINI_MULTI_5":
        # Mini Multi en 5 : top5, au moins 4 dans top4
        if len(sorted_participants) < 5:
            return False
        top5 = {sorted_participants[i].num_pmu for i in range(5)}
        real_top4 = {num for num, pos in positions.items() if pos is not None and pos <= 4}
        return len(top5 & real_top4) >= 4

    elif pari_key == "MINI_MULTI_6":
        # Mini Multi en 6 : top6, au moins 4 dans top4
        if len(sorted_participants) < 6:
            return False
        top6 = {sorted_participants[i].num_pmu for i in range(6)}
        real_top4 = {num for num, pos in positions.items() if pos is not None and pos <= 4}
        return len(top6 & real_top4) >= 4

    elif pari_key == "TRIO_ORDRE":
        # top3 dans l'ordre exact (1er, 2ème, 3ème)
        if len(sorted_participants) < 3:
            return False
        return (positions.get(sorted_participants[0].num_pmu) == 1
                and positions.get(sorted_participants[1].num_pmu) == 2
                and positions.get(sorted_participants[2].num_pmu) == 3)

    elif pari_key == "TRIO":
        # top3 tous dans top3 dans n'importe quel ordre
        if len(sorted_participants) < 3:
            return False
        top3 = {sorted_participants[i].num_pmu for i in range(3)}
        real_top3 = {num for num, pos in positions.items() if pos is not None and pos <= 3}
        return top3 == real_top3

    elif pari_key == "SUPER4":
        # top4 dans l'ordre exact — uniquement valide si nb_partants entre 5 et 9
        # (le filtrage partants est géré dans la boucle principale)
        if len(sorted_participants) < 4:
            return False
        return (positions.get(sorted_participants[0].num_pmu) == 1
                and positions.get(sorted_participants[1].num_pmu) == 2
                and positions.get(sorted_participants[2].num_pmu) == 3
                and positions.get(sorted_participants[3].num_pmu) == 4)

    return False


@router.get("/api/bilan")
async def get_bilan(
    periode: Optional[str] = Query(default="all", description="today|7days|30days|month|all"),
    discipline: Optional[str] = Query(default="all", description="all|PLAT|TROT_MONTE|TROT_ATTELE|HAIE"),
    db: AsyncSession = Depends(get_db),
):
    """
    Retourne le bilan de backtesting pour chaque type de pari et chaque mode de scoring.
    Filtre par période et par discipline.
    """
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

    query = (
        select(Course)
        .join(Reunion)
        .options(selectinload(Course.participants), selectinload(Course.reunion))
        .where(Course.statut_resultat == "TERMINE")
    )
    courses_result = await db.execute(query)
    courses = courses_result.scalars().all()

    stats = _init_stats(list(PARIS_LABELS.keys()))
    evolution_stats: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    total_courses_with_results = 0

    # Convertir date_from en ISO pour comparaison correcte inter-mois
    date_from_iso = _ddmmyyyy_to_iso(date_from) if date_from else None

    for course in courses:
        course_date_str = course.reunion.date_str if course.reunion else None
        course_date_iso = _ddmmyyyy_to_iso(course_date_str) if course_date_str else None
        matches_period = not date_from_iso or (course_date_iso and course_date_iso >= date_from_iso)
        matches_discipline = _is_discipline_match(course.discipline, discipline)

        if matches_period and matches_discipline:
            if _process_course_for_stats(course, list(PARIS_LABELS.keys()), stats):
                total_courses_with_results += 1

        if matches_discipline:
            week_key = _week_key_from_date_str(course_date_str or "")
            if week_key:
                week_stats = evolution_stats.setdefault(week_key, _init_stats(EVOLUTION_PARIS))
                _process_course_for_stats(course, EVOLUTION_PARIS, week_stats)

    paris_result = _serialize_stats(stats, PARIS_LABELS)
    latest_weeks = sorted(evolution_stats.keys())[-8:]
    evolution_result = {}
    for pari_key in EVOLUTION_PARIS:
        series = []
        for week_key in latest_weeks:
            week_stats = evolution_stats[week_key][pari_key]
            if not any(week_stats[mode]["evaluees"] > 0 for mode in MODES):
                continue
            series.append({
                "semaine": week_key,
                "auto": round(100 * week_stats["auto"]["gagnes"] / week_stats["auto"]["evaluees"], 1) if week_stats["auto"]["evaluees"] > 0 else None,
                "expert": round(100 * week_stats["expert"]["gagnes"] / week_stats["expert"]["evaluees"], 1) if week_stats["expert"]["evaluees"] > 0 else None,
                "sans_cote": round(100 * week_stats["sans_cote"]["gagnes"] / week_stats["sans_cote"]["evaluees"], 1) if week_stats["sans_cote"]["evaluees"] > 0 else None,
            })
        evolution_result[pari_key] = series

    return {
        "total_courses": total_courses_with_results,
        "paris": paris_result,
        "evolution": evolution_result,
    }
