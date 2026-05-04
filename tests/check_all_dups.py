"""Check all courses for duplicate participants."""
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine

async def check():
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT course_id, num_pmu, COUNT(*) as cnt
            FROM participants
            GROUP BY course_id, num_pmu
            HAVING COUNT(*) > 1
            LIMIT 20
        """))
        dups = result.fetchall()
        if dups:
            print(f"Found {len(dups)} duplicate entries!")
            for d in dups[:5]:
                print(f"  course_id={d[0]}, num_pmu={d[1]}, count={d[2]}")
            # Clean them
            await conn.execute(text("""
                DELETE FROM participants
                WHERE id NOT IN (
                    SELECT MIN(id) FROM participants GROUP BY course_id, num_pmu
                )
            """))
            print("Cleaned up.")
        else:
            print("No duplicates found - DB is clean.")
        
        total = (await conn.execute(text("SELECT COUNT(*) FROM participants"))).scalar()
        print(f"Total participants in DB: {total}")
        
        loaded = (await conn.execute(text("SELECT COUNT(*) FROM courses WHERE participants_loaded = 1"))).scalar()
        print(f"Courses with participants loaded: {loaded}")

asyncio.run(check())
