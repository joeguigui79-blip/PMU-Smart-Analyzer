import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from app.config import PMU_BASE_URL, PMU_PARTICIPANTS_URL, PMU_ARRIVEE_URL, PARIS_TZ

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Smart-Analyzer/1.0)",
    "Accept": "application/json",
}


def _ts_to_datetime(ts_ms: int | None) -> datetime | None:
    if ts_ms is None:
        return None
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=PARIS_TZ)
    except Exception:
        return None


class PMUClient:
    def __init__(self, timeout: float = 15.0):
        self._client = httpx.AsyncClient(headers=HEADERS, timeout=timeout, follow_redirects=True)

    async def close(self):
        await self._client.aclose()

    async def get_programme(self, date_str: str) -> dict:
        """
        Récupère le programme d'une journée.
        date_str : format DDMMYYYY
        Retourne un dict structuré {reunions: [...]}
        """
        url = f"{PMU_BASE_URL}/{date_str}"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("PMU programme HTTP error %s: %s", e.response.status_code, url)
            return {"reunions": []}
        except Exception as e:
            logger.error("PMU programme error: %s", e)
            return {"reunions": []}

        programme = data.get("programme", data)
        raw_reunions = programme.get("reunions", [])
        reunions = []

        for r in raw_reunions:
            hipp = r.get("hippodrome", {})
            pays = r.get("pays", {})
            courses = []
            for c in r.get("courses", []):
                penet = c.get("penetrometre", {})
                courses.append({
                    "num_ordre": c.get("numOrdre", c.get("numExterne", 0)),
                    "num_externe": c.get("numExterne", 0),
                    "libelle": c.get("libelle", ""),
                    "libelle_court": c.get("libelleCourt", ""),
                    "heure_depart": _ts_to_datetime(c.get("heureDepart")),
                    "distance": c.get("distance", 0),
                    "discipline": c.get("specialite", c.get("discipline", "PLAT")),
                    "specialite": c.get("specialite", c.get("discipline", "PLAT")),
                    "terrain": penet.get("libelle", ""),
                    "penetrometre_valeur": penet.get("valeur"),
                    "nombre_partants": c.get("nombreDeclaresPartants", 0),
                    "montant_prix": c.get("montantPrix", 0),
                    "statut": c.get("statut", "PROGRAMMEE"),
                    "condition_age": c.get("conditionAge", ""),
                    "condition_sexe": c.get("conditionSexe", ""),
                    "paris_disponibles": [p.get("typePari", "") for p in c.get("paris", []) if p.get("typePari")],
                })
            reunions.append({
                "num_officiel": r.get("numOfficiel", 0),
                "num_externe": r.get("numExterne", 0),
                "hippodrome_code": hipp.get("code", ""),
                "hippodrome_libelle": hipp.get("libelleLong", hipp.get("libelleCourt", "")),
                "pays": pays.get("libelle", "FRANCE"),
                "courses": courses,
            })

        return {"reunions": reunions}

    async def get_participants(self, date_str: str, reunion_num: int, course_num: int) -> list[dict]:
        """
        Récupère les participants d'une course.
        Retourne une liste de dicts participant.
        """
        url = PMU_PARTICIPANTS_URL.format(
            date=date_str,
            reunion=reunion_num,
            course=course_num,
        )
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("PMU participants HTTP %s: %s", e.response.status_code, url)
            return []
        except Exception as e:
            logger.warning("PMU participants error: %s", e)
            return []

        raw_participants = data.get("participants", [])
        participants = []

        for p in raw_participants:
            # Cotes
            cote_act = None
            cote_init = None
            rapport_direct = p.get("dernierRapportDirect")
            if rapport_direct:
                cote_act = rapport_direct.get("rapport")
            rapport_ref = p.get("dernierRapportReference")
            if rapport_ref:
                cote_init = rapport_ref.get("rapport")

            # Jockey / Driver (trot) / Entraîneur
            jockey = p.get("driver", "") or p.get("jockey", "")
            entraineur = p.get("entraineur", "")
            if isinstance(jockey, dict):
                jockey = jockey.get("nom", "")
            if isinstance(entraineur, dict):
                entraineur = entraineur.get("nom", "")

            # Gains carrière depuis l'API
            gains_data = p.get("gainsParticipant") or {}
            gains_carriere = gains_data.get("gainsCarriere", 0) or 0
            gains_annee = gains_data.get("gainsAnneeEnCours", 0) or 0
            gains_annee_prec = gains_data.get("gainsAnneePrecedente", 0) or 0

            participants.append({
                "num_pmu": p.get("numPmu", p.get("numero", 0)),
                "nom": p.get("nom", ""),
                "jockey": jockey,
                "entraineur": entraineur,
                "proprietaire": p.get("proprietaire", ""),
                "cote_actuelle": float(cote_act) if cote_act else None,
                "cote_initiale": float(cote_init) if cote_init else None,
                "musique": p.get("musique", ""),
                "poids": p.get("poidsConditionMonte"),
                "handicap_distance": p.get("handicapDistance", 0) or 0,
                "age": p.get("age", 0) or 0,
                "sexe": p.get("sexe", ""),
                "provenance": p.get("pays", {}).get("libelle", "") if isinstance(p.get("pays"), dict) else "",
                # Nouveaux champs
                "gains_carriere": gains_carriere,
                "gains_annee": gains_annee,
                "gains_annee_prec": gains_annee_prec,
                "nombre_courses": p.get("nombreCourses", 0) or 0,
                "nombre_victoires": p.get("nombreVictoires", 0) or 0,
                "nombre_places": p.get("nombrePlaces", 0) or 0,
                "driver_change": bool(p.get("driverChange", False)),
            })

        return participants

    async def get_arrivee(self, date_str: str, reunion_num: int, course_num: int) -> list[dict] | None:
        """
        Récupère le classement d'arrivée d'une course terminée.
        Retourne une liste [{numero_cheval, position}] triée par position,
        ou None si la course n'est pas encore terminée.
        
        Stratégie : utilise ordreArrivee depuis le programme (plus fiable que /arrivee).
        """
        # Essayer d'abord via le programme (ordreArrivee)
        arrivee_from_programme = await self._get_arrivee_from_programme(
            date_str, reunion_num, course_num
        )
        if arrivee_from_programme:
            return arrivee_from_programme

        # Fallback : endpoint dédié /arrivee
        url = PMU_ARRIVEE_URL.format(date=date_str, reunion=reunion_num, course=course_num)
        try:
            resp = await self._client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (400, 404):
                return None
            logger.warning("PMU arrivee HTTP %s: %s", e.response.status_code, url)
            return None
        except Exception as e:
            logger.warning("PMU arrivee error: %s", e)
            return None

        # L'API retourne soit une liste directe, soit un objet avec clé "arrivee"
        raw = data if isinstance(data, list) else data.get("arrivee", data.get("participants", []))
        if not raw:
            return None

        result = []
        for item in raw:
            num = item.get("numPmu") or item.get("numero") or item.get("numCheval")
            pos = item.get("ordreArrivee") or item.get("position") or item.get("rang")
            if num is not None and pos is not None:
                try:
                    result.append({"numero_cheval": int(num), "position": int(pos)})
                except (ValueError, TypeError):
                    pass

        if not result:
            return None

        result.sort(key=lambda x: x["position"])
        return result

    async def _get_arrivee_from_programme(
        self, date_str: str, reunion_num: int, course_num: int
    ) -> list[dict] | None:
        """
        Extrait ordreArrivee depuis le programme du jour ou l'endpoint participants.
        """
        # Cas 1 : chercher dans le programme global (fonctionne pour la R1 / plat)
        url = f"{PMU_BASE_URL}/{date_str}"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
            programme = data.get("programme", data)
            for r in programme.get("reunions", []):
                if r.get("numOfficiel") != reunion_num:
                    continue
                for c in r.get("courses", []):
                    if c.get("numExterne") != course_num:
                        continue
                    ordre = c.get("ordreArrivee")
                    if isinstance(ordre, list) and ordre:
                        result = []
                        for position, item in enumerate(ordre, start=1):
                            if isinstance(item, list):
                                num = item[0] if item else None
                            else:
                                num = item
                            if num is not None:
                                try:
                                    result.append({"numero_cheval": int(num), "position": position})
                                except (ValueError, TypeError):
                                    pass
                        if result:
                            return result
        except Exception as e:
            logger.warning("PMU programme (arrivee) error: %s", e)

        # Cas 2 : fallback — appel direct à l'endpoint participants (trot et réunions non incluses dans /programme)
        participants_url = PMU_PARTICIPANTS_URL.format(
            date=date_str, reunion=reunion_num, course=course_num
        )
        try:
            resp2 = await self._client.get(participants_url)
            resp2.raise_for_status()
            p_data = resp2.json()
        except Exception as e:
            logger.warning("PMU participants (arrivee fallback) error: %s", e)
            return None
        p_list = p_data if isinstance(p_data, list) else p_data.get("participants", [])
        result = []
        for p in p_list:
            ordre_p = p.get("ordreArrivee")
            num_pmu = p.get("numPmu")
            if ordre_p is not None and num_pmu is not None:
                try:
                    result.append({"numero_cheval": int(num_pmu), "position": int(ordre_p)})
                except (ValueError, TypeError):
                    pass
        if result:
            result.sort(key=lambda x: x["position"])
            return result
        return None


# Instance globale réutilisable
pmu_client = PMUClient()
