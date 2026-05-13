import os
from datetime import datetime
from zoneinfo import ZoneInfo

PMU_BASE_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme"
PMU_PARTICIPANTS_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date}/R{reunion}/C{course}/participants"
PMU_ARRIVEE_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date}/R{reunion}/C{course}/arrivee"

# DATABASE_URL format attendu: postgresql+asyncpg://user:password@host:port/dbname
# Neon/Supabase fournissent une URL postgres:// ou postgresql:// — conversion automatique ci-dessous.
# Sans DATABASE_URL dans l'environnement, fallback SQLite local.
_raw_db_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./pmu_analyzer.db")
# Retirer ?sslmode=require (asyncpg gère le SSL via connect_args, pas via URL)
if "?" in _raw_db_url:
    _raw_db_url = _raw_db_url.split("?")[0]
if _raw_db_url.startswith("postgres://"):
    DATABASE_URL = _raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _raw_db_url.startswith("postgresql://") and "+asyncpg" not in _raw_db_url:
    DATABASE_URL = _raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = _raw_db_url

PARIS_TZ = ZoneInfo("Europe/Paris")

def today_str() -> str:
    """Date du jour au format DDMMYYYY pour l'API PMU."""
    return datetime.now(PARIS_TZ).strftime("%d%m%Y")

# Pondérations différenciées par discipline (somme = 1.0 pour chaque)
SCORING_WEIGHTS_DISCIPLINE = {
    "PLAT": {
        "forme_recente": 0.31,
        "value_cote":    0.12,
        "jockey":        0.11,
        "entraineur":    0.06,
        "distance":      0.07,
        "terrain":       0.08,
        "repos":         0.06,
        "gains":         0.12,
        "age":           0.04,
        "partants":      0.01,
        "hippodrome":    0.02,
    },
    "TROT_ATTELE": {
        "forme_recente": 0.22,
        "value_cote":    0.20,
        "corde":         0.10,
        "regularite":    0.07,
        "gains":         0.08,
        "recence":       0.07,
        "entraineur":    0.03,
        "distance":      0.10,
        "age":           0.05,
        "partants":      0.08,
    },
    "TROT_MONTE": {
        "forme_recente": 0.25,
        "value_cote":    0.18,
        "corde":         0.08,
        "regularite":    0.07,
        "gains":         0.10,
        "recence":       0.06,
        "jockey":        0.08,
        "entraineur":    0.06,
        "distance":      0.08,
        "age":           0.04,
    },
    "HAIE": {
        "forme_recente": 0.30,
        "value_cote":    0.14,
        "jockey":        0.15,
        "terrain":       0.15,
        "entraineur":    0.08,
        "distance":      0.07,
        "gains":         0.05,
        "age":           0.03,
        "partants":      0.03,
    },
    "STEEPLE": {
        "forme_recente": 0.30,
        "value_cote":    0.14,
        "jockey":        0.15,
        "terrain":       0.15,
        "entraineur":    0.08,
        "distance":      0.07,
        "gains":         0.05,
        "age":           0.03,
        "partants":      0.03,
    },
    "CROSS": {
        "forme_recente": 0.30,
        "value_cote":    0.14,
        "jockey":        0.15,
        "terrain":       0.15,
        "entraineur":    0.08,
        "distance":      0.07,
        "gains":         0.05,
        "age":           0.03,
        "partants":      0.03,
    },
}

# Rétro-compatibilité : référence aux poids PLAT
SCORING_WEIGHTS = SCORING_WEIGHTS_DISCIPLINE['PLAT']

# Seuil value bet : cote réelle >= facteur * probabilité implicite estimée
# Seuils globaux (rétro-compatibilité / fallback)
VALUE_BET_FACTOR = 1.38
VALUE_BET_MIN_SCORE = 60

# Seuils value bet par discipline (section 5.2)
VALUE_BET_THRESHOLDS_DISCIPLINE = {
    "PLAT":        {"min_score": 62, "factor": 1.45},
    "TROT_ATTELE": {"min_score": 60, "factor": 1.30},
    "TROT_MONTE":  {"min_score": 58, "factor": 1.32},
    "HAIE":        {"min_score": 62, "factor": 1.40},
    "STEEPLE":     {"min_score": 62, "factor": 1.40},
    "CROSS":       {"min_score": 62, "factor": 1.40},
}
