import logging
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardSchema)
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """Résumé du jour : stats globales et top recommandations."""
    try:
        await load_programme_today(db)
    except Exception as exc:
        logger.warning("load_programme_today failed (non-blocking): %s", exc)
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
    """Statistiques des 7 derniers jours — 3 requêtes groupées au lieu de 21."""
    today = datetime.utcnow().date()

    # Préparer les 7 jours : date ISO (clé de sortie) et DDMMYYYY (filtre DB)
    date_range = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        date_range.append((day.strftime("%Y-%m-%d"), day.strftime("%d%m%Y")))

    ddmmyyyy_list = [ddmmyyyy for _, ddmmyyyy in date_range]

    # 1. Nombre de courses par jour
    courses_rows = await db.execute(
        select(Reunion.date_str, func.count(Course.id))
        .join(Course, Course.reunion_id == Reunion.id)
        .where(Reunion.date_str.in_(ddmmyyyy_list))
        .group_by(Reunion.date_str)
    )
    courses_by_date: dict[str, int] = {row[0]: row[1] for row in courses_rows}

    # 2. Nombre de value bets par jour
    vb_rows = await db.execute(
        select(Reunion.date_str, func.count(Participant.id))
        .join(Course, Course.reunion_id == Reunion.id)
        .join(Participant, Participant.course_id == Course.id)
        .where(Reunion.date_str.in_(ddmmyyyy_list))
        .where(Participant.is_value_bet.is_(True))
        .group_by(Reunion.date_str)
    )
    vb_by_date: dict[str, int] = {row[0]: row[1] for row in vb_rows}

    # 3. Nombre de courses terminées par jour
    fin_rows = await db.execute(
        select(Reunion.date_str, func.count(Course.id))
        .join(Course, Course.reunion_id == Reunion.id)
        .where(Reunion.date_str.in_(ddmmyyyy_list))
        .where(Course.statut_resultat == 'TERMINE')
        .group_by(Reunion.date_str)
    )
    fin_by_date: dict[str, int] = {row[0]: row[1] for row in fin_rows}

    # Assembler les résultats
    return [
        DailyStatsSchema(
            date=day_str,
            nb_courses=courses_by_date.get(ddmmyyyy, 0),
            nb_value_bets=vb_by_date.get(ddmmyyyy, 0),
            nb_top_picks_correct=0,
            nb_courses_finished=fin_by_date.get(ddmmyyyy, 0),
        )
        for day_str, ddmmyyyy in date_range
    ]
