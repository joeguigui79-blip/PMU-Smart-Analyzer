from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import DATABASE_URL, SCORING_WEIGHTS_DISCIPLINE


# statement_cache_size=0 requis pour Supabase (PgBouncer ne supporte pas les prepared statements)
connect_args = {}
if "postgresql" in DATABASE_URL or "postgres" in DATABASE_URL:
    connect_args = {"statement_cache_size": 0}
engine = create_async_engine(DATABASE_URL, echo=False, connect_args=connect_args)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Crée les tables si elles n'existent pas (CREATE TABLE IF NOT EXISTS via create_all).
    Aucun drop/recreate : compatible PostgreSQL (Supabase) et SQLite local.
    """
    from app import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_scoring_weights()


async def seed_scoring_weights():
    """Insère les poids par défaut par discipline si la table est vide."""
    from sqlalchemy import select
    from app.models import ScoringWeight
    from datetime import datetime

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ScoringWeight).limit(1))
        if result.scalar_one_or_none() is not None:
            return  # déjà initialisé

        for disc, weights in SCORING_WEIGHTS_DISCIPLINE.items():
            for critere, poids in weights.items():
                session.add(ScoringWeight(
                    discipline=disc,
                    critere=critere,
                    poids=poids,
                    precision=0.0,
                    nb_samples=0,
                    updated_at=datetime.utcnow(),
                ))
        await session.commit()


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
