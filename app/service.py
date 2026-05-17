"""
Service layer : chargement et mise à jour des données PMU en base.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Reunion, Course, Participant, Bet, ScoringWeight
from app.pmu_client import pmu_client
from app.scoring import (
    calculer_scores,
    load_weights_from_config_or_db,
    score_cote as scoring_score_cote,
    is_value_bet as scoring_is_value_bet,
    get_confiance,
    get_weights_for_discipline,
)
from app.config import today_str

# Debounce de l'auto-calibration : ne calibrer qu'une fois toutes les 15 minutes max
_last_calibration: datetime | None = None
CALIBRATION_DEBOUNCE_MINUTES = 15

# Statuts PMU qui indiquent qu'une course est terminée
STATUTS_TERMINES = frozenset({
    "FIN_COURSE",
    "ARRIVEE_DEFINITIVE",
    "ARRIVEE_DEFINITIVE_COMPLETE",
    "COURSE_ARRIVEE",
    "ARRIVEE_PROVISOIRE",
    "TERMINE",
})

logger = logging.getLogger(__name__)


async def _get_db_weights(db: AsyncSession) -> dict | None:
    """Charge les poids depuis la table scoring_weights (discipline PLAT, compatibilité)."""
    result = await db.execute(select(ScoringWeight).where(ScoringWeight.discipline == "PLAT"))
    rows = result.scalars().all()
    if not rows:
        return None
    return {row.critere: row.poids for row in rows}


async def _get_db_weights_by_discipline(db: AsyncSession) -> dict | None:
    """Charge les poids depuis la table scoring_weights, groupés par discipline."""
    result = await db.execute(select(ScoringWeight))
    rows = result.scalars().all()
    if not rows:
        return None
    weights_by_disc: dict[str, dict] = {}
    for row in rows:
        disc = row.discipline or "PLAT"
        if disc not in weights_by_disc:
            weights_by_disc[disc] = {}
        weights_by_disc[disc][row.critere] = row.poids
    return weights_by_disc if weights_by_disc else None


async def _get_auto_weights_by_discipline(db: AsyncSession) -> dict | None:
    """Charge les poids auto-calibrés depuis la table calibration_weights, groupés par discipline."""
    from app.calibration import get_auto_weights_from_db
    auto = await get_auto_weights_from_db(db)
    return auto if auto else None


async def load_programme_today(db: AsyncSession) -> bool:
    """
    Charge le programme du jour depuis l'API PMU si pas déjà en base.
    Retourne True si de nouvelles données ont été chargées.
    """
    date_str = today_str()

    existing = await db.execute(
        select(Reunion).where(Reunion.date_str == date_str).limit(1)
    )
    if existing.scalar_one_or_none():
        return False

    logger.info("Chargement du programme PMU pour %s", date_str)
    data = await pmu_client.get_programme(date_str)

    reunions_data = data.get("reunions", [])
    if not reunions_data:
        logger.warning("Aucune réunion trouvée pour %s", date_str)
        return False

    for r_data in reunions_data:
        reunion = Reunion(
            date_str=date_str,
            num_officiel=r_data["num_officiel"],
            num_externe=r_data["num_externe"],
            hippodrome_code=r_data["hippodrome_code"],
            hippodrome_libelle=r_data["hippodrome_libelle"],
            pays=r_data["pays"],
        )
        db.add(reunion)
        await db.flush()

        for c_data in r_data.get("courses", []):
            statut_pmu = c_data.get("statut", "")
            statut_resultat = "TERMINE" if statut_pmu in STATUTS_TERMINES else "EN_COURS"
            course = Course(
                reunion_id=reunion.id,
                num_ordre=c_data["num_ordre"],
                num_externe=c_data["num_externe"],
                libelle=c_data["libelle"],
                libelle_court=c_data["libelle_court"],
                heure_depart=c_data["heure_depart"],
                distance=c_data["distance"],
                discipline=c_data["discipline"],
                specialite=c_data["specialite"],
                terrain=c_data["terrain"],
                penetrometre_valeur=c_data["penetrometre_valeur"],
                nombre_partants=c_data["nombre_partants"],
                montant_prix=c_data["montant_prix"],
                statut=statut_pmu,
                condition_age=c_data["condition_age"],
                condition_sexe=c_data["condition_sexe"],
                paris_disponibles=",".join(c_data.get("paris_disponibles", [])),
                statut_resultat=statut_resultat,
            )
            db.add(course)

    await db.commit()
    logger.info("Programme chargé : %d réunions", len(reunions_data))
    return True


_last_refresh_time: float = 0.0
REFRESH_COOLDOWN_SECONDS = 300  # 5 minutes


async def refresh_programme_statuts(db: AsyncSession) -> int:
    """
    Met à jour statut_resultat pour les courses du jour et récupère les arrivées manquantes.
    Ne s'exécute qu'une fois toutes les 5 minutes max.
    """
    import time
    global _last_refresh_time
    now = time.time()
    if now - _last_refresh_time < REFRESH_COOLDOWN_SECONDS:
        return 0
    _last_refresh_time = now

    date_str = today_str()

    # Récupérer TOUTES les courses du jour qui n'ont pas encore de positions d'arrivée
    all_courses_result = await db.execute(
        select(Course)
        .join(Reunion)
        .where(Reunion.date_str == date_str)
    )
    all_courses = all_courses_result.scalars().all()

    if not all_courses:
        return 0

    updated = 0
    for course in all_courses:
        # Vérifier si cette course a déjà des positions d'arrivée
        p_check = await db.execute(
            select(Participant).where(
                Participant.course_id == course.id,
                Participant.position_arrivee.isnot(None),
            ).limit(1)
        )
        has_positions = p_check.scalar_one_or_none() is not None

        if has_positions:
            # S'assurer que le statut est TERMINE
            if course.statut_resultat != "TERMINE":
                course.statut_resultat = "TERMINE"
                updated += 1
            continue

        # Pas de positions → tenter de récupérer les arrivées
        try:
            got_arrivee = await fetch_and_store_arrivee(db, course.id)
            if got_arrivee:
                updated += 1
            elif course.statut in STATUTS_TERMINES and course.statut_resultat != "TERMINE":
                course.statut_resultat = "TERMINE"
                updated += 1
        except Exception as e:
            logger.warning("Erreur récup arrivée course %d: %s", course.id, e)

    if updated:
        await db.commit()
        logger.info("refresh_programme_statuts : %d cours(es) mises à jour", updated)

    return updated


async def _refresh_cotes_if_needed(db: AsyncSession, course: Course, reunion: Reunion) -> None:
    """
    Si des participants ont cote_actuelle=null, re-fetch les cotes depuis l'API PMU,
    met à jour cote_actuelle en base, et recalcule score_cote / score_global / is_value_bet.
    """
    # Vérifier s'il y a des cotes manquantes
    result = await db.execute(
        select(Participant).where(
            Participant.course_id == course.id,
            Participant.cote_actuelle.is_(None),
        )
    )
    participants_without_cote = result.scalars().all()
    if not participants_without_cote:
        return

    # Appeler l'API PMU pour récupérer les cotes
    try:
        participants_data = await pmu_client.get_participants(
            reunion.date_str, reunion.num_officiel, course.num_externe
        )
    except Exception:
        return

    if not participants_data:
        return

    # Construire un dict num_pmu -> cotes
    cotes_map = {}
    for p_data in participants_data:
        num = p_data.get("num_pmu")
        cote = p_data.get("cote_actuelle")
        if num and cote:
            cotes_map[num] = cote

    if not cotes_map:
        return

    # Charger les poids DB pour cette discipline (même logique que load_participants_for_course)
    db_weights_by_disc = await _get_db_weights_by_discipline(db)
    w = get_weights_for_discipline(course.discipline, db_weights_by_disc)
    w_value_cote = w.get("value_cote", 0.0)

    # Mettre à jour les participants en base + recalculer les scores dépendant de la cote
    updated_count = 0
    for p in participants_without_cote:
        if p.num_pmu in cotes_map:
            nouvelle_cote = cotes_map[p.num_pmu]
            p.cote_actuelle = nouvelle_cote

            # Recalculer score_cote (dépend uniquement de cote_actuelle)
            new_score_cote = scoring_score_cote(nouvelle_cote)
            delta_cote = new_score_cote - p.score_cote  # old score_cote was 50.0 (cote=None)

            # Mettre à jour score_cote
            p.score_cote = new_score_cote

            # Ajuster score_global, score_global_expert, score_global_auto
            # par le delta de la composante value_cote
            p.score_global = round(p.score_global + delta_cote * w_value_cote, 2)
            p.score_global_expert = round(p.score_global_expert + delta_cote * w_value_cote, 2)
            p.score_global_auto = round(p.score_global_auto + delta_cote * w_value_cote, 2)
            # score_sans_cote exclut la composante cote, pas de changement

            # Recalculer is_value_bet et confiance avec les nouveaux scores
            p.is_value_bet = scoring_is_value_bet(nouvelle_cote, p.score_global, course.discipline)
            p.confiance = get_confiance(p.score_global)

            updated_count += 1

    await db.commit()
    logger.info(
        "Cotes + scores mis à jour pour course %s: %d participants (w_value_cote=%.2f)",
        course.libelle, updated_count, w_value_cote,
    )


async def load_participants_for_course(db: AsyncSession, course: Course, reunion: Reunion) -> bool:
    """
    Charge les participants d'une course si pas déjà fait.
    Si déjà chargés mais cotes manquantes, met à jour les cotes depuis l'API.
    """
    if course.participants_loaded:
        # Vérifier si les cotes sont manquantes — les mettre à jour si oui
        await _refresh_cotes_if_needed(db, course, reunion)
        return False

    # Double-check: participants may already exist in DB (race condition guard)
    existing_check = await db.execute(
        select(Participant).where(Participant.course_id == course.id).limit(1)
    )
    if existing_check.scalar_one_or_none() is not None:
        # Participants already loaded by a concurrent request — just mark flag
        course.participants_loaded = True
        await db.commit()
        await _refresh_cotes_if_needed(db, course, reunion)
        return False

    date_str = reunion.date_str
    participants_data = await pmu_client.get_participants(
        date_str, reunion.num_officiel, course.num_externe
    )

    if not participants_data:
        course.participants_loaded = True
        await db.commit()
        return False

    # Charger les poids depuis DB (par discipline)
    db_weights_by_disc = await _get_db_weights_by_discipline(db)
    auto_weights_by_disc = await _get_auto_weights_by_discipline(db)

    scored = calculer_scores(
        participants_data,
        course.distance,
        course.terrain,
        course.penetrometre_valeur,
        nombre_partants=course.nombre_partants,
        hippodrome=reunion.hippodrome_libelle,
        discipline=course.discipline,
        db_weights_by_disc=db_weights_by_disc,
        auto_weights_by_disc=auto_weights_by_disc,
    )

    for p_data in scored:
        participant = Participant(
            course_id=course.id,
            num_pmu=p_data["num_pmu"],
            nom=p_data["nom"],
            jockey=p_data["jockey"],
            entraineur=p_data["entraineur"],
            proprietaire=p_data.get("proprietaire", ""),
            cote_actuelle=p_data["cote_actuelle"],
            cote_initiale=p_data["cote_initiale"],
            musique=p_data["musique"],
            poids=p_data["poids"],
            handicap_distance=p_data["handicap_distance"],
            age=p_data["age"],
            sexe=p_data["sexe"],
            provenance=p_data["provenance"],
            score_global=p_data["score_global"],
            score_forme=p_data["score_forme"],
            score_cote=p_data["score_cote"],
            score_jockey=p_data["score_jockey"],
            score_entraineur=p_data["score_entraineur"],
            score_distance=p_data["score_distance"],
            score_terrain=p_data["score_terrain"],
            score_repos=p_data.get("score_repos", 0.0),
            score_partants=p_data.get("score_partants", 0.0),
            score_hippodrome=p_data.get("score_hippodrome", 0.0),
            score_poids=p_data.get("score_poids", 0.0),
            score_corde=p_data.get("score_corde", 50.0),
            score_regularite=p_data.get("score_regularite", 50.0),
            score_recence=p_data.get("score_recence", 50.0),
            driver_change=p_data.get("driver_change", False),
            score_outsider=p_data.get("score_outsider", 0.0),
            score_global_expert=p_data.get("score_expert", p_data["score_global"]),
            score_global_auto=p_data.get("score_auto", p_data["score_global"]),
            score_sans_cote=p_data.get("score_sans_cote", p_data["score_global"]),
            score_gains=p_data.get("score_gains", 50.0),
            score_age=p_data.get("score_age", 50.0),
            is_value_bet=p_data["is_value_bet"],
            confiance=p_data["confiance"],
            explication=p_data["explication"],
        )
        db.add(participant)

    course.participants_loaded = True
    await db.commit()
    return True


# ---- F1 : Résultats en temps réel ----

async def fetch_and_store_arrivee(db: AsyncSession, course_id: int) -> bool:
    """
    Récupère le classement d'arrivée PMU pour une course et met à jour la DB.
    Retourne True si l'arrivée a été trouvée et stockée.
    """
    result = await db.execute(
        select(Course).where(Course.id == course_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        return False

    # Récupérer la réunion
    r_result = await db.execute(
        select(Reunion).where(Reunion.id == course.reunion_id)
    )
    reunion = r_result.scalar_one_or_none()
    if not reunion:
        return False

    if not course.participants_loaded:
        await load_participants_for_course(db, course, reunion)

    # Appel API arrivée
    arrivee = await pmu_client.get_arrivee(
        reunion.date_str, reunion.num_officiel, course.num_externe
    )
    if not arrivee:
        return False

    logger.info("Arrivée reçue pour course %d : %s", course_id, arrivee)

    # Mettre à jour les positions des participants
    positions_map = {item["numero_cheval"]: item["position"] for item in arrivee}

    participants_result = await db.execute(
        select(Participant).where(Participant.course_id == course_id)
    )
    participants = participants_result.scalars().all()
    if not participants:
        return False

    for p in participants:
        p.position_arrivee = positions_map.get(p.num_pmu)

    course.statut_resultat = "TERMINE"
    await db.commit()

    # Évaluer les paris liés à cette course
    await evaluer_paris_pour_course(db, course_id)

    # Recalibrer automatiquement les poids auto (debounce : max 1 fois / 15 min)
    global _last_calibration
    now = datetime.now()
    if _last_calibration is None or (now - _last_calibration) > timedelta(minutes=CALIBRATION_DEBOUNCE_MINUTES):
        try:
            from app.calibration import calibrate_and_store
            await calibrate_and_store(db)
            _last_calibration = now
            logger.info("Auto-calibration des poids effectuée après arrivée course %d", course_id)
        except Exception as e:
            logger.warning("Erreur auto-calibration: %s", e)
    else:
        remaining = CALIBRATION_DEBOUNCE_MINUTES - int((now - _last_calibration).total_seconds() / 60)
        logger.debug("Auto-calibration ignorée (debounce, prochaine dans ~%d min)", remaining)

    return True


async def evaluer_paris_pour_course(db: AsyncSession, course_id: int) -> None:
    """
    Évalue tous les paris EN_ATTENTE pour une course terminée.
    Met à jour statut (GAGNE/PERDU) et gain_reel.
    """
    # Récupérer participants avec positions
    p_result = await db.execute(
        select(Participant).where(Participant.course_id == course_id)
    )
    participants = {p.num_pmu: p for p in p_result.scalars().all()}

    if not any(p.position_arrivee is not None for p in participants.values()):
        return  # Pas encore de résultats

    # Récupérer le nombre de partants pour appliquer la règle PMU place
    course_result = await db.execute(select(Course).where(Course.id == course_id))
    course_obj = course_result.scalar_one_or_none()
    nombre_partants = course_obj.nombre_partants if course_obj else 0
    # Règle PMU : place = top3 si ≥8 partants, top2 si 4-7 partants
    place_threshold = 3 if nombre_partants >= 8 else 2

    # Récupérer les paris en attente
    bets_result = await db.execute(
        select(Bet).where(Bet.course_id == course_id, Bet.statut == "EN_ATTENTE")
    )
    bets = bets_result.scalars().all()

    for bet in bets:
        try:
            chevaux = json.loads(bet.chevaux_json or "[]")
        except (json.JSONDecodeError, TypeError):
            chevaux = []

        try:
            numeros = [int(c.get("numero", 0)) for c in chevaux if c.get("numero") is not None]
        except (ValueError, TypeError):
            numeros = []
        positions = []
        for num in numeros:
            p = participants.get(num)
            positions.append(p.position_arrivee if p and p.position_arrivee else 999)

        gagne = False
        gain = 0.0

        if bet.type_pari == "GAGNANT":
            if positions and positions[0] == 1:
                gagne = True
                cote = chevaux[0].get("cote") if chevaux else None
                gain = bet.montant * float(cote) if cote else bet.montant * 2

        elif bet.type_pari == "PLACE":
            if positions and positions[0] <= place_threshold:
                gagne = True
                cote = chevaux[0].get("cote") if chevaux else None
                gain = bet.montant * (float(cote) / 4) if cote else bet.montant * 1.5

        elif bet.type_pari == "COUPLE":
            if len(positions) >= 2:
                top2_set = {1, 2}
                gagne = set(positions[:2]) == top2_set
                if gagne:
                    gain = bet.montant * 8  # rapport approximatif

        elif bet.type_pari == "TIERCE":
            if len(positions) >= 3:
                gagne = set(positions[:3]) == {1, 2, 3}
                if gagne:
                    gain = bet.montant * 15

        elif bet.type_pari == "DEUX_SUR_QUATRE":
            # 2 chevaux choisis, les 2 doivent être dans le top 4
            if len(positions) >= 2:
                top4_hits = sum(1 for pos in positions[:2] if pos <= 4)
                gagne = top4_hits >= 2
                if gagne:
                    gain = bet.montant * 4

        bet.statut = "GAGNE" if gagne else "PERDU"
        bet.gain_reel = round(gain, 2) if gagne else 0.0

    await db.commit()


async def trigger_arrivee_refresh(db: AsyncSession) -> int:
    """
    Essaie de récupérer les arrivées pour toutes les courses du jour
    dont le résultat n'est pas encore connu (statut_resultat == EN_COURS).
    Retourne le nombre de courses mises à jour.
    """
    date_str = today_str()
    result = await db.execute(
        select(Course)
        .join(Reunion)
        .where(
            Reunion.date_str == date_str,
            Course.statut_resultat == "EN_COURS",
        )
    )
    courses = result.scalars().all()

    updated = 0
    for course in courses:
        try:
            if await fetch_and_store_arrivee(db, course.id):
                updated += 1
        except Exception as e:
            logger.warning("Erreur arrivée course %d : %s", course.id, e)

    return updated


async def recuperer_arrivees_manquantes(db: AsyncSession) -> int:
    """
    Passe dédiée (sans cooldown) : pour chaque course du jour avec statut_resultat=TERMINE
    mais sans aucune position_arrivee, tente fetch_and_store_arrivee.
    Appelée après le refresh programme pour rattraper les courses dont le statut a été
    mis à TERMINE avant que l'API PMU ne rende les arrivées disponibles.
    Retourne le nombre de courses dont les arrivées ont été récupérées.
    """
    date_str = today_str()

    # Courses TERMINE sans positions d'arrivée
    courses_result = await db.execute(
        select(Course)
        .join(Reunion)
        .where(
            Reunion.date_str == date_str,
            Course.statut_resultat == "TERMINE",
        )
    )
    courses = courses_result.scalars().all()

    recovered = 0
    for course in courses:
        # Vérifier s'il manque des positions
        p_check = await db.execute(
            select(Participant).where(
                Participant.course_id == course.id,
                Participant.position_arrivee.isnot(None),
            ).limit(1)
        )
        has_positions = p_check.scalar_one_or_none() is not None
        if has_positions:
            continue

        # Course TERMINE sans positions → re-tenter
        try:
            got = await fetch_and_store_arrivee(db, course.id)
            if got:
                recovered += 1
                logger.info(
                    "recuperer_arrivees_manquantes : arrivée récupérée pour course %d (%s)",
                    course.id, course.libelle,
                )
            else:
                logger.debug(
                    "recuperer_arrivees_manquantes : API pas encore dispo pour course %d (%s)",
                    course.id, course.libelle,
                )
        except Exception as e:
            logger.warning("Erreur recuperer_arrivees_manquantes course %d : %s", course.id, e)

    if recovered:
        logger.info("recuperer_arrivees_manquantes : %d arrivée(s) récupérée(s)", recovered)

    return recovered


async def backfill_participants_pour_courses_termine(db: AsyncSession, jours: int = 7) -> dict:
    """
    Charge les participants manquants pour toutes les courses TERMINE des N derniers jours.

    Couvre deux cas :
      1. participants_loaded=False  → jamais tenté
      2. participants_loaded=True MAIS aucun participant en DB (API PMU renvoyait vide lors
         du premier essai — ces courses sont maintenant re-tentées systématiquement)

    Throttle : 0.1s entre chaque appel API (réduit depuis 0.3s pour finir avant timeout Render).
    Retourne un dict avec les compteurs : courses_traitees, succes, echecs.
    """
    from app.config import PARIS_TZ
    from sqlalchemy import func, exists

    now = datetime.now(PARIS_TZ)
    date_strs = []
    for delta in range(0, jours + 1):
        d = now - timedelta(days=delta)
        date_strs.append(d.strftime("%d%m%Y"))

    logger.info("[BACKFILL] Démarrage backfill participants — %d derniers jours (%s)", jours, ", ".join(date_strs))

    # Cas 1 : jamais tentées (participants_loaded=False)
    result1 = await db.execute(
        select(Course, Reunion)
        .join(Reunion, Course.reunion_id == Reunion.id)
        .where(
            Course.statut_resultat == "TERMINE",
            Course.participants_loaded == False,  # noqa: E712
            Reunion.date_str.in_(date_strs),
        )
    )
    rows_not_loaded = result1.all()

    # Cas 2 : marquées chargées MAIS 0 participant en DB (API PMU vide au 1er passage)
    from app.models import Participant as _Participant
    subq_has_part = (
        select(_Participant.id)
        .where(_Participant.course_id == Course.id)
        .limit(1)
        .correlate(Course)
    )
    result2 = await db.execute(
        select(Course, Reunion)
        .join(Reunion, Course.reunion_id == Reunion.id)
        .where(
            Course.statut_resultat == "TERMINE",
            Course.participants_loaded == True,  # noqa: E712
            ~exists(subq_has_part),
            Reunion.date_str.in_(date_strs),
        )
    )
    rows_loaded_empty = result2.all()

    # Fusionner en évitant les doublons (par course.id)
    seen_ids: set[int] = set()
    rows: list = []
    for row in rows_not_loaded + rows_loaded_empty:
        if row[0].id not in seen_ids:
            seen_ids.add(row[0].id)
            rows.append(row)

    total = len(rows)
    succes = 0
    echecs = 0

    logger.info(
        "[BACKFILL] %d course(s) à traiter — %d jamais tentées, %d marquées chargées mais vides",
        total, len(rows_not_loaded), len(rows_loaded_empty),
    )

    for course, reunion in rows:
        # Réinitialiser le flag pour forcer le re-chargement des courses vides
        if course.participants_loaded and course.id in {r[0].id for r in rows_loaded_empty}:
            course.participants_loaded = False
            await db.commit()

        try:
            loaded = await load_participants_for_course(db, course, reunion)
            if loaded:
                succes += 1
                logger.info(
                    "[BACKFILL] OK — %s (%s R%s C%s)",
                    course.libelle, reunion.date_str, reunion.num_officiel, course.num_externe,
                )
            else:
                succes += 1
                logger.debug(
                    "[BACKFILL] déjà chargé ou API vide — course %d (%s)",
                    course.id, course.libelle,
                )
        except Exception as e:
            echecs += 1
            logger.warning(
                "[BACKFILL] ECHEC course %d (%s) : %s",
                course.id, course.libelle, e,
            )
        # Throttle réduit : 0.1s au lieu de 0.3s pour finir dans le délai Render free tier
        await asyncio.sleep(0.1)

    logger.info(
        "[BACKFILL] Terminé — %d traité(es), %d succès, %d échec(s)",
        total, succes, echecs,
    )
    return {"courses_traitees": total, "succes": succes, "echecs": echecs}
