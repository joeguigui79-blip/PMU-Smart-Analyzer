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
from app.service import load_programme_today, load_participants_for_course, fetch_and_store_arrivee
from app.config import today_str

router = APIRouter(prefix="/api", tags=["courses"])


@router.get("/reunions", response_model=list[ReunionSchema])
async def list_reunions(db: AsyncSession = Depends(get_db)):
    """Liste toutes les réunions du jour avec leurs courses."""
    await load_programme_today(db)
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
    await load_programme_today(db)
    date_str = today_str()
    result = await db.execute(
        select(Course)
        .join(Reunion)
        .where(Reunion.date_str == date_str)
        .order_by(Course.heure_depart, Course.id)
    )
    courses = result.scalars().all()
    return courses


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
    await fetch_and_store_arrivee(db, course.id)

    await db.refresh(course)
    result2 = await db.execute(
        select(Course)
        .where(Course.id == course_id)
        .options(selectinload(Course.participants), selectinload(Course.reunion))
    )
    course = result2.scalar_one()

    participants = sorted(course.participants, key=lambda p: p.score_global, reverse=True)
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
    await db.refresh(course)

    result2 = await db.execute(
        select(Participant)
        .where(Participant.course_id == course_id)
        .order_by(Participant.score_global.desc())
    )
    participants = result2.scalars().all()

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
    """Force le rechargement du programme depuis l'API PMU."""
    date_str = today_str()
    result = await db.execute(
        select(Reunion).where(Reunion.date_str == date_str)
    )
    reunions = result.scalars().all()
    for r in reunions:
        await db.delete(r)
    await db.commit()

    loaded = await load_programme_today(db)
    return {"success": True, "loaded": loaded, "date": date_str}
