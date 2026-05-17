"""
debug_bilan.py — Diagnostic des courses TERMINE absentes du bilan.

Usage:
    python tests/debug_bilan.py [DDMMYYYY]

Sans argument : utilise la date du jour (Europe/Paris).
Affiche pour chaque course TERMINE du jour :
  - son statut vis-à-vis du bilan (évaluée / en_attente / raison exclusion)
  - ses paris_disponibles bruts + quels alias matchent
"""
import asyncio
import json
import sys
import os

# Ajouter la racine au PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import Course, Reunion, Participant
from app.config import PARIS_TZ
from app.routers.bilan_router import PARIS_ALIASES, PARIS_LABELS, _pari_in_disponibles


# ─── helpers ──────────────────────────────────────────────────────────────────

def today_ddmmyyyy() -> str:
    return datetime.now(PARIS_TZ).strftime("%d%m%Y")


def fmt_paris(paris_str: str) -> list[str]:
    if not paris_str:
        return []
    try:
        return json.loads(paris_str)
    except (json.JSONDecodeError, TypeError):
        return [p.strip() for p in paris_str.replace(",", " ").split() if p.strip()]


def matched_pari_keys(paris_str: str) -> list[str]:
    """Retourne les clés PARIS_LABELS qui matchent pour cette course."""
    return [k for k in PARIS_LABELS if _pari_in_disponibles(k, paris_str)]


# ─── diagnostic principal ──────────────────────────────────────────────────────

async def run(date_str: str) -> None:
    print(f"\n{'='*80}")
    print(f"  DIAGNOSTIC BILAN — {date_str}")
    print(f"{'='*80}\n")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Course)
            .join(Reunion)
            .options(selectinload(Course.participants), selectinload(Course.reunion))
            .where(
                Reunion.date_str == date_str,
                Course.statut_resultat == "TERMINE",
            )
            .order_by(Course.num_ordre)
        )
        courses = result.scalars().all()

    if not courses:
        print(f"[!] Aucune course TERMINE trouvée pour {date_str}")
        return

    evaluees = []
    en_attente = []

    print(f"{'ID':>6}  {'Hipp':20} {'Num':>4} {'Partants':>8} {'P.loaded':>8}  {'Raison':35}  Paris DB bruts")
    print("-" * 120)

    for c in courses:
        all_p = c.participants
        nb_part = len(all_p)
        nb_pos = sum(1 for p in all_p if p.position_arrivee is not None)
        hippodrome = c.reunion.hippodrome_libelle if c.reunion else "?"
        paris_raw = fmt_paris(c.paris_disponibles)
        matched = matched_pari_keys(c.paris_disponibles)

        # Détermination raison exclusion (même logique que bilan_router)
        if nb_part == 0:
            raison = "NO_PARTICIPANTS"
            bucket = en_attente
        elif nb_pos < 2:
            raison = f"ARRIVEE_MANQUANTE ({nb_part} part., {nb_pos} avec pos)"
            bucket = en_attente
        elif not matched:
            raison = "NO_PARIS_ALIAS_MATCH"
            bucket = en_attente
        else:
            raison = f"OK ({len(matched)} types paris matchés)"
            bucket = evaluees

        row = (
            f"{c.id:>6}  {hippodrome:20} {c.num_externe:>4} "
            f"{c.nombre_partants:>8} {str(c.participants_loaded):>8}  "
            f"{raison:35}  {paris_raw}"
        )
        print(row)
        bucket.append(c)

    print(f"\n{'─'*80}")
    print(f"  RESUME : {len(courses)} TERMINE  →  {len(evaluees)} évaluées  /  {len(en_attente)} en attente/exclues")
    print(f"{'─'*80}\n")

    if en_attente:
        print("DETAIL DES COURSES EN ATTENTE / EXCLUES :")
        print()
        for c in en_attente:
            all_p = c.participants
            nb_part = len(all_p)
            nb_pos = sum(1 for p in all_p if p.position_arrivee is not None)
            paris_raw = fmt_paris(c.paris_disponibles)
            matched = matched_pari_keys(c.paris_disponibles)
            hippodrome = c.reunion.hippodrome_libelle if c.reunion else "?"

            print(f"  Course id={c.id}  {hippodrome} C{c.num_externe}  disc={c.discipline}  nb_partants={c.nombre_partants}")
            print(f"    participants_loaded = {c.participants_loaded}")
            print(f"    nb_participants_db  = {nb_part}")
            print(f"    nb_avec_position    = {nb_pos}")
            print(f"    paris_disponibles   = {paris_raw}")
            print(f"    paris_alias_matchés = {matched}")

            # Analyse fine : quels paris_disponibles ne matchent rien ?
            unmatched_paris = []
            all_aliases_flat = set()
            for aliases in PARIS_ALIASES.values():
                all_aliases_flat.update(a.upper() for a in aliases)
            for p in paris_raw:
                if p.upper() not in all_aliases_flat:
                    unmatched_paris.append(p)
            if unmatched_paris:
                print(f"    [!] Types paris DB sans alias connu: {unmatched_paris}")
            print()

    # Statistiques paris_disponibles inconnus (tous types confondus)
    unknown_types: dict[str, int] = {}
    all_aliases_flat = set()
    for aliases in PARIS_ALIASES.values():
        all_aliases_flat.update(a.upper() for a in aliases)
    for c in courses:
        for p in fmt_paris(c.paris_disponibles):
            if p.upper() not in all_aliases_flat:
                unknown_types[p] = unknown_types.get(p, 0) + 1

    if unknown_types:
        print("TYPES DE PARIS DB INCONNUS (sans alias dans PARIS_ALIASES) :")
        for ptype, cnt in sorted(unknown_types.items(), key=lambda x: -x[1]):
            print(f"  {ptype:45} apparaît dans {cnt} course(s)")
        print()
    else:
        print("Tous les types de paris DB ont un alias connu dans PARIS_ALIASES.\n")


if __name__ == "__main__":
    target_date = sys.argv[1] if len(sys.argv) > 1 else today_ddmmyyyy()
    asyncio.run(run(target_date))
