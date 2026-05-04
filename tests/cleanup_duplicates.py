"""
Script de nettoyage des doublons de participants dans la base de données.
Supprime les entrées dupliquées (même course_id + num_pmu) en gardant la première.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


async def cleanup_duplicates():
    async with engine.begin() as conn:
        # Compter les doublons avant
        result = await conn.execute(text("""
            SELECT COUNT(*) as cnt FROM participants
            WHERE id NOT IN (
                SELECT MIN(id) FROM participants GROUP BY course_id, num_pmu
            )
        """))
        before = result.scalar()
        print(f"Doublons à supprimer: {before}")

        if before == 0:
            print("Aucun doublon, base propre.")
            return

        # Supprimer les doublons (garder l'ID minimum pour chaque (course_id, num_pmu))
        await conn.execute(text("""
            DELETE FROM participants
            WHERE id NOT IN (
                SELECT MIN(id) FROM participants GROUP BY course_id, num_pmu
            )
        """))

        # Vérifier après
        result2 = await conn.execute(text("SELECT COUNT(*) FROM participants"))
        after = result2.scalar()
        print(f"Participants restants après nettoyage: {after}")
        print("Nettoyage terminé avec succès.")


if __name__ == "__main__":
    asyncio.run(cleanup_duplicates())
