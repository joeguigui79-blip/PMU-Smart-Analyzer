import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Bet
from app.schemas import BetCreate, BetSchema
from app.service import trigger_arrivee_refresh

router = APIRouter(prefix="/api/bets", tags=["bets"])


def _bet_to_schema(bet: Bet) -> BetSchema:
    try:
        chevaux_raw = json.loads(bet.chevaux_json or "[]")
    except (json.JSONDecodeError, TypeError):
        chevaux_raw = []

    from app.schemas import BetCheval
    chevaux = []
    for c in chevaux_raw:
        try:
            chevaux.append(BetCheval(
                numero=int(c.get("numero", 0)),
                nom=str(c.get("nom", "")),
                cote=float(c["cote"]) if c.get("cote") is not None else None,
            ))
        except (ValueError, TypeError):
            pass

    return BetSchema(
        id=bet.id,
        created_at=bet.created_at,
        type_pari=bet.type_pari,
        montant=bet.montant,
        statut=bet.statut,
        gain_reel=bet.gain_reel,
        course_id=bet.course_id,
        course_label=bet.course_label,
        hippodrome=bet.hippodrome,
        chevaux=chevaux,
    )


@router.get("", response_model=list[BetSchema])
async def list_bets(statut: str | None = None, db: AsyncSession = Depends(get_db)):
    """Liste tous les paris, optionnellement filtrés par statut."""
    query = select(Bet).order_by(Bet.created_at.desc())
    if statut:
        query = query.where(Bet.statut == statut.upper())
    result = await db.execute(query)
    bets = result.scalars().all()
    return [_bet_to_schema(b) for b in bets]


@router.post("", response_model=BetSchema, status_code=201)
async def create_bet(payload: BetCreate, db: AsyncSession = Depends(get_db)):
    """Créer un nouveau pari."""
    # Validation type
    valid_types = {"GAGNANT", "PLACE", "COUPLE", "TIERCE", "DEUX_SUR_QUATRE"}
    if payload.type_pari.upper() not in valid_types:
        raise HTTPException(status_code=422, detail=f"type_pari invalide. Valeurs: {valid_types}")

    # Validation nombre de chevaux
    nb_requis = {
        "GAGNANT": 1, "PLACE": 1,
        "COUPLE": 2, "TIERCE": 3, "DEUX_SUR_QUATRE": 2,
    }
    requis = nb_requis[payload.type_pari.upper()]
    if len(payload.chevaux) != requis:
        raise HTTPException(
            status_code=422,
            detail=f"{payload.type_pari} nécessite exactement {requis} cheval(aux), reçu {len(payload.chevaux)}"
        )

    chevaux_json = json.dumps([
        {"numero": c.numero, "nom": c.nom, "cote": c.cote}
        for c in payload.chevaux
    ])

    bet = Bet(
        type_pari=payload.type_pari.upper(),
        montant=payload.montant,
        statut="EN_ATTENTE",
        course_id=payload.course_id,
        course_label=payload.course_label,
        hippodrome=payload.hippodrome,
        chevaux_json=chevaux_json,
    )
    db.add(bet)
    await db.commit()
    await db.refresh(bet)
    return _bet_to_schema(bet)


@router.delete("/{bet_id}", status_code=200)
async def delete_bet(bet_id: int, db: AsyncSession = Depends(get_db)):
    """Supprimer un pari."""
    result = await db.execute(select(Bet).where(Bet.id == bet_id))
    bet = result.scalar_one_or_none()
    if not bet:
        raise HTTPException(status_code=404, detail="Pari introuvable")
    await db.delete(bet)
    await db.commit()
    return {"success": True}


@router.post("/refresh-results", status_code=200)
async def refresh_results(db: AsyncSession = Depends(get_db)):
    """Déclenche la récupération des arrivées pour toutes les courses en cours."""
    updated = await trigger_arrivee_refresh(db)
    return {"success": True, "courses_updated": updated}
