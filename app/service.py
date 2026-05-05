"""
Service layer : chargement et mise à jour des données PMU en base.
"""
import json
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Reunion, Course, Participant, Bet, ScoringWeight
from app.pmu_client import pmu_client
from app.scoring import calculer_scores, load_weights_from_config_or_db
from app.config import today_str

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
                statut=c_data["statut"],
                condition_age=c_data["condition_age"],
                condition_sexe=c_data["condition_sexe"],
                paris_disponibles=",".join(c_data.get("paris_disponibles", [])),
            )
            db.add(course)

    await db.commit()
    logger.info("Programme chargé : %d réunions", len(reunions_data))
    return True


async def load_participants_for_course(db: AsyncSession, course: Course, reunion: Reunion) -> bool:
    """
    Charge les participants d'une course si pas déjà fait.
    """
    if course.participants_loaded:
        return False

    # Double-check: participants may already exist in DB (race condition guard)
    existing_check = await db.execute(
        select(Participant).where(Participant.course_id == course.id).limit(1)
    )
    if existing_check.scalar_one_or_none() is not None:
        # Participants already loaded by a concurrent request — just mark flag
        course.participants_loaded = True
        await db.commit()
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

    scored = calculer_scores(
        participants_data,
        course.distance,
        course.terrain,
        course.penetrometre_valeur,
        nombre_partants=course.nombre_partants,
        hippodrome=reunion.hippodrome_libelle,
        discipline=course.discipline,
        db_weights_by_disc=db_weights_by_disc,
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

        numeros = [int(c.get("numero", 0)) for c in chevaux]
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
            if positions and positions[0] <= 3:
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
