from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import DATABASE_URL, SCORING_WEIGHTS, SCORING_WEIGHTS_DISCIPLINE


engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Colonnes requises pour la v3 (trot)
_REQUIRED_COLUMNS = {
    "courses":      ["statut_resultat"],
    "participants": ["score_repos", "score_partants", "score_hippodrome", "score_poids",
                     "position_arrivee", "score_corde", "score_regularite", "score_recence",
                     "score_global_expert", "score_global_auto", "score_gains", "score_age"],
}


async def _needs_migration(conn) -> bool:
    """Vérifie si la DB a besoin d'une migration (colonnes manquantes)."""
    from sqlalchemy import text

    def check_sync(sync_conn):
        for table, cols in _REQUIRED_COLUMNS.items():
            cursor = sync_conn.execute(
                text(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
            )
            row = cursor.fetchone()
            if not row:
                return True  # Table inexistante → migration
            ddl = row[0] or ""
            for col in cols:
                if col not in ddl:
                    return True
        # Vérifie que la contrainte UNIQUE existe sur participants
        cursor = sync_conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_participant_course_num'")
        )
        if cursor.fetchone() is None:
            return True
        # Vérifier que scoring_weights a la colonne discipline
        cursor = sync_conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='scoring_weights'")
        )
        row = cursor.fetchone()
        if row and "discipline" not in (row[0] or ""):
            return True
        # Vérifier que calibration_weights existe
        cursor = sync_conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='calibration_weights'")
        )
        if cursor.fetchone() is None:
            return True
        return False

    return await conn.run_sync(check_sync)


async def _cleanup_duplicates(conn) -> None:
    """Supprime les doublons de participants (même course_id + num_pmu), garde le plus petit id."""
    from sqlalchemy import text

    def do_cleanup(sync_conn):
        sync_conn.execute(text("""
            DELETE FROM participants
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM participants
                GROUP BY course_id, num_pmu
            )
        """))

    try:
        await conn.run_sync(do_cleanup)
    except Exception:
        pass  # Table inexistante lors du premier démarrage


async def init_db():
    from app import models  # noqa: F401
    async with engine.begin() as conn:
        if await _needs_migration(conn):
            # Supprimer et recréer toutes les tables (données dev uniquement)
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await _cleanup_duplicates(conn)
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
