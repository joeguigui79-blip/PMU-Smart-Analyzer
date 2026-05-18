"""
debug_tout_vs_disc.py — Analyse du sous-comptage 'Tout' vs somme disciplines.

Usage:
    python tests/debug_tout_vs_disc.py [DDMMYYYY]
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import Course, Reunion, Participant
from app.config import PARIS_TZ
from app.routers.bilan_router import (
    PARIS_ALIASES, PARIS_LABELS, _pari_in_disponibles, _is_discipline_match,
    _process_course_for_stats, _init_stats
)


DISCIPLINES_FRONT = ["PLAT", "TROT_MONTE", "TROT_ATTELE", "OBSTACLE", "HAIE", "STEEPLE", "CROSS"]


def today_ddmmyyyy():
    return datetime.now(PARIS_TZ).strftime("%d%m%Y")


async def run(date_str: str):
    print(f"\n{'='*80}")
    print(f"  DEBUG TOUT vs DISCIPLINES — {date_str}")
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
        print(f"[!] Aucune course TERMINE pour {date_str}")
        return

    print(f"Total courses TERMINE en DB: {len(courses)}\n")

    # Compter pour discipline='all' (comme le backend avec filtre 'Tout')
    count_all_ok = 0
    count_all_attente = 0
    disc_counts = {}  # disc -> {ok, attente}

    for c in courses:
        nb_part = len(c.participants)
        nb_pos = sum(1 for p in c.participants if p.position_arrivee is not None)
        disc = c.discipline or "INCONNU"

        is_ok = (nb_part > 0 and nb_pos >= 2)
        is_attente = (nb_part == 0 or nb_pos < 2)

        # Compteur global (all)
        if is_ok:
            count_all_ok += 1
        else:
            count_all_attente += 1

        # Compteur par discipline
        if disc not in disc_counts:
            disc_counts[disc] = {"ok": 0, "attente": 0}
        if is_ok:
            disc_counts[disc]["ok"] += 1
        else:
            disc_counts[disc]["attente"] += 1

    print(f"Filtre 'Tout'   → OK={count_all_ok}  en_attente={count_all_attente}")
    print()

    total_disc_ok = 0
    total_disc_attente = 0
    for disc in sorted(disc_counts.keys()):
        ok = disc_counts[disc]["ok"]
        attente = disc_counts[disc]["attente"]
        total_disc_ok += ok
        total_disc_attente += attente
        # Simuler si _is_discipline_match retourne True pour une des disciplines du front
        matched_by = [d for d in DISCIPLINES_FRONT if _is_discipline_match(disc, d)]
        print(f"  Discipline '{disc}': ok={ok} attente={attente}  [matchée par filtres front: {matched_by}]")

    print()
    print(f"Somme disciplines: OK={total_disc_ok}  attente={total_disc_attente}")
    print()

    # Chercher les courses OK dans 'Tout' mais absentes des buckets par discipline du FRONT
    print("=" * 60)
    print("COURSES OK ('Tout') mais HORS DISCIPLINES FRONT connues :")
    print("=" * 60)
    orphelines = []
    for c in courses:
        nb_part = len(c.participants)
        nb_pos = sum(1 for p in c.participants if p.position_arrivee is not None)
        if nb_part > 0 and nb_pos >= 2:
            disc = c.discipline or "INCONNU"
            matched_by = [d for d in DISCIPLINES_FRONT if _is_discipline_match(disc, d)]
            if not matched_by:
                orphelines.append(c)
                hipp = c.reunion.hippodrome_libelle if c.reunion else "?"
                print(f"  id={c.id}  {hipp} C{c.num_externe}  disc={disc}  part={nb_part}  pos={nb_pos}")

    if not orphelines:
        print("  Aucune — toutes les courses OK sont couvertes par un filtre discipline.")

    print()
    # Vérifier les courses OBSTACLE spécifiquement
    print("COURSES DE DISCIPLINE OBSTACLE/HAIE/STEEPLE/CROSS :")
    for c in courses:
        disc = c.discipline or "INCONNU"
        if disc in {"HAIE", "STEEPLE", "CROSS", "OBSTACLE"}:
            nb_part = len(c.participants)
            nb_pos = sum(1 for p in c.participants if p.position_arrivee is not None)
            hipp = c.reunion.hippodrome_libelle if c.reunion else "?"
            match_obstacle = _is_discipline_match(disc, "OBSTACLE")
            match_haie = _is_discipline_match(disc, "HAIE")
            print(f"  id={c.id}  {hipp} C{c.num_externe}  disc={disc}  part={nb_part}  pos={nb_pos}  "
                  f"match_OBSTACLE={match_obstacle}  match_HAIE={match_haie}")

    # Tester l'appel réel bilan avec periode=today et discipline=all vs disciplines
    print()
    print("=" * 60)
    print("SIMULATION BILAN BACKEND (même logique que /api/bilan):")
    print("=" * 60)

    def count_for_discipline(filter_disc):
        ok = 0
        attente = 0
        for c in courses:
            if not _is_discipline_match(c.discipline, filter_disc):
                continue
            nb_part = len(c.participants)
            nb_pos = sum(1 for p in c.participants if p.position_arrivee is not None)
            if nb_part == 0:
                attente += 1
            elif nb_pos < 2:
                attente += 1
            else:
                ok += 1
        return ok, attente

    for disc_filter in ["all", "PLAT", "TROT_MONTE", "TROT_ATTELE", "OBSTACLE", "HAIE"]:
        ok, att = count_for_discipline(disc_filter)
        print(f"  discipline='{disc_filter}': OK={ok}  en_attente={att}")

    plat_ok, _ = count_for_discipline("PLAT")
    monte_ok, _ = count_for_discipline("TROT_MONTE")
    attele_ok, _ = count_for_discipline("TROT_ATTELE")
    obstacle_ok, _ = count_for_discipline("OBSTACLE")
    haie_ok, _ = count_for_discipline("HAIE")
    somme = plat_ok + monte_ok + attele_ok + obstacle_ok + haie_ok
    all_ok2, _ = count_for_discipline("all")
    print(f"\n  Somme PLAT+MONTE+ATTELE+OBSTACLE+HAIE = {somme}")
    print(f"  'all' = {all_ok2}")
    if somme != all_ok2:
        print(f"  ECART = {all_ok2 - somme}  ← BUG ICI si négatif (all < somme) ou cours orphelines si positif")
    else:
        print(f"  OK: 'all' == somme des disciplines")


if __name__ == "__main__":
    target_date = sys.argv[1] if len(sys.argv) > 1 else today_ddmmyyyy()
    asyncio.run(run(target_date))
