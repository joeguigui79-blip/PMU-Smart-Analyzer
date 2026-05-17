"""
Admin router — endpoints d'administration réservés.
Protégé par le middleware auth existant (token JWT).
"""
import time
import logging
from fastapi import APIRouter
from pydantic import BaseModel

from app.database import AsyncSessionLocal
from app.service import backfill_participants_pour_courses_termine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class BackfillRequest(BaseModel):
    jours: int = 7


class BackfillResponse(BaseModel):
    courses_traitees: int
    succes: int
    echecs: int
    duree_sec: float


@router.post("/backfill-participants", response_model=BackfillResponse)
async def backfill_participants(payload: BackfillRequest = BackfillRequest()):
    """
    Lance le backfill des participants manquants pour les courses TERMINE
    des N derniers jours (participants_loaded=False).

    Exemple curl (avec token) :
        curl -X POST https://<votre-app>.onrender.com/api/admin/backfill-participants \\
             -H "Authorization: Bearer <token>" \\
             -H "Content-Type: application/json" \\
             -d '{"jours": 7}'
    """
    jours = max(1, min(payload.jours, 30))  # borne : 1-30 jours
    logger.info("[ADMIN] Backfill manuel déclenché — %d jour(s)", jours)
    t0 = time.monotonic()
    async with AsyncSessionLocal() as db:
        result = await backfill_participants_pour_courses_termine(db, jours=jours)
    duree = round(time.monotonic() - t0, 1)
    logger.info("[ADMIN] Backfill terminé en %.1fs", duree)
    return BackfillResponse(
        courses_traitees=result["courses_traitees"],
        succes=result["succes"],
        echecs=result["echecs"],
        duree_sec=duree,
    )
