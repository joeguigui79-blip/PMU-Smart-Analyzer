from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Reunion, Course, Participant
from app.schemas import (
    CourseSchema, CourseDetailSchema, ReunionSchema, ParticipantSchema,
    CourseSuggestionsSchema,
)
import app.service as _svc
from app.service import load_programme_today, load_participants_for_course, fetch_and_store_arrivee, refresh_programme_statuts, recuperer_arrivees_manquantes, _get_db_weights_by_discipline, _get_auto_weights_by_discipline
from app.scoring import calculer_scores
from app.pmu_client import pmu_client
from app.config import today_str

router = APIRouter(prefix="/api", tags=["courses"])


@router.get("/reunions", response_model=list[ReunionSchema])
async def list_reunions(db: AsyncSession = Depends(get_db)):
    """Liste toutes les réunions du jour avec leurs courses."""
    date_str = today_str()
    result = await db.execute(
        select(Reunion)
        .where(Reunion.date_str == date_str)
        .options(selectinload(Reunion.courses))
        .order_by(Reunion.num_officiel)
    )
    reunions = result.scalars().all()
    return reunions


@router.get("/courses", response_model=list[CourseSchema])
async def list_courses(db: AsyncSession = Depends(get_db)):
    """Liste toutes les courses du jour."""
    date_str = today_str()
    result = await db.execute(
        select(Course)
        .join(Reunion)
        .where(Reunion.date_str == date_str)
        .order_by(Reunion.num_officiel, Course.num_externe)
    )
    courses = result.scalars().all()
    return courses


@router.post("/refresh-programme", status_code=200)
async def refresh_programme_data(db: AsyncSession = Depends(get_db)):
    """Charge le programme PMU du jour et met à jour les statuts."""
    loaded = await load_programme_today(db)
    await refresh_programme_statuts(db)
    return {"success": True, "loaded": loaded, "date": today_str()}


@router.get("/courses/{course_id}", response_model=CourseDetailSchema)
async def get_course(course_id: int, db: AsyncSession = Depends(get_db)):
    """Détails d'une course avec participants et scores."""
    result = await db.execute(
        select(Course)
        .where(Course.id == course_id)
        .options(selectinload(Course.participants), selectinload(Course.reunion))
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    await load_participants_for_course(db, course, course.reunion)
    # Tenter de récupérer les arrivées si pas encore de positions en DB
    has_positions = any(p.position_arrivee is not None for p in course.participants)
    if not has_positions:
        await fetch_and_store_arrivee(db, course.id)
        await db.refresh(course, attribute_names=["participants"])

    participants = sorted(course.participants, key=lambda p: p.score_global or 0, reverse=True)
    value_bets = [p for p in participants if p.is_value_bet]
    top_pick = participants[0] if participants else None

    return CourseDetailSchema(
        id=course.id,
        reunion_id=course.reunion_id,
        num_ordre=course.num_ordre,
        libelle=course.libelle,
        libelle_court=course.libelle_court,
        heure_depart=course.heure_depart,
        distance=course.distance,
        discipline=course.discipline,
        specialite=course.specialite,
        terrain=course.terrain,
        penetrometre_valeur=course.penetrometre_valeur,
        nombre_partants=course.nombre_partants,
        montant_prix=course.montant_prix,
        statut=course.statut,
        statut_resultat=course.statut_resultat,
        condition_age=course.condition_age,
        condition_sexe=course.condition_sexe,
        paris_disponibles=course.paris_disponibles or "",
        participants_loaded=course.participants_loaded,
        hippodrome=course.reunion.hippodrome_libelle,
        participants=[ParticipantSchema.model_validate(p) for p in participants],
        top_pick=ParticipantSchema.model_validate(top_pick) if top_pick else None,
        value_bets=[ParticipantSchema.model_validate(p) for p in value_bets],
    )


@router.get("/courses/{course_id}/suggestions", response_model=CourseSuggestionsSchema)
async def get_course_suggestions(course_id: int, db: AsyncSession = Depends(get_db)):
    """Retourne les suggestions de combos IA pour une course."""
    result = await db.execute(
        select(Course)
        .where(Course.id == course_id)
        .options(selectinload(Course.participants), selectinload(Course.reunion))
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    # Charger les participants si nécessaire
    await load_participants_for_course(db, course, course.reunion)
    await db.refresh(course, attribute_names=["participants"])

    participants = (
        await db.execute(
            select(Participant)
            .where(Participant.course_id == course_id)
            .order_by(Participant.score_global.desc())
        )
    ).scalars().all()

    if not participants:
        return CourseSuggestionsSchema()

    ps = [ParticipantSchema.model_validate(p) for p in participants]

    return CourseSuggestionsSchema(
        gagnant=ps[0] if len(ps) >= 1 else None,
        place=ps[0] if len(ps) >= 1 else None,
        couple=ps[:2] if len(ps) >= 2 else ps,
        tierce=ps[:3] if len(ps) >= 3 else ps,
        deux_sur_quatre=ps[:2] if len(ps) >= 2 else ps,
    )


@router.post("/refresh", status_code=200)
async def refresh_programme(db: AsyncSession = Depends(get_db)):
    """Force le rechargement du programme depuis l'API PMU (mise à jour non-destructive).

    Au lieu de supprimer/recréer les réunions (ce qui détruit participants et arrivées),
    on récupère le programme frais et on met à jour les champs en place.
    Les participants et positions d'arrivée déjà en base sont préservés.
    """
    date_str = today_str()

    # Récupérer le programme frais depuis l'API PMU
    data = await pmu_client.get_programme(date_str)
    reunions_data = data.get("reunions", [])

    if not reunions_data:
        # Aucune donnée PMU — bypass cooldown et rafraîchir les statuts seulement
        _svc._last_refresh_time = 0
        await refresh_programme_statuts(db)
        arrivees_recuperees = await recuperer_arrivees_manquantes(db)
        return {"success": False, "loaded": False, "date": date_str, "arrivees_recuperees": arrivees_recuperees}

    # Récupérer les réunions existantes (mise à jour en place, pas de suppression)
    existing_reunions_result = await db.execute(
        select(Reunion).where(Reunion.date_str == date_str)
    )
    existing_reunions = {r.num_officiel: r for r in existing_reunions_result.scalars().all()}

    new_items = 0
    for r_data in reunions_data:
        num_off = r_data["num_officiel"]
        if num_off in existing_reunions:
            reunion = existing_reunions[num_off]
        else:
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
            new_items += 1

        # Courses existantes pour cette réunion
        existing_courses_result = await db.execute(
            select(Course).where(Course.reunion_id == reunion.id)
        )
        existing_courses = {c.num_externe: c for c in existing_courses_result.scalars().all()}

        for c_data in r_data.get("courses", []):
            statut_pmu = c_data.get("statut", "")
            num_ext = c_data["num_externe"]

            if num_ext in existing_courses:
                course = existing_courses[num_ext]
                # Mettre à jour le statut PMU brut
                course.statut = statut_pmu
                # NE PAS forcer TERMINE ici : le statut PMU des courses étrangères
                # (R5/R6 internationales) n'est pas fiable. refresh_programme_statuts,
                # appelé juste après, vérifie les arrivées réelles avant de passer
                # une course à TERMINE.
                # Mettre à jour le nombre de partants si changé
                course.nombre_partants = c_data["nombre_partants"]
            else:
                # Toujours créer en EN_COURS : refresh_programme_statuts se chargera
                # de passer la course à TERMINE si elle a des arrivées vérifiées.
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
                    statut_resultat="EN_COURS",
                )
                db.add(course)
                new_items += 1

    await db.commit()

    # Bypass du cooldown pour forcer le refresh des statuts et des arrivées manquantes
    _svc._last_refresh_time = 0
    await refresh_programme_statuts(db)

    # Passe supplémentaire : récupérer les arrivées des courses TERMINE sans positions
    # (cas où le statut TERMINE a été enregistré avant que l'API PMU rende l'arrivée disponible)
    arrivees_recuperees = await recuperer_arrivees_manquantes(db)

    return {"success": True, "loaded": True, "date": date_str, "arrivees_recuperees": arrivees_recuperees}


@router.get("/courses/{course_id}/live-scores")
async def get_live_scores(course_id: int, db: AsyncSession = Depends(get_db)):
    """
    Recalcule les scores avec les cotes en temps réel depuis l'API PMU.
    Utilise les poids Auto (calibrés) pour le calcul.
    """
    result = await db.execute(
        select(Course)
        .where(Course.id == course_id)
        .options(selectinload(Course.participants), selectinload(Course.reunion))
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    reunion = course.reunion

    # Récupérer les cotes fraîches depuis l'API PMU
    try:
        participants_data = await pmu_client.get_participants(
            reunion.date_str, reunion.num_officiel, course.num_externe
        )
    except Exception:
        raise HTTPException(status_code=502, detail="Impossible de récupérer les cotes PMU")

    if not participants_data:
        raise HTTPException(status_code=404, detail="Aucun participant PMU")

    # Mettre à jour les cotes en base aussi
    cotes_map = {p.get("num_pmu"): p.get("cote_actuelle") for p in participants_data if p.get("cote_actuelle")}
    for p in course.participants:
        if p.num_pmu in cotes_map:
            p.cote_actuelle = cotes_map[p.num_pmu]
    await db.commit()

    # Recalculer les scores avec les cotes fraîches et les poids Auto
    auto_weights_by_disc = await _get_auto_weights_by_discipline(db)
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
        auto_weights_by_disc=auto_weights_by_disc,
    )

    # Retourner les participants triés par score auto
    results = []
    for p in sorted(scored, key=lambda x: x.get("score_auto", x["score_global"]), reverse=True):
        results.append({
            "num_pmu": p["num_pmu"],
            "nom": p["nom"],
            "score_live": p.get("score_auto", p["score_global"]),
            "cote_actuelle": p.get("cote_actuelle"),
            "score_cote": p.get("score_cote", 0),
        })

    return {"course_id": course_id, "participants": results}


@router.get("/courses/{course_id}/pronostics")
async def get_pronostics(course_id: int, db: AsyncSession = Depends(get_db)):
    """Récupère les pronostics Equidia pour une course."""
    result = await db.execute(
        select(Course)
        .where(Course.id == course_id)
        .options(selectinload(Course.reunion))
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    reunion = course.reunion
    prono = await pmu_client.get_pronostics(
        reunion.date_str, reunion.num_officiel, course.num_externe
    )

    if not prono:
        return {"source": None, "selection": []}

    return prono
