"""
Endpoint /api/courses/{course_id}/couple-jockey
Analyse la relation cheval-jockey à partir des performances détaillées PMU.

AFFICHAGE SEUL — aucun impact sur score_global, score_sans_cote, bilan ou pronostics.
Cache mémoire TTL 24h (86400s).
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

import httpx

from app.database import get_db
from app.models import Course, Participant
from app.config import PMU_PERFORMANCES_URL
from app.cache import cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["couple-jockey"])

TTL_COUPLE_JOCKEY = 86400  # 24h

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Smart-Analyzer/1.0)",
    "Accept": "application/json",
}


def _normalize_jockey(name: str) -> str:
    """Normalise un nom de jockey pour la comparaison (minuscule, sans espaces multiples)."""
    if not name:
        return ""
    return " ".join(name.strip().lower().split())


def _parse_position(pos) -> int | None:
    """Parse une position d'arrivée. Retourne None pour D/A/T/R (non classé)."""
    if pos is None:
        return None
    try:
        return int(pos)
    except (ValueError, TypeError):
        return None


def _compute_couple_badge(num_pmu: int, jockey_actuel: str, performances: list[dict]) -> dict:
    """
    Calcule le badge couple cheval-jockey à partir des 5 dernières performances.

    Retourne un dict :
      { couple_status, couple_label, badge_color, num_pmu }
    """
    jockey_norm = _normalize_jockey(jockey_actuel)

    sorties_avec = []   # positions avec ce jockey
    sorties_sans = []   # positions avec d'autres jockeys

    for perf in performances[:5]:
        jockey_perf = _normalize_jockey(
            perf.get("driver") or perf.get("jockey") or ""
        )
        pos = _parse_position(perf.get("position") or perf.get("ordreArrivee"))

        if jockey_perf == jockey_norm:
            if pos is not None:
                sorties_avec.append(pos)
        else:
            if pos is not None:
                sorties_sans.append(pos)

    n_avec = len(sorties_avec)

    # ---- Cas 0 sortie avec ce jockey ----
    if n_avec == 0:
        return {
            "num_pmu": num_pmu,
            "couple_status": "NEW",
            "couple_label": "Nouvelle assoc",
            "badge_color": "grey",
        }

    # ---- Cas 1 seule sortie ----
    if n_avec == 1:
        pos1 = sorties_avec[0]
        if pos1 <= 3:
            return {
                "num_pmu": num_pmu,
                "couple_status": "BON_RETOUR",
                "couple_label": "Bon retour",
                "badge_color": "orange",
            }
        else:
            return {
                "num_pmu": num_pmu,
                "couple_status": "MAUVAIS_RETOUR",
                "couple_label": "Mauvais retour",
                "badge_color": "orange",
            }

    # ---- Cas >= 2 sorties ----
    moy_avec = sum(sorties_avec) / n_avec
    if sorties_sans:
        moy_sans = sum(sorties_sans) / len(sorties_sans)
        ecart = round(moy_sans - moy_avec, 1)
        if moy_avec < moy_sans:
            return {
                "num_pmu": num_pmu,
                "couple_status": "POSITIF",
                "couple_label": f"Couple +{ecart}",
                "badge_color": "green",
            }
        elif moy_avec > moy_sans:
            ecart_neg = round(moy_avec - moy_sans, 1)
            return {
                "num_pmu": num_pmu,
                "couple_status": "NEGATIF",
                "couple_label": f"Couple -{ecart_neg}",
                "badge_color": "red",
            }
        else:
            return {
                "num_pmu": num_pmu,
                "couple_status": "NEUTRE",
                "couple_label": f"Couple ={round(moy_avec, 1)}",
                "badge_color": "grey",
            }
    else:
        # Toutes les sorties sont avec ce jockey — pas de référence sans
        return {
            "num_pmu": num_pmu,
            "couple_status": "POSITIF" if moy_avec <= 3 else "NEUTRE",
            "couple_label": f"Moy {round(moy_avec, 1)} (exc.)",
            "badge_color": "green" if moy_avec <= 3 else "grey",
        }


@router.get("/courses/{course_id}/couple-jockey")
async def get_couple_jockey(course_id: int, db: AsyncSession = Depends(get_db)):
    """
    Retourne les badges couple cheval-jockey pour chaque partant d'une course.
    LECTURE SEULE — n'affecte pas les scores ni le bilan.
    Cache 24h.
    """
    cache_key = f"couple_jockey:{course_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Charger la course avec reunion et participants
    result = await db.execute(
        select(Course)
        .where(Course.id == course_id)
        .options(selectinload(Course.participants), selectinload(Course.reunion))
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    reunion = course.reunion
    participants: list[Participant] = course.participants

    if not participants:
        response = {"course_id": course_id, "badges": {}}
        cache.set(cache_key, response, ttl=TTL_COUPLE_JOCKEY)
        return response

    # Construire mapping num_pmu → jockey actuel
    jockey_map: dict[int, str] = {p.num_pmu: (p.jockey or "") for p in participants}

    # Appel PMU performances-detaillées
    url = PMU_PERFORMANCES_URL.format(
        date=reunion.date_str,
        reunion=reunion.num_officiel,
        course=course.num_externe,
    )
    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=15.0, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning(
            "couple-jockey: HTTP %s pour %s", e.response.status_code, url
        )
        response = {"course_id": course_id, "badges": {}, "error": "performances indisponibles"}
        # Cache court (5 min) pour les erreurs
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        logger.warning("couple-jockey: erreur réseau %s", e)
        response = {"course_id": course_id, "badges": {}, "error": str(e)}
        cache.set(cache_key, response, ttl=300)
        return response

    # L'API retourne une liste de chevaux avec leurs performances
    # Structure: [{ numPmu, participants: [{ ordreArrivee, driver/jockey, ... }] }, ...]
    # ou une liste directe selon la réponse
    chevaux_list = data if isinstance(data, list) else data.get("participants", data.get("chevaux", []))

    badges: dict[str, dict] = {}

    for cheval in chevaux_list:
        num_pmu = cheval.get("numPmu") or cheval.get("num_pmu") or cheval.get("numero")
        if num_pmu is None:
            continue
        num_pmu = int(num_pmu)

        jockey_actuel = jockey_map.get(num_pmu, "")
        if not jockey_actuel:
            badges[str(num_pmu)] = {
                "num_pmu": num_pmu,
                "couple_status": "UNKNOWN",
                "couple_label": "",
                "badge_color": "grey",
            }
            continue

        # Performances passées du cheval
        perfs_raw = cheval.get("participants", cheval.get("performances", cheval.get("sorties", [])))
        if not isinstance(perfs_raw, list):
            perfs_raw = []

        # Normaliser les performances : on veut { driver/jockey, position }
        perfs = []
        for p in perfs_raw[:5]:
            driver = p.get("driver") or p.get("jockey") or p.get("nomDriver") or p.get("nomJockey") or ""
            if isinstance(driver, dict):
                driver = driver.get("nom", "")
            pos = p.get("ordreArrivee") or p.get("position") or p.get("rang")
            perfs.append({"driver": driver, "position": pos})

        badge = _compute_couple_badge(num_pmu, jockey_actuel, perfs)
        badges[str(num_pmu)] = badge

    response = {"course_id": course_id, "badges": badges}
    cache.set(cache_key, response, ttl=TTL_COUPLE_JOCKEY)
    return response
