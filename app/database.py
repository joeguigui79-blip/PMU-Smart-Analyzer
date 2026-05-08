from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import DATABASE_URL, SCORING_WEIGHTS_DISCIPLINE
from sqlalchemy.pool import NullPool


# Pour Supabase (PgBouncer) : NullPool + statement_cache_size=0 dans l'URL
_engine_kwargs = {"echo": False}
if "postgresql" in DATABASE_URL or "asyncpg" in DATABASE_URL:
    # NullPool évite les conflits avec PgBouncer
    _engine_kwargs["poolclass"] = NullPool
    # Passer statement_cache_size via connect_args pour asyncpg
    _engine_kwargs["connect_args"] = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)
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
