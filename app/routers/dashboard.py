from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Reunion, Course, Participant, DailyStats
from app.schemas import DashboardSchema, ReunionSchema, ParticipantSchema, DailyStatsSchema
from app.service import load_programme_today
from app.config import today_str

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardSchema)
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """Résumé du jour : stats globales et top recommandations."""
    await load_programme_today(db)
    date_str = today_str()

    # Réunions avec courses
    result = await db.execute(
        select(Reunion)
        .where(Reunion.date_str == date_str)
        .options(selectinload(Reunion.courses))
        .order_by(Reunion.num_officiel)
    )
    reunions = result.scalars().all()

    nb_reunions = len(reunions)
    nb_courses = sum(len(r.courses) for r in reunions)

    # Compter les value bets (parmi les courses déjà analysées)
    vb_result = await db.execute(
        select(func.count(Participant.id))
        .join(Course)
        .join(Reunion)
        .where(Reunion.date_str == date_str)
        .where(Participant.is_value_bet.is_(True))
    )
    nb_value_bets = vb_result.scalar_one() or 0

    # Top 5 picks globaux (meilleurs scores toutes courses confondues)
    top_result = await db.execute(
        select(Participant)
        .join(Course)
        .join(Reunion)
        .where(Reunion.date_str == date_str)
        .order_by(Participant.score_global.desc())
        .limit(5)
    )
    top_picks = top_result.scalars().all()

    return DashboardSchema(
        date=date_str,
        nb_reunions=nb_reunions,
        nb_courses=nb_courses,
        nb_value_bets=nb_value_bets,
        top_picks=[ParticipantSchema.model_validate(p) for p in top_picks],
        reunions=[ReunionSchema.model_validate(r) for r in reunions],
    )


@router.get("/stats", response_model=list[DailyStatsSchema])
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Statistiques des 7 derniers jours (upsert depuis la DB en temps réel)."""
    today = datetime.utcnow().date()
    days = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        # DDMMYYYY format used in reunions
        ddmmyyyy = day.strftime("%d%m%Y")

        # Count courses for that day
        courses_result = await db.execute(
            select(func.count(Course.id))
            .join(Reunion)
            .where(Reunion.date_str == ddmmyyyy)
        )
        nb_courses = courses_result.scalar_one() or 0

        # Count value bets
        vb_result = await db.execute(
            select(func.count(Participant.id))
            .join(Course)
            .join(Reunion)
            .where(Reunion.date_str == ddmmyyyy)
            .where(Participant.is_value_bet.is_(True))
        )
        nb_value_bets = vb_result.scalar_one() or 0

        # Count finished courses
        fin_result = await db.execute(
            select(func.count(Course.id))
            .join(Reunion)
            .where(Reunion.date_str == ddmmyyyy)
            .where(Course.statut_resultat == 'TERMINE')
        )
        nb_finished = fin_result.scalar_one() or 0

        days.append(DailyStatsSchema(
            date=day_str,
            nb_courses=nb_courses,
            nb_value_bets=nb_value_bets,
            nb_top_picks_correct=0,
            nb_courses_finished=nb_finished,
        ))

    return days
