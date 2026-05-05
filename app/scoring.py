"""
Moteur de scoring des chevaux PMU — v4 avec scoring corrigé par discipline.

Score global (0-100) = somme pondérée de critères selon la discipline :

PLAT (défaut) :
  - forme_recente (28%) : analyse de la musique (historique performances)
  - value_cote   (20%) : probabilité de victoire basée sur la cote (1/cote * 100)
  - jockey       (10%) : qualité du jockey basée sur la forme de ses chevaux
  - entraineur    (8%) : score entraîneur
  - distance      (7%) : adéquation distance de la course
  - terrain       (6%) : adéquation terrain / pénétromètre
  - repos         (5%) : jours depuis la dernière course (repos optimal ~14-28j)
  - gains         (7%) : gains carrière normalisés dans le champ
  - age           (4%) : âge optimal selon discipline
  - partants      (3%) : moins de partants = course plus accessible
  - hippodrome    (2%) : performance historique sur cet hippodrome

TROT ATTELE / MONTE — critères spécifiques :
  - forme_recente (24%) : performances récentes dans la MÊME discipline
  - value_cote   (17%) : probabilité de victoire
  - corde        (14%) : avantage du numéro bas (corde) en départ à l'élastique
  - regularite   (11%) : fiabilité (absence de disqualifications)
  - gains         (8%) : gains carrière (très révélateurs en trot)
  - recence       (7%) : préparation récente (< 20 jours)
  - entraineur    (6%) : driver/entraîneur
  - distance      (5%) : adéquation distance
  - age           (4%) : âge optimal
  - partants      (4%) : nombre de partants

OBSTACLE (HAIE / STEEPLE / CROSS) :
  - forme_recente (30%) : forme récente (sauts)
  - value_cote   (18%) : probabilité de victoire
  - jockey        (14%) : jockey obstacle très important
  - terrain       (12%) : terrain crucial en obstacle
  - entraineur    (8%) : entraîneur obstacle
  - distance      (7%) : adéquation distance
  - gains         (5%) : gains carrière
  - age           (3%) : âge optimal
  - partants      (3%) : nombre partants
"""

import re
import logging
from app.config import SCORING_WEIGHTS, SCORING_WEIGHTS_DISCIPLINE, VALUE_BET_FACTOR, VALUE_BET_MIN_SCORE

logger = logging.getLogger(__name__)

# Correspondance caractère musique → score de position (1er = 100, 2e = 80, ...)
POSITION_SCORES = {
    "1": 100, "2": 80, "3": 65, "4": 52, "5": 42,
    "6": 35, "7": 28, "8": 22, "9": 16,
    "0": 10,  # 10e ou au-delà
    "D": 5,   # Disqualifié (en trot : allure défectueuse)
    "T": 5,   # Tombé / trot déclassé
    "A": 0,   # Arrêté / Abandonné
    "R": 0,   # Refusé
    "N": 0,   # Non partant
    "p": 30,  # Placé (générique)
}

# Scores de position pour musique TROT : les 'D' sont moins pénalisants car fréquents
POSITION_SCORES_TROT = {
    "1": 100, "2": 80, "3": 65, "4": 52, "5": 42,
    "6": 35, "7": 28, "8": 22, "9": 16,
    "0": 10,
    "D": 15,  # Disqualifié trot : plus fréquent, moins pénalisant
    "T": 10,  # Tombé / déclassé trot
    "A": 5,   # Arrêté
    "R": 0,   # Refusé
    "N": 0,   # Non partant
    "p": 30,
}

TERRAIN_LABELS = {
    "LEGER": 1, "BON": 2, "BON_A_SOUPLE": 3, "SOUPLE": 4,
    "ASSEZ_SOUPLE": 5, "TRES_SOUPLE": 6, "LOURD": 7,
    "TRES_LOURD": 8, "COLLANT": 9,
}

# Disciplines de trot
TROT_DISCIPLINES = {"ATTELE", "TROT_ATTELE", "MONTE", "TROT_MONTE", "TROT"}
# Disciplines obstacle
OBSTACLE_DISCIPLINES = {"HAIE", "HAIES", "STEEPLE", "STEEPLECHASE", "CROSS", "OBSTACLE"}


def _normalize_discipline(discipline: str) -> str:
    """Normalise le nom de la discipline vers une clé standard."""
    d = (discipline or "").upper().strip()
    if d in ("ATTELE", "TROT_ATTELE"):
        return "TROT_ATTELE"
    if d in ("MONTE", "TROT_MONTE"):
        return "TROT_MONTE"
    if d in ("HAIE", "HAIES"):
        return "HAIE"
    if d in ("STEEPLE", "STEEPLECHASE"):
        return "STEEPLE"
    if d in ("CROSS",):
        return "CROSS"
    if d in ("OBSTACLE",):
        return "HAIE"
    return "PLAT"


def _is_trot(discipline: str) -> bool:
    d = (discipline or "").upper()
    return d in TROT_DISCIPLINES or "TROT" in d or d in ("ATTELE", "MONTE")


def _is_obstacle(discipline: str) -> bool:
    d = (discipline or "").upper()
    return d in OBSTACLE_DISCIPLINES or "HAIE" in d or "STEEPLE" in d or "CROSS" in d or "OBSTACLE" in d


def _parse_musique(musique: str, is_trot: bool = False) -> list[int]:
    """
    Parse la chaîne musique PMU et retourne une liste de scores (le plus récent en premier).
    Ex: "1a3a2p" → [100, 65, 80]  (ignore les suffixes de discipline a/m/p)

    Suffixes dans la musique :
      'a' = attelé, 'm' = monté, 'p' = plat, 's' = steeple/obstacle
    Les groupes entre parenthèses comme (25) indiquent l'année de la saison.
    """
    scores = []
    pos_map = POSITION_SCORES_TROT if is_trot else POSITION_SCORES
    i = 0
    while i < len(musique):
        char = musique[i]

        # Ignorer les années entre parenthèses : (25), (24), etc.
        if char == "(":
            while i < len(musique) and musique[i] != ")":
                i += 1
            i += 1
            continue

        if char.isdigit():
            num = char
            if i + 1 < len(musique) and musique[i + 1].isdigit():
                num = char + musique[i + 1]
                i += 1
            pos = min(int(num), 9)
            pos_str = str(pos) if pos < 10 else "0"
            score = pos_map.get(pos_str, 10)
            scores.append(score)
            # Ignorer le suffixe de discipline qui suit (a, m, p, s)
            if i + 1 < len(musique) and musique[i + 1].lower() in ("a", "m", "p", "s"):
                i += 1
        elif char.upper() in pos_map:
            scores.append(pos_map[char.upper()])
            # Ignorer éventuellement un suffixe de discipline (Da, Dm, Dp)
            if i + 1 < len(musique) and musique[i + 1].lower() in ("a", "m", "p", "s"):
                i += 1
        i += 1
    return scores


def _parse_musique_discipline_filter(musique: str, target_suffix: str) -> list[int]:
    """
    Parse la musique en ne prenant en compte QUE les courses de la discipline cible.
    target_suffix : 'a' pour attelé, 'm' pour monté, 'p' pour plat, None pour tout
    Utile pour scorer la forme dans la même discipline.
    """
    if not target_suffix:
        return _parse_musique(musique, is_trot=True)

    scores = []
    i = 0
    while i < len(musique):
        char = musique[i]

        if char == "(":
            while i < len(musique) and musique[i] != ")":
                i += 1
            i += 1
            continue

        if char.isdigit():
            num = char
            if i + 1 < len(musique) and musique[i + 1].isdigit():
                num = char + musique[i + 1]
                i += 1
            # Vérifier si la prochaine lettre est le suffix cible
            suffix = musique[i + 1].lower() if (i + 1 < len(musique) and musique[i + 1].isalpha()) else ""
            if suffix == target_suffix:
                pos = min(int(num), 9)
                pos_str = str(pos) if pos < 10 else "0"
                scores.append(POSITION_SCORES_TROT.get(pos_str, 10))
                i += 1  # skip suffix
        elif char.upper() in POSITION_SCORES_TROT:
            suffix = musique[i + 1].lower() if (i + 1 < len(musique) and musique[i + 1].isalpha()) else ""
            if suffix == target_suffix:
                scores.append(POSITION_SCORES_TROT[char.upper()])
                i += 1
        i += 1
    return scores


def _count_disqualifications(musique: str) -> int:
    """Compte le nombre de D (disqualifications/allure défectueuse) dans la musique."""
    return sum(1 for c in musique if c.upper() == "D")


def _count_arrets(musique: str) -> int:
    """Compte les abandons (A), refus (R), non-partants (N), tombés (T)."""
    return sum(1 for c in musique if c.upper() in ("A", "R", "N", "T"))


def score_forme_recente(musique: str, discipline: str = "PLAT") -> float:
    """Score forme (0-100) basé sur les 5 dernières courses pondérées.

    Pour les disciplines trot, utilise le score_trot (moins pénalisant sur D)
    et privilégie les courses dans la même discipline.
    """
    if not musique:
        return 40.0

    is_trot = _is_trot(discipline)

    if is_trot:
        # Essayer d'abord les courses dans la même discipline
        suffix = "a" if "ATTELE" in discipline.upper() or discipline.upper() == "ATTELE" else "m"
        discipline_scores = _parse_musique_discipline_filter(musique, suffix)
        all_scores = _parse_musique(musique, is_trot=True)

        if len(discipline_scores) >= 3:
            # Assez de courses dans la même discipline
            recent = discipline_scores[:5]
        elif discipline_scores:
            # Mélanger : priorité aux courses de même discipline
            recent = (discipline_scores + all_scores)[:5]
        else:
            recent = all_scores[:5]
    else:
        recent = _parse_musique(musique, is_trot=False)[:5]

    if not recent:
        return 40.0

    weights = [5, 4, 3, 2, 1]
    weighted_sum = sum(s * w for s, w in zip(recent, weights))
    weight_total = sum(weights[:len(recent)])
    return round(weighted_sum / weight_total, 2)


def score_cote(cote: float | None, scores_tous: list[float] = None) -> float:
    """
    Score cote (0-100) basé sur la PROBABILITÉ DE VICTOIRE.
    Formule : (1 / cote) * 100, plafonnée à 85.
    - Cote 1.5 → prob 66% → score 66
    - Cote 3.0 → prob 33% → score 33
    - Cote 10.0 → prob 10% → score 10
    Le favori (cote basse) a donc le score le plus élevé, conformément aux statistiques réelles.
    """
    if cote is None or cote <= 0:
        return 50.0  # Neutre si pas de cote disponible
    if cote < 1.01:
        return 85.0  # Très gros favori
    prob = (1.0 / cote) * 100.0
    return round(min(prob, 85.0), 2)


def score_jockey(
    jockey: str,
    all_jockeys: list[str],
    participants: list[dict] | None = None,
    current_horse_musique: str = "",
    discipline: str = "PLAT",
) -> float:
    """
    Score jockey (0-100) basé sur la qualité réelle du jockey/driver.

    Stratégie :
    1. Analyser la forme moyenne des AUTRES chevaux montés par ce jockey dans la course.
       Un jockey qui a plusieurs chevaux en bonne forme = bon jockey → bonus.
    2. Si le jockey n'a qu'un seul cheval (cas normal), score neutre enrichi.
    3. En trot attelé, un driver avec plusieurs chevaux en bonne forme = indicateur fort.
    """
    if not jockey:
        return 40.0

    if not participants:
        return 50.0

    is_trot = _is_trot(discipline)

    # Méthode 1 : forme des autres chevaux du même jockey (existant)
    other_formes = []
    for p in participants:
        p_jockey = p.get("jockey", "")
        p_musique = p.get("musique", "") or ""
        if p_jockey == jockey and p_musique != current_horse_musique:
            forme = score_forme_recente(p_musique, discipline)
            other_formes.append(forme)

    # Méthode 2 : fréquence du jockey dans la course (jockey populaire = demandé)
    nb_montes = sum(1 for j in all_jockeys if j == jockey)

    # Score de base
    base = 50.0

    if other_formes:
        avg_forme = sum(other_formes) / len(other_formes)
        if avg_forme >= 70:
            base = 72.0
        elif avg_forme >= 60:
            base = 63.0
        elif avg_forme >= 50:
            base = 55.0
        elif avg_forme >= 40:
            base = 45.0
        else:
            base = 38.0
        if is_trot and len(other_formes) >= 2:
            base = min(base + 5.0, 80.0)
    elif nb_montes >= 2:
        # Jockey avec plusieurs chevaux mais pas assez d'info forme
        base = 58.0

    # Jockey unique sans autres données : score neutre
    if nb_montes == 1 and not other_formes:
        base = 50.0

    return round(base, 2)


def score_entraineur(entraineur: str, all_entraineurs: list[str]) -> float:
    """Score entraîneur / driver similaire au jockey."""
    if not entraineur:
        return 40.0
    count = sum(1 for e in all_entraineurs if e == entraineur)
    if count == 1:
        return 55.0
    elif count == 2:
        return 50.0
    else:
        return 42.0


def score_distance(musique: str, distance_course: int, discipline: str = "PLAT") -> float:
    """
    Score distance (0-100) basé sur les performances passées du cheval.

    Classe les distances en catégories et évalue l'adéquation selon les résultats
    enregistrés dans la musique (victoires et places).
    """
    if not musique or distance_course <= 0:
        return 50.0

    is_trot = _is_trot(discipline)

    # Catégoriser la distance de la course
    if is_trot:
        # En trot : courte < 2100m, moyenne 2100-2700m, longue > 2700m
        if distance_course < 2100:
            cat_course = "court"
        elif distance_course <= 2700:
            cat_course = "moyen"
        else:
            cat_course = "long"
    else:
        # Plat/obstacle
        if distance_course < 1400:
            cat_course = "sprint"
        elif distance_course < 1800:
            cat_course = "mile"
        elif distance_course < 2200:
            cat_course = "intermediaire"
        elif distance_course < 2800:
            cat_course = "classique"
        else:
            cat_course = "long"

    # Analyser la musique : compter victoires et places
    scores = _parse_musique(musique, is_trot=is_trot)
    if not scores:
        return 50.0

    nb_courses = len(scores)
    nb_top3 = sum(1 for s in scores if s >= 65)  # score >= 65 = place 1-3
    nb_victoires = sum(1 for s in scores if s >= 100)

    # Score de base selon le taux de réussite global
    if nb_courses >= 3:
        taux_top3 = nb_top3 / nb_courses
        if taux_top3 >= 0.5:
            base = 75.0
        elif taux_top3 >= 0.3:
            base = 62.0
        elif taux_top3 >= 0.15:
            base = 50.0
        else:
            base = 38.0
    else:
        base = 50.0

    # Ajustement selon la catégorie de distance (heuristique)
    if cat_course in ("sprint", "court"):
        # Sprint/court : vitesse pure. Un cheval avec des victoires est probablement adapté
        if nb_victoires >= 2:
            base = min(base + 8.0, 85.0)
    elif cat_course in ("long", "classique"):
        # Long : endurance. Pénaliser si le cheval n'a jamais bien fini
        if nb_top3 == 0 and nb_courses >= 4:
            base = max(base - 10.0, 30.0)
        elif nb_victoires >= 1:
            base = min(base + 5.0, 80.0)
    # Mile/intermédiaire/moyen : distances standard, pas d'ajustement spécial

    return round(base, 2)


def score_terrain(musique: str, terrain_course: str, penetrometre: float | None, discipline: str = "PLAT") -> float:
    """
    Score terrain (0-100) heuristique amélioré avec pénétromètre intelligent.

    Logique :
    - Terrain lourd (pénétromètre >= 4.5) : très discriminant, seuls les endurants s'en sortent
    - Terrain souple (>= 3.5) : légèrement discriminant
    - Terrain léger (< 2.0) : avantage aux chevaux rapides (bonne forme récente)
    - Terrain bon (2.0-3.5) : neutre, léger avantage si bonne forme
    """
    if not musique:
        return 50.0

    forme = score_forme_recente(musique, discipline)
    is_obstacle = _is_obstacle(discipline)

    # Classifier le terrain
    if penetrometre is not None:
        if penetrometre >= 4.5:
            terrain_cat = "lourd"
        elif penetrometre >= 3.5:
            terrain_cat = "souple"
        elif penetrometre >= 2.0:
            terrain_cat = "bon"
        else:
            terrain_cat = "leger"
    else:
        terrain_cat = "bon"  # défaut neutre

    # Score basé sur la combinaison forme + terrain
    if terrain_cat == "lourd":
        # Terrain lourd : très discriminant
        if forme >= 70:
            base = 68.0
        elif forme >= 55:
            base = 50.0
        elif forme >= 40:
            base = 35.0
        else:
            base = 22.0
        # En obstacle, terrain lourd encore plus impactant
        if is_obstacle:
            if forme >= 65:
                base = min(base + 8.0, 80.0)
            else:
                base = max(base - 8.0, 18.0)
    elif terrain_cat == "souple":
        # Terrain souple : légèrement discriminant
        if forme >= 65:
            base = 60.0
        elif forme >= 50:
            base = 50.0
        else:
            base = 38.0
    elif terrain_cat == "leger":
        # Terrain léger/rapide : avantage aux chevaux rapides
        if forme >= 70:
            base = 70.0
        elif forme >= 55:
            base = 58.0
        else:
            base = 42.0
    else:
        # Bon terrain : neutre, léger avantage si bonne forme
        if forme >= 65:
            base = 58.0
        elif forme >= 50:
            base = 52.0
        else:
            base = 44.0

    return round(base, 2)


def score_repos(musique: str, jours_depuis_sortie: int | None = None, discipline: str = "PLAT") -> float:
    """
    Score repos (0-100).

    Priorité : utiliser jours_depuis_sortie si disponible dans l'API.
    Sinon, heuristique basée sur la densité de la musique de saison.

    Repos optimal selon discipline :
    - Plat : 14-28 jours
    - Obstacle : 21-35 jours
    - Trot : 14-21 jours
    """
    is_trot = _is_trot(discipline)
    is_obstacle = _is_obstacle(discipline)

    if jours_depuis_sortie is not None and jours_depuis_sortie > 0:
        # Utiliser le vrai nombre de jours
        if is_trot:
            # Repos optimal trot : 14-21 jours
            if 14 <= jours_depuis_sortie <= 21:
                return 80.0
            elif 10 <= jours_depuis_sortie <= 28:
                return 65.0
            elif jours_depuis_sortie < 10:
                return 45.0  # Trop frais
            elif jours_depuis_sortie <= 45:
                return 55.0  # Un peu long
            else:
                return 35.0  # Long repos = désavantage probable
        elif is_obstacle:
            # Repos optimal obstacle : 21-35 jours
            if 21 <= jours_depuis_sortie <= 35:
                return 80.0
            elif 14 <= jours_depuis_sortie <= 45:
                return 65.0
            elif jours_depuis_sortie < 14:
                return 40.0
            elif jours_depuis_sortie <= 60:
                return 55.0
            else:
                return 35.0
        else:
            # Repos optimal plat : 14-28 jours
            if 14 <= jours_depuis_sortie <= 28:
                return 80.0
            elif 7 <= jours_depuis_sortie <= 35:
                return 65.0
            elif jours_depuis_sortie < 7:
                return 40.0  # Trop frais
            elif jours_depuis_sortie <= 60:
                return 50.0
            else:
                return 35.0  # Long repos

    # Fallback : heuristique sur la densité de la musique
    if not musique:
        return 50.0

    # Extraire la saison en cours (avant le premier "(")
    saison_actuelle = musique.split("(")[0] if "(" in musique else musique
    nb_recent = len(_parse_musique(saison_actuelle, is_trot=is_trot))

    # Compter les pauses (N, A, R) dans la saison actuelle
    pauses = sum(1 for c in saison_actuelle if c.upper() in ("A", "R", "N"))

    if pauses > 0 and len(saison_actuelle) > 0:
        pause_rate = pauses / max(len(saison_actuelle), 1)
        if pause_rate > 0.3:
            return 30.0  # Beaucoup de non-partants = irrégulier

    # Densité de courses récentes comme proxy du repos
    if nb_recent == 0:
        return 60.0  # Cheval de début de saison → repos frais
    elif nb_recent <= 2:
        return 70.0  # Peu de courses récentes → repos probable
    elif nb_recent <= 4:
        return 62.0  # Activité modérée
    elif nb_recent <= 7:
        return 52.0  # Très actif → moins de repos
    else:
        return 42.0  # Suractivité → fatigue possible


def score_partants(nombre_partants: int) -> float:
    """Score partants (0-100) : moins de concurrents = course plus accessible."""
    if nombre_partants <= 0:
        return 50.0
    if nombre_partants <= 6:
        return 80.0
    elif nombre_partants <= 9:
        return 65.0
    elif nombre_partants <= 12:
        return 55.0
    elif nombre_partants <= 15:
        return 45.0
    else:
        return 35.0


def score_hippodrome(nom_cheval: str, hippodrome: str, historique_hippodromes: dict) -> float:
    """
    Score hippodrome (0-100) basé sur l'historique du cheval sur cet hippodrome.
    """
    if not nom_cheval or not hippodrome:
        return 50.0
    cheval_data = historique_hippodromes.get(nom_cheval, {})
    hipp_data = cheval_data.get(hippodrome, {})
    nb = hipp_data.get("nb_courses", 0)
    top3 = hipp_data.get("nb_top3", 0)
    if nb == 0:
        return 50.0
    taux = top3 / nb
    if taux >= 0.5:
        return 80.0
    elif taux >= 0.3:
        return 65.0
    elif taux >= 0.15:
        return 55.0
    else:
        return 38.0


def score_poids(poids: float | None) -> float:
    """Score poids jockey (0-100). Poids léger = avantage."""
    if poids is None:
        return 50.0
    if poids < 52:
        return 72.0
    elif poids < 56:
        return 65.0
    elif poids < 60:
        return 55.0
    elif poids < 64:
        return 45.0
    else:
        return 35.0


def score_gains(gains_carriere: int | float, all_gains: list[int | float]) -> float:
    """
    Score gains (0-100) basé sur les gains carrière normalisés dans le champ.

    Les gains cumulés sont un excellent indicateur du niveau du cheval.
    Formule : rang en gains / nb_partants * 100 (inversé : plus de gains = meilleur rang)

    Si le cheval a 0 gains et qu'il y en a d'autres, c'est un débutant → score bas.
    """
    valid_gains = [g for g in all_gains if g is not None and g >= 0]
    if not valid_gains or gains_carriere is None:
        return 50.0

    nb = len(valid_gains)
    if nb == 1:
        return 50.0  # Un seul cheval, pas de comparaison possible

    # Trier les gains (ordre décroissant = meilleur rang = indice bas)
    sorted_gains = sorted(valid_gains, reverse=True)

    # Trouver le rang du cheval courant (1-based, 1 = meilleur)
    rang = 1
    for i, g in enumerate(sorted_gains):
        if g <= gains_carriere:
            rang = i + 1
            break

    # Normaliser : rang 1 = score élevé, rang nb = score bas
    # Score = (nb - rang + 1) / nb * 80 + 10 → range [10, 90]
    score = ((nb - rang + 1) / nb) * 75.0 + 15.0
    return round(min(score, 85.0), 2)


def score_age(age: int | None, discipline: str = "PLAT") -> float:
    """
    Score âge (0-100) selon la discipline.

    Les chevaux de 4-6 ans sont généralement à leur peak.
    Les jeunes (3 ans) sont prometteurs mais imprévisibles.
    Les vieux (8+) déclinent.

    Plat  : 3=65, 4-5=75, 6-7=60, 8+=45
    Trot  : 4-6=75, 7-8=65, 9+=50, 3=55
    Obst. : 5-7=75, 8-9=65, 4=60, 10+=45
    """
    if age is None or age <= 0:
        return 50.0  # Âge inconnu → neutre

    is_trot = _is_trot(discipline)
    is_obstacle = _is_obstacle(discipline)

    if is_trot:
        if age == 3:
            return 55.0
        elif 4 <= age <= 6:
            return 75.0
        elif 7 <= age <= 8:
            return 65.0
        else:  # 9+
            return 50.0
    elif is_obstacle:
        if age == 4:
            return 60.0
        elif 5 <= age <= 7:
            return 75.0
        elif 8 <= age <= 9:
            return 65.0
        else:  # 10+
            return 45.0
    else:
        # Plat
        if age == 3:
            return 65.0
        elif 4 <= age <= 5:
            return 75.0
        elif 6 <= age <= 7:
            return 60.0
        else:  # 8+
            return 45.0


# ============================================================
# NOUVEAUX CRITÈRES SPÉCIFIQUES AU TROT
# ============================================================

def score_corde(num_pmu: int, nombre_partants: int = 10) -> float:
    """
    Score corde (0-100) pour le trot attelé.
    En départ à l'élastique, les numéros bas (intérieur) ont un avantage.
    - N°1-3 : très bon avantage (80-90)
    - N°4-7 : avantage moyen (60-70)
    - N°8-11 : neutre à léger désavantage (45-55)
    - N°12+ : net désavantage (25-40)
    """
    if num_pmu is None or num_pmu <= 0:
        return 50.0
    if num_pmu <= 3:
        return 85.0
    elif num_pmu <= 7:
        return 65.0
    elif num_pmu <= 11:
        return 48.0
    else:
        return 28.0


def score_regularite_trot(musique: str) -> float:
    """
    Score régularité (0-100) pour le trot.
    Un trotteur qui ne se fait pas disqualifier est plus fiable.
    - Pas de D : excellent (75-85)
    - 1 D sur 10+ courses : acceptable (60)
    - 2+ D : moins fiable (35-50)
    - D récents (dans les 3 dernières) : très pénalisant
    """
    if not musique:
        return 50.0

    all_scores = _parse_musique(musique, is_trot=True)
    if not all_scores:
        return 50.0

    # Compter les D dans toute la musique
    nb_disq = _count_disqualifications(musique)
    nb_courses = len(all_scores)

    # Vérifier si les 3 dernières courses ont un D
    recent_musique = musique[:6]  # approximation des 3 dernières (2 chars par course)
    recent_disq = _count_disqualifications(recent_musique)

    if recent_disq >= 2:
        # D récents fréquents = cheval instable
        return 20.0
    elif recent_disq == 1:
        # 1 D récent = prudence
        return 38.0
    elif nb_disq == 0:
        # Aucune disqualification = très régulier
        if nb_courses >= 6:
            return 85.0
        else:
            return 70.0
    elif nb_disq == 1:
        return 62.0
    elif nb_disq == 2:
        return 48.0
    else:
        # Beaucoup de D = cheval irrégulier
        rate = nb_disq / max(nb_courses, 1)
        return max(20.0, 42.0 - rate * 30)


def score_recence_trot(musique: str) -> float:
    """
    Score récence (0-100) pour le trot.
    Heuristique : longueur de musique + densité de courses récentes.
    Un cheval qui court régulièrement est mieux en condition.
    Différent du score_repos du plat : en trot, la régularité dans la saison compte.
    """
    if not musique:
        return 50.0

    # En trot, la musique contient des (25), (24) pour les années
    # Compter les courses de la saison actuelle (avant le premier "(")
    saison_actuelle = musique.split("(")[0] if "(" in musique else musique
    # Approximer le nombre de courses de la saison actuelle
    nb_recent = len(_parse_musique(saison_actuelle, is_trot=True))

    # Un cheval avec 3-6 courses récentes est bien en condition
    if nb_recent == 0:
        return 40.0  # Débutant de saison
    elif nb_recent <= 2:
        return 55.0  # Peu de courses récentes
    elif nb_recent <= 5:
        return 70.0  # Bien en condition
    elif nb_recent <= 8:
        return 65.0  # Très actif
    else:
        return 55.0  # Peut-être surmené


# ============================================================
# POIDS PAR DISCIPLINE
# ============================================================

def get_weights_for_discipline(discipline: str, db_weights_by_disc: dict | None = None) -> dict:
    """
    Retourne les poids appropriés pour la discipline donnée.
    Priorité : poids DB spécifiques à la discipline > config par défaut.
    """
    norm_disc = _normalize_discipline(discipline)

    # Vérifier les poids en DB pour cette discipline
    if db_weights_by_disc and norm_disc in db_weights_by_disc:
        disc_weights = db_weights_by_disc[norm_disc]
        if disc_weights:
            # Normaliser pour que la somme = 1.0
            total = sum(disc_weights.values())
            if total > 0:
                return {k: v / total for k, v in disc_weights.items()}

    # Poids par défaut selon la discipline
    from app.config import SCORING_WEIGHTS_DISCIPLINE
    if norm_disc in SCORING_WEIGHTS_DISCIPLINE:
        return SCORING_WEIGHTS_DISCIPLINE[norm_disc].copy()

    return SCORING_WEIGHTS_DISCIPLINE.get("PLAT", {}).copy()


def is_value_bet(cote: float | None, score_global: float) -> bool:
    """
    Détecte si un cheval est un value bet.
    La détection value bet est séparée du score_cote et n'influence pas le score global.
    Un value bet est un cheval dont le score estimé dépasse ce que la cote suggère.
    """
    if cote is None or cote <= 1.0 or score_global < VALUE_BET_MIN_SCORE:
        return False
    prob_implicite = 1.0 / cote
    prob_estimee = score_global / 100.0
    return prob_estimee >= prob_implicite * VALUE_BET_FACTOR


def get_confiance(score: float) -> str:
    if score >= 70:
        return "HIGH"
    elif score >= 50:
        return "MEDIUM"
    else:
        return "LOW"


def generer_explication(
    nom: str,
    score_global: float,
    score_forme: float,
    score_cote_val: float,
    cote: float | None,
    musique: str,
    is_vb: bool,
    confiance: str,
    discipline: str = "PLAT",
    score_corde: float | None = None,
    score_regularite: float | None = None,
    age: int | None = None,
    gains_carriere: int | None = None,
) -> str:
    parts = []
    is_trot = _is_trot(discipline)

    if score_forme >= 70:
        parts.append("excellente forme récente")
    elif score_forme >= 55:
        parts.append("bonne forme récente")
    elif score_forme < 35:
        parts.append("forme décevante récemment")

    if cote and cote < 2.5:
        parts.append(f"grand favori ({cote:.1f})")
    elif cote and cote < 5.0 and score_cote_val >= 25:
        parts.append(f"favori ({cote:.1f})")
    elif cote and cote >= 10.0:
        parts.append(f"outsider ({cote:.1f})")

    if is_vb:
        parts.append("value bet détecté")

    if musique and len(musique) > 0:
        wins = sum(1 for c in musique if c == "1")
        if wins >= 2:
            parts.append(f"{wins} victoires récentes")

    if age and age > 0:
        if age <= 3:
            parts.append(f"jeune ({age} ans)")
        elif age >= 9:
            parts.append(f"vétéran ({age} ans)")

    # Critères spécifiques trot
    if is_trot:
        if score_corde is not None and score_corde >= 80:
            parts.append("avantage corde (numéro bas)")
        elif score_corde is not None and score_corde <= 30:
            parts.append("désavantage numéro extérieur")
        if score_regularite is not None and score_regularite >= 75:
            parts.append("très régulier (sans disqualification)")
        elif score_regularite is not None and score_regularite <= 25:
            parts.append("irrégulier (disqualifications récentes)")

    if not parts:
        parts.append("profil standard")

    disc_label = ""
    if is_trot:
        disc_label = " [Trot]"
    elif _is_obstacle(discipline):
        disc_label = " [Obstacle]"

    return f"{nom}{disc_label} : {', '.join(parts)}. Confiance {confiance}."


def load_weights_from_config_or_db(db_weights: dict | None = None) -> dict:
    """
    Retourne les poids à utiliser (discipline = PLAT par défaut) : DB en priorité, sinon config.
    db_weights : {critere: poids} depuis la table scoring_weights, ou None.
    """
    if db_weights:
        required = set(SCORING_WEIGHTS.keys())
        if required.issubset(set(db_weights.keys())):
            total = sum(db_weights[k] for k in required)
            if total > 0:
                return {k: db_weights[k] / total for k in required}
    return SCORING_WEIGHTS.copy()


def _parse_positions_recentes(musique: str, nb: int = 5) -> list[int | None]:
    """
    Retourne les `nb` dernières positions numériques réelles (1-9 ou 10+→10)
    en ignorant les codes spéciaux (D/A/R/N/T) et les suffixes de discipline.
    Le plus récent en premier.
    """
    positions: list[int | None] = []
    i = 0
    while i < len(musique) and len(positions) < nb:
        char = musique[i]
        if char == "(":
            while i < len(musique) and musique[i] != ")":
                i += 1
            i += 1
            continue
        if char.isdigit():
            num = char
            if i + 1 < len(musique) and musique[i + 1].isdigit():
                num = char + musique[i + 1]
                i += 1
            pos = int(num)
            if pos == 0:
                pos = 10  # "0" dans musique = 10e+
            positions.append(pos)
            if i + 1 < len(musique) and musique[i + 1].lower() in ("a", "m", "p", "s"):
                i += 1
        i += 1
    return positions


def score_outsider_signals(
    participant: dict,
    cote_actuelle: float | None,
    cote_initiale: float | None,
    discipline: str = "PLAT",
) -> float:
    """
    Calcule un bonus outsider cumulant 4 critères :

    1. Variation de cote (baisse > 20% = argent informé)          → 0 à +15 pts
    2. Changement de driver/jockey sur un outsider (cote > 10)    → 0 à +12 pts
    3. Progression dans la musique (dernières 5 positions)         → 0 à +12 pts
    4. Ratio victoires ou top3 / courses si sous-évalué            → 0 à +10 pts

    PLAT   : seuil cote > 10, plafond 15 pts (pour ne pas perturber les bons résultats)
    Autres : seuil cote > 6,  plafond 30 pts
    """
    # Seuil et plafond selon la discipline
    seuil_cote = 10.0 if discipline == "PLAT" else 6.0
    plafond = 15.0 if discipline == "PLAT" else 30.0

    # Bonus outsider désactivé pour le PLAT (scoring classique Expert uniquement)
    if discipline == "PLAT":
        return 0.0

    # Garde : seulement pour les outsiders
    if cote_actuelle is None or cote_actuelle <= seuil_cote:
        return 0.0

    bonus = 0.0
    musique = participant.get("musique", "") or ""

    # ── Critère 1 : variation de cote ────────────────────────────────────────
    if cote_initiale is not None and cote_initiale > 0 and cote_actuelle > 0:
        variation = (cote_initiale - cote_actuelle) / cote_initiale  # >0 = baisse
        if variation > 0.20:
            # Baisse > 20% : argent informé
            if variation >= 0.50:
                bonus += 15.0
            elif variation >= 0.40:
                bonus += 12.0
            elif variation >= 0.30:
                bonus += 9.0
            else:
                bonus += 5.0

    # ── Critère 2 : changement de driver/jockey ──────────────────────────────
    driver_change = participant.get("driver_change", False)
    if driver_change and cote_actuelle > 10.0:
        # Signal fort : entraîneur mise sur un meilleur jockey
        if cote_actuelle > 20.0:
            bonus += 12.0
        elif cote_actuelle > 15.0:
            bonus += 10.0
        else:
            bonus += 8.0

    # ── Critère 3 : progression dans la musique ───────────────────────────────
    if musique:
        positions = _parse_positions_recentes(musique, nb=5)
        if len(positions) >= 3:
            # Comparer la première moitié et la deuxième moitié
            mid = len(positions) // 2
            recent_avg = sum(positions[:mid]) / mid          # positions les plus récentes
            older_avg = sum(positions[mid:]) / (len(positions) - mid)  # plus anciennes
            progression = older_avg - recent_avg             # >0 = amélioration
            if progression >= 3.0:
                bonus += 12.0  # Progression nette (ex: 7→4→2)
            elif progression >= 1.5:
                bonus += 7.0
            elif progression >= 0.5:
                bonus += 3.0
        # Bonus additionnel : récente victoire ou place malgré cote haute
        if len(positions) >= 1 and positions[0] <= 3:
            # Dernier résultat = top 3 alors que cote > seuil
            bonus += 2.0

    # ── Critère 4 : ratio victoires/courses (sous-évaluation) ────────────────
    nb_courses = participant.get("nombre_courses", 0) or 0
    nb_victoires = participant.get("nombre_victoires", 0) or 0
    nb_places = participant.get("nombre_places", 0) or 0

    if nb_courses >= 3:
        ratio_win = nb_victoires / nb_courses
        ratio_top3 = (nb_victoires + nb_places) / nb_courses
        # Cheval avec bon ratio mais cote élevée = sous-évalué par le marché
        if ratio_win > 0.15 and cote_actuelle > 8.0:
            bonus += 10.0
        elif ratio_win > 0.10 and cote_actuelle > 8.0:
            bonus += 6.0
        elif ratio_top3 > 0.35 and cote_actuelle > 8.0:
            bonus += 4.0

    return round(min(bonus, plafond), 2)


def _weights_sans_cote(w: dict) -> dict:
    """
    Retourne une copie des poids w sans le critère 'value_cote',
    en redistribuant son poids proportionnellement sur les critères restants.
    Formule : nouveau_poids[k] = ancien_poids[k] / (1 - poids_cote)
    """
    poids_cote = w.get("value_cote", 0.0)
    if poids_cote <= 0.0:
        return w.copy()
    restant = 1.0 - poids_cote
    if restant <= 0.0:
        restant = 1.0
    return {k: (v / restant if k != "value_cote" else 0.0) for k, v in w.items()}


def _compute_score_with_weights(
    w: dict,
    s_forme: float,
    s_cote: float,
    s_jockey: float,
    s_entraineur: float,
    s_distance: float,
    s_terrain: float,
    s_repos: float,
    s_partants: float,
    s_hippodrome: float,
    s_gains: float,
    s_age: float,
    s_corde: float,
    s_regularite: float,
    s_recence: float,
    is_trot: bool,
    is_obstacle: bool,
) -> float:
    """Calcule le score global pondéré pour un jeu de poids donné."""
    if is_trot:
        return round(
            s_forme        * w.get("forme_recente", 0.24)
            + s_cote       * w.get("value_cote",    0.17)
            + s_corde      * w.get("corde",         0.14)
            + s_regularite * w.get("regularite",    0.11)
            + s_gains      * w.get("gains",         0.08)
            + s_recence    * w.get("recence",       0.07)
            + s_entraineur * w.get("entraineur",    0.06)
            + s_distance   * w.get("distance",      0.05)
            + s_age        * w.get("age",           0.04)
            + s_partants   * w.get("partants",      0.04)
            + s_hippodrome * w.get("hippodrome",    0.0),
            2,
        )
    elif is_obstacle:
        return round(
            s_forme        * w.get("forme_recente", 0.30)
            + s_cote       * w.get("value_cote",    0.18)
            + s_jockey     * w.get("jockey",        0.14)
            + s_terrain    * w.get("terrain",       0.12)
            + s_entraineur * w.get("entraineur",    0.08)
            + s_distance   * w.get("distance",      0.07)
            + s_gains      * w.get("gains",         0.05)
            + s_age        * w.get("age",           0.03)
            + s_partants   * w.get("partants",      0.03)
            + s_hippodrome * w.get("hippodrome",    0.0),
            2,
        )
    else:
        return round(
            s_forme        * w.get("forme_recente", 0.28)
            + s_cote       * w.get("value_cote",    0.20)
            + s_jockey     * w.get("jockey",        0.10)
            + s_entraineur * w.get("entraineur",    0.08)
            + s_distance   * w.get("distance",      0.07)
            + s_terrain    * w.get("terrain",       0.06)
            + s_repos      * w.get("repos",         0.05)
            + s_gains      * w.get("gains",         0.07)
            + s_age        * w.get("age",           0.04)
            + s_partants   * w.get("partants",      0.03)
            + s_hippodrome * w.get("hippodrome",    0.02),
            2,
        )


def calculer_scores(
    participants: list[dict],
    distance_course: int,
    terrain: str,
    penetrometre: float | None,
    nombre_partants: int = 0,
    hippodrome: str = "",
    historique_hippodromes: dict | None = None,
    weights: dict | None = None,
    discipline: str = "PLAT",
    db_weights_by_disc: dict | None = None,
    auto_weights_by_disc: dict | None = None,
) -> list[dict]:
    """
    Calcule les scores pour tous les participants d'une course.
    Utilise des poids différenciés selon la discipline.

    Double scoring :
      - score_expert : poids Expert (DB scoring_weights ou config)
      - score_auto   : poids Auto-calibrés (DB calibration_weights) si disponibles
      - score_global : score_auto si calibré, sinon score_expert

    Retourne la liste enrichie avec les scores.
    """
    if not participants:
        return []

    # Poids Expert pour cette discipline
    if db_weights_by_disc is not None:
        w_expert = get_weights_for_discipline(discipline, db_weights_by_disc)
    elif weights is not None:
        w_expert = load_weights_from_config_or_db(weights)
    else:
        w_expert = get_weights_for_discipline(discipline)

    # Poids Auto si disponibles
    norm_disc = _normalize_discipline(discipline)
    w_auto = None
    if auto_weights_by_disc and norm_disc in auto_weights_by_disc:
        w_auto = auto_weights_by_disc[norm_disc]

    hist = historique_hippodromes or {}
    is_trot = _is_trot(discipline)
    is_obstacle = _is_obstacle(discipline)

    all_jockeys = [p.get("jockey", "") for p in participants]
    all_entraineurs = [p.get("entraineur", "") for p in participants]

    # Collecter tous les gains pour la normalisation
    all_gains = [p.get("gains_carriere", 0) or 0 for p in participants]

    scored = []
    for p in participants:
        musique = p.get("musique", "") or ""
        cote = p.get("cote_actuelle")
        nom = p.get("nom", "")
        num_pmu = p.get("num_pmu", 0)
        age = p.get("age", 0) or 0
        gains_carriere = p.get("gains_carriere", 0) or 0
        jours_sortie = p.get("jours_depuis_sortie")  # None si pas disponible dans API

        # Scores communs
        s_forme = score_forme_recente(musique, discipline)
        s_cote = score_cote(cote)
        s_jockey = score_jockey(
            p.get("jockey", ""),
            all_jockeys,
            participants=participants,
            current_horse_musique=musique,
            discipline=discipline,
        )
        s_entraineur = score_entraineur(p.get("entraineur", ""), all_entraineurs)
        s_distance = score_distance(musique, distance_course, discipline)
        s_terrain = score_terrain(musique, terrain, penetrometre, discipline)
        s_repos = score_repos(musique, jours_sortie, discipline)
        s_partants = score_partants(nombre_partants or len(participants))
        s_hippodrome = score_hippodrome(nom, hippodrome, hist)
        s_poids = score_poids(p.get("poids"))
        s_gains = score_gains(gains_carriere, all_gains)
        s_age = score_age(age if age > 0 else None, discipline)

        # Scores spécifiques trot
        s_corde = 50.0
        s_regularite = 50.0
        s_recence = 50.0
        if is_trot:
            s_corde = score_corde(num_pmu, nombre_partants or len(participants))
            s_regularite = score_regularite_trot(musique)
            s_recence = score_recence_trot(musique)

        # ── Calcul du score Expert (poids manuels) ──────────────────────────
        _kwargs = dict(
            s_forme=s_forme, s_cote=s_cote, s_jockey=s_jockey,
            s_entraineur=s_entraineur, s_distance=s_distance,
            s_terrain=s_terrain, s_repos=s_repos, s_partants=s_partants,
            s_hippodrome=s_hippodrome, s_gains=s_gains, s_age=s_age,
            s_corde=s_corde, s_regularite=s_regularite, s_recence=s_recence,
            is_trot=is_trot, is_obstacle=is_obstacle,
        )
        sg_expert = _compute_score_with_weights(w_expert, **_kwargs)

        # ── Calcul du score Auto-calibré (si poids disponibles) ──────────
        if w_auto:
            sg_auto = _compute_score_with_weights(w_auto, **_kwargs)
        else:
            sg_auto = sg_expert  # fallback

        # ── Score principal = Auto si calibré, sinon Expert ──────────────
        score_global = sg_auto if w_auto else sg_expert

        # ── Bonus outsider (4 critères, plafonné 30 pts) ────────────────────
        s_outsider = score_outsider_signals(p, cote, p.get("cote_initiale"), discipline=discipline)
        score_global = round(score_global + s_outsider, 2)
        sg_expert_final = round(sg_expert + s_outsider, 2)
        sg_auto_final = round(sg_auto + s_outsider, 2)

        # ── Score sans cote (redistribution proportionnelle des poids) ─────────
        w_sc = _weights_sans_cote(w_expert)
        sg_sans_cote = _compute_score_with_weights(w_sc, **_kwargs)
        # Pas de bonus outsider (il dépend de la cote)
        score_sans_cote = round(sg_sans_cote, 2)

        is_vb = is_value_bet(cote, score_global)
        confiance = get_confiance(score_global)
        explication = generer_explication(
            nom, score_global, s_forme, s_cote, cote, musique, is_vb, confiance,
            discipline=discipline,
            score_corde=s_corde if is_trot else None,
            score_regularite=s_regularite if is_trot else None,
            age=age if age > 0 else None,
            gains_carriere=gains_carriere,
        )

        scored.append({
            **p,
            "score_global":     score_global,
            "score_forme":      round(s_forme, 2),
            "score_cote":       round(s_cote, 2),
            "score_jockey":     round(s_jockey, 2),
            "score_entraineur": round(s_entraineur, 2),
            "score_distance":   round(s_distance, 2),
            "score_terrain":    round(s_terrain, 2),
            "score_repos":      round(s_repos, 2),
            "score_partants":   round(s_partants, 2),
            "score_hippodrome": round(s_hippodrome, 2),
            "score_poids":      round(s_poids, 2),
            "score_gains":      round(s_gains, 2),
            "score_age":        round(s_age, 2),
            # Critères trot
            "score_corde":      round(s_corde, 2),
            "score_regularite": round(s_regularite, 2),
            "score_recence":    round(s_recence, 2),
            # F4 : bonus outsider
            "score_outsider":   round(s_outsider, 2),
            # F5 : double scoring
            "score_expert":     sg_expert_final,
            "score_auto":       sg_auto_final,
            "score_sans_cote":  score_sans_cote,
            "scoring_mode":     "auto" if w_auto else "expert",
            "is_value_bet":     is_vb,
            "confiance":        confiance,
            "explication":      explication,
        })

    scored.sort(key=lambda x: x["score_global"], reverse=True)
    return scored
