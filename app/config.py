from datetime import datetime
from zoneinfo import ZoneInfo

PMU_BASE_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme"
PMU_PARTICIPANTS_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date}/R{reunion}/C{course}/participants"
PMU_ARRIVEE_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date}/R{reunion}/C{course}/arrivee"

DATABASE_URL = "sqlite+aiosqlite:///./pmu_analyzer.db"

PARIS_TZ = ZoneInfo("Europe/Paris")

def today_str() -> str:
    """Date du jour au format DDMMYYYY pour l'API PMU."""
    return datetime.now(PARIS_TZ).strftime("%d%m%Y")

# Pondérations du moteur de scoring — PLAT (défaut, somme = 1.0)
SCORING_WEIGHTS = {
    "forme_recente": 0.28,
    "value_cote":    0.20,
    "jockey":        0.10,
    "entraineur":    0.08,
    "distance":      0.07,
    "terrain":       0.06,
    "repos":         0.05,
    "gains":         0.07,
    "age":           0.04,
    "partants":      0.03,
    "hippodrome":    0.02,
}

# Pondérations différenciées par discipline (somme = 1.0 pour chaque)
SCORING_WEIGHTS_DISCIPLINE = {
    "PLAT": {
        "forme_recente": 0.28,
        "value_cote":    0.20,
        "jockey":        0.10,
        "entraineur":    0.08,
        "distance":      0.07,
        "terrain":       0.06,
        "repos":         0.05,
        "gains":         0.07,
        "age":           0.04,
        "partants":      0.03,
        "hippodrome":    0.02,
    },
    "TROT_ATTELE": {
        "forme_recente": 0.24,
        "value_cote":    0.17,
        "corde":         0.14,
        "regularite":    0.11,
        "gains":         0.08,
        "recence":       0.07,
        "entraineur":    0.06,
        "distance":      0.05,
        "age":           0.04,
        "partants":      0.04,
    },
    "TROT_MONTE": {
        "forme_recente": 0.25,
        "value_cote":    0.17,
        "corde":         0.12,
        "regularite":    0.10,
        "gains":         0.08,
        "recence":       0.07,
        "jockey":        0.07,
        "entraineur":    0.06,
        "distance":      0.05,
        "age":           0.03,
    },
    "HAIE": {
        "forme_recente": 0.30,
        "value_cote":    0.18,
        "jockey":        0.14,
        "terrain":       0.12,
        "entraineur":    0.08,
        "distance":      0.07,
        "gains":         0.05,
        "age":           0.03,
        "partants":      0.03,
    },
    "STEEPLE": {
        "forme_recente": 0.30,
        "value_cote":    0.18,
        "jockey":        0.14,
        "terrain":       0.12,
        "entraineur":    0.08,
        "distance":      0.07,
        "gains":         0.05,
        "age":           0.03,
        "partants":      0.03,
    },
    "CROSS": {
        "forme_recente": 0.30,
        "value_cote":    0.18,
        "jockey":        0.14,
        "terrain":       0.12,
        "entraineur":    0.08,
        "distance":      0.07,
        "gains":         0.05,
        "age":           0.03,
        "partants":      0.03,
    },
}

# Seuil value bet : cote réelle >= facteur * probabilité implicite estimée
VALUE_BET_FACTOR = 1.30
VALUE_BET_MIN_SCORE = 50
